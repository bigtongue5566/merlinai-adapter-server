import json
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Union

from fastapi import HTTPException

from .config import TOOL_DESCRIPTION_MAX_CHARS, TOOL_MESSAGE_MAX_CHARS, TOOL_PARAMETER_DESCRIPTION_MAX_CHARS
from .message_utils import (
    build_prompt_message_sections,
    build_prompt_message_sections_json,
    count_recent_tool_interactions,
    get_last_user_message,
    has_recent_tool_interaction,
    last_message_is_tool_result,
    select_tool_prompt_messages,
    trim_text,
)
from .protocol_constants import STRUCTURED_PAYLOAD_END, STRUCTURED_PAYLOAD_START, ToolPromptMode
from .schemas import OpenAIRequest


def normalize_tool_choice(tool_choice: Optional[Union[str, Dict[str, Any]]]) -> Optional[str]:
    if isinstance(tool_choice, str):
        return tool_choice

    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            function_name = tool_choice.get("function", {}).get("name")
            if isinstance(function_name, str) and function_name:
                return f"function:{function_name}"

        raw_type = tool_choice.get("type")
        if isinstance(raw_type, str) and raw_type:
            return raw_type

    return None


def should_force_tool_json(request: OpenAIRequest) -> bool:
    return bool(request.tools)


def _compact_tool_parameters(parameters: Any) -> Any:
    if not isinstance(parameters, dict):
        return None

    compact: Dict[str, Any] = {}
    schema_type = parameters.get("type")
    if isinstance(schema_type, str) and schema_type:
        compact["type"] = schema_type
    elif isinstance(schema_type, list) and schema_type:
        compact["type"] = [item for item in schema_type if isinstance(item, str)]

    description = parameters.get("description")
    if isinstance(description, str) and description.strip():
        compact["description"] = trim_text(description.strip(), TOOL_PARAMETER_DESCRIPTION_MAX_CHARS)

    title = parameters.get("title")
    if isinstance(title, str) and title.strip():
        compact["title"] = trim_text(title.strip(), TOOL_PARAMETER_DESCRIPTION_MAX_CHARS)

    required = parameters.get("required")
    if isinstance(required, list) and required:
        compact["required"] = [item for item in required if isinstance(item, str)]

    enum_values = parameters.get("enum")
    if isinstance(enum_values, list) and enum_values:
        compact["enum"] = [item for item in enum_values if not isinstance(item, (dict, list))]

    for numeric_key in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"):
        numeric_value = parameters.get(numeric_key)
        if isinstance(numeric_value, (int, float)):
            compact[numeric_key] = numeric_value

    pattern = parameters.get("pattern")
    if isinstance(pattern, str) and pattern:
        compact["pattern"] = trim_text(pattern, TOOL_PARAMETER_DESCRIPTION_MAX_CHARS)

    format_value = parameters.get("format")
    if isinstance(format_value, str) and format_value:
        compact["format"] = format_value

    additional_properties = parameters.get("additionalProperties")
    if isinstance(additional_properties, bool):
        compact["additionalProperties"] = additional_properties
    elif isinstance(additional_properties, dict):
        compact_additional_properties = _compact_tool_parameters(additional_properties)
        if compact_additional_properties:
            compact["additionalProperties"] = compact_additional_properties

    properties = parameters.get("properties")
    if isinstance(properties, dict) and properties:
        compact_properties: Dict[str, Any] = {}
        for name, raw_property in properties.items():
            if not isinstance(name, str) or not isinstance(raw_property, dict):
                continue

            property_payload = _compact_tool_parameters(raw_property)
            if property_payload:
                compact_properties[name] = property_payload

        if compact_properties:
            compact["properties"] = compact_properties

    items = parameters.get("items")
    if isinstance(items, dict):
        compact_items = _compact_tool_parameters(items)
        if compact_items:
            compact["items"] = compact_items
    elif isinstance(items, list) and items:
        compact_items_list = [
            compact_item for raw_item in items if isinstance(raw_item, dict)
            if (compact_item := _compact_tool_parameters(raw_item))
        ]
        if compact_items_list:
            compact["items"] = compact_items_list

    for composite_key in ("anyOf", "oneOf", "allOf"):
        composite_value = parameters.get(composite_key)
        if isinstance(composite_value, list) and composite_value:
            compact_composite = [
                compact_item for raw_item in composite_value if isinstance(raw_item, dict)
                if (compact_item := _compact_tool_parameters(raw_item))
            ]
            if compact_composite:
                compact[composite_key] = compact_composite

    default_value = parameters.get("default")
    if default_value is not None and not isinstance(default_value, (dict, list)):
        compact["default"] = default_value

    return compact or None


