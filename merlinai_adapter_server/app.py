from typing import Optional

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from .logging_config import configure_logger, log_debug_payload
from .merlin_client import merlin_openai_client
from .models_catalog import build_models_response
from .openai_response_builder import build_streamed_openai_response
from .schemas import OpenAIRequest
from .security import verify_proxy_api_key

configure_logger()

app = FastAPI(title="merlinai-adapter-server")


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
    result = merlin_openai_client.execute_chat_completion(request)
    log_debug_payload(
        "outgoing_openai_response",
        {
            "response": result.response_payload,
            "merlin_event_count": len(result.raw_events),
            "merlin_event_sample": result.raw_events[:3],
        },
    )

    if request.stream:
        return StreamingResponse(
            build_streamed_openai_response(request, result.content, result.tool_calls),
            media_type="text/event-stream",
        )

    return result.response_payload


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(default=None)):
    verify_proxy_api_key(authorization)
    return build_models_response()
