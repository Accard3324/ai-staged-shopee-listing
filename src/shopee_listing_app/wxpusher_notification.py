from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional
from urllib.parse import quote
import urllib.request


WXPUSHER_SPT_ENDPOINT = "https://wxpusher.zjiecode.com/api/send/message/{spt}/{content}"


def send_wxpusher_spt_message(
    title: str,
    description: str,
    *,
    spt: Optional[str] = None,
    timeout_seconds: float = 15,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> Dict[str, object]:
    token = str(spt or os.environ.get("WXPUSHER_SPT", "")).strip()
    if not token:
        raise RuntimeError("Enter a WxPusher SPT first.")
    if not token.startswith("SPT_") or any(char.isspace() for char in token):
        raise RuntimeError("The WxPusher SPT is invalid; it must start with SPT_.")

    content = (str(title).strip() + "\n\n" + str(description).strip())[:3000]
    endpoint = WXPUSHER_SPT_ENDPOINT.format(
        spt=quote(token, safe=""),
        content=quote(content, safe=""),
    )
    request = urllib.request.Request(endpoint, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "code", "")
        suffix = f"（HTTP {status}）" if status else ""
        raise RuntimeError(f"WxPusher connection failed{suffix}") from None

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("WxPusher returned an unrecognized response.") from None
    success = isinstance(result, dict) and int(result.get("code", -1)) == 1000 and result.get("success", True) is not False
    if not success:
        message = str(result.get("msg") or result.get("message") or "send failed") if isinstance(result, dict) else "send failed"
        raise RuntimeError("WxPusher send failed: " + message[:200])
    return {"code": 1000, "message": "WxPusher notification sent"}
