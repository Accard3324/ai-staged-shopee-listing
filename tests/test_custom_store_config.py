from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.config_manager import add_custom_store_name, load_app_config


class CustomStoreConfigTests(unittest.TestCase):
    def make_config(self, base: Path) -> Path:
        config_dir = base / "config"
        config_dir.mkdir()
        (config_dir / "stores.yaml").write_text(
            json.dumps(
                {
                    "stores": [
                        {
                            "name": "Base Store",
                            "status_column": "D",
                            "template_key": "Base Template",
                            "listing_sheet": "StoreAListings",
                            "aliases": ["Base Store"],
                        }
                    ],
                    "description_templates": {"Base Template": ""},
                }
            ),
            encoding="utf-8",
        )
        (config_dir / "workbook.yaml").write_text(
            json.dumps(
                {
                    "path": "products.xlsx",
                    "sheet_prefix": "Income",
                    "unlisted_status": "Unlisted",
                    "field_columns": {"sku": "A"},
                }
            ),
            encoding="utf-8",
        )
        (config_dir / "ai.yaml").write_text(
            json.dumps(
                {
                    "provider": "openai",
                    "openai": {"model": "gpt-5.6"},
                }
            ),
            encoding="utf-8",
        )
        return config_dir

    def test_custom_name_is_saved_with_the_selected_store_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = self.make_config(Path(temp_dir))

            store, created = add_custom_store_name(
                config_dir,
                "Base Store",
                "My Custom Store",
            )

            self.assertTrue(created)
            self.assertEqual(store.name, "My Custom Store")
            self.assertEqual(store.status_column, "D")
            self.assertEqual(store.listing_sheet, "StoreAListings")
            config = load_app_config(config_dir)
            self.assertEqual(config.description_template("My Custom Store"), "")

            existing, created_again = add_custom_store_name(
                config_dir,
                "Base Store",
                "  My   Custom Store  ",
            )
            self.assertFalse(created_again)
            self.assertEqual(existing.name, "My Custom Store")
            self.assertEqual(
                [item.name for item in load_app_config(config_dir).stores.values()].count(
                    "My Custom Store"
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
