from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Dict, List, Mapping


URL_RE = re.compile(r"https?://\S+", re.I)
SALES_RE = re.compile(r"(Sold\s*[\w.]+|售\s*[\d.]+\s*[万千kK]?|销量\s*[\d.]+\s*[万千kK]?)", re.I)


def parse_manual_competitors(text: str) -> List[Dict[str, object]]:
    competitors: List[Dict[str, object]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        url_match = URL_RE.search(line)
        sales_match = SALES_RE.search(line)
        url = url_match.group(0).rstrip("，,;；") if url_match else ""
        sales = sales_match.group(0).strip() if sales_match else ""
        title = line
        if url:
            title = title.replace(url_match.group(0), " ")
        if sales:
            title = title.replace(sales_match.group(0), " ")
        title = re.sub(r"\s+", " ", title.replace("|", " ")).strip(" -，,;；")
        if not title and url:
            title = url
        competitors.append(
            {
                "url": url,
                "source_title": title,
                "observed_sales": sales,
                "full_text": line,
                "raw_input": line,
                "is_relevant": True,
                "warnings": [],
                "source": "manual_gui",
            }
        )
    return competitors


def save_manual_competitors(
    output_dir: Path,
    sku_code: str,
    competitors: List[Mapping[str, object]],
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_sku = re.sub(r"[^A-Za-z0-9._-]+", "_", str(sku_code)).strip("_") or "sku"
    json_path = output_dir / f"{safe_sku}_manual_competitors.json"
    markdown_path = output_dir / f"{safe_sku}_manual_competitors.md"
    json_path.write_text(
        json.dumps({"competitors": [dict(item) for item in competitors]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["# Manual Competitors", ""]
    for index, item in enumerate(competitors, start=1):
        lines.extend(
            [
                f"## {index}. {item.get('source_title', '')}",
                "",
                f"- URL: {item.get('url', '')}",
                f"- Observed sales: {item.get('observed_sales', '')}",
                f"- Raw input: {item.get('raw_input', '')}",
                "",
            ]
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path}
