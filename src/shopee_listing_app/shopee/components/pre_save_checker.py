from __future__ import annotations


PRE_SAVE_CHECK_SCRIPT = r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const text = document.body.innerText || "";
  const ql = document.querySelector(".ql-editor");
  const table = document.querySelector(".variation-model-table-container");
  const shipScope = document.querySelector(".product-shipping,[data-product-edit-field-unique-id='logistic']");
  const ship = shipScope?.innerText || "";
  const imageCountText = text.match(/添加图片\s*\((\d+)\s*\/\s*9\)/);
  const productImageScope = document.querySelector('[data-product-edit-field-unique-id="images"]');
  const imageNodes = [
    ...(productImageScope?.querySelectorAll(
      ".shopee-image-manager__image,.image-manager__image,.product-image img,.image-card img,[class*='image-manager'] img"
    ) || [])
  ].filter(node => {
    const src = String(node.currentSrc || node.src || node.getAttribute("data-src") || "").trim();
    return visible(node)
      && !node.closest('.variation-model-table-container,.variation-image-manager,[data-product-edit-field-unique-id="promotionImages"]')
      && !!src
      && !src.startsWith("data:");
  });
  const imageCount = imageCountText ? Number(imageCountText[1]) : imageNodes.length;
  const imageManagerText = imageNodes.map(node => {
    const manager = node.closest(".shopee-image-manager__image,.image-manager__image,.product-image,.image-card,[class*='image-manager']");
    return norm(manager?.innerText || node.getAttribute("alt") || node.getAttribute("title") || "");
  }).filter(Boolean).join(" ");
  const unsafeImageSignals = /OEM|ODM|factory|wholesale|supplier|dropship|招募|招商|供货|代理|批发/i.test(imageManagerText);
  const fileInputs = [...document.querySelectorAll('input[type="file"]')];
  const videoInput = fileInputs.find(input => /video|mp4/i.test(input.accept || ""));
  const videoScope = document.querySelector('[data-product-edit-field-unique-id="video"]')
    || videoInput?.closest(".edit-row,[class*='edit-row'],section");
  const videoText = norm(videoScope?.innerText || "");
  const videoPreviewCount = videoScope
    ? [...videoScope.querySelectorAll("video,.video-container img,[class*='video-preview'] img,[class*='video-cover'] img")].filter(visible).length
    : 0;
  const videoProgress = videoText.match(/(?:^|\s)(\d{1,3})%(?:\s|$)/);
  const videoProcessing = /上传中|处理中|正在处理|Uploading|Processing/i.test(videoText) || !!(videoProgress && Number(videoProgress[1]) < 100);
  const videoFailed = /上传失败|处理失败|格式错误|Upload failed|Processing failed|Invalid video/i.test(videoText);
  const videoUploaded = !!videoScope && !videoFailed && !videoProcessing && videoPreviewCount > 0 && /\b\d{2}:\d{2}\b/.test(videoText);
  const videoOk = !videoScope || videoUploaded;
  const healthScope = document.querySelector(".product-attribute-item-100966")?.closest(".attribute-select-item")
    || [...document.querySelectorAll(".attribute-select-item")].find(item => /卫生部认证|Ministry of Health Certification/i.test(norm(item.innerText)));
  const healthText = norm(healthScope?.innerText || "");
  // Treat an absent field as acceptable because some categories do not display it.
  const healthCertificationNo = !healthScope || (!!healthScope && /卫生部认证\s*(否|No)(?:\s|$)/i.test(healthText));
  const variationRows = table
    ? [...table.querySelectorAll(".variation-model-table-fixed-left .variation-model-table-body .table-cell-wrapper")]
        .filter(visible)
        .map(row => ({ row, text: norm(row.innerText), top: row.getBoundingClientRect().top }))
        .filter(item => /\/[123]box/i.test(item.text))
    : [];
  const variationDataRows = table
    ? [...table.querySelectorAll(".variation-model-table-middle-scroll .variation-model-table-body .second-variation-wrapper")]
        .filter(visible)
        .map(row => ({ row, top: row.getBoundingClientRect().top }))
    : [];
  const nearestDataRow = labelRow => variationDataRows
    .slice()
    .sort((a, b) => Math.abs(a.top - labelRow.top) - Math.abs(b.top - labelRow.top))[0]?.row;
  const visibleInputs = [...document.querySelectorAll("input")].filter(visible);
  const optionTexts = visibleInputs.map(input => input.value || "").filter(value => /\/[123]box$/i.test(value));
  const hasThreeVariationRows = variationRows.length >= 3 || optionTexts.length >= 3;
  const hasRealVisibleImage = row => [...row.querySelectorAll(".variation-image-manager img,.variation-image-manager .shopee-image-manager__image,img")]
    .some(image => {
      const src = String(image.currentSrc || image.src || image.getAttribute("data-src") || "").trim();
      const rect = image.getBoundingClientRect();
      return visible(image) && !!src && !src.startsWith("data:") && rect.width >= 20 && rect.height >= 20;
    });
  const variationImageFor = suffix => {
    const row = variationRows.find(item => new RegExp("/" + suffix + "box", "i").test(item.text));
    return !!row && hasRealVisibleImage(row.row);
  };
  const variation_image_1box = variationImageFor("1");
  const variation_image_2box = variationImageFor("2");
  const variation_image_3box = variationImageFor("3");
  const variationImagesOk = variation_image_1box && variation_image_2box && variation_image_3box;
  const rowScopes = variationRows.map(item => nearestDataRow(item)).filter(Boolean);
  const valuesIn = (scope, selector) => [...scope.querySelectorAll(selector)].filter(visible).map(el => String(el.value || "").trim());
  const prices = rowScopes.flatMap(row => valuesIn(row, ".price-input input,input")).filter(value => /^\d+(\.\d+)?$/.test(value));
  const stocks = rowScopes.flatMap(row => valuesIn(row, ".stock-column input,input")).filter(value => /^\d+$/.test(value));
  const skuCodes = rowScopes.flatMap(row => valuesIn(row, ".sku-textarea textarea,textarea")).filter(value =>
    value && !/Welcome|Greetings|Product Highlights|After-Sales|Order Today/i.test(value)
  );
  const pricesOk = prices.length >= 3;
  const stockOk = stocks.length >= 3 && stocks.every(value => Number(value) > 0);
  const skuCodesOk = skuCodes.length >= 3 && new Set(skuCodes).size >= 1;
  const weightValue = [...document.querySelectorAll("[data-product-edit-field-unique-id='weight'] input,input[name='weight']")]
    .filter(visible).map(input => input.value).find(Boolean) || "";
  const dimensionValues = ["dimension.width", "dimension.length", "dimension.height"].map(id => {
    const scope = document.querySelector(`[data-product-edit-field-unique-id="${id}"]`);
    const input = scope ? [...scope.querySelectorAll("input")].filter(visible)[0] : null;
    return input ? String(input.value || "").trim() : "";
  });
  const weightDimensionOk = /^\d+(\.\d+)?$/.test(weightValue) && dimensionValues.every(value => /^\d+(\.\d+)?$/.test(value));
  const shippingOk = /RM\s?\d|SHOPEE\s*物流服务|Doorstep|Economy|Standard Delivery/i.test(ship) && !/未开启物流选项|请输入重量|No logistics/i.test(ship);
  const parentSkuValue = [...document.querySelectorAll("[data-product-edit-field-unique-id='parentSku'] input,input[name='parentSku']")]
    .filter(visible).map(input => input.value).find(Boolean) || "";
  const parentSkuOk = !!String(parentSkuValue).trim();
  const visibleErrors = [...document.querySelectorAll(".eds-form-item__error,.product-edit-form-item__error,.error,.error-container,[class*='error']")]
    .filter(visible)
    .map(el => norm(el.innerText))
    .filter(Boolean)
    .filter(value => !/optional|recommend/i.test(value));
  const titleInputs = visibleInputs.filter(input => String(input.value || "").trim().length > 20);
  const saveDelistButtonVisible = [...document.querySelectorAll("button")].some(b => visible(b) && norm(b.innerText) === "储存并下架");
  const descriptionText = ql ? String(ql.innerText || "").trim() : "";
  const descriptionLines = descriptionText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const lastDescriptionLine = descriptionLines[descriptionLines.length - 1] || "";
  const seoHashtags = lastDescriptionLine.match(/#[A-Za-z0-9]+/g) || [];
  const descriptionExists = descriptionText.length > 100 && (ql?.innerHTML.match(/<p><br><\/p>/g) || []).length === 0;
  const descriptionLengthOk = descriptionText.length <= 3000;
  const seoKeywordCount = seoHashtags.length;
  const seoKeywordCountOk = seoKeywordCount >= 15 && seoKeywordCount <= 20;
  const seoHashtagLineAtBottom = seoKeywordCountOk && lastDescriptionLine === seoHashtags.join(" ");
  const seoKeywordsProductRelevant = seoKeywordCountOk && !/cure|medicalgrade|guaranteedcure/i.test(lastDescriptionLine.replace(/\s+/g, ""));
  // Description content is prepared and reviewed in earlier steps. Here we only
  // verify that Shopee currently contains a non-empty description.
  const hasDescription = descriptionExists;
  const canSaveDelist = (
    imageCount >= 3 &&
    imageCount <= 9 &&
    !unsafeImageSignals &&
    videoOk &&
    healthCertificationNo &&
    titleInputs.length > 0 &&
    hasDescription &&
    hasThreeVariationRows &&
    variationImagesOk &&
    pricesOk &&
    stockOk &&
    skuCodesOk &&
    weightDimensionOk &&
    shippingOk &&
    parentSkuOk &&
    visibleErrors.length === 0 &&
    saveDelistButtonVisible
  );
  return {
    imageCount,
    imageManagerText,
    unsafeImageSignals,
    videoUploaded,
    videoProcessing,
    videoFailed,
    videoOk,
    healthCertificationNo,
    hasTitle: titleInputs.length > 0,
    hasDescription,
    descriptionExists,
    descriptionLength: descriptionText.length,
    descriptionLengthOk,
    seoKeywordCount,
    seoKeywordCountOk,
    seoHashtagLineAtBottom,
    seoKeywordsProductRelevant,
    hasVariationTable: !!table,
    hasThreeVariationRows,
    variation_image_1box,
    variation_image_2box,
    variation_image_3box,
    variationImagesOk,
    pricesOk,
    stockOk,
    skuCodesOk,
    weightDimensionOk,
    hasShippingPanel: !!shipScope || /物流|运费|Shipping|Doorstep/.test(text),
    shippingHasRates: /RM\s?\d|SHOPEE\s*物流服务|Doorstep|Economy/i.test(ship),
    shippingOk,
    parentSkuOk,
    visibleErrors,
    saveDelistButtonVisible,
    canSaveDelist
  };
})()
"""
