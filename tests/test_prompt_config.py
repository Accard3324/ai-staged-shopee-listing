from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.prompt_config import DEFAULT_PROMPTS, load_prompt_config, save_prompt_config


BLANK_STAGE_PROMPTS = {
    "image_analysis",
    "description_generation",
    "keyword_generation",
    "competitor_title_analysis",
}


class PromptConfigTests(unittest.TestCase):
    def test_steps_3_5_6_7_are_blank_by_default(self):
        self.assertEqual(
            set(DEFAULT_PROMPTS),
            BLANK_STAGE_PROMPTS | {"category_selection"},
        )
        for key in BLANK_STAGE_PROMPTS:
            self.assertEqual(DEFAULT_PROMPTS[key], "", key)
        self.assertIn("category suggestions", DEFAULT_PROMPTS["category_selection"])

    def test_save_and_reload_preserves_blank_prompts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prompts.yaml"
            saved = save_prompt_config(
                path,
                {
                    **DEFAULT_PROMPTS,
                    "category_selection": "",
                },
            )

            self.assertTrue(all(saved[key] == "" for key in DEFAULT_PROMPTS))
            self.assertEqual(load_prompt_config(path), saved)

    def test_user_can_add_prompt_text_later(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prompts.yaml"
            saved = save_prompt_config(
                path,
                {**DEFAULT_PROMPTS, "image_analysis": "custom image prompt"},
            )

            self.assertEqual(saved["image_analysis"], "custom image prompt")
            self.assertEqual(load_prompt_config(path)["image_analysis"], "custom image prompt")


if __name__ == "__main__":
    unittest.main()
