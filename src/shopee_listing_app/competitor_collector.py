from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Dict, List, Optional


def collect_competitors(
    sku_code: str,
    keyword: str,
    cache_dir: Path,
    competitor_file: Optional[Path] = None,
    limit: int = 5,
) -> Dict[str, object]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{safe_filename(sku_code)}.json"

    if competitor_file:
        sources = load_competitor_file(competitor_file)[:limit]
        result = {
            "sku_code": sku_code,
            "keyword": keyword,
            "sources": sources,
            "warnings": [],
        }
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    result = {
        "sku_code": sku_code,
        "keyword": keyword,
        "sources": [],
        "warnings": [
            "No competitor file or cache was provided. Phase 2 will collect from the Ziniao Shopee session automatically."
        ],
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_competitor_file(path: Path) -> List[Dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        raw = json.loads(text)
        return [normalize_source(item) for item in raw]

    sources = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            url, sales, title = parts[0], parts[1], "\t".join(parts[2:])
        else:
            url, sales, title = "", "", line
        sources.append(normalize_source({"url": url, "sales": sales, "title": title}))
    return sources


def normalize_source(item: Dict[str, object]) -> Dict[str, object]:
    title = str(item.get("title") or item.get("source_title") or item.get("full_title") or "").strip()
    full_text = str(item.get("fullText") or item.get("full_text") or title).strip()
    return {
        "url": str(item.get("url") or item.get("href") or "").strip(),
        "observed_sales": str(item.get("observed_sales") or item.get("sales") or "").strip(),
        "source_title": title or extract_shopee_title(full_text),
        "full_text": full_text,
        "reused_keywords": item.get("reused_keywords", []),
    }


def extract_shopee_title(full_text: str) -> str:
    price_index = full_text.find("RM ")
    if price_index > 0:
        return full_text[:price_index].strip()
    rating = re.search(r"\s\d\.\d\s", full_text)
    if rating and rating.start() > 0:
        return full_text[: rating.start()].strip()
    return full_text.strip()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "sku")).strip("_") or "sku"
