from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_provider import (  # noqa: E402
    AI_MODEL_LABELS,
    MULTIMODAL_AI_MODELS,
    NvidiaDualProvider,
    OPENAI_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_MODEL,
    VISION_TEXT_AI_MODELS,
    get_ai_provider,
)
from shopee_listing_app.config_manager import AIConfig  # noqa: E402


class _ImmediateRequestController:
    rate_limit_report = {}

    def execute(self, func, **_kwargs):
        return func()


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class NvidiaDualProviderTests(unittest.TestCase):
    def provider(self) -> NvidiaDualProvider:
        return NvidiaDualProvider(
            AIConfig(
                provider="openai",
                endpoint=OPENAI_DEFAULT_BASE_URL,
                api_key_env="OPENAI_API_KEY",
                model=OPENAI_DEFAULT_MODEL,
                timeout_seconds=900,
            ),
            ROOT / "prompts",
            request_controller=_ImmediateRequestController(),
        )

    def test_openai_is_the_default_real_model_id(self):
        self.assertEqual(AI_MODEL_LABELS[OPENAI_DEFAULT_MODEL], OPENAI_DEFAULT_MODEL)
        self.assertEqual(MULTIMODAL_AI_MODELS[0], OPENAI_DEFAULT_MODEL)
        self.assertIn(OPENAI_DEFAULT_MODEL, VISION_TEXT_AI_MODELS)

    def test_factory_returns_the_openai_capable_provider(self):
        provider = get_ai_provider(
            AIConfig(
                provider="openai",
                endpoint=OPENAI_DEFAULT_BASE_URL,
                api_key_env="OPENAI_API_KEY",
                model=OPENAI_DEFAULT_MODEL,
                timeout_seconds=900,
            ),
            ROOT / "prompts",
        )
        self.assertIsInstance(provider, NvidiaDualProvider)

    def test_missing_openai_key_has_actionable_error(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                self.provider().request_text_json(
                    "Return JSON.",
                    {"task": "test"},
                    ["ok"],
                    model_override=OPENAI_DEFAULT_MODEL,
                )

    def test_openai_text_request_uses_chat_completions_and_json_mode(self):
        response = _JsonResponse(
            {"choices": [{"message": {"content": '{"ok": true}'}}]}
        )
        urlopen = Mock(return_value=response)
        with patch("urllib.request.urlopen", urlopen), patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "OPENAI_MODEL": OPENAI_DEFAULT_MODEL,
                "OPENAI_MAX_OUTPUT_TOKENS": "32768",
            },
            clear=False,
        ):
            result = self.provider().request_text_json(
                "Return JSON.",
                {"task": "test"},
                ["ok"],
                model_override=OPENAI_DEFAULT_MODEL,
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-openai-key")
        self.assertEqual(body["model"], OPENAI_DEFAULT_MODEL)
        self.assertEqual(body["max_completion_tokens"], 32768)
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_openai_multimodal_request_embeds_local_image(self):
        response = _JsonResponse(
            {"choices": [{"message": {"content": '{"ok": true}'}}]}
        )
        urlopen = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "product.jpg"
            image_path.write_bytes(b"image-bytes")
            with patch("urllib.request.urlopen", urlopen), patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "test-openai-key"},
                clear=False,
            ):
                result = self.provider().request_multimodal_json(
                    OPENAI_DEFAULT_MODEL,
                    "Return JSON.",
                    {"task": "test"},
                    [str(image_path)],
                    ["ok"],
                )

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        user_content = body["messages"][1]["content"]
        self.assertTrue(result["ok"])
        self.assertEqual(user_content[0]["type"], "text")
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertTrue(
            user_content[1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"
            )
        )

    def test_errors_mask_the_openai_key(self):
        secret = "test-secret-that-must-not-leak"
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False), patch(
            "urllib.request.urlopen",
            side_effect=RuntimeError(secret + " failed"),
        ):
            with self.assertRaises(RuntimeError) as context:
                self.provider().request_text_json(
                    "Return JSON.",
                    {"task": "test"},
                    ["ok"],
                    model_override=OPENAI_DEFAULT_MODEL,
                )
        self.assertNotIn(secret, str(context.exception))


if __name__ == "__main__":
    unittest.main()
