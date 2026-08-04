from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.config_manager import load_app_config


class StoreMappingTests(unittest.TestCase):
    def test_configured_stores_keep_required_status_columns(self):
        config = load_app_config(ROOT / "config")

        self.assertEqual(config.store("Shopee-MY-Store-A").status_column, "D")
        self.assertEqual(config.store("Shopee-MY-Store-B").status_column, "C")
        self.assertEqual(config.store("Shopee-MY-Store-C").status_column, "B")
        self.assertEqual(config.store("Shopee-MY-Store-A").listing_sheet, "StoreAListings")
        self.assertEqual(config.store("Shopee-MY-Store-B").listing_sheet, "StoreBListings")
        self.assertEqual(config.store("Shopee-MY-Store-C").listing_sheet, "StoreCListings")

    def test_all_description_templates_are_blank(self):
        config = load_app_config(ROOT / "config")

        self.assertEqual(
            config.templates,
            {"Store A": "", "Store B": "", "Store C": ""},
        )


if __name__ == "__main__":
    unittest.main()
