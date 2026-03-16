import datetime
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .logging_config import log_debug_payload
from .request_logging import clear_request_log_context, set_attempt_context, set_request_log_context
from .schemas import OpenAIRequest
from .tool_payload_parser import filter_allowed_tool_calls, resolve_payload_result, try_parse_payload_candidates
from .tool_prompt import get_allowed_tool_names, normalize_tool_choice, should_force_tool_json


def _build_response_message(
    full_content: str,
    selected_message_content: Optional[str],
    all_tool_calls: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], str]:
    response_message: Dict[str, Any] = {"role": "assistant", "content": selected_message_content or full_content or None}
    finish_reason = "stop"

    if all_tool_calls:
        response_message["content"] = None
        response_message["tool_calls"] = all_tool_calls
        finish_reason = "tool_calls"

    return response_message, finish_reason


def _validate_response_mode(
    request: OpenAIRequest,
    force_tool_json: bool,
    all_tool_calls: List[Dict[str, Any]],
    selected_message_content: Optional[str],
    finish_reason: str,
) -> None:
    required_tool_call = normalize_tool_choice(request.tool_choice)
    if (
        force_tool_json
        and required_tool_call in {"required"}
        and not all_tool_calls
        and selected_message_content is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Tool mode was enabled, but upstream did not return a valid structured JSON payload.",
        )
    if finish_reason != "tool_calls" and required_tool_call in {"required"}:
        raise HTTPException(
            status_code=422,
            detail="Tool calling was required, but upstream did not return a valid tool call payload.",
        )
    if finish_reason != "tool_calls" and isinstance(required_tool_call, str) and required_tool_call.startswith("function:"):
        raise HTTPException(
            status_code=422,
            detail=f"Specific tool call was required ({required_tool_call}), but upstream did not return a valid tool call payload.",
        )


def build_openai_response(request: OpenAIRequest, full_content: str, response_tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    force_tool_json = should_force_tool_json(request)
    allowed_tool_names = get_allowed_tool_names(request)
    parsed_payloads = try_parse_payload_candidates(full_content) if force_tool_json else []
    payload_tool_calls, selected_message_content = (
        resolve_payload_result(full_content, allowed_tool_names) if force_tool_json else ([], None)
    )
    filtered_response_tool_calls = filter_allowed_tool_calls(response_tool_calls, allowed_tool_names)
    all_tool_calls = filtered_response_tool_calls or payload_tool_calls
    if selected_message_content is None and not all_tool_calls:
        selected_message_content = full_content or None
    if force_tool_json:
        log_debug_payload(
            "structured_payload_resolution",
            {
                "parsed_payload_count": len(parsed_payloads),
                "parsed_payload_types": [payload.get("type") for payload in parsed_payloads if isinstance(payload, dict)],
                "payload_tool_call_names": [
                    tool_call.get("function", {}).get("name") for tool_call in payload_tool_calls if isinstance(tool_call, dict)
                ],
                "event_tool_call_names": [
                    tool_call.get("function", {}).get("name")
                    for tool_call in filtered_response_tool_calls
                    if isinstance(tool_call, dict)
                ],
                "selected_message_preview": (selected_message_content or "")[:200],
            },
        )
    response_message, finish_reason = _build_response_message(full_content, selected_message_content, all_tool_calls)
    _validate_response_mode(
        request,
        force_tool_json,
        all_tool_calls,
        selected_message_content,
        finish_reason,
    )

    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(datetime.datetime.now().timestamp()),
        "model": request.model,
        "choices": [{"index": 0, "message": response_message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _build_stream_chunk(
    response_id: str,
    created: int,
    model: str,
    delta: Dict[str, Any],
    finish_reason: Optional[str],
) -> str:
    return (
        "data: "
        + json.dumps(
            {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }
        )
        + "\n\n"
    )


def build_streamed_openai_response(
    request: OpenAIRequest,
    full_content: str,
    response_tool_calls: List[Dict[str, Any]],
    request_id: str | None = None,
):
    if request_id:
        set_request_log_context(request_id=request_id)
        set_attempt_context(None)

    try:
        response_payload = build_openai_response(request, full_content, response_tool_calls)
        response_id = response_payload["id"]
        created = response_payload["created"]
        choice = response_payload["choices"][0]
        finish_reason = choice["finish_reason"]
        message = choice["message"]
        log_debug_payload(
            "streamed_openai_response_summary",
            {
                "response_id": response_id,
                "finish_reason": finish_reason,
                "tool_call_names": [tool_call["function"]["name"] for tool_call in message.get("tool_calls", [])],
                "content_preview": (message.get("content") or "")[:300],
            },
        )

        yield _build_stream_chunk(
            response_id=response_id,
            created=created,
            model=request.model,
            delta={"role": "assistant"},
            finish_reason=None,
        )

        if finish_reason == "tool_calls":
            for index, tool_call in enumerate(message["tool_calls"]):
                yield _build_stream_chunk(
                    response_id=response_id,
                    created=created,
                    model=request.model,
                    delta={
                        "tool_calls": [
                            {
                                "index": index,
                                "id": tool_call["id"],
                                "type": "function",
                                "function": {
                                    "name": tool_call["function"]["name"],
                                    "arguments": tool_call["function"]["arguments"],
                                },
                            }
                        ]
                    },
                    finish_reason=None,
                )
            yield _build_stream_chunk(
                response_id=response_id,
                created=created,
                model=request.model,
                delta={},
                finish_reason="tool_calls",
            )
            yield "data: [DONE]\n\n"
            return

        content = message.get("content") or ""
        if content:
            yield _build_stream_chunk(
                response_id=response_id,
                created=created,
                model=request.model,
                delta={"content": content},
                finish_reason=None,
            )

        yield _build_stream_chunk(
            response_id=response_id,
            created=created,
            model=request.model,
            delta={},
            finish_reason="stop",
        )
        yield "data: [DONE]\n\n"
    finally:
        if request_id:
            clear_request_log_context()
