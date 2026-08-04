from __future__ import annotations

import base64
from pathlib import Path


def save_base64_screenshot(base64_data: str, output_dir: Path, sku_code: str, stage: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{safe_part(sku_code)}_{safe_part(stage)}.png"
    data = base64.b64decode(base64_data) if base64_data else b""
    path.write_bytes(data)
    return path


def safe_part(value: object) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "unknown"))
