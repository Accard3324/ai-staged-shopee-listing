from __future__ import annotations

import json
from typing import Any, Mapping


def step2_extended_fill_script(payload: Mapping[str, Any]) -> str:
    return f"""
(() => {{
  const payload = {json.dumps(dict(payload), ensure_ascii=False)};
  const variations = Array.isArray(payload.variations) ? payload.variations : [];
  const packageInfo = payload.package || {{}};
  const skuCode = String(payload.sku_code || "");
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const setValue = (el, value) => {{
    if (!el) return false;
    el.focus();
    const descriptor = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value");
    if (descriptor && descriptor.set) descriptor.set.call(el, String(value));
    else el.value = String(value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: String(value) }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dispatchEvent(new KeyboardEvent("keydown", {{ bubbles: true, key: "Tab" }}));
    el.blur();
    return true;
  }};
  const clickExact = (scope, texts) => {{
    const wanted = Array.isArray(texts) ? texts : [texts];
    const button = [...(scope || document).querySelectorAll("button,.eds-switch,[role='button'],span,div")]
      .filter(visible)
      .find(el => wanted.some(text => norm(el.innerText) === text || norm(el.innerText).includes(text)));
    if (button) {{ button.click(); return true; }}
    return false;
  }};
  const fillFieldById = (id, value) => {{
    const scope = document.querySelector(`[data-product-edit-field-unique-id="${{id}}"]`);
    if (!scope) return false;
    const input = [...scope.querySelectorAll("input,textarea")].filter(visible)[0];
    return setValue(input, value);
  }};

  const result = {{
    variation: {{ attempted: false, options: [], rows: 0, warnings: [] }},
    sales: {{ prices: [], stock: [], skuCodes: [] }},
    package: {{ weight: false, dimensions: [] }},
    logistics: {{ attempted: false, hasDoorstep: false }},
    parentSku: false,
    warnings: []
  }};

  const variationScope = document.querySelector('[data-product-edit-field-unique-id="variation"], [data-product-edit-field-unique-id="tierVariation_0"]');
  if (variationScope && variations.length) {{
    result.variation.attempted = true;
    const tier0 = document.querySelector('[data-product-edit-field-unique-id="tierVariation_0"]') || variationScope;
    if (!document.querySelector(".variation-model-table-container")) {{
      clickExact(variationScope, ["开启商品规格", "Enable Variations", "规格"]);
    }}
    const nameInput = [...tier0.querySelectorAll("input")].filter(visible)[0];
    if (nameInput && !/Quantity/i.test(nameInput.value || "")) setValue(nameInput, "Quantity");
    const optionInputs = [...tier0.querySelectorAll("input")]
      .filter(input => visible(input) && input !== nameInput)
      .slice(0, variations.length);
    variations.forEach((item, index) => {{
      const input = optionInputs[index];
      if (input) {{
        setValue(input, item.name || "");
        result.variation.options.push(item.name || "");
      }}
    }});
  }}

  const table = document.querySelector(".variation-model-table-container");
  if (table && variations.length) {{
    const rowCandidates = [...table.querySelectorAll(".second-variation-wrapper,.flex.data-group,.variation-model-table-body [class*='row'],.variation-model-table-body > div")]
      .filter(visible)
      .filter(row => variations.some(item => norm(row.innerText).includes(norm(item.name))));
    const rows = rowCandidates.length ? rowCandidates : [...table.querySelectorAll(".variation-model-table-body .flex,.variation-model-table-body > div")].filter(visible);
    result.variation.rows = rows.length;
    variations.forEach((item, index) => {{
      const row = rows.find(candidate => norm(candidate.innerText).includes(norm(item.name))) || rows[index];
      if (!row) return;
      const inputs = [...row.querySelectorAll("input")].filter(visible);
      const textareas = [...row.querySelectorAll("textarea")].filter(visible);
      const priceInput = row.querySelector(".price-input input") || inputs.find(input => /RM|price|价格/i.test(norm((input.closest("div") || {{}}).innerText)));
      const stockInput = row.querySelector(".stock-column input") || inputs.find(input => /stock|库存|数量|quantity/i.test(norm((input.closest("div") || {{}}).innerText)));
      const skuTextarea = row.querySelector(".sku-textarea textarea") || textareas[0];
      if (priceInput && setValue(priceInput, item.price || "")) result.sales.prices.push(item.price || "");
      if (stockInput && setValue(stockInput, item.stock || "")) result.sales.stock.push(item.stock || "");
      if (skuTextarea && setValue(skuTextarea, item.item_code || skuCode)) result.sales.skuCodes.push(item.item_code || skuCode);
      clickExact(row, ["没有GTIN的商品", "No GTIN"]);
    }});
  }} else if (variations[0]) {{
    fillFieldById("price", variations[0].price || "");
    fillFieldById("stock", variations[0].stock || "");
    result.sales.prices.push(variations[0].price || "");
    result.sales.stock.push(variations[0].stock || "");
  }}

  if (packageInfo.weight_kg) result.package.weight = fillFieldById("weight", packageInfo.weight_kg);
  for (const [id, value] of [
    ["dimension.width", packageInfo.width_cm],
    ["dimension.length", packageInfo.length_cm],
    ["dimension.height", packageInfo.height_cm],
  ]) {{
    if (value) result.package.dimensions.push({{ id, ok: fillFieldById(id, value) }});
  }}
  clickExact(document.querySelector('[data-product-edit-field-unique-id="dangersGoods"]') || document, ["否", "No"]);
  clickExact(document.querySelector('[data-product-edit-field-unique-id="preOrder"]') || document, ["否", "No"]);
  result.parentSku = fillFieldById("parentSku", skuCode);

  const logisticScope = document.querySelector('[data-product-edit-field-unique-id="logistic"],.product-shipping');
  result.logistics.hasDoorstep = !!(logisticScope && /Doorstep/i.test(norm(logisticScope.innerText)));
  if (logisticScope && !/RM\\s?\\d|Doorstep|SHOPEE/i.test(norm(logisticScope.innerText))) {{
    result.logistics.attempted = clickExact(logisticScope, ["Doorstep Delivery", "Doorstep"]);
  }}
  return result;
}})()
"""
