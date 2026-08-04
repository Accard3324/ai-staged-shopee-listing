from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..competitor_collector import safe_filename
from ..config_manager import PROJECT_ROOT


def latest_asset_manifest(sku_code: str | None = None, project_root: Path = PROJECT_ROOT) -> Path:
    manifest_dir = project_root / "outputs" / "asset_manifests"
    if sku_code:
        expected = manifest_dir / f"{safe_filename(str(sku_code))}_asset_manifest.json"
        if expected.exists():
            return expected
    files = sorted(manifest_dir.glob("*_asset_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("asset_manifest.json was not found. Inspect the asset pack first.")
    return files[0]


def load_asset_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"asset_manifest.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
