from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.step2_category import (
    category_select_script,
    choose_category_candidate,
    wait_for_category_unlock_script,
)


class Step2CategoryTests(unittest.TestCase):
    def test_choose_category_prefers_ointment_for_wart_cream(self):
        candidates = [
            {"text": "保健 > 医疗保健 > 急救用品 > 软膏与乳膏"},
            {"text": "美妆保养 > 护肤品 > 保湿乳液、乳霜"},
            {"text": "美妆保养 > 头发护理 > 护发用品"},
        ]
        payload = {
            "title": "EELHOE 肌肤平滑护理膏 20g/盒 Shopee Malaysia",
            "description": "Warts Remover Cream for skin care. Greetings, Valued Shopper!",
            "category": "",
        }

        choice = choose_category_candidate(candidates, payload)

        self.assertTrue(choice["ok"])
        self.assertEqual(choice["text"], "保健 > 医疗保健 > 急救用品 > 软膏与乳膏")
        self.assertGreaterEqual(choice["score"], 6)
        self.assertIn("ointment", " ".join(choice["reasons"]))

    def test_choose_category_declines_weak_candidates(self):
        choice = choose_category_candidate(
            [{"text": "美妆保养 > 头发护理 > 护发用品"}],
            {"title": "Generic item", "description": "", "category": ""},
        )

        self.assertFalse(choice["ok"])
        self.assertIn("not confident", choice["reason"])

    def test_duplicate_visible_rows_do_not_create_a_false_confidence_tie(self):
        path = "保健 > 医疗保健 > 急救用品 > 软膏与乳膏"
        choice = choose_category_candidate(
            [{"text": path}, {"text": path}, {"text": "美妆保养 > 护肤品 > 保湿乳液、乳霜"}],
            {"title": "EELHOE Wart Removal Ointment", "description": "Skin care ointment", "category": path},
        )

        self.assertTrue(choice["ok"])
        self.assertEqual(choice["text"], path)

    def test_category_select_script_targets_exact_row_text(self):
        script = category_select_script("保健 > 医疗保健 > 急救用品 > 软膏与乳膏")

        self.assertIn(".category-select-row-text", script)
        self.assertIn("targetCategory", script)
        self.assertIn("item.text === targetCategory", script)
        self.assertNotIn("rows[0].click", script)

    def test_wait_for_category_unlock_script_checks_quill(self):
        script = wait_for_category_unlock_script()

        self.assertIn(".ql-editor", script)
        self.assertIn("在您选择商品分类后更新", script)


if __name__ == "__main__":
    unittest.main()
