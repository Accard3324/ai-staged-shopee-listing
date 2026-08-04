from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict

from ..assets.image_filter import existing_files, select_step1_images
from ..browser.cdp_client import CdpClient, create_page, list_pages
from ..browser.context_selector import best_page_for_product_new
from ..browser.cdp_discovery import find_ziniao_cdp_candidates
from ..config_manager import PROJECT_ROOT
from ..listing_builder import normalize_price
from ..reporting.final_report import (
    save_page_diagnostics,
    write_autofill_failure_log,
    write_autofill_failure_report,
    write_autofill_success_report,
)
from ..reporting.html_snapshot import save_html_snapshot
from ..reporting.screenshot_manager import save_base64_screenshot
from .components.modal_handler import exact_modal_button_script, shipping_confirmation_modal_script
from .components.gtin_editor import gtin_handling_script
from .components.image_uploader import (
    set_file_input_files,
    step1_status_script,
    upload_step1_product_images,
    wait_for_promo_image,
)
from .components.next_step_handler import click_next_step
from .components.pre_save_checker import PRE_SAVE_CHECK_SCRIPT
from .components.product_code_editor import product_code_fill_script
from .components.quill_editor import quill_fill_script
from .components.step2_category import (
    category_select_script,
    choose_category_candidate,
    wait_for_category_unlock_script,
)
from .components.step2_minimal import (
    brand_mouse_probe_script,
    description_fill_script,
    health_certification_probe_script,
    step2_minimal_fill_script,
)
from .components.step2_extended import step2_extended_fill_script
from .components.step2_probe import step2_probe_script
from .components.step2_state_machine import STEP2_STAGES, wait_for_step
from .components.title_editor import title_fill_script
from .components.video_uploader import upload_product_video
from .product_list_page import product_list_search_script, product_list_status_script, unlisted_tab_script
from .components.variation_editor import (
    logistics_enable_doorstep_script,
    logistics_status_script,
    package_and_parent_fill_script,
    package_and_parent_status_script,
    variation_enable_script,
    variation_image_visible_status_script,
    variation_image_targets_script,
    variation_options_fill_script,
    variation_rows_fill_script,
    variation_status_script,
)


RUN_MODES = {"dry_run", "fill_only", "save_delist"}
NEW_PRODUCT_URL = "https://seller.shopee.com.my/portal/product/new"
UNLISTED_PRODUCT_URL = "https://seller.shopee.com.my/portal/product/list/unpublished/unlisted"


@dataclass(frozen=True)
class AutofillResult:
    ok: bool
    mode: str
    stage: str
    message: str
    sku_code: str
    screenshot_path: str = ""
    html_path: str = ""
    diagnostics_path: str = ""
    report_path: str = ""
    log_path: str = ""
    cdp_port: int = 0
    product_id: str = ""
    listing_status: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "stage": self.stage,
            "message": self.message,
            "sku_code": self.sku_code,
            "screenshot_path": self.screenshot_path,
            "html_path": self.html_path,
            "diagnostics_path": self.diagnostics_path,
            "report_path": self.report_path,
            "log_path": self.log_path,
            "cdp_port": self.cdp_port,
            "product_id": self.product_id,
            "listing_status": self.listing_status,
        }


def validate_run_mode(mode: str) -> str:
    if mode not in RUN_MODES:
        raise ValueError(f"Invalid run mode: {mode}. Use dry_run, fill_only, or save_delist.")
    return mode


def should_continue_to_save(mode: str) -> bool:
    return validate_run_mode(mode) == "save_delist"


