from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.gtin_editor import gtin_handling_script
from shopee_listing_app.shopee.components.image_uploader import (
    set_file_input_files,
    step1_status_script,
    wait_for_promo_image,
)
from shopee_listing_app.shopee.components.next_step_handler import next_step_click_script
from shopee_listing_app.shopee.components.product_code_editor import product_code_fill_script


class Step1ComponentTests(unittest.TestCase):
    def test_step1_status_script_reports_required_first_page_state(self):
        script = step1_status_script()

        for text in [
            "isStep1",
            "productImageUpload",
            "promoImageUpload",
            "titleInput",
            "productCodeInput",
            "gtinInput",
            "nextStep",
            "missingRequired",
            "商品图片",
            "促销活动图片",
            "Next Step",
        ]:
            self.assertIn(text, script)

    def test_next_step_click_script_clicks_only_enabled_next_step(self):
        script = next_step_click_script()

        self.assertIn("Next Step", script)
        self.assertIn("!button.disabled", script)
        self.assertIn("button.click()", script)
        self.assertIn("hasStep2Signals", script)
        self.assertIn("Previous", script)

    def test_product_code_script_avoids_gtin_like_input(self):
        script = product_code_fill_script("SKU-001")

        self.assertIn("SKU-001", script)
        self.assertIn("商品代码", script)
        self.assertIn("GTIN", script)
        self.assertIn("通用商品代码", script)
        self.assertIn("skipGtinLike", script)

    def test_gtin_script_never_fills_fake_gtin(self):
        script = gtin_handling_script()

        self.assertIn("withoutGtin", script)
        self.assertIn("没有GTIN", script)
        self.assertNotIn("000000", script)

    def test_file_input_upload_enables_dom_before_setting_files(self):
        class FakeClient:
            def __init__(self):
                self.commands = []

            def command(self, name, params=None):
                self.commands.append((name, params or {}))
                if name == "DOM.getDocument":
                    return {"root": {"nodeId": 1}}
                if name == "DOM.querySelectorAll":
                    return {"nodeIds": [101]}
                return {}

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "main.jpg"
            image_path.write_bytes(b"fake image")
            client = FakeClient()

            set_file_input_files(client, 0, [str(image_path)])

        self.assertEqual(client.commands[0][0], "DOM.enable")
        self.assertEqual(client.commands[-1][0], "DOM.setFileInputFiles")
        self.assertEqual(client.commands[-1][1]["nodeId"], 101)

    def test_wait_for_promo_image_uses_promo_count(self):
        class FakeClient:
            def evaluate(self, script):
                return {"result": {"value": {"promoImageCount": 1, "loadingSlots": 0}}}

        status = wait_for_promo_image(FakeClient(), minimum_count=1, timeout_seconds=1)

        self.assertEqual(status["promoImageCount"], 1)


if __name__ == "__main__":
    unittest.main()
