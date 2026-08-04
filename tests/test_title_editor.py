from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.title_editor import title_fill_script


class TitleEditorTests(unittest.TestCase):
    def test_title_fill_script_uses_real_shopee_edit_row_context(self):
        script = title_fill_script("EELHOE title")

        self.assertIn(".edit-row", script)
        self.assertIn("商品名称", script)
        self.assertIn("品牌名称 + 商品类型", script)
        self.assertIn("hasTitleSignal", script)
        self.assertIn("nativeInputValueSetter", script)
        self.assertIn("badTitleText.test(text) && !hasTitleSignal(text)", script)


if __name__ == "__main__":
    unittest.main()
