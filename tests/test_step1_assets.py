from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.assets.image_filter import select_step1_images, validate_confirmed_image_selection


class Step1AssetTests(unittest.TestCase):
    def test_select_step1_images_uses_main_plus_details_and_skips_unsafe_names(self):
        manifest = {
            "main_images": [r"D:\safe\main1.jpg"],
            "detail_images": [
                r"D:\safe\detail1.jpg",
                r"D:\safe\OEM_factory.jpg",
                r"D:\safe\detail2.png",
            ],
        }

        plan = select_step1_images(manifest)

        self.assertEqual(plan["product_images"], [r"D:\safe\main1.jpg", r"D:\safe\detail1.jpg", r"D:\safe\detail2.png"])
        self.assertEqual(plan["promo_image"], r"D:\safe\main1.jpg")
        self.assertEqual(plan["skipped_unsafe"], [r"D:\safe\OEM_factory.jpg"])

    def test_select_step1_images_limits_product_images_to_nine(self):
        manifest = {
            "main_images": [r"D:\safe\main1.jpg"],
            "detail_images": [rf"D:\safe\detail{i}.jpg" for i in range(20)],
        }

        plan = select_step1_images(manifest)

        self.assertEqual(len(plan["product_images"]), 9)

    def test_confirmed_selection_requires_main_folder_but_manual_choice_overrides_ai_risk(self):
        manifest = {
            "main_images": ["main1.jpg", "main2.jpg"],
            "detail_images": ["detail1.jpg", "detail2.jpg", "detail3.jpg"],
        }
        result = validate_confirmed_image_selection(
            manifest,
            "main2.jpg",
            ["detail1.jpg", "detail3.jpg"],
            [{"file": "detail2.jpg", "reason": "OEM text"}],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["total_images"], 3)
        self.assertEqual(result["unsafe_selected"], [])

        invalid = validate_confirmed_image_selection(manifest, "detail1.jpg", ["detail2.jpg"], [])
        self.assertFalse(invalid["ok"])
        self.assertIn("Select exactly one image from the main-image folder", invalid["errors"])

        manual_override = validate_confirmed_image_selection(
            manifest,
            "main1.jpg",
            ["detail2.jpg"],
            [{"file": "detail2.jpg", "reason": "OEM text"}],
        )
        self.assertTrue(manual_override["ok"])
        self.assertEqual(manual_override["unsafe_selected"], ["detail2.jpg"])
        self.assertTrue(manual_override["manual_override"])

    def test_confirmed_selection_keeps_shopee_nine_image_limit(self):
        details = [f"detail{i}.jpg" for i in range(9)]
        result = validate_confirmed_image_selection(
            {"main_images": ["main.jpg"], "detail_images": details},
            "main.jpg",
            details,
            [],
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["exceeds_nine"])
        self.assertIn("Main and detail images may total at most 9; 10 are selected", result["errors"])

    def test_confirmed_selection_accepts_only_explicitly_promoted_detail_as_main(self):
        manifest = {
            "main_images": ["oem-main.jpg"],
            "detail_images": ["detail1.jpg", "detail2.jpg"],
        }
        result = validate_confirmed_image_selection(
            manifest,
            "detail1.jpg",
            ["detail2.jpg"],
            [{"file": "oem-main.jpg", "reason": "包含 OEM/ODM 信息"}],
            promoted_main_candidates=["detail1.jpg"],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["main_image"], "detail1.jpg")


if __name__ == "__main__":
    unittest.main()
