from __future__ import annotations

import time

from ...browser.cdp_client import CdpClient


def next_step_click_script() -> str:
    return """
(() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = text => String(text || "").replace(/\\s+/g, " ").trim();
  const button = [...document.querySelectorAll("button")]
    .filter(visible)
    .find(item => norm(item.innerText) === "Next Step");
  if (!button) return { ok: false, reason: "Next Step button not found" };
  if (button.disabled || button.className.includes("disabled")) {
    return { ok: false, reason: "Next Step disabled", disabled: true };
  }
  if (!button.disabled) button.click();
  return { ok: true, disabled: false, hasStep2Signals: false, waitedFor: "Previous or Step 2 fields" };
})()
"""


def click_next_step(client: CdpClient, timeout_seconds: int = 30) -> dict:
    result = client.evaluate(next_step_click_script()).get("result", {}).get("value", {})
    if not result.get("ok"):
        raise RuntimeError(f"Next Step is not clickable: {result}")
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        last = client.evaluate(
            """
(() => ({
  url: location.href,
  hasQuill: !!document.querySelector(".ql-editor,.ql-container"),
  hasStep2Signals: /Previous|Category|Brand|Description|Sales Information|Shipping|类目|品牌|商品描述|销售资料|物流/i.test((document.body && document.body.innerText || "")),
  hasNextStep: [...document.querySelectorAll("button")].some(button => (button.innerText || "").trim() === "Next Step"),
  bodyText: (document.body && document.body.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 1000)
}))()
"""
        ).get("result", {}).get("value", {})
        if last.get("hasQuill") or last.get("hasStep2Signals"):
            return last
        time.sleep(1)
    raise RuntimeError(f"The page did not advance after clicking Next Step: {last}")
