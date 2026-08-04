from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence


def _norm_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _candidate_text(candidate: object) -> str:
    if isinstance(candidate, Mapping):
        return _norm_text(candidate.get("text") or candidate.get("path") or candidate.get("label"))
    return _norm_text(candidate)


def choose_category_candidate(
    candidates: Sequence[object],
    payload: Mapping[str, Any],
    min_score: int = 6,
) -> dict[str, Any]:
    """Choose only when the visible category candidate clearly matches the draft."""
    source_text = _norm_text(
        " ".join(
            [
                str(payload.get("category") or ""),
                str(payload.get("title") or ""),
                str(payload.get("description") or ""),
                str(payload.get("sku_code") or ""),
            ]
        )
    ).lower()
    preferred_path = _norm_text(payload.get("category") or "")
    scored: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        text = _candidate_text(candidate)
        if not text:
            continue
        lower = text.lower()
        score = 0
        reasons: list[str] = []

        if preferred_path and (preferred_path in text or text in preferred_path):
            score += 12
            reasons.append("draft category path match")

        if re.search(r"wart|warts|verruca|疣|鸡眼|肉粒|remover|去除|护理膏", source_text):
            if re.search(r"医疗|保健|急救|medical|health|first aid", text, re.I):
                score += 4
                reasons.append("medical/first-aid match")
            if re.search(r"软膏|乳膏|ointment|cream", text, re.I):
                score += 4
                reasons.append("ointment/cream match")

        if re.search(r"cream|ointment|膏|乳膏|软膏|乳霜|balm", source_text):
            if re.search(r"软膏|乳膏|ointment", text, re.I):
                score += 3
                reasons.append("ointment form match")
            elif re.search(r"乳霜|cream", text, re.I):
                score += 2
                reasons.append("cream form match")

        if re.search(r"skin|肌肤|皮肤|护肤", source_text) and re.search(r"护肤|美妆|skincare", text, re.I):
            score += 2
            reasons.append("skin-care match")

        if re.search(r"保湿|moisturi[sz]ing|lotion", text, re.I) and not re.search(r"保湿|moisturi[sz]e|lotion", source_text):
            score -= 2
            reasons.append("moisturising mismatch")

        if re.search(r"头发|护发|hair", text, re.I) and not re.search(r"头发|护发|hair", source_text):
            score -= 5
            reasons.append("hair-care mismatch")

        scored.append({"index": index, "text": text, "score": score, "reasons": reasons})

    unique_scored: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for item in scored:
        key = item["text"].casefold()
        if key in seen_texts:
            continue
        seen_texts.add(key)
        unique_scored.append(item)
    scored = unique_scored
    scored.sort(key=lambda item: item["score"], reverse=True)
    if not scored:
        return {"ok": False, "reason": "no visible category candidates", "candidates": []}

    best = scored[0]
    second_score = scored[1]["score"] if len(scored) > 1 else -999
    if int(best["score"]) < min_score or int(best["score"]) - int(second_score) < 2:
        return {
            "ok": False,
            "reason": "not confident enough to choose category automatically",
            "best": best,
            "candidates": scored,
        }

    return {
        "ok": True,
        "text": best["text"],
        "index": best["index"],
        "score": best["score"],
        "reasons": best["reasons"],
        "candidates": scored,
    }


def category_select_script(category_text: str) -> str:
    return f"""
(async () => {{
  const targetCategory = {json.dumps(category_text, ensure_ascii=False)};
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const rowText = row => {{
    const textEl = row.querySelector(".category-select-row-text,[class*='category-select-row-text']");
    return norm((textEl || row).innerText);
  }};
  const rows = [...document.querySelectorAll(".category-select-row,[class*='category-select-row']")]
    .filter(visible)
    .map((row, index) => ({{ row, index, text: rowText(row) }}))
    .filter(item => item.text && item.text.includes(">"));
  const match = rows.find(item => item.text === targetCategory);
  if (!match) {{
    return {{
      ok: false,
      reason: "category candidate not visible",
      targetCategory,
      candidates: rows.map(item => ({{ index: item.index, text: item.text }}))
    }};
  }}
  match.row.scrollIntoView({{ block: "center", inline: "nearest" }});
  match.row.click();
  await sleep(1200);
  const bodyText = norm(document.body && document.body.innerText || "");
  const hasQuill = !!document.querySelector(".ql-editor,.ql-container");
  return {{
    ok: hasQuill || bodyText.includes(targetCategory),
    action: "clicked_exact_category_candidate",
    targetCategory,
    rowIndex: match.index,
    hasQuill,
    stillLocked: bodyText.includes("在您选择商品分类后更新") || /after you select a category/i.test(bodyText),
    candidates: rows.map(item => ({{ index: item.index, text: item.text }}))
  }};
}})()
"""


def wait_for_category_unlock_script() -> str:
    return r"""
(() => {
  const norm = text => String(text || "").replace(/\s+/g, " ").trim();
  const bodyText = norm(document.body && document.body.innerText || "");
  const editor = document.querySelector(".ql-editor");
  const container = document.querySelector(".ql-container");
  return {
    hasQuill: !!(editor || container),
    stillLocked: bodyText.includes("在您选择商品分类后更新") || /after you select a category/i.test(bodyText),
    hasBrandSignal: /Brand|品牌/i.test(bodyText),
    bodyTextSample: bodyText.slice(0, 1200)
  };
})()
"""
