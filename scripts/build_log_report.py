from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LOG_PREFIX = "[adapter] "


def _try_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_adapter_log(log_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    body_lines: list[str] = []

    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.startswith(LOG_PREFIX):
            if current is not None:
                body_lines.append(line)
            continue

        if current is not None:
            current["payload"] = _try_json_loads("\n".join(body_lines).strip())
            entries.append(current)

        header = line[len(LOG_PREFIX) :]
        if " DEBUG " not in header:
            current = None
            body_lines = []
            continue

        timestamp, rest = header.split(" DEBUG ", 1)
        label = rest.removesuffix(":")
        current = {"timestamp": timestamp.strip(), "label": label.strip()}
        body_lines = []

    if current is not None:
        current["payload"] = _try_json_loads("\n".join(body_lines).strip())
        entries.append(current)

    return entries


def _ensure_attempt_bucket(store: dict[str, dict[str, Any]], attempt: str) -> dict[str, Any]:
    return store.setdefault(
        attempt,
        {
            "incoming_chat_request": None,
            "tool_prompt_metrics": None,
            "outgoing_merlin_payload": None,
            "merlin_raw_response": None,
            "merlin_non_stream_error": None,
            "merlin_attempt_summary": None,
            "structured_payload_resolution": None,
        },
    )


def group_entries(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    requests: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    attempt_level_labels = {
        "tool_prompt_metrics",
        "outgoing_merlin_payload",
        "merlin_raw_response",
        "merlin_non_stream_error",
        "merlin_attempt_summary",
        "structured_payload_resolution",
    }

    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        request_id = payload.get("request_id")
        if not request_id:
            warnings.append(f"{entry['label']} 缺少 request_id")
            continue

        request_bucket = requests.setdefault(
            request_id,
            {
                "request_id": request_id,
                "first_timestamp": entry["timestamp"],
                "last_timestamp": entry["timestamp"],
                "incoming_chat_request": None,
                "attempts": {},
                "outgoing_openai_response": None,
            },
        )
        request_bucket["last_timestamp"] = entry["timestamp"]

        if entry["label"] == "incoming_chat_request":
            request_bucket["incoming_chat_request"] = payload
            continue

        if entry["label"] == "outgoing_openai_response":
            request_bucket["outgoing_openai_response"] = payload
            continue

        if entry["label"] not in attempt_level_labels:
            continue

        attempt = payload.get("attempt")
        if not attempt:
            continue
        attempt_bucket = _ensure_attempt_bucket(request_bucket["attempts"], attempt)
        if entry["label"] in attempt_bucket:
            attempt_bucket[entry["label"]] = payload
        else:
            attempt_bucket[entry["label"]] = payload

    return requests, warnings


def parse_opencode_session_export(session_export_path: Path) -> list[str]:
    data = json.loads(session_export_path.read_text(encoding="utf-8"))
    findings: list[str] = []
    saw_successful_itinerary_write = False

    for message in data.get("messages", []):
        role = message.get("info", {}).get("role")
        for part in message.get("parts", []):
            part_type = part.get("type")
            if part_type == "tool" and part.get("tool") == "bash":
                state = part.get("state", {})
                metadata = state.get("metadata", {})
                exit_code = metadata.get("exit")
                command = state.get("input", {}).get("command", "")
                description = state.get("input", {}).get("description", "bash tool")
                if exit_code not in (None, 0):
                    findings.append(f"OpenCode bash tool failed once (`exit={exit_code}`): {description}.")
                if exit_code == 0 and "itinerary.md" in command and "Set-Content" in command:
                    saw_successful_itinerary_write = True
                    findings.append("OpenCode later succeeded in writing `itinerary.md` via PowerShell `Set-Content`.")
            elif part_type == "text" and role == "assistant":
                text = part.get("text", "")
                if (
                    "無法直接" in text
                    or "不能實際建立" in text
                    or "cannot directly" in text.lower()
                ):
                    if saw_successful_itinerary_write:
                        findings.append(
                            "OpenCode's final assistant text incorrectly claimed it could not write `itinerary.md` after a successful tool write."
                        )
                    else:
                        findings.append("OpenCode's final assistant text claimed it could not write `itinerary.md`.")

    deduped: list[str] = []
    for finding in findings:
        if finding not in deduped:
            deduped.append(finding)
    return deduped


def format_payload_for_markdown(label: str, payload: Any) -> Any:
    if label != "merlin_raw_response" or not isinstance(payload, dict):
        return payload

    return {
        "prompt_mode": payload.get("prompt_mode"),
        "event_count": payload.get("event_count"),
        "assembled_content": payload.get("assembled_content"),
        "tool_calls": payload.get("tool_calls"),
        "request_id": payload.get("request_id"),
        "attempt": payload.get("attempt"),
    }


def build_markdown(
    *,
    requests: dict[str, dict[str, Any]],
    warnings: list[str],
    session_id: str | None,
    model_name: str | None,
    opencode_findings: list[str] | None,
) -> str:
    lines: list[str] = [
        "# Merlin Test Log",
        "",
        "## Session",
        "",
        f"- Session ID: `{session_id or 'N/A'}`",
        f"- Model: `{model_name or 'N/A'}`",
        f"- Request count: `{len(requests)}`",
    ]

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    if opencode_findings:
        lines.extend(["", "## OpenCode Findings", ""])
        for finding in opencode_findings:
            lines.append(f"- {finding}")

    lines.extend(["", "## Requests", ""])

    for request_id, request_data in sorted(requests.items(), key=lambda item: item[1]["first_timestamp"]):
        incoming = request_data.get("incoming_chat_request") or {}
        lines.extend(
            [
                f"### Request `{request_id}`",
                "",
                f"- Started: `{request_data['first_timestamp']}`",
                f"- Finished: `{request_data['last_timestamp']}`",
                f"- Model: `{incoming.get('model', model_name or 'N/A')}`",
                f"- Message count: `{incoming.get('message_count', 'N/A')}`",
            ]
        )

        attempt_names = list(request_data["attempts"].keys())
        if not attempt_names:
            lines.append("- Attempts: `0`")
        else:
            lines.append(f"- Attempts: `{', '.join(attempt_names)}`")
        lines.append("")

        if incoming:
            lines.extend(
                [
                    "#### Incoming Chat Request",
                    "",
                    "```json",
                    json.dumps(incoming, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

        for attempt, attempt_data in request_data["attempts"].items():
            lines.extend([f"#### Attempt `{attempt}`", ""])

            issue_lines: list[str] = []
            if attempt == "repair":
                issue_lines.append("Adapter had to issue a repair retry because the first tool-oriented response was not usable as-is.")
            if attempt == "agentic_repair":
                issue_lines.append("Adapter had to issue an agentic retry because upstream stopped instead of cleanly continuing the tool workflow.")
            if attempt_data.get("merlin_non_stream_error"):
                issue_lines.append("Merlin upstream returned a non-200 response.")
            raw_response = attempt_data.get("merlin_raw_response")
            if isinstance(raw_response, dict) and raw_response.get("event_count", 0) == 0:
                issue_lines.append("Merlin raw event stream was empty.")
            if isinstance(raw_response, dict) and "Search is off" in str(raw_response.get("assembled_content", "")):
                issue_lines.append("This attempt drifted into a Merlin web-search warning instead of continuing the requested file workflow.")

            lines.extend(["Problems:", ""])
            if issue_lines:
                for issue in issue_lines:
                    lines.append(f"- {issue}")
            else:
                lines.append("- No immediate issues detected in this attempt.")
            lines.append("")

            for label in (
                "tool_prompt_metrics",
                "outgoing_merlin_payload",
                "merlin_raw_response",
                "merlin_non_stream_error",
                "merlin_attempt_summary",
                "structured_payload_resolution",
            ):
                payload = attempt_data.get(label)
                if payload is None:
                    continue
                display_payload = format_payload_for_markdown(label, payload)
                lines.extend(
                    [
                        f"##### {label}",
                        "",
                        "```json",
                        json.dumps(display_payload, ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )

        outgoing = request_data.get("outgoing_openai_response")
        if outgoing:
            lines.extend(
                [
                    "#### Outgoing OpenAI Response",
                    "",
                    "```json",
                    json.dumps(outgoing, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

    lines.extend(["## Summary", ""])
    if not requests:
        lines.append("- No request logs were found.")
    else:
        total_attempts = sum(len(request_data["attempts"]) for request_data in requests.values())
        lines.append(f"- Adapter logged `{len(requests)}` client request(s) and `{total_attempts}` Merlin attempt(s).")
        has_retry_issues = any(
            any(attempt_name in {"repair", "agentic_repair"} for attempt_name in request_data["attempts"])
            for request_data in requests.values()
        )
        has_errors = any(
            attempt_data.get("merlin_non_stream_error")
            for request_data in requests.values()
            for attempt_data in request_data["attempts"].values()
        )
        if has_errors:
            lines.append("- Verdict: adapter path completed with upstream or transport errors that need review.")
        elif has_retry_issues or opencode_findings:
            lines.append("- Verdict: adapter path is usable, but this run exposed Merlin/OpenCode workflow issues that need attention.")
        else:
            lines.append("- Verdict: adapter path looks usable for this scenario.")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Markdown report from adapter.log")
    parser.add_argument("--log", required=True, type=Path, help="Path to adapter.log")
    parser.add_argument("--out", required=True, type=Path, help="Path to output Markdown report")
    parser.add_argument("--session-id", default=None, help="OpenCode session ID")
    parser.add_argument("--model", default=None, help="Model name used for the run")
    parser.add_argument("--session-export", default=None, type=Path, help="Path to `opencode export` JSON")
    args = parser.parse_args()

    entries = parse_adapter_log(args.log)
    requests, warnings = group_entries(entries)
    opencode_findings = parse_opencode_session_export(args.session_export) if args.session_export else None
    output = build_markdown(
        requests=requests,
        warnings=warnings,
        session_id=args.session_id,
        model_name=args.model,
        opencode_findings=opencode_findings,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
