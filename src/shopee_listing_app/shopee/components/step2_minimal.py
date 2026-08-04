from __future__ import annotations

import json


def brand_mouse_probe_script(brand: str) -> str:
    return f"""
(() => {{
  const targetBrand = {json.dumps(brand, ensure_ascii=False)};
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const rectInfo = el => {{
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return {{
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height
    }};
  }};
  const brandScope = document.querySelector(".product-brand-item");
  const selector = brandScope ? brandScope.querySelector(".eds-selector") : null;
  const scopeText = brandScope ? norm(brandScope.innerText) : "";
  const selected = !!targetBrand && scopeText.includes(targetBrand) && !/请选择|Please select/i.test(scopeText);
  const optionCandidates = [...document.querySelectorAll(".eds-option,[role='option'],.eds-select-popover-content .eds-option")]
    .filter(visible)
    .map(el => ({{ el, text: norm(el.innerText), rect: rectInfo(el) }}))
    .filter(item => item.text && item.rect);
  const exactOption = optionCandidates.find(item => item.text === targetBrand) || null;
  const noBrandOption = optionCandidates.find(item => /^No\\s*Brand$|^NoBrand$/i.test(item.text)) || null;
  const recommended = [...document.querySelectorAll(".brand-rcmd-box__item")]
    .filter(visible)
    .find(el => norm(el.innerText) === targetBrand) || null;
  if (recommended) recommended.scrollIntoView({{ block: "center", inline: "nearest" }});
  return {{
    ok: !!brandScope,
    targetBrand,
    scopeText,
    selected,
    selectorRect: rectInfo(selector),
    recommendedOption: recommended ? {{ text: norm(recommended.innerText), rect: rectInfo(recommended) }} : null,
    exactOption: exactOption ? {{ text: exactOption.text, rect: exactOption.rect }} : null,
    noBrandOption: noBrandOption ? {{ text: noBrandOption.text, rect: noBrandOption.rect }} : null,
    optionCandidates: optionCandidates.slice(0, 30).map(item => item.text)
  }};
}})()
"""


def health_certification_probe_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const rectInfo = el => {
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, width: rect.width, height: rect.height };
  };
  const scopes = [...document.querySelectorAll(".attribute-select-item")];
  const scope = document.querySelector(".product-attribute-item-100966")?.closest(".attribute-select-item")
    || scopes.find(item => /卫生部认证|Ministry of Health Certification/i.test(norm(item.innerText)));
  if (!scope) return { ok: false, reason: "health certification field not found" };
  const selector = scope.querySelector(".eds-selector");
  if (selector) selector.scrollIntoView({ block: "center", inline: "nearest" });
  const scopeText = norm(scope.innerText);
  const selectedNo = /卫生部认证\s*(否|No)\b/i.test(scopeText) || (!/请选择|Please select/i.test(scopeText) && /(^|\s)(否|No)($|\s)/i.test(scopeText));
  const optionCandidates = [...document.querySelectorAll(".eds-option,[role='option'],.eds-select-popover-content li,.eds-select-popover-content div")]
    .filter(visible)
    .map(el => ({ el, text: norm(el.innerText), rect: rectInfo(el.closest(".eds-option,[role='option'],li") || el) }))
    .filter(item => item.text && item.rect);
  const noOption = optionCandidates.find(item => /^(否|No)$/i.test(item.text)) || null;
  return {
    ok: true,
    scopeText,
    selectedNo,
    selectorRect: rectInfo(selector),
    noOption: noOption ? { text: noOption.text, rect: noOption.rect } : null,
    options: optionCandidates.slice(0, 20).map(item => item.text)
  };
})()
"""


def brand_fill_script(brand: str) -> str:
    return f"""
