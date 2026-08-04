from __future__ import annotations

from typing import Any, Dict, Iterable


def find_page_by_url(pages: Iterable[Dict[str, Any]], contains: str) -> Dict[str, Any] | None:
    for page in pages:
        if contains in str(page.get("url", "")):
            return page
    return None


def best_page_for_product_new(pages: list[Dict[str, Any]]) -> Dict[str, Any] | None:
    return find_page_by_url(pages, "seller.shopee.com.my/portal/product/new") or find_page_by_url(
        pages, "seller.shopee.com.my"
    )
