"""Bounded Merlin diagnostics. Sends a request, but never executes model tools.

Experimental parameters are confined to this script, not the production API.
Reports omit credentials, raw reasoning, account limits and billing details.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["LOG_TO_FILE"] = "false"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", type=Path, required=True,
                        help="OpenAI request JSON; messages and tool schemas are preserved")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--max-seconds", type=int, default=180)
    parser.add_argument("--variant", choices=("baseline", "effort-low", "thinking-disabled", "native"),
                        default="baseline")
    parser.add_argument("--adapter-instruction", type=Path,
                        help="Optional extra system instruction; does not edit caller messages")
    parser.add_argument("--save-content", action="store_true",
                        help="Include model answer text in the local report (never raw reasoning)")
    args = parser.parse_args()
    from merlinai_adapter_server.models_catalog import resolve_max_tokens
    args.max_tokens = resolve_max_tokens(args.model, args.max_tokens)
    if args.max_tokens < 1 or args.max_seconds < 1:
        parser.error("budgets must be positive")
    if args.out.exists():
        parser.error("output already exists; choose a new report path")

    from merlinai_adapter_server.emulated_tools import parse_emulated_response
    from merlinai_adapter_server.merlin_client import MerlinGateway, MerlinOpenAIClient, ChatCompletionContext
    from merlinai_adapter_server.schemas import OpenAIRequest

    source = json.loads(args.request_json.read_text(encoding="utf-8-sig"))
    source.update(model=args.model, max_tokens=args.max_tokens)
    request = OpenAIRequest(**source)
    mode = "native" if args.variant == "native" else "emulated"
    gateway = MerlinGateway()
    client = MerlinOpenAIClient(gateway, tool_call_mode=mode)
    context = ChatCompletionContext.from_request(request, mode)
    payload = client._build_merlin_payload(request, context)
    if args.variant == "effort-low":
        payload["params"]["reasoning_effort"] = "low"
    elif args.variant == "thinking-disabled":
        payload["params"]["thinking"] = {"type": "disabled"}
    if args.adapter_instruction:
        payload["messages"].append({"role": "system", "content": args.adapter_instruction.read_text(encoding="utf-8")})

    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    report = {"model": args.model, "variant": args.variant, "max_tokens": args.max_tokens,
              "messages_sha256": digest(source["messages"]), "payload_sha256": digest(payload),
              "upstream_done": False, "response_valid": False, "tokens": None,
              "reasoning_chars": 0, "content_chars": 0, "tool_names": []}
    started = time.monotonic()
    connection = None
    content = ""
    calls = []
    try:
        connection, response = gateway.open_request(payload)
        report["http_status"] = response.status
        allowed = context.allowed_tool_names if mode == "native" else set()
        for event in gateway.iter_event_stream(response, allowed):
            content += event.content_delta
            calls.extend(event.tool_calls)
            report["reasoning_chars"] += len(event.reasoning_delta)
            if event.usage:
                report["tokens"] = event.usage.get("tokens")
            if time.monotonic() - started > args.max_seconds:
                raise TimeoutError("diagnostic duration exceeded")
        report["upstream_done"] = True
        if mode == "emulated" and context.tools:
            tokens = report["tokens"] or {}
            output = tokens.get("output", tokens.get("completion"))
            _, calls = parse_emulated_response(
                content, context.emulation_policy,
                output_limit_reached=type(output) is int and output >= args.max_tokens,
            )
        elif not content.strip() and not calls:
            raise ValueError("Upstream completed without answer text or tool calls")
        report["response_valid"] = True
        report["tool_names"] = [call["function"]["name"] for call in calls]
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "status": getattr(exc, "status_code", None),
                           "detail": str(getattr(exc, "detail", exc))}
    finally:
        if connection:
            connection.close()
        report["seconds"] = round(time.monotonic() - started, 2)
        report["content_chars"] = len(content)
        if args.save_content:
            report["content"] = content
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A valid answer is only transport evidence, not proof of task completion.
    print(json.dumps({k: v for k, v in report.items() if k not in {"content", "error"}}, ensure_ascii=True))
    return 0 if report["response_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
