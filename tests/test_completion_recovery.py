import io
import json
import socket
import time
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import anyio

from merlinai_adapter_server.app import app
from merlinai_adapter_server.app import _stream_with_cleanup
from merlinai_adapter_server.config import AdapterSettings
from merlinai_adapter_server.emulated_recovery import RecoveryPolicy
from merlinai_adapter_server.merlin_client import merlin_gateway, merlin_openai_client
from merlinai_adapter_server.request_budget import RequestBudget
from merlinai_adapter_server.response_usage import openai_usage
from merlinai_adapter_server.schemas import OpenAIRequest
from test_emulated_tools import TOOL, call, envelope, event, upstream


class CompletionRecoveryTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.object(merlin_openai_client, "tool_call_mode", "emulated"),
            patch.object(merlin_openai_client, "recovery_policy", RecoveryPolicy()),
            patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def post(self, sources, **fields):
        self.payloads, self.connections = [], []
        sources = iter(sources)
        def open_request(payload):
            self.payloads.append(payload)
            conn = Mock(sock=None)
            self.connections.append(conn)
            return conn, io.BytesIO(next(sources))
        with patch.object(merlin_gateway, "open_request", side_effect=open_request):
            response = self.client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"},
                json={"model": "glm-5.3", "messages": [{"role": "user", "content": "Read fixture"}],
                      "tools": [TOOL], **fields})
        self.assertTrue(all(conn.close.called for conn in self.connections))
        return response

    def success(self, response, stream):
        self.assertEqual(response.status_code, 200)
        if stream:
            chunks = [json.loads(line[6:]) for line in response.text.splitlines()
                      if line.startswith("data: ") and "[DONE]" not in line]
            calls = [call for chunk in chunks for choice in chunk["choices"]
                     for call in choice["delta"].get("tool_calls", [])]
            self.assertTrue(response.text.endswith("data: [DONE]\n\n"))
            return calls, chunks[-1]["usage"]
        body = response.json()
        return body["choices"][0]["message"]["tool_calls"], body["usage"]

    def failure(self, response, stream):
        if stream:
            self.assertIn("event: error", response.text)
            self.assertNotIn("data: [DONE]", response.text)
            self.assertNotIn('"finish_reason": "tool_calls"', response.text)
            self.assertNotIn('"function":', response.text)
        else:
            self.assertEqual(response.status_code, 502)

    def test_regeneration_is_atomic_and_shares_token_budget_in_both_modes(self):
        malformed = envelope(call()).replace('"filePath":', '"filePath"')
        for stream in (False, True):
            response = self.post([
                upstream(malformed, usage={"tokens": {"input": 100, "output": 400, "reasoning": 350}}),
                upstream(envelope(call()), usage={"tokens": {"input": 200, "output": 100, "reasoning": 40}}),
            ], stream=stream, max_tokens=1000, stream_options={"include_usage": True})
            calls, usage = self.success(response, stream)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"filePath": "fixture.txt"})
            self.assertEqual(usage, {"prompt_tokens": 300, "completion_tokens": 500, "total_tokens": 800,
                                    "completion_tokens_details": {"reasoning_tokens": 390}})
            self.assertEqual(len(self.payloads), 2)
            first, second = self.payloads
            self.assertEqual(first["params"]["max_tokens"], 1000)
            self.assertEqual(second["params"]["max_tokens"], 600)
            self.assertEqual(second["messages"][:-2], first["messages"])
            self.assertEqual(second["messages"][-2], {"role": "assistant", "content": malformed})
            self.assertIn("ADAPTER_PROTOCOL_ERROR", second["messages"][-1]["content"])
            self.assertNotIn("tool_calls", second["messages"][-2])

    def test_correction_stops_after_one_attempt(self):
        for stream in (False, True):
            response = self.post([upstream('{"arguments":'), upstream('{"arguments":')], stream=stream)
            self.failure(response, stream)
            self.assertEqual(len(self.payloads), 2)

    def test_no_retry_on_empty_budget_policy_unknown_tool_or_transport_failure(self):
        cases = [
            (upstream(""), {}),
            (upstream('{"arguments":', usage={"tokens": {"output": 1000, "reasoning": 999}}), {"max_tokens": 1000}),
            (upstream(envelope(call("undeclared"))), {}),
            (upstream(envelope({"type": "message", "content": "no"})), {"tool_choice": "required"}),
            (upstream(envelope(call()) + envelope(call())), {}),
            (upstream('{"arguments":', usage={}), {}),
            (upstream('{"arguments":', done=False), {}),
            (event("error", {"message": "failed"}), {}),
        ]
        for stream in (False, True):
            for source, fields in cases:
                response = self.post([source], stream=stream, **fields)
                self.failure(response, stream)
                self.assertEqual(len(self.payloads), 1)

    def test_corrected_response_cannot_escape_validation_or_its_smaller_budget(self):
        for stream in (False, True):
            for correction in (upstream(envelope(call("undeclared"))),
                               upstream(envelope(call(arguments={}))),
                               upstream("", usage={"tokens": {"output": 600, "reasoning": 600}})):
                response = self.post([upstream('{"arguments":', usage={"tokens": {"output": 400}}), correction],
                                     stream=stream, max_tokens=1000)
                self.failure(response, stream)
                self.assertEqual(len(self.payloads), 2)

    def test_correction_can_be_disabled_and_oversized_feedback_is_not_replayed(self):
        for policy in (RecoveryPolicy(enabled=False), RecoveryPolicy(max_content_chars=5)):
            with patch.object(merlin_openai_client, "recovery_policy", policy):
                response = self.post([upstream('{"arguments":')])
            self.assertEqual(response.status_code, 502)
            self.assertEqual(len(self.payloads), 1)

    def test_response_size_limit_closes_stream_and_does_not_retry(self):
        settings = AdapterSettings(completion_max_bytes=1024)
        with patch("merlinai_adapter_server.merlin_client.SETTINGS", settings):
            for stream in (False, True):
                response = self.post([upstream(envelope(call(arguments={"filePath": "x" * 2000})))], stream=stream)
                self.failure(response, stream)
                self.assertIn("response size limit", response.text)
                self.assertEqual(len(self.payloads), 1)

    def test_generator_close_releases_connection_before_tool_release(self):
        conn = Mock(sock=None)
        req = OpenAIRequest(model="test", messages=[{"role": "user", "content": "read"}], tools=[TOOL], stream=True)
        with patch.object(merlin_gateway, "open_request", return_value=(conn, io.BytesIO(upstream(envelope(call()))))):
            stream = merlin_openai_client.open_chat_completion_stream(req)
            self.assertIn('"role": "assistant"', next(stream))
            stream.close()
        conn.close.assert_called()

    def test_unstarted_stream_close_releases_preopened_connection(self):
        conn = Mock(sock=None)
        req = OpenAIRequest(model="test", messages=[{"role": "user", "content": "read"}], tools=[TOOL])
        with patch.object(merlin_gateway, "open_request", return_value=(conn, io.BytesIO(b""))):
            stream = merlin_openai_client.open_chat_completion_stream(req)
            stream.close()
        conn.close.assert_called()

    def test_asgi_cancellation_interrupts_worker_socket(self):
        reader, writer = socket.socketpair()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        conn = Mock(sock=reader)
        budget = RequestBudget(10, 1024)
        started, ended = threading.Event(), threading.Event()
        class BlockingIterator:
            def __next__(self):
                try:
                    with budget.reading(conn):
                        started.set()
                        reader.recv(1)
                finally:
                    ended.set()
            def close(self):
                budget.cancel()
        async def run():
            async def consume():
                async for _ in _stream_with_cleanup(BlockingIterator()):
                    pass
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(consume)
                with anyio.fail_after(2):
                    while not started.is_set():
                        await anyio.sleep(.005)
                tasks.cancel_scope.cancel()
        anyio.run(run)
        self.assertTrue(ended.wait(2), "Cancelled request left its worker blocked")

    def test_deadline_interrupts_a_blocked_socket_read(self):
        reader, writer = socket.socketpair()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        conn = Mock(sock=reader)
        budget = RequestBudget(.05, 1024)
        started = time.monotonic()
        with self.assertRaises(HTTPException) as raised:
            with budget.reading(conn):
                reader.recv(1)
        self.assertEqual(raised.exception.status_code, 504)
        self.assertLess(time.monotonic() - started, 2)
        conn.close.assert_called()

    def test_usage_does_not_treat_bool_as_a_token_count(self):
        self.assertEqual(openai_usage({"tokens": {"input": True, "output": -1, "reasoning": False}}),
                         {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    def test_missing_reasoning_on_correction_is_not_reported_as_zero(self):
        response = self.post([
            upstream('{"arguments":', usage={"tokens": {"input": 10, "output": 20, "reasoning": 15}}),
            upstream(envelope(call()), usage={"tokens": {"input": 30, "output": 40}}),
        ])
        self.assertEqual(response.json()["usage"], {"prompt_tokens": 40, "completion_tokens": 60, "total_tokens": 100})

    def test_complete_131072_limit_is_forwarded_without_silent_clamping(self):
        response = self.post([upstream(envelope(call()))], max_tokens=131072)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payloads[0]["params"]["max_tokens"], 131072)

    def test_qwen_correction_uses_compatible_budget_in_both_modes(self):
        for stream in (False, True):
            for initial_output, expected in ((1000, 130072), (111072, 20000), (114687, 16385)):
                response = self.post([
                    upstream('{"arguments":', usage={"tokens": {"input": 10, "output": initial_output}}),
                    upstream(envelope(call())),
                ], model="qwen-3.8-max", max_tokens=131072, stream=stream, stream_options={"include_usage": True})
                self.success(response, stream)
                self.assertEqual(self.payloads[1]["params"]["max_tokens"], expected)
                self.assertLessEqual(initial_output + expected, 131072)

    def test_qwen_insufficient_remaining_budget_does_not_retry_or_increase_cap(self):
        for stream in (False, True):
            response = self.post([
                upstream('{"arguments":', usage={"tokens": {"output": 114688}}),
            ], model="qwen-3.8-max", max_tokens=131072, stream=stream)
            self.failure(response, stream)
            self.assertEqual(len(self.payloads), 1)

    def test_qwen_low_explicit_limit_returns_actionable_error_before_network(self):
        for stream in (False, True):
            response = self.post([], model="qwen-3.8-max", max_tokens=16384, stream=stream)
            self.assertEqual(response.status_code, 422)
            self.assertIn("16385", response.text)
            self.assertEqual(self.payloads, [])

    def test_qwen_single_call_has_full_validation_and_exact_string_arguments(self):
        argument = "C:\\test\\original\n<OPENAI_TOOL_PAYLOAD>\"quoted\""
        for stream in (False, True):
            response = self.post([upstream(envelope({"type": "tool_call", "name": "read",
                                                    "arguments": {"filePath": argument}}))],
                                 model="qwen-3.8-max", stream=stream, stream_options={"include_usage": True})
            calls, _ = self.success(response, stream)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(calls[0]["function"]["arguments"])["filePath"], argument)
            self.assertIn('"type":"tool_call"', self.payloads[0]["messages"][0]["content"])
            for bad in ({"type": "tool_call", "name": "unknown", "arguments": {}},
                        {"type": "tool_call", "name": "read", "arguments": {}, "content": "extra"},
                        {"type": "tool_call", "name": "read", "arguments": {"filePath": 7}}):
                response = self.post([upstream(envelope(bad)), upstream(envelope(bad))],
                                     model="qwen-3.8-max", stream=stream)
                self.failure(response, stream)

    def test_all_models_correction_uses_remaining_model_budget_without_hidden_cap(self):
        from merlinai_adapter_server.models_catalog import MODEL_MAX_OUTPUT_TOKENS
        for model, maximum in MODEL_MAX_OUTPUT_TOKENS.items():
            response = self.post([upstream('{"arguments":', usage={"tokens": {"output": 100}}),
                                  upstream(envelope(call()))], model=model)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.payloads[0]["params"]["max_tokens"], maximum)
            self.assertEqual(self.payloads[1]["params"]["max_tokens"], maximum - 100)


if __name__ == "__main__":
    unittest.main()
