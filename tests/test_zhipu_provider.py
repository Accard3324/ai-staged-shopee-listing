from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_provider import ZhipuProvider, load_project_env
from shopee_listing_app.config_manager import AIConfig


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ZhipuProviderTests(unittest.TestCase):
    def config(self) -> AIConfig:
        return AIConfig(
            provider="zhipu",
            endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            api_key_env="ZHIPU_API_KEY",
            model="glm-5.2",
            timeout_seconds=60,
        )

    def test_load_project_env_reads_key_without_printing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("ZHIPU_API_KEY=secret-value\nZHIPU_MODEL=GLM-5.2\n", encoding="utf-8")

            values = load_project_env(env_path)

        self.assertEqual(values["ZHIPU_API_KEY"], "secret-value")
        self.assertEqual(values["ZHIPU_MODEL"], "GLM-5.2")

    def test_zhipu_provider_retries_until_valid_json(self):
        provider = ZhipuProvider(self.config(), ROOT / "prompts")
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(json.loads(request.data.decode("utf-8")))
            if len(calls) == 1:
                return _FakeResponse({"choices": [{"message": {"content": "not json"}}]})
            return _FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

        with patch.dict("os.environ", {"ZHIPU_API_KEY": "secret-value"}, clear=False):
            with patch("urllib.request.urlopen", fake_urlopen):
                result = provider.request_json("Return JSON", {"task": "unit_test"}, required_keys=["ok"], max_retries=2)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["model"], "glm-5.2")
        self.assertIn("messages", calls[0])
        self.assertEqual(provider.last_used_model, "glm-5.2")

    def test_zhipu_provider_falls_back_to_available_models(self):
        config = AIConfig(
            provider="zhipu",
            endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            api_key_env="ZHIPU_API_KEY",
            model="GLM-5.2",
            timeout_seconds=60,
            fallback_models=["glm-4.7", "glm-4.6", "glm-4.5-air"],
            max_retries_per_model=1,
        )
        provider = ZhipuProvider(config, ROOT / "prompts")
        calls = []

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            calls.append(payload["model"])
            if payload["model"] == "glm-5.2":
                raise RuntimeError("model not found")
            return _FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

        with patch.dict("os.environ", {"ZHIPU_API_KEY": "secret-value"}, clear=False):
            with patch("urllib.request.urlopen", fake_urlopen):
                result = provider.request_json("Return JSON", {"task": "unit_test"}, required_keys=["ok"], max_retries=1)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls, ["glm-5.2", "glm-4.7"])
        self.assertEqual(provider.last_used_model, "glm-4.7")

    def test_title_request_supports_enabled_high_reasoning(self):
        provider = ZhipuProvider(self.config(), ROOT / "prompts")
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse({"choices": [{"message": {"content": "{\"ok\": true}"}}]})

        with patch.dict("os.environ", {"ZHIPU_API_KEY": "secret-value"}, clear=False):
            with patch("urllib.request.urlopen", fake_urlopen):
                provider.request_json(
                    "Return JSON",
                    {"task": "analyze_competitors_and_generate_title"},
                    required_keys=["ok"],
                    max_retries=1,
                    thinking_enabled=True,
                    reasoning_strength="high",
                )

        self.assertEqual(calls[0]["thinking"], {"type": "enabled"})
        self.assertEqual(calls[0]["max_tokens"], 24576)
        self.assertIn("Carefully verify", calls[0]["messages"][0]["content"])

    def test_zhipu_errors_mask_api_key(self):
        provider = ZhipuProvider(self.config(), ROOT / "prompts")

        with patch.dict("os.environ", {"ZHIPU_API_KEY": "secret-value"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=RuntimeError("secret-value failed")):
                with self.assertRaises(RuntimeError) as ctx:
                    provider.request_json("Return JSON", {"task": "unit_test"}, required_keys=["ok"], max_retries=1)

        self.assertNotIn("secret-value", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))
        self.assertIn("All Zhipu model requests failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
