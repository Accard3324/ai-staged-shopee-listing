from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import mimetypes
import os
from pathlib import Path
import threading
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .ai_schema import (
    validate_asset_analysis_result,
    validate_search_keywords_result,
    validate_seo_keywords_result,
    validate_title_analysis_result,
)
from .asset_inspector import AssetManifest
from .candidate_selector import CandidateSKU
from .config_manager import AIConfig, PROJECT_ROOT
from .nvidia_request_control import (
    AIResponseCache,
    NvidiaRateLimitExhausted,
    NvidiaRequestController,
    current_nvidia_request_batch_id,
    current_nvidia_request_task_id,
    get_nvidia_request_controller,
)
from .prompt_config import parse_seo_keyword_count
from .workbook_reader import norm_text

ZHIPU_DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_DEFAULT_MODEL = "glm-5.2"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-5.6"
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_VISION_DEFAULT_MODEL = "qwen/qwen3.5-397b-a17b"
NVIDIA_MINIMAX_VISION_MODEL = "minimaxai/minimax-m3"
NVIDIA_TEXT_DEFAULT_MODEL = "z-ai/glm-5.2"
AGNES_VISION_DEFAULT_MODEL = "agnes-2.0-flash"
AGNES_TEXT_DEFAULT_MODEL = AGNES_VISION_DEFAULT_MODEL
AGNES_DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
AI_EXECUTION_MODE_VISION_TEXT = "vision_text"
AI_EXECUTION_MODE_MULTIMODAL = "multimodal"
MULTIMODAL_PRODUCT_PROMPT_PREFIX = (
    "The attached images show the product that will be listed on Shopee Malaysia."
)

AI_MODEL_LABELS = {
    OPENAI_DEFAULT_MODEL: OPENAI_DEFAULT_MODEL,
    AGNES_VISION_DEFAULT_MODEL: AGNES_VISION_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL: NVIDIA_VISION_DEFAULT_MODEL,
    NVIDIA_MINIMAX_VISION_MODEL: NVIDIA_MINIMAX_VISION_MODEL,
    NVIDIA_TEXT_DEFAULT_MODEL: NVIDIA_TEXT_DEFAULT_MODEL,
}
MULTIMODAL_AI_MODELS = (
    OPENAI_DEFAULT_MODEL,
    AGNES_VISION_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL,
    NVIDIA_MINIMAX_VISION_MODEL,
)
VISION_TEXT_AI_MODELS = (
    *MULTIMODAL_AI_MODELS,
    NVIDIA_TEXT_DEFAULT_MODEL,
)

OBJECTIVE_IMAGE_RECORD_FIELDS = (
    "file_name",
    "folder_type",
    "visible_text",
    "factual_visual_description",
    "product_type",
    "product_form",
    "packaging_description",
    "visible_specs",
    "visible_ingredients_or_materials",
    "visible_claims",
    "visible_usage",
    "depicted_body_areas_or_scenarios",
    "is_before_after_image",
    "contains_oem_odm",
    "contains_supplier_ad",
    "objective_quality_issues",
    "uncertainties",
)
SELECTION_ASSESSMENT_FIELDS = (
    "suitable_for_listing",
    "recommended_role",
    "upload_score",
    "selection_reasons",
)
TITLE_REASONING_TOKEN_BUDGETS = {
    "low": 8192,
    "medium": 16384,
    "high": 24576,
    "maximum": 32768,
}
AGNES_TEXT_REASONING_TOKEN_BUDGETS = {
    **TITLE_REASONING_TOKEN_BUDGETS,
    "maximum": 65536,
}
TITLE_REASONING_INSTRUCTIONS = {
    "low": "Briefly verify the core product terms and remove clearly irrelevant terms. Complete every required field.",
    "medium": "Verify reused competitor terms, objective image facts, and title structure. Complete every required field.",
    "high": "Carefully verify each reused competitor term, objective image fact, excluded term, and title component. Complete every required field.",
    "maximum": (
        "Use the model's highest supported reasoning effort. Verify every reused term "
        "against the supplied objective image facts and source titles. Complete every required field."
    ),
}


def normalize_title_reasoning_strength(value: object) -> str:
    normalized = str(value or "").strip().lower()
    normalized = {"highest": "maximum", "max": "maximum"}.get(normalized, normalized)
    return normalized if normalized in TITLE_REASONING_TOKEN_BUDGETS else "maximum"


def normalize_text_reasoning_strength(value: object) -> str:
    normalized = str(value or "").strip().lower()
    normalized = {
        "default": "official_default",
        "model_default": "official_default",
        "highest": "maximum",
        "max": "maximum",
    }.get(normalized, normalized)
    if normalized == "official_default":
        return normalized
    return normalized if normalized in TITLE_REASONING_TOKEN_BUDGETS else "official_default"


def normalize_text_thinking_mode(
    value: object,
    thinking_enabled: object = None,
) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"official_default", "enabled", "disabled"}:
        return normalized
    if normalized in {"default", "model_default"}:
        return "official_default"
    if thinking_enabled is not None:
        return "enabled" if _as_bool(thinking_enabled) else "disabled"
    return "official_default"


def title_reasoning_instruction(thinking_enabled: bool, reasoning_strength: object) -> str:
    if not thinking_enabled:
        return "Reasoning is disabled. Return only the final valid JSON object."
    strength = normalize_title_reasoning_strength(reasoning_strength)
    return TITLE_REASONING_INSTRUCTIONS[strength]


KEYWORD_REASONING_INSTRUCTIONS = {
    "low": "Briefly verify the product category, core use, and search-term relevance. Complete every required field.",
    "medium": "Verify objective image facts, the product category, and buyer search intent. Complete every required field.",
    "high": "Carefully verify objective image facts, the product category, buyer search intent, and the distinct purpose of all five search terms. Complete every required field.",
    "maximum": (
        "Use the model's highest supported reasoning effort. Verify all five search terms "
        "against the objective image facts, product category, and buyer intent. Avoid irrelevant or duplicate terms."
    ),
}


def keyword_reasoning_instruction(thinking_enabled: bool, reasoning_strength: object) -> str:
    if not thinking_enabled:
        return "Reasoning is disabled. Return only the final valid JSON object."
    strength = normalize_title_reasoning_strength(reasoning_strength)
    return KEYWORD_REASONING_INSTRUCTIONS[strength]


DESCRIPTION_REASONING_INSTRUCTIONS = {
    "low": "Briefly verify product benefits and specification facts. Complete every required field.",
    "medium": "Verify objective image facts, description structure, and character limits. Complete every required field.",
    "high": "Carefully verify objective image facts, description placeholders, SEO term relevance, and character limits. Complete every required field.",
    "maximum": (
        "Use the model's highest supported reasoning effort. Verify every description section "
        "against the supplied objective image facts and keep the complete store template, including hashtags, within 3,000 characters."
    ),
}


VISION_REASONING_TOKEN_BUDGETS = {
    "low": 4096,
    "medium": 8192,
    "high": 12288,
    "maximum": 16384,
}

MINIMAX_REASONING_TOKEN_BUDGETS = {
    "low": 4096,
    "medium": 8192,
    "high": 8192,
    "maximum": 8192,
}


def model_reasoning_profile(model: object, usage: str) -> Dict[str, object]:
    """Return the exact token controls used by this application for one model."""
    model_id = str(model or "").strip().lower()
    normalized_usage = "vision" if usage == "vision" else "text"
    output_budgets: Mapping[str, int]
    metric = "output token limit"

    if normalized_usage == "vision":
        if model_id == NVIDIA_MINIMAX_VISION_MODEL:
            output_budgets = MINIMAX_REASONING_TOKEN_BUDGETS
        else:
            output_budgets = VISION_REASONING_TOKEN_BUDGETS
    elif model_id == AGNES_TEXT_DEFAULT_MODEL:
        output_budgets = AGNES_TEXT_REASONING_TOKEN_BUDGETS
    elif model_id == NVIDIA_MINIMAX_VISION_MODEL:
        output_budgets = MINIMAX_REASONING_TOKEN_BUDGETS
    else:
        output_budgets = TITLE_REASONING_TOKEN_BUDGETS

    displayed_budgets = output_budgets
    if model_id in {OPENAI_DEFAULT_MODEL, NVIDIA_TEXT_DEFAULT_MODEL}:
        metric = "maximum completion tokens"

    official_default_output = {
        OPENAI_DEFAULT_MODEL: 32768,
        AGNES_TEXT_DEFAULT_MODEL: 16384 if normalized_usage == "vision" else 65536,
        NVIDIA_MINIMAX_VISION_MODEL: 8192,
        NVIDIA_TEXT_DEFAULT_MODEL: 16384,
    }.get(model_id, int(output_budgets["maximum"]))
    official_default_budget = official_default_output
    return {
        "metric": metric,
        "budgets": {
            "official_default": official_default_budget,
            **{key: int(value) for key, value in displayed_budgets.items()},
        },
        "output_budgets": {
            "official_default": official_default_output,
            **{key: int(value) for key, value in output_budgets.items()},
        },
        "official_default_note": "API default",
    }

VISION_REASONING_INSTRUCTIONS = {
    "low": "Briefly verify visible text, product type, specifications, and packaging facts, then return complete JSON.",
    "medium": "Verify visible text, product type, specifications, packaging, and usage facts, then return complete JSON.",
    "high": "Carefully verify all visible information, consistency, and uncertainties, then return complete JSON.",
    "maximum": "Use the model's highest supported reasoning effort to verify every image fact and image-selection field, then return complete JSON.",
}


def normalize_vision_reasoning_strength(value: object) -> str:
    normalized = str(value or "").strip().lower()
    normalized = {
        "default": "official_default",
        "model_default": "official_default",
        "highest": "maximum",
        "max": "maximum",
    }.get(
        normalized,
        normalized,
    )
    if normalized == "official_default":
        return normalized
    return normalized if normalized in VISION_REASONING_TOKEN_BUDGETS else "official_default"


def normalize_vision_thinking_mode(
    value: object,
    thinking_enabled: object = None,
) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"enabled", "disabled", "adaptive", "official_default"}:
        return normalized
    if thinking_enabled is not None:
        return "enabled" if _as_bool(thinking_enabled) else "disabled"
    return "official_default"


def vision_reasoning_instruction(thinking_mode: object, reasoning_strength: object) -> str:
    normalized_mode = normalize_vision_thinking_mode(thinking_mode)
    if normalized_mode == "official_default":
        return ""
    if normalized_mode == "disabled":
        return "Reasoning is disabled. Inspect the image and return only the final valid JSON object."
    if normalized_mode == "adaptive":
        return "Use the model's official adaptive reasoning behavior for this image task."
    strength = normalize_vision_reasoning_strength(reasoning_strength)
    return VISION_REASONING_INSTRUCTIONS[strength]


def description_reasoning_instruction(thinking_enabled: bool, reasoning_strength: object) -> str:
    if not thinking_enabled:
        return "Reasoning is disabled. Return only the final valid JSON object."
    strength = normalize_title_reasoning_strength(reasoning_strength)
    return DESCRIPTION_REASONING_INSTRUCTIONS[strength]


def vision_analysis_output_schema() -> Dict[str, object]:
    """Keep factual extraction and operational image selection in separate branches."""
    string_list = {"type": "array", "items": {"type": "string"}}
    objective_properties: Dict[str, object] = {
        "file_name": {"type": "string"},
        "folder_type": {"type": "string"},
        "visible_text": string_list,
        "factual_visual_description": {"type": "string"},
        "product_type": {"type": "string"},
        "product_form": {"type": "string"},
        "packaging_description": {"type": "string"},
        "visible_specs": string_list,
        "visible_ingredients_or_materials": string_list,
        "visible_claims": string_list,
        "visible_usage": string_list,
        "depicted_body_areas_or_scenarios": string_list,
        "is_before_after_image": {"type": "boolean"},
        "contains_oem_odm": {"type": "boolean"},
        "contains_supplier_ad": {"type": "boolean"},
        "objective_quality_issues": string_list,
        "uncertainties": string_list,
    }
    return {
        "type": "object",
        "required": ["objective_record", "selection_assessment"],
        "properties": {
            "objective_record": {
                "type": "object",
                "required": list(OBJECTIVE_IMAGE_RECORD_FIELDS),
                "properties": objective_properties,
            },
            "selection_assessment": {
                "type": "object",
                "required": list(SELECTION_ASSESSMENT_FIELDS),
                "properties": {
                    "suitable_for_listing": {"type": "boolean"},
                    "recommended_role": {"type": "string"},
                    "upload_score": {"type": "number", "minimum": 0, "maximum": 100},
                    "selection_reasons": string_list,
                },
            },
        },
    }


