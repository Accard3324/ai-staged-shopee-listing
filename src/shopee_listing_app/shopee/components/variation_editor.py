from __future__ import annotations

import json
from typing import Any, Mapping


def variation_status_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const tier0 = document.querySelector('[data-product-edit-field-unique-id="tierVariation_0"]');
  const table = document.querySelector(".variation-model-table-container");
  const optionValues = tier0 ? [...tier0.querySelectorAll("input")].filter(visible).map(input => input.value || "") : [];
  const rows = table ? [...table.querySelectorAll(".second-variation-wrapper,.flex.data-group,.variation-model-table-body [class*='row'],.variation-model-table-body > div")]
    .filter(visible)
    .map(row => norm(row.innerText))
    .filter(text => /\/[123]box$/i.test(text.split(" ").slice(0, 6).join(" ")) || /\/[123]box/i.test(text)) : [];
  return { tier0Ready: !!tier0, hasTable: !!table, optionValues, rowTexts: rows };
})()
"""


def variation_enable_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  if (document.querySelector('[data-product-edit-field-unique-id="tierVariation_0"]')) {
    return { ok: true, action: "already_enabled" };
  }
  const scope = document.querySelector('[data-product-edit-field-unique-id="variation"]');
  const button = scope && [...scope.querySelectorAll("button")].find(visible);
  if (!button) return { ok: false, reason: "variation enable button not found" };
  button.scrollIntoView({ block: "center", inline: "nearest" });
  button.click();
  return { ok: true, action: "clicked_enable_variation" };
})()
"""


def variation_options_fill_script(variations: list[Mapping[str, Any]]) -> str:
    return f"""
(async () => {{
  const variations = {json.dumps([dict(item) for item in variations], ensure_ascii=False)};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const setValue = (el, value) => {{
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    el.focus();
    if (setter) setter.call(el, String(value)); else el.value = String(value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: String(value) }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.dispatchEvent(new KeyboardEvent("keydown", {{ bubbles: true, key: "Tab" }}));
    el.dispatchEvent(new KeyboardEvent("keyup", {{ bubbles: true, key: "Tab" }}));
    el.blur();
  }};
  const tier0 = document.querySelector('[data-product-edit-field-unique-id="tierVariation_0"]');
  if (!tier0) return {{ ok: false, reason: "Variation1 is not ready" }};
  const allInputs = () => [...tier0.querySelectorAll("input")].filter(visible).filter(input => !input.disabled && !input.readOnly);
  const optionInputs = () => allInputs().filter(input => input !== nameInput && !/添加说明|description/i.test(String(input.placeholder || "")));
  const initialInputs = allInputs();
  const nameInput = initialInputs[0];
  if (!nameInput) return {{ ok: false, reason: "Variation1 name input not found" }};
  if (String(nameInput.value || "").trim() !== "Quantity") {{
    setValue(nameInput, "Quantity");
    await sleep(450);
  }}
  const filled = [];
  for (const input of allInputs().filter(input => /添加说明|description/i.test(String(input.placeholder || "")))) {{
    if (variations.some(item => String(item.name || "").trim() === String(input.value || "").trim())) setValue(input, "");
  }}
  for (const [index, variation] of variations.entries()) {{
    const target = String(variation.name || "").trim();
    if (!target) continue;
    const option = optionInputs()[index];
    if (!option) return {{ ok: false, reason: "next variation option input not found", filled }};
    if (String(option.value || "").trim() !== target) setValue(option, target);
    await sleep(650);
    filled.push(target);
  }}
  const values = optionInputs().map(input => String(input.value || "").trim());
  return {{ ok: variations.every(item => values.includes(String(item.name || "").trim())), filled, values }};
}})()
"""