def load_listing_draft(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"listing_draft.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_autofill_payload(draft: Dict[str, Any]) -> Dict[str, Any]:
    listing = draft.get("listing", {})
    candidate = draft.get("candidate", {})
    assets = draft.get("assets", {})
    package = build_package_payload(draft)
    return {
        "store_name": draft.get("store", {}).get("name", ""),
        "title": listing.get("title", ""),
        "description": listing.get("description", ""),
        "category": listing.get("category_suggestion", {}).get("path", ""),
        "brand": candidate.get("brand", ""),
        "sku_code": candidate.get("sku_code", ""),
        "main_images": assets.get("main_images", []),
        "detail_images": assets.get("detail_images", []),
        "sku_images": assets.get("sku_images", []),
        "videos": assets.get("videos", []),
        "variations": [
            {**item, "price": normalize_price(item.get("price", ""))}
            for item in draft.get("variations", [])
            if isinstance(item, dict)
        ],
        "attributes": listing.get("attribute_suggestions", []),
        "package": package,
    }


def build_package_payload(draft: Dict[str, Any]) -> Dict[str, Any]:
    listing = draft.get("listing", {}) if isinstance(draft.get("listing", {}), dict) else {}
    candidate = draft.get("candidate", {}) if isinstance(draft.get("candidate", {}), dict) else {}
    workbook_fields = {
        "weight_kg": ("package_weight_kg", "V"),
        "length_cm": ("package_length_cm", "W"),
        "width_cm": ("package_width_cm", "X"),
        "height_cm": ("package_height_cm", "Y"),
    }
    if any(candidate_key in candidate for candidate_key, _ in workbook_fields.values()):
        package: Dict[str, Any] = {"warnings": []}
        invalid_columns = []
        for package_key, (candidate_key, column) in workbook_fields.items():
            value = str(candidate.get(candidate_key, "") or "").strip()
            try:
                is_positive = Decimal(value) > 0
            except InvalidOperation:
                is_positive = False
            if not is_positive:
                invalid_columns.append(column)
            package[package_key] = value
        if invalid_columns:
            joined = "/".join(invalid_columns)
            raise RuntimeError(
                f"The weight or dimensions in workbook column(s) {joined} are blank, non-numeric, or not greater than zero. "
                "Complete V=weight (kg), W=length (cm), X=width (cm), and Y=height (cm)."
            )
        return package

    existing = draft.get("package") or listing.get("package") or {}
    if isinstance(existing, dict) and existing:
        return {
            "weight_kg": str(existing.get("weight_kg") or existing.get("weight") or ""),
            "length_cm": str(existing.get("length_cm") or existing.get("length") or ""),
            "width_cm": str(existing.get("width_cm") or existing.get("width") or ""),
            "height_cm": str(existing.get("height_cm") or existing.get("height") or ""),
            "warnings": list(existing.get("warnings", [])) if isinstance(existing.get("warnings", []), list) else [],
        }

    spec_text = " ".join(
        str(candidate.get(key, "") or "")
        for key in ["sku_spec", "product_name", "brand"]
    )
    grams = extract_grams(spec_text)
    warnings = ["estimated package data used because workbook/assets did not provide exact package dimensions"]
    if grams:
        weight = max(round((grams / 1000) + 0.03, 2), 0.05)
    else:
        weight = 0.05
        warnings.append("weight could not be read from spec; defaulted to 0.05 kg")
    return {
        "weight_kg": f"{weight:.2f}",
        "length_cm": "10",
        "width_cm": "5",
        "height_cm": "3",
        "warnings": warnings,
    }


def extract_grams(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(g|gram|grams)\b", str(text), flags=re.I)
    if match:
        return float(match.group(1))
    return None


def run_autofill_from_draft(draft_path: Path, mode: str, cdp_port: int | None = None) -> AutofillResult:
    mode = validate_run_mode(mode)
    draft = load_listing_draft(draft_path)
    payload = build_autofill_payload(draft)
    sku_code = str(payload.get("sku_code") or "unknown")
    stage = "discover_cdp"
    client: CdpClient | None = None
    port = 0

    try:
        port = cdp_port or pick_verified_cdp_port()
        stage = "open_product_page"
        page = open_product_page(port)
        client = CdpClient(str(page.get("webSocketDebuggerUrl", "")))
        client.connect()
        client.command("Runtime.enable")
        enable_page_domain_if_available(client)
        ensure_product_new_page(client)

        stage = "locate_fields"
        diagnostics = client.evaluate(page_diagnostics_script()).get("result", {}).get("value", {})
        if mode == "dry_run":
            diagnostics_path = save_page_diagnostics(
                diagnostics,
                PROJECT_ROOT / "outputs" / "reports",
                sku_code,
                stage,
            )
            report = write_autofill_success_report(
                PROJECT_ROOT / "outputs" / "reports",
                sku_code,
                mode,
                "Connected successfully and inspected fields on the Add Product page.",
            )
            return AutofillResult(
                True,
                mode,
                stage,
                "Dry run completed: connected and checked field locations.",
                sku_code,
                diagnostics_path=str(diagnostics_path),
                report_path=str(report),
                cdp_port=port,
            )

        completed_full_step2 = False
        step1_status = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
        if step1_status.get("isStep1") and not client.evaluate("!!document.querySelector('.ql-editor,.ql-container')").get("result", {}).get("value", False):
            stage = "step1_basic_info"
            step1_result = run_step1_basic_info(client, draft, payload)
            stage = "step2_minimal_after_step1"
            step2_result = run_step2_minimal_info(client, payload)
            completed_full_step2 = True
            if not should_continue_to_save(mode):
                screenshot_path, html_path = capture_artifacts(client, sku_code, "step2_minimal_after_fill")
                diagnostics_path = save_page_diagnostics(
                    {"step1": step1_result, "step2": step2_result},
                    PROJECT_ROOT / "outputs" / "reports",
                    sku_code,
                    "step2_minimal_after_fill",
                )
                report = write_autofill_success_report(
                    PROJECT_ROOT / "outputs" / "reports",
                    sku_code,
                    mode,
                    "Next Step was clicked in Step 1; Step 2 was inspected and filled completely; final save was not clicked.",
                )
                return AutofillResult(
                    True,
                    mode,
                    "step2_minimal_after_fill",
                    "Fill-only mode completed: advanced from Step 1 to Step 2 and filled the page without saving.",
                    sku_code,
                    screenshot_path=str(screenshot_path),
                    html_path=str(html_path),
                    diagnostics_path=str(diagnostics_path),
                    report_path=str(report),
                    cdp_port=port,
                )

        step2_probe = client.evaluate(step2_probe_script()).get("result", {}).get("value", {}) if not completed_full_step2 else {}
        if not completed_full_step2 and step2_probe.get("step2Status", {}).get("isStep2"):
            stage = "step2_minimal"
            step2_result = run_step2_minimal_info(client, payload, initial_probe=step2_probe)
            completed_full_step2 = True
            if not should_continue_to_save(mode):
                screenshot_path, html_path = capture_artifacts(client, sku_code, "step2_minimal_after_fill")
                diagnostics_path = save_page_diagnostics(
                    step2_result,
                    PROJECT_ROOT / "outputs" / "reports",
                    sku_code,
                    "step2_minimal_after_fill",
                )
                report = write_autofill_success_report(
                    PROJECT_ROOT / "outputs" / "reports",
                    sku_code,
                    mode,
                    "Step 2 was inspected and filled completely; final save was not clicked.",
                )
                return AutofillResult(
                    True,
                    mode,
                    "step2_minimal_after_fill",
                    "Fill-only mode completed: filled the current Step 2 page without saving.",
                    sku_code,
                    screenshot_path=str(screenshot_path),
                    html_path=str(html_path),
                    diagnostics_path=str(diagnostics_path),
                    report_path=str(report),
                    cdp_port=port,
                )

        if not completed_full_step2:
            stage = "fill_title_description"
            fill_result = client.evaluate(fill_title_and_description_script(payload))
            value = fill_result.get("result", {}).get("value", {})
            if not value.get("titleFilled") or not value.get("description", {}).get("ok"):
                raise RuntimeError(fill_failure_reason(value))

        if mode == "fill_only":
            stage = "capture_after_fill"
            screenshot_path, html_path = capture_artifacts(client, sku_code, stage)
            report = write_autofill_success_report(
                PROJECT_ROOT / "outputs" / "reports",
                sku_code,
                mode,
                "The title and description were filled; save was not clicked.",
            )
            return AutofillResult(
                True,
                mode,
                stage,
                "Fill-only mode completed: the title and description were filled without saving.",
                sku_code,
                screenshot_path=str(screenshot_path),
                html_path=str(html_path),
                report_path=str(report),
                cdp_port=port,
            )

        stage = "pre_save_check"
        check = client.evaluate(PRE_SAVE_CHECK_SCRIPT).get("result", {}).get("value", {})
        blocking_reason = manual_save_delist_blocking_reason(check)
        if blocking_reason:
            raise RuntimeError(f"{blocking_reason}：{check}")
        manual_override_note = (
            ""
            if check.get("canSaveDelist")
            else "The pre-save check reported warnings; clicking Save and Delist is treated as operator confirmation to continue."
        )
        stage = "click_save_delist"
        click_page_save_delist(client)
        stage = "confirm_save_delist"
        confirm_value = confirm_save_delist_if_present(client)
        stage = "verify_saved_delisted"
        saved = wait_for_saved_delisted(client, sku_code)
        if not saved.get("found") or not saved.get("hasUnlistedStatus") or not saved.get("productId"):
            raise RuntimeError(f"Save and Delist was clicked, but the product list did not confirm the unlisted status or product ID: {saved}")
        screenshot_path, html_path = capture_artifacts(client, sku_code, stage)
        report = write_autofill_success_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            mode,
            (
                f"{manual_override_note}"
                f"Saved and delisted; product status: {saved.get('status')}; product ID: {saved.get('productId')}."
            ),
        )
        result_note = f"{manual_override_note} " if manual_override_note else ""
        return AutofillResult(
            True,
            mode,
            stage,
            f"{result_note}Save-and-Delist completed; product status: {saved.get('status')}; product ID: {saved.get('productId')}.",
            sku_code,
            screenshot_path=str(screenshot_path),
            html_path=str(html_path),
            report_path=str(report),
            cdp_port=port,
            product_id=str(saved.get("productId", "")),
            listing_status=str(saved.get("status", "")),
        )
    except Exception as exc:  # noqa: BLE001
        screenshot_path: Path | str = ""
        html_path: Path | str = ""
        diagnostics_path: Path | str = ""
        if client is not None:
            screenshot_path, html_path, diagnostics_path = capture_failure_artifacts(client, sku_code, stage)
        reason = friendly_failure_reason(str(exc), diagnostics_path)
        report = write_autofill_failure_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
        )
        log_path = write_autofill_failure_log(
            PROJECT_ROOT / "logs",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
            report_path=report,
        )
        return AutofillResult(
            False,
            mode,
            stage,
            reason,
            sku_code,
            screenshot_path=str(screenshot_path) if screenshot_path else "",
            html_path=str(html_path) if html_path else "",
            diagnostics_path=str(diagnostics_path) if diagnostics_path else "",
            report_path=str(report),
            log_path=str(log_path),
            cdp_port=port,
        )
    finally:
        if client is not None:
            client.close()


def run_save_delist_only_from_draft(
    draft_path: Path,
    cdp_port: int | None = None,
    *,
    cancellation_check: Callable[[], bool] | None = None,
) -> AutofillResult:
    """Click save/delist on the current page without rerunning any fill or checklist step."""
    draft = load_listing_draft(draft_path)
    candidate = draft.get("candidate", {}) if isinstance(draft.get("candidate", {}), dict) else {}
    sku_code = str(candidate.get("sku_code") or "unknown")
    stage = "discover_cdp"
    client: CdpClient | None = None
    port = 0

    try:
        port = cdp_port or pick_verified_cdp_port()
        stage = "connect_current_product_page"
        page = open_existing_product_page(port)
        client = CdpClient(str(page.get("webSocketDebuggerUrl", "")))
        client.connect()
        client.command("Runtime.enable")
        enable_page_domain_if_available(client)
        try:
            client.command("Page.bringToFront", {})
        except Exception:
            pass

        stage = "click_save_delist"
        click_page_save_delist(client)
        stage = "confirm_save_delist"
        confirm_value = confirm_save_delist_if_present(client)

        stage = "verify_save_delist_submission"
        submission = wait_for_save_delist_submission(
            client,
            cancellation_check=cancellation_check,
        )
        stage = "save_delist_confirmed"
        screenshot_path, html_path = capture_artifacts(client, sku_code, stage)
        report = write_autofill_success_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            "save_delist",
            (
                "Save and Delist was clicked; "
                f"confirmation-dialog action: {confirm_value.get('action', 'unknown')}; "
                f"platform acceptance signal: {submission.get('accepted_by', 'unknown')}; "
                "Step 13 will query the unlisted-product page by SKU to obtain the product ID."
            ),
        )
        return AutofillResult(
            True,
            "save_delist",
            stage,
            "Shopee accepted Save and Delist; continue to product-ID retrieval.",
            sku_code,
            screenshot_path=str(screenshot_path),
            html_path=str(html_path),
            report_path=str(report),
            cdp_port=port,
            listing_status="Awaiting product ID",
        )
    except Exception as exc:  # noqa: BLE001
        screenshot_path: Path | str = ""
        html_path: Path | str = ""
        diagnostics_path: Path | str = ""
        if client is not None:
            screenshot_path, html_path, diagnostics_path = capture_failure_artifacts(client, sku_code, stage)
        reason = friendly_failure_reason(str(exc), diagnostics_path)
        report = write_autofill_failure_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
        )
        log_path = write_autofill_failure_log(
            PROJECT_ROOT / "logs",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
            report_path=report,
        )
        return AutofillResult(
            False,
            "save_delist",
            stage,
            reason,
            sku_code,
            screenshot_path=str(screenshot_path) if screenshot_path else "",
            html_path=str(html_path) if html_path else "",
            diagnostics_path=str(diagnostics_path) if diagnostics_path else "",
            report_path=str(report),
            log_path=str(log_path),
            cdp_port=port,
        )
    finally:
        if client is not None:
            client.close()


