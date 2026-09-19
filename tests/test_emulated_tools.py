import io
import json
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from merlinai_adapter_server.app import app
from merlinai_adapter_server.config import AdapterSettings
from merlinai_adapter_server.merlin_client import merlin_gateway, merlin_openai_client
from merlinai_adapter_server.protocol_constants import STRUCTURED_PAYLOAD_END, STRUCTURED_PAYLOAD_START


TOOL = {"type": "function", "function": {"name": "read", "parameters": {
    "type": "object", "properties": {"filePath": {"type": "string"}},
    "required": ["filePath"], "additionalProperties": False,
}}}


def envelope(payload):
    return STRUCTURED_PAYLOAD_START + json.dumps(payload) + STRUCTURED_PAYLOAD_END


def call(name="read", arguments=None):
    return {"type": "tool_calls", "tool_calls": [{"name": name,
            "arguments": {"filePath": "fixture.txt"} if arguments is None else arguments}]}


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def upstream(text, *, done=True):
    # Split in the middle of protocol JSON to exercise buffering across frames.
    midpoint = len(text) // 2
    result = event("message", {"data": {"text": text[:midpoint]}})
    result += event("message", {"data": {"text": text[midpoint:]}})
    result += event("usage", {"tokens": {"input": 23, "output": 12}})
    if done:
        result += event("message", {"data": {"eventType": "DONE"}})
    return result


class EmulatedToolsTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.object(merlin_openai_client, "tool_call_mode", "emulated"),
            patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.payloads = []
        self.connections = []

    def post(self, source, **fields):
        body = {"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "Read fixture"}],
                "tools": [TOOL], **fields}
        def open_request(payload):
            self.payloads.append(payload)
            connection = Mock()
            self.connections.append(connection)
            return connection, io.BytesIO(source)
        with patch.object(merlin_gateway, "open_request", side_effect=open_request):
            response = self.client.post("/v1/chat/completions", json=body,
                                        headers={"Authorization": "Bearer test-key"})
        self.assertTrue(all(c.close.called for c in self.connections))
        return response

    def assert_failure(self, response, stream):
        if stream:
            self.assertEqual(response.status_code, 200)
            self.assertIn('"code": 502', response.text)
            self.assertNotIn('"finish_reason": "tool_calls"', response.text)
            self.assertNotIn('"finish_reason": "stop"', response.text)
            self.assertNotIn('"tool_calls":', response.text)
            self.assertNotIn("data: [DONE]", response.text)
            self.assertNotIn(STRUCTURED_PAYLOAD_START, response.text)
        else:
            self.assertEqual(response.status_code, 502)

    def test_call_and_full_tool_result_round_trip(self):
        response = self.post(upstream(envelope(call())))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        choice = body["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertIsNone(choice["message"]["content"])
        tool_call = choice["message"]["tool_calls"][0]
        self.assertTrue(tool_call["id"].startswith("call_"))
        self.assertEqual(json.loads(tool_call["function"]["arguments"]), {"filePath": "fixture.txt"})
        self.assertEqual(body["usage"]["total_tokens"], 35)
        self.assertEqual(self.payloads[0]["params"]["tools"], [])
        self.assertIn('"required": ["filePath"]', self.payloads[0]["messages"][0]["content"])

        long_output = "START " + "完整資料 " * 3000 + " END"
        history = [{"role": "system", "content": "Keep this instruction."},
                   {"role": "developer", "content": "Keep this developer instruction."},
                   {"role": "user", "content": "Read fixture"}, choice["message"],
                   {"role": "tool", "tool_call_id": tool_call["id"], "content": long_output}]
        response = self.post(upstream(envelope({"type": "message", "content": "FINAL_OK"})), messages=history)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "FINAL_OK")
        messages = self.payloads[-1]["messages"]
        self.assertEqual(messages[1:4], [history[0], history[1],
                         {"role": "user", "content": [{"type": "text", "text": "Read fixture"}]}])
        self.assertNotIn("tool_calls", messages[-3])
        self.assertIn(tool_call["id"], messages[-3]["content"])
        result = json.loads(messages[-2]["content"][0]["text"].split("\n", 1)[1])
        self.assertEqual(result["content"], long_output)
        self.assertEqual(result["tool_call_id"], tool_call["id"])
        self.assertEqual(messages[-2]["role"], "user")
        self.assertEqual(messages[-1]["role"], "system")
        self.assertIn("Adapter response format reminder", messages[-1]["content"])
        self.assertEqual(history[-1]["role"], "tool")  # Original request is untouched.

    def test_stream_emits_only_validated_calls_usage_and_completion(self):
        response = self.post(upstream(envelope(call())), stream=True, stream_options={"include_usage": True})
        self.assertEqual(response.status_code, 200)
        chunks = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        self.assertEqual(chunks[0]["choices"][0]["delta"], {"role": "assistant"})
        tool_call = chunks[1]["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(tool_call["index"], 0)
        self.assertEqual(chunks[2]["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(chunks[3]["choices"], [])
        self.assertEqual(chunks[3]["usage"]["total_tokens"], 35)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))
        self.assertNotIn(STRUCTURED_PAYLOAD_START, response.text)

    def test_stream_final_message_and_empty_message_are_unwrapped(self):
        for text in ("final", ""):
            response = self.post(upstream(envelope({"type": "message", "content": text})), stream=True)
            self.assertIn('"finish_reason": "stop"', response.text)
            self.assertNotIn(STRUCTURED_PAYLOAD_START, response.text)
            self.assertNotIn('"usage":', response.text)

    def test_invalid_responses_fail_without_partial_calls_or_repairs(self):
        invalid = ["plain answer", json.dumps(call()), envelope(call("unknown")),
                   envelope(call(arguments={})), envelope(call(arguments={"filePath": 7})),
                   envelope(call(arguments={"filePath": "x", "extra": True})),
                   envelope(call(arguments="{}")), envelope({"type": "tool_calls", "tool_calls": []}),
                   envelope({"type": "message", "content": "x", "tool_calls": []}),
                   envelope({"type": "tool_calls", "tool_calls": [call()["tool_calls"][0],
                                                                               call("unknown")["tool_calls"][0]]}),
                   STRUCTURED_PAYLOAD_START + '{"type":"message","content":"a","content":"b"}' + STRUCTURED_PAYLOAD_END,
                   STRUCTURED_PAYLOAD_START + '{"type":"message","content":NaN}' + STRUCTURED_PAYLOAD_END,
                   STRUCTURED_PAYLOAD_START + "[" * 1100 + "0" + "]" * 1100 + STRUCTURED_PAYLOAD_END,
                   envelope(call()) + envelope(call())]
        for stream in (False, True):
            for content in invalid:
                with self.subTest(stream=stream, content=content):
                    self.assert_failure(self.post(upstream(content), stream=stream), stream)

    def test_required_and_named_are_enforced_for_both_response_modes(self):
        for stream in (False, True):
            for choice in ("required", {"type": "function", "function": {"name": "read"}}):
                response = self.post(upstream(envelope(call())), stream=stream, tool_choice=choice)
                self.assertEqual(response.status_code, 200)
                self.assertIn('"tool_calls"', response.text)
                response = self.post(upstream(envelope({"type": "message", "content": "no"})),
                                     stream=stream, tool_choice=choice)
                self.assert_failure(response, stream)
        second = {"type": "function", "function": {"name": "other"}}
        response = self.post(upstream(envelope(call("other"))), tools=[TOOL, second],
                             tool_choice={"type": "function", "function": {"name": "read"}})
        self.assertEqual(response.status_code, 502)

    def test_commentary_around_one_complete_envelope_is_accepted(self):
        for stream in (False, True):
            response = self.post(upstream("I will read the file.\n\n" + envelope(call()) + "\nDone selecting."),
                                 stream=stream)
            self.assertEqual(response.status_code, 200)
            self.assertIn('"tool_calls"', response.text)
            self.assertNotIn("I will read", response.text)
            self.assertNotIn("Done selecting", response.text)

    def test_long_code_and_literal_markers_are_preserved_exactly(self):
        code = ('const path = "C:\\\\scene";\nconst marker = "<OPENAI_TOOL_PAYLOAD>";\n'
                'const end = "</OPENAI_TOOL_PAYLOAD>";\n') * 350
        tools = [{"type": "function", "function": {"name": "write", "parameters": {
            "type": "object", "properties": {"content": {"type": "string"}},
            "required": ["content"], "additionalProperties": False}}}]
        payload = envelope(call("write", {"content": code}))
        for stream in (False, True):
            response = self.post(upstream("Creating the scene.\n" + payload), stream=stream, tools=tools)
            if stream:
                chunks = [json.loads(line[6:]) for line in response.text.splitlines()
                          if line.startswith("data: ") and line != "data: [DONE]"]
                args = chunks[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
                self.assertTrue(response.text.endswith("data: [DONE]\n\n"))
            else:
                args = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
            self.assertEqual(json.loads(args)["content"], code)

    def test_commentary_does_not_allow_malformed_ambiguous_or_truncated_calls(self):
        bad_json = envelope(call()).replace('"fixture.txt"}', '"fixture.txt",""}')
        cases = [bad_json, envelope(call())[:-len(STRUCTURED_PAYLOAD_END)-1],
                 envelope(call()) + envelope(call()), envelope(call()) + STRUCTURED_PAYLOAD_START,
                 envelope(call()) + STRUCTURED_PAYLOAD_END, envelope(call("unknown")),
                 envelope(call(arguments={})), envelope(call()) + "{}" + STRUCTURED_PAYLOAD_END]
        for stream in (False, True):
            for source in cases:
                with self.subTest(stream=stream, source=source):
                    self.assert_failure(self.post(upstream("Creating a file.\n" + source), stream=stream), stream)

    def test_complete_json_at_eof_can_omit_only_closing_text_marker(self):
        for stream in (False, True):
            valid = STRUCTURED_PAYLOAD_START + json.dumps(call())
            response = self.post(upstream(valid), stream=stream)
            self.assertEqual(response.status_code, 200)
            self.assertIn('"tool_calls"', response.text)
            for invalid in (valid + " trailing prose", valid + "</OPENAI", valid + "{}",
                            STRUCTURED_PAYLOAD_START + json.dumps(call("unknown")), valid[:-1]):
                self.assert_failure(self.post(upstream(invalid), stream=stream), stream)
            self.assert_failure(self.post(upstream(valid, done=False), stream=stream), stream)

    def test_invalid_response_diagnostics_do_not_log_tool_content(self):
        with patch("merlinai_adapter_server.merlin_client.logger") as logger:
            response = self.post(upstream("private file contents"), model="glm-5.3-flash", max_tokens=32000)
        self.assertEqual(response.status_code, 502)
        args = logger.warning.call_args.args
        self.assertIn("glm-5.3-flash", args)
        self.assertIn(32000, args)
        self.assertNotIn("private file contents", repr(args))

    def test_invalid_requests_rejected_before_network(self):
        for fields in ({"tool_choice": "bogus"}, {"tools": [], "tool_choice": "required"},
                       {"tool_choice": {"type": "function", "function": {"name": "unknown"}}},
                       {"tools": [TOOL, TOOL]}, {"tools": [{"type": "web_search"}]},
                       {"tools": [{"function": {"name": "bad", "parameters": {"type": "nonsense"}}}]},
                       {"tools": [{"function": {"name": "bad", "parameters": {"$ref": "https://example.com/schema"}}}]}):
            response = self.post(b"", **fields)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.payloads, [])

    def test_none_and_no_tools_preserve_plain_text_without_protocol(self):
        for fields in ({"tool_choice": "none"}, {"tools": []}):
            response = self.post(upstream(envelope(call())), **fields)
            self.assertEqual(response.json()["choices"][0]["message"]["content"], envelope(call()))
            self.assertEqual(len(self.payloads[-1]["messages"]), 1)
            self.assertEqual(self.payloads[-1]["params"]["tools"], [])

    def test_upstream_error_eof_or_native_call_never_release_buffered_calls(self):
        valid = envelope(call())
        sources = [upstream(valid, done=False),
                   upstream(valid, done=False) + event("error", {"type": "INTERNAL_SERVER_ERROR"}),
                   event("tool_calls", [{"id": "call_x", "type": "function", "function": {
                       "name": "read", "arguments": '{"filePath":"fixture.txt"}'}}])]
        for stream in (False, True):
            for source in sources:
                self.assert_failure(self.post(source, stream=stream), stream)

    def test_local_schema_references_validate(self):
        schema = {"type": "object", "properties": {"filePath": {"$ref": "#/$defs/path"}},
                  "required": ["filePath"], "$defs": {"path": {"type": "string", "minLength": 2}}}
        tools = [{"type": "function", "function": {"name": "read", "parameters": schema}}]
        self.assertEqual(self.post(upstream(envelope(call())), tools=tools).status_code, 200)
        self.assertEqual(self.post(upstream(envelope(call(arguments={"filePath": ""}))), tools=tools).status_code, 502)

    def test_invalid_config_mode_fails_validation(self):
        with self.assertRaises(ValidationError):
            AdapterSettings(tool_call_mode="automatic-fallback")

    def test_schema_literal_ref_names_and_nested_constraints(self):
        schema = {"type": "object", "properties": {
            "$ref": {"type": "string"},
            "mode": {"enum": ["safe"]},
            "items": {"type": "array", "items": {"type": "integer"}, "minItems": 1}},
            "required": ["$ref", "mode", "items"]}
        tools = [{"function": {"name": "read", "parameters": schema}}]
        args = {"$ref": "ordinary property", "mode": "safe", "items": [1]}
        self.assertEqual(self.post(upstream(envelope(call(arguments=args))), tools=tools).status_code, 200)
        for invalid in ({**args, "mode": "bad"}, {**args, "items": ["wrong type"]}, {**args, "items": []}):
            self.assertEqual(self.post(upstream(envelope(call(arguments=invalid))), tools=tools).status_code, 502)

    def test_unresolvable_local_reference_is_a_controlled_error(self):
        tools = [{"function": {"name": "read", "parameters": {"$ref": "#/$defs/missing"}}}]
        for stream in (False, True):
            self.assert_failure(self.post(upstream(envelope(call())), tools=tools, stream=stream), stream)

    def test_multiple_calls_have_distinct_ids_and_stream_indexes(self):
        calls = [call(arguments={"filePath": path})["tool_calls"][0] for path in ("one.txt", "two.txt")]
        response = self.post(upstream(envelope({"type": "tool_calls", "tool_calls": calls})), stream=True)
        chunks = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        emitted = chunks[1]["choices"][0]["delta"]["tool_calls"]
        self.assertEqual([c["index"] for c in emitted], [0, 1])
        self.assertEqual(len({c["id"] for c in emitted}), 2)
        self.assertEqual([json.loads(c["function"]["arguments"])["filePath"] for c in emitted],
                         ["one.txt", "two.txt"])

    def test_tool_history_is_encoded_when_current_tools_are_disabled(self):
        for fields in ({"tool_choice": "none"}, {"tools": []}):
            history = [{"role": "assistant", "tool_calls": [{"id": "call_old", "type": "function",
                        "function": {"name": "read", "arguments": '{"filePath":"old.txt"}'}}]},
                       {"role": "tool", "tool_call_id": "call_old", "content": "stored result"}]
            response = self.post(upstream("plain final"), messages=history, **fields)
            self.assertEqual(response.json()["choices"][0]["message"]["content"], "plain final")
            messages = self.payloads[-1]["messages"]
            self.assertEqual([m["role"] for m in messages], ["assistant", "user"])
            self.assertIn("call_old", messages[0]["content"])
            self.assertIn("stored result", messages[1]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