(async () => {{
  const targetBrand = {json.dumps(brand, ensure_ascii=False)};
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const brandScope = document.querySelector(".product-brand-item");
  if (!targetBrand) return {{ ok: false, reason: "brand is empty" }};
  if (!brandScope) return {{ ok: false, reason: "brand field not found" }};
  if (/^No\\s*Brand$|^NoBrand$/i.test(norm(brandScope.innerText))) {{
    return {{
      ok: true,
      action: "already_selected_no_brand",
      requestedBrand: targetBrand,
      value: "NoBrand",
      exactBrandAvailable: false,
      scopeText: norm(brandScope.innerText).slice(0, 300)
    }};
  }}
  if (norm(brandScope.innerText).includes(targetBrand) && !/请选择|Please select/i.test(norm(brandScope.innerText))) {{
    return {{ ok: true, action: "already_selected", value: targetBrand, scopeText: norm(brandScope.innerText).slice(0, 300) }};
  }}
  const brandContainer = brandScope.closest(".attribute-select-item") || brandScope.parentElement || brandScope;
  const recommended = [...brandContainer.querySelectorAll(".brand-rcmd-box__item")]
    .filter(visible)
    .find(el => norm(el.innerText) === targetBrand)
    || [...brandContainer.querySelectorAll("button,span,div")]
      .filter(visible)
      .find(el => norm(el.innerText) === targetBrand);
  if (recommended) {{
    recommended.scrollIntoView({{ block: "center", inline: "nearest" }});
    recommended.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true }}));
    recommended.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true }}));
    recommended.click();
    await sleep(1500);
    if (norm(brandScope.innerText).includes(targetBrand) && !/请选择|Please select/i.test(norm(brandScope.innerText))) {{
      return {{ ok: true, action: "clicked_recommended_brand", value: targetBrand, scopeText: norm(brandScope.innerText).slice(0, 300) }};
    }}
  }}
  const selector = brandScope.querySelector(".eds-selector");
  if (!selector) {{
    return {{ ok: false, reason: "brand selector not found", value: targetBrand, scopeText: norm(brandScope.innerText).slice(0, 500) }};
  }}
  selector.scrollIntoView({{ block: "center", inline: "nearest" }});
  await sleep(200);
  selector.click();
  selector.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true }}));
  selector.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true }}));
  selector.dispatchEvent(new MouseEvent("click", {{ bubbles: true }}));
  await sleep(1500);
  const optionCandidates = [...document.querySelectorAll(".eds-select-popover-content li,.eds-select-popover-content div,.eds-option,[role='option'],li")]
    .filter(visible)
    .map(el => ({{ el, clickTarget: el.closest("li,[role='option'],.eds-option") || el, text: norm(el.innerText) }}))
    .filter(item => item.text);
  const clickOption = async item => {{
    item.clickTarget.scrollIntoView({{ block: "center", inline: "nearest" }});
    await sleep(100);
    item.clickTarget.click();
    item.clickTarget.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true }}));
    item.clickTarget.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true }}));
    item.clickTarget.dispatchEvent(new MouseEvent("click", {{ bubbles: true }}));
  }};
  const option = optionCandidates.find(item => item.text === targetBrand);
  if (option) {{
    await clickOption(option);
    await sleep(800);
    if (norm(brandScope.innerText).includes(targetBrand) && !/请选择|Please select/i.test(norm(brandScope.innerText))) {{
      return {{ ok: true, action: "selected_exact_dropdown_option", value: targetBrand, scopeText: norm(brandScope.innerText).slice(0, 300) }};
    }}
  }}
  const noBrand = optionCandidates.find(item => /^No\\s*Brand$|^NoBrand$/i.test(item.text));
  if (noBrand) {{
    await clickOption(noBrand);
    await sleep(800);
    if (/No\\s*Brand|NoBrand/i.test(norm(brandScope.innerText))) {{
      return {{
        ok: true,
        action: "selected_no_brand_fallback",
        requestedBrand: targetBrand,
        value: "NoBrand",
        exactBrandAvailable: false,
        scopeText: norm(brandScope.innerText).slice(0, 300)
      }};
    }}
  }}
  return {{
    ok: false,
    reason: "brand exact option not found",
    value: targetBrand,
    scopeText: norm(brandScope.innerText).slice(0, 300),
    optionCandidates: optionCandidates.slice(0, 20).map(item => item.text)
  }};
}})()
"""


def description_fill_script(description: str) -> str:
    return rf"""