def run_fetch_product_id_from_draft(
    draft_path: Path,
    cdp_port: int | None = None,
    *,
    cancellation_check: Callable[[], bool] | None = None,
) -> AutofillResult:
    """Find the saved unpublished item by exact SKU and return its product ID."""
    draft = load_listing_draft(draft_path)
    candidate = draft.get("candidate", {}) if isinstance(draft.get("candidate", {}), dict) else {}
    sku_code = str(candidate.get("sku_code") or "unknown")
    stage = "discover_cdp"
    client: CdpClient | None = None
    port = 0

    try:
        port = cdp_port or pick_verified_cdp_port()
        stage = "open_unlisted_product_list"
        page = open_existing_product_list_page(port)
        client = CdpClient(str(page.get("webSocketDebuggerUrl", "")))
        client.connect()
        client.command("Runtime.enable")
        enable_page_domain_if_available(client)
        try:
            client.command("Page.bringToFront", {})
        except Exception:
            pass

        stage = "fetch_product_id"
        saved = wait_for_saved_delisted(
            client,
            sku_code,
            refresh_attempts=6,
            refresh_interval_seconds=10,
            cancellation_check=cancellation_check,
        )
        if not saved.get("found") or not saved.get("hasUnlistedStatus") or not saved.get("productId"):
            raise RuntimeError(
                "The product ID for the requested SKU was not found on Shopee's Unpublished > Unlisted page. "
                f"Searched for SKU {sku_code} and refreshed every 10 seconds for 6 attempts: {saved}"
            )

        screenshot_path, html_path = capture_artifacts(client, sku_code, stage)
        report = write_autofill_success_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            "fetch_product_id",
            (
                f"Obtained product ID {saved.get('productId')} from the unlisted-product list "
                f"for SKU {sku_code}; status: {saved.get('status') or 'Unlisted'}."
            ),
        )
        return AutofillResult(
            True,
            "fetch_product_id",
            stage,
            (
                f"Product ID obtained: {saved.get('productId')}; "
                f"SKU: {sku_code}; status: {saved.get('status') or 'Unlisted'}."
            ),
            sku_code,
            screenshot_path=str(screenshot_path),
            html_path=str(html_path),
            report_path=str(report),
            cdp_port=port,
            product_id=str(saved.get("productId", "")),
            listing_status=str(saved.get("status", "") or "Unlisted"),
        )
    except Exception as exc:  # noqa: BLE001
        screenshot_path: Path | str = ""
        html_path: Path | str = ""
        diagnostics_path: Path | str = ""
        if client is not None:
            screenshot_path, html_path, diagnostics_path = capture_failure_artifacts(
                client, sku_code, stage
            )
        reason = friendly_failure_reason(str(exc), diagnostics_path)
        report = write_autofill_failure_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
        )
        log_path = write_autofill_failure_log(
            PROJECT_ROOT / "logs",
            sku_code=sku_code,
            stage=stage,
            reason=reason,
            screenshot_path=screenshot_path,
            html_path=html_path,
            diagnostics_path=diagnostics_path,
            report_path=report,
        )
        return AutofillResult(
            False,
            "fetch_product_id",
            stage,
            reason,
            sku_code,
            screenshot_path=str(screenshot_path) if screenshot_path else "",
            html_path=str(html_path) if html_path else "",
            diagnostics_path=str(diagnostics_path) if diagnostics_path else "",
            report_path=str(report),
            log_path=str(log_path),
            cdp_port=port,
        )
    finally:
        if client is not None:
            client.close()


def run_linear_stage_from_draft(
    draft_path: Path,
    target_stage: str,
    cdp_port: int | None = None,
) -> Dict[str, Any]:
    if target_stage not in {"open", "step1", "step2", "checklist"}:
        raise ValueError(f"Unknown linear Shopee stage: {target_stage}")
    draft = load_listing_draft(draft_path)
    payload = build_autofill_payload(draft)
    sku_code = str(payload.get("sku_code") or "unknown")
    client: CdpClient | None = None
    port = 0
    stage_result: Dict[str, Any] = {}
    screenshot_path: Path | str = ""
    html_path: Path | str = ""
    diagnostics_path: Path | str = ""
    try:
        port = cdp_port or pick_verified_cdp_port()
        page = open_product_page(port)
        client = CdpClient(str(page.get("webSocketDebuggerUrl", "")))
        client.connect()
        client.command("Runtime.enable")
        enable_page_domain_if_available(client)
        ensure_product_new_page(client)

        if target_stage == "open":
            stage_result = client.evaluate(page_diagnostics_script()).get("result", {}).get("value", {})
            message = "Opened and attached to the Shopee Add Product page"
        elif target_stage == "step1":
            status = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
            if not status.get("isStep1"):
                raise RuntimeError(f"The current page is not Shopee Step 1: {status}")
            stage_result = run_step1_basic_info(client, draft, payload)
            message = "Shopee Step 1 completed and advanced to Step 2"
        elif target_stage == "step2":
            probe = client.evaluate(step2_probe_script()).get("result", {}).get("value", {})
            if not probe.get("step2Status", {}).get("isStep2"):
                raise RuntimeError(f"The current page is not Shopee Step 2: {probe.get('step2Status', {})}")
            stage_result = run_step2_minimal_info(client, payload, initial_probe=probe)
            message = "Shopee Step 2 was filled and has not been saved"
        else:
            stage_result = client.evaluate(PRE_SAVE_CHECK_SCRIPT).get("result", {}).get("value", {})
            message = "Pre-save check passed" if stage_result.get("canSaveDelist") else "Pre-save check failed; save was not attempted"

        screenshot_path, html_path = capture_artifacts(client, sku_code, f"linear_{target_stage}")
        diagnostics_path = save_page_diagnostics(
            stage_result,
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            f"linear_{target_stage}",
        )
        report_path = write_autofill_success_report(
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            f"linear_{target_stage}",
            message,
        )
        return {
            "ok": True,
            "stage": target_stage,
            "message": message,
            "stage_result": stage_result,
            "checklist": stage_result if target_stage == "checklist" else {},
            "screenshot_path": str(screenshot_path),
            "html_path": str(html_path),
            "diagnostics_path": str(diagnostics_path),
            "report_path": str(report_path),
            "cdp_port": port,
        }
    except Exception as exc:  # noqa: BLE001
        if client is not None:
            screenshot_path, html_path, diagnostics_path = capture_failure_artifacts(
                client, sku_code, f"linear_{target_stage}"
            )
        return {
            "ok": False,
            "stage": target_stage,
            "message": friendly_failure_reason(str(exc), diagnostics_path),
            "stage_result": stage_result,
            "checklist": {},
            "screenshot_path": str(screenshot_path) if screenshot_path else "",
            "html_path": str(html_path) if html_path else "",
            "diagnostics_path": str(diagnostics_path) if diagnostics_path else "",
            "report_path": "",
            "cdp_port": port,
        }
    finally:
        if client is not None:
            client.close()


def friendly_failure_reason(reason: str, diagnostics_path: Path | str) -> str:
    if "title input not found" in reason or "商品标题输入框" in reason:
        suffix = f" Diagnostics: {diagnostics_path}" if diagnostics_path else ""
        return f"The product-title input was not found. The application saved a screenshot, HTML snapshot, and diagnostics for investigation.{suffix}"
    if (
        "在您选择商品分类后更新" in reason
        or "categoryLocked" in reason
        or ("category" in reason.lower() and "Quill editor not found" in reason)
    ):
        suffix = f" Diagnostics: {diagnostics_path}" if diagnostics_path else ""
        return (
            "The page is on Step 2, but category selection did not succeed, so Shopee has not unlocked the description editor. "
            f"The application saved a screenshot, HTML snapshot, and diagnostics.{suffix}"
        )
    if "Quill editor not found" in reason:
        suffix = f" Diagnostics: {diagnostics_path}" if diagnostics_path else ""
        return (
            "The description editor is not present on the current Shopee page. The live page may still be on Step 1 for product name, images, and Next Step. "
            f"The application saved a screenshot, HTML snapshot, and diagnostics.{suffix}"
        )
    return reason


def fill_failure_reason(value: Dict[str, Any]) -> str:
    if not value.get("titleFilled"):
        return f"The product-title input was not found. Details: {value}"
    description = value.get("description", {})
    if not description.get("ok"):
        return f"Description filling failed: {value}"
    return f"Title or description filling failed: {value}"


