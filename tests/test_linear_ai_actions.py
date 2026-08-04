from __future__ import annotations

import os
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shopee_listing_app.web_gui as web_gui  # noqa: E402
from shopee_listing_app.asset_inspector import AssetManifest  # noqa: E402


def asset_manifest(**overrides) -> AssetManifest:
    values = {
        "source_path": "C:/assets/product.zip",
        "extracted_root": "C:/assets/extracted",
        "selected_root": "C:/assets/extracted",
        "main_images": ["C:/assets/main.jpg"],
        "detail_images": ["C:/assets/detail-1.jpg", "C:/assets/detail-2.jpg"],
        "english_images": ["C:/assets/english.jpg"],
        "parameter_images": [],
        "sku_images": ["C:/assets/sku.jpg"],
        "information_images": [],
        "videos": [],
        "unsafe_images": [],
        "warnings": [],
    }
    values.update(overrides)
    return AssetManifest(**values)


class LinearAiActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_state = web_gui._DEFAULT_APP_STATE
        web_gui._DEFAULT_APP_STATE = web_gui.WebAppState()

    def tearDown(self) -> None:
        web_gui._DEFAULT_APP_STATE = self.previous_state

    def test_default_execution_mode_is_multimodal(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(web_gui.parse_ai_execution_mode({}), "multimodal")

    def test_multimodal_image_paths_use_details_then_english_materials(self):
        manifest = asset_manifest()
        self.assertEqual(
            web_gui.multimodal_product_image_paths(manifest),
            [
                "C:/assets/detail-1.jpg",
                "C:/assets/detail-2.jpg",
                "C:/assets/english.jpg",
            ],
        )

    def test_multimodal_image_paths_fall_back_to_sku_images(self):
        manifest = asset_manifest(english_images=[])
        self.assertEqual(
            web_gui.multimodal_product_image_paths(manifest),
            [
                "C:/assets/detail-1.jpg",
                "C:/assets/detail-2.jpg",
                "C:/assets/sku.jpg",
            ],
        )

    def test_multimodal_product_inputs_send_images_without_text_record(self):
        web_gui._DEFAULT_APP_STATE.asset_manifest = asset_manifest()
        mode, product_info, paths = web_gui.ai_step_product_inputs({})
        self.assertEqual(mode, "multimodal")
        self.assertEqual(product_info, {})
        self.assertEqual(paths[-1], "C:/assets/english.jpg")

    def test_multimodal_product_inputs_require_an_asset_pack(self):
        with self.assertRaisesRegex(RuntimeError, "Load an asset pack"):
            web_gui.ai_step_product_inputs({})

    def test_vision_plus_text_mode_uses_the_objective_record(self):
        payload = {
            "ai_execution_mode": "vision_text",
            "ai_product_info": json.dumps(
                {
                    "product_type": "Portable fan",
                    "visible_ingredients_or_materials": ["ABS"],
                    "visible_claims": ["Three speed settings"],
                }
            ),
        }
        mode, product_info, paths = web_gui.ai_step_product_inputs(payload)
        self.assertEqual(mode, "vision_text")
        self.assertEqual(product_info["product_type"], "Portable fan")
        self.assertEqual(product_info["visible_ingredients_or_materials"], ["ABS"])
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
