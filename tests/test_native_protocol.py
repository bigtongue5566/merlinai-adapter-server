import io
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from merlinai_adapter_server.merlin_client import ChatCompletionContext, MerlinGateway, MerlinOpenAIClient
from merlinai_adapter_server.native_protocol import normalize_native_tool_calls, resolve_native_tool_policy
from merlinai_adapter_server.request_logging import get_attempt, get_request_id
from merlinai_adapter_server.schemas import OpenAIRequest


TOOL = {
    "type": "function",
    "function": {"name": "echo", "parameters": {"type": "object"}},
}


class NativeProtocolTests(unittest.TestCase):
    def request(self, **kwargs):
        return OpenAIRequest(model="gpt-5.6-luna", messages=[{"role": "user", "content": "hi"}], **kwargs)

    def test_auto_and_unspecified_forward_explicit_schemas(self):
        for choice in (None, "auto"):
            policy = resolve_native_tool_policy(self.request(tools=[TOOL], tool_choice=choice))
            self.assertEqual(policy.tools[0].model_dump(exclude_none=True), TOOL)
            self.assertEqual(policy.allowed_tool_names, {"echo"})

    def test_none_sends_empty_tools(self):
        request = self.request(tools=[TOOL], tool_choice="none")
        policy = resolve_native_tool_policy(request)
        self.assertEqual(policy.tools, [])
        payload = MerlinGateway().build_payload(
            model=request.model,
            messages=[message.model_dump(exclude_none=True) for message in request.messages],
            tools=request.tools,
            tool_choice=request.tool_choice,
        )
        self.assertEqual(payload["params"]["tools"], [])

    def test_required_named_and_invalid_choices_fail_before_network(self):
        for choice in ("required", "function:echo", "bogus", {"type": "function", "function": {"name": "echo"}}):
            request = self.request(tools=[TOOL], tool_choice=choice)
            client = MerlinOpenAIClient(MerlinGateway())
            with patch.object(MerlinGateway, "open_request", side_effect=AssertionError("network opened")):
                with self.assertRaises(HTTPException) as raised:
                    client.execute_chat_completion(request)
            self.assertEqual(raised.exception.status_code, 422)

    def test_required_and_named_fail_before_network_for_stream_and_nonstream(self):
        for stream in (False, True):
            for choice in ("required", "function:echo", {"type": "function", "function": {"name": "echo"}}):
                request = self.request(tools=[TOOL], tool_choice=choice, stream=stream)
                client = MerlinOpenAIClient(MerlinGateway())
                with patch.object(MerlinGateway, "open_request", side_effect=AssertionError("network opened")):
                    if stream:
                        with self.assertRaises(HTTPException) as raised:
                            client.open_chat_completion_stream(request)
                    else:
                        with self.assertRaises(HTTPException) as raised:
                            client.execute_chat_completion(request)
                self.assertEqual(raised.exception.status_code, 422)
                self.assertIsNone(get_attempt())
                self.assertIsNone(get_request_id())

    def test_legacy_gateway_payload_is_retired(self):
        with self.assertRaisesRegex(ValueError, "legacy user_message payload is retired"):
            MerlinGateway().build_payload(model="gpt-5.6-luna", user_message="old")

    def test_legacy_user_message_is_rejected_even_with_native_messages(self):
        with self.assertRaisesRegex(ValueError, "legacy user_message payload is retired"):
            MerlinGateway().build_payload(
                model="gpt-5.6-luna",
                user_message="old",
                messages=[{"role": "user", "content": "new"}],
            )

    def test_strict_normalizer_requires_declared_structured_calls(self):
        call = {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{ "x": 1 }'}}
        normalized = normalize_native_tool_calls([call], {"echo"})
        self.assertEqual(normalized[0]["function"]["arguments"], '{ "x": 1 }')
        for bad in (
            [{"id": "", "type": "function", "function": {"name": "echo", "arguments": "{}"}}],
            [{"id": "call_1", "type": "function", "function": {"name": "other", "arguments": "{}"}}],
            [{"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": "{broken"}}],
            [{"id": "call_1", "type": "custom", "function": {"name": "echo", "arguments": "{}"}}],
            [{"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": "NaN"}}],
            [{"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"x": NaN}'}}],
            [{"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"x": Infinity}'}}],
            [{"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": {"x": float("nan")}}}],
        ):
            with self.assertRaises(HTTPException) as raised:
                normalize_native_tool_calls(bad, {"echo"})
            self.assertEqual(raised.exception.status_code, 502)

    def test_text_that_looks_like_json_is_preserved(self):
        source = b'event: message\ndata: {"data":{"type":"text","text":"{\\"function\\":{\\"name\\":\\"echo\\"}}"}}\n\nevent: message\ndata: {"data":{"eventType":"DONE"}}\n\n'
        events = list(MerlinGateway().iter_event_stream(io.BytesIO(source), set()))
        self.assertIn('"function"', events[0].content_delta)
        self.assertEqual(events[0].tool_calls, [])

    def test_embedded_malformed_tool_field_is_not_ignored(self):
        source = b'event: message\ndata: {"data":{"tool_calls":{}}}\n\nevent: message\ndata: {"data":{"eventType":"DONE"}}\n\n'
        with self.assertRaises(HTTPException) as raised:
            list(MerlinGateway().iter_event_stream(io.BytesIO(source), {"echo"}))
        self.assertEqual(raised.exception.status_code, 502)

    def test_valid_json_argument_string_is_preserved_verbatim(self):
        source = '{ "x": 1, "nested": [true, null] }'
        call = {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": source}}
        self.assertEqual(normalize_native_tool_calls([call], {"echo"})[0]["function"]["arguments"], source)

    def test_non_function_tool_type_is_rejected_before_network(self):
        with self.assertRaises(HTTPException) as raised:
            resolve_native_tool_policy(self.request(tools=[{"type": "custom", "function": {"name": "echo"}}]))
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
