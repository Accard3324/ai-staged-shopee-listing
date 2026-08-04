from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
from typing import Dict, Iterable, List


_STORE_NAME_CACHE: Dict[tuple[int, str], str] = {}


@dataclass(frozen=True)
class CdpCandidate:
    process_id: int
    name: str
    port: int
    command_line: str
    window_title: str = ""
    verified: bool = False
    browser: str = ""
    web_socket_debugger_url: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def parse_cdp_processes(processes: Iterable[Dict[str, object]]) -> List[CdpCandidate]:
    candidates_by_port: Dict[int, CdpCandidate] = {}
    for process in processes:
        command_line = str(process.get("CommandLine") or "")
        match = re.search(r"--remote-debugging-port=(\d+)", command_line)
        if not match:
            continue
        port = int(match.group(1))
        if port == 9480:
            continue
        candidate = CdpCandidate(
            process_id=int(process.get("ProcessId") or process.get("PID") or 0),
            name=str(process.get("Name") or ""),
            port=port,
            command_line=command_line,
            window_title=str(process.get("WindowTitle") or ""),
        )
        existing = candidates_by_port.get(port)
        if existing is None:
            candidates_by_port[port] = candidate
            continue
        existing_is_child = bool(re.search(r"(?:^|\s)--type=", existing.command_line))
        candidate_is_child = bool(re.search(r"(?:^|\s)--type=", candidate.command_line))
        if existing_is_child and not candidate_is_child:
            candidates_by_port[port] = candidate
        elif not existing.window_title and candidate.window_title and not candidate_is_child:
            candidates_by_port[port] = candidate
    return list(candidates_by_port.values())


def discover_cdp_candidates(verify: bool = True) -> List[CdpCandidate]:
    processes = query_ziniao_listener_processes()
    if not processes:
        processes = query_browser_processes()
    candidates = parse_cdp_processes(processes)
    if not verify:
        return sorted(candidates, key=lambda item: item.port)

    verified: List[CdpCandidate] = []
    for candidate in candidates:
        metadata = probe_json_version(candidate.port)
        if not metadata:
            continue
        verified.append(
            CdpCandidate(
                process_id=candidate.process_id,
                name=candidate.name,
                port=candidate.port,
                command_line=candidate.command_line,
                window_title=candidate.window_title,
                verified=True,
                browser=str(metadata.get("Browser", "")),
                web_socket_debugger_url=str(metadata.get("webSocketDebuggerUrl", "")),
            )
        )
    return sorted(verified, key=lambda item: item.port)


