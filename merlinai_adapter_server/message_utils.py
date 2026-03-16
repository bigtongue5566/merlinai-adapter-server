import json
import re
from typing import Any, Dict, List

from fastapi import HTTPException
from pydantic import BaseModel

from .config import (
    TOOL_MESSAGE_MAX_CHARS,
    TOOL_PROMPT_MAX_MESSAGES,
    TOOL_SYSTEM_MAX_CHARS,
    TOOL_TOOL_ARGUMENTS_MAX_CHARS,
    TOOL_TOOL_RESULT_MAX_CHARS,
)
from .protocol_constants import STRUCTURED_PAYLOAD_END, STRUCTURED_PAYLOAD_START
from .schemas import Message
from .tool_payload_parser import extract_structured_payload_blocks, try_parse_payload_candidates


def extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue

            if isinstance(item, BaseModel):
                item = item.model_dump(exclude_none=True)

            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("input_text"), str):
                    parts.append(item["input_text"])
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "".join(parts)

    return ""


def get_last_user_message(messages: List[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            text = extract_message_text(message.content)
            if text:
                return text
    raise HTTPException(status_code=400, detail="No user message content found")


def trim_text(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _message_has_prompt_content(message: Message) -> bool:
    if message.role == "assistant" and message.tool_calls:
        return True
    if message.role == "tool":
        return bool(extract_message_text(message.content) or message.name or message.tool_call_id)
    return bool(extract_message_text(message.content))


def _is_tool_interaction_message(message: Message) -> bool:
    return (
        message.role == "tool"
        or bool(message.tool_call_id)
        or (message.role == "assistant" and bool(message.tool_calls))
    )


def select_tool_prompt_messages(messages: List[Message]) -> List[Message]:
    prompt_messages = [message for message in messages if _message_has_prompt_content(message)]
    if not prompt_messages:
        return []

    non_system_messages = [message for message in prompt_messages if message.role != "system"]
    if not non_system_messages:
        return prompt_messages

    selected_non_system = non_system_messages[-TOOL_PROMPT_MAX_MESSAGES:]
    selected_non_system_ids = {id(message) for message in selected_non_system}
    return [
        message
        for message in prompt_messages
        if message.role == "system" or id(message) in selected_non_system_ids
    ]


def _normalize_prompt_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    return value


def _trim_prompt_value(value: Any, limit: int) -> Any:
    value = _normalize_prompt_value(value)
    if isinstance(value, str):
        return trim_text(value, limit)
    if isinstance(value, list):
        return [_trim_prompt_value(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _trim_prompt_value(item, limit) for key, item in value.items()}
    return value


def _serialize_tool_calls_for_prompt(tool_calls: Any) -> List[Dict[str, Any]]:
    serialized_tool_calls: List[Dict[str, Any]] = []
    for tool_call in tool_calls or []:
        normalized_tool_call = _normalize_prompt_value(tool_call)
        if not isinstance(normalized_tool_call, dict):
            continue

        serialized_tool_call: Dict[str, Any] = {}
        for key, value in normalized_tool_call.items():
            if key == "function" and isinstance(value, dict):
                serialized_function: Dict[str, Any] = {}
                for function_key, function_value in value.items():
                    if function_key == "arguments":
                        serialized_function[function_key] = _trim_prompt_value(
                            function_value,
                            TOOL_TOOL_ARGUMENTS_MAX_CHARS,
                        )
                    else:
                        serialized_function[function_key] = _trim_prompt_value(function_value, TOOL_MESSAGE_MAX_CHARS)
                serialized_tool_call[key] = serialized_function
                continue

            serialized_tool_call[key] = _trim_prompt_value(value, TOOL_MESSAGE_MAX_CHARS)

        if serialized_tool_call:
            serialized_tool_calls.append(serialized_tool_call)

    return serialized_tool_calls


def _serialize_message_content_for_prompt(message: Message) -> Any:
    if message.role == "tool":
        return _serialize_tool_content_for_prompt(message.content)

    content_limit = TOOL_MESSAGE_MAX_CHARS
    if message.role == "system":
        content_limit = TOOL_SYSTEM_MAX_CHARS

    return _trim_prompt_value(message.content, content_limit)


def _strip_structured_payload_blocks(raw_text: str) -> str:
    pattern = re.compile(
        re.escape(STRUCTURED_PAYLOAD_START) + r".*?(?:" +
        re.escape(STRUCTURED_PAYLOAD_END) + r"|" +
        re.escape(STRUCTURED_PAYLOAD_END.replace("/", r"\/")) +
        r")",
        re.DOTALL,
    )
    return pattern.sub("", raw_text).strip()


def _normalize_tool_raw_text(raw_text: str) -> str:
    normalized = raw_text
    empty_tag_pattern = re.compile(r"<([A-Za-z0-9_:-]+)>\s*</\1>", re.DOTALL)
    while True:
        updated = empty_tag_pattern.sub("", normalized)
        if updated == normalized:
            break
        normalized = updated
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _extract_tool_names_from_payload(payload: Dict[str, Any]) -> List[str]:
    tool_names: List[str] = []
    seen: set[str] = set()

    raw_tool_calls = payload.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        for tool_call in raw_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_name = tool_call.get("name")
            if isinstance(tool_name, str) and tool_name and tool_name not in seen:
                seen.add(tool_name)
                tool_names.append(tool_name)

    function_payload = payload.get("function")
    if isinstance(function_payload, dict):
        function_name = function_payload.get("name")
        if isinstance(function_name, str) and function_name and function_name not in seen:
            seen.add(function_name)
            tool_names.append(function_name)

    return tool_names


def _summarize_prior_payload_block(raw_block: str) -> Dict[str, Any]:
    parsed_payloads = try_parse_payload_candidates(raw_block)
    payload = parsed_payloads[0] if parsed_payloads else None

    if not isinstance(payload, dict):
        return {
            "type": "unknown",
            "raw_preview": trim_text(raw_block, TOOL_MESSAGE_MAX_CHARS),
        }

    summary: Dict[str, Any] = {
        "type": payload.get("type") if isinstance(payload.get("type"), str) and payload.get("type") else "unknown"
    }

    tool_names = _extract_tool_names_from_payload(payload)
    if tool_names:
        summary["tool_names"] = tool_names

    message_content = payload.get("content")
    if isinstance(message_content, str) and message_content.strip():
        summary["message_preview"] = trim_text(message_content.strip(), TOOL_MESSAGE_MAX_CHARS)

    return summary


def _serialize_tool_content_for_prompt(content: Any) -> Any:
    raw_text = extract_message_text(content)
    if not raw_text:
        return _trim_prompt_value(content, TOOL_TOOL_RESULT_MAX_CHARS)

    raw_blocks = extract_structured_payload_blocks(raw_text)
    if not raw_blocks:
        return trim_text(raw_text, TOOL_TOOL_RESULT_MAX_CHARS)

    sanitized_content: Dict[str, Any] = {
        "raw_text": trim_text(_normalize_tool_raw_text(_strip_structured_payload_blocks(raw_text)), TOOL_TOOL_RESULT_MAX_CHARS),
        "prior_payload_blocks": [_summarize_prior_payload_block(block) for block in raw_blocks],
    }
    return sanitized_content


def serialize_message_for_prompt(message: Message) -> Dict[str, Any]:
    serialized_message: Dict[str, Any] = {"role": message.role}
    if message.name:
        serialized_message["name"] = message.name
    if message.tool_call_id:
        serialized_message["tool_call_id"] = message.tool_call_id

    serialized_content = _serialize_message_content_for_prompt(message)
    if serialized_content not in (None, "", []):
        serialized_message["content"] = serialized_content

    serialized_tool_calls = _serialize_tool_calls_for_prompt(message.tool_calls)
    if serialized_tool_calls:
        serialized_message["tool_calls"] = serialized_tool_calls

    return serialized_message


def _looks_like_platform_system_message(message: Message) -> bool:
    if message.role != "system":
        return False

    text = extract_message_text(message.content).strip().lower()
    if not text:
        return False

    platform_markers = (
        "you are opencode",
        "interactive cli tool",
        "powered by the model named",
        "opencode.ai",
    )
    return any(marker in text for marker in platform_markers)


def _split_system_prompt_messages(messages: List[Message]) -> tuple[List[Message], List[Message]]:
    system_messages = [message for message in messages if message.role == "system"]
    if not system_messages:
        return [], []

    platform_messages = [message for message in system_messages if _looks_like_platform_system_message(message)]
    if platform_messages:
        platform_message_ids = {id(message) for message in platform_messages}
        user_messages = [message for message in system_messages if id(message) not in platform_message_ids]
        return platform_messages, user_messages

    if len(system_messages) >= 2:
        return system_messages[:1], system_messages[1:]

    return [], system_messages


def build_prompt_message_sections(messages: List[Message]) -> Dict[str, List[Dict[str, Any]]]:
    prompt_messages = select_tool_prompt_messages(messages)
    platform_system_source_messages, user_system_source_messages = _split_system_prompt_messages(prompt_messages)
    platform_system_message_ids = {id(message) for message in platform_system_source_messages}
    user_system_message_ids = {id(message) for message in user_system_source_messages}

    platform_system_messages: List[Dict[str, Any]] = []
    user_system_messages: List[Dict[str, Any]] = []
    conversation_messages: List[Dict[str, Any]] = []

    for message in prompt_messages:
        serialized_message = serialize_message_for_prompt(message)
        if message.role == "system":
            if id(message) in platform_system_message_ids:
                platform_system_messages.append(serialized_message)
            elif id(message) in user_system_message_ids:
                user_system_messages.append(serialized_message)
            else:
                user_system_messages.append(serialized_message)
            continue

        conversation_messages.append(serialized_message)

    return {
        "platform_system_messages": platform_system_messages,
        "user_system_messages": user_system_messages,
        "conversation_messages": conversation_messages,
    }


def build_prompt_message_sections_json(messages: List[Message]) -> Dict[str, str]:
    sections = build_prompt_message_sections(messages)
    return {
        "platform_system_messages_json": json.dumps(
            sections["platform_system_messages"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "user_system_messages_json": json.dumps(
            sections["user_system_messages"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "conversation_messages_json": json.dumps(
            sections["conversation_messages"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def build_non_tool_prompt(messages: List[Message]) -> tuple[str, Dict[str, Any]]:
    prompt_message_sections = build_prompt_message_sections(messages)
    prompt_message_sections_json = build_prompt_message_sections_json(messages)
    platform_system_messages_json = prompt_message_sections_json["platform_system_messages_json"]
    user_system_messages_json = prompt_message_sections_json["user_system_messages_json"]
    conversation_messages_json = prompt_message_sections_json["conversation_messages_json"]

    if not prompt_message_sections["conversation_messages"]:
        conversation_messages_json = json.dumps(
            [{"role": "user", "content": trim_text(get_last_user_message(messages), TOOL_MESSAGE_MAX_CHARS)}],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    prompt_parts = [
        "Follow the conversation state exactly.",
        "Platform System Messages JSON contains runtime or platform-level instructions.",
        "User System Messages JSON contains user-provided system instructions.",
        "Priority order:",
        "1. Follow Platform System Messages JSON first.",
        "2. Then follow User System Messages JSON when they do not conflict with platform instructions.",
        "3. Then use Conversation Messages JSON.",
        "If the system messages request a title, constrained format, or brief output, follow that exactly.",
        "Do not ignore system instructions just because the last user message looks open-ended.",
    ]
    if prompt_message_sections["platform_system_messages"]:
        prompt_parts.append(f"Platform System Messages JSON:\n{platform_system_messages_json}")
    if prompt_message_sections["user_system_messages"]:
        prompt_parts.append(f"User System Messages JSON:\n{user_system_messages_json}")
    prompt_parts.append(f"Conversation Messages JSON:\n{conversation_messages_json}")

    prompt = "\n".join(prompt_parts)
    metrics = {
        "original_message_count": len(messages),
        "prompt_message_count": len(select_tool_prompt_messages(messages)),
        "platform_system_message_count": len(prompt_message_sections["platform_system_messages"]),
        "user_system_message_count": len(prompt_message_sections["user_system_messages"]),
        "conversation_message_count": len(prompt_message_sections["conversation_messages"]),
        "platform_system_chars": len(platform_system_messages_json),
        "user_system_chars": len(user_system_messages_json),
        "conversation_chars": len(conversation_messages_json),
        "prompt_chars": len(prompt),
    }
    return prompt, metrics


def has_recent_tool_interaction(messages: List[Message], window: int = 6) -> bool:
    recent_messages = messages[-window:] if window > 0 else messages
    return any(_is_tool_interaction_message(message) for message in recent_messages)


def count_recent_tool_interactions(messages: List[Message], window: int = 8) -> int:
    recent_messages = messages[-window:] if window > 0 else messages
    return sum(1 for message in recent_messages if _is_tool_interaction_message(message))


def last_message_is_tool_output(messages: List[Message]) -> bool:
    if not messages:
        return False

    last_message = messages[-1]
    return last_message.role == "tool"


def last_message_is_tool_result(messages: List[Message]) -> bool:
    if not messages:
        return False
    return _is_tool_interaction_message(messages[-1])