def vision_selection_only_output_schema() -> Dict[str, object]:
    """Schema used when downstream steps will inspect the product images directly."""
    return {
        "type": "object",
        "required": ["selection_assessment"],
        "properties": {
            "selection_assessment": {
                "type": "object",
                "required": list(SELECTION_ASSESSMENT_FIELDS),
                "properties": {
                    "suitable_for_listing": {"type": "boolean"},
                    "recommended_role": {"type": "string"},
                    "upload_score": {"type": "number", "minimum": 0, "maximum": 100},
                    "selection_reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
        },
    }


def objective_product_info_for_text(product_info: Mapping[str, object]) -> Dict[str, object]:
    """Allow only factual image records into downstream text-model payloads."""
    if not isinstance(product_info, Mapping):
        return {}
    records: list[Dict[str, object]] = []
    raw_records = product_info.get("objective_image_records", [])
    if isinstance(raw_records, list):
        for raw_record in raw_records:
            if isinstance(raw_record, Mapping):
                records.append(_clean_objective_record(raw_record))
    visible_claims = _clean_string_list(product_info.get("visible_claims"))
    if not visible_claims:
        visible_claims = _clean_string_list(product_info.get("benefits"))
    visible_usage = _clean_string_list(product_info.get("visible_usage"))
    if not visible_usage:
        legacy_usage = product_info.get("usage")
        visible_usage = (
            _clean_string_list(legacy_usage)
            if isinstance(legacy_usage, list)
            else ([str(legacy_usage).strip()] if str(legacy_usage or "").strip() else [])
        )
    safe: Dict[str, object] = {
        "data_scope": "objective_image_facts_only",
        "product_type": str(product_info.get("product_type", "") or "").strip(),
        "product_forms": _clean_string_list(product_info.get("product_forms"))
        or _clean_string_list([product_info.get("product_form")]),
        "packaging_descriptions": _clean_string_list(product_info.get("packaging_descriptions"))
        or _clean_string_list([product_info.get("packaging_description")]),
        "visible_specs": _clean_string_list(product_info.get("visible_specs")),
        "visible_ingredients_or_materials": _clean_string_list(
            product_info.get("visible_ingredients_or_materials")
        ),
        "visible_claims": visible_claims,
        "visible_text": _clean_string_list(product_info.get("visible_text")),
        "visible_usage": visible_usage,
        "depicted_body_areas_or_scenarios": _clean_string_list(
            product_info.get("depicted_body_areas_or_scenarios")
        ),
        "factual_visual_descriptions": _clean_string_list(
            product_info.get("factual_visual_descriptions")
        ),
        "objective_quality_issues": _clean_string_list(product_info.get("objective_quality_issues")),
        "uncertainties": _clean_string_list(product_info.get("uncertainties")),
        "objective_image_records": records,
    }
    return {
        key: value
        for key, value in safe.items()
        if value not in ("", None) and value != [] and value != {}
    }


def _clean_objective_record(raw_record: Mapping[str, object]) -> Dict[str, object]:
    cleaned: Dict[str, object] = {}
    scalar_fields = {
        "file_name",
        "folder_type",
        "factual_visual_description",
        "product_type",
        "product_form",
        "packaging_description",
    }
    list_fields = {
        "visible_text",
        "visible_specs",
        "visible_ingredients_or_materials",
        "visible_claims",
        "visible_usage",
        "depicted_body_areas_or_scenarios",
        "objective_quality_issues",
        "uncertainties",
    }
    boolean_fields = {"is_before_after_image", "contains_oem_odm", "contains_supplier_ad"}
    for field in scalar_fields:
        cleaned[field] = str(raw_record.get(field, "") or "").strip()
    for field in list_fields:
        cleaned[field] = _clean_string_list(raw_record.get(field))
    for field in boolean_fields:
        cleaned[field] = _as_bool(raw_record.get(field))
    return cleaned


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def nvidia_vision_image_paths(asset_manifest: AssetManifest) -> list[str]:
    """One merged vision batch: all selection candidates plus approved information sources."""
    paths: list[str] = []
    for path in [
        *asset_manifest.main_images,
        *asset_manifest.detail_images,
        *asset_manifest.english_images,
        *asset_manifest.parameter_images,
        *asset_manifest.sku_images,
        *asset_manifest.information_images,
    ]:
        if path and path not in paths:
            paths.append(path)
    return paths


def nvidia_vision_analysis_targets(asset_manifest: AssetManifest) -> list[tuple[str, str]]:
    groups = [
        ("main_image", asset_manifest.main_images),
        ("detail_image", asset_manifest.detail_images),
        ("english_asset", asset_manifest.english_images),
        ("parameter_image", asset_manifest.parameter_images),
        ("sku", asset_manifest.sku_images),
        ("supplementary_asset", asset_manifest.information_images),
    ]
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for folder_type, paths in groups:
        for path in paths:
            value = str(path).strip()
            if value and value not in seen:
                targets.append((folder_type, value))
                seen.add(value)
    return targets


def load_project_env(path: Path | None = None) -> Dict[str, str]:
    env_path = path or PROJECT_ROOT / ".env"
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
        values[key] = value
    return values


def mask_secret(text: object, secret: str) -> str:
    value = str(text)
    if secret:
        value = value.replace(secret, "***")
    return value


def resolve_prompt(provider: object, key: str, default: str) -> str:
    """Use the GUI-saved prompt for this run without persisting credentials."""
    overrides = getattr(provider, "prompt_overrides", {})
    if isinstance(overrides, Mapping) and key in overrides:
        return str(overrides.get(key, "") or "").strip()
    return default


class AIProvider:
    def generate_listing(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        competitors: Iterable[Mapping[str, object]],
    ) -> Dict[str, object]:
        raise NotImplementedError

    def analyze_assets(self, candidate: CandidateSKU, asset_manifest: AssetManifest) -> Dict[str, object]:
        main_image = asset_manifest.main_images[0] if asset_manifest.main_images else ""
        return {
            "main_image": main_image,
            "detail_images": asset_manifest.detail_images[:8],
            "unsafe_images": asset_manifest.unsafe_images,
            "product_info_from_images": {
                "product_type": norm_text(candidate.product_name),
                "visible_specs": [norm_text(candidate.sku_spec)],
                "visible_ingredients_or_materials": [],
                "usage": "Use according to the visible instructions on the product packaging.",
                "warnings": list(asset_manifest.warnings),
            },
        }
    def generate_search_keywords(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        product_info: Mapping[str, object],
    ) -> Dict[str, object]:
        product_name = norm_text(candidate.product_name) or "skin care cream"
        return {
            "search_keywords": [
                {"english": f"{product_name} cream", "chinese_meaning": "Core product care cream", "why": "based on product name"},
                {"english": "skin care ointment", "chinese_meaning": "Skin care ointment", "why": "broad Shopee category keyword"},
                {"english": "wart remover cream", "chinese_meaning": "Wart care cream", "why": "related buyer search term"},
                {"english": "skin tag remover", "chinese_meaning": "Skin tag care", "why": "related buyer search term"},
                {"english": "first aid cream", "chinese_meaning": "First-aid care cream", "why": "category search term"},
            ]
        }

    def analyze_competitor_titles(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
        competitors: Iterable[Mapping[str, object]],
        thinking_enabled: bool = True,
        reasoning_strength: str = "maximum",
    ) -> Dict[str, object]:
        sources = list(competitors)
        reused: list[str] = []
        removed: list[str] = []
        for source in sources:
            title = norm_text(source.get("source_title"))
            for word in title.split():
                cleaned = word.strip(" ,.;:|/()[]{}")
                if len(cleaned) < 4:
                    continue
                if cleaned.lower() == norm_text(candidate.brand).lower():
                    continue
                if cleaned.lower() not in {item.lower() for item in reused}:
                    reused.append(cleaned)
                if len(reused) >= 8:
                    break
            if len(reused) >= 8:
                break
        title_parts = [norm_text(candidate.brand), norm_text(candidate.product_name), norm_text(candidate.sku_spec)]
        for word in reused:
            if word.lower() not in " ".join(title_parts).lower():
                title_parts.append(word)
        title = " ".join(item for item in title_parts if item).strip()[:120].rstrip()
        return {
            "final_title": title,
            "competitor_analysis": [
                {
                    "source_title": norm_text(source.get("source_title")),
                    "sales": norm_text(source.get("observed_sales")),
                    "reused_keywords": reused[:5],
                }
                for source in sources
            ],
            "removed_keywords": removed,
            "warnings": [] if sources else ["No manual competitors were provided."],
        }

    def generate_description_placeholders(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
    ) -> Dict[str, object]:
        spec = norm_text(candidate.sku_spec)
        return {
            "description_placeholders": {
                "PAIN_POINTS": "Daily care can be difficult when the product is not simple to use.",
                "BENEFITS": "Made for practical daily care with a compact pack size.",
                "SPECIFICATIONS": f"{spec} per box." if spec else "Please check the selected variation for pack size.",
                "USAGE": norm_text(product_info.get("usage")) or "Use according to the visible instructions on the product packaging.",
            }
        }

    def suggest_category(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
    ) -> Dict[str, object]:
        return {"category_suggestion": {"path": "", "confidence": 0, "source": "manual"}}


def local_seo_keywords(candidate: CandidateSKU) -> list[Dict[str, str]]:
    source = f"workbook product: {norm_text(candidate.product_name)} {norm_text(candidate.sku_spec)}".strip()
    pairs = [
        ("Daily Care", "English"),
        ("Penjagaan Harian", "Malay"),
        ("Skin Care", "English"),
        ("Penjagaan Kulit", "Malay"),
        ("Personal Care", "English"),
        ("Penjagaan Peribadi", "Malay"),
        ("Targeted Care", "English"),
        ("Penjagaan Sasaran", "Malay"),
        ("Home Care", "English"),
        ("Penjagaan Rumah", "Malay"),
        ("Easy Application", "English"),
        ("Penggunaan Mudah", "Malay"),
        ("Compact Pack", "English"),
        ("Pek Kompak", "Malay"),
        ("Care Cream", "English"),
        ("Krim Penjagaan", "Malay"),
    ]
    return [{"keyword": keyword, "language": language, "source_reason": source} for keyword, language in pairs]


class OfflineAIProvider(AIProvider):
    """Dependency-free fallback so the first MVP can run without an API key."""

    def generate_listing(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        competitors: Iterable[Mapping[str, object]],
    ) -> Dict[str, object]:
        competitor_keywords = []
        for source in competitors:
            title = norm_text(source.get("source_title"))
            for word in title.split():
                clean = word.strip(" ,.;:|/()[]{}")
                if len(clean) >= 4 and clean.lower() not in {w.lower() for w in competitor_keywords}:
                    competitor_keywords.append(clean)
                if len(competitor_keywords) >= 6:
                    break
            if len(competitor_keywords) >= 6:
                break

        base_parts = [
            norm_text(candidate.brand),
            norm_text(candidate.product_name),
            norm_text(candidate.sku_spec),
            "Shopee Malaysia",
        ]
        for keyword in competitor_keywords:
            if keyword.lower() not in " ".join(base_parts).lower():
                base_parts.append(keyword)
        title = " ".join(part for part in base_parts if part).strip()[:120].rstrip()

        main_image = asset_manifest.main_images[0] if asset_manifest.main_images else ""
        return {
            "title": title,
            "title_keywords": competitor_keywords,
            "description_placeholders": {
                "PAIN_POINTS": "Daily cleaning and care can be inconvenient when product details are unclear.",
                "BENEFITS": "Designed for simple daily use with practical value for local buyers.",
                "SPECIFICATIONS": f"{norm_text(candidate.sku_spec)} per box.",
                "USAGE": "Use according to the visible instructions on the product packaging.",
            },
            "seo_keywords": local_seo_keywords(candidate),
            "category_suggestion": {
                "path": "",
                "confidence": 0,
                "source": "manual",
            },
            "attribute_suggestions": [
                {"name": "Shelf Life", "value": "36 months", "confidence": 0.5}
            ],
            "image_selection": {
                "main_image": main_image,
                "detail_images": asset_manifest.detail_images,
                "sku_images": [
                    {"variation": variation, "file": file_path}
                    for variation, file_path in zip(
                        [f"{candidate.sku_spec} /1box", f"2x {candidate.sku_spec} /2box", f"3x {candidate.sku_spec} /3box"],
                        asset_manifest.sku_images,
                    )
                ],
                "unsafe_images": asset_manifest.unsafe_images,
            },
            "warnings": [
                "Offline provider was used. Configure a real AI API before production listing."
            ],
        }


class ZhipuProvider(AIProvider):
    def __init__(self, config: AIConfig, prompts_dir: Path):
        load_project_env(PROJECT_ROOT / ".env")
        self.config = config
        self.prompts_dir = prompts_dir
        self.endpoint = config.endpoint or ZHIPU_DEFAULT_ENDPOINT
        self.model = config.model or os.environ.get("ZHIPU_MODEL") or ZHIPU_DEFAULT_MODEL
        self.last_used_model = ""
        self.model_attempt_log: list[Dict[str, object]] = []

    def _api_key(self) -> str:
        key = os.environ.get(self.config.api_key_env or "ZHIPU_API_KEY", "") or os.environ.get("ZHIPU_API_KEY", "")
        if not key:
            raise RuntimeError("Zhipu API key is not configured. Set ZHIPU_API_KEY in .env.")
        return key

    def request_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, object],
        required_keys: Iterable[str],
        max_retries: int = 2,
        *,
        thinking_enabled: bool = False,
        reasoning_strength: str = "medium",
    ) -> Dict[str, object]:
        return self._request_json_with_models(
            system_prompt,
            user_payload,
            required_keys,
            self.model_candidates(),
            max_retries=max_retries,
            thinking_enabled=thinking_enabled,
            reasoning_strength=reasoning_strength,
        )

    def _request_json_with_models(
        self,
        system_prompt: str,
        user_payload: Mapping[str, object],
        required_keys: Iterable[str],
        models: Iterable[str],
        max_retries: int = 2,
        *,
        thinking_enabled: bool = False,
        reasoning_strength: str = "medium",
    ) -> Dict[str, object]:
        api_key = self._api_key()
        required = list(required_keys)
        attempts_per_model = max(1, int(max_retries or self.config.max_retries_per_model or 1))
        normalized_strength = normalize_title_reasoning_strength(reasoning_strength)
        max_tokens = TITLE_REASONING_TOKEN_BUDGETS[normalized_strength] if thinking_enabled else 8192
        request_system_prompt = system_prompt
        if str(user_payload.get("task", "")) == "analyze_competitors_and_generate_title":
            request_system_prompt += "\n" + title_reasoning_instruction(
                thinking_enabled,
                normalized_strength,
            )
        self.model_attempt_log = []
        last_error = ""
        for model in models:
            for attempt in range(1, attempts_per_model + 1):
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                request_system_prompt
                                + "\nReturn exactly one valid JSON object without a Markdown code fence."
                            ),
                        },
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                    ],
                    "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                }
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                request = urllib.request.Request(
                    self.endpoint,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                        data = json.loads(response.read().decode("utf-8"))
                    content = self._extract_content(data)
                    parsed = self._parse_json_content(content)
                    missing = [key for key in required if key not in parsed]
                    if missing:
                        raise ValueError("missing keys: " + ", ".join(missing))
                    self.last_used_model = model
                    self.model_attempt_log.append({"model": model, "ok": True, "attempt": attempt})
                    return parsed
                except Exception as exc:  # noqa: BLE001
                    last_error = mask_secret(exc, api_key)
                    self.model_attempt_log.append(
                        {"model": model, "ok": False, "attempt": attempt, "error": last_error}
                    )
        raise RuntimeError(
            "All Zhipu model requests failed. Check the API key, model access, and account quota."
            f" Last sanitized error: {last_error}"
        )

    def model_candidates(self) -> list[str]:
        candidates: list[str] = []
        env_model = os.environ.get("ZHIPU_MODEL", "")
        env_fallback = os.environ.get("ZHIPU_FALLBACK_MODELS", "")
        raw_values: list[str] = [
            env_model,
            self.model,
            *(self.config.fallback_models or []),
            *[item.strip() for item in env_fallback.split(",") if item.strip()],
            "glm-4.7",
            "glm-4.6",
            "glm-4.5-air",
        ]
        for raw in raw_values:
            model = str(raw or "").strip()
            if not model:
                continue
            api_model = model.lower()
            if api_model not in candidates:
                candidates.append(api_model)
        if ZHIPU_DEFAULT_MODEL not in candidates:
            candidates.insert(0, ZHIPU_DEFAULT_MODEL)
        return candidates

    def check_models(self) -> Dict[str, object]:
        results: list[Dict[str, object]] = []
        selected = ""
        for model in self.model_candidates():
            try:
                data = self._request_json_with_models(
                    "This is a connectivity check. Return JSON and write any user-facing explanation in English.",
                    {"task": "zhipu_connectivity_check"},
                    required_keys=["ok"],
                    models=[model],
                    max_retries=1,
                )
                ok = bool(data.get("ok", True))
                results.append({"model": model, "ok": ok, "error": ""})
                if ok and not selected:
                    selected = model
            except Exception as exc:  # noqa: BLE001
                results.append({"model": model, "ok": False, "error": mask_secret(exc, self._api_key())})
        return {"ok": bool(selected), "selected_model": selected, "results": results}

    @staticmethod
    def _extract_content(data: Any) -> str:
        if isinstance(data, dict) and "choices" in data:
            message = data["choices"][0].get("message", {})
            content = message.get("content") or message.get("reasoning_content")
            if content:
                return str(content)
            raise RuntimeError(
                "AI response message has no content; fields="
                + ",".join(sorted(str(key) for key in message.keys()))
            )
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        raise RuntimeError("Zhipu response is not an object")

    @staticmethod
    def _parse_json_content(content: str) -> Dict[str, object]:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            if start < 0:
                raise
            data, _ = json.JSONDecoder().raw_decode(text[start:])
        if not isinstance(data, dict):
            raise ValueError("AI response must be a JSON object")
        return data

    def analyze_assets(self, candidate: CandidateSKU, asset_manifest: AssetManifest) -> Dict[str, object]:
        payload = {
            "task": "analyze_shopee_asset_manifest",
            "candidate": candidate.to_dict(),
            "assets": asset_manifest.to_dict(),
            "rules": [
                "Select one buyer-safe main image and up to 8 buyer-safe detail images.",
                "Mark OEM/ODM/factory/wholesale/supplier-facing images unsafe.",
                "Return product info only when visible from filenames or images metadata.",
            ],
        }
        result = self.request_json(
            resolve_prompt(self, "image_analysis", ""),
            payload,
            ["main_image", "detail_images", "unsafe_images", "product_info_from_images"],
        )
        validation = validate_asset_analysis_result(result)
        if not validation.ok:
            raise RuntimeError("AI asset analysis JSON validation failed: " + "; ".join(validation.errors))
        return result

    def generate_search_keywords(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        product_info: Mapping[str, object],
    ) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        result = self.request_json(
            resolve_prompt(self, "keyword_generation", ""),
            {"task": "generate_search_keywords", "candidate": candidate.to_dict(), "product_info_from_images": safe_info},
            ["search_keywords"],
        )
        validation = validate_search_keywords_result(result)
        if not validation.ok:
            raise RuntimeError("AI search keyword JSON validation failed: " + "; ".join(validation.errors))
        return result

    def analyze_competitor_titles(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
        competitors: Iterable[Mapping[str, object]],
        thinking_enabled: bool = True,
        reasoning_strength: str = "maximum",
    ) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        result = self.request_json(
            resolve_prompt(self, "competitor_title_analysis", ""),
            {
                "task": "analyze_competitors_and_generate_title",
                "candidate": candidate.to_dict(),
                "product_info_from_images": safe_info,
                "competitors": list(competitors),
                "generation_settings": {
                    "thinking_enabled": bool(thinking_enabled),
                    "reasoning_strength": normalize_title_reasoning_strength(reasoning_strength),
                },
            },
            ["final_title", "competitor_analysis", "removed_keywords", "warnings"],
            thinking_enabled=bool(thinking_enabled),
            reasoning_strength=reasoning_strength,
        )
        result["final_title"] = _limit_shopee_title(result.get("final_title"))
        validation = validate_title_analysis_result(result)
        if not validation.ok:
            raise RuntimeError("AI title analysis JSON validation failed: " + "; ".join(validation.errors))
        return result

    def generate_listing(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        competitors: Iterable[Mapping[str, object]],
    ) -> Dict[str, object]:
        asset_result = self.analyze_assets(candidate, asset_manifest)
        product_info = asset_result.get("product_info_from_images", {})
        safe_info = objective_product_info_for_text(product_info if isinstance(product_info, Mapping) else {})
        title_result = self.analyze_competitor_titles(candidate, safe_info, competitors)
        placeholders = self.request_json(
            resolve_prompt(self, "description_generation", ""),
            {
                "task": "generate_description_placeholders",
                "candidate": candidate.to_dict(),
                "product_info_from_images": safe_info,
            },
            ["description_placeholders", "seo_keywords"],
        )
        seo_validation = validate_seo_keywords_result(placeholders.get("seo_keywords", []))
        if not seo_validation.ok:
            raise RuntimeError("AI SEO keyword JSON validation failed: " + "; ".join(seo_validation.errors))
        category = self.suggest_category(candidate, safe_info)
        return {
            "title": title_result["final_title"],
            "title_keywords": _flatten_reused_keywords(title_result.get("competitor_analysis", [])),
            "description_placeholders": placeholders["description_placeholders"],
            "seo_keywords": placeholders.get("seo_keywords", []),
            "category_suggestion": category.get("category_suggestion", {"path": "", "confidence": 0, "source": "manual"}),
            "attribute_suggestions": [{"name": "Shelf Life", "value": "36 months", "confidence": 0.8}],
            "image_selection": {
                "main_image": asset_result.get("main_image", ""),
                "detail_images": asset_result.get("detail_images", []),
                "sku_images": asset_manifest.sku_images,
                "unsafe_images": asset_result.get("unsafe_images", []),
            },
            "warnings": list(title_result.get("warnings", [])),
            "product_info_from_images": safe_info,
            "search_keywords": self.generate_search_keywords(candidate, asset_manifest, safe_info).get("search_keywords", []),
            "competitor_analysis": title_result.get("competitor_analysis", []),
            "removed_keywords": title_result.get("removed_keywords", []),
        }

    def generate_description_placeholders(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
    ) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        result = self.request_json(
            resolve_prompt(self, "description_generation", ""),
            {
                "task": "generate_description_placeholders",
                "candidate": candidate.to_dict(),
                "product_info_from_images": safe_info,
            },
            ["description_placeholders"],
        )
        placeholders = result.get("description_placeholders", {})
        if not isinstance(placeholders, dict):
            raise RuntimeError("AI description placeholder JSON validation failed: description_placeholders must be an object")
        for key in ["PAIN_POINTS", "BENEFITS", "SPECIFICATIONS", "USAGE"]:
            if not isinstance(placeholders.get(key), str) or not placeholders.get(key, "").strip():
                raise RuntimeError(f"AI description placeholder JSON validation failed: {key} is required")
        return result

    def suggest_category(self, candidate: CandidateSKU, product_info: Mapping[str, object]) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        result = self.request_json(
            resolve_prompt(self, "category_selection", "Suggest one Shopee Malaysia category using only objective image facts. Write all explanations in English."),
            {"task": "suggest_category", "candidate": candidate.to_dict(), "product_info_from_images": safe_info},
            ["category_suggestion"],
        )
        return result


class NvidiaDualProvider(AIProvider):
    """Run the selected real model IDs, with OpenAI as the default API."""

    def __init__(
        self,
        config: AIConfig,
        prompts_dir: Path,
        *,
        request_controller: NvidiaRequestController | None = None,
        cache_dir: Path | None = None,
    ):
        load_project_env(PROJECT_ROOT / ".env")
        self.config = config
        self.prompts_dir = prompts_dir
        self.last_used_models: Dict[str, str] = {}
        self.last_vision_attempts: list[Dict[str, object]] = []
        self.request_controller = request_controller or get_nvidia_request_controller()
        self.request_batch_id = current_nvidia_request_batch_id()
        self.request_task_id = current_nvidia_request_task_id()
        self.status_callback: Optional[Callable[[Dict[str, object]], None]] = None
        self.cancellation_check: Optional[Callable[[], bool]] = None
        self.response_cache = AIResponseCache(cache_dir) if cache_dir else None
        self.last_request_used_cache = False
        self._request_local = threading.local()
        self.rate_limit_report: Dict[str, object] = dict(self.request_controller.rate_limit_report)
        # Description generation uses the streaming channel so the GUI can show live model output.
        self.description_reasoning_callback: Callable[[Dict[str, object]], None] = lambda event: None

    def request_text_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, object],
        required_keys: Iterable[str],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        model_override: str = "",
    ) -> Dict[str, object]:
        settings_override = self._text_settings(model_override) if str(model_override).strip() else None
        return self._request_json(
            "text",
            system_prompt,
            user_payload,
            required_keys,
            reasoning_callback=reasoning_callback,
            settings_override=settings_override,
        )

    def request_multimodal_json(
        self,
        model: str,
        system_prompt: str,
        user_payload: Mapping[str, object],
        image_paths: Iterable[str],
        required_keys: Iterable[str],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> Dict[str, object]:
        """Run a text workflow with product images through one selected multimodal model."""
        return self._request_json(
            "text",
            system_prompt,
            user_payload,
            required_keys,
            image_paths,
            reasoning_callback=reasoning_callback,
            settings_override=self._text_settings(model),
        )

    def request_vision_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, object],
        image_paths: Iterable[str],
        required_keys: Iterable[str],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> Dict[str, object]:
        attempts: list[str] = []
        self.last_vision_attempts = []
        image_path_list = list(image_paths)
        required_key_list = list(required_keys)
        # Use only the model selected in Step 0; do not silently switch models.
        models = self._vision_model_order()
        for index, model in enumerate(models):
            file_name = str(user_payload.get("file_name", ""))
            if reasoning_callback:
                reasoning_callback(
                    {
                        "model": model,
                        "task": str(user_payload.get("task", "vision")),
                        "file_name": file_name,
                        "reasoning_delta": "",
                        "content_delta": "",
                        "status": "switching" if index else "running",
                        "reset_text": index > 0,
                    }
                )
            try:
                result = self.request_vision_model_json(
                    model,
                    system_prompt,
                    user_payload,
                    image_path_list,
                    required_key_list,
                    reasoning_callback=reasoning_callback,
                )
                self.last_vision_attempts.append({"model": model, "ok": True, "error": ""})
                if index:
                    self.rate_limit_report["fallback_used"] = model
                return result
            except Exception as exc:  # noqa: BLE001
                error = self._mask_vision_secrets(exc)
                if reasoning_callback and self._is_incomplete_json_error(error):
                    reasoning_callback(
                        {
                            "model": model,
                            "task": str(user_payload.get("task", "vision")),
                            "file_name": file_name,
                            "reasoning_delta": "\nThe streamed JSON was incomplete. Retrying the same model with a non-streaming request.\n",
                            "content_delta": "",
                            "status": "retrying_full_response",
                        }
                    )
                    try:
                        result = self.request_vision_model_json(
                            model,
                            system_prompt,
                            user_payload,
                            image_path_list,
                            required_key_list,
                            reasoning_callback=None,
                        )
                        self.last_vision_attempts.append(
                            {
                                "model": model,
                                "ok": True,
                                "error": "",
                                "recovered_with_full_response": True,
                            }
                        )
                        reasoning_callback(
                            {
                                "model": model,
                                "task": str(user_payload.get("task", "vision")),
                                "file_name": file_name,
                                "reasoning_delta": "",
                                "content_delta": "",
                                "status": "completed",
                            }
                        )
                        return result
                    except Exception as full_response_exc:  # noqa: BLE001
                        full_response_error = self._mask_vision_secrets(
                            full_response_exc
                        )
                        error = (
                            f"{error}; the non-streaming retry of the same model also failed: "
                            f"{full_response_error}"
                        )
                attempts.append(f"{model}: {error}")
                self.last_vision_attempts.append({"model": model, "ok": False, "error": error})
                if reasoning_callback:
                    reasoning_callback(
                        {
                            "model": model,
                            "task": str(user_payload.get("task", "vision")),
                            "file_name": file_name,
                            "reasoning_delta": "",
                            "content_delta": "",
                            "status": "model_failed",
                        }
                    )
        raise RuntimeError("Selected vision model failed: " + " | ".join(attempts))

    def request_vision_model_json(
        self,
        model: str,
        system_prompt: str,
        user_payload: Mapping[str, object],
        image_paths: Iterable[str],
        required_keys: Iterable[str],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> Dict[str, object]:
        """Call one exact vision model without automatic failover."""
        return self._request_json(
            "vision",
            system_prompt,
            user_payload,
            required_keys,
            image_paths,
            reasoning_callback=reasoning_callback,
            settings_override=self._vision_settings(model),
        )

    def _request_json(
        self,
        kind: str,
        system_prompt: str,
        user_payload: Mapping[str, object],
        required_keys: Iterable[str],
        image_paths: Iterable[str] = (),
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        settings_override: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        settings = dict(settings_override) if settings_override is not None else self._settings(kind)
        image_path_list = list(image_paths)
        task = str(user_payload.get("task", kind))
        # Description generation always makes a fresh request for explicit user retries.
        use_cache = task != "generate_description_placeholders"
        cache_key = ""
        self.last_request_used_cache = False
        self._request_local.used_cache = False
        if self.response_cache and use_cache:
            cache_key = self.response_cache.make_key(
                str(settings["model"]),
                system_prompt,
                user_payload,
                image_path_list,
            )
            cached = self.response_cache.load(cache_key)
            if cached is not None and all(key in cached for key in required_keys):
                self.last_request_used_cache = True
                self._request_local.used_cache = True
                self.last_used_models[kind] = str(settings["model"])
                if reasoning_callback:
                    reasoning_callback(
                        {
                            "model": str(settings["model"]),
                            "task": str(user_payload.get("task", kind)),
                            "file_name": str(user_payload.get("file_name", "")),
                            "reasoning_delta": "",
                            "content_delta": "",
                            "status": "cached",
                        }
                    )
                return cached
        content: object = json.dumps(user_payload, ensure_ascii=False)
        if image_path_list:
            parts: list[Dict[str, object]] = [{"type": "text", "text": content}]
            for path in image_path_list:
                data_url = self._image_data_url(Path(path))
                if data_url:
                    parts.append({"type": "image_url", "image_url": {"url": data_url}})
            content = parts
        text_thinking_controlled_task = kind == "text" and task in {
            "generate_search_keywords",
            "analyze_competitors_and_generate_title",
            "generate_description_placeholders",
        }
        vision_thinking_controlled_task = kind == "vision" and task == "analyze_single_shopee_image"
        raw_generation_settings = user_payload.get("generation_settings", {})
        generation_settings = raw_generation_settings if isinstance(raw_generation_settings, Mapping) else {}
        text_thinking_mode = normalize_text_thinking_mode(
            generation_settings.get("thinking_mode"),
            generation_settings.get("thinking_enabled"),
        )
        raw_text_reasoning_strength = normalize_text_reasoning_strength(
            generation_settings.get("reasoning_strength", "official_default")
        )
        text_uses_official_defaults = (
            text_thinking_controlled_task
            and text_thinking_mode == "official_default"
            and raw_text_reasoning_strength == "official_default"
        )
        vision_thinking_mode = normalize_vision_thinking_mode(
            generation_settings.get("thinking_mode"),
            generation_settings.get("thinking_enabled"),
        )
        raw_vision_reasoning_strength = normalize_vision_reasoning_strength(
            generation_settings.get("reasoning_strength", "official_default")
        )
        vision_uses_official_defaults = (
            vision_thinking_controlled_task
            and vision_thinking_mode == "official_default"
            and raw_vision_reasoning_strength == "official_default"
        )
        thinking_enabled = (
            vision_thinking_mode != "disabled"
            if vision_thinking_controlled_task
            else text_thinking_mode != "disabled"
        )
        reasoning_strength = (
            (
                "medium"
                if raw_vision_reasoning_strength == "official_default"
                else raw_vision_reasoning_strength
            )
            if vision_thinking_controlled_task
            else (
                "medium"
                if raw_text_reasoning_strength == "official_default"
                else raw_text_reasoning_strength
            )
        )
        request_system_prompt = system_prompt
        if text_thinking_controlled_task and not text_uses_official_defaults:
            instruction_fn = {
                "generate_search_keywords": keyword_reasoning_instruction,
                "analyze_competitors_and_generate_title": title_reasoning_instruction,
                "generate_description_placeholders": description_reasoning_instruction,
            }[task]
            request_system_prompt += "\n" + instruction_fn(
                thinking_enabled,
                reasoning_strength,
            )
        elif vision_thinking_controlled_task:
            vision_instruction = vision_reasoning_instruction(
                vision_thinking_mode,
                reasoning_strength,
            )
            if vision_instruction:
                request_system_prompt += "\n" + vision_instruction
        text_reasoning_token_budgets = model_reasoning_profile(
            settings.get("model"),
            "text",
        )["output_budgets"]
        text_thinking_max_tokens = (
            int(settings["max_tokens"])
            if text_uses_official_defaults
            else text_reasoning_token_budgets[reasoning_strength]
            if thinking_enabled
            else 8192
        )
        vision_thinking_max_tokens = min(
            int(settings["max_tokens"]),
            (
                VISION_REASONING_TOKEN_BUDGETS[reasoning_strength]
            )
            if thinking_enabled
            else 4096,
        )
        body_payload: Dict[str, object] = {
            "model": settings["model"],
            "messages": [
                {
                    "role": "system",
                    "content": request_system_prompt
                    + "\nReturn exactly one valid JSON object without a Markdown code fence.",
                },
                {"role": "user", "content": content},
            ],
            "stream": bool(reasoning_callback),
        }
        sampling_profile = str(settings.get("sampling_profile") or "")
        token_limit = (
            text_thinking_max_tokens
            if text_thinking_controlled_task
            else settings["max_tokens"]
            if vision_uses_official_defaults
            else vision_thinking_max_tokens
            if vision_thinking_controlled_task
            else settings["max_tokens"]
        )
        body_payload[
            "max_completion_tokens" if sampling_profile == "openai" else "max_tokens"
        ] = token_limit
        if sampling_profile == "openai":
            body_payload["response_format"] = {"type": "json_object"}
            requested_mode = (
                vision_thinking_mode
                if vision_thinking_controlled_task
                else text_thinking_mode
            )
            if requested_mode != "official_default":
                if requested_mode == "disabled":
                    body_payload["reasoning_effort"] = "none"
                else:
                    effort = "max" if reasoning_strength == "maximum" else reasoning_strength
                    body_payload["reasoning_effort"] = effort
        if kind == "text":
            if sampling_profile == "openai":
                pass
            elif sampling_profile == "agnes":
                if (
                    text_thinking_controlled_task
                    and text_thinking_mode != "official_default"
                ):
                    body_payload["chat_template_kwargs"] = {
                        "enable_thinking": thinking_enabled,
                    }
            elif sampling_profile == "minimax":
                if (
                    text_thinking_controlled_task
                    and text_thinking_mode != "official_default"
                ):
                    body_payload["chat_template_kwargs"] = {
                        "thinking_mode": text_thinking_mode,
                    }
                body_payload.update({"temperature": 1, "top_p": 0.95})
            else:
                body_payload.update({"temperature": 1, "top_p": 1, "seed": 42})
                if (
                    not text_thinking_controlled_task
                    or text_thinking_mode != "official_default"
                ):
                    body_payload["chat_template_kwargs"] = {
                        "enable_thinking": (
                            thinking_enabled
                            if text_thinking_controlled_task
                            else settings["enable_thinking"]
                        ),
                        "clear_thinking": (
                            not thinking_enabled
                            if text_thinking_controlled_task
                            else settings["clear_thinking"]
                        ),
                    }
        elif sampling_profile == "openai":
            pass
        elif sampling_profile == "agnes":
            if vision_thinking_controlled_task and not vision_uses_official_defaults:
                body_payload["chat_template_kwargs"] = {
                    "enable_thinking": thinking_enabled,
                }
            if not vision_uses_official_defaults:
                body_payload.update({"temperature": 0.6, "top_p": 0.95})
        elif settings.get("sampling_profile") == "minimax":
            if vision_thinking_controlled_task and not vision_uses_official_defaults:
                body_payload["chat_template_kwargs"] = {
                    "thinking_mode": vision_thinking_mode,
                }
            body_payload.update({"temperature": 1, "top_p": 0.95})
        else:
            if vision_thinking_controlled_task and not vision_uses_official_defaults:
                if vision_thinking_mode != "adaptive":
                    body_payload["chat_template_kwargs"] = {
                        "enable_thinking": thinking_enabled,
                    }
            body_payload.update(
                {
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "presence_penalty": 0,
                    "repetition_penalty": 1,
                }
            )
        request_body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        request_attempt = 0

        def perform_request() -> Dict[str, object]:
            nonlocal request_attempt
            request_attempt += 1
            if request_attempt > 1 and reasoning_callback:
                reasoning_callback(
                    {
                        "model": str(settings["model"]),
                        "task": task,
                        "file_name": str(user_payload.get("file_name", "")),
                        "reasoning_delta": "",
                        "content_delta": "",
                        "status": "reconnecting",
                        "reset_text": True,
                    }
                )

            def open_and_read_response() -> tuple[str, Optional[Dict[str, object]]]:
                request = urllib.request.Request(
                    settings["endpoint"],
                    data=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings['api_key']}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(
                    request,
                    timeout=float(settings["timeout_seconds"]),
                ) as response:
                    if reasoning_callback:
                        streamed_content = self._read_streaming_content(
                            response,
                            reasoning_callback,
                            model=str(settings["model"]),
                            task=task,
                            file_name=str(user_payload.get("file_name", "")),
                            cancellation_check=self.cancellation_check,
                        )
                        return streamed_content, None
                    response_data = json.loads(response.read().decode("utf-8"))
                    return "", response_data

            try:
                content_text, data = open_and_read_response()
            except urllib.error.HTTPError as exc:
                response_text = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"HTTP {exc.code}: "
                    f"{mask_secret(response_text[:1000], str(settings['api_key']))}"
                ) from None
            if data is not None:
                content_text = ZhipuProvider._extract_content(data)
            parsed = ZhipuProvider._parse_json_content(content_text)
            missing = [key for key in required_keys if key not in parsed]
            if missing:
                raise ValueError("missing keys: " + ", ".join(missing))
            return parsed

        try:
            parsed = self.request_controller.execute(
                perform_request,
                model=str(settings["model"]),
                step=task,
                max_retries=4,
                batch_id=self.request_batch_id,
                task_id=self.request_task_id,
                status_callback=self.status_callback,
                cancellation_check=self.cancellation_check,
            )
            self.rate_limit_report = dict(self.request_controller.rate_limit_report)
            if self.response_cache and cache_key and use_cache:
                self.response_cache.save(cache_key, parsed)
            self.last_used_models[kind] = str(settings["model"])
            return parsed
        except NvidiaRateLimitExhausted as exc:
            self.rate_limit_report = dict(exc.report)
            raise
        except Exception as exc:  # noqa: BLE001
            if (
                kind == "text"
                and reasoning_callback
                and self._is_incomplete_json_error(exc)
            ):
                reasoning_callback(
                    {
                        "model": str(settings["model"]),
                        "task": task,
                        "file_name": str(user_payload.get("file_name", "")),
                        "reasoning_delta": (
                            "The streamed JSON was incomplete. Retrying the same model with a non-streaming request.\n"
                        ),
                        "content_delta": "",
                        "status": "retrying_full_response",
                        "reset_text": True,
                    }
                )
                try:
                    recovered = self._request_json(
                        kind,
                        system_prompt,
                        user_payload,
                        required_keys,
                        image_path_list,
                        reasoning_callback=None,
                        settings_override=settings,
                    )
                except Exception as full_response_exc:  # noqa: BLE001
                    exc = RuntimeError(
                        f"{exc}; the non-streaming retry of the same model also failed: {full_response_exc}"
                    )
                else:
                    reasoning_callback(
                        {
                            "model": str(settings["model"]),
                            "task": task,
                            "file_name": str(user_payload.get("file_name", "")),
                            "reasoning_delta": "",
                            "content_delta": "",
                            "status": "completed",
                        }
                    )
                    return recovered
            provider_name = str(settings.get("provider_name") or settings.get("model") or "AI")
            raise RuntimeError(f"{provider_name} {kind} model request failed: {mask_secret(exc, str(settings['api_key']))}") from None

    @staticmethod
    def _read_streaming_content(
        response: object,
        callback: Callable[[Dict[str, object]], None],
        *,
        model: str,
        task: str,
        file_name: str,
        cancellation_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        for raw_line in response:
            if cancellation_check and cancellation_check():
                raise RuntimeError("The AI request was cancelled by a newer retry or by the user")
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_text = line[5:].strip()
            if data_text == "[DONE]":
                break
            if not data_text:
                continue
            chunk = json.loads(data_text)
            choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
            delta = choices[0].get("delta", {}) if choices else {}
            reasoning_delta = str(delta.get("reasoning_content") or "")
            content_delta = str(delta.get("content") or "")
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
            if content_delta:
                content_parts.append(content_delta)
            if reasoning_delta or content_delta:
                callback(
                    {
                        "model": model,
                        "task": task,
                        "file_name": file_name,
                        "reasoning_delta": reasoning_delta,
                        "content_delta": content_delta,
                        "status": "streaming",
                    }
                )
        callback(
            {
                "model": model,
                "task": task,
                "file_name": file_name,
                "reasoning_delta": "",
                "content_delta": "",
                "status": "completed",
            }
        )
        content_text = "".join(content_parts)
        return content_text if content_text.strip() else "".join(reasoning_parts)

    def _settings(self, kind: str) -> Dict[str, object]:
        if kind == "vision":
            return self._vision_settings(self._settings_model("vision"))
        return self._text_settings(
            os.environ.get("STEP6_AI_MODEL", "").strip()
            or os.environ.get("OPENAI_MODEL", "").strip()
            or OPENAI_DEFAULT_MODEL
        )

    def _text_settings(self, model: str) -> Dict[str, object]:
        normalized_model = str(model or "").strip() or OPENAI_DEFAULT_MODEL
        is_openai = normalized_model.casefold() == OPENAI_DEFAULT_MODEL.casefold()
        is_agnes = normalized_model.casefold() == AGNES_TEXT_DEFAULT_MODEL.casefold()
        is_minimax = normalized_model.casefold() == NVIDIA_MINIMAX_VISION_MODEL.casefold()
        is_qwen = normalized_model.casefold() == NVIDIA_VISION_DEFAULT_MODEL.casefold()
        if normalized_model not in VISION_TEXT_AI_MODELS:
            raise RuntimeError("Select one of the model IDs offered by this step")
        if is_openai:
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. Add it in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("OPENAI_BASE_URL", "").strip()
                or OPENAI_DEFAULT_BASE_URL
            )
            max_tokens = int(
                os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "32768")
                or "32768"
            )
            default_timeout = max(self.config.timeout_seconds, 900)
            timeout_seconds = float(
                os.environ.get(
                    "OPENAI_TIMEOUT_SECONDS",
                    str(default_timeout),
                )
                or default_timeout
            )
            request_model = normalized_model
            sampling_profile = "openai"
            provider_name = normalized_model
            thinking = True
            clear_thinking = False
        elif is_minimax:
            key = (
                os.environ.get("NVIDIA_MINIMAX_VISION_API_KEY", "").strip()
                or os.environ.get("NVIDIA_VISION_API_KEY", "").strip()
                or os.environ.get("NVIDIA_TEXT_API_KEY", "").strip()
            )
            if not key:
                raise RuntimeError(
                    "NVIDIA MiniMax M3 API Key is not configured. Add it in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("NVIDIA_MINIMAX_VISION_BASE_URL", "").strip()
                or NVIDIA_DEFAULT_BASE_URL
            )
            max_tokens = int(
                os.environ.get("NVIDIA_MINIMAX_VISION_MAX_TOKENS", "8192")
                or "8192"
            )
            default_timeout = max(self.config.timeout_seconds, 900)
            timeout_seconds = float(
                os.environ.get(
                    "NVIDIA_MINIMAX_VISION_TIMEOUT_SECONDS",
                    str(default_timeout),
                )
                or default_timeout
            )
            request_model = normalized_model
            sampling_profile = "minimax"
            provider_name = normalized_model
            thinking = False
            clear_thinking = False
        elif is_agnes:
            key = (
                os.environ.get("AGNES_API_KEY", "").strip()
                or os.environ.get("AGNES_VISION_API_KEY", "").strip()
            )
            if not key:
                raise RuntimeError(
                    "AGNES_API_KEY is not configured. Add the Agnes key in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("AGNES_TEXT_BASE_URL", "").strip()
                or os.environ.get("AGNES_VISION_BASE_URL", "").strip()
                or AGNES_DEFAULT_BASE_URL
            )
            max_tokens = int(
                os.environ.get("AGNES_TEXT_MAX_TOKENS", "65536") or "65536"
            )
            default_timeout = max(self.config.timeout_seconds, 900)
            timeout_seconds = float(
                os.environ.get("AGNES_TEXT_TIMEOUT_SECONDS", str(default_timeout))
                or default_timeout
            )
            sampling_profile = "agnes"
            provider_name = normalized_model
            thinking = False
            clear_thinking = False
        elif is_qwen:
            key = os.environ.get("NVIDIA_VISION_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "NVIDIA_VISION_API_KEY is not configured. Add it in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("NVIDIA_VISION_BASE_URL", "").strip()
                or NVIDIA_DEFAULT_BASE_URL
            )
            max_tokens = int(
                os.environ.get("NVIDIA_VISION_MAX_TOKENS", "16384") or "16384"
            )
            timeout_seconds = float(
                os.environ.get("NVIDIA_VISION_TIMEOUT_SECONDS", "900") or "900"
            )
            request_model = normalized_model
            sampling_profile = "qwen"
            provider_name = normalized_model
            thinking = True
            clear_thinking = False
        else:
            key = os.environ.get("NVIDIA_TEXT_API_KEY", "")
            if not key:
                raise RuntimeError(
                    "NVIDIA_TEXT_API_KEY is not configured. Add it in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("NVIDIA_TEXT_BASE_URL", "").strip()
                or NVIDIA_DEFAULT_BASE_URL
            )
            max_tokens = int(
                os.environ.get("NVIDIA_TEXT_MAX_TOKENS", "16384") or "16384"
            )
            default_timeout = max(self.config.timeout_seconds, 900)
            timeout_seconds = float(
                os.environ.get("NVIDIA_TEXT_TIMEOUT_SECONDS", str(default_timeout))
                or default_timeout
            )
            sampling_profile = "nvidia_glm"
            provider_name = normalized_model
            thinking = (
                os.environ.get("NVIDIA_TEXT_ENABLE_THINKING", "true")
                .strip()
                .lower()
                in {"1", "true", "yes", "on"}
            )
            clear_thinking = (
                os.environ.get("NVIDIA_TEXT_CLEAR_THINKING", "false")
                .strip()
                .lower()
                in {"1", "true", "yes", "on"}
            )
            request_model = normalized_model
        if is_agnes:
            request_model = normalized_model
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        return {
            "api_key": key,
            "endpoint": endpoint,
            "model": request_model,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "enable_thinking": thinking,
            "clear_thinking": clear_thinking,
            "sampling_profile": sampling_profile,
            "provider_name": provider_name,
        }

    def _vision_settings(self, model: str) -> Dict[str, object]:
        normalized_model = str(model or "").strip() or OPENAI_DEFAULT_MODEL
        is_openai = normalized_model.casefold() == OPENAI_DEFAULT_MODEL.casefold()
        is_agnes = normalized_model.casefold() == AGNES_VISION_DEFAULT_MODEL.casefold()
        is_minimax = normalized_model.casefold() == NVIDIA_MINIMAX_VISION_MODEL.casefold()
        if normalized_model not in MULTIMODAL_AI_MODELS:
            raise RuntimeError("Select one of the multimodal model IDs offered by Step 3")
        if is_openai:
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. Add it in .env or save it from the GUI."
                )
            base_url = (
                os.environ.get("OPENAI_BASE_URL", "").strip()
                or OPENAI_DEFAULT_BASE_URL
            )
            endpoint = base_url.rstrip("/")
            if not endpoint.endswith("/chat/completions"):
                endpoint += "/chat/completions"
            max_tokens = int(
                os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "32768") or "32768"
            )
            timeout_seconds = float(
                os.environ.get(
                    "OPENAI_TIMEOUT_SECONDS",
                    str(self.config.timeout_seconds),
                )
                or self.config.timeout_seconds
            )
            return {
                "api_key": key,
                "endpoint": endpoint,
                "model": normalized_model,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
                "enable_thinking": True,
                "clear_thinking": False,
                "sampling_profile": "openai",
                "provider_name": normalized_model,
            }
        prefix = "AGNES_VISION" if is_agnes else "NVIDIA_MINIMAX_VISION" if is_minimax else "NVIDIA_VISION"
        other_key_name = "" if is_agnes else "NVIDIA_VISION_API_KEY" if is_minimax else "NVIDIA_MINIMAX_VISION_API_KEY"
        key = (
            os.environ.get("AGNES_API_KEY", "").strip()
            or os.environ.get(f"{prefix}_API_KEY", "").strip()
            if is_agnes
            else os.environ.get(f"{prefix}_API_KEY", "")
        )
        if not key and other_key_name:
            key = os.environ.get(other_key_name, "")
        if not key:
            raise RuntimeError(
                f"{prefix}_API_KEY is not configured. Add it in .env or save it from the GUI."
            )
        default_base_url = AGNES_DEFAULT_BASE_URL if is_agnes else NVIDIA_DEFAULT_BASE_URL
        base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip() or default_base_url
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        default_max_tokens = "8192" if is_minimax else "16384"
        max_tokens = int(os.environ.get(f"{prefix}_MAX_TOKENS", default_max_tokens) or default_max_tokens)
        timeout_seconds = float(
            os.environ.get(f"{prefix}_TIMEOUT_SECONDS", str(self.config.timeout_seconds))
            or self.config.timeout_seconds
        )
        return {
            "api_key": key,
            "endpoint": endpoint,
            "model": normalized_model,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout_seconds,
            "enable_thinking": False,
            "clear_thinking": False,
            "sampling_profile": "agnes" if is_agnes else "minimax" if is_minimax else "qwen",
            "provider_name": normalized_model,
        }

    def _vision_model_order(self) -> list[str]:
        selected = (
            os.environ.get("STEP3_AI_MODEL", "").strip()
            or os.environ.get("OPENAI_MODEL", "").strip()
            or OPENAI_DEFAULT_MODEL
        )
        return [selected]

    @staticmethod
    def _mask_vision_secrets(value: object) -> str:
        text = str(value)
        for key_name in [
            "OPENAI_API_KEY",
            "AGNES_API_KEY",
            "AGNES_VISION_API_KEY",
            "NVIDIA_VISION_API_KEY",
            "NVIDIA_MINIMAX_VISION_API_KEY",
        ]:
            text = mask_secret(text, os.environ.get(key_name, ""))
        return text

    @staticmethod
    def _is_incomplete_json_error(value: object) -> bool:
        text = str(value).casefold()
        return any(
            marker in text
            for marker in (
                "unterminated string",
                "expecting property name enclosed in double quotes",
                "expecting ',' delimiter",
                "expecting ':' delimiter",
                "expecting value",
                "extra data",
                "invalid control character",
                "missing keys:",
            )
        )

    @staticmethod
    def _image_data_url(path: Path) -> str:
        if not path.is_file():
            return ""
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def check_models(self) -> Dict[str, object]:
        results: list[Dict[str, object]] = []
        vision_models = self._vision_model_order()
        for model in vision_models:
            try:
                data = self.request_vision_model_json(
                    model,
                    'This is a connectivity check. Return one non-empty JSON object, preferably {"ok": true}.',
                    {"task": "selected_vision_check"},
                    [],
                    [],
                )
                results.append(
                    {
                        "model": model,
                        "kind": "vision_selected",
                        "ok": isinstance(data, dict) and bool(data),
                        "response_fields": sorted(str(key) for key in data.keys())[:20],
                        "error": "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "model": model,
                        "kind": "vision_selected",
                        "ok": False,
                        "error": self._mask_vision_secrets(exc),
                    }
                )
        try:
            data = self._request_json(
                "text",
                'This is a connectivity check. Return one non-empty JSON object, preferably {"ok": true}.',
                {"task": "selected_text_check"},
                [],
            )
            results.append(
                {
                    "model": self.last_used_models.get("text", ""),
                    "kind": "text",
                    "ok": isinstance(data, dict) and bool(data),
                    "response_fields": sorted(str(key) for key in data.keys())[:20],
                    "error": "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "model": self._settings_model("text"),
                    "kind": "text",
                    "ok": False,
                    "error": self._mask_vision_secrets(exc),
                }
            )
        vision_ok = any(item["ok"] for item in results if str(item["kind"]).startswith("vision_"))
        text_ok = any(item["ok"] for item in results if item["kind"] == "text")
        return {"ok": vision_ok and text_ok, "all_models_ok": all(item["ok"] for item in results), "results": results}

    def _settings_model(self, kind: str) -> str:
        step_key = "STEP3_AI_MODEL" if kind == "vision" else "STEP6_AI_MODEL"
        legacy_key = "NVIDIA_VISION_MODEL" if kind == "vision" else "NVIDIA_TEXT_MODEL"
        return (
            os.environ.get(step_key, "").strip()
            or os.environ.get("OPENAI_MODEL", "").strip()
            or os.environ.get(legacy_key, "").strip()
            or OPENAI_DEFAULT_MODEL
        )

    def analyze_assets(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        thinking_enabled: Optional[bool] = None,
        thinking_mode: str = "enabled",
        reasoning_strength: str = "maximum",
        selection_only: bool = False,
    ) -> Dict[str, object]:
        normalized_thinking_mode = normalize_vision_thinking_mode(
            thinking_mode,
            thinking_enabled,
        )
        targets = nvidia_vision_analysis_targets(asset_manifest)
        if not targets:
            raise RuntimeError("No images are available for the selected vision model")
        configured_prompt = resolve_prompt(
            self,
            "image_analysis",
            "",
        )
        if selection_only:
            prompt = (
                "Multimodal mode is active. Judge only whether this image helps a buyer make a purchase, recommend a main-image or detail-image role, "
                "and provide a 0-100 upload-order score. Asset-pack images may be used unless they contain OEM/ODM material or duplicate another image. "
                "Do not extract or return objective_record, and do not make advertising, compliance, or value judgments. "
                "The following is the user's Step 3 prompt; follow only its image-selection and ordering requirements:\n"
                + configured_prompt
            )
            required_keys = ["selection_assessment"]
            output_schema = vision_selection_only_output_schema()
        else:
            prompt = configured_prompt
            required_keys = ["objective_record", "selection_assessment"]
            output_schema = vision_analysis_output_schema()
        try:
            concurrency_limit = int(
                os.environ.get("VISION_CONCURRENCY")
                or os.environ.get("NVIDIA_VISION_CONCURRENCY", "8")
                or "8"
            )
        except ValueError:
            concurrency_limit = 8
        concurrency_limit = max(1, min(20, concurrency_limit))
        concurrency = min(len(targets), concurrency_limit)
        ordered_results: list[Optional[Dict[str, object]]] = [None] * len(targets)
        progress_lock = threading.Lock()
        progress: Dict[str, object] = {
            "current_file": "",
            "active_files": [],
            "concurrency": concurrency,
            "concurrency_limit": concurrency_limit,
            "active_concurrency": concurrency,
            "retry_round": 0,
            "total": len(targets),
            "completed": 0,
            "success": 0,
            "failed": 0,
            "cached": 0,
            "rate_limit_waiting": False,
            "items": [
                {"file_name": Path(path).name, "file_path": path, "folder_type": folder_type, "status": "pending"}
                for folder_type, path in targets
            ],
        }
        _publish_image_progress(progress_callback, progress)

        def analyze_target(
            target_index: int,
            folder_type: str,
            image_path: str,
            retry_round: int = 0,
        ) -> None:
            file_name = Path(image_path).name
            with progress_lock:
                active_files = progress.get("active_files", [])
                if isinstance(active_files, list) and file_name not in active_files:
                    active_files.append(file_name)
                progress["current_file"] = file_name
                progress_items = progress.get("items", [])
                if isinstance(progress_items, list):
                    progress_items[target_index]["status"] = (
                        f"retrying (round {retry_round})" if retry_round else "analyzing"
                    )
                _publish_image_progress(progress_callback, progress)
            try:
                request_args = (
                    {
                        "reasoning_callback": reasoning_callback,
                    }
                    if reasoning_callback
                    else {}
                )
                item = self.request_vision_json(
                    prompt,
                    {
                        "task": "analyze_single_shopee_image",
                        "candidate": candidate.to_dict(),
                        "file_name": file_name,
                        "folder_type": folder_type,
                        "output_schema": output_schema,
                        "generation_settings": {
                            "thinking_mode": normalized_thinking_mode,
                            "thinking_enabled": normalized_thinking_mode != "disabled",
                            "reasoning_strength": normalize_vision_reasoning_strength(reasoning_strength),
                        },
                    },
                    [image_path],
                    required_keys,
                    **request_args,
                )
                used_cache = bool(getattr(self._request_local, "used_cache", False))
                normalized = _normalize_single_image_result(
                    item,
                    file_name=file_name,
                    file_path=image_path,
                    folder_type=folder_type,
                    status="cached" if used_cache else "analysis_succeeded",
                    selection_only=selection_only,
                )
            except Exception as exc:  # noqa: BLE001
                normalized = {
                    "file_name": file_name,
                    "file_path": image_path,
                    "folder_type": folder_type,
                    "status": "analysis_failed",
                    "objective_record": _clean_objective_record(
                        {
                            "file_name": file_name,
                            "folder_type": folder_type,
                            "uncertainties": ["Image analysis failed; no objective facts were extracted."],
                        }
                    ),
                    "selection_assessment": {
                        "suitable_for_listing": False,
                        "recommended_role": "do_not_use",
                        "upload_score": 0,
                        "selection_reasons": [str(exc)[:300]],
                    },
                }
            with progress_lock:
                previous = ordered_results[target_index]
                ordered_results[target_index] = normalized
                if previous is None:
                    if normalized.get("status") == "analysis_failed":
                        progress["failed"] = int(progress["failed"]) + 1
                    else:
                        progress["success"] = int(progress["success"]) + 1
                        if normalized.get("status") == "cached":
                            progress["cached"] = int(progress["cached"]) + 1
                    progress["completed"] = int(progress["completed"]) + 1
                elif previous.get("status") == "analysis_failed" and normalized.get("status") != "analysis_failed":
                    progress["failed"] = max(0, int(progress["failed"]) - 1)
                    progress["success"] = int(progress["success"]) + 1
                    if normalized.get("status") == "cached":
                        progress["cached"] = int(progress["cached"]) + 1
                else:
                    normalized["retry_round"] = retry_round
                active_files = progress.get("active_files", [])
                if isinstance(active_files, list) and file_name in active_files:
                    active_files.remove(file_name)
                progress["current_file"] = active_files[-1] if isinstance(active_files, list) and active_files else file_name
                progress["rate_limit_waiting"] = bool(self.request_controller.status().get("rate_limited"))
                progress_items = progress.get("items", [])
                if isinstance(progress_items, list):
                    progress_items[target_index] = {
                        "file_name": normalized.get("file_name", ""),
                        "file_path": normalized.get("file_path", ""),
                        "folder_type": normalized.get("folder_type", ""),
                        "status": normalized.get("status", ""),
                    }
                _publish_image_progress(progress_callback, progress)

        def run_pass(indexes: list[int], workers: int, retry_round: int) -> None:
            if not indexes:
                return
            active_workers = min(len(indexes), max(1, workers))
            with progress_lock:
                progress["active_concurrency"] = active_workers
                progress["retry_round"] = retry_round
                _publish_image_progress(progress_callback, progress)
            with ThreadPoolExecutor(
                max_workers=active_workers,
                thread_name_prefix=f"vision-image-{retry_round}",
            ) as executor:
                futures = [
                    executor.submit(
                        analyze_target,
                        index,
                        targets[index][0],
                        targets[index][1],
                        retry_round,
                    )
                    for index in indexes
                ]
                for future in futures:
                    future.result()

        run_pass(list(range(len(targets))), concurrency, 0)
        for retry_round in range(1, 3):
            failed_indexes = [
                index
                for index, item in enumerate(ordered_results)
                if isinstance(item, dict) and item.get("status") == "analysis_failed"
            ]
            if not failed_indexes:
                break
            run_pass(failed_indexes, concurrency_limit, retry_round)
        with progress_lock:
            progress["active_concurrency"] = 0
            progress["active_files"] = []
            _publish_image_progress(progress_callback, progress)

        per_image_results = [item for item in ordered_results if isinstance(item, dict)]
        result = _summarize_single_image_results(asset_manifest, per_image_results, progress)
        if selection_only:
            result["product_info_from_images"] = {}
            result["objective_image_records"] = []
        validation = validate_asset_analysis_result(result)
        if not validation.ok:
            raise RuntimeError("Vision-model JSON validation failed: " + "; ".join(validation.errors))
        return result

    def generate_search_keywords(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        product_info: Mapping[str, object],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        thinking_enabled: Optional[bool] = None,
        reasoning_strength: str = "maximum",
        thinking_mode: str = "enabled",
        text_model: str = OPENAI_DEFAULT_MODEL,
        image_paths: Iterable[str] = (),
        multimodal_mode: bool = False,
    ) -> Dict[str, object]:
        normalized_thinking_mode = (
            "enabled" if thinking_enabled else "disabled"
        ) if thinking_enabled is not None else normalize_text_thinking_mode(thinking_mode)
        safe_info = objective_product_info_for_text(product_info)
        output_schema = {
            "type": "object",
            "required": ["search_keywords"],
            "properties": {
                "search_keywords": {
                    "type": "array",
                    "minItems": 5,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "required": ["english", "chinese_meaning", "why", "search_intent", "confidence"],
                        "properties": {
                            "english": {"type": "string"},
                            "chinese_meaning": {"type": "string"},
                            "why": {"type": "string"},
                            "search_intent": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                    },
                }
            },
        }
        prompt = resolve_prompt(
            self,
            "keyword_generation",
            "",
        )
        image_path_list = list(image_paths)
        if multimodal_mode:
            if not image_path_list:
                raise RuntimeError("Multimodal mode has no product images to send to the Step 5 model")
            prompt = MULTIMODAL_PRODUCT_PROMPT_PREFIX + "\n" + prompt
        user_payload: Dict[str, object] = {
            "task": "generate_search_keywords",
            "candidate": candidate.to_dict(),
            "output_schema": output_schema,
            "generation_settings": {
                "thinking_mode": normalized_thinking_mode,
                "thinking_enabled": normalized_thinking_mode != "disabled",
                "reasoning_strength": normalize_text_reasoning_strength(reasoning_strength),
            },
        }
        if multimodal_mode:
            user_payload["image_input_scope"] = "All detail images plus English asset images; use SKU images when no English asset images exist"
        else:
            user_payload["product_info_from_images"] = safe_info
        if multimodal_mode:
            result = self.request_multimodal_json(
                text_model,
                prompt,
                user_payload,
                image_path_list,
                ["search_keywords"],
                reasoning_callback=reasoning_callback,
            )
        else:
            result = self.request_text_json(
                prompt,
                user_payload,
                ["search_keywords"],
                reasoning_callback=reasoning_callback,
                model_override=text_model,
            )
        validation = validate_search_keywords_result(result)
        if not validation.ok:
            raise RuntimeError("Text-model JSON validation failed: " + "; ".join(validation.errors))
        return result

    def generate_description_placeholders(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        thinking_enabled: Optional[bool] = None,
        reasoning_strength: str = "maximum",
        thinking_mode: str = "enabled",
        text_model: str = OPENAI_DEFAULT_MODEL,
        image_paths: Iterable[str] = (),
        multimodal_mode: bool = False,
    ) -> Dict[str, object]:
        normalized_thinking_mode = (
            "enabled" if thinking_enabled else "disabled"
        ) if thinking_enabled is not None else normalize_text_thinking_mode(thinking_mode)
        safe_info = objective_product_info_for_text(product_info)
        prompt = resolve_prompt(
            self,
            "description_generation",
            "",
        )
        image_path_list = list(image_paths)
        if multimodal_mode:
            if not image_path_list:
                raise RuntimeError("Multimodal mode has no product images to send to the Step 7 model")
            prompt = MULTIMODAL_PRODUCT_PROMPT_PREFIX + "\n" + prompt
        keyword_range = parse_seo_keyword_count(prompt)

        output_schema = {
            "type": "object",
            "required": ["description_placeholders", "seo_keywords"],
            "properties": {
                "description_placeholders": {
                    "type": "object",
                    "required": ["PAIN_POINTS", "BENEFITS", "SPECIFICATIONS", "USAGE"],
                    "properties": {
                        "PAIN_POINTS": {"type": "string"},
                        "BENEFITS": {"type": "string"},
                        "SPECIFICATIONS": {"type": "string"},
                        "USAGE": {"type": "string"},
                    },
                },
                "seo_keywords": {
                    "type": "array",
                    "minItems": keyword_range[0],
                    "maxItems": keyword_range[1],
                    "items": {
                        "type": "object",
                        "required": ["keyword", "language", "source_reason"],
                        "properties": {
                            "keyword": {"type": "string"},
                            "language": {"type": "string"},
                            "source_reason": {"type": "string"},
                        },
                    },
                },
            },
        }
        user_payload: Dict[str, object] = {
            "task": "generate_description_placeholders",
            "candidate": candidate.to_dict(),
            "output_schema": output_schema,
            "generation_settings": {
                "thinking_mode": normalized_thinking_mode,
                "thinking_enabled": normalized_thinking_mode != "disabled",
                "reasoning_strength": normalize_text_reasoning_strength(reasoning_strength),
            },
        }
        if multimodal_mode:
            user_payload["image_input_scope"] = "All detail images plus English asset images; use SKU images when no English asset images exist"
            result = self.request_multimodal_json(
                text_model,
                prompt,
                user_payload,
                image_path_list,
                ["description_placeholders", "seo_keywords"],
                reasoning_callback=reasoning_callback
                or self.description_reasoning_callback,
            )
        else:
            user_payload["product_info_from_images"] = safe_info
            result = self.request_text_json(
                prompt,
                user_payload,
                ["description_placeholders", "seo_keywords"],
                reasoning_callback=reasoning_callback
                or self.description_reasoning_callback,
                model_override=text_model,
            )
        placeholders = result.get("description_placeholders", {})
        if not isinstance(placeholders, dict):
            raise RuntimeError("Text-model description JSON validation failed: description_placeholders must be an object")
        for key in ["PAIN_POINTS", "BENEFITS", "SPECIFICATIONS", "USAGE"]:
            if not isinstance(placeholders.get(key), str) or not placeholders.get(key, "").strip():
                raise RuntimeError(f"Text-model description JSON validation failed: {key} is required")
        seo_validation = validate_seo_keywords_result(result.get("seo_keywords", []), expected_range=keyword_range)
        if not seo_validation.ok:
            raise RuntimeError("Text-model SEO keyword JSON validation failed: " + "; ".join(seo_validation.errors))
        return result

    def analyze_competitor_titles(
        self,
        candidate: CandidateSKU,
        product_info: Mapping[str, object],
        competitors: Iterable[Mapping[str, object]],
        reasoning_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        thinking_enabled: bool = True,
        reasoning_strength: str = "maximum",
        text_model: str = OPENAI_DEFAULT_MODEL,
        thinking_mode: str = "",
        image_paths: Iterable[str] = (),
        multimodal_mode: bool = False,
    ) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        normalized_thinking_mode = (
            normalize_text_thinking_mode(thinking_mode)
            if str(thinking_mode).strip()
            else ("enabled" if thinking_enabled else "disabled")
        )
        output_schema = {
            "type": "object",
            "required": ["final_title", "competitor_analysis", "removed_keywords", "warnings"],
            "properties": {
                "final_title": {"type": "string", "maxLength": 120},
                "competitor_analysis": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["source_title", "reused_keywords"],
                        "properties": {
                            "source_title": {"type": "string"},
                            "reused_keywords": {"type": "array", "items": {"type": "string"}},
                            "removed_keywords": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "removed_keywords": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }
        prompt = resolve_prompt(
            self,
            "competitor_title_analysis",
            "",
        )
        image_path_list = list(image_paths)
        if multimodal_mode:
            if not image_path_list:
                raise RuntimeError("Multimodal mode has no product images to send to the Step 6 model")
            prompt = MULTIMODAL_PRODUCT_PROMPT_PREFIX + "\n" + prompt
        user_payload: Dict[str, object] = {
            "task": "analyze_competitors_and_generate_title",
            "candidate": candidate.to_dict(),
            "competitors": list(competitors),
            "output_schema": output_schema,
            "generation_settings": {
                "thinking_mode": normalized_thinking_mode,
                "thinking_enabled": normalized_thinking_mode != "disabled",
                "reasoning_strength": normalize_text_reasoning_strength(reasoning_strength),
            },
        }
        if multimodal_mode:
            user_payload["image_input_scope"] = "All detail images plus English asset images; use SKU images when no English asset images exist"
            result = self.request_multimodal_json(
                text_model,
                prompt,
                user_payload,
                image_path_list,
                ["final_title", "competitor_analysis", "removed_keywords", "warnings"],
                reasoning_callback=reasoning_callback,
            )
        else:
            user_payload["product_info_from_images"] = safe_info
            result = self.request_text_json(
                prompt,
                user_payload,
                ["final_title", "competitor_analysis", "removed_keywords", "warnings"],
                reasoning_callback=reasoning_callback,
                model_override=text_model,
            )
        result["final_title"] = _limit_shopee_title(result.get("final_title"))
        validation = validate_title_analysis_result(result)
        if not validation.ok:
            raise RuntimeError("Text-model title JSON validation failed: " + "; ".join(validation.errors))
        return result

    def generate_listing(self, candidate: CandidateSKU, asset_manifest: AssetManifest, competitors: Iterable[Mapping[str, object]]) -> Dict[str, object]:
        asset_result = self.analyze_assets(candidate, asset_manifest)
        product_info = asset_result.get("product_info_from_images", {})
        safe_info = objective_product_info_for_text(product_info if isinstance(product_info, Mapping) else {})
        title_result = self.analyze_competitor_titles(candidate, safe_info, competitors)
        placeholders = self.request_text_json(
            resolve_prompt(self, "description_generation", ""),
            {"task": "generate_description_placeholders", "candidate": candidate.to_dict(), "product_info_from_images": dict(safe_info)},
            ["description_placeholders", "seo_keywords"],
        )
        seo_validation = validate_seo_keywords_result(placeholders.get("seo_keywords", []))
        if not seo_validation.ok:
            raise RuntimeError("NVIDIA SEO keyword JSON validation failed: " + "; ".join(seo_validation.errors))
        category = self.suggest_category(candidate, safe_info)
        return {
            "title": title_result["final_title"],
            "title_keywords": _flatten_reused_keywords(title_result.get("competitor_analysis", [])),
            "description_placeholders": placeholders["description_placeholders"],
            "seo_keywords": placeholders.get("seo_keywords", []),
            "category_suggestion": category.get("category_suggestion", {"path": "", "confidence": 0, "source": "manual"}),
            "attribute_suggestions": [{"name": "Shelf Life", "value": "36 months", "confidence": 0.8}],
            "image_selection": {"main_image": asset_result.get("main_image", ""), "detail_images": asset_result.get("detail_images", []), "sku_images": asset_manifest.sku_images, "unsafe_images": asset_result.get("unsafe_images", [])},
            "warnings": list(title_result.get("warnings", [])),
            "product_info_from_images": safe_info,
            "search_keywords": self.generate_search_keywords(candidate, asset_manifest, safe_info).get("search_keywords", []),
            "competitor_analysis": title_result.get("competitor_analysis", []),
            "removed_keywords": title_result.get("removed_keywords", []),
        }

    def suggest_category(self, candidate: CandidateSKU, product_info: Mapping[str, object]) -> Dict[str, object]:
        safe_info = objective_product_info_for_text(product_info)
        return self.request_text_json(
            resolve_prompt(self, "category_selection", "Suggest one Shopee Malaysia category using only objective image facts. Write all explanations in English."),
            {"task": "suggest_category", "candidate": candidate.to_dict(), "product_info_from_images": safe_info},
            ["category_suggestion"],
        )


def _publish_image_progress(
    callback: Optional[Callable[[Dict[str, object]], None]],
    progress: Mapping[str, object],
) -> None:
    if callback:
        snapshot = dict(progress)
        items = progress.get("items", [])
        if isinstance(items, list):
            snapshot["items"] = [dict(item) if isinstance(item, dict) else item for item in items]
        active_files = progress.get("active_files", [])
        if isinstance(active_files, list):
            snapshot["active_files"] = list(active_files)
        callback(snapshot)


def _normalize_single_image_result(
    raw_result: Mapping[str, object],
    *,
    file_name: str,
    file_path: str,
    folder_type: str,
    status: str,
    selection_only: bool = False,
) -> Dict[str, object]:
    """Normalize model output while keeping facts and image-selection judgment isolated."""
    raw_objective = raw_result.get("objective_record", raw_result)
    objective_source = raw_objective if isinstance(raw_objective, Mapping) else {}
    objective = _clean_objective_record(objective_source)
    objective["file_name"] = file_name
    objective["folder_type"] = folder_type

    raw_assessment = raw_result.get("selection_assessment", raw_result)
    assessment_source = raw_assessment if isinstance(raw_assessment, Mapping) else {}
    selection_reasons = _clean_string_list(assessment_source.get("selection_reasons"))
    if not selection_reasons:
        selection_reasons = _clean_string_list(assessment_source.get("selection_reasones"))
    if not selection_reasons:
        selection_reasons = _clean_string_list(assessment_source.get("warnings"))
    requested_suitable = _as_bool(assessment_source.get("suitable_for_listing"))
    if selection_only:
        selection_reason_text = " ".join(selection_reasons).casefold()
        blocked = any(
            marker in selection_reason_text
            for marker in ("oem", "odm", "duplicate")
        )
        suitable_for_listing = not blocked
        recommended_role = str(
            assessment_source.get("recommended_role", "") or ""
        ).strip()
        upload_score = min(
            100.0,
            max(0.0, _score(assessment_source.get("upload_score"))),
        )
        if suitable_for_listing and not requested_suitable:
            upload_score = max(40.0, upload_score)
            selection_reasons = [
                "This asset-pack image is usable and is ranked only by how well it supports a buyer's purchase decision"
            ]
        return {
            "file_name": file_name,
            "file_path": file_path,
            "folder_type": folder_type,
            "status": status,
            "objective_record": objective,
            "selection_assessment": {
                "suitable_for_listing": suitable_for_listing,
                "recommended_role": recommended_role,
                "upload_score": upload_score,
                "selection_reasons": selection_reasons,
            },
        }
    allowed_exclusion = _has_allowed_image_exclusion(objective, selection_reasons)
    hard_exclusion = _as_bool(objective.get("contains_oem_odm")) or (
        not requested_suitable and allowed_exclusion
    )
    suitable_for_listing = requested_suitable and not hard_exclusion
    recommended_role = str(assessment_source.get("recommended_role", "") or "").strip()
    upload_score = min(100.0, max(0.0, _score(assessment_source.get("upload_score"))))
    if not requested_suitable and not allowed_exclusion:
        suitable_for_listing = True
        recommended_role = {
            "main_image": "main_image_candidate",
            "detail_image": "detail_image_candidate",
            "english_asset": "detail_image_candidate",
            "parameter_image": "detail_image_candidate",
            "sku": "variation_image_candidate",
        }.get(folder_type, "image_candidate")
    if suitable_for_listing:
        upload_score = _buyer_purchase_value_score(objective)
        selection_reasons = [
            "This asset-pack image is usable and is ranked by how well its product view, benefits, results, ingredients, usage, specifications, and context support a purchase decision"
        ]
    elif hard_exclusion:
        selection_reasons = (
            ["Contains OEM/ODM information"]
            if _as_bool(objective.get("contains_oem_odm"))
            else ["Duplicate image"]
        )
    assessment = {
        "suitable_for_listing": suitable_for_listing,
        "recommended_role": recommended_role,
        "upload_score": upload_score,
        "selection_reasons": selection_reasons,
    }
    return {
        "file_name": file_name,
        "file_path": file_path,
        "folder_type": folder_type,
        "status": status,
        "objective_record": objective,
        "selection_assessment": assessment,
    }


def _has_allowed_image_exclusion(
    objective_record: Mapping[str, object],
    selection_reasons: Iterable[object],
) -> bool:
    """Only OEM/ODM and duplicate-image evidence may exclude an asset-pack image."""
    if _as_bool(objective_record.get("contains_oem_odm")):
        return True
    evidence = " ".join(
        [
            *(_clean_string_list(selection_reasons)),
            *(_clean_string_list(objective_record.get("objective_quality_issues"))),
        ]
    ).lower()
    allowed_markers = (
        "oem",
        "odm",
        "duplicate content",
        "duplicate image",
    )
    return any(marker in evidence for marker in allowed_markers)


def _buyer_purchase_value_score(objective_record: Mapping[str, object]) -> float:
    """Rank usable images by concrete information that helps a buyer decide."""
    score = 40.0
    if str(objective_record.get("factual_visual_description", "") or "").strip():
        score += 5.0
    if str(objective_record.get("packaging_description", "") or "").strip():
        score += 7.0
    if str(objective_record.get("product_type", "") or "").strip():
        score += 4.0
    score += min(18.0, 3.0 * len(_clean_string_list(objective_record.get("visible_claims"))))
    score += min(12.0, 4.0 * len(_clean_string_list(objective_record.get("visible_usage"))))
    score += min(
        10.0,
        2.0 * len(_clean_string_list(objective_record.get("visible_ingredients_or_materials"))),
    )
    score += min(8.0, 2.0 * len(_clean_string_list(objective_record.get("visible_specs"))))
    score += min(
        6.0,
        2.0 * len(_clean_string_list(objective_record.get("depicted_body_areas_or_scenarios"))),
    )
    if _as_bool(objective_record.get("is_before_after_image")):
        score += 10.0
    return min(100.0, score)


def _summarize_single_image_results(
    asset_manifest: AssetManifest,
    per_image_results: list[Dict[str, object]],
    progress: Mapping[str, object],
) -> Dict[str, object]:
    successful = [item for item in per_image_results if item.get("status") in {"analysis_succeeded", "cached"}]

    def objective(item: Mapping[str, object]) -> Mapping[str, object]:
        value = item.get("objective_record", {})
        return value if isinstance(value, Mapping) else {}

    def assessment(item: Mapping[str, object]) -> Mapping[str, object]:
        value = item.get("selection_assessment", {})
        return value if isinstance(value, Mapping) else {}

    def is_safe(item: Mapping[str, object]) -> bool:
        facts = objective(item)
        selection = assessment(item)
        return (
            _as_bool(selection.get("suitable_for_listing"))
            and not _as_bool(facts.get("contains_oem_odm"))
        )

    safe_main = [item for item in successful if item.get("folder_type") == "main_image" and is_safe(item)]
    safe_main.sort(
        key=lambda item: (
            _as_bool(objective(item).get("is_before_after_image")),
            _score(assessment(item).get("upload_score")),
        ),
        reverse=True,
    )
    safe_details = [item for item in successful if item.get("folder_type") == "detail_image" and is_safe(item)]
    safe_details.sort(key=lambda item: _score(assessment(item).get("upload_score")), reverse=True)

    main_image = str(safe_main[0].get("file_path", "")) if safe_main else ""
    if not main_image:
        unsafe_paths = {str(item.get("file", "")) for item in asset_manifest.unsafe_images}
        unsafe_paths.update(
            str(item.get("file_path", ""))
            for item in successful
            if not is_safe(item)
        )
        main_image = next((path for path in asset_manifest.main_images if path not in unsafe_paths), "")
        if not main_image:
            main_image = next(
                (
                    str(item.get("file_path", ""))
                    for item in safe_details
                    if str(item.get("file_path", ""))
                ),
                "",
            )
        if not main_image:
            main_image = next(
                (path for path in asset_manifest.detail_images if path not in unsafe_paths),
                "",
            )

    detail_images = [
        str(item.get("file_path", ""))
        for item in safe_details
        if item.get("file_path") and str(item.get("file_path", "")) != main_image
    ][:8]

    unsafe_images: list[Dict[str, str]] = [dict(item) for item in asset_manifest.unsafe_images]
    existing_unsafe = {str(item.get("file", "")) for item in unsafe_images}
    for item in successful:
        if is_safe(item):
            continue
        path = str(item.get("file_path", ""))
        if not path or path in existing_unsafe:
            continue
        facts = objective(item)
        selection = assessment(item)
        reasons: list[str] = []
        if _as_bool(facts.get("contains_oem_odm")):
            reasons.append("Contains OEM/ODM information")
        if not _as_bool(selection.get("suitable_for_listing")):
            reasons.extend(_clean_string_list(selection.get("selection_reasons")))
            if not reasons:
                reasons.append("The AI image-selection result marked this image as unsuitable")
        unsafe_images.append({"file": path, "reason": "; ".join(_unique_strings(reasons)) or "The AI image-selection result marked this image as unsafe"})
        existing_unsafe.add(path)

    objective_records = [_clean_objective_record(objective(item)) for item in successful]
    selection_assessments = [
        {
            "file_name": str(item.get("file_name", "")),
            "file_path": str(item.get("file_path", "")),
            "folder_type": str(item.get("folder_type", "")),
            "status": str(item.get("status", "")),
            "suitable_for_listing": _as_bool(assessment(item).get("suitable_for_listing")),
            "recommended_role": str(assessment(item).get("recommended_role", "") or "").strip(),
            "upload_score": min(100.0, max(0.0, _score(assessment(item).get("upload_score")))),
            "selection_reasons": _clean_string_list(assessment(item).get("selection_reasons")),
        }
        for item in successful
    ]
    product_type = next(
        (
            str(record.get("product_type", "")).strip()
            for record in objective_records
            if str(record.get("product_type", "")).strip()
        ),
        "",
    )
    product_info = {
        "data_scope": "objective_image_facts_only",
        "product_type": product_type,
        "product_forms": _unique_strings(
            record.get("product_form", "") for record in objective_records
        ),
        "packaging_descriptions": _unique_strings(
            record.get("packaging_description", "") for record in objective_records
        ),
        "visible_specs": _unique_strings(
            value for record in objective_records for value in _list_values(record.get("visible_specs"))
        ),
        "visible_ingredients_or_materials": _unique_strings(
            value
            for record in objective_records
            for value in _list_values(record.get("visible_ingredients_or_materials"))
        ),
        "visible_claims": _unique_strings(
            value for record in objective_records for value in _list_values(record.get("visible_claims"))
        ),
        "visible_text": _unique_strings(
            value for record in objective_records for value in _list_values(record.get("visible_text"))
        ),
        "visible_usage": _unique_strings(
            value for record in objective_records for value in _list_values(record.get("visible_usage"))
        ),
        "depicted_body_areas_or_scenarios": _unique_strings(
            value
            for record in objective_records
            for value in _list_values(record.get("depicted_body_areas_or_scenarios"))
        ),
        "factual_visual_descriptions": _unique_strings(
            record.get("factual_visual_description", "") for record in objective_records
        ),
        "objective_quality_issues": _unique_strings(
            value
            for record in objective_records
            for value in _list_values(record.get("objective_quality_issues"))
        ),
        "uncertainties": _unique_strings(
            value for record in objective_records for value in _list_values(record.get("uncertainties"))
        ),
        "objective_image_records": objective_records,
    }
    product_info = objective_product_info_for_text(product_info)
    return {
        "main_image": main_image,
        "detail_images": detail_images,
        "unsafe_images": unsafe_images,
        "product_info_from_images": product_info,
        "objective_image_records": objective_records,
        "image_selection_assessments": selection_assessments,
        "per_image_results": per_image_results,
        "analysis_progress": dict(progress),
    }


def _list_values(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _unique_strings(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _score(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _limit_shopee_title(value: object, maximum: int = 120) -> str:
    title = " ".join(str(value or "").split())
    if len(title) <= maximum:
        return title
    shortened = title[:maximum].rstrip()
    if len(title) > maximum and shortened and not title[maximum].isspace():
        boundary = shortened.rfind(" ")
        if boundary >= maximum // 2:
            shortened = shortened[:boundary].rstrip()
    return shortened


class GenericHTTPAIProvider(AIProvider):
    def __init__(self, config: AIConfig, prompts_dir: Path):
        self.config = config
        self.prompts_dir = prompts_dir

    def generate_listing(
        self,
        candidate: CandidateSKU,
        asset_manifest: AssetManifest,
        competitors: Iterable[Mapping[str, object]],
    ) -> Dict[str, object]:
        api_key = os.environ.get(self.config.api_key_env, "")
        if not self.config.endpoint or not api_key:
            raise RuntimeError("AI endpoint or API key is not configured")

        payload = {
            "model": self.config.model,
            "task": "shopee_listing_json",
            "candidate": candidate.to_dict(),
            "assets": asset_manifest.to_dict(),
            "competitors": list(competitors),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        if isinstance(data, dict) and "choices" in data:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        if not isinstance(data, dict):
            raise RuntimeError("AI provider returned non-object JSON")
        return data


def get_ai_provider(config: AIConfig, prompts_dir: Path) -> AIProvider:
    if config.provider.lower() in {
        "openai",
        "multi_model",
        "multi-model",
        "nvidia",
        "nvidia_dual",
        "nvidia-dual",
    }:
        return NvidiaDualProvider(config, prompts_dir, cache_dir=PROJECT_ROOT / "outputs" / "ai_cache")
    if config.provider.lower() in {"zhipu", "glm", "glm-5.2"}:
        return ZhipuProvider(config, prompts_dir)
    if config.provider.lower() in {"generic_http", "http", "api"}:
        return GenericHTTPAIProvider(config, prompts_dir)
    return OfflineAIProvider()


def _flatten_reused_keywords(analysis: object) -> list[str]:
    keywords: list[str] = []
    for item in analysis if isinstance(analysis, list) else []:
        if not isinstance(item, Mapping):
            continue
        for word in item.get("reused_keywords", []):
            if isinstance(word, str) and word and word.lower() not in {k.lower() for k in keywords}:
                keywords.append(word)
    return keywords
