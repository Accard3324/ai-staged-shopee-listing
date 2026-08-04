from __future__ import annotations

from pathlib import Path

from .screenshot_manager import safe_part


def save_html_snapshot(html: str, output_dir: Path, sku_code: str, stage: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{safe_part(sku_code)}_{safe_part(stage)}.html"
    path.write_text(html or "", encoding="utf-8")
    return path
