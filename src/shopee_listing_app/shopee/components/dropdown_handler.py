from __future__ import annotations


def exact_option_click_script(option_text: str) -> str:
    return f"""
(() => {{
  const target = {option_text!r};
  for (const option of document.querySelectorAll(".eds-option,[role='option'],li,div")) {{
    if (option.offsetParent !== null && (option.innerText || "").trim() === target) {{
      option.click();
      return {{ ok: true, text: target }};
    }}
  }}
  return {{ ok: false, reason: "option not found", text: target }};
}})()
"""
