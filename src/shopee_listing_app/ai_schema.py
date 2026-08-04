from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping


REQUIRED_PLACEHOLDERS = ["PAIN_POINTS", "BENEFITS", "SPECIFICATIONS", "USAGE"]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: List[str]
    warnings: List[str]


def validate_ai_listing_result(payload: Mapping[str, object], keyword_range: tuple = (15, 20)) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is required")
    elif len(title) > 120:
        errors.append("title must be 120 characters or fewer")

    placeholders = payload.get("description_placeholders")
    if not isinstance(placeholders, dict):
        errors.append("description_placeholders is required")
    else:
        for key in REQUIRED_PLACEHOLDERS:
            if key not in placeholders:
                errors.append(f"description_placeholders.{key} is required")
            elif not isinstance(placeholders[key], str):
                errors.append(f"description_placeholders.{key} must be a string")

    image_selection = payload.get("image_selection")
    if not isinstance(image_selection, dict):
        errors.append("image_selection is required")
    else:
        if "main_image" not in image_selection:
            warnings.append("image_selection.main_image is missing")
        for list_key in ["detail_images", "sku_images", "unsafe_images"]:
            if list_key in image_selection and not isinstance(image_selection[list_key], list):
                errors.append(f"image_selection.{list_key} must be a list")

    title_keywords = payload.get("title_keywords", [])
    if not isinstance(title_keywords, list):
        errors.append("title_keywords must be a list")

    seo_validation = validate_seo_keywords_result(payload.get("seo_keywords", []), expected_range=keyword_range)
    errors.extend(seo_validation.errors)
    warnings.extend(seo_validation.warnings)

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_asset_analysis_result(payload: Mapping[str, object]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    main_image = payload.get("main_image")
    detail_images = payload.get("detail_images", [])
    unsafe_images = payload.get("unsafe_images", [])
    product_info = payload.get("product_info_from_images", {})

    if not isinstance(main_image, str) or not main_image.strip():
        errors.append("main_image is required")
    if not isinstance(detail_images, list):
        errors.append("detail_images must be a list")
        detail_images = []
    if not isinstance(unsafe_images, list):
        errors.append("unsafe_images must be a list")
    if not isinstance(product_info, dict):
        errors.append("product_info_from_images must be an object")
    if isinstance(detail_images, list) and len(detail_images) + (1 if isinstance(main_image, str) and main_image.strip() else 0) > 9:
        errors.append("main_image + detail_images must be 9 images or fewer")
    for item in unsafe_images if isinstance(unsafe_images, list) else []:
        if not isinstance(item, dict) or not item.get("file") or not item.get("reason"):
            errors.append("unsafe_images items must include file and reason")
            break
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_search_keywords_result(payload: Mapping[str, object]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    keywords = payload.get("search_keywords")
    if not isinstance(keywords, list):
        errors.append("search_keywords must be a list")
        keywords = []
    elif len(keywords) != 5:
        errors.append("search_keywords must contain exactly 5 items")
    for item in keywords:
        if not isinstance(item, dict):
            errors.append("each search keyword must be an object")
            continue
        for key in ["english", "chinese_meaning", "why"]:
            if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                errors.append(f"search_keywords.{key} is required")
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_seo_keywords_result(payload: object, expected_range: tuple = (15, 20)) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(payload, list):
        return ValidationResult(False, ["seo_keywords must be a list"], warnings)
    low, high = expected_range
    if low == high:
        if len(payload) != low:
            errors.append(f"seo_keywords must contain exactly {low} items")
    elif not low <= len(payload) <= high:
        errors.append(f"seo_keywords must contain {low} to {high} items")
    seen = set()
    languages = set()
    for item in payload:
        if not isinstance(item, dict):
            errors.append("each seo keyword must be an object")
            continue
        keyword = str(item.get("keyword", "")).strip()
        language = str(item.get("language", "")).strip()
        source_reason = str(item.get("source_reason", "")).strip()
        if not keyword or not language or not source_reason:
            errors.append("seo_keywords require keyword, language, and source_reason")
        if keyword.lower() in seen:
            errors.append("seo_keywords must be unique")
        seen.add(keyword.lower())
        languages.add(language.lower())
    if payload and not {"english", "malay"}.issubset(languages):
        warnings.append("seo_keywords should include both English and Malay")
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_title_analysis_result(payload: Mapping[str, object]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    final_title = payload.get("final_title")
    if not isinstance(final_title, str) or not final_title.strip():
        errors.append("final_title is required")
    elif len(final_title) > 120:
        errors.append("final_title must be 120 characters or fewer")
    competitors = payload.get("competitor_analysis")
    if not isinstance(competitors, list) or not competitors:
        errors.append("competitor_analysis is required")
    else:
        for item in competitors:
            if not isinstance(item, dict):
                errors.append("competitor_analysis items must be objects")
                continue
            if not isinstance(item.get("source_title"), str) or not item.get("source_title", "").strip():
                errors.append("competitor_analysis.source_title is required")
            if "reused_keywords" in item and not isinstance(item["reused_keywords"], list):
                errors.append("competitor_analysis.reused_keywords must be a list")
    for key in ["removed_keywords", "warnings"]:
        if key in payload and not isinstance(payload[key], list):
            errors.append(f"{key} must be a list")
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def ai_json_schema() -> Dict[str, object]:
    return {
        "type": "object",
        "required": ["title", "title_keywords", "description_placeholders", "image_selection", "warnings"],
        "properties": {
            "title": {"type": "string", "maxLength": 120},
            "title_keywords": {"type": "array", "items": {"type": "string"}},
            "description_placeholders": {
                "type": "object",
                "required": REQUIRED_PLACEHOLDERS,
                "properties": {key: {"type": "string"} for key in REQUIRED_PLACEHOLDERS},
            },
            "category_suggestion": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "confidence": {"type": "number"},
                    "source": {"enum": ["competitor", "shopee_suggestion", "manual"]},
                },
            },
            "attribute_suggestions": {"type": "array"},
            "image_selection": {"type": "object"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    }
