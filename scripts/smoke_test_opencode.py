"""Opt-in real OpenCode -> local adapter -> Merlin smoke (uses account quota)."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["LOG_TO_FILE"] = "false"

import uvicorn  # noqa: E402

from merlinai_adapter_server.app import app  # noqa: E402
from merlinai_adapter_server.config import ADAPTER_API_KEY  # noqa: E402
from merlinai_adapter_server.merlin_client import merlin_openai_client  # noqa: E402


class RequestAudit:
    """Record protocol metadata only; never persist headers or request content."""

    def __init__(self, target):
        self.target = target
        self.records = []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/v1/chat/completions":
            return await self.target(scope, receive, send)
        record = {"status": None, "done": False, "errors": [], "finish_reasons": [],
                  "tool_deltas": 0, "content_deltas": 0, "usage_chunks": 0}
        self.records.append(record)
        request_body = bytearray()
        response_body = bytearray()

        async def read():
            event = await receive()
            request_body.extend(event.get("body", b""))
            if event["type"] == "http.request" and not event.get("more_body"):
                body = json.loads(request_body)
                record.update(model=body.get("model"), stream=body.get("stream"),
                              tool_choice=body.get("tool_choice"),
                              tools=[t.get("function", {}).get("name") for t in body.get("tools", [])],
                              roles=[m.get("role") for m in body.get("messages", [])])
            return event

        async def write(event):
            if event["type"] == "http.response.start":
                record["status"] = event["status"]
            if event["type"] == "http.response.body":
                response_body.extend(event.get("body", b""))
                while b"\n\n" in response_body:
                    frame, _, remainder = response_body.partition(b"\n\n")
                    response_body[:] = remainder
                    for line in frame.splitlines():
                        if not line.startswith(b"data: "):
                            continue
                        value = line[6:]
                        if value == b"[DONE]":
                            record["done"] = True
                            continue
                        chunk = json.loads(value)
                        if "error" in chunk:
                            record["errors"].append(chunk["error"])
                        if chunk.get("usage"):
                            record["usage_chunks"] += 1
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            record["content_deltas"] += bool(delta.get("content"))
                            record["tool_deltas"] += bool(delta.get("tool_calls"))
                            if choice.get("finish_reason"):
                                record["finish_reasons"].append(choice["finish_reason"])
                if not event.get("more_body") and record["status"] != 200:
                    try:
                        record["errors"].append(json.loads(response_body))
                    except (ValueError, UnicodeDecodeError):
                        record["errors"].append({"type": "non_json_http_error"})
            await send(event)

        await self.target(scope, read, write)


def run_case(executable, env, workdir, model, mode, expected, prompt, audit, timeout, session=None):
    offset = len(audit.records)
    command = [executable, "run", "--pure", "--format", "json", "--model",
               f"merlinai-dev/{model}", "--agent", f"adapter-{mode}",
               "--title", f"Adapter smoke {mode} {model}", "--dir", str(workdir)]
    if session:
        command.extend(["--session", session])
    command.append(prompt)
    started = time.monotonic()
    process = subprocess.Popen(command, env=env, cwd=workdir, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            process.kill()
        stdout, stderr = process.communicate(timeout=10)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    text = "".join(e.get("part", {}).get("text", "") for e in events if e.get("type") == "text")
    errors = [e.get("error") for e in events if e.get("type") == "error"]
    tool_events = [{"tool": e.get("part", {}).get("tool"),
                    "status": e.get("part", {}).get("state", {}).get("status"),
                    "error": e.get("part", {}).get("state", {}).get("error")}
                   for e in events if e.get("type") == "tool_use"]
    requests = audit.records[offset:]
    protocol_ok = bool(requests) and all(r["status"] == 200 and r["done"] and not r["errors"]
                                        and bool(r["finish_reasons"]) for r in requests)
    tool_ok = mode != "read" or (
        any(t["tool"] == "read" and t["status"] == "completed" for t in tool_events)
        and any("tool" in r.get("roles", []) for r in requests)
    )
    result = {"model": model, "mode": mode, "continued": bool(session),
              "passed": process.returncode == 0 and not timed_out and not errors
                        and text.strip() == expected and protocol_ok and tool_ok,
              "exit_code": process.returncode, "timed_out": timed_out,
              "elapsed_seconds": round(time.monotonic() - started, 2),
              "text": text, "event_types": [e.get("type") for e in events],
              "errors": errors, "tool_events": tool_events, "requests": requests,
              "stderr": stderr[-3000:],
              "session_id": next((e["sessionID"] for e in events if e.get("sessionID")), None)}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-luna", "claude-sonnet-5"])
    parser.add_argument("--modes", nargs="+", choices=["chat", "read"], default=["chat", "read"])
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--tool-call-mode", choices=["native", "emulated"],
                        default=merlin_openai_client.tool_call_mode)
    parser.add_argument("--out", type=Path, default=ROOT / "logs/opencode-smoke.json")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    merlin_openai_client.tool_call_mode = args.tool_call_mode
    executable = shutil.which("opencode")
    if not executable:
        parser.error("opencode is not installed or not on PATH")
    if not args.config.is_file():
        parser.error("OpenCode config does not exist or is not readable")
    run_dir = ROOT / "logs" / ("opencode-smoke-" + uuid.uuid4().hex[:12])
    run_dir.mkdir(parents=True)
    fixture = run_dir / ("fixture-" + uuid.uuid4().hex + ".txt")
    marker = "READ_OK_" + uuid.uuid4().hex
    fixture.write_text(marker, encoding="utf-8")
    # OpenCode versions can match native or worktree-relative paths on Windows.
    # All entries name this one randomly generated fixture; no broad read allow.
    read_permissions = {"*": "deny"}
    for path in (fixture, fixture.relative_to(ROOT), Path(fixture.name)):
        read_permissions[str(path)] = "allow"
        read_permissions[path.as_posix()] = "allow"
    chat_agent = {"mode": "primary", "description": "Adapter chat smoke", "steps": 2,
                  "permission": {"*": "deny"},
                  "prompt": "Follow the user's exact output instructions. Do not use tools."}
    read_agent = {"mode": "primary", "description": "Adapter read smoke", "steps": 3,
                  "permission": {"*": "deny", "read": read_permissions},
                  "prompt": "Use the read tool for the requested fixture, then output only its exact content."}
    audit = RequestAudit(app)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(audit, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    results = []
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Test adapter failed to start")
        base_url = f"http://127.0.0.1:{port}/v1"
        config = {
            "$schema": "https://opencode.ai/config.json", "share": "disabled", "autoupdate": False,
            "snapshot": False, "enabled_providers": ["merlinai-dev"],
            "provider": {"merlinai-dev": {"npm": "@ai-sdk/openai-compatible",
                         "options": {"baseURL": base_url, "apiKey": ADAPTER_API_KEY},
                         "models": {m: {"name": m, "limit": {"context": 32000, "output": 1000}}
                                    for m in args.models}}},
            "agent": {"adapter-chat": chat_agent, "adapter-read": read_agent,
                      "title": {"disable": True}, "summary": {"disable": True}},
            "permission": {"*": "deny"},
            "small_model": f"merlinai-dev/{args.models[0]}",
        }
        env = os.environ.copy()
        env["OPENCODE_CONFIG"] = str(args.config.resolve())
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        for model in args.models:
            if "chat" in args.modes:
                remembered = "MEMORY_" + uuid.uuid4().hex[:12]
                result = run_case(executable, env, run_dir, model, "chat", "OPENCODE_SMOKE_OK",
                                  f"Remember this code for the next turn: {remembered}. "
                                  "Reply with exactly OPENCODE_SMOKE_OK and nothing else.",
                                  audit, args.timeout)
                results.append(result)
                if result["passed"] and result["session_id"]:
                    results.append(run_case(executable, env, run_dir, model, "chat", remembered,
                                            "Reply only with the exact code I asked you to remember.",
                                            audit, args.timeout, result["session_id"]))
            if "read" in args.modes:
                results.append(run_case(executable, env, run_dir, model, "read", marker,
                                        f"Read {fixture.as_posix()} using the read tool. "
                                        "Reply only with the file's exact content. Do not guess.",
                                        audit, args.timeout))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        fixture.unlink(missing_ok=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"config": str(args.config), "tool_call_mode": args.tool_call_mode,
                                       "results": results},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    expected_cases = len(args.models) * (2 * ("chat" in args.modes) + ("read" in args.modes))
    return 0 if len(results) == expected_cases and all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
