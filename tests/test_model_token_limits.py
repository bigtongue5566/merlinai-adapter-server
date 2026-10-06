import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from merlinai_adapter_server.app import app
from merlinai_adapter_server.merlin_client import merlin_gateway, merlin_openai_client
from merlinai_adapter_server.models_catalog import MODEL_LIMITS, MODEL_MAX_OUTPUT_TOKENS, MODEL_MIN_OUTPUT_TOKENS, SUPPORTED_MODELS, resolve_max_tokens
from test_emulated_tools import TOOL, call, envelope, upstream


class ModelTokenLimitsTests(unittest.TestCase):
    def test_all_catalog_limits_match_reviewed_snapshot(self):
        snapshot = Path(__file__).resolve().parents[1] / "docs/model-limits-2026-10-03.json"
        expected = {row["adapter_model"]: row["limit"]["output"]
                    for row in json.loads(snapshot.read_text(encoding="utf-8"))["models"]}
        self.assertEqual(MODEL_MAX_OUTPUT_TOKENS, expected)
        self.assertEqual(set(SUPPORTED_MODELS), set(expected))

    def test_models_endpoint_publishes_exact_context_input_output_capacities(self):
        snapshot = Path(__file__).resolve().parents[1] / "docs/model-limits-2026-10-03.json"
        expected = {row["adapter_model"]: row["limit"]
                    for row in json.loads(snapshot.read_text(encoding="utf-8"))["models"]}
        with patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"), TestClient(app) as client:
            response = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
        self.assertEqual(response.status_code, 200)
        actual = {row["id"]: row["limit"] for row in response.json()["data"]}
        self.assertEqual(actual, expected)
        self.assertEqual(set(MODEL_LIMITS), set(expected))
        for model, limits in actual.items():
            self.assertLessEqual(limits["output"], limits["context"])
            if "input" in limits:
                self.assertLessEqual(limits["input"], limits["context"])
        self.assertNotIn("input", actual["glm-5.3"])
        self.assertEqual(actual["gpt-5.6-luna"]["input"], 922000)

    def test_model_defaults_and_explicit_limits_reach_transport_in_both_modes(self):
        for mode in ("native", "emulated"):
            for stream in (False, True):
                for model, ceiling in MODEL_MAX_OUTPUT_TOKENS.items():
                    for requested in (None, max(1000, MODEL_MIN_OUTPUT_TOKENS.get(model, 1)), ceiling):
                        with self.subTest(mode=mode, stream=stream, model=model, requested=requested):
                            captured = []
                            conn = Mock(sock=None)
                            def open_request(payload):
                                captured.append(payload)
                                return conn, io.BytesIO(upstream(envelope(call()) if mode == "emulated" else "OK"))
                            with patch.object(merlin_openai_client, "tool_call_mode", mode), \
                                 patch.object(merlin_gateway, "open_request", side_effect=open_request), \
                                 patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"), \
                                 TestClient(app) as client:
                                response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"},
                                    json={"model": model, "messages": [{"role": "user", "content": "read"}],
                                          "stream": stream, "max_tokens": requested,
                                          "tools": [TOOL] if mode == "emulated" else []})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(captured[0]["params"]["max_tokens"], ceiling if requested is None else requested)
                            conn.close.assert_called()

    def test_excess_is_rejected_before_network(self):
        for mode in ("native", "emulated"):
            for stream in (False, True):
                for model, ceiling in MODEL_MAX_OUTPUT_TOKENS.items():
                    with patch.object(merlin_openai_client, "tool_call_mode", mode), \
                         patch.object(merlin_gateway, "open_request") as network, \
                         patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"), \
                         TestClient(app) as client:
                        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"},
                            json={"model": model, "messages": [], "stream": stream, "max_tokens": ceiling + 1})
                    self.assertEqual(response.status_code, 422)
                    network.assert_not_called()

    def test_unknown_model_compatibility(self):
        self.assertEqual(resolve_max_tokens("custom-model", None), 10000)
        self.assertEqual(resolve_max_tokens("custom-model", 20000), 20000)

    def test_default_budget_exhaustion_does_not_retry(self):
        for stream in (False, True):
            conn = Mock(sock=None)
            source = upstream("", usage={"tokens": {"output": 131072, "reasoning": 131070}})
            with patch.object(merlin_openai_client, "tool_call_mode", "emulated"), \
                 patch.object(merlin_gateway, "open_request", return_value=(conn, io.BytesIO(source))) as network, \
                 patch("merlinai_adapter_server.security.ADAPTER_API_KEY", "test-key"), \
                 TestClient(app) as client:
                response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer test-key"},
                    json={"model": "glm-5.3", "messages": [], "tools": [TOOL], "stream": stream})
            self.assertIn("max_tokens=131072", response.text)
            self.assertIn("budget exhausted", response.text)
            self.assertNotIn("data: [DONE]", response.text)
            self.assertEqual(network.call_count, 1)
