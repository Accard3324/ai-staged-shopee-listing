from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Mapping


def ensure_output_dirs(project_root: Path) -> None:
    for rel in [
        "outputs/candidates",
        "outputs/asset_manifests",
        "outputs/competitor_sources",
        "outputs/listings",
        "outputs/reports",
        "outputs/screenshots",
        "outputs/html_snapshots",
        "logs",
    ]:
        (project_root / rel).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_run_report(path: Path, draft: Mapping[str, object]) -> Path:
    listing = draft.get("listing", {})
    candidate = draft.get("candidate", {})
    assets = draft.get("assets", {})
    competitors = draft.get("competitors", [])
    variations = draft.get("variations", [])
    upload = draft.get("upload_draft", {})

    lines = [
        "# Shopee Listing Draft Report",
        "",
        f"- Store: {draft.get('store', {}).get('name', '') if isinstance(draft.get('store'), dict) else ''}",
        f"- SKU code: {candidate.get('sku_code', '') if isinstance(candidate, dict) else ''}",
        f"- Product name: {candidate.get('product_name', '') if isinstance(candidate, dict) else ''}",
        f"- Title: {listing.get('title', '') if isinstance(listing, dict) else ''}",
        f"- Save mode: Save and Delist",
        f"- Workbook updated: No",
        f"- Upload implemented in this phase: {upload.get('implemented', False) if isinstance(upload, dict) else False}",
        "",
        "## Assets",
        "",
        f"- Main images: {len(assets.get('main_images', [])) if isinstance(assets, dict) else 0}",
        f"- Detail images: {len(assets.get('detail_images', [])) if isinstance(assets, dict) else 0}",
        f"- SKU images: {len(assets.get('sku_images', [])) if isinstance(assets, dict) else 0}",
        f"- Videos: {len(assets.get('videos', [])) if isinstance(assets, dict) else 0}",
        "",
        "## Variations",
        "",
    ]
    for item in variations if isinstance(variations, list) else []:
        lines.append(
            f"- {item.get('name')}: price {item.get('price')}, stock {item.get('stock')}, item code {item.get('item_code')}"
        )

    lines.extend(["", "## Competitors", ""])
    for source in competitors if isinstance(competitors, list) else []:
        lines.append(
            f"- {source.get('observed_sales', '')} | {source.get('source_title', '')} | {source.get('url', '')}"
        )
    if not competitors:
        lines.append("- No competitor source was collected in this run.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