def build_step1_upload_plan(draft: Dict[str, Any]) -> Dict[str, Any]:
    assets = draft.get("assets", {}) if isinstance(draft.get("assets"), dict) else {}
    selection = draft.get("image_selection", {}) if isinstance(draft.get("image_selection"), dict) else {}
    main_image = str(selection.get("main_image", "")).strip()
    detail_images = selection.get("detail_images", [])
    if main_image and isinstance(detail_images, list):
        selected_assets = {"main_images": [main_image], "detail_images": detail_images}
    else:
        selected_assets = assets
    plan = select_step1_images(selected_assets)
    plan["product_images"] = existing_files(plan.get("product_images", []))
    if plan.get("promo_image") and not Path(str(plan["promo_image"])).is_file():
        plan["promo_image"] = plan["product_images"][0] if plan["product_images"] else ""
    if not plan["product_images"]:
        raise RuntimeError("Step 1 failed: no buyer-visible main image was available for upload.")
    return plan


def product_images_for_step1(upload_plan: Dict[str, Any]) -> list[str]:
    return [str(path) for path in upload_plan.get("product_images", []) if str(path)]


def first_page_failure_reason(status: Dict[str, Any]) -> str:
    missing = status.get("missingRequired") or []
    if missing:
        return "Step 1 failed: " + " / ".join(str(item) for item in missing)
    return f"Step 1 failed its status check: {status}"


def build_step2_probe_markdown(probe: Dict[str, Any]) -> str:
    page = probe.get("page", {}) if isinstance(probe.get("page", {}), dict) else {}
    status = probe.get("step2Status", {}) if isinstance(probe.get("step2Status", {}), dict) else {}
    description = status.get("description", {}) if isinstance(status.get("description", {}), dict) else {}
    buttons = status.get("buttons", {}) if isinstance(status.get("buttons", {}), dict) else {}
    locator_plan = probe.get("locatorPlan", {}) if isinstance(probe.get("locatorPlan", {}), dict) else {}
    category_candidates = probe.get("categoryCandidates", [])
    if not isinstance(category_candidates, list):
        category_candidates = []
    lines = [
        "# Step 2 Page Probe",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- URL: {page.get('url', '')}",
        f"- Title: {page.get('title', '')}",
        f"- Is Seller Center: {page.get('isSellerCenter', '')}",
        f"- Is Product New Page: {page.get('isProductNewPage', '')}",
        f"- Has Login Issue: {page.get('isLoginPage', '')}",
        f"- Has Captcha: {page.get('isCaptchaPage', '')}",
        "",
        "## Field Signals",
        f"- category: {status.get('category', '')}",
        f"- brand: {status.get('brand', '')}",
        f"- attributes: {status.get('attributes', '')}",
        f"- description_has_quill: {description.get('hasQuill', '')}",
        f"- category_locked: {status.get('categoryLocked', '')}",
        f"- video: {status.get('video', '')}",
        f"- variation: {status.get('variation', '')}",
        f"- price: {status.get('price', '')}",
        f"- stock: {status.get('stock', '')}",
        f"- skuItemCode: {status.get('skuItemCode', '')}",
        f"- weightDimension: {status.get('weightDimension', '')}",
        f"- logistics: {status.get('logistics', '')}",
        f"- buttons: {json.dumps(buttons, ensure_ascii=False)}",
        "",
        "## Category Candidates",
    ]
    if category_candidates:
        lines.extend(
            f"- {item.get('index', '')}: {item.get('text', '')}"
            for item in category_candidates
            if isinstance(item, dict)
        )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Locator Plan",
    ])
    lines.extend(f"- {key}: {value}" for key, value in locator_plan.items())
    lines.extend(["", "## Body Text Sample", str(page.get("bodyTextSample", ""))[:5000]])
    return "\n".join(lines)


