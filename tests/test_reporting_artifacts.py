from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.reporting.screenshot_manager import save_base64_screenshot
from shopee_listing_app.reporting.html_snapshot import save_html_snapshot
from shopee_listing_app.reporting.final_report import (
    save_page_diagnostics,
    write_autofill_failure_log,
    write_autofill_failure_report,
)


class ReportingArtifactsTests(unittest.TestCase):
    def test_failure_artifacts_are_written_with_stage_and_sku(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            screenshot = save_base64_screenshot("", base, "SKU-001", "fill_title")
            html = save_html_snapshot("<html></html>", base, "SKU-001", "fill_title")
            diagnostics = save_page_diagnostics(
                {"url": "https://seller.shopee.com.my/portal/product/new"},
                base,
                "SKU-001",
                "fill_title",
            )
            report = write_autofill_failure_report(
                base,
                sku_code="SKU-001",
                stage="fill_title",
                reason="field not found",
                screenshot_path=screenshot,
                html_path=html,
                diagnostics_path=diagnostics,
            )
            log = write_autofill_failure_log(
                base,
                sku_code="SKU-001",
                stage="fill_title",
                reason="field not found",
                screenshot_path=screenshot,
                html_path=html,
                diagnostics_path=diagnostics,
                report_path=report,
            )

            self.assertTrue(screenshot.exists())
            self.assertTrue(html.exists())
            self.assertTrue(diagnostics.exists())
            self.assertTrue(report.exists())
            self.assertTrue(log.exists())
            self.assertIn("SKU-001", report.read_text(encoding="utf-8"))
            self.assertIn("fill_title", report.read_text(encoding="utf-8"))
            self.assertIn("Diagnostics", report.read_text(encoding="utf-8"))
            self.assertIn("diagnostics=", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
