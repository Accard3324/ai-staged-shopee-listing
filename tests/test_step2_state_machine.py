from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.step2_state_machine import STEP2_STAGES


class Step2StateMachineTests(unittest.TestCase):
    def test_variation_and_logistics_stages_follow_required_dependency_order(self):
        self.assertEqual(
            STEP2_STAGES,
            [
                "title",
                "category",
                "brand_attributes",
                "description",
                "video",
                "enable_variation",
                "create_variation_options",
                "wait_for_variation_rows",
                "variation_images",
                "variation_prices",
                "variation_stock",
                "variation_sku",
                "variation_gtin",
                "package",
                "logistics",
                "parent_sku",
                "pre_save_check",
                "save_delist",
            ],
        )


if __name__ == "__main__":
    unittest.main()
