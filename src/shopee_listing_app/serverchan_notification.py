from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional
from urllib.parse import quote, urlencode
import urllib.request


SERVERCHAN_ENDPOINT = "https://sctapi.ftqq.com/{sendkey}.send"


def send_serverchan_message(
    title: str,
    description: str,
    *,
    sendkey: Optional[str] = None,
    timeout_seconds: float = 15,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> Dict[str, object]:
    key = str(sendkey or os.environ.get("SERVERCHAN_SENDKEY", "")).strip()
    if not key:
        raise RuntimeError("Enter a ServerChan SendKey first.")
    if not key.startswith("SCT") or any(char.isspace() for char in key):
        raise RuntimeError("The ServerChan SendKey is invalid; it must start with SCT.")

    endpoint = SERVERCHAN_ENDPOINT.format(sendkey=quote(key, safe=""))
    body = urlencode(
        {
            "title": str(title).strip()[:128],
            "desp": str(description).strip()[:12000],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "code", "")
        suffix = f"（HTTP {status}）" if status else ""
        raise RuntimeError(f"ServerChan connection failed{suffix}") from None

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("ServerChan returned an unrecognized response.") from None
    if not isinstance(result, dict) or int(result.get("code", -1)) != 0:
        message = str(result.get("message") or result.get("msg") or "send failed") if isinstance(result, dict) else "send failed"
        raise RuntimeError("ServerChan send failed: " + message[:200])
    return {"code": 0, "message": "Messaging notification sent"}
