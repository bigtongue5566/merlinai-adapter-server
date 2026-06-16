import uuid
from typing import Optional

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .logging_config import configure_logger, log_debug_payload
from .merlin_client import merlin_openai_client
from .models_catalog import build_models_response
from .openai_response_builder import build_streamed_openai_response
from .request_logging import clear_request_log_context, set_request_log_context
from .schemas import OpenAIRequest, model_dump_compat
from .security import verify_adapter_api_key

configure_logger()

app = FastAPI(title="merlinai-adapter-server")


@app.post("/v1/chat/completions")
async def chat_completions(request: OpenAIRequest, authorization: Optional[str] = Header(default=None)):
    verify_adapter_api_key(authorization)
    request_id = str(uuid.uuid4())
    set_request_log_context(request_id=request_id)
    try:
        log_debug_payload(
            "incoming_chat_request",
            {
                "model": request.model,
                "stream": request.stream,
                "has_tools": bool(request.tools),
                "tool_choice": model_dump_compat(request.tool_choice),
                "message_count": len(request.messages),
                "messages": request.model_dump(exclude_none=True).get("messages", []),
                "request": request.model_dump(exclude_none=True),
            },
        )
        if request.stream and merlin_openai_client.can_stream_from_upstream(request):
            stream_iterator = await run_in_threadpool(
                merlin_openai_client.open_chat_completion_stream,
                request,
                request_id,
            )
            return StreamingResponse(
                stream_iterator,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        result = await run_in_threadpool(merlin_openai_client.execute_chat_completion, request)
        log_debug_payload(
            "outgoing_openai_response",
            {
                "response": result.response_payload,
                "merlin_event_count": len(result.raw_events),
                "tool_call_count": len(result.tool_calls),
                "content_preview": (result.content or "")[:500],
            },
        )

        if request.stream:
            return StreamingResponse(
                build_streamed_openai_response(request, result.content, result.tool_calls, request_id=request_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        return result.response_payload
    finally:
        clear_request_log_context()


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(default=None)):
    verify_adapter_api_key(authorization)
    return build_models_response()
