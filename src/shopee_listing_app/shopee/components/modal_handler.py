from __future__ import annotations

import json


def exact_modal_button_script(modal_text: str, button_text: str) -> str:
    return f"""
(() => {{
  const modalText = {json.dumps(modal_text, ensure_ascii=False)};
  const buttonText = {json.dumps(button_text, ensure_ascii=False)};
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  for (const modal of document.querySelectorAll(".eds-modal__box,[role='dialog']")) {{
    if (!visible(modal) || !(modal.innerText || "").includes(modalText)) continue;
    for (const button of modal.querySelectorAll("button")) {{
      if ((button.innerText || "").trim() === buttonText) {{
        button.click();
        return {{ ok: true, buttonText }};
      }}
    }}
  }}
  return {{ ok: false, reason: "modal button not found", modalText, buttonText }};
}})()
"""


def shipping_confirmation_modal_script() -> str:
    return r"""
(() => {
  const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const shippingSignals = [
    "Once this channel is enabled",
    "Doorstep Delivery",
    "Self Collection Point",
    "物流",
    "运费",
  ];
  for (const modal of document.querySelectorAll(".eds-modal__box,[role='dialog']")) {
    if (!visible(modal)) continue;
    const modalText = (modal.innerText || "").replace(/\s+/g, " ").trim();
    if (!shippingSignals.some(signal => modalText.includes(signal))) continue;
    const button = [...modal.querySelectorAll("button")]
      .filter(visible)
      .find(item => ["确认", "Confirm"].includes((item.innerText || "").trim()));
    if (!button) return { found: true, confirmed: false, reason: "shipping confirmation button not found", modalText };
    button.click();
    return { found: true, confirmed: true, buttonText: (button.innerText || "").trim(), modalText };
  }
  return { found: false, confirmed: false };
})()
"""
