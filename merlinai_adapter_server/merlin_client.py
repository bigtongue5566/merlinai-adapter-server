import datetime
import http.client
import json
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Set

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import token_manager
from .config import MERLIN_API_URL, MERLIN_ORIGIN, MERLIN_PATH, MERLIN_REQUEST_TIMEOUT_SECONDS, MERLIN_VERSION, TOOL_CALL_MODE, SETTINGS
from .emulated_tools import (
    EmulatedToolPolicy, build_emulated_messages, parse_emulated_response, resolve_emulated_tool_policy,
)
from .emulated_recovery import RecoveryPolicy
from .request_budget import ManagedStream, RequestBudget, active_deadline
from .response_usage import sum_usage, token_counts
from .logging_config import log_debug_payload, logger
from .models_catalog import resolve_max_tokens
from .merlin_sse import iter_merlin_sse
from .native_protocol import normalize_native_tool_calls, resolve_native_tool_policy, validate_native_tool_choice
from .openai_response_builder import build_native_openai_response, build_stream_chunk
from .protocol_constants import STRUCTURED_PAYLOAD_END, STRUCTURED_PAYLOAD_START
from .request_logging import clear_request_log_context, set_attempt_context, set_request_log_context
from .schemas import OpenAIRequest, model_dump_compat


@dataclass(frozen=True)
class MerlinStreamEvent:
    content_delta: str
    tool_calls: List[Dict[str, Any]]
    raw_event: Dict[str, Any]
    raw_chunk: str
    usage: Optional[Dict[str, Any]] = None
    reasoning_delta: str = ""


