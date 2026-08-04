from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.gui_state import build_initial_gui_state


class GuiStateTests(unittest.TestCase):
    def test_initial_state_has_required_stores_and_step_model_status(self):
        state = build_initial_gui_state(ROOT / "config")

        self.assertEqual(len(state.stores), 3)
        self.assertEqual(state.workbook_path, "C:\\path\\to\\listing_workbook.xlsx")
        self.assertEqual(state.ai_provider, "openai")
        self.assertIn("AI execution mode", state.ai_status_text)
        self.assertIn("Step 3 model", state.ai_status_text)
        self.assertIn("Step 5 model", state.ai_status_text)
        self.assertIn("Step 6 model", state.ai_status_text)
        self.assertIn("Step 7 model", state.ai_status_text)
        self.assertIn("gpt-5.6", state.ai_status_text)


if __name__ == "__main__":
    unittest.main()
