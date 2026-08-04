from __future__ import annotations


def gtin_handling_script() -> str:
    return """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const body = document.body ? document.body.innerText : "";
  const withoutGtin = [...document.querySelectorAll("label,button,span,div")]
    .filter(visible)
    .find(el => /没有GTIN|无GTIN|No GTIN|without GTIN/i.test(norm(el.innerText)));
  if (withoutGtin) {
    const clickable = withoutGtin.closest("label,button") || withoutGtin;
    clickable.click();
    return { ok: true, action: "clicked_without_gtin", text: norm(withoutGtin.innerText).slice(0, 200) };
  }
  const gtinInput = [...document.querySelectorAll("input")]
    .filter(visible)
    .find(input => /GTIN|通用商品代码/i.test(norm((input.closest(".edit-row,[class*='edit-row'],section,div") || {}).innerText || "") + " " + (input.placeholder || "")));
  if (gtinInput && gtinInput.value) {
    gtinInput.value = "";
    gtinInput.dispatchEvent(new Event("input", { bubbles: true }));
    gtinInput.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return { ok: true, action: "left_blank", hasGtinArea: /GTIN|通用商品代码/i.test(body) };
})()
"""