def variation_rows_fill_script(variations: list[Mapping[str, Any]], sku_code: str) -> str:
    return f"""
(async () => {{
  const variations = {json.dumps([dict(item) for item in variations], ensure_ascii=False)};
  const skuCode = {json.dumps(sku_code, ensure_ascii=False)};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const setValue = (el, value) => {{
    if (!el) return false;
    const prototype = el instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    el.focus();
    if (setter) setter.call(el, String(value)); else el.value = String(value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: String(value) }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.blur();
    return String(el.value || "").trim() === String(value);
  }};
  const table = document.querySelector(".variation-model-table-container");
  if (!table) return {{ ok: false, reason: "variation model table not found" }};
  const labelRows = [...table.querySelectorAll(".variation-model-table-fixed-left .variation-model-table-body .table-cell-wrapper")]
    .filter(visible)
    .map(row => ({{ row, text: norm(row.innerText), top: row.getBoundingClientRect().top }}));
  const dataRows = [...table.querySelectorAll(".variation-model-table-middle-scroll .variation-model-table-body .second-variation-wrapper")]
    .filter(visible)
    .map(row => ({{ row, top: row.getBoundingClientRect().top }}));
  const nearestDataRow = labelRow => dataRows
    .slice()
    .sort((a, b) => Math.abs(a.top - labelRow.top) - Math.abs(b.top - labelRow.top))[0]?.row;
  const filled = [];
  for (const variation of variations) {{
    const label = String(variation.name || "").trim();
    const labelRow = labelRows.filter(item => item.text.includes(label)).sort((a, b) => a.text.length - b.text.length)[0];
    const row = labelRow && nearestDataRow(labelRow);
    if (!row) return {{ ok: false, reason: "variation row not found", label, rowTexts: labelRows.map(item => item.text) }};
    const price = row.querySelector(".price-input input");
    const stock = row.querySelector(".stock-column input");
    const sku = row.querySelector(".sku-textarea textarea");
    if (!price || !stock || !sku) return {{ ok: false, reason: "variation row fields not found", label }};
    const noGtin = row.querySelector(".two-tier-variation-item-without-gtin input[type='checkbox']");
    const noGtinLabel = noGtin?.closest("label") || noGtin;
    if (noGtin && !noGtin.checked) noGtinLabel.click();
    filled.push({{
      label,
      price: setValue(price, variation.price || ""),
      stock: setValue(stock, variation.stock || ""),
      sku: setValue(sku, variation.item_code || skuCode),
      noGtin: !!noGtin?.checked,
    }});
    await sleep(250);
  }}
  return {{ ok: filled.length === variations.length && filled.every(item => item.price && item.stock && item.sku && item.noGtin), filled }};
}})()
"""


def variation_image_targets_script(variations: list[Mapping[str, Any]]) -> str:
    return rf"""
(() => {{
  const variations = {json.dumps([dict(item) for item in variations], ensure_ascii=False)};
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const table = document.querySelector(".variation-model-table-container");
  const fileInputs = [...document.querySelectorAll('input[type="file"]')];
  if (!table) return {{ ok: false, reason: "variation model table not found", targets: [] }};
  const labelRows = [...table.querySelectorAll(".variation-model-table-fixed-left .variation-model-table-body .table-cell-wrapper")]
    .filter(visible)
    .map(row => ({{ row, text: norm(row.innerText), top: row.getBoundingClientRect().top }}));
  const targets = variations.map(variation => {{
    const label = String(variation.name || "").trim();
    const labelRow = labelRows.filter(item => item.text.includes(label)).sort((a, b) => a.text.length - b.text.length)[0];
    const manager = labelRow?.row.querySelector(".variation-image-manager,[class*='variation-image']");
    const fileInput = manager?.querySelector('input[type="file"]');
    const image = [...(manager?.querySelectorAll("img") || [])].find(item => {{
      const src = item.getAttribute("src") || item.getAttribute("data-src") || "";
      return visible(item) && !!src && !src.startsWith("data:");
    }});
    return {{ label, found: !!labelRow && !!manager, uploaded: !!image, fileInputIndex: fileInput ? fileInputs.indexOf(fileInput) : -1 }};
  }});
  return {{ ok: targets.length === variations.length, targets }};
}})()
"""


