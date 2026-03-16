from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from merlinai_adapter_server.merlin_client import MerlinGateway
from merlinai_adapter_server.message_utils import get_last_user_message
from merlinai_adapter_server.schemas import Message, OpenAIRequest
from merlinai_adapter_server.tool_payload_parser import resolve_payload_result, try_parse_payload_candidates
from merlinai_adapter_server.tool_prompt import (
    build_tool_prompt,
    compact_tools_for_prompt,
    get_allowed_tool_names,
)


TEST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "required": ["location"],
                "properties": {
                    "location": {"type": "string"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
            },
        },
    }
]

TEST_USER_MESSAGE = (
    "What is the weather like in Tokyo? "
    "Use the get_current_weather tool and do not answer directly."
)


def build_request(model: str, tool_choice: str) -> OpenAIRequest:
    return OpenAIRequest(
        model=model,
        messages=[Message(role="user", content=TEST_USER_MESSAGE)],
        tools=TEST_TOOLS,
        tool_choice=tool_choice,
        stream=False,
    )


def build_case_payload(gateway: MerlinGateway, request: OpenAIRequest, mode: str) -> tuple[dict[str, Any], str]:
    if mode == "mcp_only":
        payload = gateway.build_payload(
            model=request.model,
            user_message=get_last_user_message(request.messages),
            tools=request.tools,
            tool_choice=request.tool_choice,
        )
        payload["metadata"]["mcpConfig"] = {
            "isEnabled": True,
            "tools": compact_tools_for_prompt(request.tools),
            "toolChoice": request.tool_choice,
        }
        return payload, "mcpConfig only"

    prompt, _metrics = build_tool_prompt(request, mode="strict")

    if mode == "prompt_only":
        payload = gateway.build_payload(
            model=request.model,
            user_message=prompt,
            tools=None,
            tool_choice=None,
        )
        payload["metadata"]["mcpConfig"] = {"isEnabled": False}
        return payload, "prompt only"

    if mode == "both":
        payload = gateway.build_payload(
            model=request.model,
            user_message=prompt,
            tools=request.tools,
            tool_choice=request.tool_choice,
        )
        payload["metadata"]["mcpConfig"] = {
            "isEnabled": True,
            "tools": compact_tools_for_prompt(request.tools),
            "toolChoice": request.tool_choice,
        }
        return payload, "both"

    raise ValueError(f"Unsupported mode: {mode}")


def run_case(gateway: MerlinGateway, request: OpenAIRequest, mode: str) -> dict[str, Any]:
    payload, mode_label = build_case_payload(gateway, request, mode)
    allowed_tool_names = get_allowed_tool_names(request)
    content, event_tool_calls, raw_events, _raw_chunks = gateway.send_request(payload, allowed_tool_names)
    payload_tool_calls, payload_message = resolve_payload_result(content, allowed_tool_names)
    parsed_candidates = try_parse_payload_candidates(content)

    effective_tool_calls = event_tool_calls or payload_tool_calls
    return {
        "mode": mode_label,
        "tool_choice": request.tool_choice,
        "request_payload": payload,
        "response_summary": {
            "event_count": len(raw_events),
            "parsed_payload_count": len(parsed_candidates),
            "event_tool_call_count": len(event_tool_calls),
            "payload_tool_call_count": len(payload_tool_calls),
            "effective_tool_call_count": len(effective_tool_calls),
            "effective_tool_names": [
                tool_call.get("function", {}).get("name")
                for tool_call in effective_tool_calls
                if isinstance(tool_call, dict)
            ],
            "payload_message": payload_message,
            "assembled_content": content,
        },
    }


def build_markdown_report(results: list[dict[str, Any]], model: str) -> str:
    lines = [
        "# Tool Transport Mode Comparison",
        "",
        f"- Model: `{model}`",
        f"- Cases: `{len(results)}`",
        "",
    ]

    for result in results:
        summary = result["response_summary"]
        lines.extend(
            [
                f"## {result['mode']} / tool_choice={result['tool_choice']}",
                "",
                f"- Event count: `{summary['event_count']}`",
                f"- Parsed payload count: `{summary['parsed_payload_count']}`",
                f"- Event tool calls: `{summary['event_tool_call_count']}`",
                f"- Payload tool calls: `{summary['payload_tool_call_count']}`",
                f"- Effective tool calls: `{summary['effective_tool_call_count']}`",
                f"- Effective tool names: `{', '.join(summary['effective_tool_names']) or 'N/A'}`",
                "",
                "### Assembled Content",
                "",
                "```text",
                summary["assembled_content"],
                "```",
                "",
            ]
        )

        if summary["payload_message"]:
            lines.extend(
                [
                    "### Parsed Message",
                    "",
                    "```text",
                    summary["payload_message"],
                    "```",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Merlin tool transport modes")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument(
        "--tool-choice",
        nargs="+",
        default=["required", "auto"],
        help="Tool choice values to test",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path("logs") / "tool_transport_compare.json",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=Path("logs") / "tool_transport_compare.md",
    )
    args = parser.parse_args()

    gateway = MerlinGateway()
    results: list[dict[str, Any]] = []
    for tool_choice in args.tool_choice:
        request = build_request(args.model, tool_choice)
        for mode in ("mcp_only", "prompt_only", "both"):
            results.append(run_case(gateway, request, mode))

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(build_markdown_report(results, args.model), encoding="utf-8")

    for result in results:
        summary = result["response_summary"]
        print(
            f"{result['mode']} / tool_choice={result['tool_choice']} / "
            f"effective_tool_calls={summary['effective_tool_call_count']} / "
            f"tool_names={','.join(summary['effective_tool_names']) or 'N/A'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
