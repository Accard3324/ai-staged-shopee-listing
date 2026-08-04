from pathlib import Path
import json
import sys
import unittest
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.serverchan_notification import send_serverchan_message


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ServerChanNotificationTests(unittest.TestCase):
    def test_sends_utf8_form_without_exposing_sendkey_in_the_body(self):
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["body"] = parse_qs(request.data.decode("utf-8"))
            observed["timeout"] = timeout
            return _FakeResponse({"code": 0, "message": "success"})

        result = send_serverchan_message(
            "Shopee 一键上架失败",
            "步骤 3：图片分析失败",
            sendkey="SCTtest_secret",
            urlopen=fake_urlopen,
        )

        self.assertEqual(result["code"], 0)
        self.assertEqual(observed["body"]["title"], ["Shopee 一键上架失败"])
        self.assertEqual(observed["body"]["desp"], ["步骤 3：图片分析失败"])
        self.assertNotIn("SCTtest_secret", str(observed["body"]))
        self.assertTrue(observed["url"].endswith("/SCTtest_secret.send"))
        self.assertEqual(observed["timeout"], 15)

    def test_rejects_missing_or_non_turbo_sendkey(self):
        with self.assertRaisesRegex(RuntimeError, "Enter a ServerChan"):
            send_serverchan_message("title", "body", sendkey="")
        with self.assertRaisesRegex(RuntimeError, "SCT"):
            send_serverchan_message("title", "body", sendkey="invalid")

    def test_service_error_does_not_include_the_sendkey(self):
        def fake_urlopen(_request, timeout):
            return _FakeResponse({"code": 40001, "message": "invalid key"})

        with self.assertRaises(RuntimeError) as context:
            send_serverchan_message(
                "title",
                "body",
                sendkey="SCTdo_not_leak",
                urlopen=fake_urlopen,
            )

        self.assertNotIn("SCTdo_not_leak", str(context.exception))


if __name__ == "__main__":
    unittest.main()
