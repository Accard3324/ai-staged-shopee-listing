from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_schema import (
    validate_asset_analysis_result,
    validate_search_keywords_result,
    validate_seo_keywords_result,
    validate_title_analysis_result,
)
from shopee_listing_app.competitor_input import parse_manual_competitors, save_manual_competitors
import tempfile


class AiWorkflowTests(unittest.TestCase):
    def test_asset_analysis_requires_safe_main_and_max_nine_images(self):
        result = validate_asset_analysis_result(
            {
                "main_image": "main.jpg",
                "detail_images": [f"d{i}.jpg" for i in range(8)],
                "unsafe_images": [{"file": "bad.jpg", "reason": "OEM/ODM"}],
                "product_info_from_images": {
                    "product_type": "wart remover cream",
                    "visible_specs": ["20g"],
                    "visible_ingredients_or_materials": [],
                    "usage": "apply to clean skin",
                    "warnings": [],
                },
            }
        )

        self.assertTrue(result.ok)

    def test_asset_analysis_rejects_too_many_images(self):
        result = validate_asset_analysis_result(
            {
                "main_image": "main.jpg",
                "detail_images": [f"d{i}.jpg" for i in range(9)],
                "unsafe_images": [],
                "product_info_from_images": {"product_type": "cream"},
            }
        )

        self.assertFalse(result.ok)
        self.assertIn("9", " ".join(result.errors))

    def test_search_keywords_requires_five_keyword_objects(self):
        result = validate_search_keywords_result(
            {
                "search_keywords": [
                    {"english": "wart remover cream", "chinese_meaning": "祛疣膏", "why": "product type"},
                    {"english": "skin tag remover", "chinese_meaning": "皮赘护理", "why": "similar category"},
                    {"english": "foot corn remover", "chinese_meaning": "鸡眼护理", "why": "similar care"},
                    {"english": "skin care cream", "chinese_meaning": "护肤膏", "why": "broad category"},
                    {"english": "first aid ointment", "chinese_meaning": "急救软膏", "why": "category"},
                ]
            }
        )

        self.assertTrue(result.ok)

    def test_seo_keywords_require_15_to_20_bilingual_traceable_items(self):
        result = validate_seo_keywords_result(
            [
                {"keyword": f"Care Term {index}", "language": "English" if index % 2 == 0 else "Malay", "source_reason": "visible product fact"}
                for index in range(15)
            ]
        )

        self.assertTrue(result.ok)
        self.assertFalse(validate_seo_keywords_result([{"keyword": "too few", "language": "English", "source_reason": "fact"}]).ok)

    def test_manual_competitors_parse_link_title_and_sales(self):
        parsed = parse_manual_competitors(
            """
            https://shopee.com.my/item-a  Sold 1k  Wart Remover Cream Fast Skin Care
            Skin Tag Remover Cream | 售 5千
            """
        )

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["url"], "https://shopee.com.my/item-a")
        self.assertIn("Wart Remover", parsed[0]["source_title"])
        self.assertIn("1k", parsed[0]["observed_sales"])
        self.assertEqual(parsed[1]["url"], "")
        self.assertIn("5千", parsed[1]["observed_sales"])
        self.assertEqual(parsed[0]["raw_input"].strip(), "https://shopee.com.my/item-a  Sold 1k  Wart Remover Cream Fast Skin Care")
        self.assertIn("warnings", parsed[0])

    def test_title_analysis_schema_requires_final_title_and_competitors(self):
        result = validate_title_analysis_result(
            {
                "final_title": "EELHOE Wart Remover Cream 20g Skin Care Ointment Shopee Malaysia",
                "competitor_analysis": [
                    {"source_title": "Wart Remover Cream", "sales": "Sold 1k", "reused_keywords": ["Wart Remover Cream"]}
                ],
                "removed_keywords": ["OtherBrand"],
                "warnings": [],
            }
        )

        self.assertTrue(result.ok)

    def test_manual_competitors_are_saved_as_complete_json_and_markdown(self):
        competitors = parse_manual_competitors("Complete Product Title Sold 2k+")
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = save_manual_competitors(Path(temp_dir), "sku-1", competitors)
            json_text = paths["json_path"].read_text(encoding="utf-8")
            markdown = paths["markdown_path"].read_text(encoding="utf-8")

        self.assertIn("Complete Product Title", json_text)
        self.assertIn("Complete Product Title", markdown)
        self.assertNotIn("...", markdown)


if __name__ == "__main__":
    unittest.main()