class MerlinGateway:
    # Low-level Merlin transport: payload shaping, auth headers, HTTP call, and SSE parsing.
    def build_payload(
        self,
        *,
        model: str,
        user_message: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Any]] = None,
        tool_choice: Optional[Any] = None,
        max_tokens: Optional[int] = None,
        stream_options: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        if user_message is not None:
            raise ValueError(
                "The legacy user_message payload is retired; provide native extension messages instead"
            )
        if messages is not None:
            choice_mode = validate_native_tool_choice(tool_choice)
            params: Dict[str, Any] = {
                "tools": [] if choice_mode == "none" else [model_dump_compat(tool) for tool in (tools or [])],
                "max_tokens": resolve_max_tokens(model, max_tokens),
            }
            # Merlin's Gemini 3.8 route rejects an empty tool array with
            # INTERNAL_SERVER_ERROR. Omission works; real native tools stay intact.
            if model == "gemini-3.8-flash" and not params["tools"]:
                del params["tools"]
            # The extension currently emits usage for every stream. The
            # OpenAI-facing stream_options flag is handled locally so that an
            # unsupported provider parameter is never sent upstream.
            return {
                "model": model,
                "messages": messages,
                "params": params,
                # The extension endpoint expects this session capability flag
                # even when no extension/MCP tools are supplied. It does not
                # enable or inject any tool definitions by itself.
                "metadata": {"isMCPEnabled": True},
            }
        raise ValueError(
            "The legacy user_message payload is retired; provide native extension messages instead"
        )

    def send_request(
        self,
        merlin_payload: Dict[str, Any],
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], List[str], Optional[Dict[str, Any]]]:
        conn, res = self.open_request(merlin_payload)
        try:
            return self._read_event_stream(res, allowed_tool_names)
        finally:
            conn.close()

    def open_request(
        self,
        merlin_payload: Dict[str, Any],
    ) -> tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
        deadline = active_deadline.get()
        timeout = MERLIN_REQUEST_TIMEOUT_SECONDS
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise HTTPException(504, "Merlin completion exceeded its overall time limit")
        conn = http.client.HTTPSConnection(MERLIN_API_URL, timeout=timeout)
        try:
            return conn, self._open_response(conn, merlin_payload)
        except Exception:
            conn.close()
            raise

    def _open_response(
        self,
        conn: http.client.HTTPSConnection,
        merlin_payload: Dict[str, Any],
    ) -> http.client.HTTPResponse:
        headers = self._get_headers()
        deadline = active_deadline.get()
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPException(504, "Merlin completion exceeded its overall time limit")
            conn.timeout = min(MERLIN_REQUEST_TIMEOUT_SECONDS, remaining)
        log_debug_payload(
            "merlin_request_start",
            {
                "host": MERLIN_API_URL,
                "path": MERLIN_PATH,
                "timeout_seconds": MERLIN_REQUEST_TIMEOUT_SECONDS,
            },
        )
        try:
            conn.request("POST", MERLIN_PATH, json.dumps(merlin_payload), headers)
            res = conn.getresponse()
        except socket.timeout as exc:
            raise HTTPException(status_code=504, detail="Merlin request timed out") from exc
        except OSError as exc:
            raise HTTPException(status_code=502, detail="Merlin request failed") from exc

        if res.status != 200:
            error_body = res.read().decode("utf-8", errors="ignore")
            log_debug_payload("merlin_non_stream_error", {"status": res.status, "body": error_body})
            raise HTTPException(status_code=res.status, detail=error_body)

        return res

    def _get_headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {token_manager.get_access_token()}",
            "content-type": "application/json",
            "origin": MERLIN_ORIGIN,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
            "x-merlin-version": MERLIN_VERSION,
        }

    def _read_event_stream(
        self,
        res: http.client.HTTPResponse,
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], List[str], Optional[Dict[str, Any]]]:
        full_content = ""
        response_tool_calls: List[Dict[str, Any]] = []
        raw_events: List[Dict[str, Any]] = []
        raw_chunks: List[str] = []
        usage: Optional[Dict[str, Any]] = None

        for stream_event in self.iter_event_stream(res, allowed_tool_names):
            full_content += stream_event.content_delta
            response_tool_calls.extend(stream_event.tool_calls)
            raw_events.append(stream_event.raw_event)
            raw_chunks.append(stream_event.raw_chunk)
            if stream_event.usage is not None:
                usage = stream_event.usage

        return full_content, response_tool_calls, raw_events, raw_chunks, usage

    def iter_event_stream(
        self,
        res: http.client.HTTPResponse,
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> Iterator[MerlinStreamEvent]:
        for event in iter_merlin_sse(res):
            if event.name == "usage":
                yield MerlinStreamEvent(
                    content_delta="",
                    tool_calls=[],
                    raw_event={"usage": event.data},
                    raw_chunk=event.raw,
                    usage=event.data if isinstance(event.data, dict) else None,
                )
                continue
            if event.name == "tool_calls":
                calls = normalize_native_tool_calls(event.data, allowed_tool_names)
                yield MerlinStreamEvent(
                    content_delta="",
                    tool_calls=calls,
                    raw_event={"tool_calls": calls},
                    raw_chunk=event.raw,
                )
                continue
            if event.name != "message" or not isinstance(event.data, dict):
                continue
            value = event.data
            inner_data = value.get("data") if isinstance(value.get("data"), dict) else {}
            text = inner_data.get("text") if isinstance(inner_data.get("text"), str) else ""
            content = inner_data.get("content") if isinstance(inner_data.get("content"), str) else ""
            if not content and isinstance(value.get("content"), str):
                content = value["content"]
            reasoning = inner_data.get("reasoning") if isinstance(inner_data.get("reasoning"), str) else ""
            calls: List[Dict[str, Any]] = []
            for source in (inner_data, value):
                for key in ("toolCalls", "tool_calls"):
                    if key in source:
                        calls.extend(normalize_native_tool_calls(source[key], allowed_tool_names))
            yield MerlinStreamEvent(
                content_delta=text or content,
                tool_calls=calls,
                raw_event=value,
                raw_chunk=event.raw,
                reasoning_delta=reasoning,
            )


class ChatCompletionContext(BaseModel):
    # Snapshot the request fields needed by the native extension transport.
    model_config = ConfigDict(frozen=True)

    model: str
    tools: List[Any] = Field(default_factory=list)
    tool_choice: Any
    allowed_tool_names: Set[str] = Field(default_factory=set)
    max_tokens: Optional[int] = None
    stream_options: Dict[str, bool] = Field(default_factory=dict)
    emulation_policy: Optional[EmulatedToolPolicy] = None

    @classmethod
    def from_request(cls, request: OpenAIRequest, tool_call_mode: str = "native") -> "ChatCompletionContext":
        policy = (resolve_emulated_tool_policy(request) if tool_call_mode == "emulated"
                  else resolve_native_tool_policy(request))
        return cls(
            model=request.model,
            tools=policy.tools,
            tool_choice=request.tool_choice,
            allowed_tool_names=policy.allowed_tool_names,
            max_tokens=resolve_max_tokens(request.model, request.max_tokens),
            stream_options=dict(request.stream_options or {}),
            emulation_policy=policy if tool_call_mode == "emulated" else None,
        )


class MerlinResponseEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    tool_calls: List[Dict[str, Any]]
    raw_events: List[Dict[str, Any]]
    raw_chunks: List[str]
    usage: Optional[Dict[str, Any]] = None


class ChatCompletionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    response_payload: Dict[str, Any]
    content: str
    tool_calls: List[Dict[str, Any]]
    raw_events: List[Dict[str, Any]]


class MerlinOpenAIClient:
    # High-level OpenAI-compatible client built on the native extension gateway.
    def __init__(self, gateway: MerlinGateway, *, tool_call_mode: str = "native") -> None:
        if tool_call_mode not in {"native", "emulated"}:
            raise ValueError("tool_call_mode must be native or emulated")
        self._gateway = gateway
        self.tool_call_mode = tool_call_mode
        self.recovery_policy = RecoveryPolicy(
            enabled=bool(SETTINGS.emulated_correction_attempts),
        )

    def execute_chat_completion(
        self,
        request: OpenAIRequest,
    ) -> ChatCompletionResult:
        try:
            context = ChatCompletionContext.from_request(request, self.tool_call_mode)
            initial_response = self._send_request(request, context, attempt="initial")
            full_content = initial_response.content
            response_tool_calls = initial_response.tool_calls
            raw_events = initial_response.raw_events

            response_payload = build_native_openai_response(
                request, full_content, response_tool_calls, initial_response.usage
            )
            return ChatCompletionResult(
                response_payload=response_payload,
                content=full_content,
                tool_calls=response_tool_calls,
                raw_events=raw_events,
            )
        finally:
            set_attempt_context(None)

    def open_chat_completion_stream(
        self,
        request: OpenAIRequest,
        request_id: str | None = None,
    ) -> Iterator[str]:
        if request_id:
            set_request_log_context(request_id=request_id, attempt="initial")
        else:
            set_attempt_context("initial")

        conn: http.client.HTTPSConnection | None = None
        try:
            context = ChatCompletionContext.from_request(request, self.tool_call_mode)
            merlin_payload = self._build_merlin_payload(request, context)
            budget = RequestBudget(SETTINGS.completion_timeout_seconds, SETTINGS.completion_max_bytes)
            with budget.opening():
                conn, res = self._gateway.open_request(merlin_payload)
            iterator = self._iter_openai_stream_chunks(
                request=request,
                context=context,
                conn=conn,
                res=res,
                request_id=request_id,
                payload=merlin_payload,
                budget=budget,
            )
            return ManagedStream(iterator, conn, budget)
        except Exception:
            if conn is not None:
                conn.close()
            raise
        finally:
            if request_id:
                clear_request_log_context()
            else:
                set_attempt_context(None)

    def _iter_openai_stream_chunks(
        self,
        *,
        request: OpenAIRequest,
        context: ChatCompletionContext,
        conn: http.client.HTTPSConnection,
        res: http.client.HTTPResponse,
        payload: Dict[str, Any],
        budget: RequestBudget,
        request_id: str | None = None,
    ) -> Iterator[str]:
        if request_id:
            set_request_log_context(request_id=request_id, attempt="initial")
        else:
            set_attempt_context("initial")

        response_id = f"chatcmpl-{uuid.uuid4()}"
        created = int(datetime.datetime.now().timestamp())
        full_content = ""
        content_parts: List[str] = []
        response_tool_calls: List[Dict[str, Any]] = []
        raw_events: List[Dict[str, Any]] = []
        raw_chunks: List[str] = []
        usage: Optional[Dict[str, Any]] = None
        request_log_context = {"request_id": request_id} if request_id else {}
        attempt_log_context = {**request_log_context, "attempt": "initial"}

        try:
            yield build_stream_chunk(
                response_id=response_id,
                created=created,
                model=request.model,
                delta={"role": "assistant"},
                finish_reason=None,
            )

            upstream_names = set() if context.emulation_policy else context.allowed_tool_names
            for stream_event in self._bounded_events(conn, res, upstream_names, budget):
                raw_events.append(self._event_summary(stream_event))
                tool_start_index = len(response_tool_calls)
                response_tool_calls.extend(stream_event.tool_calls)
                if stream_event.content_delta:
                    content_parts.append(stream_event.content_delta)
                usage = stream_event.usage or usage

                if context.emulation_policy and context.tools:
                    # Never expose partial protocol JSON or executable calls before
                    # the upstream has completed and the whole response is valid.
                    continue

                if stream_event.content_delta:
                    yield build_stream_chunk(
                        response_id=response_id,
                        created=created,
                        model=request.model,
                        delta={"content": stream_event.content_delta},
                        finish_reason=None,
                    )
                if stream_event.tool_calls:
                    for index, tool_call in enumerate(stream_event.tool_calls, start=tool_start_index):
                        function = tool_call.get("function") if isinstance(tool_call, dict) else {}
                        function = function if isinstance(function, dict) else {}
                        yield build_stream_chunk(
                            response_id=response_id,
                            created=created,
                            model=request.model,
                            delta={
                                "tool_calls": [{
                                    "index": index,
                                    "id": tool_call.get("id"),
                                    "type": tool_call.get("type", "function"),
                                    "function": {
                                        "name": function.get("name", ""),
                                        "arguments": function.get("arguments", "{}"),
                                    },
                                }]},
                            finish_reason=None,
                        )

            full_content = "".join(content_parts)
            content_parts.clear()
            if context.emulation_policy and context.tools:
                conn.close()
                completed = self._resolve_emulated(
                    MerlinResponseEnvelope(content=full_content, tool_calls=[], raw_events=raw_events,
                                           raw_chunks=[], usage=usage),
                    context, payload, budget,
                )
                full_content, response_tool_calls, usage = completed.content, completed.tool_calls, completed.usage
                raw_events = completed.raw_events
                if response_tool_calls:
                    yield build_stream_chunk(
                        response_id=response_id, created=created, model=request.model,
                        delta={"tool_calls": [dict(call, index=index)
                                              for index, call in enumerate(response_tool_calls)]},
                        finish_reason=None,
                    )
                elif full_content:
                    yield build_stream_chunk(
                        response_id=response_id, created=created, model=request.model,
                        delta={"content": full_content}, finish_reason=None,
                    )

            log_debug_payload(
                "merlin_raw_response",
                {
                    "transport": "extension",
                    "event_count": len(raw_events),
                    "raw_event_chunks": raw_chunks,
                    "raw_events": raw_events,
                    "assembled_content": full_content,
                    "tool_calls": response_tool_calls,
                    **attempt_log_context,
                },
            )
            log_debug_payload(
                "merlin_attempt_summary",
                {
                    "transport": "extension",
                    "event_count": len(raw_events),
                    "assembled_content": full_content,
                    "tool_call_count": len(response_tool_calls),
                    **attempt_log_context,
                },
            )
            set_attempt_context(None)
            log_debug_payload(
                "streamed_openai_response_summary",
                {
                    "response_id": response_id,
                    "finish_reason": "tool_calls" if response_tool_calls else "stop",
                    "tool_call_names": [
                        tool_call.get("function", {}).get("name")
                        for tool_call in response_tool_calls
                        if isinstance(tool_call, dict)
                    ],
                    "content_preview": full_content[:300],
                    "upstream_stream": True,
                    **request_log_context,
                },
            )

            yield build_stream_chunk(
                response_id=response_id,
                created=created,
                model=request.model,
                delta={},
                finish_reason="tool_calls" if response_tool_calls else "stop",
            )
            if context.stream_options.get("include_usage") and usage is not None:
                yield build_stream_chunk(
                    response_id=response_id,
                    created=created,
                    model=request.model,
                    delta={},
                    finish_reason=None,
                    usage=usage,
                )
            yield "data: [DONE]\n\n"
        except HTTPException as exc:
            # Headers have already been sent; report an error event, never a
            # successful finish_reason or [DONE] for an incomplete response.
            yield "event: error\ndata: " + json.dumps({"error": {
                "message": str(exc.detail), "type": "upstream_error", "code": exc.status_code,
            }}) + "\n\n"
        finally:
            conn.close()
            if request_id:
                clear_request_log_context()
            else:
                set_attempt_context(None)

    @staticmethod
    def _event_summary(event: MerlinStreamEvent) -> Dict[str, Any]:
        # Do not retain every raw event plus a second copy of its SSE JSON.
        # In particular, reasoning text does not belong in ordinary logs.
        return {"content_chars": len(event.content_delta), "reasoning_chars": len(event.reasoning_delta),
                "tool_call_count": len(event.tool_calls)}

    def _bounded_events(
        self, conn: http.client.HTTPSConnection, res: http.client.HTTPResponse,
        names: Set[str], budget: RequestBudget,
    ) -> Iterator[MerlinStreamEvent]:
        with budget.reading(conn, res):
            for event in self._gateway.iter_event_stream(res, names):
                budget.observe(event.raw_chunk)
                yield event

    def _read_response(
        self, payload: Dict[str, Any], context: ChatCompletionContext, budget: RequestBudget,
    ) -> MerlinResponseEnvelope:
        conn = None
        try:
            with budget.opening():
                conn, res = self._gateway.open_request(payload)
            parts, calls, summaries = [], [], []
            usage = None
            names = set() if context.emulation_policy else context.allowed_tool_names
            for event in self._bounded_events(conn, res, names, budget):
                parts.append(event.content_delta)
                calls.extend(event.tool_calls)
                summaries.append(self._event_summary(event))
                if event.usage is not None:
                    usage = event.usage
            return MerlinResponseEnvelope(content="".join(parts), tool_calls=calls,
                                          raw_events=summaries, raw_chunks=[], usage=usage)
        finally:
            if conn is not None:
                conn.close()

    def _resolve_emulated(
        self, response: MerlinResponseEnvelope, context: ChatCompletionContext,
        payload: Dict[str, Any], budget: RequestBudget,
    ) -> MerlinResponseEnvelope:
        """Shared atomic validation/recovery for both HTTP response modes."""
        attempts = [response.usage]
        summaries = list(response.raw_events)
        for attempt in range(2):
            try:
                content, calls = self._parse_emulated_response(response.content, context, response.usage)
                return MerlinResponseEnvelope(content=content, tool_calls=calls, raw_events=summaries,
                                              raw_chunks=[], usage=sum_usage(attempts))
            except HTTPException as exc:
                correction = (self.recovery_policy.correction_payload(payload, response.content, response.usage, exc)
                              if attempt == 0 else None)
                if correction is None:
                    raise
                budget.remaining()
                logger.info("emulated_protocol_correction model={} code={} max_tokens={}",
                            context.model, exc.code, correction["params"]["max_tokens"])
                set_attempt_context("protocol_correction")
                response = self._read_response(correction, context, budget)
                # Validate against this attempt's ceiling, not the initial one.
                context = context.model_copy(update={"max_tokens": correction["params"]["max_tokens"]})
                attempts.append(response.usage)
                summaries.extend(response.raw_events)
        raise AssertionError("unreachable")

    def _send_request(
        self, request: OpenAIRequest, context: ChatCompletionContext, *, attempt: str,
    ) -> MerlinResponseEnvelope:
        set_attempt_context(attempt)
        payload = self._build_merlin_payload(request, context)
        budget = RequestBudget(SETTINGS.completion_timeout_seconds, SETTINGS.completion_max_bytes)
        response = self._read_response(payload, context, budget)
        if context.emulation_policy and context.tools:
            response = self._resolve_emulated(response, context, payload, budget)
        log_debug_payload("merlin_attempt_summary", {
            "transport": "extension", "event_count": len(response.raw_events),
            "content_chars": len(response.content), "tool_call_count": len(response.tool_calls),
            "usage": response.usage,
        })
        return response

    def _parse_emulated_response(
        self, content: str, context: ChatCompletionContext, usage: Optional[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        tokens = token_counts(usage)
        output_tokens = tokens.get("output")
        reasoning_tokens = tokens.get("reasoning")
        max_tokens = resolve_max_tokens(context.model, context.max_tokens)
        limit_reached = type(output_tokens) is int and output_tokens >= max_tokens
        try:
            return parse_emulated_response(content, context.emulation_policy,
                                           output_limit_reached=limit_reached)
        except HTTPException as exc:
            detail = exc.detail
            incomplete = not content.strip() or exc.detail in {
                "Emulated tool response is missing its complete payload envelope",
                "Emulated tool response contains invalid JSON",
            }
            if limit_reached and incomplete:
                detail = ("Merlin output token budget exhausted before a complete emulated response "
                          f"(max_tokens={max_tokens}, output_tokens={output_tokens}, "
                          f"reasoning_tokens={reasoning_tokens if type(reasoning_tokens) is int else 'unknown'}); "
                          "no tool calls were released")
            # Keep failures diagnosable without logging prompts, code or tool results.
            logger.warning(
                "emulated_response_invalid model={} chars={} has_start={} has_end={} "
                "max_tokens={} output_tokens={} reasoning_tokens={} error={}",
                context.model, len(content), STRUCTURED_PAYLOAD_START in content,
                STRUCTURED_PAYLOAD_END in content, max_tokens, output_tokens, reasoning_tokens, detail,
            )
            if limit_reached and incomplete:
                raise HTTPException(502, detail) from exc
            raise

    def _build_merlin_payload(
        self,
        request: OpenAIRequest,
        context: ChatCompletionContext,
    ) -> Dict[str, Any]:
        messages = []
        source_messages = (build_emulated_messages(request, context.emulation_policy)
                           if context.emulation_policy else request.messages)
        for message in source_messages:
            payload = model_dump_compat(message)
            # Merlin's extension client represents user and tool text as
            # content parts. Keep assistant/system strings intact, matching
            # the observed native request contract.
            if (
                isinstance(payload, dict)
                and payload.get("role") in {"user", "tool"}
                and isinstance(payload.get("content"), str)
            ):
                payload["content"] = [{"type": "text", "text": payload["content"]}]
            messages.append(payload)
        merlin_payload = self._gateway.build_payload(
            model=context.model,
            messages=messages,
            tools=[] if context.emulation_policy else context.tools,
            tool_choice="none" if context.emulation_policy else context.tool_choice,
            max_tokens=context.max_tokens,
            stream_options=context.stream_options,
        )
        log_debug_payload(
            "outgoing_merlin_payload",
            {
                "transport": "extension",
                "tool_call_mode": self.tool_call_mode,
                "payload": model_dump_compat(merlin_payload),
            },
        )
        return merlin_payload


merlin_gateway = MerlinGateway()
merlin_openai_client = MerlinOpenAIClient(merlin_gateway, tool_call_mode=TOOL_CALL_MODE)
