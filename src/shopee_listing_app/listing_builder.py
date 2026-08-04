from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
import re
from typing import Dict, Iterable, List, Mapping

from .ai_schema import REQUIRED_PLACEHOLDERS, validate_ai_listing_result
from .asset_inspector import AssetManifest
from .candidate_selector import CandidateSKU
from .workbook_reader import norm_text


def _render_description(template: str, placeholders: Mapping[str, str]) -> str:
    description = template
    for key in REQUIRED_PLACEHOLDERS:
        description = description.replace("{{" + key + "}}", norm_text(placeholders.get(key, "")))
    description = "\n".join(line.rstrip() for line in description.splitlines()).strip()
    if "{{" in description or "}}" in description:
        raise ValueError("description still contains unreplaced placeholders")
    return description


def build_description(template: str, placeholders: Mapping[str, str]) -> str:
    description = _render_description(template, placeholders)
    if len(description) > 3000:
        raise ValueError("description must be 3000 characters or fewer")
    return description


def _seo_count_error(keyword_range: tuple) -> str:
    low, high = keyword_range
    if low == high:
        return f"seo_keywords must contain exactly {low} items"
    return f"seo_keywords must contain {low} to {high} items"


def build_description_with_seo(
    template: str,
    placeholders: Mapping[str, str],
    seo_keywords: Iterable[Mapping[str, object]],
    keyword_range: tuple = (15, 20),
    *,
    enforce_character_limit: bool = True,
) -> Dict[str, object]:
    keywords = list(seo_keywords)
    low, high = keyword_range
    if low == high:
        if len(keywords) != low:
            raise ValueError(_seo_count_error(keyword_range))
    elif not low <= len(keywords) <= high:
        raise ValueError(_seo_count_error(keyword_range))
    hashtags: List[str] = []
    relevant = True
    for item in keywords:
        keyword = norm_text(item.get("keyword"))
        source_reason = norm_text(item.get("source_reason"))
        hashtag = "#" + "".join(part[:1].upper() + part[1:] for part in re.findall(r"[A-Za-z0-9]+", keyword))
        if hashtag == "#" or hashtag.lower() in {value.lower() for value in hashtags}:
            raise ValueError("seo_keywords must be unique non-empty English or Malay terms")
        hashtags.append(hashtag)
        relevant = relevant and bool(source_reason)
    hashtag_line = " ".join(hashtags)
    body = _render_description(template, placeholders)
    final_description = f"{body}\n\n{hashtag_line}".strip()
    if enforce_character_limit and len(final_description) > 3000:
        raise ValueError("final description including SEO hashtags must be 3000 characters or fewer")
    return {
        "final_description": final_description,
        "final_description_length": len(final_description),
        "within_character_limit": len(final_description) <= 3000,
        "seo_keywords": keywords,
        "seo_keyword_count": len(keywords),
        "seo_hashtag_line": hashtag_line,
        "seo_hashtag_line_at_bottom": final_description.splitlines()[-1] == hashtag_line,
        "seo_keywords_product_relevant": relevant,
    }


def audit_final_description(
    final_description: str,
    seo_keywords: Iterable[Mapping[str, object]],
    keyword_range: tuple = (15, 20),
) -> Dict[str, object]:
    """Accept the user's final edit without changing its content."""
    text = str(final_description).strip()
    if not text:
        raise ValueError("final description is required")
    keywords = list(seo_keywords)
    low, high = keyword_range
    if low == high:
        if len(keywords) != low:
            raise ValueError(_seo_count_error(keyword_range))
    elif not low <= len(keywords) <= high:
        raise ValueError(_seo_count_error(keyword_range))
    hashtags: List[str] = []
    relevant = True
    for item in keywords:
        keyword = norm_text(item.get("keyword"))
        source_reason = norm_text(item.get("source_reason"))
        hashtag = "#" + "".join(part[:1].upper() + part[1:] for part in re.findall(r"[A-Za-z0-9]+", keyword))
        if hashtag == "#" or hashtag.lower() in {value.lower() for value in hashtags}:
            raise ValueError("seo_keywords must be unique non-empty English or Malay terms")
        hashtags.append(hashtag)
        relevant = relevant and bool(source_reason)
    hashtag_line = " ".join(hashtags)
    if len(text) > 3000:
        raise ValueError(
            f"final description must be 3000 characters or fewer; "
            f"the server received {len(text)} characters"
        )
    hashtag_line_at_bottom = bool(text) and text.splitlines()[-1].strip() == hashtag_line
    return {
        "final_description": text,
        "final_description_length": len(text),
        "within_character_limit": len(text) <= 3000,
        "seo_keywords": keywords,
        "seo_keyword_count": len(keywords),
        "seo_hashtag_line": hashtag_line,
        "seo_hashtag_line_at_bottom": hashtag_line_at_bottom,
        "seo_keywords_product_relevant": relevant,
        "manual_override": True,
    }


