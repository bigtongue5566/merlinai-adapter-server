"""SSE framing and failure detection shared by Merlin chat protocols."""

import http.client
import json
import socket
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterator

from fastapi import HTTPException


@dataclass(frozen=True)
class SSEEvent:
    name: str
    data: Any
    raw: str


def _is_error_marker(value: Any) -> bool:
    return isinstance(value, str) and value in {"error", "ERROR"}


def _frames(response: BinaryIO) -> Iterator[tuple[str, str]]:
    name = "message"
    lines: list[str] = []
    size = 0
    limit = 1_048_576
    while True:
        try:
            raw = response.readline(limit + 1)
        except socket.timeout as exc:
            raise HTTPException(504, "Merlin event stream timed out") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise HTTPException(502, "Merlin event stream failed") from exc
        if not raw:
            if lines:
                yield name, "\n".join(lines)
            return
        size += len(raw)
        if size > limit:
            raise HTTPException(502, "Merlin SSE frame exceeds size limit")
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise HTTPException(502, "Merlin SSE contains invalid UTF-8") from exc
        if not line:
            if lines:
                yield name, "\n".join(lines)
            name, lines, size = "message", [], 0
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value or "message"
        elif field == "data":
            lines.append(value)


def iter_merlin_sse(response: BinaryIO) -> Iterator[SSEEvent]:
    """Require an explicit completion; an HTTP 200 is not proof of success."""
    for name, raw in _frames(response):
        # Error takes precedence even if the payload is malformed or says DONE.
        if name == "error":
            raise HTTPException(502, "Merlin returned an upstream SSE error")
        if name == "INIT_MESSAGE_CONTENT":
            continue
        if raw.strip() == "[DONE]" and name == "message":
            return
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            if name not in {"message", "tool_calls", "usage"}:
                continue
            raise HTTPException(502, "Merlin returned malformed SSE JSON") from exc
        if isinstance(value, dict):
            inner = value.get("data")
            inner = inner if isinstance(inner, dict) else {}
            if (
                value.get("error")
                or inner.get("error")
                or value.get("status") == "error"
                or inner.get("status") == "error"
                or _is_error_marker(value.get("eventType"))
                or _is_error_marker(inner.get("eventType"))
                or _is_error_marker(value.get("type"))
                or _is_error_marker(inner.get("type"))
            ):
                raise HTTPException(502, "Merlin returned an upstream SSE error")
            if name == "message" and (inner.get("eventType") == "DONE" or value.get("status") == "done"):
                return
        if name == "message" and not isinstance(value, dict):
            raise HTTPException(502, "Merlin returned invalid message data")
        if name == "tool_calls" and not isinstance(value, list):
            raise HTTPException(502, "Merlin returned invalid tool call data")
        yield SSEEvent(name, value, raw)
    raise HTTPException(502, "Merlin event stream ended before DONE")
