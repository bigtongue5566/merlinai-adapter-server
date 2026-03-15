import datetime
import http.client
import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

from .auth import token_manager
from .config import MERLIN_API_URL, MERLIN_PATH, MERLIN_VERSION
from .logging_config import log_debug_payload
from .message_utils import get_last_user_message
from .openai_response_builder import build_openai_response
from .schemas import OpenAIRequest
from .tool_payload_parser import extract_tool_calls
from .tool_prompt import (
    build_tool_prompt,
    compact_tools_for_prompt,
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
        compact_tools = compact_tools_for_prompt(tools)
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
                "mcpConfig": {
                    "isEnabled": bool(tools),
                    "tools": compact_tools,
                    "toolChoice": tool_choice,
                },
                "isWebpageChat": False,
                "webAccess": False,
            },
        }

    def send_request(
        self,
        merlin_payload: Dict[str, Any],
        allowed_tool_names: Optional[Set[str]] = None,
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        conn = http.client.HTTPSConnection(MERLIN_API_URL)
        try:
            conn.request("POST", MERLIN_PATH, json.dumps(merlin_payload), self._get_headers())
            res = conn.getresponse()

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
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        full_content = ""
        response_tool_calls: List[Dict[str, Any]] = []
        raw_events: List[Dict[str, Any]] = []

        while True:
            line = res.readline()
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

        return full_content, response_tool_calls, raw_events


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
        prompt_mode = "strict"
        initial_response = self._send_request(
            request,
            context,
            prompt_mode=prompt_mode,
        )
        full_content = initial_response.content
        response_tool_calls = initial_response.tool_calls
        raw_events = initial_response.raw_events
        log_debug_payload(
            "merlin_request_summary",
            {
                "prompt_mode": prompt_mode,
                "merlin_event_count": len(raw_events),
                "merlin_event_sample": raw_events[:3],
                "assembled_content": full_content,
                "tool_call_count": len(response_tool_calls),
            },
        )

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
                prompt_mode="repair",
                previous_response=previous_content,
            )
            full_content = repaired_response.content
            response_tool_calls = repaired_response.tool_calls
            log_debug_payload(
                "merlin_repair_request_summary",
                {
                    "previous_content": previous_content,
                    "repaired_content": full_content,
                    "repair_event_count": len(repaired_response.raw_events),
                    "repair_event_sample": repaired_response.raw_events[:3],
                    "repair_tool_call_count": len(response_tool_calls),
                },
            )
            raw_events = raw_events + repaired_response.raw_events
            response_payload = build_openai_response(request, full_content, response_tool_calls)

        # In multi-step tool workflows, give Merlin one more chance to emit tool calls instead of plain text.
        if self._should_retry_agentic_tool_call(request, response_payload):
            repaired_response = self._send_request(
                request,
                context,
                prompt_mode="strict",
                previous_response=full_content,
            )
            repaired_content = repaired_response.content
            repaired_tool_calls = repaired_response.tool_calls
            log_debug_payload(
                "merlin_agentic_repair_summary",
                {
                    "previous_content": full_content,
                    "repaired_content": repaired_content,
                    "repair_event_count": len(repaired_response.raw_events),
                    "repair_event_sample": repaired_response.raw_events[:3],
                    "repair_tool_call_count": len(repaired_tool_calls),
                },
            )
            candidate_response = build_openai_response(request, repaired_content, repaired_tool_calls)
            if candidate_response["choices"][0]["finish_reason"] == "tool_calls":
                full_content = repaired_content
                response_tool_calls = repaired_tool_calls
                raw_events = raw_events + repaired_response.raw_events
                response_payload = candidate_response

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
        prompt_mode: str,
        previous_response: str | None = None,
    ) -> MerlinResponseEnvelope:
        merlin_payload = self._build_merlin_payload(
            request,
            context,
            prompt_mode=prompt_mode,
            previous_response=previous_response,
        )
        content, tool_calls, raw_events = self._gateway.send_request(merlin_payload, context.allowed_tool_names)
        return MerlinResponseEnvelope(content=content, tool_calls=tool_calls, raw_events=raw_events)

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
            log_debug_payload("tool_prompt_metrics", tool_prompt_metrics)
        else:
            user_message = get_last_user_message(request.messages)

        merlin_payload = self._gateway.build_payload(
            model=context.model,
            user_message=user_message,
            tools=context.tools,
            tool_choice=context.tool_choice,
        )
        log_debug_payload("outgoing_merlin_payload", merlin_payload)
        return merlin_payload

    def _should_retry_agentic_tool_call(self, request: OpenAIRequest, response_payload: Dict[str, Any]) -> bool:
        return (
            should_force_tool_json(request)
            and normalize_tool_choice(request.tool_choice) == "auto"
            and is_agent_like_tool_context(request)
            and response_payload["choices"][0]["finish_reason"] == "stop"
            and not response_payload["choices"][0]["message"].get("tool_calls")
        )


merlin_gateway = MerlinGateway()
merlin_openai_client = MerlinOpenAIClient(merlin_gateway)