def save_step2_probe_artifacts(
    project_root: Path,
    probe: Dict[str, Any],
    html: str,
    screenshot_base64: str,
    stamp: str | None = None,
) -> Dict[str, Path]:
    provided_stamp = stamp is not None
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = project_root / "outputs" / "reports"
    html_dir = project_root / "outputs" / "html_snapshots"
    screenshot_dir = project_root / "outputs" / "screenshots"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"step2_page_probe_{stamp}.md"
    json_path = report_dir / f"step2_page_probe_{stamp}.json"
    base_stamp = stamp
    counter = 2
    while not provided_stamp and (report_path.exists() or json_path.exists()):
        stamp = f"{base_stamp}_{counter}"
        report_path = report_dir / f"step2_page_probe_{stamp}.md"
        json_path = report_dir / f"step2_page_probe_{stamp}.json"
        counter += 1
    html_path = save_html_snapshot(html, html_dir, "step2_page_probe", stamp)
    screenshot_path = save_base64_screenshot(screenshot_base64, screenshot_dir, "step2_page_probe", stamp)
    artifacts = {
        "report_path": report_path,
        "json_path": json_path,
        "html_path": html_path,
        "screenshot_path": screenshot_path,
    }
    probe_with_artifacts = dict(probe)
    probe_with_artifacts["artifacts"] = {key: str(value) for key, value in artifacts.items()}
    report_path.write_text(build_step2_probe_markdown(probe_with_artifacts), encoding="utf-8")
    json_path.write_text(json.dumps(probe_with_artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts


def capture_step2_probe(client: CdpClient, initial_probe: Dict[str, Any] | None = None) -> Dict[str, Any]:
    probe = initial_probe or client.evaluate(step2_probe_script()).get("result", {}).get("value", {})
    html = client.html()
    screenshot = capture_screenshot_or_empty(client)
    artifacts = save_step2_probe_artifacts(PROJECT_ROOT, probe, html=html, screenshot_base64=screenshot)
    result = dict(probe)
    result["artifacts"] = {key: str(value) for key, value in artifacts.items()}
    return result


def wait_for_step2_category_unlock(client: CdpClient, timeout_seconds: int = 20) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = client.evaluate(wait_for_category_unlock_script()).get("result", {}).get("value", {})
        if last.get("hasQuill"):
            return last
        time.sleep(1)
    return last


def wait_for_saved_delisted(
    client: CdpClient,
    sku_code: str,
    timeout_seconds: int = 45,
    *,
    refresh_attempts: int = 6,
    refresh_interval_seconds: float = 10,
    cancellation_check: Callable[[], bool] | None = None,
) -> Dict[str, Any]:
    """Wait for Shopee to publish the saved item into the unpublished list.

    Shopee can return an empty product list immediately after saving. Probe once
    without a reload, then refresh the visible list page every ten seconds up to
    six times. The legacy timeout argument remains for call compatibility.
    """
    del timeout_seconds
    attempts = max(1, int(refresh_attempts))
    interval = max(0.0, float(refresh_interval_seconds))
    last: Dict[str, Any] = {}
    refresh_history: list[Dict[str, Any]] = []

    def ensure_not_cancelled() -> None:
        if cancellation_check and cancellation_check():
            raise RuntimeError("Product-ID retrieval was superseded by a newer retry")

    def interruptible_sleep(seconds: float) -> None:
        duration = max(0.0, float(seconds))
        if duration <= 0:
            ensure_not_cancelled()
            return
        slices = max(1, int(duration / 0.25))
        delay = duration / slices
        for _ in range(slices):
            ensure_not_cancelled()
            time.sleep(delay)
        ensure_not_cancelled()

    def probe(refresh_attempt: int) -> Dict[str, Any]:
        ensure_not_cancelled()
        wait_for_product_list_page_ready(client)
        tab_action = client.evaluate(unlisted_tab_script()).get("result", {}).get("value", {})
        if tab_action.get("tabFound") and tab_action.get("clicked"):
            interruptible_sleep(1)
            wait_for_product_list_page_ready(client)
        search_action = client.evaluate(product_list_search_script(sku_code)).get("result", {}).get("value", {})
        if search_action.get("inputFound"):
            interruptible_sleep(1)
        status: Dict[str, Any] = {}
        for _ in range(10):
            ensure_not_cancelled()
            status = client.evaluate(product_list_status_script(sku_code)).get("result", {}).get("value", {})
            if status.get("found") and status.get("hasUnlistedStatus") and status.get("productId"):
                break
            interruptible_sleep(0.5)
        status["unlistedTabAction"] = tab_action
        status["searchAction"] = search_action
        status["refreshAttempt"] = refresh_attempt
        status["refreshMaxAttempts"] = attempts
        status["refreshIntervalSeconds"] = interval
        status["refreshHistory"] = list(refresh_history)
        return status

    ensure_unlisted_product_list_page(client)
    last = probe(0)
    if last.get("found") and last.get("hasUnlistedStatus") and last.get("productId"):
        return last

    next_refresh_at = time.monotonic() + interval
    for attempt in range(1, attempts + 1):
        ensure_not_cancelled()
        remaining = next_refresh_at - time.monotonic()
        if remaining > 0:
            interruptible_sleep(remaining)
        try:
            client.command("Page.bringToFront", {})
        except Exception:
            pass
        try:
            client.command("Page.reload", {"ignoreCache": True})
            reload_action: Dict[str, Any] = {"ok": True, "method": "Page.reload"}
        except Exception as exc:  # noqa: BLE001
            fallback = client.evaluate("(() => { location.reload(); return {ok:true}; })()")
            reload_action = {
                "ok": bool(fallback.get("result", {}).get("value", {}).get("ok")),
                "method": "location.reload",
                "error": str(exc)[:200],
            }
        refresh_history.append({"attempt": attempt, **reload_action})
        interruptible_sleep(1)
        last = probe(attempt)
        last["refreshHistory"] = list(refresh_history)
        if last.get("found") and last.get("hasUnlistedStatus") and last.get("productId"):
            return last
        next_refresh_at += interval
    return last


def click_rect_center(client: CdpClient, rect: Dict[str, Any]) -> None:
    x = float(rect.get("x", 0))
    y = float(rect.get("y", 0))
    client.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    client.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    client.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def run_step2_brand_mouse_fallback(client: CdpClient, brand: str) -> Dict[str, Any]:
    first = client.evaluate(brand_mouse_probe_script(brand)).get("result", {}).get("value", {})
    if first.get("selected"):
        return {"ok": True, "action": "already_selected_mouse_probe", "value": brand, "probe": first}
    recommended = first.get("recommendedOption") if isinstance(first.get("recommendedOption"), dict) else None
    if recommended and isinstance(recommended.get("rect"), dict):
        click_rect_center(client, recommended["rect"])
        time.sleep(2)
        recommended_verified = client.evaluate(brand_mouse_probe_script(brand)).get("result", {}).get("value", {})
        if recommended_verified.get("selected") or brand in str(recommended_verified.get("scopeText", "")):
            return {
                "ok": True,
                "action": "selected_recommended_brand_by_mouse",
                "value": brand,
                "firstProbe": first,
                "verifiedProbe": recommended_verified,
            }
    first_exact = first.get("exactOption") if isinstance(first.get("exactOption"), dict) else None
    first_fallback = first.get("noBrandOption") if isinstance(first.get("noBrandOption"), dict) else None
    if first_exact or first_fallback:
        opened = first
    elif first.get("selectorRect"):
        click_rect_center(client, first["selectorRect"])
        time.sleep(2)
        opened = client.evaluate(brand_mouse_probe_script(brand)).get("result", {}).get("value", {})
    else:
        opened = first
    exact = opened.get("exactOption") if isinstance(opened.get("exactOption"), dict) else None
    fallback = opened.get("noBrandOption") if isinstance(opened.get("noBrandOption"), dict) else None
    option = exact or fallback
    if not option or not isinstance(option.get("rect"), dict):
        return {"ok": False, "reason": "brand mouse option not found", "firstProbe": first, "openedProbe": opened}
    click_rect_center(client, option["rect"])
    time.sleep(2)
    verified = client.evaluate(brand_mouse_probe_script(brand)).get("result", {}).get("value", {})
    selected_text = str(verified.get("scopeText", ""))
    if exact and brand in selected_text:
        return {
            "ok": True,
            "action": "selected_exact_dropdown_option_by_mouse",
            "value": brand,
            "firstProbe": first,
            "openedProbe": opened,
            "verifiedProbe": verified,
        }
    if fallback and ("NoBrand" in selected_text or "No Brand" in selected_text):
        return {
            "ok": True,
            "action": "selected_no_brand_fallback_by_mouse",
            "requestedBrand": brand,
            "value": "NoBrand",
            "exactBrandAvailable": False,
            "firstProbe": first,
            "openedProbe": opened,
            "verifiedProbe": verified,
        }
    return {
        "ok": False,
        "reason": "brand mouse click did not change selected value",
        "clickedOption": option,
        "firstProbe": first,
        "openedProbe": opened,
        "verifiedProbe": verified,
    }


def ensure_health_certification_no(client: CdpClient) -> Dict[str, Any]:
    first = client.evaluate(health_certification_probe_script()).get("result", {}).get("value", {})
    if not first.get("ok"):
        # Skip an absent optional certification field without blocking later steps.
        return {"ok": True, "action": "skipped_field_not_found", "reason": "The Ministry of Health Certification field was not found and was skipped", "probe": first}
    if first.get("selectedNo"):
        return {"ok": True, "action": "already_selected_no", "probe": first}
    opened = first
    if not first.get("noOption") and isinstance(first.get("selectorRect"), dict):
        click_rect_center(client, first["selectorRect"])
        time.sleep(1)
        opened = client.evaluate(health_certification_probe_script()).get("result", {}).get("value", {})
    no_option = opened.get("noOption") if isinstance(opened.get("noOption"), dict) else None
    if not no_option or not isinstance(no_option.get("rect"), dict):
        raise RuntimeError(f"Step 2 could not select No for Ministry of Health Certification: first={first} opened={opened}")
    click_rect_center(client, no_option["rect"])
    time.sleep(1)
    verified = client.evaluate(health_certification_probe_script()).get("result", {}).get("value", {})
    if not verified.get("selectedNo"):
        raise RuntimeError(f"Step 2 did not verify the No selection for Ministry of Health Certification: {verified}")
    return {"ok": True, "action": "selected_no_by_mouse", "firstProbe": first, "openedProbe": opened, "verifiedProbe": verified}


def run_optional_step2_field(
    field_name: str,
    operation: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run a non-critical Step 2 field without blocking the remaining workflow."""
    try:
        result = operation()
    except Exception as exc:
        return {
            "ok": True,
            "action": "skipped_optional_field_error",
            "field": field_name,
            "reason": f"{field_name} failed and was skipped so later operations can continue",
            "error": str(exc),
        }
    if not isinstance(result, dict):
        return {
            "ok": True,
            "action": "skipped_optional_field_invalid_result",
            "field": field_name,
            "reason": f"{field_name} returned an invalid result and was skipped so later operations can continue",
            "originalResult": result,
        }
    if not result.get("ok"):
        return {
            "ok": True,
            "action": "skipped_optional_field_failed",
            "field": field_name,
            "reason": f"{field_name} did not complete and was skipped so later operations can continue",
            "originalResult": result,
        }
    return result


def ensure_step2_category_unlocked(
    client: CdpClient,
    payload: Dict[str, Any],
    before_probe: Dict[str, Any],
) -> Dict[str, Any]:
    status = before_probe.get("step2Status", {}) if isinstance(before_probe.get("step2Status", {}), dict) else {}
    description = status.get("description", {}) if isinstance(status.get("description", {}), dict) else {}
    if description.get("hasQuill"):
        return {"needed": False, "reason": "description editor already available"}

    choice = choose_category_candidate(before_probe.get("categoryCandidates", []), payload)
    if not choice.get("ok"):
        raise RuntimeError(f"Step 2 requires a category before the description area unlocks, but no category could be confirmed automatically: {choice}")

    select_result = client.evaluate(category_select_script(str(choice.get("text", "")))).get("result", {}).get("value", {})
    if not select_result.get("ok"):
        raise RuntimeError(f"Step 2 category selection failed: choice={choice} selectResult={select_result}")

    unlock_result = wait_for_step2_category_unlock(client)
    after_category_probe = capture_step2_probe(client)
    after_status = after_category_probe.get("step2Status", {}) if isinstance(after_category_probe.get("step2Status", {}), dict) else {}
    after_description = after_status.get("description", {}) if isinstance(after_status.get("description", {}), dict) else {}
    if not after_description.get("hasQuill"):
        raise RuntimeError(
            "A Step 2 category candidate was clicked, but the description editor is still locked: "
            f"choice={choice} selectResult={select_result} unlockResult={unlock_result} afterProbe={after_category_probe}"
        )

    return {
        "needed": True,
        "choice": choice,
        "selectResult": select_result,
        "unlockResult": unlock_result,
        "afterCategoryProbe": after_category_probe,
    }


def run_step2_minimal_info(
    client: CdpClient,
    payload: Dict[str, Any],
    initial_probe: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    before_probe = capture_step2_probe(client, initial_probe=initial_probe)
    status = before_probe.get("step2Status", {}) if isinstance(before_probe.get("step2Status", {}), dict) else {}
    if not status.get("isStep2"):
        raise RuntimeError(f"The page is not on Step 2, so brand and description cannot be filled: {before_probe}")
    title_result = client.evaluate(title_fill_script(str(payload.get("title", "")))).get("result", {}).get("value", {})
    if not title_result.get("ok"):
        raise RuntimeError(f"Step 2 title verification failed: {title_result}")
    category_result = ensure_step2_category_unlocked(client, payload, before_probe)
    fill_result = client.evaluate(
        step2_minimal_fill_script(
            str(payload.get("brand", "")),
            str(payload.get("description", "")),
            "",
        )
    ).get("result", {}).get("value", {})
    after_probe = client.evaluate(step2_probe_script()).get("result", {}).get("value", {})
    cleanup = fill_result.get("cleanup", {}) if isinstance(fill_result.get("cleanup", {}), dict) else {}
    brand_result = fill_result.get("brandResult", {}) if isinstance(fill_result.get("brandResult", {}), dict) else {}
    description = fill_result.get("description", {}) if isinstance(fill_result.get("description", {}), dict) else {}
    if not cleanup.get("titleOk", True):
        raise RuntimeError(f"Step 2 title restoration failed: {fill_result}")
    if not brand_result.get("ok"):
        mouse_brand_result = run_step2_brand_mouse_fallback(client, str(payload.get("brand", "")))
        fill_result["brandResult"] = mouse_brand_result
        brand_result = mouse_brand_result
    if not brand_result.get("ok"):
        raise RuntimeError(f"Step 2 brand filling failed: {fill_result}")
    if not description.get("ok"):
        description = client.evaluate(
            description_fill_script(str(payload.get("description", "")))
        ).get("result", {}).get("value", {})
        fill_result["afterBrandRetry"] = {"description": description}
    if not description.get("ok"):
        raise RuntimeError(f"Step 2 description filling failed: {fill_result}")
    health_certification_result = run_optional_step2_field(
        "Ministry of Health Certification",
        lambda: ensure_health_certification_no(client),
    )
    video_result = upload_product_video(client, payload.get("videos", []))
    extended_fill_result = run_step2_variation_and_logistics(client, payload)
    after_probe = client.evaluate(step2_probe_script()).get("result", {}).get("value", {})
    return {
        "beforeProbe": before_probe,
        "titleResult": title_result,
        "categoryResult": category_result,
        "fillResult": fill_result,
        "healthCertificationResult": health_certification_result,
        "videoResult": video_result,
        "extendedFillResult": extended_fill_result,
        "afterProbe": after_probe,
    }


def run_step2_variation_and_logistics(client: CdpClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    variations = payload.get("variations", [])
    if not isinstance(variations, list) or len(variations) != 3:
        raise RuntimeError("Step 2 requires exactly three variation records before continuing")
    expected_labels = [str(item.get("name", "")).strip() for item in variations if isinstance(item, dict)]
    if len(expected_labels) != 3 or any(not label for label in expected_labels):
        raise RuntimeError("Step 2 variation labels are incomplete")

    result: Dict[str, Any] = {"stages": [], "stageOrder": STEP2_STAGES}
    result["stages"].append({"stage": "enable_variation", "result": client.evaluate(variation_enable_script()).get("result", {}).get("value", {})})
    tier0 = wait_for_step(
        client,
        "enable_variation",
        variation_status_script(),
        lambda state: bool(state.get("tier0Ready")),
    )
    result["tier0Ready"] = tier0

    options_result = client.evaluate(variation_options_fill_script(variations)).get("result", {}).get("value", {})
    result["stages"].append({"stage": "create_variation_options", "result": options_result})
    if not options_result.get("ok"):
        raise RuntimeError(f"Step 2 variation option fill failed: {options_result}")
    table_ready = wait_for_step(
        client,
        "wait_for_variation_rows",
        variation_status_script(),
        lambda state: bool(state.get("hasTable")) and all(label in state.get("rowTexts", []) or any(label in row for row in state.get("rowTexts", [])) for label in expected_labels),
    )
    result["variationTable"] = table_ready

    rows_result = client.evaluate(variation_rows_fill_script(variations, str(payload.get("sku_code", "")))).get("result", {}).get("value", {})
    result["stages"].append({"stage": "variation_rows", "result": rows_result})
    if not rows_result.get("ok"):
        raise RuntimeError(f"Step 2 variation price/stock/SKU fill failed: {rows_result}")

    image_result = upload_variation_images(client, variations, payload.get("sku_images", []))
    result["stages"].append({"stage": "variation_images", "result": image_result})

    package_result = client.evaluate(
        package_and_parent_fill_script(payload.get("package", {}), str(payload.get("sku_code", "")))
    ).get("result", {}).get("value", {})
    result["stages"].append({"stage": "package", "result": package_result})
    if not all(package_result.get(key) for key in ["weight", "width", "length", "height", "parentSku"]):
        time.sleep(0.75)
        package_verification = client.evaluate(
            package_and_parent_status_script(payload.get("package", {}), str(payload.get("sku_code", "")))
        ).get("result", {}).get("value", {})
        result["stages"].append({"stage": "package_verification", "result": package_verification})
        for key in ["weight", "width", "length", "height", "parentSku"]:
            if package_verification.get(key):
                package_result[key] = True
        package_result["finalVerification"] = package_verification
    if not all(package_result.get(key) for key in ["weight", "width", "length", "height", "parentSku"]):
        raise RuntimeError(f"Step 2 package or parent SKU fill failed: {package_result}")

    logistics_before = client.evaluate(logistics_status_script()).get("result", {}).get("value", {})
    logistics_action = client.evaluate(logistics_enable_doorstep_script()).get("result", {}).get("value", {})
    if isinstance(logistics_action.get("toggleRect"), dict):
        click_rect_center(client, logistics_action["toggleRect"])
        time.sleep(2)
    shipping_confirmation = client.evaluate(shipping_confirmation_modal_script()).get("result", {}).get("value", {})
    result["stages"].append(
        {"stage": "logistics", "before": logistics_before, "action": logistics_action, "confirmation": shipping_confirmation}
    )
    if not logistics_action.get("ok"):
        raise RuntimeError(f"Step 2 logistics enable failed: {logistics_action}")
    if shipping_confirmation.get("found") and not shipping_confirmation.get("confirmed"):
        raise RuntimeError(f"Step 2 shipping confirmation modal was not confirmed: {shipping_confirmation}")
    logistics_after = wait_for_step(
        client,
        "logistics",
        logistics_status_script(),
        lambda state: bool(state.get("hasRates")) and bool(state.get("doorstepEnabled")),
    )
    result["logistics"] = logistics_after
    if logistics_after.get("errors"):
        result["logisticsWarnings"] = [
            "The target Doorstep Delivery option is enabled; other non-required logistics warnings were ignored: "
            + "; ".join(str(item) for item in logistics_after.get("errors", []))
        ]
    return result


def upload_variation_images(client: CdpClient, variations: list[Dict[str, Any]], sku_images: object) -> Dict[str, Any]:
    available = [path for path in sku_images if isinstance(path, str) and Path(path).is_file()] if isinstance(sku_images, list) else []
    if not available:
        raise RuntimeError("Variation images are required but no valid SKU image files were found")
    targets = client.evaluate(variation_image_targets_script(variations)).get("result", {}).get("value", {})
    if not targets.get("ok"):
        raise RuntimeError(f"Variation image targets were not found: {targets}")
    for index, target in enumerate(targets.get("targets", [])):
        if target.get("uploaded"):
            continue
        file_input_index = int(target.get("fileInputIndex", -1))
        if file_input_index < 0:
            raise RuntimeError(f"Variation image upload control not found: {target}")
        set_file_input_files(client, file_input_index, [available[index % len(available)]])
        time.sleep(1)
    verified = wait_for_step(
        client,
        "variation_images",
        variation_image_targets_script(variations),
        lambda state: bool(state.get("ok")) and all(item.get("uploaded") for item in state.get("targets", [])),
        timeout_seconds=30,
    )
    return verified


def validate_variation_images_visible(client: CdpClient, sku_code: str, variations: list[Dict[str, Any]]) -> Dict[str, str | bool | list[Dict[str, Any]]]:
    status = client.evaluate(variation_image_visible_status_script(variations)).get("result", {}).get("value", {})
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots = PROJECT_ROOT / "outputs" / "screenshots"
    reports = PROJECT_ROOT / "outputs" / "reports"
    screenshots.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    report_path = reports / f"variation_images_visible_validation_{stamp}.md"
    json_path = reports / f"variation_images_visible_validation_{stamp}.json"
    screenshot_base64 = client.command("Page.captureScreenshot", {"format": "png"}).get("data", "")
    screenshot_path = save_base64_screenshot(
        str(screenshot_base64), screenshots, "variation_images_visible_validation", stamp
    )
    artifact = {
        "captured_at": stamp,
        "sku_code": sku_code,
        "visible_validation": status,
        "screenshot_path": str(screenshot_path),
    }
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = status.get("rows", []) if isinstance(status, dict) else []
    lines = ["# Variation Images Visible Validation", "", f"- SKU: {sku_code}", f"- Visible validation: {bool(status.get('ok')) if isinstance(status, dict) else False}", f"- Screenshot: {screenshot_path}", "", "| Variation | Row visible | Image visible | Size |", "| --- | --- | --- | --- |"]
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        lines.append(f"| {row.get('label', '')} | {row.get('rowVisible', False)} | {row.get('imageVisible', False)} | {row.get('imageWidth', 0)}x{row.get('imageHeight', 0)} |")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "ok": bool(status.get("ok")) if isinstance(status, dict) else False,
        "rows": rows if isinstance(rows, list) else [],
        "screenshot_path": str(screenshot_path),
        "report_path": str(report_path),
        "json_path": str(json_path),
    }


def run_step1_basic_info(client: CdpClient, draft: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    upload_plan = build_step1_upload_plan(draft)
    product_images = product_images_for_step1(upload_plan)
    before = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
    if int(before.get("productImageCount") or 0) >= 1:
        image_status = before
    else:
        image_status = upload_step1_product_images(client, product_images)
    title_result = client.evaluate(title_fill_script(str(payload.get("title", "")))).get("result", {}).get("value", {})
    if not title_result.get("titleFilled"):
        raise RuntimeError(first_page_failure_reason({"missingRequired": ["Title is blank"], "titleResult": title_result}))
    product_code_result = client.evaluate(product_code_fill_script(str(payload.get("sku_code", "")))).get("result", {}).get("value", {})
    gtin_result = client.evaluate(gtin_handling_script()).get("result", {}).get("value", {})
    after_fields = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
    if after_fields.get("nextStep", {}).get("disabled") and after_fields.get("promoImageUpload") and upload_plan.get("promo_image"):
        promo_index = int(after_fields["promoImageUpload"]["index"])
        set_file_input_files(client, promo_index, [str(upload_plan["promo_image"])])
        time.sleep(2)
        wait_for_promo_image(client, 1, timeout_seconds=30)
        after_fields = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
    if after_fields.get("nextStep", {}).get("disabled"):
        raise RuntimeError(first_page_failure_reason(after_fields))
    next_result = click_next_step(client)
    return {
        "before": before,
        "uploadedProductImages": product_images,
        "imageStatus": image_status,
        "titleResult": title_result,
        "productCodeResult": product_code_result,
        "gtinResult": gtin_result,
        "afterFields": after_fields,
        "nextStepResult": next_result,
        "uploadPlanWarnings": upload_plan.get("warnings", []),
        "skippedUnsafeImages": upload_plan.get("skipped_unsafe", []),
    }


def pick_verified_cdp_port() -> int:
    candidates = find_ziniao_cdp_candidates(verify=True)
    if not candidates:
        raise RuntimeError("No verified Ziniao store-browser CDP port was found. Start or switch to the target store in Ziniao first.")
    return candidates[0].port


def open_product_page(port: int) -> Dict[str, Any]:
    pages = [page for page in list_pages(port) if page.get("type", "page") == "page"]
    page = best_page_for_product_new(pages)
    if page and page.get("webSocketDebuggerUrl"):
        return page
    page = create_page(port, NEW_PRODUCT_URL)
    if not page.get("webSocketDebuggerUrl"):
        raise RuntimeError("CDP page does not expose webSocketDebuggerUrl")
    return page


def open_existing_product_page(port: int) -> Dict[str, Any]:
    pages = [page for page in list_pages(port) if page.get("type", "page") == "page"]
    page = best_page_for_product_new(pages)
    if not page or not page.get("webSocketDebuggerUrl"):
        raise RuntimeError("No currently open Shopee product-edit page was found")
    return page


def open_existing_product_list_page(port: int) -> Dict[str, Any]:
    pages = [page for page in list_pages(port) if page.get("type", "page") == "page"]
    page = next(
        (
            item
            for item in pages
            if "/portal/product/list/unpublished/unlisted" in str(item.get("url", ""))
        ),
        None,
    ) or next(
        (
            item
            for item in pages
            if "seller.shopee.com.my/portal/product/list" in str(item.get("url", ""))
        ),
        None,
    ) or best_page_for_product_new(pages)
    if page and page.get("webSocketDebuggerUrl"):
        return page
    page = create_page(port, UNLISTED_PRODUCT_URL)
    if not page.get("webSocketDebuggerUrl"):
        raise RuntimeError("No Shopee product-list page was available for product-ID retrieval")
    return page


def enable_page_domain_if_available(client: CdpClient) -> None:
    try:
        client.command("Page.enable")
    except RuntimeError:
        # Some Ziniao targets expose Runtime but not Page. Runtime evaluation is
        # still enough for diagnostics and field filling.
        return


def ensure_product_new_page(client: CdpClient) -> None:
    state = client.evaluate(
        """
(() => ({
  href: location.href,
  isSellerCenter: location.href.includes("seller.shopee.com.my"),
  isProductNewPage: location.href.includes("/portal/product/new")
}))()
"""
    ).get("result", {}).get("value", {})
    if not (state.get("isSellerCenter") and state.get("isProductNewPage")):
        client.navigate(NEW_PRODUCT_URL)
    wait_for_product_page_ready(client)


def wait_for_product_page_ready(client: CdpClient, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_state: Dict[str, Any] = {}
    while time.time() < deadline:
        state = client.evaluate(
            """
(() => ({
  readyState: document.readyState,
  href: location.href,
  isSellerCenter: location.href.includes("seller.shopee.com.my"),
  bodyLength: (document.body && document.body.innerText || "").length
}))()
"""
        ).get("result", {}).get("value", {})
        last_state = state
        if state.get("readyState") in {"interactive", "complete"} and state.get("isSellerCenter") and state.get("bodyLength", 0) > 100:
            return
        time.sleep(0.5)
    raise RuntimeError(f"The Add Product page did not load before the timeout: {last_state}")


def ensure_unlisted_product_list_page(client: CdpClient) -> None:
    state = client.evaluate(
        """
(() => ({
  href: location.href,
  isSellerCenter: location.href.includes("seller.shopee.com.my"),
  isUnlistedProductPage: location.href.includes("/portal/product/list/unpublished/unlisted")
}))()
"""
    ).get("result", {}).get("value", {})
    if not (state.get("isSellerCenter") and state.get("isUnlistedProductPage")):
        client.navigate(UNLISTED_PRODUCT_URL)
    wait_for_product_list_page_ready(client)


def wait_for_product_list_page_ready(client: CdpClient, timeout_seconds: int = 25) -> None:
    deadline = time.time() + timeout_seconds
    last_state: Dict[str, Any] = {}
    while time.time() < deadline:
        state = client.evaluate(
            """
(() => {
  const bodyText = (document.body && document.body.innerText || "");
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const hasSearchInput = [...document.querySelectorAll("input")].some(node =>
    visible(node)
    && /搜索商品名称|主商品货号|商品货号|商品编号|Search product|Parent SKU|Product ID/i.test(
      node.placeholder || node.getAttribute("aria-label") || ""
    )
  );
  return {
    readyState: document.readyState,
    href: location.href,
    isSellerCenter: location.href.includes("seller.shopee.com.my"),
    isProductListPage: location.href.includes("/portal/product/list"),
    bodyLength: bodyText.length,
    hasSearchInput
  };
})()
"""
        ).get("result", {}).get("value", {})
        last_state = state
        if (
            state.get("readyState") in {"interactive", "complete"}
            and state.get("isSellerCenter")
            and state.get("isProductListPage")
            and state.get("bodyLength", 0) > 500
            and state.get("hasSearchInput")
        ):
            return
        time.sleep(0.5)
    raise RuntimeError(f"The Shopee unlisted-product page did not load before the timeout: {last_state}")


def page_diagnostics_script() -> str:
    return """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const editable = el => !el.disabled && !el.readOnly;
  const nearbyLabel = el => {
    const scope = el.closest(".product-edit-form-item,.eds-form-item,[class*='form-item'],[data-product-edit-field-unique-id],section,div");
    return ((scope && scope.innerText) || "").replace(/\\s+/g, " ").trim().slice(0, 500);
  };
  const inputInfo = el => ({
    placeholder: el.getAttribute("placeholder") || "",
    value: el.value || "",
    type: el.getAttribute("type") || "",
    disabled: !!el.disabled,
    readonly: !!el.readOnly,
    editable: editable(el),
    nearbyLabel: nearbyLabel(el),
    className: String(el.className || "").slice(0, 200),
    name: el.getAttribute("name") || "",
    ariaLabel: el.getAttribute("aria-label") || "",
    maxLength: el.getAttribute("maxlength") || ""
  });
  const bodyText = (document.body && document.body.innerText || "").replace(/\\s+/g, " ").trim();
  return {
    url: location.href,
    title: document.title,
    isSellerCenter: location.href.includes("seller.shopee.com.my"),
    isProductNewPage: location.href.includes("/portal/product/new"),
    isLoginPage: /login|登录|Sign In|Log In/i.test(location.href + " " + bodyText.slice(0, 1000)),
    isCaptchaPage: /verify\\/captcha|verify\\/traffic|captcha|读取时出现问题|再试一次/i.test(location.href + " " + bodyText.slice(0, 1000)),
    isProductListPage: location.href.includes("/portal/product/list") || /我的商品|My Products/i.test(bodyText.slice(0, 1000)),
    isZiniaoExtensionPage: /chrome-extension:|紫鸟|Ziniao/i.test(location.href + " " + document.title),
    bodyTextSample: bodyText.slice(0, 1000),
    visibleInputs: [...document.querySelectorAll("input")].filter(visible).map(inputInfo),
    visibleTextareas: [...document.querySelectorAll("textarea")].filter(visible).map(inputInfo)
  };
})()
"""


def field_locator_script() -> str:
    return """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  return {
    url: location.href,
    titleInputs: [...document.querySelectorAll("input")].filter(visible).length,
    hasQuill: !!document.querySelector(".ql-container,.ql-editor"),
    hasSaveDelist: [...document.querySelectorAll("button")].some(b => visible(b) && (b.innerText || "").trim() === "储存并下架")
  };
})()
"""


def fill_title_and_description_script(payload: Dict[str, Any]) -> str:
    title_script = title_fill_script(str(payload.get("title", "")))
    quill_script = quill_fill_script(str(payload.get("description", "")))
    return f"""
