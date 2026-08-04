from __future__ import annotations

from pathlib import Path
import time
from typing import Iterable, List

from ...browser.cdp_client import CdpClient


IMAGE_UPLOAD_STATUS_SCRIPT = """
(() => ({
  uploadedImages: document.querySelectorAll(".shopee-image-manager__image,img[src]").length,
  loadingSlots: document.querySelectorAll(".image-loading,.error-container").length
}))()
"""


def step1_status_script() -> str:
    return """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const selectorFor = el => {
    if (!el) return "";
    const field = el.getAttribute("data-product-edit-field-unique-id");
    if (field) return `${el.tagName.toLowerCase()}[data-product-edit-field-unique-id="${field}"]`;
    const parent = el.parentElement;
    if (!parent) return el.tagName.toLowerCase();
    const same = [...parent.children].filter(item => item.tagName === el.tagName);
    return `${selectorFor(parent)} > ${el.tagName.toLowerCase()}:nth-of-type(${same.indexOf(el) + 1})`;
  };
  const scopeText = el => norm((el.closest(".edit-row,[class*='edit-row'],section,div") || {}).innerText || "");
  const fileInputs = [...document.querySelectorAll("input[type=file]")].map((input, index) => ({
    index,
    selector: selectorFor(input),
    accept: input.accept || "",
    multiple: !!input.multiple,
    visible: visible(input),
    scopeText: scopeText(input)
  }));
  const productImageUpload = fileInputs.find(item => item.multiple && /商品图片|添加图片|1:1 图片/.test(item.scopeText)) || fileInputs.find(item => item.multiple);
  const promoImageUpload = fileInputs.find(item => !item.multiple && /促销活动图片/.test(item.scopeText));
  const buttons = [...document.querySelectorAll("button")].filter(visible);
  const nextButton = buttons.find(button => norm(button.innerText) === "Next Step");
  const imageCountText = document.body.innerText.match(/添加图片\\s*\\((\\d+)\\s*\\/\\s*9\\)/);
  const promoCountText = document.body.innerText.match(/促销活动图片\\s*\\((\\d+)\\s*\\/\\s*1\\)/);
  const productImageScope = document.querySelector('[data-product-edit-field-unique-id="images"]');
  const promoImageScope = document.querySelector('[data-product-edit-field-unique-id="promotionImages"]');
  const countUploadedImages = scope => scope
    ? [...scope.querySelectorAll("img")].filter(img => visible(img) && img.src && !img.src.startsWith("data:image/svg")).length
    : 0;
  const productImageCount = imageCountText ? Number(imageCountText[1]) : countUploadedImages(productImageScope);
  const promoImageCount = promoCountText ? Number(promoCountText[1]) : countUploadedImages(promoImageScope);
  const titleInput = [...document.querySelectorAll("input")].find(input => /商品名称|品牌名称 \\+ 商品类型/.test(scopeText(input) + " " + (input.placeholder || "")));
  const productCodeInput = [...document.querySelectorAll("input")].find(input => /商品代码/.test(scopeText(input)) && !/GTIN|通用商品代码/.test(scopeText(input) + " " + (input.placeholder || "")));
  const gtinInput = [...document.querySelectorAll("input")].find(input => /GTIN|通用商品代码/.test(scopeText(input) + " " + (input.placeholder || "")));
  const titleFilled = !!(titleInput && norm(titleInput.value));
  const missingRequired = [];
  if (!productImageCount) missingRequired.push("商品图片");
  if (!titleFilled) missingRequired.push("商品名称");
  if (nextButton && nextButton.disabled) missingRequired.push("Next Step disabled");
  return {
    isStep1: /新增商品/.test(document.body.innerText) && !!nextButton && !document.querySelector(".ql-editor"),
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
})()
"""


def set_file_input_files(client: CdpClient, input_index: int, files: Iterable[str]) -> None:
    file_list = [str(Path(path)) for path in files]
    if not file_list:
        raise RuntimeError("No uploadable image files were provided.")
    for path in file_list:
        if not Path(path).is_file():
            raise RuntimeError(f"Image file not found: {path}")
    client.command("DOM.enable")
    root = client.command("DOM.getDocument", {"depth": -1, "pierce": True}).get("root", {})
    node_ids = client.command("DOM.querySelectorAll", {"nodeId": root.get("nodeId"), "selector": "input[type=file]"}).get(
        "nodeIds", []
    )
    if input_index >= len(node_ids):
        raise RuntimeError(f"Image upload input {input_index} was not found.")
    client.command("DOM.setFileInputFiles", {"nodeId": node_ids[input_index], "files": file_list})


def wait_for_promo_image(client: CdpClient, minimum_count: int = 1, timeout_seconds: int = 30) -> dict:
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        last = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
        if int(last.get("promoImageCount") or 0) >= minimum_count and int(last.get("loadingSlots") or 0) == 0:
            return last
        time.sleep(1)
    raise RuntimeError(f"The promotional image did not finish uploading or still reports loading/error: {last}")


def wait_for_product_images(client: CdpClient, minimum_count: int, timeout_seconds: int = 45) -> dict:
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        last = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
        if int(last.get("productImageCount") or 0) >= minimum_count and int(last.get("loadingSlots") or 0) == 0:
            return last
        time.sleep(1)
    raise RuntimeError(f"Image upload did not finish or still reports loading/error: {last}")


def upload_step1_product_images(client: CdpClient, image_paths: List[str], max_images: int = 9) -> dict:
    status = client.evaluate(step1_status_script()).get("result", {}).get("value", {})
    upload = status.get("productImageUpload") or {}
    if upload.get("index") is None:
        raise RuntimeError(f"The product-image upload control was not found: {status}")
    selected = image_paths[:max_images]
    before = int(status.get("productImageCount") or 0)
    set_file_input_files(client, int(upload["index"]), selected)
    return wait_for_product_images(client, before + len(selected))
