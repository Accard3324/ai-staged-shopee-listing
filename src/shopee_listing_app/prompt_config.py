from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Dict, Mapping, Tuple


PROMPT_KEYS = (
    "image_analysis",
    "description_generation",
    "keyword_generation",
    "competitor_title_analysis",
    "category_selection",
)

DEFAULT_PROMPTS: Dict[str, str] = {
    "image_analysis": "",
    "description_generation": "",
    "keyword_generation": "",
    "competitor_title_analysis": "",
    "category_selection": (
        "Choose only from category suggestions actually displayed on the current Shopee page and rank them using objective image facts. "
        "Never invent a category path. When evidence is limited, choose the safest displayed suggestion and explain the choice. "
        "Keep category_suggestion.path in the page's original language and write all explanations and warnings in English."
    ),
}


def load_prompt_config(path: Path) -> Dict[str, str]:
    """Load only JSON-compatible YAML so the desktop app stays dependency-free."""
    values = dict(DEFAULT_PROMPTS)
    if not path.exists():
        return values
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Prompt config is invalid: {exc}") from exc
    prompts = stored.get("prompts", stored) if isinstance(stored, dict) else {}
    if not isinstance(prompts, dict):
        raise RuntimeError("Prompt config must contain an object named prompts")
    for key in PROMPT_KEYS:
        value = prompts.get(key)
        if isinstance(value, str):
            values[key] = value.strip()
    return values


def save_prompt_config(path: Path, prompts: Mapping[str, object]) -> Dict[str, str]:
    values = {
        key: str(prompts.get(key, "")).strip()
        for key in PROMPT_KEYS
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"prompts": values}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return values


DEFAULT_SEO_KEYWORD_RANGE: Tuple[int, int] = (15, 20)


def parse_seo_keyword_count(prompt: str) -> Tuple[int, int]:
    """Parse the seo_keywords count requirement from the active prompt.

    Looks at the sentence(s) mentioning seo_keywords / SEO terms and supports:
    - a range like "15-20 terms" -> (15, 20)
    - an exact count like "10 terms" -> (10, 10)
    Falls back to DEFAULT_SEO_KEYWORD_RANGE when nothing is specified.
    """
    text = str(prompt or "")
    segments = re.split(r"[.;\n]", text)
    for segment in segments:
        if "seo" not in segment.lower():
            continue
        range_match = re.search(
            r"(\d+)\s*(?:to|[-\u2013\u2014])\s*(\d+)\s*(?:terms?|keywords?)?",
            segment,
            re.IGNORECASE,
        )
        if range_match:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            if 0 < low <= high <= 50:
                return low, high
        exact_match = re.search(
            r"(\d+)\s*(?:terms?|keywords?)",
            segment,
            re.IGNORECASE,
        )
        if exact_match:
            count = int(exact_match.group(1))
            if 0 < count <= 50:
                return count, count
    return DEFAULT_SEO_KEYWORD_RANGE


def seo_keyword_count_text(keyword_range: Tuple[int, int]) -> str:
    low, high = keyword_range
    if low == high:
        return f"{low} term" if low == 1 else f"{low} terms"
    return f"{low}\u2013{high} terms"