def compact_tools_for_prompt(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [deepcopy(tool) for tool in tools or [] if isinstance(tool, dict)]


def get_allowed_tool_names(request: OpenAIRequest) -> Set[str]:
    allowed_names: Set[str] = set()
    for tool in request.tools or []:
        if not isinstance(tool, dict):
            continue

        function_payload = tool.get("function")
        if not isinstance(function_payload, dict):
            continue

        name = function_payload.get("name")
        if isinstance(name, str) and name:
            allowed_names.add(name)

    return allowed_names


def _count_complex_tool_schemas(tools: Optional[List[Dict[str, Any]]]) -> int:
    count = 0
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function_payload = tool.get("function")
        if not isinstance(function_payload, dict):
            continue
        parameters = function_payload.get("parameters")
        if not isinstance(parameters, dict):
            continue

        properties = parameters.get("properties")
        if isinstance(properties, dict) and properties:
            count += 1
            continue

        required = parameters.get("required")
        if isinstance(required, list) and required:
            count += 1

    return count


def is_agent_like_tool_context(request: OpenAIRequest) -> bool:
    if not request.tools:
        return False

    score = 0
    if has_recent_tool_interaction(request.messages):
        score += 2
    if count_recent_tool_interactions(request.messages) >= 2:
        score += 1
    if last_message_is_tool_result(request.messages):
        score += 2
    if len(request.tools) >= 4:
        score += 1
    if _count_complex_tool_schemas(request.tools) >= 3:
        score += 1

    return score >= 4


def _build_tool_choice_guidance(tool_choice: str) -> List[str]:
    if tool_choice == "auto":
        return [
            "Tool choice mode: auto.",
        ]

    if tool_choice == "required":
        return [
            "Tool choice mode: required.",
        ]

    if tool_choice == "none":
        return [
            "Tool choice mode: none.",
        ]

    if tool_choice.startswith("function:"):
        tool_name = tool_choice.split(":", 1)[1].strip()
        if tool_name:
            return [
                "Tool choice mode: specific function.",
                f'Allowed tool for this response: "{tool_name}".',
            ]

    return [
        f"Tool choice mode: {tool_choice}.",
        "Follow this tool choice exactly.",
    ]


def _build_tool_response_guidance(tool_choice: str) -> List[str]:
    if tool_choice == "none":
        return [
            "Return a message payload only.",
            "Do not emit any tool_calls.",
        ]

    if tool_choice == "required":
        return [
            "Return tool_calls.",
            "Do not emit a message payload.",
        ]

    if tool_choice.startswith("function:"):
        return [
            "Return tool_calls.",
            "Do not emit a message payload.",
        ]

    return [
        "You may return either tool_calls or message.",
        "Prefer tool_calls when any available tool can advance the task.",
        "Use tool_calls whenever an available tool can continue the workflow.",
        "If the conversation is already in a tool workflow, prefer tool_calls over message.",
        "Use message only when no available tool can advance the conversation.",
    ]


def _build_tool_name_guidance(tool_choice: str, *, available_tools_label: str) -> List[str]:
    if tool_choice == "none":
        return []

    if tool_choice.startswith("function:"):
        tool_name = tool_choice.split(":", 1)[1].strip()
        if tool_name:
            return [f'If you emit tool_calls, the only valid tool name is "{tool_name}".']

    return [f"Every tool_calls.name must exactly match a tool name from {available_tools_label}."]


def _build_execution_environment_guidance(tool_names: Set[str]) -> List[str]:
    guidance = [
        "Use only tools from Available Tools JSON.",
    ]

    if "task" in tool_names:
        guidance.append("For open-ended or multi-step work, prefer the task tool.")

    return guidance


def _build_tool_prompt_instructions(mode: ToolPromptMode, tool_choice: str) -> List[str]:
    payload_schema = (
        '{"type":"tool_calls","tool_calls":[{"name":"tool_name","arguments":{}}]} '
        'or {"type":"message","content":"final answer"}'
    )
    tool_choice_guidance = _build_tool_choice_guidance(tool_choice)
    tool_response_guidance = _build_tool_response_guidance(tool_choice)
    base_tool_name_guidance = _build_tool_name_guidance(tool_choice, available_tools_label="Tools")
    base_instructions = [
        "Return exactly one payload block and nothing else.",
        f"Block format: {STRUCTURED_PAYLOAD_START}{payload_schema}{STRUCTURED_PAYLOAD_END}",
        *tool_choice_guidance,
        *tool_response_guidance,
        *base_tool_name_guidance,
        "arguments must be a JSON object.",
        "No markdown. No explanation outside the payload block.",
        "Examples:",
        'User asks to read a file and read exists -> '
        f'{STRUCTURED_PAYLOAD_START}{{"type":"tool_calls","tool_calls":[{{"name":"read","arguments":{{"filePath":"notes.txt"}}}}]}}{STRUCTURED_PAYLOAD_END}',
        'User asks a normal question with no tool needed -> '
        f'{STRUCTURED_PAYLOAD_START}{{"type":"message","content":"final answer"}}{STRUCTURED_PAYLOAD_END}',
    ]

    if mode == "repair":
        return [
            "Your previous answer was invalid.",
            "Re-emit only one valid payload block.",
            "Do not explain or apologize.",
            *tool_choice_guidance,
            *tool_response_guidance,
            *_build_tool_name_guidance(tool_choice, available_tools_label="Tools"),
            f"Allowed JSON schema: {payload_schema}",
            f"Output must start with {STRUCTURED_PAYLOAD_START} and end with {STRUCTURED_PAYLOAD_END}.",
        ]

    if mode == "strict":
        return [
            "Return exactly one payload block and nothing else.",
            f"Block format: {STRUCTURED_PAYLOAD_START}{payload_schema}{STRUCTURED_PAYLOAD_END}",
            *tool_choice_guidance,
            "Platform System Messages JSON contains runtime or platform-level instructions.",
            "User System Messages JSON contains user-provided system instructions.",
            "Priority order:",
            "1. Follow Platform System Messages JSON first.",
            "2. Then follow User System Messages JSON when they do not conflict with platform instructions.",
            "3. Then use Conversation Messages JSON and Available Tools JSON.",
            "Conversation Messages JSON preserves the recent message, tool call, and tool result state.",
            *tool_response_guidance,
            *_build_tool_name_guidance(tool_choice, available_tools_label="Available Tools JSON"),
            "arguments must be a JSON object.",
            "No markdown. No explanation outside the payload block.",
        ]

    return base_instructions


def build_tool_prompt(
    request: OpenAIRequest, mode: ToolPromptMode = "default", previous_response: Optional[str] = None
) -> tuple[str, Dict[str, Any]]:
    tool_choice = normalize_tool_choice(request.tool_choice) or "auto"
    allowed_tool_names = get_allowed_tool_names(request)
    compact_tools = compact_tools_for_prompt(request.tools)
    tools_json = json.dumps(compact_tools, ensure_ascii=False, separators=(",", ":"))
    prompt_message_sections = build_prompt_message_sections(request.messages)
    prompt_message_sections_json = build_prompt_message_sections_json(request.messages)
    platform_system_messages_json = prompt_message_sections_json["platform_system_messages_json"]
    user_system_messages_json = prompt_message_sections_json["user_system_messages_json"]
    conversation_messages_json = prompt_message_sections_json["conversation_messages_json"]
    if not prompt_message_sections["conversation_messages"]:
        conversation_messages_json = json.dumps(
            [{"role": "user", "content": trim_text(get_last_user_message(request.messages), TOOL_MESSAGE_MAX_CHARS)}],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    prompt_parts = _build_tool_prompt_instructions(mode, tool_choice)
    prompt_parts.extend(_build_execution_environment_guidance(allowed_tool_names))

    if prompt_message_sections["platform_system_messages"]:
        prompt_parts.append(f"Platform System Messages JSON:\n{platform_system_messages_json}")
    if prompt_message_sections["user_system_messages"]:
        prompt_parts.append(f"User System Messages JSON:\n{user_system_messages_json}")
    prompt_parts.extend(
        [
            f"Conversation Messages JSON:\n{conversation_messages_json}",
            f"Available Tools JSON:\n{tools_json}",
        ]
    )
    if previous_response:
        prompt_parts.append(f"Previous invalid response:\n{trim_text(previous_response, TOOL_MESSAGE_MAX_CHARS)}")
    prompt = "\n".join(prompt_parts)

    metrics = {
        "mode": mode,
        "original_message_count": len(request.messages),
        "prompt_message_count": len(select_tool_prompt_messages(request.messages)),
        "platform_system_message_count": len(prompt_message_sections["platform_system_messages"]),
        "user_system_message_count": len(prompt_message_sections["user_system_messages"]),
        "conversation_message_count": len(prompt_message_sections["conversation_messages"]),
        "original_tools_count": len(request.tools or []),
        "messages_chars": len(platform_system_messages_json) + len(user_system_messages_json) + len(conversation_messages_json),
        "platform_system_chars": len(platform_system_messages_json),
        "user_system_chars": len(user_system_messages_json),
        "conversation_chars": len(conversation_messages_json),
        "tools_chars": len(tools_json),
        "prompt_chars": len(prompt),
    }
    return prompt, metrics


def should_retry_tool_response(request: OpenAIRequest, exc: HTTPException) -> bool:
    if not should_force_tool_json(request) or exc.status_code != 422:
        return False

    detail = exc.detail if isinstance(exc.detail, str) else ""
    if detail == "Tool mode was enabled, but upstream did not return a valid structured JSON payload.":
        return True
    if detail == "Tool-capable request was answered with plain text instead of a tool call payload.":
        return True
    if detail == "Tool calling was required, but upstream did not return a valid tool call payload.":
        return True
    return isinstance(detail, str) and detail.startswith("Specific tool call was required (")
