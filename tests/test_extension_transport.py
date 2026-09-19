import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from merlinai_adapter_server.merlin_client import ChatCompletionContext, MerlinGateway, MerlinOpenAIClient
from merlinai_adapter_server.merlin_sse import iter_merlin_sse
from merlinai_adapter_server.openai_response_builder import build_native_openai_response, build_stream_chunk
from merlinai_adapter_server.schemas import OpenAIRequest


TOOL = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Echo text",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
}


class ExtensionTransportTests(unittest.TestCase):
    def test_extension_headers_use_configured_version_and_origin(self):
        with patch("merlinai_adapter_server.merlin_client.MERLIN_VERSION", "test-extension-version"), patch(
            "merlinai_adapter_server.merlin_client.MERLIN_ORIGIN",
            "chrome-extension://test-extension-id",
        ), patch("merlinai_adapter_server.merlin_client.token_manager.get_access_token", return_value="test-token"):
            headers = MerlinGateway()._get_headers()
        self.assertEqual(headers["x-merlin-version"], "test-extension-version")
        self.assertEqual(headers["origin"], "chrome-extension://test-extension-id")
        self.assertNotIn("referer", headers)
        self.assertNotIn("x-request-timestamp", headers)

    def test_native_payload_preserves_messages_and_does_not_add_extension_tools(self):
        request = OpenAIRequest(
            model="gpt-5.6-luna",
            messages=[
                {"role": "system", "content": "policy", "_tag": "user_time"},
                {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            ],
            max_tokens=123,
        )
        payload = MerlinGateway().build_payload(
            model=request.model,
            messages=[message.model_dump(exclude_none=True) for message in request.messages],
            tools=[],
            max_tokens=request.max_tokens,
        )
        self.assertEqual(payload["messages"][0]["_tag"], "user_time")
        self.assertEqual(payload["messages"][1]["content"][0]["text"], "hello")
        self.assertEqual(payload["params"], {"tools": [], "max_tokens": 123})
        self.assertEqual(payload["metadata"], {"isMCPEnabled": True})

    def test_client_converts_string_user_content_to_native_text_part(self):
        request = OpenAIRequest(model="gpt-5.6-luna", messages=[{"role": "user", "content": "hello"}])
        payload = MerlinOpenAIClient(MerlinGateway())._build_merlin_payload(
            request, ChatCompletionContext.from_request(request)
        )
        self.assertEqual(payload["messages"][0]["content"], [{"type": "text", "text": "hello"}])

    def test_sse_parser_handles_native_events_and_fragmented_lines(self):
        source = (
            b"event: message\r\ndata: {\"data\":{\"type\":\"text\",\"text\":\"hel\"}}\r\n\r\n"
            b"event: tool_calls\r\ndata: [{\"id\":\"call_1\",\"type\":\"function\",\"function\":{\"name\":\"echo\",\"arguments\":\"{\\\"text\\\":\\\"ok\\\"}\"}}]\r\n\r\n"
            b"event: usage\r\ndata: {\"tokens\":{\"input\":4,\"output\":2}}\r\n\r\n"
            b"event: message\r\ndata: {\"data\":{\"eventType\":\"DONE\"}}\r\n\r\n"
        )
        events = list(iter_merlin_sse(io.BytesIO(source)))
        self.assertEqual([event.name for event in events], ["message", "tool_calls", "usage"])
        self.assertEqual(events[0].data["data"]["text"], "hel")
        self.assertEqual(events[1].data[0]["function"]["name"], "echo")
        self.assertEqual(events[2].data["tokens"]["output"], 2)

    def test_gateway_extracts_native_text_tools_and_usage(self):
        source = (
            b"event: message\ndata: {\"data\":{\"type\":\"text\",\"text\":\"hi\"}}\n\n"
            b"event: tool_calls\ndata: [{\"id\":\"call_1\",\"type\":\"function\",\"function\":{\"name\":\"echo\",\"arguments\":\"{}\"}}]\n\n"
            b"event: usage\ndata: {\"tokens\":{\"input\":1,\"output\":1}}\n\n"
            b"event: message\ndata: {\"data\":{\"eventType\":\"DONE\"}}\n\n"
        )
        events = list(MerlinGateway().iter_event_stream(io.BytesIO(source), {"echo"}))
        self.assertEqual(events[0].content_delta, "hi")
        self.assertEqual(events[1].tool_calls[0]["function"]["name"], "echo")
        self.assertEqual(events[2].usage["tokens"]["input"], 1)

    def test_sse_error_and_missing_done_are_failures(self):
        with self.assertRaises(HTTPException) as error:
            list(iter_merlin_sse(io.BytesIO(b"event: error\ndata: {\"type\":\"INTERNAL\"}\n\n")))
        self.assertEqual(error.exception.status_code, 502)
        with self.assertRaises(HTTPException) as nested_error:
            list(iter_merlin_sse(io.BytesIO(b"event: message\ndata: {\"eventType\":\"ERROR\"}\n\n")))
        self.assertEqual(nested_error.exception.status_code, 502)
        with self.assertRaises(HTTPException) as incomplete:
            list(iter_merlin_sse(io.BytesIO(b"event: message\ndata: {\"data\":{\"text\":\"ok\"}}\n\n")))
        self.assertEqual(incomplete.exception.status_code, 502)

    def test_native_response_maps_usage_and_never_parses_text_as_tool(self):
        request = OpenAIRequest(model="gpt-5.6-luna", messages=[{"role": "user", "content": "hello"}], tools=[TOOL])
        response = build_native_openai_response(
            request,
            '{"type":"tool_calls","tool_calls":[{"name":"echo"}]}',
            [],
            {"tokens": {"input": 7, "output": 3}},
        )
        self.assertEqual(response["choices"][0]["finish_reason"], "stop")
        self.assertNotIn("tool_calls", response["choices"][0]["message"])
        self.assertEqual(response["usage"], {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})

    def test_native_response_maps_structured_tool_event(self):
        request = OpenAIRequest(model="gpt-5.6-luna", messages=[{"role": "user", "content": "call it"}], tools=[TOOL])
        response = build_native_openai_response(
            request,
            "",
            [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"text":"ok"}'},
            }],
        )
        self.assertEqual(response["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(response["choices"][0]["message"]["tool_calls"][0]["id"], "call_1")

    def test_usage_stream_chunk_has_empty_choices(self):
        payload = json.loads(
            build_stream_chunk("chatcmpl-test", 1, "gpt-5.6-luna", {}, None, {"tokens": {"input": 1, "output": 2}})
            .removeprefix("data: ")
            .strip()
        )
        self.assertEqual(payload["choices"], [])
        self.assertEqual(payload["usage"]["total_tokens"], 3)


if __name__ == "__main__":
    unittest.main()