def variation_image_visible_status_script(variations: list[Mapping[str, Any]]) -> str:
    return rf"""
(() => {{
  const variations = {json.dumps([dict(item) for item in variations], ensure_ascii=False)};
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const table = document.querySelector(".variation-model-table-container");
  if (!table) return {{ ok: false, reason: "variation model table not found", rows: [] }};
  table.scrollIntoView({{ block: "center", inline: "nearest" }});
  const tableRect = table.getBoundingClientRect();
  const labelRows = [...table.querySelectorAll(".variation-model-table-fixed-left .variation-model-table-body .table-cell-wrapper")]
    .filter(visible)
    .map(row => ({{ row, text: norm(row.innerText) }}));
  const rows = variations.map(variation => {{
    const label = String(variation.name || "").trim();
    const match = labelRows.filter(item => item.text.includes(label)).sort((a, b) => a.text.length - b.text.length)[0];
    const image = [...(match?.row.querySelectorAll(".variation-image-manager img") || [])].find(item => {{
      const src = item.getAttribute("src") || item.getAttribute("data-src") || "";
      return visible(item) && !!src && !src.startsWith("data:");
    }});
    const rowRect = match?.row.getBoundingClientRect();
    const imageRect = image?.getBoundingClientRect();
    const imageVisible = !!image && visible(image) && !!imageRect && imageRect.width >= 20 && imageRect.height >= 20
      && imageRect.bottom > 0 && imageRect.top < window.innerHeight && imageRect.left >= tableRect.left - 4;
    return {{
      label,
      rowFound: !!match,
      rowVisible: !!rowRect && rowRect.bottom > 0 && rowRect.top < window.innerHeight,
      imageVisible,
      imageSrc: image?.getAttribute("src") || image?.getAttribute("data-src") || "",
      imageWidth: Math.round(imageRect?.width || 0),
      imageHeight: Math.round(imageRect?.height || 0),
    }};
  }});
  return {{ ok: rows.length === variations.length && rows.every(item => item.rowFound && item.rowVisible && item.imageVisible), rows }};
}})()
"""


def logistics_status_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const scope = document.querySelector('[data-product-edit-field-unique-id="logistic"],.product-shipping');
  if (!scope) return { found: false };
  const rows = [...scope.querySelectorAll(".optional-item,.logistics-item,[class*='logistics-item']")].filter(visible);
  const doorstep = rows.find(row => /Doorstep Delivery\s*SHOPEE|Doorstep Delivery/i.test(row.innerText || "") && !/Sea Shipping/i.test(row.innerText || ""));
  const doorstepSwitch = doorstep?.querySelector(".eds-switch");
  const errors = [...scope.querySelectorAll(".logistics-global-error-tips,.eds-form-item__error,.error,[class*='error']")]
    .filter(visible)
    .map(el => (el.innerText || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return {
    found: true,
    hasRates: /RM\s?\d/.test(scope.innerText || ""),
    doorstepFound: !!doorstep,
    doorstepEnabled: !!doorstepSwitch && /eds-switch--open/.test(String(doorstepSwitch.className || "")),
    errors,
  };
})()
"""


def logistics_enable_doorstep_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const scope = document.querySelector('[data-product-edit-field-unique-id="logistic"],.product-shipping');
  if (!scope) return { ok: false, reason: "shipping panel not found" };
  const rows = [...scope.querySelectorAll(".optional-item,.logistics-item,[class*='logistics-item']")].filter(visible);
  const doorstep = rows.find(row => /Doorstep Delivery\s*SHOPEE|Doorstep Delivery/i.test(row.innerText || "") && !/Sea Shipping/i.test(row.innerText || ""));
  const toggle = doorstep?.querySelector(".eds-switch");
  if (!toggle) return { ok: false, reason: "ordinary Doorstep Delivery switch not found" };
  if (/eds-switch--open/.test(String(toggle.className || ""))) return { ok: true, action: "already_enabled" };
  toggle.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = toggle.getBoundingClientRect();
  return {
    ok: true,
    action: "requires_mouse_click",
    toggleRect: {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      width: rect.width,
      height: rect.height
    }
  };
})()
"""


