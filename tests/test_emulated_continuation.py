import json
import unittest
from unittest.mock import patch

from merlinai_adapter_server.emulated_continuation import ContinuationPolicy, incomplete_json_prefix
from merlinai_adapter_server.emulated_recovery import RecoveryPolicy
from merlinai_adapter_server.merlin_client import merlin_openai_client
from merlinai_adapter_server.protocol_constants import STRUCTURED_PAYLOAD_START
import test_completion_recovery as fixtures
from test_emulated_tools import TOOL, envelope, upstream


class EmulatedContinuationTests(unittest.TestCase):
    # Reuse the endpoint fixtures without inheriting/rerunning their test suite.
    post = fixtures.CompletionRecoveryTests.post
    success = fixtures.CompletionRecoveryTests.success
    failure = fixtures.CompletionRecoveryTests.failure

    def setUp(self):
        fixtures.CompletionRecoveryTests.setUp(self)
        patcher = patch.object(merlin_openai_client, "continuation_policy", ContinuationPolicy())
        patcher.start()
        self.addCleanup(patcher.stop)

    def sample(self, value="fixture.txt"):
        text = envelope({"type": "tool_call", "name": "read", "arguments": {"filePath": value}})
        split = text.index('"filePath": "') + len('"filePath": "') + 3
        return text, text[:split], text[split:]

    def test_multiple_suffixes_preserve_exact_code_and_share_all_usage(self):
        value = 'C:\\scene\\雨夜\n"quoted" <OPENAI_TOOL_PAYLOAD> </OPENAI_TOOL_PAYLOAD>'
        full, prefix, suffix = self.sample(value)
        split = suffix.index(r"\u96") + 4  # Cut inside the Unicode escape for 雨.
        for stream in (False, True):
            response = self.post([
                upstream(prefix, usage={"tokens": {"input": 10, "output": 30, "reasoning": 20}}),
                upstream(suffix[:split], usage={"tokens": {"input": 11, "output": 25, "reasoning": 15}}),
                upstream(suffix[split:], usage={"tokens": {"input": 12, "output": 20, "reasoning": 10}}),
            ], model="qwen-3.8-max", stream=stream, stream_options={"include_usage": True})
            calls, usage = self.success(response, stream)
            self.assertEqual(json.loads(calls[0]["function"]["arguments"])["filePath"], value)
            self.assertEqual([p["params"]["max_tokens"] for p in self.payloads], [131072, 131042, 131017])
            self.assertEqual(usage["completion_tokens"], 75)
            self.assertEqual(usage["completion_tokens_details"]["reasoning_tokens"], 45)
            self.assertEqual(self.payloads[1]["messages"][-2]["content"], prefix)
            self.assertEqual(self.payloads[2]["messages"][-2]["content"], prefix + suffix[:split])
            self.assertIn("hexadecimal digits", self.payloads[2]["messages"][-1]["content"])
            # Only the adapter-owned rules change; caller history is preserved.
            self.assertEqual(self.payloads[1]["messages"][1:-3], self.payloads[0]["messages"][1:-1])
            self.assertIn("Available tools", self.payloads[1]["messages"][0]["content"])

    def test_trailing_escape_and_file_content_are_not_stripped_or_reencoded(self):
        value = 'one\ntwo\\three "four"\n'
        full, _, _ = self.sample(value)
        split = full.index(r"\n") + 1
        for stream in (False, True):
            response = self.post([upstream(full[:split]), upstream(full[split:])],
                                 model="qwen-3.8-max", stream=stream, stream_options={"include_usage": True})
            calls, _ = self.success(response, stream)
            self.assertEqual(json.loads(calls[0]["function"]["arguments"])["filePath"], value)
            self.assertIn("first character must finish that escape", self.payloads[1]["messages"][-1]["content"])

    def test_bad_suffix_is_replaced_without_appending_any_of_its_bytes(self):
        _, prefix, suffix = self.sample()
        for stream in (False, True):
            for bad in ('literal\nnewline', suffix.replace('}}', '}}}')):
                response = self.post([
                    upstream(prefix, usage={"tokens": {"output": 30}}),
                    upstream(bad, usage={"tokens": {"output": 10}}),
                    upstream(suffix, usage={"tokens": {"output": 20}}),
                ], model="qwen-3.8-max", stream=stream, stream_options={"include_usage": True})
                calls, usage = self.success(response, stream)
                self.assertEqual(json.loads(calls[0]["function"]["arguments"])["filePath"], "fixture.txt")
                self.assertEqual(usage["completion_tokens"], 60)
                self.assertEqual(self.payloads[2]["params"]["max_tokens"], 131032)
                self.assertEqual(self.payloads[2]["messages"][-2]["content"], prefix)
                self.assertIn("NONE of it was appended", self.payloads[2]["messages"][-1]["content"])

    def test_bad_prefix_is_not_treated_as_truncation(self):
        cases = [STRUCTURED_PAYLOAD_START + '{"content":"bad\n',
                 STRUCTURED_PAYLOAD_START + r'{"content":"bad\q',
                 STRUCTURED_PAYLOAD_START + '{"type":"message",,',
                 STRUCTURED_PAYLOAD_START + '{"a":{"x":1,"x":2},"content":"unfinished']
        for text in cases:
            self.assertIsNone(incomplete_json_prefix(text))
            with patch.object(merlin_openai_client, "recovery_policy", RecoveryPolicy(enabled=False)):
                response = self.post([upstream(text)], model="qwen-3.8-max")
            self.failure(response, False)
            self.assertEqual(len(self.payloads), 1)

    def test_valid_progress_allows_one_replacement_for_each_later_fragment(self):
        _, prefix, suffix = self.sample()
        first, last = suffix[:3], suffix[3:]
        for stream in (False, True):
            response = self.post([upstream(prefix), upstream("bad\n"), upstream(first),
                                  upstream("bad\n"), upstream(last)], model="qwen-3.8-max",
                                 stream=stream, stream_options={"include_usage": True})
            calls, _ = self.success(response, stream)
            self.assertEqual(json.loads(calls[0]["function"]["arguments"])["filePath"], "fixture.txt")
            self.assertEqual(len(self.payloads), 5)

    def test_completed_suffix_cannot_release_wrong_tool_or_wrong_choice(self):
        for name, choice in (("unknown", "auto"), ("other", {"type": "function", "function": {"name": "read"}})):
            text = envelope({"type": "tool_call", "name": name, "arguments": {"filePath": "fixture.txt"}})
            split = text.index("fixture") + 3
            for stream in (False, True):
                response = self.post([upstream(text[:split]), upstream(text[split:])], model="qwen-3.8-max",
                                     stream=stream, tool_choice=choice,
                                     tools=[TOOL, {"type": "function", "function": {"name": "other"}}])
                self.failure(response, stream)
                self.assertEqual(len(self.payloads), 2)

    def test_missing_usage_in_any_continuation_stops_before_tool_release(self):
        _, prefix, suffix = self.sample()
        for stream in (False, True):
            response = self.post([upstream(prefix), upstream(suffix, usage={})],
                                 model="qwen-3.8-max", stream=stream)
            self.failure(response, stream)
            self.assertIn("omitted output token usage", response.text)
            self.assertEqual(len(self.payloads), 2)

    def test_unknown_initial_usage_cannot_be_treated_as_zero_for_continuation(self):
        _, prefix, _ = self.sample()
        for stream in (False, True):
            for usage in ({}, {"tokens": {"input": 100}}, {"tokens": {"output": -1}}):
                response = self.post([upstream(prefix, usage=usage)],
                                     model="qwen-3.8-max", stream=stream)
                self.failure(response, stream)
                self.assertEqual(len(self.payloads), 1)

    def test_minimum_remaining_budget_is_never_reset_or_increased(self):
        _, prefix, _ = self.sample()
        for stream in (False, True):
            response = self.post([
                upstream(prefix, usage={"tokens": {"output": 114687}}),
                upstream("more", usage={"tokens": {"output": 1000}}),
            ], model="qwen-3.8-max", stream=stream)
            self.failure(response, stream)
            self.assertEqual(len(self.payloads), 2)
            self.assertEqual(self.payloads[1]["params"]["max_tokens"], 16385)

    def test_attempt_limit_and_repeated_bad_fragments_fail_atomically(self):
        _, prefix, _ = self.sample()
        for stream in (False, True):
            with patch.object(merlin_openai_client, "continuation_policy", ContinuationPolicy(max_attempts=2)):
                for chunks in (("more", "again"), ("bad\n", "bad\n")):
                    response = self.post([upstream(prefix), *[upstream(c) for c in chunks]],
                                         model="qwen-3.8-max", stream=stream)
                    self.failure(response, stream)
                    self.assertEqual(len(self.payloads), 3)

    def test_disabling_continuation_keeps_existing_regeneration(self):
        full, prefix, _ = self.sample()
        with patch.object(merlin_openai_client, "continuation_policy", ContinuationPolicy(max_attempts=0)):
            response = self.post([upstream(prefix), upstream(full)], model="qwen-3.8-max")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ADAPTER_PROTOCOL_ERROR", self.payloads[1]["messages"][-1]["content"])

    def test_continuation_after_regeneration_charges_every_attempt(self):
        _, prefix, suffix = self.sample()
        for stream in (False, True):
            response = self.post([
                upstream('{"arguments":', usage={"tokens": {"output": 100}}),
                upstream(prefix, usage={"tokens": {"output": 40}}),
                upstream(suffix, usage={"tokens": {"output": 30}}),
            ], model="qwen-3.8-max", stream=stream, stream_options={"include_usage": True})
            _, usage = self.success(response, stream)
            self.assertEqual(usage["completion_tokens"], 170)
            self.assertEqual(self.payloads[1]["params"]["max_tokens"], 130972)
            self.assertEqual(self.payloads[2]["params"]["max_tokens"], 130932)

    def test_reported_overspending_and_empty_suffix_fail_before_release(self):
        _, prefix, suffix = self.sample()
        for stream in (False, True):
            for source in (upstream(suffix, usage={"tokens": {"output": 131073}}), upstream("")):
                response = self.post([upstream(prefix), source], model="qwen-3.8-max", stream=stream)
                self.failure(response, stream)
                self.assertEqual(len(self.payloads), 2)

    def test_transport_failure_does_not_release_partial_or_complete_suffix(self):
        _, prefix, suffix = self.sample()
        for stream in (False, True):
            response = self.post([upstream(prefix), upstream(suffix, done=False)],
                                 model="qwen-3.8-max", stream=stream)
            self.failure(response, stream)
            self.assertEqual(len(self.payloads), 2)


if __name__ == "__main__":
    unittest.main()
