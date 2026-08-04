from __future__ import annotations

import json


def quill_fill_script(description: str) -> str:
    return f"""
(() => {{
  const descriptionText = {json.dumps(description, ensure_ascii=False)};
  const normalized = descriptionText.replace(/\\n{{2,}}/g, "\\n").trim();
  const container = document.querySelector(".ql-container");
  const editor = document.querySelector(".ql-editor");
  if (container && container.__quill) {{
    container.__quill.setText(normalized, "user");
  }} else if (editor) {{
    editor.innerText = normalized;
    editor.dispatchEvent(new InputEvent("input", {{ bubbles: true, inputType: "insertText", data: normalized }}));
  }} else {{
    return {{ ok: false, reason: "Quill editor not found" }};
  }}
  const text = (document.querySelector(".ql-editor") || {{ innerText: "" }}).innerText || "";
  const blanks = ((document.querySelector(".ql-editor") || {{ innerHTML: "" }}).innerHTML.match(/<p><br><\\/p>/g) || []).length;
  return {{ ok: text.includes(normalized.slice(0, 30)), noBlankParagraphs: blanks === 0, length: text.length }};
}})()
"""
