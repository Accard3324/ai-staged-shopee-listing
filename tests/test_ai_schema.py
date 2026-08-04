from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_schema import validate_ai_listing_result


class AISchemaTests(unittest.TestCase):
    def test_valid_ai_json_passes(self):
        result = validate_ai_listing_result(
            {
                "title": "BrandA Oral Care Toothpaste 28g Fresh Breath Daily Cleaning",
                "title_keywords": ["Oral Care", "Fresh Breath"],
                "description_placeholders": {
                    "PAIN_POINTS": "Bad breath after meals.",
                    "BENEFITS": "Helps with daily cleaning.",
                    "SPECIFICATIONS": "28g per box.",
                    "USAGE": "Use as directed on the package.",
                },
                "seo_keywords": [
                    {"keyword": f"Care Term {index}", "language": "English" if index % 2 == 0 else "Malay", "source_reason": "visible fact"}
                    for index in range(15)
                ],
                "category_suggestion": {
                    "path": "Health > Personal Care",
                    "confidence": 0.8,
                    "source": "competitor",
                },
                "attribute_suggestions": [{"name": "Shelf Life", "value": "36 months", "confidence": 0.7}],
                "image_selection": {
                    "main_image": "main.jpg",
                    "detail_images": ["detail.jpg"],
                    "sku_images": [{"variation": "28g /1box", "file": "sku.jpg"}],
                    "unsafe_images": [],
                },
                "warnings": [],
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])

    def test_title_over_120_characters_fails(self):
        result = validate_ai_listing_result(
            {
                "title": "A" * 121,
                "title_keywords": [],
                "description_placeholders": {
                    "PAIN_POINTS": "",
                    "BENEFITS": "",
                    "SPECIFICATIONS": "",
                    "USAGE": "",
                },
                "image_selection": {
                    "main_image": "",
                    "detail_images": [],
                    "sku_images": [],
                    "unsafe_images": [],
                },
                "warnings": [],
            }
        )

        self.assertFalse(result.ok)
        self.assertIn("title must be 120 characters or fewer", result.errors)


if __name__ == "__main__":
    unittest.main()
