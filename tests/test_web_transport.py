import io
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from merlinai_adapter_server.app import app
from merlinai_adapter_server.merlin_client import MerlinGateway, MerlinOpenAIClient, merlin_gateway
from merlinai_adapter_server.merlin_web import TRUNCATION_NOTICE, build_web_payload


def event(name, value):
    return f"event: {name}\ndata: {json.dumps(value)}\n\n".encode()


def source(text, *, length=False, output=20):
    data = event("message", {"data": {"content": text}})
    if length:
        data += event("finishReason", {"reason": "length"})
        for part in ("\n\n" + TRUNCATION_NOTICE + " \n",):
            data += event("message", {"data": {"content": part}})
    data += event("usage", {"userPlan": "private", "cost": {"dailyUsage": 9}})
    data += event("turnUsage", {"totals": {"input": 10, "output": output, "reasoning": 2, "dollars": 5}})
    return data + event("message", {"data": {"eventType": "DONE"}})


TOOL = {"type": "function", "function": {"name": "echo", "parameters": {
    "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
    "additionalProperties": False}}}


class WebTransportTests(unittest.TestCase):
    def test_wire_profile_and_full_history_override_stale_extension_settings(self):
        gateway = MerlinGateway("web")
        payload = gateway.build_payload(model="qwen-3.8-max", messages=[
            {"role": "system", "content": "policy"},
            {"role": "user", "content": [{"type": "text", "text": "original prompt"}]},
            {"role": "assistant", "content": "previous reply"},
            {"role": "user", "content": "tool result data"}], max_tokens=131072)
        conn = Mock()
        conn.getresponse.return_value.status = 200
        with patch("merlinai_adapter_server.merlin_client.token_manager.get_access_token", return_value="test"):
            gateway._open_response(conn, payload)
        method, path, body, headers = conn.request.call_args.args
        wire = json.loads(body)
        self.assertEqual(path, "/arcane/api/v2/thread/unified")
        self.assertEqual(headers["x-merlin-version"], "web-merlin")
        self.assertEqual(headers["origin"], "https://www.getmerlin.in")
        self.assertIn("x-request-timestamp", headers)
        self.assertIn("referer", headers)
        self.assertEqual(wire["model"], "qwen-3.8-max")
        self.assertEqual(wire["message"]["content"], "SYSTEM:\npolicy\n\nUSER:\noriginal prompt\n\nASSISTANT:\nprevious reply\n\nUSER:\ntool result data")
        self.assertNotIn("params", wire)
        self.assertNotIn("tools", wire)
        self.assertFalse(wire["metadata"]["mcpConfig"]["isEnabled"])
        self.assertNotEqual(wire["chatId"], build_web_payload(payload)["chatId"])

    def test_unsupported_media_is_rejected_instead_of_silently_lost(self):
        payload = {"model": "grok-4.7", "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]}]}
        with self.assertRaises(HTTPException) as error:
            build_web_payload(payload)
        self.assertEqual(error.exception.status_code, 422)

    def test_length_footer_removed_without_trimming_partial_json_escape(self):
        prefix = '<OPENAI_TOOL_PAYLOAD>{"type":"message","content":"' + 'x' * 400 + '\\'
        events = list(MerlinGateway("web").iter_event_stream(io.BytesIO(source(prefix, length=True))))
        self.assertEqual("".join(e.content_delta for e in events), prefix)
        self.assertIn("length", [e.finish_reason for e in events])
        self.assertEqual([e.usage for e in events if e.usage], [{"tokens": {"input": 10, "output": 20, "reasoning": 2}}])
        self.assertNotIn("private", json.dumps([e.raw_event for e in events]))

    def test_footer_text_is_preserved_without_length_marker(self):
        text = "ordinary quotation\n\n" + TRUNCATION_NOTICE + " "
        events = list(MerlinGateway("web").iter_event_stream(io.BytesIO(source(text))))
        self.assertEqual("".join(e.content_delta for e in events), text)

    def test_errors_do_not_flush_pending_tail_or_complete_the_stream(self):
        raw = event("message", {"data": {"content": "private partial tail"}}) + event("error", {})
        received = []
        with self.assertRaises(HTTPException):
            for e in MerlinGateway("web").iter_event_stream(io.BytesIO(raw)):
                received.append(e.content_delta)
        self.assertEqual("".join(received), "")
        with self.assertRaises(HTTPException):
            list(MerlinGateway("web").iter_event_stream(io.BytesIO(event("message", {"data": {"content": "partial"}}))))

    def test_openai_length_and_usage_for_both_response_modes(self):
        for stream in (False, True):
            response, _ = self.post([source("partial", length=True)], stream=stream, tools=[])
            self.assertEqual(response.status_code, 200)
            if stream:
                chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and "[DONE]" not in line]
                self.assertEqual([c["choices"][0]["finish_reason"] for c in chunks if c["choices"]][-1], "length")
                self.assertEqual(chunks[-1]["usage"]["completion_tokens"], 20)
            else:
                self.assertEqual(response.json()["choices"][0]["finish_reason"], "length")
                self.assertEqual(response.json()["usage"]["completion_tokens"], 20)
            self.assertNotIn("maximum output length", response.text)

    def post(self, sources, **fields):
        payloads = []
        sources = iter(sources)
        def open_request(payload):
            payloads.append(payload)
            return Mock(), io.BytesIO(next(sources))
        with patch.object(merlin_gateway, "transport", "web"), patch.object(merlin_gateway, "open_request", side_effect=open_request), patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test"):
            with TestClient(app) as client:
                response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test"}, json={
                    "model": "qwen-3.8-max", "messages": [{"role": "user", "content": "echo"}],
                    "stream_options": {"include_usage": True}, **fields})
        return response, payloads

    def test_web_qwen_continuation_uses_real_turn_usage_and_validates_atomically(self):
        full = '<OPENAI_TOOL_PAYLOAD>{"type":"tool_call","name":"echo","arguments":{"text":"one two"}}</OPENAI_TOOL_PAYLOAD>'
        split = full.index("two")
        for stream in (False, True):
            response, payloads = self.post([source(full[:split], length=True, output=40), source(full[split:], output=15)],
                                           stream=stream, tools=[TOOL], tool_choice="required")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("event: error", response.text)
            self.assertIn('"finish_reason": "tool_calls"' if stream else '"finish_reason":"tool_calls"', response.text)
            self.assertEqual(len(payloads), 2)
            self.assertEqual(payloads[1]["params"]["max_tokens"], 131032)
            self.assertNotIn("maximum output length", payloads[1]["messages"][-2]["content"])
            self.assertIn('one two', response.text.replace('\\"', '"'))

    def test_web_over_budget_response_is_not_reported_as_success(self):
        for stream in (False, True):
            response, _ = self.post([source("large", output=131073)], stream=stream, tools=[])
            if stream:
                self.assertIn("event: error", response.text)
                self.assertNotIn("data: [DONE]", response.text)
            else:
                self.assertEqual(response.status_code, 502)
