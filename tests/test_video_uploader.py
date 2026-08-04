from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.video_uploader import (
    video_modal_confirm_script,
    video_upload_status_script,
)


class VideoUploaderTests(unittest.TestCase):
    def test_status_finds_real_mp4_input_and_requires_completed_preview(self):
        script = video_upload_status_script()

        self.assertIn("video|mp4", script)
        self.assertIn("inputIndex", script)
        self.assertIn("previewCount", script)
        self.assertIn("processing", script)
        self.assertIn("uploaded", script)

    def test_modal_confirmation_only_uses_video_dialog_actions(self):
        script = video_modal_confirm_script()

        self.assertIn("local-edit-video-container", script)
        self.assertIn("完成", script)
        self.assertIn("confirmed", script)


if __name__ == "__main__":
    unittest.main()
