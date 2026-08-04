from __future__ import annotations

import json


def product_code_fill_script(sku_code: str) -> str:
    return f"""
(() => {{
  const skuCode = {json.dumps(str(sku_code), ensure_ascii=False)};
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  function setValue(el, value) {{
    el.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(el, value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: value }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.blur();
  }}
  function scopeText(el) {{
    return norm((el.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,section,div") || {{}}).innerText || "");
  }}
  function skipGtinLike(el) {{
    const text = `${{scopeText(el)}} ${{el.placeholder || ""}}`;
    return /GTIN|通用商品代码|Global Trade Item/i.test(text);
  }}
  const inputs = [...document.querySelectorAll("input")].filter(input => visible(input) && !input.disabled && !input.readOnly);
  const target = inputs.find(input => /商品代码|Product Code|SKU Code/i.test(scopeText(input)) && !skipGtinLike(input));
  if (!target) return {{ ok: true, skipped: true, reason: "product code input not present or GTIN-like only" }};
  setValue(target, skuCode);
  return {{ ok: norm(target.value) === skuCode, skipped: false, value: target.value || "" }};
}})()
"""
