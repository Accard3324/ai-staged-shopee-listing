from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict

from ..browser.cdp_client import CdpClient, list_pages
from ..browser.context_selector import best_page_for_product_new
from ..browser.cdp_discovery import find_ziniao_cdp_candidates
from ..config_manager import PROJECT_ROOT
from ..reporting.html_snapshot import save_html_snapshot
from ..reporting.screenshot_manager import save_base64_screenshot
from .product_new_page import (
    build_autofill_payload,
    capture_screenshot_or_empty,
    enable_page_domain_if_available,
    fill_title_and_description_script,
    load_listing_draft,
)


def run_real_page_probe(
    draft_path: Path | None = None,
    fill_title_description: bool = False,
    cdp_port: int | None = None,
) -> Dict[str, Any]:
    port, pages, selected_page = select_probe_page(cdp_port)
    probe: Dict[str, Any] = {
        "cdpPort": port,
        "allPages": simplify_pages(pages),
        "selectedPage": simplify_page(selected_page),
        "fillRequested": fill_title_description,
    }
    client = CdpClient(str(selected_page.get("webSocketDebuggerUrl", "")))
    client.connect()
    try:
        client.command("Runtime.enable")
        enable_page_domain_if_available(client)
        page_probe = client.evaluate(real_page_probe_script()).get("result", {}).get("value", {})
        probe.update(page_probe)

        if fill_title_description:
            if not draft_path:
                draft_path = latest_listing_draft()
            draft = load_listing_draft(draft_path)
            payload = build_autofill_payload(draft)
            fill_result = client.evaluate(fill_title_and_description_script(payload)).get("result", {}).get("value", {})
            verify_probe = client.evaluate(real_page_probe_script()).get("result", {}).get("value", {})
            probe.update(verify_probe)
            probe["draftPath"] = str(draft_path)
            probe["fillCheck"] = {
                "title": payload.get("title", ""),
                "descriptionSample": str(payload.get("description", ""))[:200],
                "titleOk": bool(fill_result.get("titleFilled")),
                "descriptionOk": bool(fill_result.get("description", {}).get("ok")),
                "rawResult": fill_result,
            }

        html = client.html()
        screenshot = safe_capture_screenshot(client)
    finally:
        client.close()

    artifacts = save_probe_artifacts(PROJECT_ROOT, probe, html=html, screenshot_base64=screenshot)
    probe["artifacts"] = {key: str(value) for key, value in artifacts.items()}
    return probe


def select_probe_page(cdp_port: int | None = None) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    if cdp_port is None:
        candidates = find_ziniao_cdp_candidates(verify=True)
        if not candidates:
            raise RuntimeError("No verified Ziniao store-browser CDP port was found.")
        cdp_port = candidates[0].port
    pages = [page for page in list_pages(cdp_port) if page.get("type") == "page"]
    selected = best_page_for_product_new(pages)
    if not selected:
        raise RuntimeError("No Shopee Seller Centre page was found.")
    if not selected.get("webSocketDebuggerUrl"):
        raise RuntimeError("The selected Shopee page has no webSocketDebuggerUrl.")
    return cdp_port, pages, selected


