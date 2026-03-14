from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from .logging_config import configure_logger, log_debug_payload
from .merlin_client import build_merlin_payload, send_merlin_request
from .message_utils import get_last_user_message
from .openai_response_builder import build_openai_response, build_streamed_openai_response
from .schemas import OpenAIRequest
from .security import verify_proxy_api_key
from .tool_prompt import (
    build_tool_prompt,
    is_agent_like_tool_context,
    normalize_tool_choice,
    should_force_tool_json,
    should_retry_tool_response,
)

configure_logger()

app = FastAPI(title="merlinai-adapter-server")


def _build_merlin_payload_for_request(
    request: OpenAIRequest, prompt_mode: str = "default", previous_response: str | None = None
):
    if should_force_tool_json(request):
        user_message, tool_prompt_metrics = build_tool_prompt(request, mode=prompt_mode, previous_response=previous_response)
        log_debug_payload("tool_prompt_metrics", tool_prompt_metrics)
    else:
        user_message = get_last_user_message(request.messages)

    merlin_payload = build_merlin_payload(request, user_message)
    log_debug_payload("outgoing_merlin_payload", merlin_payload)
    return merlin_payload


def _execute_merlin_request(request: OpenAIRequest):
    prompt_mode = "strict"
    merlin_payload = _build_merlin_payload_for_request(request, prompt_mode=prompt_mode)
    full_content, response_tool_calls, raw_events = send_merlin_request(merlin_payload, request)
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

        repair_payload = _build_merlin_payload_for_request(
            request, prompt_mode="repair", previous_response=full_content
        )
        repaired_content, repaired_tool_calls, repaired_raw_events = send_merlin_request(repair_payload, request)
        log_debug_payload(
            "merlin_repair_request_summary",
            {
                "previous_content": full_content,
                "repaired_content": repaired_content,
                "repair_event_count": len(repaired_raw_events),
                "repair_event_sample": repaired_raw_events[:3],
                "repair_tool_call_count": len(repaired_tool_calls),
            },
        )
        full_content = repaired_content
        response_tool_calls = repaired_tool_calls
        raw_events = raw_events + repaired_raw_events
        response_payload = build_openai_response(request, full_content, response_tool_calls)

    if (
        should_force_tool_json(request)
        and normalize_tool_choice(request.tool_choice) == "auto"
        and is_agent_like_tool_context(request)
        and response_payload["choices"][0]["finish_reason"] == "stop"
        and not response_payload["choices"][0]["message"].get("tool_calls")
    ):
        repair_payload = _build_merlin_payload_for_request(
            request, prompt_mode="strict", previous_response=full_content
        )
        repaired_content, repaired_tool_calls, repaired_raw_events = send_merlin_request(repair_payload, request)
        log_debug_payload(
            "merlin_agentic_repair_summary",
            {
                "previous_content": full_content,
                "repaired_content": repaired_content,
                "repair_event_count": len(repaired_raw_events),
                "repair_event_sample": repaired_raw_events[:3],
                "repair_tool_call_count": len(repaired_tool_calls),
            },
        )
        candidate_response = build_openai_response(request, repaired_content, repaired_tool_calls)
        if candidate_response["choices"][0]["finish_reason"] == "tool_calls":
            full_content = repaired_content
            response_tool_calls = repaired_tool_calls
            raw_events = raw_events + repaired_raw_events
            response_payload = candidate_response
    return response_payload, full_content, response_tool_calls, raw_events


@app.post("/v1/chat/completions")
async def chat_completions(request: OpenAIRequest, authorization: Optional[str] = Header(default=None)):
    verify_proxy_api_key(authorization)
    log_debug_payload(
        "incoming_chat_request",
        {
            "model": request.model,
            "stream": request.stream,
            "has_tools": bool(request.tools),
            "tool_choice": request.tool_choice,
            "message_count": len(request.messages),
            "messages": request.model_dump(exclude_none=True).get("messages", []),
        },
    )
    response_payload, full_content, response_tool_calls, raw_events = _execute_merlin_request(request)
    log_debug_payload(
        "outgoing_openai_response",
        {
            "response": response_payload,
            "merlin_event_count": len(raw_events),
            "merlin_event_sample": raw_events[:3],
        },
    )

    if request.stream:
        return StreamingResponse(
            build_streamed_openai_response(request, full_content, response_tool_calls), media_type="text/event-stream"
        )

    return response_payload


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(default=None)):
    verify_proxy_api_key(authorization)
    models = [
        "gpt-5.4",
        "grok-4.1-fast",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro",
        "claude-4.6-sonnet",
        "claude-4.6-opus",
        "glm-5",
        "minimax-m2.5",
    ]
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": "merlin",
            }
            for model in models
        ],
    }
