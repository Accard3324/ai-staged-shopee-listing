from __future__ import annotations

import json


def title_fill_script(title: str) -> str:
    return f"""
(() => {{
  const title = {json.dumps(title, ensure_ascii=False)};
  const titleLabels = ["商品名称", "商品标题", "Product Name", "Product Title", "Nama Produk", "Product Info", "Basic Information"];
  const titlePlaceholders = [
    "请输入商品名称",
    "请输入商品标题",
    "Please enter product name",
    "Enter product name",
    "Product name",
    "品牌名称 + 商品类型"
  ];
  const badTitleText = /category|类别|类目|brand id|品牌 ID|sku|seller sku|gtin|price|价格|stock|库存|quantity|数量|重量|weight|dimension|尺寸|search|搜索|关键字/i;
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const editable = el => !el.disabled && !el.readOnly;
  const normalize = text => String(text || "").replace(/\\s+/g, " ").trim();
  function setValue(el, value) {{
    el.focus();
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    nativeInputValueSetter.call(el, value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: value }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.blur();
  }}
  function fieldScope(el) {{
    return el.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,.eds-form-item,[class*='form-item'],[class*='FormItem'],[data-product-edit-field-unique-id],section");
  }}
  function labelText(el) {{
    const labels = [];
    let cursor = el.parentElement;
    for (let depth = 0; cursor && depth < 6; depth += 1, cursor = cursor.parentElement) {{
      const items = cursor.querySelectorAll(":scope > label,:scope .edit-label,:scope .edit-title,:scope .eds-form-item__label,:scope [class*='label']");
      for (const item of items) labels.push(item.innerText || "");
      if (labels.some(text => normalize(text))) break;
    }}
    return normalize(labels.join(" "));
  }}
  function nearbyText(el) {{
    const scope = fieldScope(el);
    return normalize([
      el.placeholder || "",
      el.getAttribute("aria-label") || "",
      el.getAttribute("name") || "",
      labelText(el),
      scope ? scope.innerText : ""
    ].join(" ")).slice(0, 1200);
  }}
  function hasTitleSignal(text) {{
    return titleLabels.some(label => text.includes(label)) || titlePlaceholders.some(label => text.includes(label));
  }}
  function isBadInputCandidate(el) {{
    if (!(el.tagName === "INPUT")) return true;
    if (!visible(el) || !editable(el)) return true;
    const type = String(el.getAttribute("type") || "text").toLowerCase();
    if (!["", "text"].includes(type)) return true;
    const text = nearbyText(el);
    if (badTitleText.test(text) && !hasTitleSignal(text)) return true;
    return false;
  }}
  function titleScore(el) {{
    if (isBadInputCandidate(el)) return -1;
    const text = nearbyText(el);
    let score = -1;
    if (text.includes("商品名称") || text.includes("商品标题")) score = Math.max(score, 120);
    if (text.includes("Product Name") || text.includes("Product Title") || text.includes("Nama Produk")) score = Math.max(score, 110);
    if (titlePlaceholders.some(label => text.includes(label))) score = Math.max(score, 100);
    const maxLength = Number(el.getAttribute("maxlength") || "0");
    if (maxLength >= 120 && maxLength <= 300) score = Math.max(score, 70);
    return score;
  }}
  const candidates = [...document.querySelectorAll("input")].map(el => ({{
    el,
    score: titleScore(el),
    text: nearbyText(el),
    placeholder: el.placeholder || "",
    value: el.value || ""
  }})).filter(item => item.score >= 0).sort((a, b) => b.score - a.score);
  const best = candidates[0];
  if (!best) {{
    return {{
      ok: false,
      titleFilled: false,
      reason: "title input not found",
      candidateCount: candidates.length,
      visibleInputCount: [...document.querySelectorAll("input")].filter(visible).length
    }};
  }}
  setValue(best.el, title);
  const filled = normalize(best.el.value).includes(normalize(title).slice(0, 20));
  return {{
    ok: filled,
    titleFilled: filled,
    reason: filled ? "" : "title value verification failed",
    locator: {{
      score: best.score,
      nearbyText: best.text.slice(0, 500),
      placeholder: best.placeholder
    }},
    candidates: candidates.slice(0, 5).map(item => ({{
      score: item.score,
      placeholder: item.placeholder,
      nearbyText: item.text.slice(0, 300)
    }}))
  }};
}})()
"""