def query_browser_processes() -> List[Dict[str, object]]:
    command = [
        _powershell_executable(),
        "-NoProfile",
        "-Command",
        (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match '--remote-debugging-port' -or "
            "$_.Name -match 'chrome|browser|ziniao|znbrowser|Chromium|紫鸟' } | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 3"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    stdout = decode_process_output(completed.stdout)
    if completed.returncode != 0 or not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def query_ziniao_listener_processes() -> List[Dict[str, object]]:
    """Discover Ziniao CDP ports without requiring Win32_Process access."""
    process_details = _query_ziniao_browser_process_details()
    if not process_details:
        return []

    netstat_executable = _netstat_executable()
    try:
        completed = subprocess.run(
            [netstat_executable, "-ano", "-p", "tcp"],
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    stdout = decode_process_output(completed.stdout)
    if completed.returncode != 0 or not stdout.strip():
        return []

    processes: List[Dict[str, object]] = []
    listener_pattern = re.compile(
        r"^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$",
        re.IGNORECASE,
    )
    for line in stdout.splitlines():
        match = listener_pattern.match(line)
        if not match:
            continue
        port = int(match.group(1))
        process_id = int(match.group(2))
        process_info = process_details.get(process_id)
        if not process_info:
            continue
        process_name = process_info["name"]
        processes.append(
            {
                "ProcessId": process_id,
                "Name": process_name,
                "WindowTitle": process_info["window_title"],
                "CommandLine": (
                    f"{process_name}.exe --remote-debugging-port={port} "
                    "--discovered-from-listener"
                ),
            }
        )
    return processes


def _query_ziniao_browser_process_details() -> Dict[int, Dict[str, str]]:
    command = [
        _powershell_executable(),
        "-NoProfile",
        "-Command",
        (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Get-Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.ProcessName -match 'ziniao.*browser|znbrowser' } | "
            "Select-Object @{Name='ProcessId';Expression={[int]$_.Id}},"
            "@{Name='Name';Expression={$_.ProcessName}},"
            "@{Name='WindowTitle';Expression={$_.MainWindowTitle}} | "
            "ConvertTo-Json -Depth 3"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    stdout = decode_process_output(completed.stdout)
    if completed.returncode != 0 or not stdout.strip():
        return {}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return {}

    result: Dict[int, Dict[str, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        process_id = int(item.get("ProcessId") or 0)
        process_name = str(item.get("Name") or "")
        if process_id > 0 and process_name:
            result[process_id] = {
                "name": process_name,
                "window_title": str(item.get("WindowTitle") or "").strip(),
            }
    return result


def _powershell_executable() -> str:
    system_root = Path(os.environ.get("SystemRoot") or "C:/Windows")
    bundled_system_path = (
        system_root
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if bundled_system_path.is_file():
        return str(bundled_system_path)
    return shutil.which("powershell.exe") or shutil.which("powershell") or "powershell"


def _netstat_executable() -> str:
    system_root = Path(os.environ.get("SystemRoot") or "C:/Windows")
    bundled_system_path = system_root / "System32" / "netstat.exe"
    if bundled_system_path.is_file():
        return str(bundled_system_path)
    return shutil.which("netstat.exe") or shutil.which("netstat") or "netstat"


def decode_process_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    encodings = ["utf-8-sig", "utf-8", "utf-16", locale.getpreferredencoding(False), "gbk"]
    for encoding in dict.fromkeys(encodings):
        try:
            return output.decode(encoding)
        except UnicodeDecodeError:
            continue
    return output.decode("utf-8", errors="replace")


def probe_json_version(port: int) -> Dict[str, object]:
    if int(port) == 9480:
        return {}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
            if response.status != 200:
                return {}
            data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def detect_ziniao_store_name(
    port: int,
    expected_names: Iterable[str] = (),
) -> str:
    """Read the full store name from Ziniao's own account page."""
    try:
        from .browser.cdp_client import CdpClient, list_pages

        pages = list_pages(int(port))
    except Exception:
        return ""

    extension_pages = [
        page
        for page in pages
        if isinstance(page, dict)
        and str(page.get("type", "page") or "page") == "page"
        and str(page.get("url", "") or "").startswith("chrome-extension://")
        and str(page.get("url", "") or "").rstrip("/").endswith("/index.html")
        and str(page.get("webSocketDebuggerUrl", "") or "").strip()
    ]
    normalized_expected = [
        (str(name).strip(), _normalize_store_name(name))
        for name in expected_names
        if str(name).strip()
    ]
    for page in extension_pages:
        websocket_url = str(page.get("webSocketDebuggerUrl", "") or "").strip()
        cache_key = (int(port), websocket_url)
        cached = _STORE_NAME_CACHE.get(cache_key, "")
        if cached:
            for original_name, normalized_name in normalized_expected:
                if normalized_name == _normalize_store_name(cached):
                    return original_name
            return cached

        client = CdpClient(websocket_url)
        try:
            client.connect()
            client.command("Runtime.enable")
            evaluated = client.evaluate("document.body?.innerText || ''")
            body_text = str(
                evaluated.get("result", {}).get("value", "")
                if isinstance(evaluated, dict)
                else ""
            )
        except Exception:
            continue
        finally:
            client.close()

        normalized_body = _normalize_store_name(body_text)
        for original_name, normalized_name in normalized_expected:
            if normalized_name and normalized_name in normalized_body:
                _STORE_NAME_CACHE[cache_key] = original_name
                return original_name

        match = re.search(
            r"(?m)^\s*([^\r\n]{2,160}?)\s*\r?\n\s*[（(]\s*登录账号\s*[：:]",
            body_text,
        )
        if match:
            store_name = re.sub(r"\s+", " ", match.group(1)).strip()
            if store_name:
                _STORE_NAME_CACHE[cache_key] = store_name
                return store_name
    return ""


def _normalize_store_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()
