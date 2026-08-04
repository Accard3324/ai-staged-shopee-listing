from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List


UNSAFE_IMAGE_WORDS = [
    "oem",
    "odm",
    "factory cooperation",
    "wholesale recruitment",
    "wholesale",
    "supplier",
    "招商",
    "供货商",
    "代理",
    "加盟",
    "批发招商",
]


def select_step1_images(manifest: Dict[str, Any], max_product_images: int = 9) -> Dict[str, Any]:
    warnings: List[str] = []
    skipped_unsafe: List[str] = []
    product_images: List[str] = []

    for image in _as_list(manifest.get("main_images")) + _as_list(manifest.get("detail_images")):
        if is_unsafe_image_path(image):
            skipped_unsafe.append(image)
            continue
        product_images.append(image)
        if len(product_images) >= max_product_images:
            break

    if not product_images:
        warnings.append("No buyer-safe product image found for Step 1 upload.")

    source_count = len(_as_list(manifest.get("main_images")) + _as_list(manifest.get("detail_images")))
    if source_count > len(product_images) + len(skipped_unsafe):
        warnings.append("Shopee allows 9 product images; extra images were not selected for Step 1.")

    return {
        "product_images": product_images,
        "promo_image": product_images[0] if product_images else "",
        "skipped_unsafe": skipped_unsafe,
        "warnings": warnings,
    }


def is_unsafe_image_path(path: str) -> bool:
    name = str(path or "").lower()
    return any(word.lower() in name for word in UNSAFE_IMAGE_WORDS)


def existing_files(paths: Iterable[str]) -> List[str]:
    return [path for path in paths if Path(path).is_file()]


def validate_confirmed_image_selection(
    manifest: Dict[str, Any],
    main_image: str,
    detail_images: Iterable[str],
    unsafe_images: Iterable[Any],
    promoted_main_candidates: Iterable[str] = (),
) -> Dict[str, Any]:
    main_candidates = set(_as_list(manifest.get("main_images")))
    main_candidates.update(str(item) for item in promoted_main_candidates if str(item))
    detail_candidates = set(_as_list(manifest.get("detail_images")))
    main = str(main_image).strip()
    details = list(dict.fromkeys(str(item) for item in detail_images if str(item)))
    unsafe_files = {
        str(item.get("file", "")) if isinstance(item, dict) else str(item)
        for item in unsafe_images
    }
    selected = ([main] if main else []) + details
    unsafe_selected = [path for path in selected if path in unsafe_files or is_unsafe_image_path(path)]
    errors: List[str] = []
    if main not in main_candidates:
        errors.append("Select exactly one image from the main-image folder")
    if any(path not in detail_candidates for path in details):
        errors.append("Detail images must come from the detail-image folder")
    if len(details) > 8 or len(selected) > 9:
        errors.append(f"Main and detail images may total at most 9; {len(selected)} are selected")
    return {
        "ok": not errors,
        "main_image": main,
        "detail_images": details,
        "total_images": len(selected),
        "exceeds_nine": len(selected) > 9,
        "unsafe_selected": unsafe_selected,
        "manual_override": True,
        "errors": errors,
    }


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []
