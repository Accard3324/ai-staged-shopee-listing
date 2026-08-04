from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.product_new_page import build_step1_upload_plan, first_page_failure_reason


class Step1FlowTests(unittest.TestCase):
    def test_build_step1_upload_plan_uses_draft_assets_and_starts_with_main_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            main = base / "main.jpg"
            detail = base / "detail.jpg"
            main.write_bytes(b"fake")
            detail.write_bytes(b"fake")
            draft = {
                "assets": {
                    "main_images": [str(main)],
                    "detail_images": [str(detail)],
                }
            }

            plan = build_step1_upload_plan(draft)

        self.assertEqual(plan["product_images"][0], str(main))
        self.assertEqual(plan["promo_image"], str(main))

    def test_first_page_failure_reason_names_first_page_problem(self):
        reason = first_page_failure_reason({"missingRequired": ["商品图片", "Next Step disabled"]})

        self.assertIn("Step 1 failed", reason)
        self.assertIn("商品图片", reason)
        self.assertIn("Next Step", reason)

    def test_build_step1_upload_plan_uses_confirmed_image_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            candidates = [base / name for name in ["main1.jpg", "main2.jpg", "detail1.jpg", "detail2.jpg"]]
            for path in candidates:
                path.write_bytes(b"fake")
            draft = {
                "assets": {"main_images": [str(candidates[0]), str(candidates[1])], "detail_images": [str(candidates[2]), str(candidates[3])]},
                "image_selection": {"main_image": str(candidates[1]), "detail_images": [str(candidates[3]), str(candidates[2])], "unsafe_images": []},
            }

            plan = build_step1_upload_plan(draft)

        self.assertEqual(plan["product_images"], [str(candidates[1]), str(candidates[3]), str(candidates[2])])
        self.assertEqual(plan["promo_image"], str(candidates[1]))


if __name__ == "__main__":
    unittest.main()
