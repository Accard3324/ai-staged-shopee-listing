from __future__ import annotations

import os
from pathlib import Path
import json
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shopee_listing_app.web_gui as web_gui  # noqa: E402
from shopee_listing_app.ai_provider import OPENAI_DEFAULT_MODEL  # noqa: E402
from shopee_listing_app.gui_state import build_initial_gui_state  # noqa: E402
from shopee_listing_app.linear_workflow_ui import build_linear_home_html  # noqa: E402


class WebGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_state = web_gui._DEFAULT_APP_STATE
        web_gui._DEFAULT_APP_STATE = web_gui.WebAppState()
        web_gui._TASK_STATES.clear()
        web_gui._MULTI_GROUPS.clear()
        web_gui._SKU_RESERVATIONS.clear()

    def tearDown(self) -> None:
        web_gui._DEFAULT_APP_STATE = self.previous_state
        web_gui._TASK_STATES.clear()
        web_gui._MULTI_GROUPS.clear()
        web_gui._SKU_RESERVATIONS.clear()

    def home_html(self) -> str:
        with patch.dict(os.environ, {}, clear=True):
            return build_linear_home_html(build_initial_gui_state(ROOT / "config"))

    def test_home_is_english_and_contains_the_complete_linear_workflow(self):
        html = self.home_html()
        self.assertEqual(re.findall(r"[\u4e00-\u9fff]", html), [])
        self.assertEqual(html.count('class="workflow-step"'), 16)
        step_positions = [html.index(f"Step {step}") for step in range(16)]
        self.assertEqual(step_positions, sorted(step_positions))

    def test_openai_multimodal_is_the_default(self):
        html = self.home_html()
        self.assertIn('value="multimodal" selected', html)
        self.assertIn(OPENAI_DEFAULT_MODEL, html)
        self.assertIn("OpenAI API Key", html)
        self.assertEqual(web_gui.parse_ai_execution_mode({}), "multimodal")

    def test_step_zero_can_add_and_save_a_custom_store_name(self):
        html = self.home_html()
        self.assertIn('id="custom_store_name"', html)
        self.assertIn("Add and Save Store", html)
        self.assertIn("reuse the selected store's workbook status column", html)

    def test_steps_3_5_6_7_prompt_editors_start_blank(self):
        html = self.home_html()
        for key in (
            "image_analysis",
            "keyword_generation",
            "competitor_title_analysis",
            "description_generation",
        ):
            self.assertIn(f'<textarea id="prompt_{key}"></textarea>', html)
        self.assertIn("Templates are blank by default.", html)

    def test_custom_store_action_is_available(self):
        expected = {"message": "saved"}
        with patch.object(
            web_gui,
            "action_save_custom_store",
            return_value=expected,
        ) as save_action:
            result = web_gui.handle_action(
                "save-custom-store",
                {"store": "Base Store", "custom_store_name": "New Store"},
            )

        self.assertEqual(result, expected)
        save_action.assert_called_once()

    def test_empty_description_template_can_be_saved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_dir = project_root / "config"
            config_dir.mkdir()
            stores_path = config_dir / "stores.yaml"
            stores_path.write_text(
                json.dumps({"description_templates": {"Store A": "old"}}),
                encoding="utf-8",
            )
            with patch.object(web_gui, "PROJECT_ROOT", project_root), patch.object(
                web_gui,
                "_resolve_store_template",
                return_value=("Shopee-MY-Store-A", "Store A", "old"),
            ):
                result = web_gui.action_save_description_template(
                    {"store": "Shopee-MY-Store-A", "description_template": ""}
                )

            stored = json.loads(stores_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["description_templates"]["Store A"], "")
            self.assertIn("cleared", result["message"])

    def test_asset_pack_flow_is_manual_only(self):
        html = self.home_html()
        self.assertIn("Manual Asset Pack Path", html)
        self.assertIn("Automatic asset-pack download: planned", html)
        self.assertNotIn("download-assets", html)
        self.assertNotIn("select-asset-version", html)
        with self.assertRaisesRegex(RuntimeError, "Unknown action"):
            web_gui.handle_action("download-assets", {})
        with self.assertRaisesRegex(RuntimeError, "Unknown action"):
            web_gui.handle_action("select-asset-version", {})

    def test_ai_key_input_is_blank_and_masked(self):
        html = self.home_html()
        self.assertIn('id="openai_api_key" type="password"', html)
        self.assertNotRegex(html, r'id="openai_api_key"[^>]+value=')

    def test_manual_asset_path_error_explains_planned_download(self):
        web_gui._DEFAULT_APP_STATE.current_candidate = object()
        with self.assertRaisesRegex(
            RuntimeError,
            "manually supplied asset pack.*planned",
        ):
            web_gui.action_inspect_assets({"asset_path": ""})


if __name__ == "__main__":
    unittest.main()
