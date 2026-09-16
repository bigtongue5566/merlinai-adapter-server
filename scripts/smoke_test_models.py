"""Exercise the local ASGI app with real Merlin requests (uses account quota)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Keep credentials and request bodies out of smoke-test logs.
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["LOG_TO_FILE"] = "false"

from fastapi.testclient import TestClient

from merlinai_adapter_server import app
from merlinai_adapter_server.config import ADAPTER_API_KEY
from merlinai_adapter_server.models_catalog import SUPPORTED_MODELS
from merlinai_adapter_server.schemas import OpenAIChatCompletionChunk, OpenAIChatCompletionResponse

HEADERS = {"Authorization": f"Bearer {ADAPTER_API_KEY}"}
MARKER = "MERLIN_SMOKE_OK"
TOOL = {
    "type": "function",
    "function": {
        "name": "echo_probe",
        "description": "Return the supplied text unchanged.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_tools(calls: list[dict]) -> None:
    check(len(calls) == 1, "Expected one tool call")
    call = calls[0]
    check(bool(call.get("id")), "Missing tool call ID")
    check(call["type"] == "function", "Invalid tool type")
    check(call["function"]["name"] == "echo_probe", "Wrong tool name")
    check(json.loads(call["function"]["arguments"]) == {"text": MARKER}, "Wrong tool arguments")


def run_case(case: tuple[str, str]) -> dict:
    model, mode = case
    started = time.monotonic()
    result = {"model": model, "mode": mode, "passed": False}
    stream = mode.endswith("stream")
    tool_mode = mode.startswith("tool")
    request = {
        "model": model,
        "messages": [{"role": "user", "content": (
            f'Call echo_probe with text exactly "{MARKER}". Do not answer directly.'
            if tool_mode else f"Reply with exactly {MARKER} and nothing else."
        )}],
        "stream": stream,
    }
    if tool_mode:
        request.update(tools=[TOOL], tool_choice="required")
    try:
        with TestClient(app) as client:
            response = client.post("/v1/chat/completions", headers=HEADERS, json=request)
        result["status"] = response.status_code
        check(response.status_code == 200, f"HTTP {response.status_code}")
        if stream:
            check(response.headers["content-type"].startswith("text/event-stream"), "Wrong content type")
            events = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
            check(bool(events) and events[-1] == "[DONE]", "Missing SSE terminator")
            chunks = [json.loads(event) for event in events[:-1]]
            check(len(chunks) >= 3, "Missing SSE chunks")
            for chunk in chunks:
                OpenAIChatCompletionChunk.model_validate(chunk)
                check(chunk["model"] == model, "Wrong response model")
                check(chunk["id"] == chunks[0]["id"], "Inconsistent stream ID")
            check(chunks[0]["choices"][0]["delta"].get("role") == "assistant", "Missing assistant role")
            choices = [chunk["choices"][0] for chunk in chunks]
            check(choices[-1]["finish_reason"] == ("tool_calls" if tool_mode else "stop"), "Wrong finish reason")
            if tool_mode:
                calls: dict[int, dict] = {}
                for choice in choices:
                    for delta in choice["delta"].get("tool_calls", []):
                        call = calls.setdefault(delta["index"], {"function": {"name": "", "arguments": ""}})
                        for key in ("id", "type"):
                            if key in delta:
                                call[key] = delta[key]
                        for key in ("name", "arguments"):
                            call["function"][key] += delta.get("function", {}).get(key, "")
                check_tools(list(calls.values()))
            else:
                content = "".join(choice["delta"].get("content", "") for choice in choices)
                check(MARKER in content, "Missing expected reply")
            result["chunks"] = len(chunks)
        else:
            body = response.json()
            OpenAIChatCompletionResponse.model_validate(body)
            check(body["model"] == model, "Wrong response model")
            choice = body["choices"][0]
            check(choice["finish_reason"] == ("tool_calls" if tool_mode else "stop"), "Wrong finish reason")
            if tool_mode:
                check_tools(choice["message"].get("tool_calls", []))
            else:
                check(MARKER in (choice["message"].get("content") or ""), "Missing expected reply")
        result["passed"] = True
    except Exception as exc:
        # Do not serialize upstream bodies, tokens, or auth exception details.
        result["error"] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
    result["seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(result), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=SUPPORTED_MODELS, default=list(SUPPORTED_MODELS))
    parser.add_argument("--modes", nargs="+", choices=["chat", "chat-stream", "tool", "tool-stream"], default=["chat"])
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--out", type=Path, default=Path("logs/model-smoke.json"))
    args = parser.parse_args()
    with TestClient(app) as client:
        check(client.get("/v1/models").status_code == 401, "Model list must require auth")
        check(client.post("/v1/chat/completions", json={"model": args.models[0], "messages": []}).status_code == 401, "Chat must require auth")
        response = client.get("/v1/models", headers=HEADERS)
        check(response.status_code == 200, "Model list failed")
        body = response.json()
        check(body["object"] == "list", "Wrong model list object")
        ids = [entry["id"] for entry in body["data"]]
        check(ids == list(SUPPORTED_MODELS) and len(ids) == len(set(ids)), "Model list mismatch or duplicates")
        check(client.post("/v1/chat/completions", headers=HEADERS, json={}).status_code == 422, "Request validation failed")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_case, [(model, mode) for model in args.models for mode in args.modes]))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "transport": "FastAPI TestClient -> real Merlin upstream; no mocked responses",
        "local_checks": ["models auth", "chat auth", "model catalog", "request validation"],
        "results": results,
        "passed": sum(result["passed"] for result in results),
        "failed": sum(not result["passed"] for result in results),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {report['passed']}/{len(results)}; report: {args.out}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
