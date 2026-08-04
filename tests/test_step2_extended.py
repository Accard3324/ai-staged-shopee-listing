from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.pre_save_checker import PRE_SAVE_CHECK_SCRIPT
from shopee_listing_app.shopee.components.variation_editor import (
    package_and_parent_fill_script,
    package_and_parent_status_script,
    variation_image_targets_script,
    variation_options_fill_script,
    variation_rows_fill_script,
)
from shopee_listing_app.shopee.components.step2_minimal import brand_fill_script
from shopee_listing_app.shopee.components.step2_extended import step2_extended_fill_script


class Step2ExtendedTests(unittest.TestCase):
    def test_extended_fill_script_covers_variation_prices_stock_sku_shipping(self):
        script = step2_extended_fill_script(
            {
                "sku_code": "SKU-001",
                "variations": [
                    {"name": "20g /1box", "price": "9.90", "stock": "88", "item_code": "SKU-001"},
                    {"name": "2x 20g /2box", "price": "18.80", "stock": "88", "item_code": "SKU-001"},
                    {"name": "3x 20g /3box", "price": "27.50", "stock": "88", "item_code": "SKU-001"},
                ],
                "package": {"weight_kg": "0.05", "length_cm": "10", "width_cm": "5", "height_cm": "3"},
            }
        )

        for text in [
            "tierVariation_0",
            "Quantity",
            "variation-model-table-container",
            "price",
            "stock",
            "sku",
            "dimension.width",
            "dimension.length",
            "dimension.height",
            "Doorstep",
            "parentSku",
        ]:
            self.assertIn(text, script)
        self.assertNotIn("rows[i + 3]", script)

    def test_pre_save_check_has_strict_required_items(self):
        for text in [
            "imageCount",
            "unsafeImageSignals",
            "hasThreeVariationRows",
            "variationImagesOk",
            "pricesOk",
            "stockOk",
            "skuCodesOk",
            "weightDimensionOk",
            "shippingOk",
            "parentSkuOk",
            "visibleErrors",
            "canSaveDelist",
        ]:
            self.assertIn(text, PRE_SAVE_CHECK_SCRIPT)
        self.assertIn("variation-model-table-fixed-left", PRE_SAVE_CHECK_SCRIPT)
        self.assertIn("nearestDataRow", PRE_SAVE_CHECK_SCRIPT)

    def test_package_fill_waits_for_shopee_component_and_verifies_final_values(self):
        package = {"weight_kg": "0.04", "length_cm": "8", "width_cm": "3", "height_cm": "9"}

        fill_script = package_and_parent_fill_script(package, "SKU-001")
        status_script = package_and_parent_status_script(package, "SKU-001")

        self.assertIn("(async () =>", fill_script)
        self.assertIn("await delay(350)", fill_script)
        self.assertIn("valuesEquivalent", fill_script)
        self.assertIn('await fillField("weight"', fill_script)
        self.assertIn("valuesEquivalent", status_script)
        self.assertIn("values:", status_script)

    def test_variation_options_skip_description_inputs(self):
        script = variation_options_fill_script(
            [
                {"name": "20g /1box"},
                {"name": "2x 20g /2box"},
                {"name": "3x 20g /3box"},
            ]
        )

        self.assertIn("添加说明", script)
        self.assertIn("optionInputs", script)

    def test_variation_rows_map_label_panel_to_data_panel_without_row_indexes(self):
        script = variation_rows_fill_script([{"name": "20g /1box"}], "SKU-001")

        self.assertIn("variation-model-table-fixed-left", script)
        self.assertIn("nearestDataRow", script)
        self.assertIn("instanceof HTMLTextAreaElement", script)
        self.assertIn("noGtin.checked", script)
        self.assertNotIn("rows[i + 3]", script)

    def test_variation_image_targets_use_the_same_dynamic_row_mapping(self):
        script = variation_image_targets_script([{"name": "20g /1box"}])

        self.assertIn("variation-model-table-fixed-left", script)
        self.assertIn("labelRow?.row.querySelector", script)

    def test_brand_fill_accepts_existing_no_brand_fallback(self):
        script = brand_fill_script("EELHOE")

        self.assertIn("already_selected_no_brand", script)


if __name__ == "__main__":
    unittest.main()