(() => {{
  const descriptionText = {json.dumps(description, ensure_ascii=False)};
  const normalized = descriptionText.replace(/\n{{2,}}/g, "\n").trim();
  const container = document.querySelector(".ql-container");
  const editor = document.querySelector(".ql-editor");
  if (!container && !editor) return {{ ok: false, reason: "Quill editor not found" }};
  if (container && container.__quill) {{
    container.__quill.setText(normalized, "user");
  }} else {{
    editor.innerText = normalized;
    editor.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: normalized }}));
    editor.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}
  const ql = document.querySelector(".ql-editor");
  const text = ql ? ql.innerText || "" : "";
  const html = ql ? ql.innerHTML || "" : "";
  const blanks = (html.match(/<p><br><\/p>/g) || []).length;
  const firstLine = normalized.split("\n").find(Boolean) || normalized.slice(0, 30);
  const skuTextareas = [...document.querySelectorAll("textarea")]
    .map(textarea => {{
      const scopeText = ((textarea.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,.eds-form-item,[class*='form-item'],section,div") || {{}}).innerText || "").replace(/\s+/g, " ").trim();
      return {{ value: textarea.value || "", scopeText }};
    }})
    .filter(item => /sku|item code|seller sku|商品货号|货号|商品代码/i.test(item.scopeText));
  const contaminatedSkuTextareas = skuTextareas.filter(item => item.value.includes(firstLine) || /Greetings, Valued Shopper|Product Highlights|Welcome to our store/i.test(item.value));
  return {{
    ok: text.includes(firstLine) && blanks === 0 && contaminatedSkuTextareas.length === 0,
    length: text.length,
    noBlankParagraphs: blanks === 0,
    skuTextareas,
    contaminatedSkuTextareas,
    hasTemplateAnchor: /Greetings, Valued Shopper|Welcome|After-Sales|Order/.test(text)
  }};
}})()
"""


def title_restore_and_cleanup_script(title: str, brand: str) -> str:
    return f"""
(() => {{
  const targetTitle = {json.dumps(title, ensure_ascii=False)};
  const cleanupBrand = {json.dumps(brand, ensure_ascii=False)};
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const setInputValue = (el, value) => {{
    el.focus();
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (descriptor && descriptor.set) descriptor.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: value ? "insertText" : "deleteContentBackward", data: value }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    el.blur();
  }};
  const titleScope = document.querySelector("[data-product-edit-field-unique-id='name']");
  const titleInput = titleScope ? titleScope.querySelector("input") : null;
  let titleOk = true;
  if (targetTitle && titleInput && visible(titleInput) && norm(titleInput.value) !== norm(targetTitle)) {{
    setInputValue(titleInput, targetTitle);
    titleOk = norm(titleInput.value) === norm(targetTitle);
  }} else if (targetTitle && !titleInput) {{
    titleOk = false;
  }}
  const attributeScope = document.querySelector("[data-product-edit-field-unique-id='brandAndAttributes']");
  const clearedAttributeInputs = attributeScope ? [...attributeScope.querySelectorAll("input")]
    .filter(input => visible(input) && !input.closest(".product-brand-item") && input.value === cleanupBrand)
    .map(input => {{
      const placeholder = input.placeholder || "";
      setInputValue(input, "");
      return placeholder;
    }}) : [];
  return {{
    titleOk,
    titleValue: titleInput ? titleInput.value || "" : "",
    clearedAttributeInputs
  }};
}})()
"""


def step2_minimal_fill_script(brand: str, description: str, title: str = "") -> str:
    return f"""
(async () => {{
  const cleanup = {title_restore_and_cleanup_script(title, brand)};
  const brandResult = await {brand_fill_script(brand)};
  const description = {description_fill_script(description)};
  return {{
    ok: !!description.ok && !!cleanup.titleOk && !!brandResult.ok,
    cleanup,
    brandResult,
    description,
    note: "Step 2 minimal loop only fills brand and Quill description; no variation, price, stock, logistics, or final save."
  }};
}})()
"""
