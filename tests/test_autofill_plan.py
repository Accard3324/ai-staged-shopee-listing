from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.shopee.product_new_page import (
    NEW_PRODUCT_URL,
    build_autofill_payload,
    capture_screenshot_or_empty,
    confirm_save_delist_if_present,
    ensure_product_new_page,
    fill_failure_reason,
    fill_title_and_description_script,
    friendly_failure_reason,
    manual_save_delist_blocking_reason,
    page_diagnostics_script,
    product_images_for_step1,
    run_fetch_product_id_from_draft,
    run_step2_minimal_info,
    run_step2_variation_and_logistics,
    run_save_delist_only_from_draft,
    should_continue_to_save,
    validate_run_mode,
    wait_for_save_delist_submission,
)


class AutofillPlanTests(unittest.TestCase):
    def test_product_page_state_guard_opens_new_page_only_when_needed(self):
        class FakeClient:
            def __init__(self, state):
                self.state = state
                self.navigated_urls = []

            def evaluate(self, _script):
                return {"result": {"value": self.state}}

            def navigate(self, url):
                self.navigated_urls.append(url)

        with patch("shopee_listing_app.shopee.product_new_page.wait_for_product_page_ready") as wait:
            client = FakeClient({"isSellerCenter": False, "isProductNewPage": False})
            ensure_product_new_page(client)
            self.assertEqual(client.navigated_urls, [NEW_PRODUCT_URL])
            wait.assert_called_once_with(client)

        with patch("shopee_listing_app.shopee.product_new_page.wait_for_product_page_ready") as wait:
            client = FakeClient({"isSellerCenter": True, "isProductNewPage": True})
            ensure_product_new_page(client)
            self.assertEqual(client.navigated_urls, [])
            wait.assert_called_once_with(client)

    def test_build_autofill_payload_reads_title_description_and_variations(self):
        draft = {
            "store": {"name": "Shopee-MY-Store-C"},
            "candidate": {"sku_code": "SKU-001", "brand": "BrandA"},
            "listing": {
                "title": "BrandA Oral Care 28g",
                "description": "Full shop template description",
                "category_suggestion": {"path": "Health > Oral Care"},
                "attribute_suggestions": [{"name": "Shelf Life", "value": "36 months"}],
            },
            "assets": {"main_images": ["main.jpg"], "detail_images": ["d1.jpg"], "videos": []},
            "variations": [
                {"name": "28g /1box", "price": "9.90", "stock": "88", "item_code": "SKU-001"},
                {"name": "2x 28g /2box", "price": "18.80", "stock": "88", "item_code": "SKU-001"},
            ],
        }

        payload = build_autofill_payload(draft)

        self.assertEqual(payload["title"], "BrandA Oral Care 28g")
        self.assertEqual(payload["description"], "Full shop template description")
        self.assertEqual(payload["sku_code"], "SKU-001")
        self.assertEqual(len(payload["variations"]), 2)

    def test_build_autofill_payload_adds_package_defaults_from_spec(self):
        draft = {
            "store": {"name": "Shopee Malaysia Test Store"},
            "candidate": {"sku_code": "SKU-001", "brand": "BrandA", "sku_spec": "20g"},
            "listing": {"title": "BrandA Cream 20g", "description": "Full description"},
            "assets": {},
            "variations": [],
        }

        payload = build_autofill_payload(draft)

        self.assertEqual(payload["package"]["weight_kg"], "0.05")
        self.assertEqual(payload["package"]["length_cm"], "10")
        self.assertIn("estimated", " ".join(payload["package"]["warnings"]))

    def test_build_autofill_payload_uses_workbook_package_columns(self):
        draft = {
            "candidate": {
                "sku_code": "SKU-001",
                "package_weight_kg": "0.12",
                "package_length_cm": "14",
                "package_width_cm": "8",
                "package_height_cm": "5",
            },
            "listing": {},
            "assets": {},
            "variations": [],
        }

        payload = build_autofill_payload(draft)

        self.assertEqual(
            payload["package"],
            {
                "weight_kg": "0.12",
                "length_cm": "14",
                "width_cm": "8",
                "height_cm": "5",
                "warnings": [],
            },
        )

    def test_build_autofill_payload_rejects_incomplete_workbook_package_columns(self):
        draft = {
            "candidate": {
                "sku_code": "SKU-001",
                "package_weight_kg": "0.12",
                "package_length_cm": "14",
                "package_width_cm": "",
                "package_height_cm": "5",
            }
        }

        with self.assertRaisesRegex(RuntimeError, "X"):
            build_autofill_payload(draft)

    def test_step2_minimal_flow_calls_ordered_variation_state_machine(self):
        import inspect

        source = inspect.getsource(run_step2_minimal_info)

        self.assertIn("run_step2_variation_and_logistics", source)
        self.assertIn("extendedFillResult", source)
        self.assertIn("afterBrandRetry", source)
        self.assertIn("video_result = upload_product_video", source)

    def test_step2_logistics_accepts_enabled_doorstep_despite_other_option_warning(self):
        import inspect

        source = inspect.getsource(run_step2_variation_and_logistics)

        self.assertIn('bool(state.get("doorstepEnabled"))', source)
        self.assertNotIn('and not state.get("errors")', source)
        self.assertIn("logisticsWarnings", source)

    def test_validate_run_mode_accepts_only_safe_modes(self):
        self.assertEqual(validate_run_mode("dry_run"), "dry_run")
        self.assertEqual(validate_run_mode("fill_only"), "fill_only")
        self.assertEqual(validate_run_mode("save_delist"), "save_delist")
        with self.assertRaises(ValueError):
            validate_run_mode("publish_now")

    def test_save_delist_continues_after_step2_but_fill_only_stops(self):
        self.assertTrue(should_continue_to_save("save_delist"))
        self.assertFalse(should_continue_to_save("fill_only"))

    def test_manual_save_action_ignores_checklist_warnings_when_button_exists(self):
        check = {
            "canSaveDelist": False,
            "hasDescription": False,
            "seoKeywordCountOk": False,
            "saveDelistButtonVisible": True,
        }

        self.assertEqual(manual_save_delist_blocking_reason(check), "")

    def test_manual_save_action_still_requires_the_real_shopee_button(self):
        check = {"canSaveDelist": False, "saveDelistButtonVisible": False}

        self.assertIn("was not found", manual_save_delist_blocking_reason(check))

    def test_step13_direct_save_does_not_rerun_fill_or_checklist(self):
        import inspect

        source = inspect.getsource(run_save_delist_only_from_draft)

        self.assertIn("click_page_save_delist", source)
        self.assertIn("confirm_save_delist", source)
        self.assertIn("wait_for_save_delist_submission", source)
        self.assertNotIn("PRE_SAVE_CHECK_SCRIPT", source)
        self.assertNotIn("run_step2_minimal_info", source)
        self.assertNotIn("run_step1_basic_info", source)
        self.assertNotIn("ensure_product_new_page", source)

    def test_step13_direct_save_requires_platform_acceptance_without_waiting_for_id(self):
        client = Mock()
        client.evaluate.return_value = {"result": {"value": {"ok": True}}}
        module = "shopee_listing_app.shopee.product_new_page"
        with patch(f"{module}.load_listing_draft", return_value={"candidate": {"sku_code": "SKU-001"}}), patch(
            f"{module}.pick_verified_cdp_port", return_value=9222
        ), patch(
            f"{module}.open_existing_product_page",
            return_value={"webSocketDebuggerUrl": "ws://127.0.0.1/page"},
        ), patch(
            f"{module}.CdpClient", return_value=client
        ), patch(
            f"{module}.click_page_save_delist"
        ) as click_save, patch(
            f"{module}.wait_for_save_delist_submission",
            return_value={"ok": True, "accepted_by": "product_list_redirect"},
        ) as verify_submission, patch(
            f"{module}.capture_artifacts", return_value=(Path("saved.png"), Path("saved.html"))
        ), patch(
            f"{module}.write_autofill_success_report", return_value=Path("saved.md")
        ):
            result = run_save_delist_only_from_draft(Path("draft.json"))

        self.assertTrue(result.ok)
        self.assertEqual(result.product_id, "")
        self.assertEqual(result.stage, "save_delist_confirmed")
        self.assertEqual(result.listing_status, "Awaiting product ID")
        click_save.assert_called_once_with(client)
        verify_submission.assert_called_once_with(client, cancellation_check=None)

    def test_step13_platform_validation_error_blocks_product_id_lookup(self):
        client = Mock()
        client.evaluate.return_value = {
            "result": {
                "value": {
                    "href": "https://seller.shopee.com.my/portal/product/new/",
                    "isNewProductPage": True,
                    "isProductListPage": False,
                    "blockingErrors": [
                        "由于7个错误而无法保存，请更改后再试",
                        "此栏位不可空白",
                    ],
                    "successMessages": [],
                }
            }
        }

        with self.assertRaisesRegex(RuntimeError, "Shopee rejected.*will not start product-ID retrieval"):
            wait_for_save_delist_submission(client, attempts=1, interval_seconds=0)

    def test_step13_waits_for_real_product_list_redirect(self):
        client = Mock()
        client.evaluate.side_effect = [
            {
                "result": {
                    "value": {
                        "href": "https://seller.shopee.com.my/portal/product/new/",
                        "isNewProductPage": True,
                        "isProductListPage": False,
                        "blockingErrors": [],
                        "successMessages": [],
                        "saveButtonLoading": True,
                    }
                }
            },
            {
                "result": {
                    "value": {
                        "href": "https://seller.shopee.com.my/portal/product/list/all",
                        "isNewProductPage": False,
                        "isProductListPage": True,
                        "blockingErrors": [],
                        "successMessages": [],
                    }
                }
            },
        ]

        with patch("shopee_listing_app.shopee.product_new_page.time.sleep") as sleep:
            result = wait_for_save_delist_submission(
                client,
                attempts=3,
                interval_seconds=0.5,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["accepted_by"], "product_list_redirect")
        sleep.assert_called_once_with(0.5)

    def test_step13_missing_confirmation_modal_is_optional(self):
        client = Mock()
        client.evaluate.return_value = {
            "result": {
                "value": {
                    "ok": False,
                    "reason": "modal button not found",
                }
            }
        }

        with patch("shopee_listing_app.shopee.product_new_page.time.sleep"):
            result = confirm_save_delist_if_present(
                client,
                attempts=2,
                interval_seconds=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "confirmation_not_present")
        self.assertEqual(client.evaluate.call_count, 2)

    def test_step13_fetch_product_id_uses_exact_sku_on_unlisted_page(self):
        client = Mock()
        saved = {
            "found": True,
            "hasUnlistedStatus": True,
            "productId": "52613167535",
            "status": "未上架",
        }
        module = "shopee_listing_app.shopee.product_new_page"
        with patch(
            f"{module}.load_listing_draft",
            return_value={"candidate": {"sku_code": "SKU-001"}},
        ), patch(
            f"{module}.pick_verified_cdp_port", return_value=9222
        ), patch(
            f"{module}.open_existing_product_list_page",
            return_value={"webSocketDebuggerUrl": "ws://127.0.0.1/page"},
        ), patch(
            f"{module}.CdpClient", return_value=client
        ), patch(
            f"{module}.wait_for_saved_delisted", return_value=saved
        ) as fetch_saved, patch(
            f"{module}.capture_artifacts", return_value=(Path("id.png"), Path("id.html"))
        ), patch(
            f"{module}.write_autofill_success_report", return_value=Path("id.md")
        ):
            result = run_fetch_product_id_from_draft(Path("draft.json"))

        self.assertTrue(result.ok)
        self.assertEqual(result.product_id, "52613167535")
        self.assertEqual(result.sku_code, "SKU-001")
        fetch_saved.assert_called_once()
        self.assertEqual(fetch_saved.call_args.args[1], "SKU-001")
        self.assertEqual(fetch_saved.call_args.kwargs["refresh_attempts"], 6)
        self.assertEqual(fetch_saved.call_args.kwargs["refresh_interval_seconds"], 10)

    def test_step1_uploads_every_confirmed_product_image(self):
        plan = {"product_images": [f"image-{index}.jpg" for index in range(7)]}

        self.assertEqual(product_images_for_step1(plan), plan["product_images"])

    def test_friendly_failure_reason_explains_missing_description_editor(self):
        reason = friendly_failure_reason("description failed: Quill editor not found", "diag.json")

        self.assertIn("description editor is not present", reason)
        self.assertIn("diag.json", reason)

    def test_fill_failure_reason_distinguishes_title_from_description(self):
        title_reason = fill_failure_reason({"titleFilled": False, "reason": "title input not found"})
        description_reason = fill_failure_reason(
            {"titleFilled": True, "description": {"ok": False, "reason": "Quill editor not found"}}
        )

        self.assertIn("product-title input was not found", title_reason)
        self.assertIn("Description filling failed", description_reason)
        self.assertNotIn("product-title input was not found", description_reason)

    def test_capture_screenshot_or_empty_uses_viewport_screenshot(self):
        class FakeClient:
            def command(self, method, params):
                self.calls.append((method, params))
                if method == "Page.bringToFront":
                    return {}
                return {"data": "abc"}

            def capture_screenshot(self):
                return "fallback"

        client = FakeClient()
        client.calls = []
        data = capture_screenshot_or_empty(client)

        self.assertEqual(data, "abc")
        self.assertEqual(client.calls[0][0], "Page.bringToFront")
        self.assertEqual(client.calls[1][0], "Page.captureScreenshot")
        self.assertFalse(client.calls[1][1]["captureBeyondViewport"])

    def test_capture_screenshot_or_empty_returns_empty_after_failures(self):
        class BrokenClient:
            def command(self, _method, _params):
                raise TimeoutError("viewport screenshot timed out")

            def capture_screenshot(self):
                raise TimeoutError("full screenshot timed out")

        self.assertEqual(capture_screenshot_or_empty(BrokenClient()), "")

    def test_title_locator_script_has_multilingual_fallbacks_and_avoids_textareas(self):
        script = fill_title_and_description_script(
            {
                "title": "BrandA Oral Care 28g",
                "description": "Full shop template description",
            }
        )

        self.assertIn("商品名称", script)
        self.assertIn("Product Name", script)
        self.assertIn("Nama Produk", script)
        self.assertIn("Please enter product name", script)
        self.assertIn("tagName === \"INPUT\"", script)
        self.assertIn("[\"\", \"text\"]", script)
        self.assertIn("isBadInputCandidate", script)

    def test_page_diagnostics_script_records_inputs_textareas_and_page_state(self):
        script = page_diagnostics_script()

        self.assertIn("visibleInputs", script)
        self.assertIn("visibleTextareas", script)
        self.assertIn("bodyTextSample", script)
        self.assertIn("isSellerCenter", script)
        self.assertIn("isProductNewPage", script)
        self.assertIn("isCaptchaPage", script)


if __name__ == "__main__":
    unittest.main()
