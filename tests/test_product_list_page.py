from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.product_list_page import (
    product_list_search_script,
    product_list_status_script,
    unlisted_tab_script,
)
from shopee_listing_app.shopee.product_new_page import wait_for_saved_delisted


class ProductListPageTests(unittest.TestCase):
    def test_status_is_scoped_to_requested_sku_and_extracts_product_id(self):
        script = product_list_status_script("DEMO-SKU-001")

        self.assertIn("DEMO-SKU-001", script)
        self.assertIn("商品编号", script)
        self.assertIn("hasUnlistedStatus", script)
        self.assertIn("productId", script)
        self.assertIn("pageIsUnlisted", script)
        self.assertIn("candidateProductId", script)

    def test_unlisted_tab_script_clicks_the_unpublished_product_tab(self):
        script = unlisted_tab_script()

        self.assertIn("尚未刊登", script)
        self.assertIn("tab.click()", script)
        self.assertIn("tabFound", script)

    def test_product_search_script_filters_by_requested_sku(self):
        script = product_list_search_script("DEMO-SKU-001")

        self.assertIn("DEMO-SKU-001", script)
        self.assertIn("搜索商品名称", script)
        self.assertIn("Product ID", script)
        self.assertIn("dispatchEvent", script)
        self.assertIn("应用", script)

    def test_saved_item_page_refreshes_every_ten_seconds_up_to_six_times(self):
        client = Mock()

        def evaluate(script):
            if "tabFound" in script:
                value = {"tabFound": True, "clicked": False}
            elif "inputFound" in script:
                value = {"inputFound": True, "applied": True}
            else:
                value = {
                    "found": False,
                    "hasUnlistedStatus": False,
                    "productId": "",
                }
            return {"result": {"value": value}}

        client.evaluate.side_effect = evaluate
        with patch(
            "shopee_listing_app.shopee.product_new_page.time.sleep"
        ), patch(
            "shopee_listing_app.shopee.product_new_page.time.monotonic",
            return_value=0,
        ), patch(
            "shopee_listing_app.shopee.product_new_page.ensure_unlisted_product_list_page"
        ), patch(
            "shopee_listing_app.shopee.product_new_page.wait_for_product_list_page_ready"
        ):
            result = wait_for_saved_delisted(client, "SKU-001")

        reload_calls = [
            call
            for call in client.command.call_args_list
            if call.args and call.args[0] == "Page.reload"
        ]
        self.assertEqual(len(reload_calls), 6)
        self.assertEqual(result["refreshAttempt"], 6)
        self.assertEqual(result["refreshMaxAttempts"], 6)
        self.assertEqual(result["refreshIntervalSeconds"], 10)

    def test_saved_item_refresh_stops_as_soon_as_product_id_appears(self):
        client = Mock()
        status_checks = 0

        def evaluate(script):
            nonlocal status_checks
            if "tabFound" in script:
                value = {"tabFound": True, "clicked": False}
            elif "inputFound" in script:
                value = {"inputFound": True, "applied": True}
            else:
                status_checks += 1
                found = status_checks == 21
                value = {
                    "found": found,
                    "hasUnlistedStatus": found,
                    "productId": "52613167535" if found else "",
                    "status": "未上架" if found else "",
                }
            return {"result": {"value": value}}

        client.evaluate.side_effect = evaluate
        with patch(
            "shopee_listing_app.shopee.product_new_page.time.sleep"
        ), patch(
            "shopee_listing_app.shopee.product_new_page.time.monotonic",
            return_value=0,
        ), patch(
            "shopee_listing_app.shopee.product_new_page.ensure_unlisted_product_list_page"
        ), patch(
            "shopee_listing_app.shopee.product_new_page.wait_for_product_list_page_ready"
        ):
            result = wait_for_saved_delisted(client, "SKU-001")

        reload_calls = [
            call
            for call in client.command.call_args_list
            if call.args and call.args[0] == "Page.reload"
        ]
        self.assertEqual(len(reload_calls), 2)
        self.assertEqual(result["refreshAttempt"], 2)
        self.assertEqual(result["productId"], "52613167535")


if __name__ == "__main__":
    unittest.main()
