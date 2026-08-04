from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.ai_provider import resolve_prompt


class PromptOverrideTests(unittest.TestCase):
    def test_uses_current_run_override(self):
        provider = type("Provider", (), {"prompt_overrides": {"image_analysis": "edited prompt"}})()
        self.assertEqual(resolve_prompt(provider, "image_analysis", "default"), "edited prompt")

    def test_falls_back_when_override_missing(self):
        self.assertEqual(resolve_prompt(object(), "image_analysis", "default"), "default")

    def test_explicit_blank_override_does_not_restore_hard_coded_text(self):
        provider = type("Provider", (), {"prompt_overrides": {"image_analysis": ""}})()
        self.assertEqual(resolve_prompt(provider, "image_analysis", "default"), "")


if __name__ == "__main__":
    unittest.main()
