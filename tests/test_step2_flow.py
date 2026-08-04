from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.product_new_page import (
    build_step2_probe_markdown,
    run_optional_step2_field,
    save_step2_probe_artifacts,
)


class Step2FlowTests(unittest.TestCase):
    def test_optional_step2_field_skips_operation_error(self):
        def fail():
            raise RuntimeError("field not found")

        result = run_optional_step2_field("卫生部认证", fail)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "skipped_optional_field_error")
        self.assertEqual(result["field"], "卫生部认证")
        self.assertIn("field not found", result["error"])

    def test_optional_step2_field_skips_failed_result(self):
        result = run_optional_step2_field(
            "卫生部认证",
            lambda: {"ok": False, "reason": "option not found"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "skipped_optional_field_failed")
        self.assertEqual(result["originalResult"]["reason"], "option not found")

    def test_optional_step2_field_preserves_success(self):
        success = {"ok": True, "action": "selected_no_by_mouse"}

        result = run_optional_step2_field("卫生部认证", lambda: success)

        self.assertIs(result, success)

    def test_build_step2_probe_markdown_summarizes_fields(self):
        probe = {
            "page": {"url": "https://seller.shopee.com.my/portal/product/new", "title": "Shopee"},
            "step2Status": {
                "category": True,
                "brand": True,
                "attributes": False,
                "description": {"hasQuill": True},
                "variation": True,
                "price": True,
                "stock": True,
                "skuItemCode": True,
                "weightDimension": False,
                "logistics": False,
                "buttons": {"saveDelist": False},
            },
            "locatorPlan": {"brand": "brand locator"},
        }

        markdown = build_step2_probe_markdown(probe)

        self.assertIn("Step 2 Page Probe", markdown)
        self.assertIn("category: True", markdown)
        self.assertIn("brand locator", markdown)

    def test_save_step2_probe_artifacts_uses_required_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifacts = save_step2_probe_artifacts(
                base,
                {"page": {"url": "u"}, "step2Status": {}, "locatorPlan": {}},
                html="<html></html>",
                screenshot_base64="",
                stamp="20260707_010203",
            )

            self.assertEqual(artifacts["report_path"].name, "step2_page_probe_20260707_010203.md")
            self.assertEqual(artifacts["json_path"].name, "step2_page_probe_20260707_010203.json")
            self.assertEqual(artifacts["html_path"].name, "step2_page_probe_20260707_010203.html")
            self.assertEqual(artifacts["screenshot_path"].name, "step2_page_probe_20260707_010203.png")
            self.assertTrue(artifacts["report_path"].exists())
            self.assertTrue(artifacts["json_path"].exists())
            self.assertTrue(artifacts["html_path"].exists())
            self.assertTrue(artifacts["screenshot_path"].exists())


if __name__ == "__main__":
    unittest.main()
