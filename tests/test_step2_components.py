from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.step2_probe import step2_probe_script
from shopee_listing_app.shopee.components.step2_minimal import (
    brand_mouse_probe_script,
    brand_fill_script,
    description_fill_script,
    health_certification_probe_script,
    step2_minimal_fill_script,
)


class Step2ComponentTests(unittest.TestCase):
    def test_step2_probe_script_reports_required_fields(self):
        script = step2_probe_script()

        for text in [
            "step2Status",
            "bodyTextSample",
            "category",
            "brand",
            "attributes",
            "description",
            "categoryCandidates",
            ".category-select-row-text",
            "categoryLocked",
            "video",
            "variation",
            "price",
            "stock",
            "skuItemCode",
            "weightDimension",
            "logistics",
            "visibleInputs",
            "visibleTextareas",
            "visibleButtons",
            "locatorPlan",
        ]:
            self.assertIn(text, script)

    def test_brand_fill_script_targets_brand_without_using_gtin(self):
        script = brand_fill_script("EELHOE")

        self.assertIn("EELHOE", script)
        self.assertIn("brand", script.lower())
        self.assertIn(".product-brand-item", script)
        self.assertIn("brand exact option not found", script)
        self.assertIn("selected_no_brand_fallback", script)
        self.assertIn("NoBrand", script)
        self.assertIn(".brand-rcmd-box__item", script)
        self.assertIn("clicked_recommended_brand", script)
        self.assertIn("clickTarget", script)
        self.assertIn("closest(\"li,[role='option'],.eds-option\")", script)
        self.assertNotIn("filled_visible_input", script)
        self.assertNotIn("GTIN", script)

    def test_brand_mouse_probe_reports_selector_and_option_rects(self):
        script = brand_mouse_probe_script("EELHOE")

        self.assertIn(".product-brand-item", script)
        self.assertIn(".eds-option", script)
        self.assertIn("selectorRect", script)
        self.assertIn("recommendedOption", script)
        self.assertIn("noBrandOption", script)

    def test_description_script_emits_valid_javascript_regex_escapes(self):
        script = description_fill_script("Line one\n\nLine two")

        self.assertIn(r"/\n{2,}/g", script)
        self.assertIn(r"/<p><br><\/p>/g", script)
        self.assertNotIn(r"/<p><br><\\/p>/g", script)

    def test_health_certification_probe_targets_required_no_value(self):
        script = health_certification_probe_script()

        self.assertIn("product-attribute-item-100966", script)
        self.assertIn("卫生部认证", script)
        self.assertIn("noOption", script)

    def test_step2_minimal_fill_script_uses_quill_and_checks_sku_textareas(self):
        script = step2_minimal_fill_script(
            "EELHOE",
            "Greetings, Valued Shopper!\nProduct Highlights",
            "EELHOE 肌肤平滑护理膏 20g/盒 Shopee Malaysia",
        )

        self.assertIn(".ql-container", script)
        self.assertIn(".ql-editor", script)
        self.assertIn("skuTextareas", script)
        self.assertIn("clearedAttributeInputs", script)
        self.assertIn("data-product-edit-field-unique-id='name'", script)
        self.assertIn("description", script)
        self.assertIn("brandResult", script)
        self.assertIn("noBlankParagraphs", script)


if __name__ == "__main__":
    unittest.main()
