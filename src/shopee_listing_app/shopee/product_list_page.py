from __future__ import annotations

import json


def unlisted_tab_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = value => String(value || "").replace(/\s+/g, " ").trim();
  const tab = document.querySelector("#product-list-tab-unpublished")
    || [...document.querySelectorAll("a,button,.tabs__tab,[role='tab'],.eds-tabs__nav-tab")]
      .find(node =>
        visible(node)
        && (
          /^尚未刊登(?:\s*\(\d+\))?$/i.test(norm(node.innerText))
          || /^Unpublished(?:\s*\(\d+\))?$/i.test(norm(node.innerText))
          || /\/portal\/product\/list\/unpublished/.test(node.getAttribute("href") || "")
        )
      );
  if (!tab) return { tabFound: false, clicked: false, reason: "unpublished tab not found", url: location.href };
  const nav = tab.closest(".eds-tabs__nav-tab,[role='tab']") || tab;
  const alreadyActive = /active/.test(String(nav.className || "")) || nav.getAttribute("aria-selected") === "true";
  if (!alreadyActive) tab.click();
  return { tabFound: true, clicked: !alreadyActive, alreadyActive, text: norm(tab.innerText), url: location.href };
})()
"""


def product_list_search_script(sku_code: str) -> str:
    return rf"""
(() => {{
  const sku = {json.dumps(str(sku_code), ensure_ascii=False)};
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = value => String(value || "").replace(/\s+/g, " ").trim();
  const input = [...document.querySelectorAll("input")].find(node =>
    visible(node)
    && /搜索商品名称|主商品货号|商品货号|商品编号|Search product|Parent SKU|Product ID/i.test(
      node.placeholder || node.getAttribute("aria-label") || ""
    )
  );
  if (!input) return {{ inputFound: false, applied: false, reason: "product search input not found", url: location.href }};
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (setter) setter.call(input, sku); else input.value = sku;
  input.focus();
  input.dispatchEvent(new Event("input", {{ bubbles: true }}));
  input.dispatchEvent(new Event("change", {{ bubbles: true }}));
  const apply = [...document.querySelectorAll("button")].find(button => visible(button) && norm(button.innerText) === "应用");
  if (apply) apply.click();
  else input.dispatchEvent(new KeyboardEvent("keydown", {{ key: "Enter", code: "Enter", bubbles: true }}));
  return {{ inputFound: true, applied: !!apply, usedEnter: !apply, value: input.value, url: location.href }};
}})()
"""


def product_list_status_script(sku_code: str) -> str:
    return rf"""
(() => {{
  const sku = {json.dumps(str(sku_code), ensure_ascii=False)};
  const text = document.body.innerText || "";
  const productIdPattern = /(?:商品编号|商品\s*ID|Product\s*ID)\s*[:：]\s*(\d{{8,}})/i;
  let index = -1;
  let before = "";
  let context = "";
  let productIdMatch = null;
  let cursor = 0;
  while (sku && cursor < text.length) {{
    const candidateIndex = text.indexOf(sku, cursor);
    if (candidateIndex < 0) break;
    const candidateBefore = text.slice(Math.max(0, candidateIndex - 900), candidateIndex);
    const candidateAfter = text.slice(candidateIndex, candidateIndex + 1800);
    const candidateContext = candidateBefore + candidateAfter;
    const candidateProductId = candidateContext.match(productIdPattern);
    if (index < 0 || candidateProductId) {{
      index = candidateIndex;
      before = candidateBefore;
      context = candidateContext;
      productIdMatch = candidateProductId;
    }}
    if (candidateProductId) break;
    cursor = candidateIndex + Math.max(1, sku.length);
  }}
  const statusMatch = context.match(/(?:^|\n)\s*(未上架|尚未刊登|Unlisted)\s*(?:\n|$)/i);
  const pageIsUnlisted = /\/portal\/product\/list\/unpublished(?:\/unlisted)?/i.test(location.pathname);
  return {{
    found: index >= 0,
    sku,
    productId: productIdMatch ? productIdMatch[1] : "",
    status: statusMatch ? statusMatch[1] : "",
    hasUnlistedStatus: !!statusMatch || pageIsUnlisted,
    pageIsUnlisted,
    url: location.href,
    context: context.slice(0, 1800)
  }};
}})()
"""


PRODUCT_LIST_STATUS_SCRIPT = product_list_status_script("")
