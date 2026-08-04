from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.variation_editor import variation_image_targets_script, variation_image_visible_status_script


class VariationVisibleValidationTests(unittest.TestCase):
    def test_visible_validation_checks_each_label_and_real_image_geometry(self):
        script = variation_image_visible_status_script(
            [{"name": "20g /1box"}, {"name": "2x 20g /2box"}, {"name": "3x 20g /3box"}]
        )

        self.assertIn("scrollIntoView", script)
        self.assertIn("getBoundingClientRect", script)
        self.assertIn("imageVisible", script)
        self.assertIn("20g /1box", script)

    def test_upload_status_rejects_empty_and_placeholder_images(self):
        script = variation_image_targets_script([{"name": "20g /1box"}])

        self.assertIn('startsWith("data:")', script)


if __name__ == "__main__":
    unittest.main()