def normalize_price(value: object) -> str:
    try:
        return format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    except (InvalidOperation, ValueError):
        text = norm_text(value)
        if not text:
            raise ValueError("variation price is required")
        return text


def build_variations(candidate: CandidateSKU) -> List[Dict[str, object]]:
    spec = norm_text(candidate.sku_spec)
    stock = norm_text(candidate.overseas_available_stock)
    sku_code = norm_text(candidate.sku_code)
    if not stock or stock == "0":
        stock = "100"
    if not sku_code:
        raise ValueError("SKU code from column AB is required before building variations")

    names = [f"{spec} /1box", f"2x {spec} /2box", f"3x {spec} /3box"]
    prices = [
        normalize_price(candidate.price_1box),
        normalize_price(candidate.price_2box),
        normalize_price(candidate.price_3box),
    ]
    return [
        {
            "name": name,
            "price": price,
            "stock": stock,
            "item_code": sku_code,
            "gtin": "",
            "no_gtin": True,
        }
        for name, price in zip(names, prices)
    ]


def build_listing_draft(
    candidate: CandidateSKU,
    store_name: str,
    template_key: str,
    description_template: str,
    asset_manifest: AssetManifest,
    competitors: Iterable[Mapping[str, object]],
    ai_result: Mapping[str, object],
    keyword_range: tuple = (15, 20),
) -> Dict[str, object]:
    validation = validate_ai_listing_result(ai_result, keyword_range=keyword_range)
    if not validation.ok:
        raise ValueError("AI JSON validation failed: " + "; ".join(validation.errors))

    description_override = str(ai_result.get("final_description_override", "")).strip()
    if description_override:
        description_result = audit_final_description(
            description_override,
            ai_result.get("seo_keywords", []),  # type: ignore[arg-type]
            keyword_range,
        )
    else:
        description_result = build_description_with_seo(
            description_template,
            ai_result["description_placeholders"],  # type: ignore[arg-type]
            ai_result.get("seo_keywords", []),  # type: ignore[arg-type]
            keyword_range,
        )
    description = str(description_result["final_description"])
    variations = build_variations(candidate)

    draft = {
        "schema_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "store": {"name": store_name, "template_key": template_key},
        "candidate": candidate.to_dict(),
        "listing": {
            "title": ai_result["title"],
            "title_keywords": ai_result.get("title_keywords", []),
            "description": description,
            "description_audit": description_result,
            "category_suggestion": ai_result.get("category_suggestion", {}),
            "attribute_suggestions": ai_result.get("attribute_suggestions", []),
            "save_mode": "delist",
            "save_button_text": "储存并下架",
        },
        "assets": asset_manifest.to_dict(),
        "image_selection": ai_result.get("image_selection", {}),
        "competitors": list(competitors),
        "variations": variations,
        "validation": {
            "ai_errors": validation.errors,
            "ai_warnings": validation.warnings,
            "business_rules": [
                "prices come from workbook columns E/F/G",
                "stock comes from workbook column AO",
                "SKU code comes from workbook column AB",
                "description template comes from config",
                "workbook is not updated by default",
            ],
        },
        "upload_draft": {
            "implemented": False,
            "next_phase": "Phase 2 will connect Ziniao Browser and fill Shopee Seller Center.",
        },
    }
    return draft
