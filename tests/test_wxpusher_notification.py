from pathlib import Path
import json
import sys
import unittest
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.wxpusher_notification import send_wxpusher_spt_message


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class WxPusherNotificationTests(unittest.TestCase):
    def test_sends_failure_text_through_spt_endpoint(self):
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            return _FakeResponse({"code": 1000, "msg": "处理成功", "success": True})

        result = send_wxpusher_spt_message(
            "Shopee 一键上架失败",
            "步骤 3：图片分析失败",
            spt="SPT_test_secret",
            urlopen=fake_urlopen,
        )

        decoded_url = unquote(observed["url"])
        self.assertEqual(result["code"], 1000)
        self.assertIn("/SPT_test_secret/", decoded_url)
        self.assertIn("Shopee 一键上架失败", decoded_url)
        self.assertIn("步骤 3：图片分析失败", decoded_url)
        self.assertEqual(observed["timeout"], 15)

    def test_rejects_missing_or_invalid_spt(self):
        with self.assertRaisesRegex(RuntimeError, "Enter a WxPusher"):
            send_wxpusher_spt_message("title", "body", spt="")
        with self.assertRaisesRegex(RuntimeError, "SPT_"):
            send_wxpusher_spt_message("title", "body", spt="invalid")

    def test_service_error_does_not_include_the_spt(self):
        def fake_urlopen(_request, timeout):
            return _FakeResponse({"code": 1001, "msg": "invalid token", "success": False})

        with self.assertRaises(RuntimeError) as context:
            send_wxpusher_spt_message(
                "title",
                "body",
                spt="SPT_do_not_leak",
                urlopen=fake_urlopen,
            )

        self.assertNotIn("SPT_do_not_leak", str(context.exception))


if __name__ == "__main__":
    unittest.main()
