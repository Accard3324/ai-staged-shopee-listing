from __future__ import annotations


def step2_probe_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const editable = el => !el.disabled && !el.readOnly;
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const cssEscape = value => {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  };
  const selectorFor = el => {
    if (!el) return "";
    if (el.id) return `${el.tagName.toLowerCase()}#${cssEscape(el.id)}`;
    const field = el.getAttribute("data-product-edit-field-unique-id");
    if (field) return `${el.tagName.toLowerCase()}[data-product-edit-field-unique-id="${cssEscape(field)}"]`;
    const placeholder = el.getAttribute("placeholder");
    if (placeholder) return `${el.tagName.toLowerCase()}[placeholder="${cssEscape(placeholder)}"]`;
    const parent = el.parentElement;
    if (!parent) return el.tagName.toLowerCase();
    const same = [...parent.children].filter(item => item.tagName === el.tagName);
    return `${selectorFor(parent)} > ${el.tagName.toLowerCase()}:nth-of-type(${same.indexOf(el) + 1})`;
  };
  const scopeText = el => norm((el.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,.eds-form-item,[class*='form-item'],section,[data-product-edit-field-unique-id],div") || {}).innerText || "");
  const fieldText = el => norm([
    el.getAttribute("placeholder") || "",
    el.getAttribute("aria-label") || "",
    el.getAttribute("name") || "",
    scopeText(el)
  ].join(" ")).slice(0, 1200);
  const inputInfo = (el, index) => {
    const rect = el.getBoundingClientRect();
    return {
      index,
      selector: selectorFor(el),
      type: el.getAttribute("type") || "",
      placeholder: el.getAttribute("placeholder") || "",
      value: el.value || "",
      disabled: !!el.disabled,
      readonly: !!el.readOnly,
      editable: editable(el),
      fieldText: fieldText(el),
      top: Math.round(rect.top + window.scrollY)
    };
  };
  const buttonInfo = (el, index) => {
    const rect = el.getBoundingClientRect();
    return {
      index,
      selector: selectorFor(el),
      text: norm(el.innerText),
      disabled: !!el.disabled || String(el.className || "").includes("disabled"),
      top: Math.round(rect.top + window.scrollY)
    };
  };
  const bodyText = norm(document.body && document.body.innerText || "");
  const has = regex => regex.test(bodyText);
  const quillContainer = document.querySelector(".ql-container");
  const quillEditor = document.querySelector(".ql-editor");
  const visibleInputs = [...document.querySelectorAll("input")].filter(visible).map(inputInfo);
  const visibleTextareas = [...document.querySelectorAll("textarea")].filter(visible).map(inputInfo);
  const visibleButtons = [...document.querySelectorAll("button")].filter(visible).map(buttonInfo);
  const dataFields = [...document.querySelectorAll("[data-product-edit-field-unique-id]")]
    .filter(visible)
    .map(el => ({
      selector: selectorFor(el),
      id: el.getAttribute("data-product-edit-field-unique-id") || "",
      text: norm(el.innerText).slice(0, 500)
    }));
  const categoryRows = [...document.querySelectorAll(".category-select-row,[class*='category-select-row']")]
    .filter(visible)
    .map((row, index) => {
      const textEl = row.querySelector(".category-select-row-text,[class*='category-select-row-text']");
      const text = norm((textEl || row).innerText);
      const rect = row.getBoundingClientRect();
      return {
        index,
        selector: selectorFor(row),
        text,
        top: Math.round(rect.top + window.scrollY)
      };
    })
    .filter(item => item.text && item.text.includes(">"));
  const skuTextareas = visibleTextareas.filter(item => /sku|item code|seller sku|商品货号|货号|商品代码/i.test(item.fieldText));
  const step2Status = {
    isStep2: !!quillEditor || has(/Category|类目|类别|Brand|品牌|Description|商品描述|Sales Information|销售资料|variation|规格|物流|Shipping/i),
    category: has(/Category|类目|类别/i) || dataFields.some(item => /category/i.test(item.id)),
    brand: has(/Brand|品牌/i) || dataFields.some(item => /brand/i.test(item.id)),
    attributes: has(/Attributes|属性|Shelf Life|保质期|Formula|配方/i),
    description: { hasQuill: !!quillEditor, hasContainer: !!quillContainer, textLength: quillEditor ? norm(quillEditor.innerText).length : 0 },
    categoryLocked: bodyText.includes("在您选择商品分类后更新") || /after you select a category/i.test(bodyText),
    video: has(/Video|视频|商品影片|上传影片/i),
    variation: has(/variation|规格|变体|Sales Information|销售资料/i),
    price: has(/Price|价格|RM/i),
    stock: has(/Stock|库存|Quantity|数量/i),
    skuItemCode: skuTextareas.length > 0 || has(/Seller SKU|Item Code|商品货号|货号/i),
    weightDimension: has(/Weight|重量|Dimension|尺寸|包裹/i),
    logistics: has(/Shipping|物流|Doorstep|运费/i),
    buttons: {
      nextStep: visibleButtons.some(item => item.text === "Next Step"),
      previous: visibleButtons.some(item => /Previous|上一步|返回/i.test(item.text)),
      save: visibleButtons.some(item => /^Save$|保存|储存/i.test(item.text)),
      saveDelist: visibleButtons.some(item => /储存并下架|Save and Delist/i.test(item.text))
    }
  };
  const locatorPlan = {
    category: "Use data-product-edit-field-unique-id containing category or a localized Category label; inspect options before choosing.",
    brand: "Use product-brand-item or data-product-edit-field-unique-id containing brand; prefer exact recommended tag, then exact dropdown option.",
    description: "Use .ql-container.__quill and verify .ql-editor.innerText; never use generic textarea.",
    skuItemCode: "Treat textareas near SKU/item-code labels as item-code fields, not description.",
    variation: "Scope to tierVariation_0 if variation is enabled later.",
    logistics: "Inspect visible product-shipping panel after weight and dimensions are present."
  };
  return {
    page: {
      url: location.href,
      title: document.title,
      isSellerCenter: location.href.includes("seller.shopee.com.my"),
      isProductNewPage: location.href.includes("/portal/product/new"),
      isLoginPage: /login|登录|Sign In|Log In/i.test(location.href + " " + bodyText.slice(0, 1000)),
      isCaptchaPage: /verify\/captcha|verify\/traffic|captcha|读取时出现问题|再试一次/i.test(location.href + " " + bodyText.slice(0, 1000)),
      bodyTextSample: bodyText.slice(0, 5000)
    },
    step2Status,
    categoryCandidates: categoryRows,
    dataFields,
    visibleInputs,
    visibleTextareas,
    visibleButtons,
    locatorPlan
  };
})()
"""