def latest_listing_draft() -> Path:
    listing_dir = PROJECT_ROOT / "outputs" / "listings"
    files = sorted(listing_dir.glob("*_listing_draft.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("listing_draft.json was not found. Generate a listing draft first.")
    return files[0]


def simplify_page(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page.get("id", ""),
        "type": page.get("type", ""),
        "title": page.get("title", ""),
        "url": page.get("url", ""),
    }


def simplify_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [simplify_page(page) for page in pages]


def save_probe_artifacts(
    project_root: Path,
    probe: Dict[str, Any],
    html: str,
    screenshot_base64: str,
    stamp: str | None = None,
) -> Dict[str, Path]:
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = project_root / "outputs" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"real_page_probe_{stamp}.md"
    json_path = report_dir / f"real_page_probe_{stamp}.json"
    html_path = save_html_snapshot(html, project_root / "outputs" / "html_snapshots", "real_page_probe", stamp)
    screenshot_path = save_base64_screenshot(
        screenshot_base64,
        project_root / "outputs" / "screenshots",
        "real_page_probe",
        stamp,
    )
    artifacts = {
        "report_path": report_path,
        "json_path": json_path,
        "html_path": html_path,
        "screenshot_path": screenshot_path,
    }
    probe_with_artifacts = dict(probe)
    probe_with_artifacts["artifacts"] = {key: str(value) for key, value in artifacts.items()}
    report_path.write_text(build_probe_markdown(probe_with_artifacts), encoding="utf-8")
    json_path.write_text(json.dumps(probe_with_artifacts, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts


def safe_capture_screenshot(client: CdpClient) -> str:
    return capture_screenshot_or_empty(client)


def build_probe_markdown(probe: Dict[str, Any]) -> str:
    page = probe.get("page", {})
    selected = probe.get("selectedPage", {})
    title_candidate = first_item(probe.get("titleCandidates", []))
    fill_check = probe.get("fillCheck", {})
    quill = probe.get("quill", {})
    step1 = probe.get("step1Status", {}) if isinstance(probe.get("step1Status", {}), dict) else {}
    next_step = step1.get("nextStep", {}) if isinstance(step1.get("nextStep", {}), dict) else {}
    lines = [
        "# Shopee Real Page Probe",
        "",
        f"- Time: {datetime.now().isoformat(timespec='seconds')}",
        f"- CDP Port: {probe.get('cdpPort', '')}",
        f"- Selected Page URL: {selected.get('url', '') or page.get('url', '')}",
        f"- Selected Page Title: {selected.get('title', '') or page.get('title', '')}",
        f"- Is Seller Center: {page.get('isSellerCenter', '')}",
        f"- Is Product New Page: {page.get('isProductNewPage', '')}",
        f"- Has Captcha: {page.get('isCaptchaPage', '')}",
        f"- Has Login Issue: {page.get('isLoginPage', '')}",
        f"- Has Blocking Modal: {page.get('hasBlockingModal', '')}",
        "",
        "## Step 1 page status",
        f"- Is Step 1: {step1.get('isStep1', '')}",
        f"- Product Image Upload: {bool(step1.get('productImageUpload'))}",
        f"- Promo Image Upload: {bool(step1.get('promoImageUpload'))}",
        f"- Product Image Count: {step1.get('productImageCount', '')}",
        f"- Promo Image Count: {step1.get('promoImageCount', '')}",
        f"- Product Code Input: {bool(step1.get('productCodeInput'))}",
        f"- GTIN Input: {bool(step1.get('gtinInput'))}",
        f"- Next Step Exists: {next_step.get('exists', '')}",
        f"- Next Step Disabled: {next_step.get('disabled', '')}",
        f"- Missing Required: {json.dumps(step1.get('missingRequired', []), ensure_ascii=False)}",
        "",
        "## Live title input",
        f"- Selector: {title_candidate.get('selector', 'not found')}",
        f"- Reason: {title_candidate.get('reason', 'not found')}",
        f"- Score: {title_candidate.get('score', '')}",
        f"- Nearby Text: {title_candidate.get('nearbyText', '')}",
        "",
        "## Live Quill description editor",
        f"- Container: {quill.get('containerSelector', '')}",
        f"- Editor: {quill.get('editorSelector', '')}",
        f"- Has Quill API: {quill.get('canUseApi', '')}",
        "",
        "## Live fill verification",
        f"- Title Success: {fill_check.get('titleOk', 'not run')}",
        f"- Description Success: {fill_check.get('descriptionOk', 'not run')}",
        f"- Raw Result: {json.dumps(fill_check.get('rawResult', {}), ensure_ascii=False)}",
        "",
        "## Page recognition",
        f"- Product-title input: {bool(probe.get('titleCandidates'))}",
        f"- Description editor: {bool(quill.get('hasEditor'))}",
        f"- Image-upload area: {probe.get('imageUploadDetected', '')}",
        f"- Variation area: {probe.get('variationDetected', '')}",
        f"- Price/stock table: {probe.get('priceStockDetected', '')}",
        f"- Logistics area: {probe.get('logisticsDetected', '')}",
        "",
        "## Body Text Sample",
        str(page.get("bodyTextSample", ""))[:3000],
    ]
    return "\n".join(lines)


def first_item(items: Any) -> dict[str, Any]:
    if isinstance(items, list) and items:
        first = items[0]
        return first if isinstance(first, dict) else {}
    return {}


def real_page_probe_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const editable = el => !el.disabled && !el.readOnly;
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const shortHtml = el => norm(el.outerHTML || "").slice(0, 1200);
  const cssEscape = value => {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  };
  const selectorFor = el => {
    if (!el) return "";
    if (el.id) return `${el.tagName.toLowerCase()}#${cssEscape(el.id)}`;
    const dataId = el.getAttribute("data-product-edit-field-unique-id");
    if (dataId) return `${el.tagName.toLowerCase()}[data-product-edit-field-unique-id="${cssEscape(dataId)}"]`;
    const placeholder = el.getAttribute("placeholder");
    if (placeholder) return `${el.tagName.toLowerCase()}[placeholder="${cssEscape(placeholder)}"]`;
    const name = el.getAttribute("name");
    if (name) return `${el.tagName.toLowerCase()}[name="${cssEscape(name)}"]`;
    const parent = el.parentElement;
    if (!parent) return el.tagName.toLowerCase();
    const same = [...parent.children].filter(child => child.tagName === el.tagName);
    const index = same.indexOf(el) + 1;
    return `${selectorFor(parent)} > ${el.tagName.toLowerCase()}:nth-of-type(${index})`;
  };
  const labelText = el => {
    const labels = [];
    if (el.id) {
      const label = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (label) labels.push(label.innerText);
    }
    const direct = el.closest("label");
    if (direct) labels.push(direct.innerText);
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      for (const id of labelledBy.split(/\s+/)) {
        const item = document.getElementById(id);
        if (item) labels.push(item.innerText);
      }
    }
    let cursor = el.parentElement;
    for (let depth = 0; cursor && depth < 5; depth += 1, cursor = cursor.parentElement) {
      const label = cursor.querySelector(":scope > label,:scope .edit-label,:scope .edit-title,.eds-form-item__label,[class*='label']");
      if (label) labels.push(label.innerText);
    }
    return norm(labels.filter(Boolean).join(" | ")).slice(0, 500);
  };
  const formItem = el => el.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,.eds-form-item,[class*='form-item'],[class*='FormItem'],[data-product-edit-field-unique-id],section");
  const fieldText = el => {
    const scope = formItem(el);
    return norm([
      el.getAttribute("placeholder") || "",
      el.getAttribute("aria-label") || "",
      el.getAttribute("name") || "",
      labelText(el),
      scope ? scope.innerText : ""
    ].join(" ")).slice(0, 1200);
  };
  const likelyField = (el, kind) => {
    const text = fieldText(el).toLowerCase();
    if (/商品名称|商品标题|product name|product title|nama produk|品牌名称 \+ 商品类型/.test(text)) return "title";
    if (/description|商品描述|描述/.test(text)) return "description";
    if (/sku|variation code|seller sku|gtin/.test(text)) return "sku";
    if (/category|类别|类目/.test(text)) return "category";
    if (/brand|品牌/.test(text)) return "brand";
    if (/price|价格|stock|库存|quantity|数量/.test(text)) return "price_stock";
    if (kind === "textarea") return "textarea_unknown";
    return "unknown";
  };
  const inputInfo = (el, index) => {
    const rect = el.getBoundingClientRect();
    return {
      index,
      selector: selectorFor(el),
      outerHTML: shortHtml(el),
      type: el.getAttribute("type") || "",
      placeholder: el.getAttribute("placeholder") || "",
      value: el.value || "",
      disabled: !!el.disabled,
      readonly: !!el.readOnly,
      ariaLabel: el.getAttribute("aria-label") || "",
      className: String(el.className || "").slice(0, 300),
      name: el.getAttribute("name") || "",
      id: el.id || "",
      nearestLabel: labelText(el),
      formItemText: fieldText(el),
      top: Math.round(rect.top + window.scrollY),
      editable: editable(el),
      likelyField: likelyField(el, "input")
    };
  };
  const textareaInfo = (el, index) => {
    const rect = el.getBoundingClientRect();
    const info = inputInfo(el, index);
    return {
      ...info,
      top: Math.round(rect.top + window.scrollY),
      likelyField: likelyField(el, "textarea"),
      mayBeSkuCode: /sku|variation code|seller sku/i.test(fieldText(el)),
      mayBeDescription: /description|商品描述|描述/i.test(fieldText(el))
    };
  };
  const visibleInputs = [...document.querySelectorAll("input")].filter(visible).map(inputInfo);
  const visibleTextareas = [...document.querySelectorAll("textarea")].filter(visible).map(textareaInfo);
  const titleKeywords = ["商品名称", "商品标题", "Product Name", "Product Title", "Basic Information", "Product Info", "Nama Produk"];
  const titlePlaceholders = ["请输入商品名称", "请输入商品标题", "Please enter product name", "Enter product name", "Product name", "品牌名称 + 商品类型"];
  const hasTitleSignal = text => titleKeywords.some(keyword => text.includes(keyword)) || titlePlaceholders.some(keyword => text.includes(keyword));
  const titleRegions = [...document.querySelectorAll("label,div,section,span")]
    .filter(visible)
    .map(el => ({ selector: selectorFor(el), text: norm(el.innerText), outerHTML: shortHtml(el) }))
    .filter(item => item.text.length <= 2500 && titleKeywords.some(keyword => item.text.includes(keyword)))
    .slice(0, 20);
  const badTitleText = /category|类别|类目|brand id|品牌 ID|sku|gtin|price|价格|stock|库存|quantity|数量|重量|weight|dimension|尺寸|search|搜索|关键字/i;
  const titleCandidates = visibleInputs.map(input => {
    const text = input.formItemText;
    let score = -1;
    const reasons = [];
    if (input.editable && ["", "text"].includes(String(input.type || "").toLowerCase())) {
      if (/商品名称|商品标题|Product Name|Product Title|Nama Produk/.test(text)) {
        score = 100;
        reasons.push("field text has title label");
      }
      if (titlePlaceholders.some(keyword => text.includes(keyword))) {
        score = Math.max(score, 110);
        reasons.push("placeholder has title text");
      }
      if (badTitleText.test(text) && !hasTitleSignal(text)) {
        score = -1;
        reasons.push("rejected by non-title text");
      }
    }
    return { ...input, score, reason: reasons.join("; "), nearbyText: text };
  }).filter(item => item.score >= 0).sort((a, b) => b.score - a.score);
  const quillContainer = document.querySelector(".ql-container");
  const quillEditor = document.querySelector(".ql-editor");
  const bodyText = norm(document.body && document.body.innerText || "");
  const dialogs = [...document.querySelectorAll("[role='dialog'],.eds-modal__box,.shopee-modal,.modal")]
    .filter(visible)
    .map(el => ({ selector: selectorFor(el), text: norm(el.innerText).slice(0, 500), outerHTML: shortHtml(el) }));
  const stepScopeText = el => norm((el.closest(".edit-row,[class*='edit-row'],.product-edit-form-item,.eds-form-item,[class*='form-item'],section,div") || {}).innerText || "");
  const fileInputs = [...document.querySelectorAll("input[type=file]")].map((input, index) => ({
    index,
    selector: selectorFor(input),
    accept: input.accept || "",
    multiple: !!input.multiple,
    visible: visible(input),
    scopeText: stepScopeText(input)
  }));
  const productImageUpload = fileInputs.find(item => item.multiple && /商品图片|添加图片|1:1 图片|Product Images|Add image/i.test(item.scopeText)) || fileInputs.find(item => item.multiple) || null;
  const promoImageUpload = fileInputs.find(item => !item.multiple && /促销活动图片|Promotion Image|Promotional image/i.test(item.scopeText)) || null;
  const buttons = [...document.querySelectorAll("button")].filter(visible);
  const nextButton = buttons.find(button => norm(button.innerText) === "Next Step") || null;
  const imageCountText = bodyText.match(/添加图片\s*\((\d+)\s*\/\s*9\)/);
  const promoCountText = bodyText.match(/促销活动图片\s*\((\d+)\s*\/\s*1\)/);
  const productImageScope = document.querySelector('[data-product-edit-field-unique-id="images"]');
  const promoImageScope = document.querySelector('[data-product-edit-field-unique-id="promotionImages"]');
  const countUploadedImages = scope => scope
    ? [...scope.querySelectorAll("img")].filter(img => visible(img) && img.src && !img.src.startsWith("data:image/svg")).length
    : 0;
  const productImageCount = imageCountText ? Number(imageCountText[1]) : countUploadedImages(productImageScope);
  const promoImageCount = promoCountText ? Number(promoCountText[1]) : countUploadedImages(promoImageScope);
  const titleInput = [...document.querySelectorAll("input")].find(input => /商品名称|商品标题|品牌名称 \+ 商品类型|Product Name|Product Title|Nama Produk/i.test(fieldText(input))) || null;
  const productCodeInput = [...document.querySelectorAll("input")].find(input => /商品代码|Product Code|Seller SKU/i.test(fieldText(input)) && !/GTIN|通用商品代码|Global Trade Item Number/i.test(fieldText(input))) || null;
  const gtinInput = [...document.querySelectorAll("input")].find(input => /GTIN|通用商品代码|Global Trade Item Number/i.test(fieldText(input))) || null;
  const titleFilled = !!(titleInput && norm(titleInput.value));
  const missingRequired = [];
  if (!productImageCount) missingRequired.push("商品图片");
  if (!titleFilled) missingRequired.push("商品名称");
  if (nextButton && nextButton.disabled) missingRequired.push("Next Step disabled");
  const step1Status = {
    isStep1: /新增商品|Basic Information|Product Information/i.test(bodyText) && !!nextButton && !quillEditor,
    productImageUpload,
    promoImageUpload,
    titleInput: titleInput ? { value: titleInput.value || "", placeholder: titleInput.placeholder || "" } : null,
    productCodeInput: productCodeInput ? { value: productCodeInput.value || "", placeholder: productCodeInput.placeholder || "" } : null,
    gtinInput: gtinInput ? { value: gtinInput.value || "", placeholder: gtinInput.placeholder || "" } : null,
    productImageCount,
    promoImageCount,
    loadingSlots: [...document.querySelectorAll(".image-loading,.error-container,[class*='loading'],[class*='error-container']")].filter(visible).length,
    nextStep: nextButton ? { exists: true, disabled: !!nextButton.disabled, text: norm(nextButton.innerText) } : { exists: false, disabled: true, text: "" },
    missingRequired,
    fileInputs
  };
  return {
    page: {
      url: location.href,
      title: document.title,
      lang: document.documentElement.lang || "",
      isSellerCenter: location.href.includes("seller.shopee.com.my"),
      isProductNewPage: location.href.includes("/portal/product/new"),
      isLoginPage: /login|登录|Sign In|Log In/i.test(location.href + " " + bodyText.slice(0, 1000)),
      isCaptchaPage: /verify\/captcha|verify\/traffic|captcha|读取时出现问题|再试一次/i.test(location.href + " " + bodyText.slice(0, 1000)),
      hasBlockingModal: dialogs.length > 0,
      bodyTextSample: bodyText.slice(0, 3000)
    },
    visibleInputs,
    visibleTextareas,
    titleRegions,
    titleCandidates,
    quill: {
      hasContainer: !!quillContainer,
      hasEditor: !!quillEditor,
      canUseApi: !!(quillContainer && quillContainer.__quill),
      containerSelector: selectorFor(quillContainer),
      editorSelector: selectorFor(quillEditor),
      editorTextLength: quillEditor ? norm(quillEditor.innerText).length : 0,
      editorTextSample: quillEditor ? norm(quillEditor.innerText).slice(0, 500) : ""
    },
    dialogs,
    step1Status,
    imageUploadDetected: /image|图片|照片|上传图片|Add image/i.test(bodyText),
    variationDetected: /variation|规格|变体|Sales Information/i.test(bodyText),
    priceStockDetected: /price|stock|价格|库存/i.test(bodyText),
    logisticsDetected: /shipping|物流|运费/i.test(bodyText)
  };
})()
"""
