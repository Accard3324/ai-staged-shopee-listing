from __future__ import annotations


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


def missing_playwright_message() -> str:
    return "Playwright is not installed; the app is using the dependency-free CDP connector for this stage."
