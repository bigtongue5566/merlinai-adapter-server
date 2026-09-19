"""Native extension protocol policy and strict tool-call validation."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

from .schemas import OpenAIRequest, model_dump_compat


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


@dataclass(frozen=True)
class NativeToolPolicy:
    """Resolved caller tool policy for the native extension endpoint."""

    tools: List[Any]
    allowed_tool_names: Set[str]


def validate_native_tool_choice(choice: Any) -> Optional[str]:
    """Return the supported mode or raise before any request is opened."""
    choice = model_dump_compat(choice)
    if choice is None:
        return None
    if isinstance(choice, str):
        mode = choice
    elif isinstance(choice, dict):
        if choice.get("type") == "function":
            function = choice.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str) and name.strip():
                raise HTTPException(422, "Named tool_choice is not supported by this adapter native transport")
            raise HTTPException(422, "Invalid function tool_choice for this adapter native transport")
        raise HTTPException(422, "Invalid tool_choice for this adapter native transport")
    else:
        raise HTTPException(422, "Invalid tool_choice for the native Merlin endpoint")

    if mode == "required" or (isinstance(mode, str) and mode.startswith("function:")):
        raise HTTPException(422, "Required or named tool_choice is not supported by this adapter native transport")
    if mode not in {None, "auto", "none"}:
        raise HTTPException(422, f"Invalid tool_choice: {mode}")
    return mode


def resolve_native_tool_policy(request: OpenAIRequest) -> NativeToolPolicy:
    """Validate the supported OpenAI tool modes before opening the network.

    Merlin's extension endpoint has no verified equivalent for required or
    named tool selection.  Auto and omitted choices can still forward the
    caller's explicit schemas; ``none`` deliberately sends an empty schema.
    """
    mode = validate_native_tool_choice(request.tool_choice)

    if mode == "none":
        return NativeToolPolicy(tools=[], allowed_tool_names=set())

    tools = list(request.tools or [])
    names: Set[str] = set()
    for tool in tools:
        payload = model_dump_compat(tool)
        if not isinstance(payload, dict) or payload.get("type") != "function":
            raise HTTPException(422, "Only function tools are supported by this adapter native transport")
        function = payload.get("function") if isinstance(payload, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(function, dict) or not isinstance(name, str) or not name.strip():
            raise HTTPException(422, "Function tools must include a non-empty function name")
        names.add(name)
    return NativeToolPolicy(tools=tools, allowed_tool_names=names)


def normalize_native_tool_calls(
    raw_tool_calls: Any,
    allowed_tool_names: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    """Normalize only structured native calls; never repair or filter errors."""
    if not isinstance(raw_tool_calls, list):
        raise HTTPException(502, "Merlin returned malformed native tool calls")

    normalized: List[Dict[str, Any]] = []
    for call in raw_tool_calls:
        if not isinstance(call, dict):
            raise HTTPException(502, "Merlin returned a malformed native tool call")
        call_id = call.get("id")
        function = call.get("function")
        if not isinstance(call.get("type"), str) or call.get("type") != "function":
            raise HTTPException(502, "Merlin native tool call must have type=function")
        if not isinstance(call_id, str) or not call_id.strip() or not isinstance(function, dict):
            raise HTTPException(502, "Merlin native tool call is missing id or function")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(502, "Merlin native tool call is missing function name")
        if name not in (allowed_tool_names or set()):
            raise HTTPException(502, f"Merlin returned undeclared tool call: {name}")

        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            try:
                argument_text = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise HTTPException(502, "Merlin native tool arguments are not valid JSON") from exc
        elif isinstance(arguments, str):
            try:
                parsed = json.loads(arguments, parse_constant=_reject_nonfinite_json_constant)
            except (TypeError, ValueError) as exc:
                raise HTTPException(502, "Merlin native tool arguments are not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise HTTPException(502, "Merlin native tool arguments must be a JSON object")
            # Preserve the provider's original argument string exactly.
            argument_text = arguments
        else:
            raise HTTPException(502, "Merlin native tool call is missing arguments")

        normalized.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": argument_text},
            }
        )
    return normalized
