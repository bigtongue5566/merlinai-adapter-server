import json
from typing import Any, Optional, Set

from json_repair import repair_json
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from .schemas import (
    JsonDict,
    NormalizedFunctionCall,
    NormalizedToolCall,
    ToolPromptMessagePayload,
    ToolPromptPayloadSchema,
    ToolPromptToolCallsPayload,
)

_JSON_OBJECT_ADAPTER = TypeAdapter(JsonDict)


class StructuredOutputResolution(BaseModel):
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    message_content: Optional[str] = None
    payload_type: Optional[str] = None

    def dump_tool_calls(self) -> list[JsonDict]:
        return [tool_call.model_dump() for tool_call in self.tool_calls]


def _parse_json_object(value: Any) -> Optional[JsonDict]:
    if isinstance(value, dict):
        try:
            return _JSON_OBJECT_ADAPTER.validate_python(value)
        except ValidationError:
            return None

    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return _JSON_OBJECT_ADAPTER.validate_json(value)
    except ValidationError:
        try:
            repaired = repair_json(value, return_objects=True)
        except Exception:
            return None

    if not isinstance(repaired, dict):
        return None

    try:
        return _JSON_OBJECT_ADAPTER.validate_python(repaired)
    except ValidationError:
        return None


def build_normalized_tool_call(
    *,
    name: str,
    arguments: JsonDict | str,
    call_id: Optional[str] = None,
) -> NormalizedToolCall:
    call_id_payload = {"id": call_id} if isinstance(call_id, str) and call_id else {}
    argument_text = json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else arguments
    return NormalizedToolCall(
        **call_id_payload,
        function=NormalizedFunctionCall(
            name=name,
            arguments=argument_text,
        ),
    )


def _is_allowed_tool_name(name: str, allowed_tool_names: Optional[Set[str]]) -> bool:
    return allowed_tool_names is None or name in allowed_tool_names


def _resolve_schema_payload(payload: ToolPromptPayloadSchema, allowed_tool_names: Optional[Set[str]]) -> StructuredOutputResolution:
    structured_payload = payload.root
    if isinstance(structured_payload, ToolPromptMessagePayload):
        return StructuredOutputResolution(
            message_content=structured_payload.content,
            payload_type=structured_payload.type,
        )

    if isinstance(structured_payload, ToolPromptToolCallsPayload):
        tool_calls = [
            build_normalized_tool_call(
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
            for tool_call in structured_payload.tool_calls
            if _is_allowed_tool_name(tool_call.name, allowed_tool_names)
        ]
        return StructuredOutputResolution(tool_calls=tool_calls, payload_type=structured_payload.type)

    return StructuredOutputResolution()


def _resolve_legacy_tool_call_payload(payload: JsonDict, allowed_tool_names: Optional[Set[str]]) -> StructuredOutputResolution:
    function_payload = payload.get("function")
    if not isinstance(function_payload, dict):
        return StructuredOutputResolution(payload_type=payload.get("type") if isinstance(payload.get("type"), str) else None)

    name = function_payload.get("name") or payload.get("name")
    if not isinstance(name, str) or not name or not _is_allowed_tool_name(name, allowed_tool_names):
        return StructuredOutputResolution(payload_type=payload.get("type") if isinstance(payload.get("type"), str) else None)

    arguments = _parse_json_object(function_payload.get("arguments", payload.get("arguments", {})))
    if arguments is None:
        return StructuredOutputResolution(payload_type=payload.get("type") if isinstance(payload.get("type"), str) else None)

    return StructuredOutputResolution(
        tool_calls=[build_normalized_tool_call(name=name, arguments=arguments, call_id=payload.get("id"))],
        payload_type=payload.get("type") if isinstance(payload.get("type"), str) else None,
    )


def _resolve_legacy_message_payload(payload: JsonDict) -> StructuredOutputResolution:
    payload_type = payload.get("type") if isinstance(payload.get("type"), str) else None
    if payload.get("type") == "message" and isinstance(payload.get("content"), str):
        return StructuredOutputResolution(message_content=payload["content"], payload_type=payload_type)
    if isinstance(payload.get("message"), str):
        return StructuredOutputResolution(message_content=payload["message"], payload_type=payload_type)
    if payload.get("type") in {None, "assistant"} and isinstance(payload.get("content"), str):
        return StructuredOutputResolution(message_content=payload["content"], payload_type=payload_type)
    return StructuredOutputResolution(payload_type=payload_type)


def resolve_tool_strategy_payload(payload: Any, allowed_tool_names: Optional[Set[str]] = None) -> StructuredOutputResolution:
    if not isinstance(payload, dict):
        return StructuredOutputResolution()

    try:
        return _resolve_schema_payload(ToolPromptPayloadSchema.model_validate(payload), allowed_tool_names)
    except ValidationError:
        pass

    legacy_tool_call = _resolve_legacy_tool_call_payload(payload, allowed_tool_names)
    legacy_message = _resolve_legacy_message_payload(payload)
    return StructuredOutputResolution(
        tool_calls=legacy_tool_call.tool_calls,
        message_content=legacy_message.message_content,
        payload_type=legacy_tool_call.payload_type or legacy_message.payload_type,
    )


def normalize_merlin_event_tool_calls(
    raw_tool_calls: Any,
    allowed_tool_names: Optional[Set[str]] = None,
) -> list[JsonDict]:
    if not isinstance(raw_tool_calls, list):
        return []

    normalized: list[JsonDict] = []
    for call in raw_tool_calls:
        if not isinstance(call, dict):
            continue

        function_payload = call.get("function")
        if not isinstance(function_payload, dict):
            continue

        function_name = function_payload.get("name")
        if not isinstance(function_name, str) or not function_name:
            continue
        if not _is_allowed_tool_name(function_name, allowed_tool_names):
            continue

        raw_arguments = function_payload.get("arguments")
        parsed_arguments = _parse_json_object(raw_arguments)
        if parsed_arguments is None and not isinstance(raw_arguments, str):
            continue

        normalized_call = build_normalized_tool_call(
            name=function_name,
            arguments=parsed_arguments if parsed_arguments is not None else raw_arguments,
            call_id=call.get("id"),
        )
        normalized.append(normalized_call.model_dump())

    return normalized
