from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.pre_save_checker import PRE_SAVE_CHECK_SCRIPT


class PreSaveVariationImageTests(unittest.TestCase):
    def test_reports_each_required_variation_image_separately(self):
        for check_name in [
            "variation_image_1box",
            "variation_image_2box",
            "variation_image_3box",
        ]:
            self.assertIn(check_name, PRE_SAVE_CHECK_SCRIPT)

    def test_rejects_placeholder_image_urls(self):
        self.assertIn('startsWith("data:")', PRE_SAVE_CHECK_SCRIPT)
        self.assertIn("getBoundingClientRect", PRE_SAVE_CHECK_SCRIPT)

    def test_main_image_count_excludes_variation_table_images(self):
        self.assertIn(".variation-model-table-container", PRE_SAVE_CHECK_SCRIPT)

    def test_product_image_count_is_scoped_away_from_promotion_images(self):
        self.assertIn("const productImageScope", PRE_SAVE_CHECK_SCRIPT)
        self.assertIn("productImageScope?.querySelectorAll", PRE_SAVE_CHECK_SCRIPT)
        self.assertIn('data-product-edit-field-unique-id="promotionImages"', PRE_SAVE_CHECK_SCRIPT)

    def test_unsafe_text_check_is_scoped_to_image_managers(self):
        self.assertIn("imageManagerText", PRE_SAVE_CHECK_SCRIPT)
        self.assertNotIn("unsafeImageSignals = /OEM|ODM|factory|wholesale|supplier|dropship", PRE_SAVE_CHECK_SCRIPT.split("imageManagerText")[0])

    def test_description_presence_is_the_only_description_save_requirement(self):
        for check_name in [
            "descriptionExists",
            "descriptionLengthOk",
            "seoKeywordCount",
            "seoKeywordCountOk",
            "seoHashtagLineAtBottom",
            "seoKeywordsProductRelevant",
        ]:
            self.assertIn(check_name, PRE_SAVE_CHECK_SCRIPT)
        self.assertIn("const hasDescription = descriptionExists;", PRE_SAVE_CHECK_SCRIPT)

    def test_video_and_health_certification_are_hard_save_checks(self):
        for check_name in ["videoUploaded", "videoProcessing", "videoOk", "healthCertificationNo"]:
            self.assertIn(check_name, PRE_SAVE_CHECK_SCRIPT)


if __name__ == "__main__":
    unittest.main()
