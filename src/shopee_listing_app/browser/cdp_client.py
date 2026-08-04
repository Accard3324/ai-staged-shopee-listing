from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
from typing import Any, Dict
from urllib.parse import urlparse
import urllib.request


def http_json(url: str, method: str = "GET") -> Any:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def list_pages(port: int) -> list[dict[str, Any]]:
    data = http_json(f"http://127.0.0.1:{port}/json/list")
    return data if isinstance(data, list) else []


def create_page(port: int, url: str) -> dict[str, Any]:
    try:
        return http_json(f"http://127.0.0.1:{port}/json/new?{urllib.request.quote(url, safe=':/?=&')}", method="PUT")
    except Exception:
        pages = list_pages(port)
        if not pages:
            raise
        return pages[0]


class CdpClient:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> "CdpClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise ValueError("Only ws:// CDP endpoints are supported by the dependency-free client")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query
        sock = socket.create_connection((host, port), timeout=8)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:120]!r}")
        self.sock = sock

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def command(self, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        command_id = self.next_id
        self.next_id += 1
        self._send_json({"id": command_id, "method": method, "params": params or {}})
        while True:
            message = self._read_json()
            if message.get("id") != command_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP command failed {method}: {message['error']}")
            return message.get("result", {})

    def evaluate(self, expression: str, return_by_value: bool = True) -> Dict[str, Any]:
        return self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": return_by_value,
            },
        )

    def navigate(self, url: str) -> Dict[str, Any]:
        return self.command("Page.navigate", {"url": url})

    def capture_screenshot(self) -> str:
        result = self.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        return str(result.get("data", ""))

    def html(self) -> str:
        result = self.evaluate("document.documentElement ? document.documentElement.outerHTML : ''")
        return str(result.get("result", {}).get("value", ""))

    def _send_json(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(data)

    def _send_frame(self, data: bytes) -> None:
        if not self.sock:
            raise RuntimeError("CDP client is not connected")
        first = 0x81
        length = len(data)
        mask_bit = 0x80
        if length < 126:
            header = struct.pack("!BB", first, mask_bit | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, mask_bit | 126, length)
        else:
            header = struct.pack("!BBQ", first, mask_bit | 127, length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def _read_json(self) -> Dict[str, Any]:
        data = self._read_frame()
        return json.loads(data.decode("utf-8"))

    def _read_frame(self) -> bytes:
        if not self.sock:
            raise RuntimeError("CDP client is not connected")
        first_two = self._recv_exact(2)
        opcode = first_two[0] & 0x0F
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if first_two[1] & 0x80:
            mask = self._recv_exact(4)
            data = self._recv_exact(length)
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        else:
            data = self._recv_exact(length)
        if opcode == 0x8:
            raise RuntimeError("CDP WebSocket closed")
        if opcode not in {0x1, 0x2}:
            return self._read_frame()
        return data

    def _recv_exact(self, length: int) -> bytes:
        if not self.sock:
            raise RuntimeError("CDP client is not connected")
        chunks = []
        remaining = length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RuntimeError("Socket closed while reading CDP response")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