(() => {{
  const titleResult = {title_script};
  if (!titleResult.titleFilled) {{
    return {{
      titleFilled: false,
      reason: titleResult.reason || "title input not found",
      titleResult
    }};
  }}
  const description = {quill_script};
  return {{
    titleFilled: true,
    titleLocator: titleResult.locator,
    titleResult,
    description
  }};
}})()
"""


def click_page_save_delist(client: CdpClient) -> None:
    result = client.evaluate(
        """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  for (const button of document.querySelectorAll("button")) {
    if (visible(button) && (button.innerText || "").trim() === "储存并下架") {
      button.click();
      return { ok: true };
    }
  }
  return { ok: false, reason: "page save delist button not found" };
})()
"""
    )
    value = result.get("result", {}).get("value", {})
    if not value.get("ok"):
        raise RuntimeError(f"The page-level Save and Delist click failed: {value}")


def confirm_save_delist_if_present(
    client: CdpClient,
    attempts: int = 10,
    interval_seconds: float = 0.5,
) -> Dict[str, Any]:
    """Confirm the save/delist modal when it appears; some Shopee pages submit directly."""
    last_probe: Dict[str, Any] = {}
    for attempt in range(max(1, attempts)):
        confirm = client.evaluate(
            exact_modal_button_script("Are you sure to 储存并下架", "储存并下架")
        )
        last_probe = confirm.get("result", {}).get("value", {})
        if last_probe.get("ok"):
            return {
                "ok": True,
                "action": "confirmation_clicked",
                "probe": last_probe,
            }
        if attempt + 1 < max(1, attempts):
            time.sleep(max(0.0, interval_seconds))
    return {
        "ok": True,
        "action": "confirmation_not_present",
        "probe": last_probe,
    }


SAVE_DELIST_SUBMISSION_PROBE_SCRIPT = r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = value => String(value || "").replace(/\s+/g, " ").trim();
  const href = location.href;
  const errorSelectors = [
    ".product-edit__submit-bottom-tip.error",
    ".product-edit-form-item-error",
    ".eds-form-item__error",
    ".eds-input__error-msg",
    ".eds-input-range__error-msg",
    ".eds-alert--error",
    ".eds-toast--error"
  ];
  const fieldErrors = [...document.querySelectorAll(errorSelectors.join(","))]
    .filter(visible)
    .map(node => norm(node.innerText || node.textContent))
    .filter(Boolean);
  const bodyText = norm(document.body && document.body.innerText);
  const summaryPatterns = [
    /由于\s*\d+\s*个错误而无法保存[^。.!]*/i,
    /无法保存[^。.!]*/i,
    /unable to save[^.!]*/i,
    /cannot be saved[^.!]*/i
  ];
  const summaryErrors = summaryPatterns
    .map(pattern => (bodyText.match(pattern) || [""])[0])
    .map(norm)
    .filter(Boolean);
  const successMessages = [...document.querySelectorAll(
    ".eds-toast,.eds-message,.eds-alert,[role='status']"
  )]
    .filter(visible)
    .map(node => norm(node.innerText || node.textContent))
    .filter(text => /保存成功|储存成功|successfully saved|saved successfully/i.test(text));
  const saveButton = [...document.querySelectorAll("button")]
    .find(node => visible(node) && norm(node.innerText) === "储存并下架");
  return {
    href,
    isSellerCenter: href.includes("seller.shopee.com.my"),
    isNewProductPage: href.includes("/portal/product/new"),
    isProductListPage: href.includes("/portal/product/list"),
    blockingErrors: [...new Set([...summaryErrors, ...fieldErrors])].slice(0, 20),
    successMessages: [...new Set(successMessages)].slice(0, 5),
    saveButtonLoading: !!(saveButton && (
      saveButton.disabled
      || /loading|is-loading/i.test(String(saveButton.className || ""))
      || !!saveButton.querySelector(".eds-spinner,.eds-loading,[class*='loading']")
    ))
  };
})()
"""


