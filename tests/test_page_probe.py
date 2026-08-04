from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.page_probe import (
    build_probe_markdown,
    real_page_probe_script,
    safe_capture_screenshot,
    save_probe_artifacts,
)


class PageProbeTests(unittest.TestCase):
    def test_real_page_probe_script_collects_required_dom_details(self):
        script = real_page_probe_script()

        for text in [
            "bodyTextSample",
            "visibleInputs",
            "visibleTextareas",
            "titleRegions",
            "quill",
            "imageUploadDetected",
            "variationDetected",
            "priceStockDetected",
            "logisticsDetected",
            "outerHTML",
            "likelyField",
            ".edit-row",
            "品牌名称 + 商品类型",
            "hasTitleSignal",
            "step1Status",
            "missingRequired",
            "productImageUpload",
            "nextStep",
        ]:
            self.assertIn(text, script)

    def test_probe_artifacts_are_written_with_required_names(self):
        probe = {
            "cdpPort": 60094,
            "selectedPage": {"url": "https://seller.shopee.com.my/portal/product/new"},
            "page": {"title": "Shopee卖家中心", "bodyTextSample": "Basic Information Product Name"},
            "visibleInputs": [{"index": 0, "placeholder": "Please enter product name", "likelyField": "title"}],
            "visibleTextareas": [],
            "titleCandidates": [{"selector": "input[placeholder='Please enter product name']", "score": 100}],
            "quill": {"hasContainer": True, "hasEditor": True, "selector": ".ql-editor"},
            "fillCheck": {"titleOk": True, "descriptionOk": True},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifacts = save_probe_artifacts(
                base,
                probe,
                html="<html></html>",
                screenshot_base64="",
                stamp="20260706_210000",
            )

            self.assertTrue(artifacts["report_path"].name.startswith("real_page_probe_20260706_210000"))
            self.assertTrue(artifacts["json_path"].exists())
            self.assertTrue(artifacts["html_path"].exists())
            self.assertTrue(artifacts["screenshot_path"].exists())
            self.assertIn("Live title input", build_probe_markdown(probe))

    def test_safe_capture_screenshot_does_not_block_probe(self):
        class BrokenClient:
            def capture_screenshot(self):
                raise TimeoutError("screenshot timed out")

        self.assertEqual(safe_capture_screenshot(BrokenClient()), "")


if __name__ == "__main__":
    unittest.main()
