from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from ...browser.cdp_client import CdpClient


STEP2_STAGES = [
    "title",
    "category",
    "brand_attributes",
    "description",
    "video",
    "enable_variation",
    "create_variation_options",
    "wait_for_variation_rows",
    "variation_images",
    "variation_prices",
    "variation_stock",
    "variation_sku",
    "variation_gtin",
    "package",
    "logistics",
    "parent_sku",
    "pre_save_check",
    "save_delist",
]


def wait_for_step(
    client: CdpClient,
    stage: str,
    script: str,
    is_ready: Callable[[Mapping[str, Any]], bool],
    timeout_seconds: float = 12,
) -> dict[str, Any]:
    """Wait for a Shopee UI state change instead of relying on a fixed delay."""
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        value = client.evaluate(script).get("result", {}).get("value", {})
        last = value if isinstance(value, dict) else {"value": value}
        if is_ready(last):
            return last
        time.sleep(0.35)
    raise RuntimeError(f"Step 2 stopped at {stage}: expected UI state was not reached: {last}")
