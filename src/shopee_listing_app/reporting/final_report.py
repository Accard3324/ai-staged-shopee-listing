from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


def write_autofill_failure_report(
    output_dir: Path,
    sku_code: str,
    stage: str,
    reason: str,
    screenshot_path: Path | str,
    html_path: Path | str,
    diagnostics_path: Path | str = "",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{sku_code}_{stage}_failure.md"
    lines = [
        "# Shopee Autofill Failure",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- SKU: {sku_code}",
        f"- Stage: {stage}",
        f"- Reason: {reason}",
        f"- Screenshot: {screenshot_path or 'not captured'}",
        f"- HTML snapshot: {html_path or 'not captured'}",
        f"- Diagnostics: {diagnostics_path or 'not captured'}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def save_page_diagnostics(diagnostics: dict, output_dir: Path, sku_code: str, stage: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{sku_code}_{stage}_page_diagnostics.json"
    path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_autofill_failure_log(
    output_dir: Path,
    sku_code: str,
    stage: str,
    reason: str,
    screenshot_path: Path | str,
    html_path: Path | str,
    diagnostics_path: Path | str,
    report_path: Path | str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{sku_code}_{stage}_failure_{stamp}.log"
    lines = [
        f"time={datetime.now().isoformat(timespec='seconds')}",
        f"sku={sku_code}",
        f"stage={stage}",
        f"reason={reason}",
        f"screenshot={screenshot_path or 'not captured'}",
        f"html={html_path or 'not captured'}",
        f"diagnostics={diagnostics_path or 'not captured'}",
        f"report={report_path or 'not captured'}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_autofill_success_report(output_dir: Path, sku_code: str, mode: str, message: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{sku_code}_{mode}_autofill_success.md"
    path.write_text(
        "\n".join(
            [
                "# Shopee Autofill Result",
                "",
                f"- Time: {datetime.now().isoformat(timespec='seconds')}",
                f"- SKU: {sku_code}",
                f"- Mode: {mode}",
                f"- Result: {message}",
            ]
        ),
        encoding="utf-8",
    )
    return path
