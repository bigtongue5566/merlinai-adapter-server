import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from json_repair import repair_json

from .protocol_constants import STRUCTURED_PAYLOAD_END, STRUCTURED_PAYLOAD_START
from .structured_output import (
    normalize_merlin_event_tool_calls,
    resolve_tool_strategy_payload,
)


def extract_structured_payload_blocks(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    pattern = re.compile(
        re.escape(STRUCTURED_PAYLOAD_START) + r"(.*?)" + r"(?:" +
        re.escape(STRUCTURED_PAYLOAD_END) + r"|" +
        re.escape(STRUCTURED_PAYLOAD_END.replace("/", r"\/")) +
        r")",
        re.DOTALL,
    )
    blocks: List[str] = []
    for match in pattern.finditer(raw_text):
        block = match.group(1).strip()
        if block:
            blocks.append(block)
    return blocks


def _try_parse_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_text, str):
        return None

    candidate = raw_text.strip()
    if not candidate:
        return None

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            parsed = repair_json(candidate, return_objects=True)
        except Exception:
            parsed = None

    return parsed if isinstance(parsed, dict) else None


def _extract_fenced_json_blocks(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    return [match.group(1).strip() for match in pattern.finditer(raw_text) if match.group(1).strip()]


def _extract_braced_json_candidates(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    candidates: List[str] = []
    stack = 0
    start_index: Optional[int] = None

    for index, char in enumerate(raw_text):
        if char == "{":
            if stack == 0:
                start_index = index
            stack += 1
        elif char == "}":
            if stack == 0:
                continue
            stack -= 1
            if stack == 0 and start_index is not None:
                candidate = raw_text[start_index : index + 1].strip()
                if candidate:
                    candidates.append(candidate)
                start_index = None

    return candidates


def try_parse_payload_candidates(raw_text: str) -> List[Dict[str, Any]]:
    candidates: List[str] = []
    seen: Set[str] = set()

    def add_candidate(candidate: str) -> None:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    for block in extract_structured_payload_blocks(raw_text):
        add_candidate(block)
    for block in _extract_fenced_json_blocks(raw_text):
        add_candidate(block)
    for block in _extract_braced_json_candidates(raw_text):
        add_candidate(block)
    add_candidate(raw_text)

    parsed_objects: List[Dict[str, Any]] = []
    for candidate in candidates:
        parsed = _try_parse_json_object(candidate)
        if isinstance(parsed, dict):
            parsed_objects.append(parsed)
    return parsed_objects


def extract_tool_calls(inner_data: Dict[str, Any], allowed_tool_names: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    raw_tool_calls = inner_data.get("toolCalls") or inner_data.get("tool_calls") or []
    return normalize_merlin_event_tool_calls(raw_tool_calls, allowed_tool_names)


def extract_tool_calls_from_json_payload(
    payload: Optional[Dict[str, Any]], allowed_tool_names: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    return resolve_tool_strategy_payload(payload, allowed_tool_names).dump_tool_calls()


def extract_single_tool_call_from_json_payload(
    payload: Optional[Dict[str, Any]], allowed_tool_names: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    return resolve_tool_strategy_payload(payload, allowed_tool_names).dump_tool_calls()


def _extract_message_content_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    return resolve_tool_strategy_payload(payload).message_content


def filter_allowed_tool_calls(response_tool_calls: List[Dict[str, Any]], allowed_tool_names: Set[str]) -> List[Dict[str, Any]]:
    return [
        tool_call
        for tool_call in response_tool_calls
        if tool_call.get("function", {}).get("name") in allowed_tool_names
    ]


def resolve_payload_result(raw_text: str, allowed_tool_names: Set[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    selected_tool_calls: List[Dict[str, Any]] = []
    selected_message_content: Optional[str] = None

    for payload in reversed(try_parse_payload_candidates(raw_text)):
        resolution = resolve_tool_strategy_payload(payload, allowed_tool_names)
        if not selected_tool_calls:
            selected_tool_calls = resolution.dump_tool_calls()
        if selected_message_content is None:
            selected_message_content = resolution.message_content
        if selected_tool_calls and selected_message_content is not None:
            return selected_tool_calls, selected_message_content

    return selected_tool_calls, selected_message_content
