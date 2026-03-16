import datetime
import http.client
import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

from .auth import token_manager
from .config import MERLIN_API_URL, MERLIN_PATH, MERLIN_REQUEST_TIMEOUT_SECONDS, MERLIN_VERSION
from .logging_config import log_debug_payload
from .message_utils import build_non_tool_prompt, last_message_is_tool_output
from .openai_response_builder import build_openai_response
from .request_logging import set_attempt_context
from .schemas import OpenAIRequest
from .tool_payload_parser import extract_tool_calls
from .tool_prompt import (
    build_tool_prompt,
    get_allowed_tool_names,
    is_agent_like_tool_context,
    normalize_tool_choice,
    should_force_tool_json,
    should_retry_tool_response,
)

class MerlinGateway:
    # Low-level Merlin transport: payload shaping, auth headers, HTTP call, and SSE parsing.
    def build_payload(
        self,
        *,
        model: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> Dict[str, Any]:
        return {
            "attachments": [],
            "chatId": str(uuid.uuid4()),
            "language": "AUTO",
            "message": {
                "childId": str(uuid.uuid4()),
                "content": user_message,
                "context": "",
                "id": str(uuid.uuid4()),
                "parentId": "root",
            },
            "mode": "UNIFIED_CHAT",
            "model": model,
            "metadata": {
                "deepResearch": False,
                "merlinMagic": False,
                "noTask": True,
                "proFinderMode": False,
                "mcpConfig": {"isEnabled": False},
                "isWebpageChat": False,
                "webAccess": True,
            },
        }

    def send_request(
        self,
        merlin_payload: Dict[str, Any],
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        conn = http.client.HTTPSConnection(MERLIN_API_URL, timeout=MERLIN_REQUEST_TIMEOUT_SECONDS)
        try:
            headers = self._get_headers()
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

            return self._read_event_stream(res, allowed_tool_names)
        finally:
            conn.close()

    def _get_headers(self) -> Dict[str, str]:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+08:00[Asia/Taipei]"
        return {
            "accept": "text/event-stream",
            "authorization": f"Bearer {token_manager.get_access_token()}",
            "content-type": "application/json",
            "origin": "https://extension.getmerlin.in",
            "referer": "https://extension.getmerlin.in/",
            "user-agent": "Mozilla/5.0",
            "x-merlin-version": MERLIN_VERSION,
            "x-request-timestamp": timestamp,
        }

    def _read_event_stream(
        self,
        res: http.client.HTTPResponse,
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        full_content = ""
        response_tool_calls: List[Dict[str, Any]] = []
        raw_events: List[Dict[str, Any]] = []
        raw_chunks: List[str] = []

        while True:
            try:
                line = res.readline()
            except socket.timeout as exc:
                raise HTTPException(status_code=504, detail="Merlin event stream timed out") from exc
            except OSError as exc:
                raise HTTPException(status_code=502, detail="Merlin event stream failed") from exc
            if not line:
                break

            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str.startswith("data:"):
                continue

            data_str = line_str[5:].strip()
            if not data_str:
                continue
            if data_str == "[DONE]":
                break
            raw_chunks.append(data_str)

            try:
                merlin_data = json.loads(data_str)
                raw_events.append(merlin_data)
                inner_data = merlin_data.get("data", {})
                text = inner_data.get("text", "")
                content = inner_data.get("content", "")
                full_content += text or content
                response_tool_calls.extend(extract_tool_calls(inner_data, allowed_tool_names))
            except json.JSONDecodeError:
                continue

        return full_content, response_tool_calls, raw_events, raw_chunks


@dataclass(frozen=True)
class ChatCompletionContext:
    # Snapshot only the request fields needed by the Merlin/OpenAI orchestration path.
    model: str
    tools: List[Dict[str, Any]]
    tool_choice: Any
    allowed_tool_names: Set[str]

    @classmethod
    def from_request(cls, request: OpenAIRequest) -> "ChatCompletionContext":
        return cls(
            model=request.model,
            tools=list(request.tools or []),
            tool_choice=request.tool_choice,
            allowed_tool_names=get_allowed_tool_names(request),
        )


@dataclass(frozen=True)
class MerlinResponseEnvelope:
    content: str
    tool_calls: List[Dict[str, Any]]
    raw_events: List[Dict[str, Any]]
    raw_chunks: List[str]


@dataclass(frozen=True)
class ChatCompletionResult:
    response_payload: Dict[str, Any]
    content: str
    tool_calls: List[Dict[str, Any]]
    raw_events: List[Dict[str, Any]]


class MerlinOpenAIClient:
    # High-level OpenAI-compatible client built on top of the raw Merlin gateway.
    def __init__(self, gateway: MerlinGateway) -> None:
        self._gateway = gateway

    def execute_chat_completion(
        self,
        request: OpenAIRequest,
    ) -> ChatCompletionResult:
        context = ChatCompletionContext.from_request(request)
        initial_response = self._send_request(
            request,
            context,
            attempt="initial",
            prompt_mode="strict",
        )
        full_content = initial_response.content
        response_tool_calls = initial_response.tool_calls
        raw_events = initial_response.raw_events

        try:
            response_payload = build_openai_response(request, full_content, response_tool_calls)
        except HTTPException as exc:
            if not should_retry_tool_response(request, exc):
                raise

            # Retry once with a repair prompt when Merlin returns malformed tool payloads.
            previous_content = full_content
            repaired_response = self._send_request(
                request,
                context,
                attempt="repair",
                prompt_mode="repair",
                previous_response=previous_content,
            )
            full_content = repaired_response.content
            response_tool_calls = repaired_response.tool_calls
            raw_events = raw_events + repaired_response.raw_events
            response_payload = build_openai_response(request, full_content, response_tool_calls)

        # In multi-step tool workflows, give Merlin one more chance to emit tool calls instead of plain text.
        if self._should_retry_agentic_tool_call(request, response_payload):
            repaired_response = self._send_request(
                request,
                context,
                attempt="agentic_repair",
                prompt_mode="strict",
                previous_response=full_content,
            )
            repaired_content = repaired_response.content
            repaired_tool_calls = repaired_response.tool_calls
            candidate_response = build_openai_response(request, repaired_content, repaired_tool_calls)
            if candidate_response["choices"][0]["finish_reason"] == "tool_calls":
                full_content = repaired_content
                response_tool_calls = repaired_tool_calls
                raw_events = raw_events + repaired_response.raw_events
                response_payload = candidate_response
        set_attempt_context(None)

        return ChatCompletionResult(
            response_payload=response_payload,
            content=full_content,
            tool_calls=response_tool_calls,
            raw_events=raw_events,
        )

    def _send_request(
        self,
        request: OpenAIRequest,
        context: ChatCompletionContext,
        *,
        attempt: str,
        prompt_mode: str,
        previous_response: str | None = None,
    ) -> MerlinResponseEnvelope:
        set_attempt_context(attempt)
        merlin_payload = self._build_merlin_payload(
            request,
            context,
            prompt_mode=prompt_mode,
            previous_response=previous_response,
        )
        content, tool_calls, raw_events, raw_chunks = self._gateway.send_request(merlin_payload, context.allowed_tool_names)
        log_debug_payload(
            "merlin_raw_response",
            {
                "prompt_mode": prompt_mode,
                "event_count": len(raw_events),
                "raw_event_chunks": raw_chunks,
                "raw_events": raw_events,
                "assembled_content": content,
                "tool_calls": tool_calls,
            },
        )
        log_debug_payload(
            "merlin_attempt_summary",
            {
                "prompt_mode": prompt_mode,
                "previous_response": previous_response,
                "event_count": len(raw_events),
                "assembled_content": content,
                "tool_call_count": len(tool_calls),
            },
        )
        return MerlinResponseEnvelope(content=content, tool_calls=tool_calls, raw_events=raw_events, raw_chunks=raw_chunks)

    def _build_merlin_payload(
        self,
        request: OpenAIRequest,
        context: ChatCompletionContext,
        *,
        prompt_mode: str,
        previous_response: str | None = None,
    ) -> Dict[str, Any]:
        if should_force_tool_json(request):
            user_message, tool_prompt_metrics = build_tool_prompt(
                request,
                mode=prompt_mode,
                previous_response=previous_response,
            )
            tool_prompt_metrics["prompt_mode"] = prompt_mode
            log_debug_payload("tool_prompt_metrics", tool_prompt_metrics)
        else:
            user_message, prompt_metrics = build_non_tool_prompt(request.messages)
            prompt_metrics["prompt_mode"] = "messages_json"
            log_debug_payload("non_tool_prompt_metrics", prompt_metrics)

        merlin_payload = self._gateway.build_payload(
            model=context.model,
            user_message=user_message,
            tools=context.tools,
            tool_choice=context.tool_choice,
        )
        log_debug_payload(
            "outgoing_merlin_payload",
            {
                "prompt_mode": prompt_mode,
                "previous_response": previous_response,
                "payload": merlin_payload,
            },
        )
        return merlin_payload

    def _should_retry_agentic_tool_call(self, request: OpenAIRequest, response_payload: Dict[str, Any]) -> bool:
        if last_message_is_tool_output(request.messages):
            log_debug_payload(
                "agentic_repair_skipped",
                {
                    "reason": "last_message_is_tool_output",
                    "finish_reason": response_payload["choices"][0]["finish_reason"],
                    "content_preview": (response_payload["choices"][0]["message"].get("content") or "")[:200],
                },
            )
            return False

        return (
            should_force_tool_json(request)
            and normalize_tool_choice(request.tool_choice) == "auto"
            and is_agent_like_tool_context(request)
            and response_payload["choices"][0]["finish_reason"] == "stop"
            and not response_payload["choices"][0]["message"].get("tool_calls")
        )


merlin_gateway = MerlinGateway()
merlin_openai_client = MerlinOpenAIClient(merlin_gateway)
