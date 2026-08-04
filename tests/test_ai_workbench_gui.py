from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_provider import (  # noqa: E402
    AI_EXECUTION_MODE_MULTIMODAL,
    NVIDIA_MINIMAX_VISION_MODEL,
    NVIDIA_TEXT_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
)
from shopee_listing_app.gui_state import build_initial_gui_state  # noqa: E402
from shopee_listing_app.linear_workflow_ui import build_linear_home_html  # noqa: E402
from shopee_listing_app.web_gui import (  # noqa: E402
    action_save_ai_settings,
    parse_full_workflow_auto_retry_count,
    parse_vision_concurrency,
)


class AiWorkbenchGuiTests(unittest.TestCase):
    def html(self) -> str:
        with patch.dict(os.environ, {}, clear=True):
            return build_linear_home_html(build_initial_gui_state(ROOT / "config"))

    def test_home_is_english_and_uses_openai_multimodal_defaults(self):
        html = self.html()
        self.assertEqual(re.findall(r"[\u4e00-\u9fff]", html), [])
        self.assertIn("Shopee AI Listing Assistant", html)
        self.assertIn('value="multimodal" selected', html)
        self.assertIn(OPENAI_DEFAULT_MODEL, html)
        self.assertIn("OpenAI API Key", html)

    def test_model_options_show_real_model_ids(self):
        html = self.html()
        for model in (
            OPENAI_DEFAULT_MODEL,
            NVIDIA_VISION_DEFAULT_MODEL,
            NVIDIA_MINIMAX_VISION_MODEL,
            NVIDIA_TEXT_DEFAULT_MODEL,
        ):
            self.assertIn(model, html)
        self.assertNotIn("provided by", html.lower())

    def test_asset_pack_step_is_manual_only(self):
        html = self.html()
        self.assertIn("Manual Asset Pack Path", html)
        self.assertIn("Automatic asset-pack download: planned", html)
        self.assertNotIn("download-assets", html)
        self.assertNotIn("select-asset-version", html)

    def test_api_keys_are_blank_password_inputs(self):
        html = self.html()
        self.assertIn('id="openai_api_key" type="password"', html)
        self.assertNotRegex(html, r'id="openai_api_key"[^>]+value=')

    def test_saving_configuration_persists_openai_and_step_defaults(self):
        captured: dict[str, str] = {}
        payload = {
            "ai_execution_mode": AI_EXECUTION_MODE_MULTIMODAL,
            "vision_model": OPENAI_DEFAULT_MODEL,
            "vision_concurrency": "8",
            "full_workflow_auto_retry_count": "1",
            "vision_thinking_mode": "official_default",
            "vision_reasoning_strength": "official_default",
            "keyword_text_model": OPENAI_DEFAULT_MODEL,
            "keyword_thinking_mode": "official_default",
            "keyword_reasoning_strength": "official_default",
            "title_text_model": OPENAI_DEFAULT_MODEL,
            "title_thinking_mode": "official_default",
            "title_reasoning_strength": "official_default",
            "description_text_model": OPENAI_DEFAULT_MODEL,
            "description_thinking_mode": "official_default",
            "description_reasoning_strength": "official_default",
            "openai_api_key": "test-key-not-a-real-secret",
        }
        with patch(
            "shopee_listing_app.web_gui.save_local_env_values",
            side_effect=lambda values: captured.update(values),
        ), patch("shopee_listing_app.web_gui.load_project_env"):
            result = action_save_ai_settings(payload)

        self.assertIn("Configuration saved", result["message"])
        self.assertEqual(captured["AI_PROVIDER"], "openai")
        self.assertEqual(captured["AI_EXECUTION_MODE"], "multimodal")
        self.assertEqual(captured["OPENAI_MODEL"], OPENAI_DEFAULT_MODEL)
        self.assertEqual(captured["OPENAI_API_KEY"], "test-key-not-a-real-secret")
        for key in ("STEP3_AI_MODEL", "STEP5_AI_MODEL", "STEP6_AI_MODEL", "STEP7_AI_MODEL"):
            self.assertEqual(captured[key], OPENAI_DEFAULT_MODEL)

    def test_numeric_controls_validate_supported_ranges(self):
        self.assertEqual(parse_vision_concurrency({"vision_concurrency": "8"}), 8)
        self.assertEqual(parse_full_workflow_auto_retry_count({"full_workflow_auto_retry_count": "5"}), 5)
        for value in ("0", "21", "bad"):
            with self.assertRaises(RuntimeError):
                parse_vision_concurrency({"vision_concurrency": value})
        for value in ("0", "6", "bad"):
            with self.assertRaises(RuntimeError):
                parse_full_workflow_auto_retry_count({"full_workflow_auto_retry_count": value})


if __name__ == "__main__":
    unittest.main()
