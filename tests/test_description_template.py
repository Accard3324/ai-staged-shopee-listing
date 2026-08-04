from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.listing_builder import (
    audit_final_description,
    build_description,
    build_description_with_seo,
)


SYNTHETIC_TEMPLATE = (
    "Welcome to the test store.\n"
    "{{PAIN_POINTS}}\n{{BENEFITS}}\n{{SPECIFICATIONS}}\n{{USAGE}}"
)


class DescriptionTemplateTests(unittest.TestCase):
    def test_only_known_placeholders_are_replaced(self):
        description = build_description(
            template=SYNTHETIC_TEMPLATE,
            placeholders={
                "PAIN_POINTS": "Bad breath after meals.",
                "BENEFITS": "Helps keep daily oral care simple.",
                "SPECIFICATIONS": "28g per box.",
                "USAGE": "Use as directed on the package.",
            },
        )

        self.assertIn("Welcome to the test store.", description)
        self.assertIn("Bad breath after meals.", description)
        self.assertNotIn("{{PAIN_POINTS}}", description)
        self.assertLessEqual(len(description), 3000)

    def test_seo_keywords_are_counted_and_written_on_the_last_line(self):
        keywords = [
            {"keyword": f"Product Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]
        result = build_description_with_seo(
            SYNTHETIC_TEMPLATE,
            {"PAIN_POINTS": "Daily care.", "BENEFITS": "Practical care.", "SPECIFICATIONS": "20g.", "USAGE": "Follow package instructions."},
            keywords,
        )

        self.assertEqual(result["seo_keyword_count"], 15)
        self.assertTrue(result["seo_hashtag_line_at_bottom"])
        self.assertEqual(result["final_description"].splitlines()[-1], result["seo_hashtag_line"])
        self.assertEqual(result["final_description_length"], len(result["final_description"]))
        self.assertLessEqual(result["final_description_length"], 3000)

    def test_seo_keyword_count_outside_15_to_20_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "15 to 20"):
            build_description_with_seo(
                "{{PAIN_POINTS}} {{BENEFITS}} {{SPECIFICATIONS}} {{USAGE}}",
                {"PAIN_POINTS": "a", "BENEFITS": "b", "SPECIFICATIONS": "c", "USAGE": "d"},
                [{"keyword": f"word{i}"} for i in range(14)],
            )

    def test_overlength_description_can_be_returned_for_manual_editing(self):
        keywords = [
            {"keyword": f"Product Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]

        result = build_description_with_seo(
            "{{PAIN_POINTS}}\n{{BENEFITS}}\n{{SPECIFICATIONS}}\n{{USAGE}}",
            {
                "PAIN_POINTS": "A" * 3100,
                "BENEFITS": "Daily care.",
                "SPECIFICATIONS": "20g.",
                "USAGE": "Follow package instructions.",
            },
            keywords,
            enforce_character_limit=False,
        )

        self.assertGreater(result["final_description_length"], 3000)
        self.assertFalse(result["within_character_limit"])
        self.assertTrue(result["final_description"].startswith("A" * 3100))

    def test_overlength_description_is_still_rejected_for_final_listing(self):
        keywords = [
            {"keyword": f"Product Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]

        with self.assertRaisesRegex(ValueError, "3000 characters or fewer"):
            build_description_with_seo(
                "{{PAIN_POINTS}}\n{{BENEFITS}}\n{{SPECIFICATIONS}}\n{{USAGE}}",
                {
                    "PAIN_POINTS": "A" * 3100,
                    "BENEFITS": "Daily care.",
                    "SPECIFICATIONS": "20g.",
                    "USAGE": "Follow package instructions.",
                },
                keywords,
            )

    def test_edited_final_description_is_reaudited_and_kept(self):
        keywords = [
            {"keyword": f"Skin Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]
        hashtag_line = " ".join(f"#SkinCare{index}" for index in range(15))
        edited = f"Manually edited complete store description.\n\n{hashtag_line}"

        result = audit_final_description(edited, keywords)

        self.assertEqual(result["final_description"], edited)
        self.assertEqual(result["final_description_length"], len(edited))
        self.assertTrue(result["seo_hashtag_line_at_bottom"])

    def test_edited_final_description_allows_user_changes_to_bottom_hashtag_line(self):
        keywords = [
            {"keyword": f"Skin Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]
        result = audit_final_description("Edited body\n\n#WrongTag", keywords)

        self.assertEqual(result["final_description"], "Edited body\n\n#WrongTag")
        self.assertFalse(result["seo_hashtag_line_at_bottom"])

    def test_overlength_manual_description_is_rejected_without_changing_it(self):
        keywords = [
            {"keyword": f"Skin Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]
        hashtag_line = " ".join(f"#SkinCare{index}" for index in range(15))
        edited = f"{'A' * 3100}\n\n{hashtag_line}"

        with self.assertRaisesRegex(ValueError, f"server received {len(edited)} characters"):
            audit_final_description(edited, keywords)

    def test_exactly_3000_manual_characters_are_kept_unchanged(self):
        keywords = [
            {"keyword": f"Skin Care {index}", "language": "English", "source_reason": "visible product information"}
            for index in range(15)
        ]
        edited = "A" * 3000

        result = audit_final_description(edited, keywords)

        self.assertEqual(result["final_description"], edited)
        self.assertEqual(result["final_description_length"], 3000)


if __name__ == "__main__":
    unittest.main()
