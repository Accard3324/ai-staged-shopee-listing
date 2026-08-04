from __future__ import annotations

import ctypes
import os
import threading


MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040
MB_SYSTEMMODAL = 0x00001000
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000


def _show_topmost_alert(title: str, message: str, icon: int, thread_name: str) -> bool:
    if os.name != "nt":
        return False

    safe_title = str(title).strip()[:120] or "Shopee AI Listing Assistant"
    safe_message = str(message).strip()[:3500] or "Operation status unknown"

    def display() -> None:
        ctypes.windll.user32.MessageBoxW(
            None,
            safe_message,
            safe_title,
            MB_OK | icon | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST,
        )

    threading.Thread(target=display, name=thread_name, daemon=True).start()
    return True


def show_topmost_error_alert(title: str, message: str) -> bool:
    return _show_topmost_alert(title, message, MB_ICONERROR, "shopee-failure-alert")


def show_topmost_success_alert(title: str, message: str) -> bool:
    return _show_topmost_alert(title, message, MB_ICONINFORMATION, "shopee-success-alert")
