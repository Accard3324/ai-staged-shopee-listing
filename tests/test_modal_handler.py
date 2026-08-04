from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.components.modal_handler import shipping_confirmation_modal_script


class ModalHandlerTests(unittest.TestCase):
    def test_shipping_confirmation_targets_only_the_visible_shipping_modal(self):
        script = shipping_confirmation_modal_script()

        self.assertIn("Once this channel is enabled", script)
        self.assertIn("Doorstep Delivery", script)
        self.assertIn("确认", script)
        self.assertIn("found: false", script)


if __name__ == "__main__":
    unittest.main()