def wait_for_save_delist_submission(
    client: CdpClient,
    attempts: int = 40,
    interval_seconds: float = 0.5,
    *,
    cancellation_check: Callable[[], bool] | None = None,
) -> Dict[str, Any]:
    """Require Shopee to accept the save before the workflow may query a product ID."""
    last_state: Dict[str, Any] = {}
    last_evaluation_error = ""
    for attempt in range(max(1, attempts)):
        if cancellation_check and cancellation_check():
            raise RuntimeError("The Save-and-Delist wait was cancelled by a newer retry or by the operator")
        try:
            state = client.evaluate(SAVE_DELIST_SUBMISSION_PROBE_SCRIPT)
            last_state = state.get("result", {}).get("value", {})
            last_evaluation_error = ""
        except RuntimeError as exc:
            # Shopee navigation briefly destroys the JavaScript context. Retry until
            # the destination page is available instead of treating that as failure.
            last_evaluation_error = str(exc)
            last_state = {}

        blocking_errors = [
            str(item).strip()
            for item in last_state.get("blockingErrors", [])
            if str(item).strip()
        ]
        if blocking_errors:
            details = "；".join(dict.fromkeys(blocking_errors))
            raise RuntimeError(
                "Shopee rejected Save and Delist, and the Add Product page was preserved. "
                f"Platform message: {details}. Correct the red validation messages and retry Step 13; "
                "the application will not start product-ID retrieval."
            )
        if last_state.get("isProductListPage"):
            return {"ok": True, "accepted_by": "product_list_redirect", **last_state}
        if last_state.get("successMessages"):
            return {"ok": True, "accepted_by": "success_message", **last_state}

        if attempt + 1 < max(1, attempts):
            time.sleep(max(0.0, interval_seconds))

    detail = last_state or {"evaluation_error": last_evaluation_error}
    raise RuntimeError(
        "Shopee acceptance could not be confirmed after clicking Save and Delist. "
        "The Add Product page was preserved and product-ID retrieval will not start; inspect the page and retry Step 13. "
        f"Last state: {detail}"
    )


