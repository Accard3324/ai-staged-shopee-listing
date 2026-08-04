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
    AGNES_VISION_DEFAULT_MODEL,
    AI_EXECUTION_MODE_MULTIMODAL,
    AI_EXECUTION_MODE_VISION_TEXT,
    MULTIMODAL_PRODUCT_PROMPT_PREFIX,
    NVIDIA_MINIMAX_VISION_MODEL,
    NVIDIA_TEXT_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    NvidiaDualProvider,
    _normalize_single_image_result,
    model_reasoning_profile,
)
from shopee_listing_app.asset_inspector import AssetManifest  # noqa: E402
from shopee_listing_app.config_manager import AIConfig  # noqa: E402
from shopee_listing_app.gui_state import build_initial_gui_state  # noqa: E402
from shopee_listing_app.linear_workflow_ui import build_linear_home_html  # noqa: E402
from shopee_listing_app.web_gui import (  # noqa: E402
    multimodal_product_image_paths,
    parse_step_text_model,
)


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


class AIExecutionModeTests(unittest.TestCase):
    def provider(self) -> NvidiaDualProvider:
        return NvidiaDualProvider(
            AIConfig(
                provider="nvidia_dual",
                endpoint="",
                api_key_env="NVIDIA_TEXT_API_KEY",
                model="",
                timeout_seconds=90,
            ),
            ROOT / "prompts",
            request_controller=_ImmediateRequestController(),
        )

    def test_ui_shows_per_step_models_and_exact_software_token_values(self):
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": AI_EXECUTION_MODE_VISION_TEXT,
                "STEP3_AI_MODEL": NVIDIA_VISION_DEFAULT_MODEL,
                "STEP5_AI_MODEL": AGNES_VISION_DEFAULT_MODEL,
                "STEP6_AI_MODEL": NVIDIA_TEXT_DEFAULT_MODEL,
                "STEP7_AI_MODEL": OPENAI_DEFAULT_MODEL,
            },
            clear=False,
        ):
            html = build_linear_home_html(build_initial_gui_state(ROOT / "config"))

        for marker in (
            'id="ai_execution_mode"',
            'id="vision_model"',
            'id="keyword_text_model"',
            'id="title_text_model"',
            'id="description_text_model"',
            '"maximum": 65536',
            '"maximum": 32768',
            '"maximum": 8192',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("Qwen3.5", html)

    def test_model_reasoning_profiles_use_existing_request_mappings(self):
        openai = model_reasoning_profile(OPENAI_DEFAULT_MODEL, "text")
        qwen = model_reasoning_profile(NVIDIA_VISION_DEFAULT_MODEL, "text")
        agnes = model_reasoning_profile(AGNES_VISION_DEFAULT_MODEL, "text")
        minimax = model_reasoning_profile(NVIDIA_MINIMAX_VISION_MODEL, "text")
        glm = model_reasoning_profile(NVIDIA_TEXT_DEFAULT_MODEL, "text")

        self.assertEqual(openai["budgets"]["maximum"], 32768)
        self.assertEqual(qwen["budgets"]["maximum"], 32768)
        self.assertEqual(agnes["budgets"]["maximum"], 65536)
        self.assertEqual(minimax["budgets"]["maximum"], 8192)
        self.assertEqual(glm["budgets"]["maximum"], 32768)

    def test_multimodal_mode_limits_text_steps_to_image_capable_models(self):
        payload = {
            "ai_execution_mode": AI_EXECUTION_MODE_MULTIMODAL,
            "keyword_text_model": OPENAI_DEFAULT_MODEL,
        }
        self.assertEqual(
            parse_step_text_model(payload, "keyword_text_model"),
            OPENAI_DEFAULT_MODEL,
        )
        payload["keyword_text_model"] = NVIDIA_TEXT_DEFAULT_MODEL
        with self.assertRaisesRegex(RuntimeError, "not available"):
            parse_step_text_model(payload, "keyword_text_model")

    def test_multimodal_images_use_details_and_english_then_fall_back_to_sku(self):
        manifest = AssetManifest(
            source_path="source",
            extracted_root="root",
            selected_root="selected",
            detail_images=["detail-1.jpg", "detail-2.jpg"],
            english_images=["english-1.jpg"],
            sku_images=["sku-1.jpg"],
        )
        self.assertEqual(
            multimodal_product_image_paths(manifest),
            ["detail-1.jpg", "detail-2.jpg", "english-1.jpg"],
        )
        fallback = AssetManifest(
            source_path="source",
            extracted_root="root",
            selected_root="selected",
            detail_images=["detail-1.jpg"],
            sku_images=["sku-1.jpg", "sku-2.jpg"],
        )
        self.assertEqual(
            multimodal_product_image_paths(fallback),
            ["detail-1.jpg", "sku-1.jpg", "sku-2.jpg"],
        )

    def test_multimodal_request_uses_text_task_limits_and_embeds_images(self):
        response = _JsonResponse(
            {"choices": [{"message": {"content": '{"ok": true}'}}]}
        )
        urlopen = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "detail.jpg"
            image_path.write_bytes(b"test-image")
            with patch(
                "urllib.request.urlopen",
                urlopen,
            ), patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "safe-test-key",
                    "OPENAI_MAX_OUTPUT_TOKENS": "32768",
                },
                clear=False,
            ):
                result = self.provider().request_multimodal_json(
                    OPENAI_DEFAULT_MODEL,
                    MULTIMODAL_PRODUCT_PROMPT_PREFIX,
                    {
                        "task": "generate_search_keywords",
                        "generation_settings": {
                            "thinking_mode": "enabled",
                            "reasoning_strength": "maximum",
                        },
                    },
                    [str(image_path)],
                    ["ok"],
                )

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(body["max_completion_tokens"], 32768)
        self.assertEqual(body["model"], OPENAI_DEFAULT_MODEL)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(
            body["messages"][0]["content"].splitlines()[0],
            MULTIMODAL_PRODUCT_PROMPT_PREFIX,
        )
        user_content = body["messages"][1]["content"]
        self.assertEqual(user_content[0]["type"], "text")
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertTrue(user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_multimodal_selection_only_rejects_only_oem_or_duplicates(self):
        risk_rejected = _normalize_single_image_result(
            {
                "selection_assessment": {
                    "suitable_for_listing": False,
                    "recommended_role": "detail_image",
                    "upload_score": 0,
                    "selection_reasons": ["The image is visually weak."],
                }
            },
            file_name="detail.jpg",
            file_path="detail.jpg",
            folder_type="detail_image",
            status="analysis_succeeded",
            selection_only=True,
        )
        duplicate = _normalize_single_image_result(
            {
                "selection_assessment": {
                    "suitable_for_listing": True,
                    "recommended_role": "detail_image",
                    "upload_score": 80,
                    "selection_reasons": ["Duplicate of another image."],
                }
            },
            file_name="duplicate.jpg",
            file_path="duplicate.jpg",
            folder_type="detail_image",
            status="analysis_succeeded",
            selection_only=True,
        )

        self.assertTrue(
            risk_rejected["selection_assessment"]["suitable_for_listing"]
        )
        self.assertFalse(
            duplicate["selection_assessment"]["suitable_for_listing"]
        )


if __name__ == "__main__":
    unittest.main()
