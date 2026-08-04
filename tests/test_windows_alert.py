from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.windows_alert import show_topmost_error_alert, show_topmost_success_alert


class WindowsAlertTests(unittest.TestCase):
    def test_windows_alert_uses_a_daemon_thread(self):
        with patch("shopee_listing_app.windows_alert.os.name", "nt"), patch(
            "shopee_listing_app.windows_alert.threading.Thread"
        ) as thread:
            result = show_topmost_error_alert("失败", "步骤 3 失败")

        self.assertTrue(result)
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()

    def test_success_alert_uses_a_daemon_thread(self):
        with patch("shopee_listing_app.windows_alert.os.name", "nt"), patch(
            "shopee_listing_app.windows_alert.threading.Thread"
        ) as thread:
            result = show_topmost_success_alert("完成", "步骤 3 完成")

        self.assertTrue(result)
        self.assertEqual(thread.call_args.kwargs["name"], "shopee-success-alert")
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