def manual_save_delist_blocking_reason(check: Dict[str, Any]) -> str:
    """An explicit save action overrides checklist warnings."""
    if not check.get("saveDelistButtonVisible"):
        return "The Save and Delist button was not found on the current page"
    return ""


def capture_artifacts(client: CdpClient, sku_code: str, stage: str) -> tuple[Path, Path]:
    screenshot_dir = PROJECT_ROOT / "outputs" / "screenshots"
    html_dir = PROJECT_ROOT / "outputs" / "html_snapshots"
    screenshot_path = save_base64_screenshot(capture_screenshot_or_empty(client), screenshot_dir, sku_code, stage)
    html_path = save_html_snapshot(client.html(), html_dir, sku_code, stage)
    return screenshot_path, html_path


def capture_screenshot_or_empty(client: CdpClient) -> str:
    try:
        try:
            client.command("Page.bringToFront", {})
        except Exception:
            pass
        result = client.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        return str(result.get("data", ""))
    except Exception:
        try:
            return client.capture_screenshot()
        except Exception:
            return ""


def capture_failure_artifacts(client: CdpClient, sku_code: str, stage: str) -> tuple[Path | str, Path | str, Path | str]:
    screenshot_path: Path | str = ""
    html_path: Path | str = ""
    diagnostics_path: Path | str = ""
    failure_stage = f"{stage}_failure"
    try:
        screenshot_path = save_base64_screenshot(
            capture_screenshot_or_empty(client),
            PROJECT_ROOT / "outputs" / "screenshots",
            sku_code,
            failure_stage,
        )
    except Exception:
        screenshot_path = ""
    try:
        html_path = save_html_snapshot(
            client.html(),
            PROJECT_ROOT / "outputs" / "html_snapshots",
            sku_code,
            failure_stage,
        )
    except Exception:
        html_path = ""
    try:
        diagnostics = client.evaluate(page_diagnostics_script()).get("result", {}).get("value", {})
        diagnostics_path = save_page_diagnostics(
            diagnostics,
            PROJECT_ROOT / "outputs" / "reports",
            sku_code,
            failure_stage,
        )
    except Exception:
        diagnostics_path = ""
    return screenshot_path, html_path, diagnostics_path