def package_and_parent_fill_script(package: Mapping[str, Any], sku_code: str) -> str:
    return rf"""
(async () => {{
  const packageInfo = {json.dumps(dict(package), ensure_ascii=False)};
  const skuCode = {json.dumps(sku_code, ensure_ascii=False)};
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const valuesEquivalent = (actual, expected) => {{
    const left = String(actual ?? "").trim();
    const right = String(expected ?? "").trim();
    if (left === right) return true;
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    return left !== "" && right !== "" && Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber === rightNumber;
  }};
  const setValue = async (el, value) => {{
    if (!el || value === undefined || value === null || value === "") return false;
    if (valuesEquivalent(el.value, value)) return true;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    el.focus();
    if (setter) setter.call(el, String(value)); else el.value = String(value);
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: String(value) }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.blur();
    await delay(350);
    return valuesEquivalent(el.value, value);
  }};
  const fillField = async (id, value) => {{
    const scope = document.querySelector(`[data-product-edit-field-unique-id="${{id}}"]`);
    const input = scope && [...scope.querySelectorAll("input")].find(visible);
    return await setValue(input, value);
  }};
  const clickNoRadio = id => {{
    const scope = document.querySelector(`[data-product-edit-field-unique-id="${{id}}"]`);
    const radio = scope && [...scope.querySelectorAll('input[type="radio"]')].find(input => input.value === "0" || input.value === "false");
    if (!radio) return false;
    if (!radio.checked) radio.closest("label")?.click();
    return true;
  }};
  return {{
    weight: await fillField("weight", packageInfo.weight_kg),
    width: await fillField("dimension.width", packageInfo.width_cm),
    length: await fillField("dimension.length", packageInfo.length_cm),
    height: await fillField("dimension.height", packageInfo.height_cm),
    dangerousGoodsNo: clickNoRadio("dangersGoods"),
    preOrderNo: clickNoRadio("preOrder"),
    parentSku: await fillField("parentSku", skuCode),
  }};
}})()
"""


def package_and_parent_status_script(package: Mapping[str, Any], sku_code: str) -> str:
    return rf"""
(() => {{
  const packageInfo = {json.dumps(dict(package), ensure_ascii=False)};
  const skuCode = {json.dumps(sku_code, ensure_ascii=False)};
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const valuesEquivalent = (actual, expected) => {{
    const left = String(actual ?? "").trim();
    const right = String(expected ?? "").trim();
    if (left === right) return true;
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    return left !== "" && right !== "" && Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber === rightNumber;
  }};
  const readField = (id, expected) => {{
    const scope = document.querySelector(`[data-product-edit-field-unique-id="${{id}}"]`);
    const input = scope && [...scope.querySelectorAll("input,textarea")].find(visible);
    const actual = String(input?.value ?? "").trim();
    return {{ ok: valuesEquivalent(actual, expected), actual, expected: String(expected ?? "") }};
  }};
  const weight = readField("weight", packageInfo.weight_kg);
  const width = readField("dimension.width", packageInfo.width_cm);
  const length = readField("dimension.length", packageInfo.length_cm);
  const height = readField("dimension.height", packageInfo.height_cm);
  const parentSku = readField("parentSku", skuCode);
  return {{
    weight: weight.ok,
    width: width.ok,
    length: length.ok,
    height: height.ok,
    parentSku: parentSku.ok,
    values: {{ weight, width, length, height, parentSku }},
  }};
}})()
"""
