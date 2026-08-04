from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.cli import build_parser


class CliUploadTests(unittest.TestCase):
    def test_upload_draft_accepts_cdp_port(self):
        args = build_parser().parse_args(
            [
                "upload-draft",
                "--draft",
                "outputs/listings/example.json",
                "--mode",
                "fill_only",
                "--cdp-port",
                "60094",
            ]
        )

        self.assertEqual(args.cdp_port, 60094)


if __name__ == "__main__":
    unittest.main()
