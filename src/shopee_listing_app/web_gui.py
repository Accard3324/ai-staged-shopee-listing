from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
import errno
import hashlib
import inspect
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser

from .ai_provider import (
    AGNES_DEFAULT_BASE_URL,
    AGNES_TEXT_DEFAULT_MODEL,
    AGNES_VISION_DEFAULT_MODEL,
    AI_EXECUTION_MODE_MULTIMODAL,
    AI_EXECUTION_MODE_VISION_TEXT,
    AI_MODEL_LABELS,
    MULTIMODAL_AI_MODELS,
    NVIDIA_MINIMAX_VISION_MODEL,
    NVIDIA_TEXT_DEFAULT_MODEL,
    NVIDIA_VISION_DEFAULT_MODEL,
    OPENAI_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_MODEL,
    VISION_TEXT_AI_MODELS,
    NvidiaDualProvider,
    OfflineAIProvider,
    ZhipuProvider,
    get_ai_provider,
    load_project_env,
    mask_secret,
    nvidia_vision_analysis_targets,
    objective_product_info_for_text,
)
from .asset_inspector import AssetManifest, inspect_assets, normalize_asset_path
from .assets.image_filter import validate_confirmed_image_selection
from .browser.cdp_client import CdpClient, list_pages
from .candidate_selector import CandidateSKU, CandidateSelectionResult, select_candidates
from .competitor_collector import collect_competitors, safe_filename
from .competitor_input import URL_RE, parse_manual_competitors, save_manual_competitors
from .config_manager import AIConfig, PROJECT_ROOT, add_custom_store_name, load_app_config
from .gui_state import GuiInitialState, build_initial_gui_state
from .listing_builder import build_description_with_seo, build_listing_draft
from .linear_workflow_ui import build_linear_home_html
from .listing_workbook_writer import append_listing_record
from .nvidia_request_control import (
    NvidiaRateLimitExhausted,
    get_nvidia_request_controller,
    nvidia_request_batch_scope,
)
from .prompt_config import PROMPT_KEYS, load_prompt_config, parse_seo_keyword_count, save_prompt_config
from .report_writer import ensure_output_dirs, timestamp, write_json, write_run_report
from .serverchan_notification import send_serverchan_message
from .wxpusher_notification import send_wxpusher_spt_message
from .windows_alert import show_topmost_error_alert, show_topmost_success_alert
from .shopee.page_probe import run_real_page_probe
from .shopee.product_new_page import (
    run_autofill_from_draft,
    run_fetch_product_id_from_draft,
    run_linear_stage_from_draft,
    run_save_delist_only_from_draft,
)
from .ziniao_connector import (
    detect_ziniao_store_name,
    discover_cdp_candidates,
    probe_json_version,
)


class WebAppState:
    def __init__(self) -> None:
        self.config = load_app_config(PROJECT_ROOT / "config")
        self.selection: Optional[CandidateSelectionResult] = None
        self.current_candidate: Optional[CandidateSKU] = None
        self.asset_manifest: Optional[AssetManifest] = None
        self.asset_download_status = "Waiting for a manually supplied asset-pack path"
        self.selected_asset_path = ""
        self.competitors: Dict[str, Any] = {"sources": []}
        self.asset_analysis: Dict[str, Any] = {}
        self.search_keywords: Dict[str, Any] = {}
        self.title_analysis: Dict[str, Any] = {}
        self.ai_result: Dict[str, Any] = {}
        self.ai_warnings: list[str] = []
        self.ai_runtime_status: Dict[str, Any] = get_nvidia_request_controller().status()
        self.image_analysis_progress: Dict[str, Any] = {
            "current_file": "",
            "total": 0,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "cached": 0,
            "rate_limit_waiting": False,
            "items": [],
        }
        self.ai_reasoning_lock = threading.RLock()
        self.ai_result_lock = threading.RLock()
        self.ai_reasoning: Dict[str, Any] = {
            "vision": {"current_file": "", "model": "", "text": "", "status": "idle", "items": []},
            "keywords": {"model": "", "text": "", "status": "idle"},
            "title": {"model": "", "text": "", "status": "idle"},
            "description": {"model": "", "text": "", "status": "idle"},
        }
        self.listing_runtime_status: Dict[str, Any] = {"state": "idle", "message": "The listing workflow has not started"}
        self.nvidia_rate_limit_reports: list[Dict[str, Any]] = []
        self.confirmed_image_selection: Dict[str, Any] = {}
        self.selected_store_name = ""
        self.last_ai_model = ""
        self.ai_model_check_path = ""
        self.draft: Optional[Dict[str, Any]] = None
        self.draft_path = ""
        self.report_path = ""
        self.last_checklist: Dict[str, Any] = {}
        self.last_listing_result: Dict[str, Any] = {}
        self.last_workbook_update: Dict[str, Any] = {}
        self.listing_results: Dict[str, Dict[str, Any]] = {}
        self.last_listing_result_token = ""
        self.listing_result_lock = threading.RLock()
        self.task_id = ""
        self.multi_group_id = ""
        self.multi_slot = 0
        self.multi_count = 0
        self.cdp_port = 0
        self.cdp_process_id = 0
        self.cdp_binding_confirmed = False
        self.cdp_bound_store_name = ""
        self.cdp_bound_window_label = ""
        self.reserved_listing_key: tuple[str, str, str] | None = None
        self.action_request_lock = threading.RLock()
        self.action_request_ids: Dict[str, str] = {}
        self.action_request_batch_ids: Dict[str, str] = {}


_DEFAULT_APP_STATE = WebAppState()
_ACTIVE_APP_STATE: ContextVar[Optional[WebAppState]] = ContextVar("active_shopee_app_state", default=None)
_TASK_STATES: Dict[str, WebAppState] = {}
_MULTI_GROUPS: Dict[str, list[str]] = {}
_SKU_RESERVATIONS: Dict[tuple[str, str, str], str] = {}
_TASK_REGISTRY_LOCK = threading.RLock()
_ACTIVE_ACTION_REQUEST: ContextVar[Optional["ActionRequestGuard"]] = ContextVar(
    "active_shopee_action_request",
    default=None,
)


class ActionRequestSuperseded(RuntimeError):
    """Raised when a newer retry has replaced the current request."""


@dataclass(frozen=True)
class ActionRequestGuard:
    state: WebAppState
    action: str
    request_id: str


class _AppStateProxy:
    def resolve(self) -> WebAppState:
        return _ACTIVE_APP_STATE.get() or _DEFAULT_APP_STATE

    def __getattr__(self, name: str) -> Any:
        return getattr(self.resolve(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.resolve(), name, value)


APP_STATE = _AppStateProxy()
APP_RELEASE_ID = "2026-07-31-empty-stock-fallback-v53"
_PROMPT_CONFIG_LOCK = threading.RLock()
_ENV_CONFIG_LOCK = threading.RLock()
_UI_HEARTBEAT_TIMEOUT_SECONDS = 90.0
_UI_EMPTY_SHUTDOWN_SECONDS = 8.0


def _runtime_context_id() -> str:
    session_id = ""
    elevated = ""
    if os.name == "nt":
        try:
            import ctypes

            value = ctypes.c_uint()
            if ctypes.windll.kernel32.ProcessIdToSessionId(
                ctypes.c_uint(os.getpid()),
                ctypes.byref(value),
            ):
                session_id = str(value.value)
            elevated = "1" if ctypes.windll.shell32.IsUserAnAdmin() else "0"
        except (AttributeError, OSError):
            pass

    account = "\\".join(
        part
        for part in (
            os.environ.get("USERDOMAIN", "").strip(),
            os.environ.get("USERNAME", "").strip(),
        )
        if part
    )
    home = os.path.normcase(os.path.abspath(str(Path.home())))
    session_name = os.environ.get("SESSIONNAME", "").strip()
    identity = "\n".join((account.casefold(), home.casefold(), session_id, session_name.casefold(), elevated))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class UiClientRegistry:
    def __init__(
        self,
        heartbeat_timeout: float = _UI_HEARTBEAT_TIMEOUT_SECONDS,
        shutdown_delay: float = _UI_EMPTY_SHUTDOWN_SECONDS,
    ) -> None:
        self.heartbeat_timeout = heartbeat_timeout
        self.shutdown_delay = shutdown_delay
        self._lock = threading.RLock()
        self._clients: Dict[str, float] = {}
        self._ever_connected = False
        self._empty_since: Optional[float] = None

    @staticmethod
    def normalize_client_id(value: object) -> str:
        client_id = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", client_id):
            return client_id
        return ""

    def heartbeat(self, client_id: object, now: Optional[float] = None) -> bool:
        normalized = self.normalize_client_id(client_id)
        if not normalized:
            return False
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            self._clients[normalized] = observed_at
            self._ever_connected = True
            self._empty_since = None
        return True

    def close(self, client_id: object, now: Optional[float] = None) -> bool:
        normalized = self.normalize_client_id(client_id)
        if not normalized:
            return False
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            existed = self._clients.pop(normalized, None) is not None
            self._prune_locked(observed_at)
        return existed

    def should_shutdown(self, now: Optional[float] = None) -> bool:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            self._prune_locked(observed_at)
            return bool(
                self._ever_connected
                and not self._clients
                and self._empty_since is not None
                and observed_at - self._empty_since >= self.shutdown_delay
            )

    def _prune_locked(self, observed_at: float) -> None:
        stale_ids = [
            client_id
            for client_id, last_seen in self._clients.items()
            if observed_at - last_seen >= self.heartbeat_timeout
        ]
        for client_id in stale_ids:
            self._clients.pop(client_id, None)
        if self._ever_connected and not self._clients:
            if self._empty_since is None:
                self._empty_since = observed_at
        else:
            self._empty_since = None


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ui_clients = UiClientRegistry()
        self.lifecycle_stop_event = threading.Event()

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def active_app_state() -> WebAppState:
    return APP_STATE.resolve() if isinstance(APP_STATE, _AppStateProxy) else APP_STATE


@contextmanager
def app_state_scope(task_id: str = ""):
    normalized_task_id = _normalize_task_id(task_id)
    if normalized_task_id:
        with _TASK_REGISTRY_LOCK:
            state = _TASK_STATES.get(normalized_task_id)
            if state is None:
                raise RuntimeError("The multi-store task does not exist or is closed. Return to the single-store page and start it again.")
    else:
        state = _DEFAULT_APP_STATE
    token = _ACTIVE_APP_STATE.set(state)
    try:
        yield state
    finally:
        _ACTIVE_APP_STATE.reset(token)


def _normalize_action_request_id(value: object) -> str:
    request_id = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
        return request_id
    return secrets.token_urlsafe(18).replace("-", "_")


def begin_action_request(
    state: WebAppState,
    action: str,
    request_id: object,
) -> ActionRequestGuard:
    normalized_action = str(action or "").strip()
    normalized_request_id = _normalize_action_request_id(request_id)
    old_batch_id = ""
    with state.action_request_lock:
        old_batch_id = state.action_request_batch_ids.pop(normalized_action, "")
        state.action_request_ids[normalized_action] = normalized_request_id
    if old_batch_id:
        get_nvidia_request_controller().finish_batch(old_batch_id)
    return ActionRequestGuard(state, normalized_action, normalized_request_id)


@contextmanager
def action_request_scope(guard: ActionRequestGuard):
    token = _ACTIVE_ACTION_REQUEST.set(guard)
    try:
        yield guard
    finally:
        _ACTIVE_ACTION_REQUEST.reset(token)


def current_action_request_guard() -> Optional[ActionRequestGuard]:
    return _ACTIVE_ACTION_REQUEST.get()


def is_action_request_current(guard: Optional[ActionRequestGuard] = None) -> bool:
    active_guard = guard or current_action_request_guard()
    if active_guard is None:
        return True
    with active_guard.state.action_request_lock:
        return (
            active_guard.state.action_request_ids.get(active_guard.action)
            == active_guard.request_id
        )


def ensure_action_request_current(
    guard: Optional[ActionRequestGuard] = None,
) -> None:
    if not is_action_request_current(guard):
            raise ActionRequestSuperseded("This request was superseded by a new retry; the old result was discarded.")


def assign_action_request_batch(guard: ActionRequestGuard, batch_id: str) -> None:
    if not batch_id:
        return
    with guard.state.action_request_lock:
        if (
            guard.state.action_request_ids.get(guard.action)
            != guard.request_id
        ):
            get_nvidia_request_controller().finish_batch(batch_id)
            raise ActionRequestSuperseded("This request was superseded by a new retry.")
        guard.state.action_request_batch_ids[guard.action] = batch_id


def finish_action_request(guard: ActionRequestGuard) -> None:
    with guard.state.action_request_lock:
        if (
            guard.state.action_request_ids.get(guard.action)
            != guard.request_id
        ):
            return
        guard.state.action_request_ids.pop(guard.action, None)
        guard.state.action_request_batch_ids.pop(guard.action, None)


def cancel_action_request(
    state: WebAppState,
    action: str,
    request_id: object = "",
) -> bool:
    normalized_action = str(action or "").strip()
    expected_request_id = str(request_id or "").strip()
    batch_id = ""
    with state.action_request_lock:
        current_request_id = state.action_request_ids.get(normalized_action, "")
        if not current_request_id:
            return False
        if expected_request_id and current_request_id != expected_request_id:
            return False
        state.action_request_ids.pop(normalized_action, None)
        batch_id = state.action_request_batch_ids.pop(normalized_action, "")
    if batch_id:
        get_nvidia_request_controller().finish_batch(batch_id)
    return True


def guarded_action_callback(
    guard: Optional[ActionRequestGuard],
    callback: Any,
) -> Any:
    def guarded(value: Any) -> None:
        if is_action_request_current(guard):
            callback(value)

    return guarded


def _normalize_task_id(value: object) -> str:
    task_id = str(value or "").strip()
    return task_id if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", task_id) else ""


def current_task_context() -> Dict[str, object]:
    state = active_app_state()
    return {
        "task_id": str(getattr(state, "task_id", "") or ""),
        "multi_group_id": str(getattr(state, "multi_group_id", "") or ""),
        "multi_slot": int(getattr(state, "multi_slot", 0) or 0),
        "multi_count": int(getattr(state, "multi_count", 0) or 0),
    }


def task_output_root() -> Path:
    task_id = str(getattr(active_app_state(), "task_id", "") or "")
    if task_id:
        return PROJECT_ROOT / "outputs" / "multi_tasks" / task_id
    return PROJECT_ROOT / "outputs"


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _measure_generated_path(path: Path) -> tuple[int, int]:
    if not path.exists() and not path.is_symlink():
        return 0, 0
    if path.is_file() or path.is_symlink():
        try:
            return 1, int(path.stat().st_size)
        except OSError:
            return 1, 0
    files = 0
    total_bytes = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        files += 1
        try:
            total_bytes += int(item.stat().st_size)
        except OSError:
            pass
    return files, total_bytes


def _remove_generated_path(path: Path, allowed_root: Path) -> tuple[int, int]:
    if not _path_is_within(path, allowed_root) or path.resolve(strict=False) == allowed_root.resolve(strict=False):
        raise RuntimeError(f"Refusing to clean a path outside the allowlist: {path}")
    files, total_bytes = _measure_generated_path(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)
    return files, total_bytes


def _clear_generated_tree(
    root: Path,
    protected_paths: list[Path],
) -> tuple[int, int]:
    root = root.resolve(strict=False)
    if not root.exists():
        return 0, 0
    protected = [
        path.resolve(strict=False)
        for path in protected_paths
        if _path_is_within(path, root)
    ]
    files = 0
    total_bytes = 0

    def clear_children(directory: Path) -> None:
        nonlocal files, total_bytes
        for child in list(directory.iterdir()):
            resolved = child.resolve(strict=False)
            protects_child = [
                path
                for path in protected
                if path == resolved or _path_is_within(path, resolved)
            ]
            if resolved in protected:
                continue
            if protects_child and child.is_dir() and not child.is_symlink():
                clear_children(child)
                try:
                    if not any(child.iterdir()):
                        child.rmdir()
                except OSError:
                    pass
                continue
            removed_files, removed_bytes = _remove_generated_path(child, root)
            files += removed_files
            total_bytes += removed_bytes

    clear_children(root)
    return files, total_bytes


def _reset_generated_task_state(state: WebAppState) -> None:
    preserved = {
        "config": state.config,
        "selected_store_name": state.selected_store_name,
        "task_id": state.task_id,
        "multi_group_id": state.multi_group_id,
        "multi_slot": state.multi_slot,
        "multi_count": state.multi_count,
        "cdp_port": state.cdp_port,
        "cdp_process_id": state.cdp_process_id,
        "cdp_binding_confirmed": state.cdp_binding_confirmed,
        "cdp_bound_store_name": state.cdp_bound_store_name,
        "cdp_bound_window_label": state.cdp_bound_window_label,
    }
    if state.reserved_listing_key:
        with _TASK_REGISTRY_LOCK:
            _SKU_RESERVATIONS.pop(state.reserved_listing_key, None)
    fresh = WebAppState()
    state.__dict__.clear()
    state.__dict__.update(fresh.__dict__)
    state.__dict__.update(preserved)


def _reset_sku_dependent_state(state: WebAppState) -> None:
    """Clear one product's runtime data while preserving task, store, AI, and CDP settings."""
    state.selection = None
    state.current_candidate = None
    state.asset_manifest = None
    state.asset_download_status = "Waiting for a manually supplied asset-pack path"
    state.selected_asset_path = ""
    state.competitors = {"sources": []}
    state.asset_analysis = {}
    state.search_keywords = {}
    state.title_analysis = {}
    with state.ai_result_lock:
        state.ai_result = {}
        state.ai_warnings = []
    state.image_analysis_progress = {
        "current_file": "",
        "total": 0,
        "completed": 0,
        "success": 0,
        "failed": 0,
        "cached": 0,
        "rate_limit_waiting": False,
        "items": [],
    }
    with state.ai_reasoning_lock:
        state.ai_reasoning = new_ai_reasoning_state()
    state.listing_runtime_status = {"state": "idle", "message": "Listing workflow has not started"}
    state.nvidia_rate_limit_reports = []
    state.confirmed_image_selection = {}
    state.last_ai_model = ""
    state.ai_model_check_path = ""
    state.draft = None
    state.draft_path = ""
    state.report_path = ""
    state.last_checklist = {}
    with state.listing_result_lock:
        state.last_listing_result = {}
        state.last_workbook_update = {}
        state.listing_results = {}
        state.last_listing_result_token = ""


def _clear_cdp_binding(state: WebAppState) -> None:
    state.cdp_port = 0
    state.cdp_process_id = 0
    state.cdp_binding_confirmed = False
    state.cdp_bound_store_name = ""
    state.cdp_bound_window_label = ""


def _draft_store_name_if_available() -> str:
    draft = APP_STATE.draft if isinstance(APP_STATE.draft, dict) else {}
    store = draft.get("store", {}) if isinstance(draft.get("store", {}), dict) else {}
    return str(store.get("name", "") or "").strip()


def _expected_task_store(payload: Optional[Dict[str, Any]] = None) -> str:
    draft_store = _draft_store_name_if_available()
    payload_store = str((payload or {}).get("store", "") or "").strip()
    selected_store = str(APP_STATE.selected_store_name or "").strip()
    if draft_store and payload_store and draft_store.casefold() != payload_store.casefold():
        raise RuntimeError(
                f'The current listing draft belongs to store "{draft_store}", but the page has "{payload_store}" selected. '
                "Switch to the correct store or regenerate this store's product data from Step 1."
        )
    return draft_store or selected_store or payload_store


def _restore_exact_store_cdp_binding(
    state: WebAppState,
    expected_store: str,
    candidates: Optional[list[Any]] = None,
) -> bool:
    normalized_store = _normalize_store_name(expected_store)
    if not normalized_store:
        return False
    available_candidates = (
        candidates
        if candidates is not None
        else discover_cdp_candidates(verify=True)
    )
    matches = [
        candidate
        for candidate in available_candidates
        if _normalize_store_name(
            _candidate_store_name(candidate, expected_names=[expected_store])
        )
        == normalized_store
    ]
    if len(matches) != 1:
        return False
    candidate = matches[0]
    port = int(candidate.port)
    with _TASK_REGISTRY_LOCK:
        conflict = next(
            (
                other
                for other in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]
                if other is not state
                and other.cdp_binding_confirmed
                and int(other.cdp_port or 0) == port
            ),
            None,
        )
        if conflict is not None:
            return False
        state.cdp_port = port
        state.cdp_process_id = int(candidate.process_id or 0)
        state.cdp_binding_confirmed = True
        state.cdp_bound_store_name = expected_store
        state.cdp_bound_window_label = (
            _candidate_store_name(candidate, expected_names=[expected_store])
            or f"Port {port}"
        )
    return True


def assigned_task_cdp_port(required_store_name: str = "") -> Optional[int]:
    state = active_app_state()
    expected_store = str(required_store_name or _expected_task_store()).strip()
    if not state.cdp_binding_confirmed or not state.cdp_port:
        candidates = discover_cdp_candidates(verify=True)
        if _restore_exact_store_cdp_binding(state, expected_store, candidates):
            return int(state.cdp_port)
        raise RuntimeError(
            "This listing task is not manually bound to a Ziniao store window. "
            "Refresh the window list in Step 9, locate the correct window, and confirm the binding."
        )
    if (
        expected_store
        and state.cdp_bound_store_name
        and expected_store.casefold() != state.cdp_bound_store_name.casefold()
    ):
        bound_store = state.cdp_bound_store_name
        _clear_cdp_binding(state)
        raise RuntimeError(
            f'The previous Ziniao window was bound to "{bound_store}", while this task belongs to "{expected_store}". '
            "The binding was removed; bind the correct window again in Step 9."
        )
    candidates = discover_cdp_candidates(verify=True)
    candidate = next(
        (item for item in candidates if int(item.port) == int(state.cdp_port)),
        None,
    )
    if candidate is None:
        if _restore_exact_store_cdp_binding(state, expected_store, candidates):
            return int(state.cdp_port)
        if not probe_json_version(int(state.cdp_port)):
            raise RuntimeError(
            "The bound Ziniao port is temporarily unreachable; the binding was preserved. "
            "Keep that store window open and retry without matching it again."
            )
    else:
        detected_store = _candidate_store_name(
            candidate,
            expected_names=[expected_store] if expected_store else (),
        )
        if (
            expected_store
            and detected_store
            and _normalize_store_name(detected_store)
            != _normalize_store_name(expected_store)
        ):
            if _restore_exact_store_cdp_binding(state, expected_store, candidates):
                return int(state.cdp_port)
            raise RuntimeError(
            f'Port {state.cdp_port} now belongs to store "{detected_store}". '
            f'No new window was found for "{expected_store}"; bind it again in Step 9.'
            )
        if int(candidate.process_id or 0):
            state.cdp_process_id = int(candidate.process_id)
    with _TASK_REGISTRY_LOCK:
        conflict = next(
            (
                other
                for other in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]
                if other is not state
                and other.cdp_binding_confirmed
                and int(other.cdp_port or 0) == int(state.cdp_port)
            ),
            None,
        )
        if conflict is not None:
            conflicting_store = conflict.cdp_bound_store_name or "another store"
            _clear_cdp_binding(state)
            raise RuntimeError(
                f'This Ziniao window is already bound to "{conflicting_store}". The current task binding was removed. '
                "Select another window in Step 9."
            )
    return int(state.cdp_port)


def build_home_html(
    state: GuiInitialState,
    task_context: Optional[Dict[str, object]] = None,
) -> str:
    return build_linear_home_html(state, task_context=task_context or current_task_context())



class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        task_id = _normalize_task_id((query.get("task_id") or [""])[0])
        if parsed.path == "/api/app-info":
            self.respond_json(
                {
                    "ok": True,
                    "app": "shopee_listing_app",
                    "release_id": APP_RELEASE_ID,
                    "runtime_context_id": _runtime_context_id(),
                    "pid": os.getpid(),
                    "ui_lifecycle": True,
                }
            )
            return
        if parsed.path == "/asset-image":
            try:
                index = int((query.get("index") or [""])[0])
                with app_state_scope(task_id):
                    path = Path(asset_candidates()[index]["path"])
                if not path.is_file():
                    raise FileNotFoundError(path)
                self.respond_file(path)
            except (ValueError, IndexError, FileNotFoundError):
                self.respond_json({"ok": False, "message": "Asset preview not found"}, status=404)
            return
        if parsed.path == "/":
            try:
                with app_state_scope(task_id):
                    state = build_initial_gui_state(PROJECT_ROOT / "config")
                    self.respond_html(build_home_html(state, current_task_context()))
            except RuntimeError as exc:
                self.respond_html(
                    "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                        f"<title>Multi-Store Task Closed</title><body><p>{escape_html(str(exc))}</p>"
                        "<p><a href='/'>Return to Single-Store Mode</a></p></body></html>"
                )
            return
        self.respond_json({"ok": False, "message": "Not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.respond_json({"ok": False, "message": "Not found"}, status=404)
            return
        action = parsed.path.rsplit("/", 1)[-1]
        payload = self.read_json()
        if action == "ui-heartbeat":
            registry = getattr(self.server, "ui_clients", None)
            accepted = bool(registry and registry.heartbeat(payload.get("client_id", "")))
            self.respond_json(
                {
                    "ok": accepted,
                    "message": "Interface connection registered" if accepted else "Invalid interface connection identifier",
                },
                status=200 if accepted else 400,
            )
            return
        if action == "ui-client-close":
            registry = getattr(self.server, "ui_clients", None)
            if registry:
                registry.close(payload.get("client_id", ""))
            self.respond_json({"ok": True, "message": "Interface close state registered"})
            return
        if action == "shutdown":
            self.respond_json({"ok": True, "message": "The application background process is closing"})
            _schedule_server_shutdown(self.server)
            return
        try:
            task_id = self.request_task_id(payload)
            with app_state_scope(task_id):
                if action == "cancel-action":
                    target_action = str(payload.get("target_action") or "").strip()
                    cancelled = cancel_action_request(
                        active_app_state(),
                        target_action,
                        payload.get("target_request_id", ""),
                    )
                    self.respond_json(
                        {
                            "ok": True,
                            "cancelled": cancelled,
                            "message": (
                            f"Stopped the wait and invalidated the old request: {target_action}"
                                if cancelled
                            else "The old request has ended or was superseded by a new retry"
                            ),
                        }
                    )
                    return
                guard = begin_action_request(
                    active_app_state(),
                    action,
                    payload.get("_request_id", ""),
                )
                controller = get_nvidia_request_controller()
                batch_id = ""
                try:
                    if action in AI_BATCH_ACTIONS:
                        batch_id = controller.begin_batch(
                            task_id or "single",
                            action,
                            expected_ai_request_count(action),
                        )
                        assign_action_request_batch(guard, batch_id)
                    with action_request_scope(guard):
                        with nvidia_request_batch_scope(batch_id, task_id or "single"):
                            result = handle_action(action, payload)
                        ensure_action_request_current(guard)
                finally:
                    controller.finish_batch(batch_id)
                    finish_action_request(guard)
            self.respond_json(
                {"ok": True, "_request_id": guard.request_id, **result}
            )
        except ActionRequestSuperseded as exc:
            self.respond_json(
                {
                    "ok": False,
                    "cancelled": True,
                    "superseded": True,
                    "message": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001
            log_path = PROJECT_ROOT / "logs" / f"web_gui_error_{timestamp()}.log"
            safe_error = mask_known_secrets(exc)
            log_path.write_text(f"{action} failed: {safe_error}", encoding="utf-8")
            self.respond_json({"ok": False, "message": safe_error, "log_path": str(log_path)})

    def request_task_id(self, payload: Dict[str, Any]) -> str:
        task_id = _normalize_task_id(payload.get("task_id", ""))
        if task_id:
            return task_id
        referer = str(self.headers.get("Referer", "") or "")
        if referer:
            query = parse_qs(urlparse(referer).query)
            task_id = _normalize_task_id((query.get("task_id") or [""])[0])
        return task_id

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def respond_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # The browser intentionally disconnects the old request after Retry or Stop.
            return

    def respond_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


AI_BATCH_ACTIONS = {
    "analyze-images",
    "generate-keywords",
    "analyze-title",
    "generate-description",
    "analyze-ai",
    "test-nvidia-vision",
    "test-nvidia-minimax",
    "test-nvidia-text",
    "test-all-ai",
}


def expected_ai_request_count(action: str) -> int:
    if action == "analyze-images" and APP_STATE.asset_manifest is not None:
        return max(1, len(nvidia_vision_analysis_targets(APP_STATE.asset_manifest)))
    if action == "test-all-ai":
        return 3
    if action == "analyze-ai":
        return 4
    return 1


def handle_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_output_dirs(PROJECT_ROOT)
    if action == "start-multi-store-mode":
        return action_start_multi_store_mode(payload)
    if action == "close-multi-store-mode":
        return action_close_multi_store_mode(payload)
    if action == "select-candidates":
        return action_select_candidates(payload)
    if action == "inspect-assets":
        return action_inspect_assets(payload)
    if action == "analyze-images":
        return action_analyze_images(payload)
    if action == "generate-keywords":
        return action_generate_keywords(payload)
    if action == "analyze-title":
        return action_analyze_title(payload)
    if action == "validate-competitors":
        return action_validate_competitors(payload)
    if action == "generate-description":
        return action_generate_description(payload)
    if action == "ai-status":
        global_ai_status = get_nvidia_request_controller().status(
            str(APP_STATE.task_id or "single")
        )
        APP_STATE.ai_runtime_status = {
            **APP_STATE.ai_runtime_status,
            **global_ai_status,
        }
        return {
            "message": "runtime status",
            "ai_status": APP_STATE.ai_runtime_status,
            "listing_status": APP_STATE.listing_runtime_status,
            "image_analysis_progress": APP_STATE.image_analysis_progress,
            "ai_reasoning": ai_reasoning_snapshot(),
            "asset_download_status": APP_STATE.asset_download_status,
        }
    if action == "load-prompts":
        return {"message": "Local prompts loaded", "result": current_result(), "workbench": workbench_payload()}
    if action == "save-prompts":
        return action_save_prompts(payload)
    if action == "save-custom-store":
        return action_save_custom_store(payload)
    if action == "get-description-template":
        return action_get_description_template(payload)
    if action == "save-description-template":
        return action_save_description_template(payload)
    if action == "analyze-ai":
        return action_analyze_ai(payload)
    if action == "confirm-image-selection":
        return action_confirm_image_selection(payload)
    if action == "confirm-ai-results":
        return action_confirm_ai_results(payload)
    if action == "test-zhipu-ai":
        return action_test_zhipu_ai()
    if action == "save-ai-settings":
        return action_save_ai_settings(payload)
    if action == "test-serverchan":
        return action_test_serverchan(payload)
    if action == "test-wxpusher":
        return action_test_wxpusher(payload)
    if action == "send-workflow-failure":
        return action_send_workflow_failure(payload)
    if action == "send-action-success":
        return action_send_action_success(payload)
    if action == "test-nvidia-vision":
        return action_test_nvidia_ai(payload, "vision")
    if action == "test-nvidia-minimax":
        return action_test_nvidia_ai(payload, "minimax")
    if action == "test-nvidia-text":
        return action_test_nvidia_ai(payload, "text")
    if action == "test-all-ai":
        return action_test_all_ai(payload)
    if action == "collect-competitors":
        return action_collect_competitors(payload)
    if action == "generate-listing":
        return action_analyze_ai(payload)
    if action == "open-outputs":
        return open_folder(task_output_root())
    if action == "open-logs":
        return open_folder(PROJECT_ROOT / "logs")
    if action == "list-ziniao-windows":
        return action_list_ziniao_windows()
    if action == "preview-ziniao-window":
        return action_preview_ziniao_window(payload)
    if action == "bind-ziniao-window":
        return action_bind_ziniao_window(payload)
    if action == "auto-bind-ziniao-window":
        return action_auto_bind_ziniao_window(payload)
    if action == "unbind-ziniao-window":
        return action_unbind_ziniao_window()
    if action == "validate-ziniao-binding":
        return action_validate_ziniao_binding(payload)
    if action == "connect-ziniao":
        return action_connect_ziniao()
    if action == "open-shopee-page":
        return action_run_linear_shopee_stage("open", payload)
    if action == "execute-step1":
        return action_run_linear_shopee_stage("step1", payload)
    if action == "execute-step2":
        return action_run_linear_shopee_stage("step2", payload)
    if action == "run-checklist":
        return action_run_linear_shopee_stage("checklist", payload)
    if action == "open-final-report":
        return open_folder(task_output_root() / "reports")
    if action == "probe-shopee-page":
        return action_probe_shopee_page()
    if action == "auto-fill":
        return action_auto_fill(payload)
    if action == "save-delist":
        payload = dict(payload)
        payload["run_mode"] = "save_delist"
        return action_auto_fill(payload)
    if action == "fetch-product-id":
        return action_fetch_product_id(payload)
    if action == "record-listing-result":
        return action_record_listing_result(payload)
    if action == "cleanup-cache":
        return action_cleanup_cache()
    raise RuntimeError(f"Unknown action: {action}")


def action_start_multi_store_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        count = int(payload.get("multi_store_count", 0))
    except (TypeError, ValueError):
        count = 0
    if count < 2 or count > 5:
        raise RuntimeError("Multi-store mode requires 2 to 5 store pages.")

    group_id = secrets.token_urlsafe(12).replace("-", "_")
    task_ids: list[str] = []
    with _TASK_REGISTRY_LOCK:
        for slot in range(1, count + 1):
            task_id = secrets.token_urlsafe(18).replace("-", "_")
            state = WebAppState()
            state.task_id = task_id
            state.multi_group_id = group_id
            state.multi_slot = slot
            state.multi_count = count
            _TASK_STATES[task_id] = state
            task_ids.append(task_id)
        _MULTI_GROUPS[group_id] = task_ids

    task_urls = [
        "/?" + urlencode(
            {
                "task_id": task_id,
                "multi_group_id": group_id,
                "slot": index,
                "count": count,
            }
        )
        for index, task_id in enumerate(task_ids, start=1)
    ]
    return {
        "message": f"Multi-store mode started with {count} independent pages",
        "multi_group_id": group_id,
        "multi_store_count": count,
        "task_urls": task_urls,
    }


def action_close_multi_store_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    group_id = str(
        payload.get("multi_group_id")
        or getattr(active_app_state(), "multi_group_id", "")
        or ""
    ).strip()
    if not group_id:
        return {"message": "The app is already in single-store mode", "closed_task_ids": []}

    with _TASK_REGISTRY_LOCK:
        task_ids = list(_MULTI_GROUPS.pop(group_id, []))
        for task_id in task_ids:
            state = _TASK_STATES.get(task_id)
            if state and state.reserved_listing_key:
                _SKU_RESERVATIONS.pop(state.reserved_listing_key, None)
            _TASK_STATES.pop(task_id, None)
    return {
        "message": "Multi-store mode closed; the main page will return to single-store mode",
        "multi_group_id": group_id,
        "closed_task_ids": task_ids,
    }


def action_select_candidates(payload: Dict[str, Any]) -> Dict[str, Any]:
    requested_sku_code = str(payload.get("manual_sku_code", "") or "").strip()
    selection_mode = str(payload.get("sku_selection_mode", "") or "").strip().lower()
    if selection_mode == "manual" and not requested_sku_code:
            raise RuntimeError("Enter the SKU code to load first.")
    multi_task = bool(APP_STATE.task_id)
    selection_count = 1000 if multi_task and not requested_sku_code else 1
    selection = select_candidates(
        store_name=str(payload.get("store", "")),
        count=selection_count,
        workbook_path=Path(str(payload.get("workbook", ""))),
        config_dir=PROJECT_ROOT / "config",
        requested_sku_code=requested_sku_code or None,
    )
    if multi_task and selection.candidates:
        chosen = _reserve_candidate_for_task(
            selection.candidates,
            workbook_path=str(payload.get("workbook", "")),
            store_name=str(payload.get("store", "")),
        )
        if chosen is None:
            if requested_sku_code:
                raise RuntimeError(
                f"SKU {requested_sku_code} is already reserved by another multi-store task"
                )
            raise RuntimeError("All unlisted SKUs for this store are reserved by other multi-store tasks.")
        selection = replace(
            selection,
            requested_count=1,
            returned_count=1,
            candidates=[chosen],
        )
    if not selection.candidates:
        if requested_sku_code:
            raise RuntimeError(f"SKU code not found in the product workbook: {requested_sku_code}")
        raise RuntimeError("No unlisted SKU was found.")
    selected_store_name = str(payload.get("store", "")).strip()
    if (
        APP_STATE.task_id
        and APP_STATE.cdp_binding_confirmed
        and APP_STATE.cdp_bound_store_name
        and APP_STATE.cdp_bound_store_name.casefold() != selected_store_name.casefold()
    ):
        _clear_cdp_binding(active_app_state())
    _reset_sku_dependent_state(active_app_state())
    APP_STATE.selection = selection
    APP_STATE.current_candidate = selection.candidates[0]
    APP_STATE.selected_store_name = selected_store_name
    out_path = task_output_root() / "candidates" / f"web_candidates_{timestamp()}.json"
    write_json(out_path, APP_STATE.selection.to_dict())
    selection_message = (
            f"Workbook data loaded for specified SKU {APP_STATE.current_candidate.sku_code}"
        if requested_sku_code
            else f"Unlisted SKU {APP_STATE.current_candidate.sku_code} selected automatically"
    )
    result = current_result()
    result["sku_context_reset"] = "true"
    return {
        "message": selection_message,
        "result": result,
        "workbench": workbench_payload(),
    }


def _reserve_candidate_for_task(
    candidates: list[CandidateSKU],
    *,
    workbook_path: str,
    store_name: str,
) -> Optional[CandidateSKU]:
    state = active_app_state()
    workbook_key = str(Path(workbook_path).resolve()).casefold()
    store_key = str(store_name or "").strip().casefold()
    with _TASK_REGISTRY_LOCK:
        for candidate in candidates:
            reservation_key = (
                workbook_key,
                store_key,
                str(candidate.sku_code or "").strip().casefold(),
            )
            owner = _SKU_RESERVATIONS.get(reservation_key)
            if owner and owner != state.task_id:
                continue
            if state.reserved_listing_key and state.reserved_listing_key != reservation_key:
                _SKU_RESERVATIONS.pop(state.reserved_listing_key, None)
            _SKU_RESERVATIONS[reservation_key] = state.task_id
            state.reserved_listing_key = reservation_key
            return candidate
    return None


def action_inspect_assets(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = require_candidate()
    asset_path = normalize_asset_path(payload.get("asset_path", ""))
    if not asset_path:
        raise RuntimeError(
            "Enter the local path to a manually supplied asset pack. Automatic asset-pack download is planned but is not implemented in this open-source release."
        )
    sku = safe_filename(str(candidate.sku_code))
    APP_STATE.asset_manifest = inspect_assets(Path(asset_path), task_output_root() / "asset_work" / sku)
    APP_STATE.selected_asset_path = asset_path
    APP_STATE.asset_download_status = f"Loaded manual asset pack: {asset_path}"
    APP_STATE.confirmed_image_selection = {}
    APP_STATE.ai_result = {}
    APP_STATE.image_analysis_progress = {}
    APP_STATE.draft = None
    APP_STATE.draft_path = ""
    APP_STATE.report_path = ""
    manifest_path = task_output_root() / "asset_manifests" / f"{sku}_asset_manifest.json"
    write_json(manifest_path, APP_STATE.asset_manifest.to_dict())
    return {"message": "Manual asset pack inspected successfully", "result": current_result(), "workbench": workbench_payload()}


def _unique(values: Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def action_save_prompts(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompts = payload.get("prompts", {})
    if not isinstance(prompts, dict):
        raise RuntimeError("Prompts must be an object")
    with _PROMPT_CONFIG_LOCK:
        save_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml", prompts)
    return {"message": "Prompts saved to config/prompts.yaml", "result": current_result(), "workbench": workbench_payload()}


def action_save_custom_store(payload: Dict[str, Any]) -> Dict[str, Any]:
    saved_store, created = add_custom_store_name(
        PROJECT_ROOT / "config",
        str(payload.get("store", "")),
        str(payload.get("custom_store_name", "")),
    )
    refreshed = load_app_config(PROJECT_ROOT / "config")
    with _TASK_REGISTRY_LOCK:
        for state in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]:
            state.config = refreshed
        APP_STATE.selected_store_name = saved_store.name
    message = (
        f'Store "{saved_store.name}" added and saved.'
        if created
        else f'Store "{saved_store.name}" already exists and is now selected.'
    )
    return {
        "message": message,
        "created": created,
        "saved_store": saved_store.name,
        "stores": [store.name for store in refreshed.stores.values()],
        "result": current_result(),
    }


REQUIRED_TEMPLATE_PLACEHOLDERS = ("PAIN_POINTS", "BENEFITS", "SPECIFICATIONS", "USAGE")


def _resolve_store_template(store_name: str) -> tuple[str, str, str]:
    store = APP_STATE.config.store(store_name)
    template = APP_STATE.config.description_template(store.template_key)
    return store.name, store.template_key, template


def action_get_description_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    store_name, template_key, template = _resolve_store_template(str(payload.get("store", "")))
    return {
        "message": f"Current store description template: {template_key}",
        "result": current_result(),
        "description_template": {
            "store_name": store_name,
            "template_key": template_key,
            "template": template,
            "template_length": len(template),
        },
    }


def action_save_description_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    store_name, template_key, _current = _resolve_store_template(str(payload.get("store", "")))
    template = str(payload.get("description_template", "")).strip()
    if template:
        missing = [key for key in REQUIRED_TEMPLATE_PLACEHOLDERS if "{{" + key + "}}" not in template]
        if missing:
            raise RuntimeError("The description template is missing required placeholders: " + ", ".join("{{" + key + "}}" for key in missing))
    stores_path = PROJECT_ROOT / "config" / "stores.yaml"
    raw = json.loads(stores_path.read_text(encoding="utf-8"))
    templates = raw.setdefault("description_templates", {})
    if not isinstance(templates, dict):
        raise RuntimeError("description_templates in config/stores.yaml must be an object.")
    templates[template_key] = template
    stores_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    APP_STATE.config.templates[template_key] = template
    operation = "cleared" if not template else "saved"
    return {
        "message": f"Description template for store {store_name} {operation} in config/stores.yaml (template_key: {template_key})",
        "result": current_result(),
        "workbench": workbench_payload(),
        "description_template": {
            "store_name": store_name,
            "template_key": template_key,
            "template": template,
            "template_length": len(template),
        },
    }


def action_confirm_image_selection(payload: Dict[str, Any]) -> Dict[str, Any]:
    if APP_STATE.asset_manifest is None:
        raise RuntimeError("Inspect an asset pack first.")
    image_selection = APP_STATE.ai_result.get("image_selection", {}) if isinstance(APP_STATE.ai_result.get("image_selection"), dict) else {}
    edited_analysis = parse_json_editor(payload, "ai_asset_analysis", image_selection)
    if not isinstance(edited_analysis, dict):
        raise RuntimeError("ai_asset_analysis must be a JSON object")
    selected_main = str(payload.get("selected_main_image", "")).strip() or str(edited_analysis.get("main_image", ""))
    selected_details = payload.get("selected_detail_images")
    if not isinstance(selected_details, list):
        selected_details = edited_analysis.get("detail_images", [])
    unsafe_images = edited_analysis.get("unsafe_images", image_selection.get("unsafe_images", APP_STATE.asset_manifest.unsafe_images))
    if not isinstance(unsafe_images, list):
        raise RuntimeError("unsafe_images must be a JSON list")
    validation = validate_confirmed_image_selection(
        APP_STATE.asset_manifest.to_dict(),
        selected_main,
        selected_details,
        unsafe_images,
        promoted_main_candidates=[str(image_selection.get("main_image", ""))],
    )
    if not validation["ok"]:
        raise RuntimeError("Image selection cannot be confirmed: " + "; ".join(validation["errors"]))
    APP_STATE.confirmed_image_selection = validation
    APP_STATE.ai_result["image_selection"] = {
        "main_image": validation["main_image"],
        "detail_images": validation["detail_images"],
        "sku_images": image_selection.get("sku_images", APP_STATE.asset_manifest.sku_images),
        "unsafe_images": unsafe_images,
    }
    confirmed_paths = {validation["main_image"], *validation["detail_images"]}
    progress_items = APP_STATE.image_analysis_progress.get("items", [])
    if isinstance(progress_items, list):
        for item in progress_items:
            if isinstance(item, dict) and str(item.get("file_path", "")) in confirmed_paths:
                item["status"] = "manually_confirmed"
    per_image_results = APP_STATE.ai_result.get("per_image_results", [])
    if isinstance(per_image_results, list):
        for item in per_image_results:
            if isinstance(item, dict):
                item["manual_confirmed"] = str(item.get("file_path", "")) in confirmed_paths
    return {
        "message": "Image selection confirmed manually; manual selection overrides AI risk assessments",
        "result": current_result(),
        "workbench": workbench_payload(),
    }


def multimodal_product_image_paths(asset_manifest: AssetManifest) -> list[str]:
    """Use all detail images plus English materials, falling back to all SKU images."""
    support_images = (
        asset_manifest.english_images
        if asset_manifest.english_images
        else asset_manifest.sku_images
    )
    paths: list[str] = []
    for path in [*asset_manifest.detail_images, *support_images]:
        normalized = str(path or "").strip()
        if normalized and normalized not in paths:
            paths.append(normalized)
    return paths


def persist_step_ai_preferences(
    *,
    step: int,
    model: str,
    thinking_mode: str,
    reasoning_strength: str,
    execution_mode: str,
) -> None:
    prefix = f"STEP{step}"
    values = {
        "AI_EXECUTION_MODE": execution_mode,
        f"{prefix}_AI_MODEL": model,
        f"{prefix}_THINKING_MODE": thinking_mode,
        f"{prefix}_REASONING_STRENGTH": reasoning_strength,
    }
    legacy_prefix = {
        5: "STEP5_TEXT",
        6: "STEP6_TEXT",
        7: "STEP7_TEXT",
    }.get(step)
    if legacy_prefix:
        values.update(
            {
                f"{legacy_prefix}_MODEL": model,
                f"{legacy_prefix}_THINKING_MODE": thinking_mode,
                f"{legacy_prefix}_REASONING_STRENGTH": reasoning_strength,
            }
        )
    if step == 3:
        values.update(
            {
                "NVIDIA_VISION_MODEL": model,
                "NVIDIA_VISION_THINKING_MODE": thinking_mode,
                "NVIDIA_VISION_REASONING_STRENGTH": reasoning_strength,
            }
        )
    save_local_env_values(values)


def ai_step_product_inputs(
    payload: Dict[str, Any],
) -> tuple[str, Dict[str, object], list[str]]:
    execution_mode = parse_ai_execution_mode(payload)
    if execution_mode == AI_EXECUTION_MODE_MULTIMODAL:
        if APP_STATE.asset_manifest is None:
            raise RuntimeError("Load an asset pack and complete Step 3 first.")
        image_paths = multimodal_product_image_paths(APP_STATE.asset_manifest)
        if not image_paths:
            raise RuntimeError(
                "Multimodal mode requires detail images plus English-language asset images; if no English asset image is available, an SKU image is required."
            )
        return execution_mode, {}, image_paths

    edited_product_info = parse_json_editor(
        payload,
        "ai_product_info",
        APP_STATE.ai_result.get("product_info_from_images", {}),
    )
    if not isinstance(edited_product_info, dict):
        raise RuntimeError("The objective image record must be a JSON object.")
    product_info = objective_product_info_for_text(edited_product_info)
    if not isinstance(product_info, dict) or not product_info:
        raise RuntimeError("Complete the objective image record in Step 3 first.")
    APP_STATE.ai_result["product_info_from_images"] = product_info
    return execution_mode, product_info, []


def action_analyze_images(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = active_app_state()
    request_guard = current_action_request_guard()
    candidate = require_candidate()
    if APP_STATE.asset_manifest is None:
        action_inspect_assets(payload)
    if APP_STATE.asset_manifest is None:
        raise RuntimeError("Load and inspect an asset pack first.")
    vision_concurrency = parse_vision_concurrency(payload)
    thinking_mode, reasoning_strength = parse_vision_reasoning_settings(payload)
    selected_vision_model = parse_vision_model(payload)
    execution_mode = parse_ai_execution_mode(payload)
    persist_step_ai_preferences(
        step=3,
        model=selected_vision_model,
        thinking_mode=thinking_mode,
        reasoning_strength=reasoning_strength,
        execution_mode=execution_mode,
    )
    save_local_env_values(
        {
            "NVIDIA_VISION_CONCURRENCY": str(vision_concurrency),
            "NVIDIA_VISION_ENABLE_THINKING": "false" if thinking_mode == "disabled" else "true",
        }
    )
    with _PROMPT_CONFIG_LOCK:
        prompts = save_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml", payload.get("prompts", {}))
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    provider.prompt_overrides = prompts
    if isinstance(provider, NvidiaDualProvider):
        provider.cancellation_check = lambda: not is_action_request_current(
            request_guard
        )
        provider.status_callback = guarded_action_callback(
            request_guard,
            lambda status: update_ai_runtime_status(status, state),
        )
    APP_STATE.image_analysis_progress = {
        "current_file": "",
        "total": 0,
        "completed": 0,
        "success": 0,
        "failed": 0,
        "cached": 0,
        "rate_limit_waiting": False,
        "items": [],
    }
    reset_ai_reasoning("vision")
    if thinking_mode == "disabled":
        update_vision_reasoning(
            {
        "reasoning_delta": "Vision reasoning was disabled for this request; only final model output is shown.",
                "status": "disabled",
            }
        )
    parameters = inspect.signature(provider.analyze_assets).parameters
    callbacks: Dict[str, Any] = {}
    if "progress_callback" in parameters:
        callbacks["progress_callback"] = guarded_action_callback(
            request_guard,
            lambda status: update_image_analysis_progress(status, state),
        )
    if "reasoning_callback" in parameters:
        callbacks["reasoning_callback"] = guarded_action_callback(
            request_guard,
            lambda event: update_vision_reasoning(event, state),
        )
    if "thinking_mode" in parameters:
        callbacks["thinking_mode"] = thinking_mode
    elif "thinking_enabled" in parameters:
        callbacks["thinking_enabled"] = thinking_mode != "disabled"
    if "reasoning_strength" in parameters:
        callbacks["reasoning_strength"] = reasoning_strength
    if "selection_only" in parameters:
        callbacks["selection_only"] = (
            execution_mode == AI_EXECUTION_MODE_MULTIMODAL
        )
    analysis = provider.analyze_assets(candidate, APP_STATE.asset_manifest, **callbacks)
    ensure_action_request_current(request_guard)
    progress = analysis.get("analysis_progress", APP_STATE.image_analysis_progress)
    if isinstance(progress, dict):
        update_image_analysis_progress(progress)
    APP_STATE.ai_result = {
        "image_selection": {
            "main_image": analysis.get("main_image", ""),
            "detail_images": analysis.get("detail_images", []),
            "sku_images": APP_STATE.asset_manifest.sku_images,
            "unsafe_images": analysis.get("unsafe_images", []),
        },
        "product_info_from_images": (
            {}
            if execution_mode == AI_EXECUTION_MODE_MULTIMODAL
            else objective_product_info_for_text(
                analysis.get("product_info_from_images", {})
                if isinstance(analysis.get("product_info_from_images"), dict)
                else {}
            )
        ),
        "objective_image_records": analysis.get("objective_image_records", []),
        "image_selection_assessments": analysis.get("image_selection_assessments", []),
        "per_image_results": analysis.get("per_image_results", []),
        "analysis_progress": APP_STATE.image_analysis_progress,
        "warnings": [],
    }
    APP_STATE.confirmed_image_selection = {}
    APP_STATE.draft = None
    APP_STATE.draft_path = ""
    APP_STATE.report_path = ""
    APP_STATE.last_ai_model = ", ".join(getattr(provider, "last_used_models", {}).values())
    report_path = task_output_root() / "reports" / f"image_analysis_{safe_filename(str(candidate.sku_code))}_{timestamp()}.json"
    write_json(
        report_path,
        {
            "sku_code": str(candidate.sku_code),
            "model": APP_STATE.last_ai_model,
            "progress": APP_STATE.image_analysis_progress,
            "per_image_results": APP_STATE.ai_result["per_image_results"],
            "image_selection": APP_STATE.ai_result["image_selection"],
            "product_info_from_images": APP_STATE.ai_result["product_info_from_images"],
            "image_selection_assessments": APP_STATE.ai_result["image_selection_assessments"],
        },
    )
    failed_results = [
        item
        for item in APP_STATE.ai_result["per_image_results"]
        if isinstance(item, dict) and item.get("status") == "analysis_failed"
    ]
    if failed_results:
        set_ai_reasoning_status("vision", "failed")
        first_assessment = failed_results[0].get("selection_assessment", {})
        first_reasons = (
            first_assessment.get("selection_reasons", [])
            if isinstance(first_assessment, dict)
            else []
        )
        first_reason = next(
            (str(reason).strip() for reason in first_reasons if str(reason).strip()),
            "The vision model returned no valid image-analysis result.",
        )
        raise RuntimeError(
            f"Step 3 image analysis failed: {APP_STATE.image_analysis_progress.get('success', 0)} succeeded and "
            f"{len(failed_results)} failed. Failed images were retried twice under the configured concurrency. "
            f"The workflow stopped before later steps. First error: {first_reason[:500]}; "
            f"diagnostic report: {report_path}"
        )
    set_ai_reasoning_status("vision", "completed")
    return {
        "message": (
        f"Per-image analysis completed: {APP_STATE.image_analysis_progress.get('success', 0)} succeeded, "
        f"{APP_STATE.image_analysis_progress.get('failed', 0)} failed, and "
        f"{APP_STATE.image_analysis_progress.get('cached', 0)} used cached results; "
        f"mode: {'multimodal image selection' if execution_mode == AI_EXECUTION_MODE_MULTIMODAL else 'objective record + image selection'}; "
        f"report: {report_path}"
        ),
        "result": current_result(),
        "workbench": workbench_payload(),
        "image_analysis_progress": APP_STATE.image_analysis_progress,
    }


def action_generate_keywords(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = active_app_state()
    request_guard = current_action_request_guard()
    candidate = require_candidate()
    if APP_STATE.asset_manifest is None:
        raise RuntimeError("Load an asset pack and complete per-image analysis first.")
    execution_mode, product_info, image_paths = ai_step_product_inputs(payload)
    provider = _linear_ai_provider(payload)
    reset_ai_reasoning("keywords")
    thinking_mode, reasoning_strength = parse_keyword_reasoning_settings(payload)
    text_model = parse_step_text_model(payload, "keyword_text_model")
    persist_step_ai_preferences(
        step=5,
        model=text_model,
        thinking_mode=thinking_mode,
        reasoning_strength=reasoning_strength,
        execution_mode=execution_mode,
    )
    if thinking_mode == "disabled":
        update_keyword_reasoning(
            {
        "reasoning_delta": "Search-term reasoning was disabled for this request; only the final search terms were generated.",
                "status": "disabled",
            }
        )
    parameters = inspect.signature(provider.generate_search_keywords).parameters
    options: Dict[str, Any] = {}
    if "reasoning_callback" in parameters:
        options["reasoning_callback"] = guarded_action_callback(
            request_guard,
            lambda event: update_keyword_reasoning(event, state),
        )
    if "thinking_mode" in parameters:
        options["thinking_mode"] = thinking_mode
    elif "thinking_enabled" in parameters:
        options["thinking_enabled"] = thinking_mode != "disabled"
    if "reasoning_strength" in parameters:
        options["reasoning_strength"] = reasoning_strength
    if "text_model" in parameters:
        options["text_model"] = text_model
    if "image_paths" in parameters:
        options["image_paths"] = image_paths
    if "multimodal_mode" in parameters:
        options["multimodal_mode"] = (
            execution_mode == AI_EXECUTION_MODE_MULTIMODAL
        )
    try:
        result = provider.generate_search_keywords(candidate, APP_STATE.asset_manifest, product_info, **options)
    except Exception:
        if is_action_request_current(request_guard):
            set_ai_reasoning_status("keywords", "failed")
        raise
    ensure_action_request_current(request_guard)
    set_ai_reasoning_status("keywords", "completed")
    APP_STATE.ai_result["search_keywords"] = result.get("search_keywords", [])
    return {"message": "Competitor search terms generated", "result": current_result(), "workbench": workbench_payload()}


def action_analyze_title(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = active_app_state()
    request_guard = current_action_request_guard()
    candidate = require_candidate()
    execution_mode, product_info, image_paths = ai_step_product_inputs(payload)
    competitors = parse_manual_competitors(str(payload.get("manual_competitors", "")))
    APP_STATE.competitors = {"sources": competitors, "warnings": []}
    workflow_source = str(payload.get("workflow_source") or "manual_step").strip().lower()
    valid_competitor_titles = valid_manual_competitor_titles(competitors)
    if workflow_source == "one_click" and not valid_competitor_titles:
        reset_ai_reasoning("title")
        update_title_reasoning(
            {
            "reasoning_delta": "No real competitor title was found. The full workflow stopped until competitor titles are supplied in Step 6.",
                "status": "failed",
            }
        )
        raise RuntimeError(
            "Step 6 requires at least one real competitor title; the full workflow will not invent one. "
            "Add competitor titles under Competitor Inputs in Step 6, then run the full workflow again to retry this step."
        )
    if competitors:
        save_manual_competitors(task_output_root() / "competitor_sources", str(candidate.sku_code), competitors)
    provider = _linear_ai_provider(payload)
    reset_ai_reasoning("title")
    thinking_mode, reasoning_strength = parse_title_reasoning_settings(payload)
    text_model = parse_step_text_model(payload, "title_text_model")
    persist_step_ai_preferences(
        step=6,
        model=text_model,
        thinking_mode=thinking_mode,
        reasoning_strength=reasoning_strength,
        execution_mode=execution_mode,
    )
    if thinking_mode == "disabled":
        update_title_reasoning(
            {
        "reasoning_delta": "Title reasoning was disabled for this request; only the final title and analysis were generated.",
                "status": "disabled",
            }
        )
    parameters = inspect.signature(provider.analyze_competitor_titles).parameters
    options: Dict[str, Any] = {}
    if "reasoning_callback" in parameters:
        options["reasoning_callback"] = guarded_action_callback(
            request_guard,
            lambda event: update_title_reasoning(event, state),
        )
    if "thinking_enabled" in parameters:
        options["thinking_enabled"] = thinking_mode != "disabled"
    if "thinking_mode" in parameters:
        options["thinking_mode"] = thinking_mode
    if "reasoning_strength" in parameters:
        options["reasoning_strength"] = reasoning_strength
    if "text_model" in parameters:
        options["text_model"] = text_model
    if "image_paths" in parameters:
        options["image_paths"] = image_paths
    if "multimodal_mode" in parameters:
        options["multimodal_mode"] = (
            execution_mode == AI_EXECUTION_MODE_MULTIMODAL
        )
    result = provider.analyze_competitor_titles(candidate, product_info, competitors, **options)
    ensure_action_request_current(request_guard)
    set_ai_reasoning_status("title", "completed")
    with APP_STATE.ai_result_lock:
        APP_STATE.ai_result.update(
            {
                "title": result.get("final_title", ""),
                "competitor_analysis": result.get("competitor_analysis", []),
                "removed_keywords": result.get("removed_keywords", []),
                "title_keywords": _reused_keywords(result.get("competitor_analysis", [])),
            }
        )
        merge_ai_warnings(result.get("warnings", []))
    return {"message": "Competitor analysis and title generation completed", "result": current_result(), "workbench": workbench_payload()}


def valid_manual_competitor_titles(competitors: list[Dict[str, object]]) -> list[str]:
    return [
        str(item.get("source_title") or "").strip()
        for item in competitors
        if str(item.get("source_title") or "").strip()
        and not URL_RE.fullmatch(str(item.get("source_title") or "").strip())
    ]


def action_validate_competitors(payload: Dict[str, Any]) -> Dict[str, Any]:
    competitors = parse_manual_competitors(str(payload.get("manual_competitors", "")))
    valid_titles = valid_manual_competitor_titles(competitors)
    if not valid_titles:
        raise RuntimeError(
            "Step 6 requires at least one real competitor title. Add titles under Competitor Inputs in Step 6, "
            "then confirm before Steps 6 and 7 run in parallel."
        )
    return {
        "message": f"Step 6 competitor-title precheck passed: {len(valid_titles)} titles recognized",
        "competitor_title_count": len(valid_titles),
    }


def parse_description_reasoning_settings(payload: Dict[str, Any]) -> tuple[str, str]:
    mode = str(
        payload.get("description_thinking_mode")
        or os.environ.get("STEP7_THINKING_MODE")
        or os.environ.get("STEP7_TEXT_THINKING_MODE", "enabled")
        or "enabled"
    ).strip().lower()
    if mode in {"default", "model_default"}:
        mode = "official_default"
    if mode not in {"official_default", "enabled", "disabled"}:
        raise RuntimeError("Description reasoning mode must be Official Default, Enabled, or Disabled.")
    strength = str(
        payload.get("description_reasoning_strength")
        or os.environ.get("STEP7_REASONING_STRENGTH")
        or os.environ.get("STEP7_TEXT_REASONING_STRENGTH", "maximum")
        or "maximum"
    ).strip().lower()
    if strength in {"default", "model_default"}:
        strength = "official_default"
    if strength == "highest":
        strength = "maximum"
    if strength not in {"official_default", "low", "medium", "high", "maximum"}:
        raise RuntimeError("Description reasoning effort must be Official Default, Low, Medium, High, or Maximum.")
    return mode, strength


def action_generate_description(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = active_app_state()
    request_guard = current_action_request_guard()
    candidate = require_candidate()
    execution_mode, product_info, image_paths = ai_step_product_inputs(payload)
    provider = _linear_ai_provider(payload)
    reset_ai_reasoning("description")
    thinking_mode, reasoning_strength = parse_description_reasoning_settings(payload)
    text_model = parse_step_text_model(payload, "description_text_model")
    persist_step_ai_preferences(
        step=7,
        model=text_model,
        thinking_mode=thinking_mode,
        reasoning_strength=reasoning_strength,
        execution_mode=execution_mode,
    )
    if thinking_mode == "disabled":
        update_description_reasoning(
            {
        "reasoning_delta": "Description reasoning was disabled for this request; only the final result was generated.",
                "status": "disabled",
            }
        )
    parameters = inspect.signature(provider.generate_description_placeholders).parameters
    options: Dict[str, Any] = {}
    if "reasoning_callback" in parameters:
        options["reasoning_callback"] = guarded_action_callback(
            request_guard,
            lambda event: update_description_reasoning(event, state),
        )
    if "thinking_mode" in parameters:
        options["thinking_mode"] = thinking_mode
    elif "thinking_enabled" in parameters:
        options["thinking_enabled"] = thinking_mode != "disabled"
    if "reasoning_strength" in parameters:
        options["reasoning_strength"] = reasoning_strength
    if "text_model" in parameters:
        options["text_model"] = text_model
    if "image_paths" in parameters:
        options["image_paths"] = image_paths
    if "multimodal_mode" in parameters:
        options["multimodal_mode"] = (
            execution_mode == AI_EXECUTION_MODE_MULTIMODAL
        )
    result = provider.generate_description_placeholders(candidate, product_info, **options)
    ensure_action_request_current(request_guard)
    with APP_STATE.ai_result_lock:
        APP_STATE.ai_result["description_placeholders"] = result.get("description_placeholders", {})
        APP_STATE.ai_result["seo_keywords"] = result.get("seo_keywords", [])
        APP_STATE.ai_result.pop("final_description_override", None)
        merge_ai_warnings(result.get("warnings", []))
    try:
        store = APP_STATE.config.store(APP_STATE.selected_store_name)
        description_audit = build_description_with_seo(
            APP_STATE.config.description_template(store.template_key),
            APP_STATE.ai_result.get("description_placeholders", {}),
            APP_STATE.ai_result.get("seo_keywords", []),
            keyword_range=current_seo_keyword_range(),
            enforce_character_limit=False,
        )
        final_description = str(description_audit["final_description"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        set_ai_reasoning_status("description", "failed")
        workbench = workbench_payload()
        build_error = (
                "The AI returned content, but the complete final description could not be assembled. "
                f"If automatic retries also fail, inspect Step 7 manually. Details: {exc}"
        )
        workbench["final_description"] = ""
        workbench["description_audit"] = {}
        workbench["description_build_error"] = build_error
        return {
            "ok": False,
            "message": build_error,
            "result": current_result(),
            "workbench": workbench,
        }
    workbench = workbench_payload()
    workbench["final_description"] = final_description
    workbench["description_audit"] = description_audit
    if not final_description:
        set_ai_reasoning_status("description", "failed")
        message = "The AI returned content, but the final description is empty. Retry Step 7 or edit it manually."
        workbench["description_build_error"] = message
        return {
            "ok": False,
            "message": message,
            "result": current_result(),
            "workbench": workbench,
        }
    if len(final_description) > 3000:
        set_ai_reasoning_status("description", "failed")
        message = (
            f"Step 7 generated a {len(final_description)}-character description, "
            f"which exceeds the 3,000-character limit by {len(final_description) - 3000}. "
            "The full workflow regenerates it using the Step 0 settings. If all retries remain too long, "
            "edit the current text manually before continuing."
        )
        workbench["description_build_error"] = message
        return {
            "ok": False,
            "message": message,
            "result": current_result(),
            "workbench": workbench,
        }
    with APP_STATE.ai_result_lock:
        APP_STATE.ai_result["final_description_override"] = final_description
    set_ai_reasoning_status("description", "completed")
    workbench["description_build_error"] = ""
    return {
        "message": f"Product description generated ({len(final_description)} characters)",
        "result": current_result(),
        "workbench": workbench,
    }


def _linear_ai_provider(payload: Dict[str, Any]) -> Any:
    state = active_app_state()
    request_guard = current_action_request_guard()
    with _PROMPT_CONFIG_LOCK:
        prompts = save_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml", payload.get("prompts", {}))
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    provider.prompt_overrides = prompts
    if isinstance(provider, NvidiaDualProvider):
        provider.cancellation_check = lambda: not is_action_request_current(
            request_guard
        )
        provider.status_callback = guarded_action_callback(
            request_guard,
            lambda status: update_ai_runtime_status(status, state),
        )
        provider.description_reasoning_callback = guarded_action_callback(
            request_guard,
            lambda event: update_description_reasoning(event, state),
        )
    return provider


def merge_ai_warnings(warnings: object) -> None:
    if not isinstance(warnings, list):
        return
    for item in warnings:
        text = str(item).strip()
        if text and text not in APP_STATE.ai_warnings:
            APP_STATE.ai_warnings.append(text)


def _reused_keywords(analysis: object) -> list[str]:
    result: list[str] = []
    if not isinstance(analysis, list):
        return result
    for item in analysis:
        if not isinstance(item, dict):
            continue
        values = item.get("reused_keywords", [])
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
    return result


def action_analyze_ai(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = active_app_state()
    candidate = require_candidate()
    if APP_STATE.asset_manifest is None:
        action_inspect_assets(payload)
    with _PROMPT_CONFIG_LOCK:
        prompts = save_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml", payload.get("prompts", {}))
    manual_competitors = parse_manual_competitors(str(payload.get("manual_competitors", "")))
    if manual_competitors:
        APP_STATE.competitors = {"sources": manual_competitors, "warnings": []}
        save_manual_competitors(
            task_output_root() / "competitor_sources",
            str(candidate.sku_code),
            manual_competitors,
        )
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    provider.prompt_overrides = prompts
    if isinstance(provider, NvidiaDualProvider):
        provider.status_callback = lambda status: update_ai_runtime_status(status, state)
    APP_STATE.ai_warnings = []
    try:
        APP_STATE.ai_result = provider.generate_listing(candidate, APP_STATE.asset_manifest, APP_STATE.competitors.get("sources", []))
        APP_STATE.last_ai_model = ", ".join(getattr(provider, "last_used_models", {}).values()) or getattr(provider, "last_used_model", "")
        message = "AI analysis completed. Review the assets, title, and description before building the draft."
    except NvidiaRateLimitExhausted as exc:
        report = dict(exc.report)
        report["fallback_used"] = "local_rules"
        report["blocked_listing_flow"] = False
        APP_STATE.nvidia_rate_limit_reports.append(report)
        APP_STATE.ai_result = OfflineAIProvider().generate_listing(candidate, APP_STATE.asset_manifest, APP_STATE.competitors.get("sources", []))
        APP_STATE.ai_warnings = ["The AI API remained rate-limited after retries. Local rules were used so the listing workflow can continue."]
        APP_STATE.ai_runtime_status.update({"rate_limited": True, "message": "AI API rate limit persisted; using local-rule results"})
        APP_STATE.listing_runtime_status = {"state": "ready", "message": "AI fallback completed; the listing workflow can continue"}
        message = "The AI API is rate-limited. A conservative local draft is shown; edit and confirm it manually."
    except Exception as exc:  # noqa: BLE001
        APP_STATE.ai_result = OfflineAIProvider().generate_listing(candidate, APP_STATE.asset_manifest, APP_STATE.competitors.get("sources", []))
        APP_STATE.ai_warnings = [f"AI request failed; a conservative local draft was used: {mask_known_secrets(exc)}"]
        message = "The AI request failed. A conservative local draft is shown; edit and confirm it manually."
    return {"message": message, "result": current_result(), "workbench": workbench_payload()}


def action_confirm_ai_results(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = require_candidate()
    if APP_STATE.asset_manifest is None or not APP_STATE.ai_result:
        raise RuntimeError("Inspect an asset pack and complete AI analysis first.")
    result = dict(APP_STATE.ai_result)
    product_info = parse_json_editor(payload, "ai_product_info", {})
    keywords = parse_json_editor(payload, "ai_keywords", [])
    title_analysis = parse_json_editor(payload, "ai_title_analysis", {})
    placeholders = parse_json_editor(payload, "ai_description_placeholders", {})
    seo_keywords = parse_json_editor(payload, "ai_seo_keywords", [])
    if not isinstance(product_info, dict) or not isinstance(keywords, list) or not isinstance(title_analysis, dict) or not isinstance(placeholders, dict) or not isinstance(seo_keywords, list):
        raise RuntimeError("The AI editor contains invalid JSON.")
    if not APP_STATE.confirmed_image_selection:
        action_confirm_image_selection(payload)
    main_image = str(APP_STATE.confirmed_image_selection["main_image"])
    detail_images = list(APP_STATE.confirmed_image_selection["detail_images"])
    result["title"] = str(payload.get("ai_title", "")).strip()
    result["product_info_from_images"] = objective_product_info_for_text(product_info)
    result["search_keywords"] = keywords
    result["competitor_analysis"] = title_analysis.get("competitor_analysis", [])
    result["removed_keywords"] = title_analysis.get("removed_keywords", [])
    result["warnings"] = list(title_analysis.get("warnings", [])) + APP_STATE.ai_warnings
    result["description_placeholders"] = placeholders
    result["seo_keywords"] = seo_keywords
    edited_description = str(payload.get("ai_final_description", "")).strip()
    if not edited_description:
        raise RuntimeError("The final product description cannot be empty.")
    result["final_description_override"] = edited_description
    prior_images = result.get("image_selection", {}) if isinstance(result.get("image_selection"), dict) else {}
    result["image_selection"] = {
        "main_image": main_image,
        "detail_images": detail_images,
        "sku_images": prior_images.get("sku_images", APP_STATE.asset_manifest.sku_images),
        "unsafe_images": prior_images.get("unsafe_images", APP_STATE.asset_manifest.unsafe_images),
    }
    store = APP_STATE.config.store(str(payload.get("store", "")))
    APP_STATE.draft = build_listing_draft(
        candidate=candidate,
        store_name=store.name,
        template_key=store.template_key,
        description_template=APP_STATE.config.description_template(store.template_key),
        asset_manifest=APP_STATE.asset_manifest,
        competitors=APP_STATE.competitors.get("sources", []),
        ai_result=result,
        keyword_range=current_seo_keyword_range(),
    )
    description_audit = APP_STATE.draft.get("listing", {}).get("description_audit", {})
    final_description = str(APP_STATE.draft.get("listing", {}).get("description", ""))
    result["final_description_override"] = final_description
    APP_STATE.ai_result = result
    sku = safe_filename(str(candidate.sku_code))
    draft_path = task_output_root() / "listings" / f"{sku}_listing_draft.json"
    report_path = task_output_root() / "reports" / f"{sku}_report.md"
    write_json(draft_path, APP_STATE.draft)
    write_run_report(report_path, APP_STATE.draft)
    APP_STATE.draft_path = str(draft_path)
    APP_STATE.report_path = str(report_path)
    message = (
            "The listing draft was built from the manually edited content without rewriting it; "
            f"the current description is {description_audit.get('final_description_length', len(final_description))} characters."
    )
    return {"message": message, "result": current_result(), "workbench": workbench_payload()}


def parse_json_editor(payload: Dict[str, Any], key: str, fallback: Any) -> Any:
    raw = str(payload.get(key, "")).strip()
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{key} is not valid JSON: {exc.msg}") from exc


def asset_candidates() -> list[Dict[str, Any]]:
    manifest = APP_STATE.asset_manifest
    if manifest is None:
        return []
    image_selection = (
        APP_STATE.ai_result.get("image_selection", {})
        if isinstance(APP_STATE.ai_result.get("image_selection"), dict)
        else {}
    )
    promoted_main = str(image_selection.get("main_image", "") or "")
    items: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for kind, paths in [
        ("main", manifest.main_images),
        ("detail", manifest.detail_images),
        ("english", manifest.english_images),
        ("parameter", manifest.parameter_images),
        ("sku", manifest.sku_images),
    ]:
        for path in paths:
            value = str(path)
            if value in seen:
                continue
            seen.add(value)
            effective_kind = "main" if kind == "detail" and value == promoted_main else kind
            try:
                stat = Path(value).stat()
                cache_identity = f"{value}|{stat.st_size}|{stat.st_mtime_ns}"
            except OSError:
                cache_identity = value
            items.append(
                {
                    "index": len(items),
                    "kind": effective_kind,
                    "path": value,
                    "name": Path(value).name,
                    "cache_key": hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()[:16],
                }
            )
    return items


def _assembled_description_length() -> int:
    """Best-effort length of the currently assembled description (template + hashtags)."""
    try:
        store = APP_STATE.config.store(APP_STATE.selected_store_name)
        template = APP_STATE.config.description_template(store.template_key)
        placeholders = APP_STATE.ai_result.get("description_placeholders", {})
        seo_keywords = APP_STATE.ai_result.get("seo_keywords", [])
        if not isinstance(placeholders, dict):
            return 0
        body = template
        for key, value in placeholders.items():
            body = body.replace("{{" + str(key) + "}}", str(value))
        body = "\n".join(line.rstrip() for line in body.splitlines()).strip()
        hashtags: list[str] = []
        if isinstance(seo_keywords, list):
            for item in seo_keywords:
                if not isinstance(item, dict):
                    continue
                keyword = str(item.get("keyword", "")).strip()
                hashtag = "#" + "".join(
                    part[:1].upper() + part[1:] for part in re.findall(r"[A-Za-z0-9]+", keyword)
                )
                if hashtag != "#" and hashtag.lower() not in {value.lower() for value in hashtags}:
                    hashtags.append(hashtag)
        final = f"{body}\n\n{' '.join(hashtags)}".strip() if hashtags else body
        return len(final)
    except Exception:  # noqa: BLE001
        return 0


def current_seo_keyword_range() -> tuple:
    """Return the SEO-keyword count range required by the current editable prompt."""
    prompts = load_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml")
    return parse_seo_keyword_count(prompts.get("description_generation", ""))


def workbench_payload() -> Dict[str, Any]:
    listing = APP_STATE.draft.get("listing", {}) if APP_STATE.draft else {}
    final_description = listing.get("description", "")
    description_audit = listing.get("description_audit", {}) if isinstance(listing, dict) else {}
    description_build_error = ""
    if not final_description and APP_STATE.ai_result and APP_STATE.selected_store_name:
        try:
            store = APP_STATE.config.store(APP_STATE.selected_store_name)
            description_audit = build_description_with_seo(
                APP_STATE.config.description_template(store.template_key),
                APP_STATE.ai_result.get("description_placeholders", {}),
                APP_STATE.ai_result.get("seo_keywords", []),
                keyword_range=current_seo_keyword_range(),
                enforce_character_limit=False,
            )
            final_description = description_audit["final_description"]
            if len(final_description) > 3000:
                description_build_error = (
            f"The complete description is shown and contains {len(final_description)} characters, "
            f"exceeding the 3,000-character limit by {len(final_description) - 3000}. "
            "Edit it in the text box below, then run Step 8 after it is 3,000 characters or fewer."
                )
        except (KeyError, TypeError, ValueError) as exc:
            final_description = ""
            description_audit = {}
            description_build_error = (
            "Unable to assemble the final product description. Check the body placeholders and SEO-keyword format. "
            f"Details: {exc}"
            )
    provider = APP_STATE.config.ai.provider or "offline"
    return {
        "prompts": load_prompt_config(PROJECT_ROOT / "config" / "prompts.yaml"),
        "asset_candidates": asset_candidates(),
        "ai_result": APP_STATE.ai_result,
        "warnings": APP_STATE.ai_warnings + list(APP_STATE.ai_result.get("warnings", [])),
        "final_description": final_description,
        "description_audit": description_audit,
        "description_build_error": description_build_error,
        "key_status": f"Current mode: {provider}. Keys are stored only in the local .env file and are never displayed in the interface.",
        "ai_status": APP_STATE.ai_runtime_status,
        "listing_status": APP_STATE.listing_runtime_status,
        "nvidia_api_rate_limit": APP_STATE.nvidia_rate_limit_reports,
        "confirmed_image_selection": APP_STATE.confirmed_image_selection,
        "image_selection_summary": APP_STATE.confirmed_image_selection,
        "asset_download": {},
        "image_analysis_progress": APP_STATE.image_analysis_progress,
        "ai_reasoning": ai_reasoning_snapshot(),
    }


def update_ai_runtime_status(
    status: Dict[str, object],
    state: Optional[WebAppState] = None,
) -> None:
    target = state or active_app_state()
    target.ai_runtime_status = dict(status)


def update_image_analysis_progress(
    status: Dict[str, object],
    state: Optional[WebAppState] = None,
) -> None:
    target = state or active_app_state()
    target.image_analysis_progress = dict(status)


def new_ai_reasoning_state() -> Dict[str, Any]:
    return {
        "vision": {"current_file": "", "model": "", "text": "", "status": "idle", "items": []},
        "keywords": {"model": "", "text": "", "status": "idle"},
        "title": {"model": "", "text": "", "status": "idle"},
        "description": {"model": "", "text": "", "status": "idle"},
    }


def _ensure_ai_reasoning_state(state: Optional[WebAppState] = None) -> WebAppState:
    """Fill missing reasoning-state keys while preserving existing reasoning text."""
    target = state or active_app_state()
    if not isinstance(target.ai_reasoning, dict):
        target.ai_reasoning = new_ai_reasoning_state()
        return target
    defaults = new_ai_reasoning_state()
    for kind, default_state in defaults.items():
        reasoning_state = target.ai_reasoning.get(kind)
        if not isinstance(reasoning_state, dict):
            target.ai_reasoning[kind] = default_state
            continue
        for field, default_value in default_state.items():
            reasoning_state.setdefault(field, default_value)
    return target


def reset_ai_reasoning(kind: str, state: Optional[WebAppState] = None) -> None:
    target = state or active_app_state()
    with target.ai_reasoning_lock:
        _ensure_ai_reasoning_state(target)
        target.ai_reasoning[kind] = (
            {"current_file": "", "model": "", "text": "", "status": "running", "items": []}
            if kind == "vision"
            else {"model": "", "text": "", "status": "running"}
        )


def set_ai_reasoning_status(
    kind: str,
    status: str,
    state: Optional[WebAppState] = None,
) -> None:
    target = state or active_app_state()
    with target.ai_reasoning_lock:
        _ensure_ai_reasoning_state(target)
        target.ai_reasoning[kind]["status"] = status


def update_vision_reasoning(
    event: Dict[str, object],
    app_state: Optional[WebAppState] = None,
) -> None:
    target = app_state or active_app_state()
    with target.ai_reasoning_lock:
        _ensure_ai_reasoning_state(target)
        state = target.ai_reasoning["vision"]
        file_name = str(event.get("file_name", ""))
        model = str(event.get("model", ""))
        state["current_file"] = file_name
        if model:
            state["model"] = model
        state["status"] = str(event.get("status", "streaming"))
        items = state.setdefault("items", [])
        item = next((entry for entry in items if entry.get("file_name") == file_name), None)
        if item is None:
            item = {"file_name": file_name, "model": model, "text": "", "status": "streaming", "display_mode": ""}
            items.append(item)
        if model:
            item["model"] = model
        if bool(event.get("reset_text")):
            item["text"] = ""
            item["display_mode"] = ""
        reasoning_delta = str(event.get("reasoning_delta", ""))
        content_delta = str(event.get("content_delta", ""))
        if reasoning_delta:
            if item.get("display_mode") != "reasoning":
                item["text"] = ""
            item["display_mode"] = "reasoning"
            item["text"] = (str(item.get("text", "")) + reasoning_delta)[-200000:]
        elif content_delta and item.get("display_mode") != "reasoning":
            item["display_mode"] = "model_output"
            item["text"] = (str(item.get("text", "")) + content_delta)[-200000:]
        item["status"] = str(event.get("status", "streaming"))
        state["text"] = item["text"]


def _update_text_reasoning(
    kind: str,
    event: Dict[str, object],
    app_state: Optional[WebAppState] = None,
) -> None:
    """Accumulate streaming reasoning for text tasks (title / description).

    Records the model name and falls back to the live model output when the
    model does not return a separate reasoning stream.
    """
    target = app_state or active_app_state()
    with target.ai_reasoning_lock:
        _ensure_ai_reasoning_state(target)
        state = target.ai_reasoning[kind]
        model = str(event.get("model", ""))
        if model:
            state["model"] = model
        if bool(event.get("reset_text")):
            state["text"] = ""
            state["display_mode"] = ""
        reasoning_delta = str(event.get("reasoning_delta", ""))
        content_delta = str(event.get("content_delta", ""))
        if reasoning_delta:
            if state.get("display_mode") != "reasoning":
                state["text"] = ""
            state["display_mode"] = "reasoning"
            state["text"] = (str(state.get("text", "")) + reasoning_delta)[-200000:]
        elif content_delta and state.get("display_mode") != "reasoning":
            state["display_mode"] = "model_output"
            state["text"] = (str(state.get("text", "")) + content_delta)[-200000:]
        state["status"] = str(event.get("status", "streaming"))


def update_title_reasoning(
    event: Dict[str, object],
    state: Optional[WebAppState] = None,
) -> None:
    _update_text_reasoning("title", event, state)


def update_keyword_reasoning(
    event: Dict[str, object],
    state: Optional[WebAppState] = None,
) -> None:
    _update_text_reasoning("keywords", event, state)


def update_description_reasoning(
    event: Dict[str, object],
    state: Optional[WebAppState] = None,
) -> None:
    _update_text_reasoning("description", event, state)


def ai_reasoning_snapshot(state: Optional[WebAppState] = None) -> Dict[str, Any]:
    target = state or active_app_state()
    with target.ai_reasoning_lock:
        _ensure_ai_reasoning_state(target)
        return copy.deepcopy(target.ai_reasoning)


def mask_known_secrets(value: object) -> str:
    text = str(value)
    for key_name in [
        "OPENAI_API_KEY",
        "AGNES_API_KEY",
        "AGNES_VISION_API_KEY",
        "NVIDIA_VISION_API_KEY",
        "NVIDIA_MINIMAX_VISION_API_KEY",
        "NVIDIA_TEXT_API_KEY",
        "ZHIPU_API_KEY",
        "SERVERCHAN_SENDKEY",
        "WXPUSHER_SPT",
    ]:
        text = mask_secret(text, os.environ.get(key_name, ""))
    return text[:500]


def action_test_zhipu_ai() -> Dict[str, Any]:
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    if not isinstance(provider, ZhipuProvider):
        raise RuntimeError("The current AI provider is not zhipu. Check config/ai.yaml.")
    result = provider.check_models()
    stamp = timestamp()
    report_path = task_output_root() / "reports" / f"ai_model_check_{stamp}.md"
    json_path = task_output_root() / "reports" / f"ai_model_check_{stamp}.json"
    payload = {
        "checked_at": stamp,
        "api_key": "***masked***",
        "default_model": APP_STATE.config.ai.model or "glm-5.2",
        "fallback_models": APP_STATE.config.ai.fallback_models,
        **result,
    }
    write_json(json_path, payload)
    lines = [
            "# Zhipu AI Model Connectivity Test",
        "",
        "- API Key: ***masked***",
            f"- Final available model: {result.get('selected_model') or 'None'}",
        "",
            "| Model | Result | Error |",
        "| --- | --- | --- |",
    ]
    for item in result.get("results", []):
        if not isinstance(item, dict):
            continue
        error = str(item.get("error", ""))[:220].replace("|", "/")
        lines.append(f"| {item.get('model', '')} | {'Available' if item.get('ok') else 'Unavailable'} | {error} |")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    APP_STATE.ai_model_check_path = str(report_path)
    APP_STATE.last_ai_model = str(result.get("selected_model") or "")
    return {
        "message": f"Zhipu AI test completed. Final available model: {APP_STATE.last_ai_model or 'None'}; report: {report_path}",
        "result": {
            **current_result(),
            "report_path": str(report_path),
            "ai_model_check_json": str(json_path),
            "last_ai_model": APP_STATE.last_ai_model,
        },
    }


def action_save_ai_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = "openai"
    execution_mode = parse_ai_execution_mode(payload)
    selected_vision_model = parse_vision_model(payload)
    vision_concurrency = parse_vision_concurrency(payload)
    full_workflow_auto_retry_count = parse_full_workflow_auto_retry_count(payload)
    vision_thinking_mode, vision_reasoning_strength = parse_vision_reasoning_settings(payload)
    step5_text_model = parse_step_text_model(payload, "keyword_text_model")
    step6_text_model = parse_step_text_model(payload, "title_text_model")
    step7_text_model = parse_step_text_model(payload, "description_text_model")
    step5_thinking_mode, step5_reasoning_strength = parse_keyword_reasoning_settings(payload)
    step6_thinking_mode, step6_reasoning_strength = parse_title_reasoning_settings(payload)
    step7_thinking_mode, step7_reasoning_strength = parse_description_reasoning_settings(payload)
    values = {
        "AI_PROVIDER": mode,
        "AI_EXECUTION_MODE": execution_mode,
        "OPENAI_BASE_URL": OPENAI_DEFAULT_BASE_URL,
        "OPENAI_MODEL": OPENAI_DEFAULT_MODEL,
        "OPENAI_MAX_OUTPUT_TOKENS": "32768",
        "OPENAI_TIMEOUT_SECONDS": "900",
        "NVIDIA_VISION_MODEL": selected_vision_model,
        "STEP3_AI_MODEL": selected_vision_model,
        "STEP3_THINKING_MODE": vision_thinking_mode,
        "STEP3_REASONING_STRENGTH": vision_reasoning_strength,
        "AGNES_VISION_MODEL": AGNES_VISION_DEFAULT_MODEL,
        "AGNES_VISION_BASE_URL": AGNES_DEFAULT_BASE_URL,
        "AGNES_VISION_MAX_TOKENS": "16384",
        "AGNES_VISION_TIMEOUT_SECONDS": "90",
        "AGNES_TEXT_MODEL": AGNES_TEXT_DEFAULT_MODEL,
        "AGNES_TEXT_BASE_URL": AGNES_DEFAULT_BASE_URL,
        "AGNES_TEXT_MAX_TOKENS": "65536",
        "AGNES_TEXT_TIMEOUT_SECONDS": "900",
        "NVIDIA_VISION_BASE_URL": "https://integrate.api.nvidia.com/v1",
        "NVIDIA_VISION_TIMEOUT_SECONDS": "90",
        "NVIDIA_MINIMAX_VISION_MODEL": NVIDIA_MINIMAX_VISION_MODEL,
        "NVIDIA_MINIMAX_VISION_BASE_URL": "https://integrate.api.nvidia.com/v1",
        "NVIDIA_MINIMAX_VISION_MAX_TOKENS": "8192",
        "NVIDIA_MINIMAX_VISION_TIMEOUT_SECONDS": "90",
        "NVIDIA_TEXT_MODEL": "z-ai/glm-5.2",
        "NVIDIA_TEXT_BASE_URL": "https://integrate.api.nvidia.com/v1",
        "NVIDIA_TEXT_ENABLE_THINKING": "true",
        "NVIDIA_TEXT_CLEAR_THINKING": "false",
        "NVIDIA_TEXT_MAX_TOKENS": "16384",
        "STEP5_TEXT_MODEL": step5_text_model,
        "STEP6_TEXT_MODEL": step6_text_model,
        "STEP5_TEXT_THINKING_MODE": step5_thinking_mode,
        "STEP5_TEXT_REASONING_STRENGTH": step5_reasoning_strength,
        "STEP6_TEXT_THINKING_MODE": step6_thinking_mode,
        "STEP6_TEXT_REASONING_STRENGTH": step6_reasoning_strength,
        "STEP7_TEXT_MODEL": step7_text_model,
        "STEP7_TEXT_THINKING_MODE": step7_thinking_mode,
        "STEP7_TEXT_REASONING_STRENGTH": step7_reasoning_strength,
        "STEP5_AI_MODEL": step5_text_model,
        "STEP5_THINKING_MODE": step5_thinking_mode,
        "STEP5_REASONING_STRENGTH": step5_reasoning_strength,
        "STEP6_AI_MODEL": step6_text_model,
        "STEP6_THINKING_MODE": step6_thinking_mode,
        "STEP6_REASONING_STRENGTH": step6_reasoning_strength,
        "STEP7_AI_MODEL": step7_text_model,
        "STEP7_THINKING_MODE": step7_thinking_mode,
        "STEP7_REASONING_STRENGTH": step7_reasoning_strength,
        "NVIDIA_VISION_MAX_TOKENS": "16384",
        "AI_API_MAX_REQUESTS_PER_MINUTE": "40",
        "AI_API_SAFE_REQUESTS_PER_MINUTE": "40",
        "VISION_CONCURRENCY": str(vision_concurrency),
        "FULL_WORKFLOW_AUTO_RETRY_COUNT": str(full_workflow_auto_retry_count),
        "NVIDIA_VISION_THINKING_MODE": vision_thinking_mode,
        "NVIDIA_VISION_ENABLE_THINKING": "false" if vision_thinking_mode == "disabled" else "true",
        "NVIDIA_VISION_REASONING_STRENGTH": vision_reasoning_strength,
        "AI_REASONING_STRENGTH": step6_reasoning_strength,
        "SERVERCHAN_ENABLED": "true" if payload_bool(payload.get("serverchan_enabled")) else "false",
        "WXPUSHER_ENABLED": "true" if payload_bool(payload.get("wxpusher_enabled")) else "false",
    }
    openai_key = str(payload.get("openai_api_key") or "").strip()
    agnes_vision_key = str(payload.get("agnes_vision_key") or "").strip()
    vision_key = str(payload.get("nvidia_vision_key") or "").strip()
    minimax_vision_key = str(payload.get("nvidia_minimax_vision_key") or "").strip()
    text_key = str(payload.get("nvidia_text_key") or "").strip()
    zhipu_key = str(payload.get("api_key") or "").strip()
    serverchan_sendkey = str(payload.get("serverchan_sendkey") or "").strip()
    wxpusher_spt = str(payload.get("wxpusher_spt") or "").strip()
    if openai_key:
        values["OPENAI_API_KEY"] = openai_key
    if agnes_vision_key:
        values["AGNES_API_KEY"] = agnes_vision_key
    if vision_key:
        values["NVIDIA_VISION_API_KEY"] = vision_key
    if minimax_vision_key:
        values["NVIDIA_MINIMAX_VISION_API_KEY"] = minimax_vision_key
    if text_key:
        values["NVIDIA_TEXT_API_KEY"] = text_key
    if zhipu_key:
        values["ZHIPU_API_KEY"] = zhipu_key
    if serverchan_sendkey:
        values["SERVERCHAN_SENDKEY"] = serverchan_sendkey
    if wxpusher_spt:
        values["WXPUSHER_SPT"] = wxpusher_spt
    save_local_env_values(values)
    load_project_env(PROJECT_ROOT / ".env")
    APP_STATE.config = load_app_config(PROJECT_ROOT / "config")
    return {
        "message": "Configuration saved. Model and reasoning settings for Steps 3, 5, 6, and 7 are now stored locally.",
        "result": current_result(),
    }


def payload_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def action_test_serverchan(payload: Dict[str, Any]) -> Dict[str, Any]:
    sendkey = str(payload.get("serverchan_sendkey") or "").strip()
    values = {
        "SERVERCHAN_ENABLED": "true" if payload_bool(payload.get("serverchan_enabled")) else "false",
    }
    if sendkey:
        values["SERVERCHAN_SENDKEY"] = sendkey
    save_local_env_values(values)
    load_project_env(PROJECT_ROOT / ".env")
    result = send_serverchan_message(
        "Shopee AI Listing Assistant Test Notification",
        "The ServerChan notification connection is working.\n\nIf the full workflow later fails, the app sends the failed step and an error summary.",
    )
    return {"message": str(result["message"]), "notification_sent": True}


def action_test_wxpusher(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = str(payload.get("wxpusher_spt") or "").strip()
    values = {
        "WXPUSHER_ENABLED": "true" if payload_bool(payload.get("wxpusher_enabled")) else "false",
    }
    if token:
        values["WXPUSHER_SPT"] = token
    save_local_env_values(values)
    load_project_env(PROJECT_ROOT / ".env")
    result = send_wxpusher_spt_message(
        "Shopee AI Listing Assistant Test Notification",
        "The WxPusher notification connection is working.\n\nIf the full workflow later fails, the app sends the failed step and an error summary.",
    )
    return {"message": str(result["message"]), "notification_sent": True}


def action_send_workflow_failure(payload: Dict[str, Any]) -> Dict[str, Any]:
    serverchan_enabled = payload_bool(os.environ.get("SERVERCHAN_ENABLED", "false"))
    wxpusher_enabled = payload_bool(os.environ.get("WXPUSHER_ENABLED", "false"))
    candidate = APP_STATE.current_candidate
    store = str(payload.get("store") or APP_STATE.selected_store_name or "-").strip()
    sku = str(candidate.sku_code if candidate else payload.get("sku_code") or "-").strip()
    product_name = str(candidate.product_name if candidate else payload.get("product_name") or "-").strip()
    step_number = str(payload.get("failed_step_number") or "-").strip()
    step_label = str(payload.get("failed_step_label") or payload.get("failed_action") or "-").strip()
    failure_source = str(payload.get("failure_source") or "one_click").strip().lower()
    one_click_failure = failure_source == "one_click"
    failure_title = "Shopee Full Listing Workflow Failed" if one_click_failure else "Shopee Operation Failed"
    step_display = f"{step_number}/15 {step_label}" if step_number != "-" else step_label
    task_display = (
        f"Multi-store task {APP_STATE.multi_slot}/{APP_STATE.multi_count}"
        if APP_STATE.multi_group_id
        else "Single-store task"
    )
    error_message = mask_known_secrets(payload.get("error_message") or "Unknown error")[:1200]
    description = "\n".join(
        [
            f"## {failure_title}",
            "",
            f"- Store: {store}",
            f"- Task: {task_display}",
            f"- SKU：{sku}",
            f"- Product: {product_name}",
            f"- Failed step: {step_display}",
            f"- Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "### Error Summary",
            error_message,
            "",
            "Open Shopee AI Listing Assistant to review the detailed log and retry.",
        ]
    )
    popup_shown = show_topmost_error_alert(
        failure_title,
        "\n".join(
            [
            f"Store: {store}",
            f"Task: {task_display}",
                f"SKU：{sku}",
            f"Product: {product_name}",
            f"Failed step: {step_display}",
                "",
                error_message,
            ]
        ),
    )
    if not serverchan_enabled and not wxpusher_enabled:
        return {
            "message": "Windows topmost failure alert shown; messaging notifications are disabled",
            "notification_sent": False,
            "popup_shown": popup_shown,
        }
    sent_channels: list[str] = []
    failed_channels: list[str] = []
    if wxpusher_enabled:
        try:
            send_wxpusher_spt_message(failure_title, description)
            sent_channels.append("WxPusher")
        except Exception as exc:  # noqa: BLE001
            failed_channels.append("WxPusher：" + mask_known_secrets(exc))
    if serverchan_enabled:
        try:
            send_serverchan_message(failure_title, description)
            sent_channels.append("ServerChan")
        except Exception as exc:  # noqa: BLE001
            failed_channels.append("ServerChan: " + mask_known_secrets(exc))
    if not sent_channels:
        raise RuntimeError("Messaging notification failed: " + "; ".join(failed_channels))
    message = "Messaging notification sent through " + ", ".join(sent_channels)
    if failed_channels:
        message += "; other channels failed: " + "; ".join(failed_channels)
    return {
        "message": message,
        "notification_sent": True,
        "sent_channels": sent_channels,
        "popup_shown": popup_shown,
    }


def action_send_action_success(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = APP_STATE.current_candidate
    store = str(payload.get("store") or APP_STATE.selected_store_name or "-").strip()
    sku = str(candidate.sku_code if candidate else payload.get("sku_code") or "-").strip()
    product_name = str(candidate.product_name if candidate else payload.get("product_name") or "-").strip()
    step_number = str(payload.get("step_number") or "-").strip()
    step_label = str(payload.get("step_label") or payload.get("action") or "Operation completed").strip()
    success_source = str(payload.get("success_source") or "manual_step").strip().lower()
    one_click_success = success_source == "one_click"
    title = "Shopee Full Listing Workflow Completed" if one_click_success else "Shopee Operation Completed"
    step_display = "Steps 0–15 all completed" if one_click_success else (
        f"{step_number}/15 {step_label}" if step_number != "-" else step_label
    )
    task_display = (
        f"Multi-store task {APP_STATE.multi_slot}/{APP_STATE.multi_count}"
        if APP_STATE.multi_group_id
        else "Single-store task"
    )
    summary = mask_known_secrets(payload.get("summary") or "Operation completed successfully")[:1200]
    popup_shown = show_topmost_success_alert(
        title,
        "\n".join(
            [
            f"Store: {store}",
            f"Task: {task_display}",
                f"SKU：{sku}",
            f"Product: {product_name}",
            f"Completed step: {step_display}",
                "",
                summary,
            ]
        ),
    )
    return {
        "message": "Windows topmost completion alert shown",
        "popup_shown": popup_shown,
    }


def parse_vision_concurrency(payload: Dict[str, Any]) -> int:
    raw_value = payload.get("vision_concurrency")
    if raw_value in (None, ""):
        raw_value = os.environ.get("VISION_CONCURRENCY") or os.environ.get("NVIDIA_VISION_CONCURRENCY", "8")
    try:
        value = int(str(raw_value).strip())
    except ValueError as exc:
        raise RuntimeError("Image-analysis concurrency must be an integer from 1 to 20") from exc
    if not 1 <= value <= 20:
        raise RuntimeError("Image-analysis concurrency must be an integer from 1 to 20")
    return value


def parse_ai_execution_mode(payload: Dict[str, Any]) -> str:
    mode = str(
        payload.get("ai_execution_mode")
        or os.environ.get("AI_EXECUTION_MODE", AI_EXECUTION_MODE_MULTIMODAL)
        or AI_EXECUTION_MODE_MULTIMODAL
    ).strip().lower()
    aliases = {
        "vision_text": AI_EXECUTION_MODE_VISION_TEXT,
        "vision+text": AI_EXECUTION_MODE_VISION_TEXT,
        "multimodal": AI_EXECUTION_MODE_MULTIMODAL,
    }
    normalized = aliases.get(mode)
    if not normalized:
        raise RuntimeError("AI execution mode must be either vision-plus-text or multimodal")
    return normalized


def parse_vision_model(payload: Dict[str, Any]) -> str:
    selected_value = str(
        payload.get("step3_model")
        or payload.get("vision_model")
        or payload.get("vision_model_priority")
        or os.environ.get("STEP3_AI_MODEL")
        or os.environ.get("NVIDIA_VISION_MODEL")
        or OPENAI_DEFAULT_MODEL
    ).strip().lower()
    aliases = {
        "openai": OPENAI_DEFAULT_MODEL,
        OPENAI_DEFAULT_MODEL: OPENAI_DEFAULT_MODEL,
        "agnes_primary": AGNES_VISION_DEFAULT_MODEL,
        AGNES_VISION_DEFAULT_MODEL: AGNES_VISION_DEFAULT_MODEL,
        "qwen_primary": NVIDIA_VISION_DEFAULT_MODEL,
        NVIDIA_VISION_DEFAULT_MODEL: NVIDIA_VISION_DEFAULT_MODEL,
        "minimax_primary": NVIDIA_MINIMAX_VISION_MODEL,
        NVIDIA_MINIMAX_VISION_MODEL: NVIDIA_MINIMAX_VISION_MODEL,
    }
    model = aliases.get(selected_value)
    if model not in MULTIMODAL_AI_MODELS:
        raise RuntimeError("Step 3 requires one of the displayed multimodal model IDs")
    return model


def parse_full_workflow_auto_retry_count(payload: Dict[str, Any]) -> int:
    raw_value = payload.get("full_workflow_auto_retry_count")
    if raw_value in (None, ""):
        raw_value = os.environ.get("FULL_WORKFLOW_AUTO_RETRY_COUNT", "1")
    try:
        value = int(str(raw_value).strip())
    except ValueError as exc:
        raise RuntimeError("Automatic retries after failure must be an integer from 1 to 5.") from exc
    if not 1 <= value <= 5:
        raise RuntimeError("Automatic retries after failure must be an integer from 1 to 5.")
    return value


def parse_vision_reasoning_settings(payload: Dict[str, Any]) -> tuple[str, str]:
    mode = str(
        payload.get("vision_thinking_mode")
        or os.environ.get("STEP3_THINKING_MODE")
        or os.environ.get("NVIDIA_VISION_THINKING_MODE", "enabled")
        or "enabled"
    ).strip().lower()
    if mode in {"default", "model_default"}:
        mode = "official_default"
    if mode not in {"official_default", "adaptive", "enabled", "disabled"}:
        raise RuntimeError("Vision reasoning mode must be Official Default, Adaptive, Enabled, or Disabled.")
    strength = str(
        payload.get("vision_reasoning_strength")
        or os.environ.get("STEP3_REASONING_STRENGTH")
        or os.environ.get("NVIDIA_VISION_REASONING_STRENGTH", "maximum")
        or "maximum"
    ).strip().lower()
    if strength in {"default", "model_default"}:
        strength = "official_default"
    if strength == "highest":
        strength = "maximum"
    if strength not in {"official_default", "low", "medium", "high", "maximum"}:
        raise RuntimeError("Vision reasoning effort must be Official Default, Low, Medium, High, or Maximum.")
    return mode, strength


def parse_title_reasoning_settings(payload: Dict[str, Any]) -> tuple[str, str]:
    mode = str(
        payload.get("title_thinking_mode")
        or os.environ.get("STEP6_THINKING_MODE")
        or os.environ.get("STEP6_TEXT_THINKING_MODE", "enabled")
        or "enabled"
    ).strip().lower()
    if mode in {"default", "model_default"}:
        mode = "official_default"
    if mode not in {"official_default", "enabled", "disabled"}:
        raise RuntimeError("Title reasoning mode must be Official Default, Enabled, or Disabled.")
    strength = str(
        payload.get("title_reasoning_strength")
        or os.environ.get("STEP6_REASONING_STRENGTH")
        or os.environ.get("STEP6_TEXT_REASONING_STRENGTH", "maximum")
        or "maximum"
    ).strip().lower()
    if strength in {"default", "model_default"}:
        strength = "official_default"
    if strength == "highest":
        strength = "maximum"
    if strength not in {"official_default", "low", "medium", "high", "maximum"}:
        raise RuntimeError("Title reasoning effort must be Official Default, Low, Medium, High, or Maximum.")
    return mode, strength


def parse_keyword_reasoning_settings(
    payload: Dict[str, Any],
) -> tuple[str, str]:
    mode = str(
        payload.get("keyword_thinking_mode")
        or os.environ.get("STEP5_THINKING_MODE")
        or os.environ.get("STEP5_TEXT_THINKING_MODE", "enabled")
        or "enabled"
    ).strip().lower()
    if mode in {"default", "model_default"}:
        mode = "official_default"
    if mode not in {"official_default", "enabled", "disabled"}:
        raise RuntimeError("Search-term reasoning mode must be Official Default, Enabled, or Disabled.")
    strength = str(
        payload.get("keyword_reasoning_strength")
        or os.environ.get("STEP5_REASONING_STRENGTH")
        or os.environ.get("STEP5_TEXT_REASONING_STRENGTH", "maximum")
        or "maximum"
    ).strip().lower()
    if strength in {"default", "model_default"}:
        strength = "official_default"
    if strength == "highest":
        strength = "maximum"
    if strength not in {"official_default", "low", "medium", "high", "maximum"}:
        raise RuntimeError("Search-term reasoning effort must be Official Default, Low, Medium, High, or Maximum.")
    return mode, strength


def parse_step_text_model(payload: Dict[str, Any], payload_key: str) -> str:
    env_key = {
        "keyword_text_model": "STEP5_TEXT_MODEL",
        "title_text_model": "STEP6_TEXT_MODEL",
        "description_text_model": "STEP7_TEXT_MODEL",
    }.get(payload_key)
    if not env_key:
        raise RuntimeError("Unknown text-model setting")
    default_model = OPENAI_DEFAULT_MODEL
    new_env_key = {
        "keyword_text_model": "STEP5_AI_MODEL",
        "title_text_model": "STEP6_AI_MODEL",
        "description_text_model": "STEP7_AI_MODEL",
    }[payload_key]
    raw_model = str(
        payload.get(payload_key)
        or os.environ.get(new_env_key)
        or os.environ.get(env_key, default_model)
        or default_model
    ).strip().lower()
    aliases = {
        "openai": OPENAI_DEFAULT_MODEL,
        OPENAI_DEFAULT_MODEL: OPENAI_DEFAULT_MODEL,
        "agnes": AGNES_TEXT_DEFAULT_MODEL,
        AGNES_TEXT_DEFAULT_MODEL: AGNES_TEXT_DEFAULT_MODEL,
        "glm": NVIDIA_TEXT_DEFAULT_MODEL,
        "glm-5.2": NVIDIA_TEXT_DEFAULT_MODEL,
        NVIDIA_TEXT_DEFAULT_MODEL: NVIDIA_TEXT_DEFAULT_MODEL,
        "m3": NVIDIA_MINIMAX_VISION_MODEL,
        NVIDIA_MINIMAX_VISION_MODEL: NVIDIA_MINIMAX_VISION_MODEL,
        "qwen": NVIDIA_VISION_DEFAULT_MODEL,
        NVIDIA_VISION_DEFAULT_MODEL: NVIDIA_VISION_DEFAULT_MODEL,
    }
    model = aliases.get(raw_model)
    allowed_models = (
        MULTIMODAL_AI_MODELS
        if parse_ai_execution_mode(payload) == AI_EXECUTION_MODE_MULTIMODAL
        else VISION_TEXT_AI_MODELS
    )
    if model not in allowed_models:
        raise RuntimeError("The selected model is not available in the current AI execution mode")
    return model


def save_local_env_values(values: Dict[str, str]) -> None:
    """Persist only approved AI settings locally and never return their values."""
    with _ENV_CONFIG_LOCK:
        _save_local_env_values_unlocked(values)


def _save_local_env_values_unlocked(values: Dict[str, str]) -> None:
    allowed = {
        "AI_PROVIDER",
        "AI_EXECUTION_MODE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_MAX_OUTPUT_TOKENS",
        "OPENAI_TIMEOUT_SECONDS",
        "ZHIPU_API_KEY",
        "AGNES_API_KEY",
        "AGNES_VISION_API_KEY",
        "AGNES_VISION_MODEL",
        "AGNES_VISION_BASE_URL",
        "AGNES_VISION_MAX_TOKENS",
        "AGNES_VISION_TIMEOUT_SECONDS",
        "AGNES_TEXT_MODEL",
        "AGNES_TEXT_BASE_URL",
        "AGNES_TEXT_MAX_TOKENS",
        "AGNES_TEXT_TIMEOUT_SECONDS",
        "NVIDIA_VISION_API_KEY",
        "NVIDIA_VISION_MODEL",
        "NVIDIA_VISION_FALLBACK_MODELS",
        "NVIDIA_VISION_BASE_URL",
        "NVIDIA_VISION_MAX_TOKENS",
        "NVIDIA_VISION_TIMEOUT_SECONDS",
        "NVIDIA_MINIMAX_VISION_API_KEY",
        "NVIDIA_MINIMAX_VISION_MODEL",
        "NVIDIA_MINIMAX_VISION_BASE_URL",
        "NVIDIA_MINIMAX_VISION_MAX_TOKENS",
        "NVIDIA_MINIMAX_VISION_TIMEOUT_SECONDS",
        "NVIDIA_TEXT_API_KEY",
        "NVIDIA_TEXT_MODEL",
        "NVIDIA_TEXT_BASE_URL",
        "NVIDIA_TEXT_ENABLE_THINKING",
        "NVIDIA_TEXT_CLEAR_THINKING",
        "NVIDIA_TEXT_MAX_TOKENS",
        "STEP5_TEXT_MODEL",
        "STEP6_TEXT_MODEL",
        "STEP5_TEXT_THINKING_MODE",
        "STEP5_TEXT_REASONING_STRENGTH",
        "STEP6_TEXT_THINKING_MODE",
        "STEP6_TEXT_REASONING_STRENGTH",
        "STEP7_TEXT_MODEL",
        "STEP7_TEXT_THINKING_MODE",
        "STEP7_TEXT_REASONING_STRENGTH",
        "STEP3_AI_MODEL",
        "STEP3_THINKING_MODE",
        "STEP3_REASONING_STRENGTH",
        "STEP5_AI_MODEL",
        "STEP5_THINKING_MODE",
        "STEP5_REASONING_STRENGTH",
        "STEP6_AI_MODEL",
        "STEP6_THINKING_MODE",
        "STEP6_REASONING_STRENGTH",
        "STEP7_AI_MODEL",
        "STEP7_THINKING_MODE",
        "STEP7_REASONING_STRENGTH",
        "NVIDIA_API_MAX_REQUESTS_PER_MINUTE",
        "NVIDIA_API_SAFE_REQUESTS_PER_MINUTE",
        "NVIDIA_VISION_CONCURRENCY",
        "AI_API_MAX_REQUESTS_PER_MINUTE",
        "AI_API_SAFE_REQUESTS_PER_MINUTE",
        "VISION_CONCURRENCY",
        "FULL_WORKFLOW_AUTO_RETRY_COUNT",
        "NVIDIA_VISION_THINKING_MODE",
        "NVIDIA_VISION_ENABLE_THINKING",
        "NVIDIA_VISION_REASONING_STRENGTH",
        "AI_REASONING_STRENGTH",
        "SERVERCHAN_ENABLED",
        "SERVERCHAN_SENDKEY",
        "WXPUSHER_ENABLED",
        "WXPUSHER_SPT",
    }
    env_path = PROJECT_ROOT / ".env"
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    update_keys = {key for key, value in values.items() if key in allowed and value}
    remaining = [line for line in existing if line.split("=", 1)[0].strip() not in update_keys]
    for key, value in values.items():
        if key in update_keys:
            remaining.append(f"{key}={value}")
            os.environ[key] = value
    env_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")


def action_test_nvidia_ai(payload: Dict[str, Any], kind: str) -> Dict[str, Any]:
    action_save_ai_settings({**payload, "ai_mode": "nvidia_dual"})
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    if not isinstance(provider, NvidiaDualProvider):
        raise RuntimeError("NVIDIA dual provider is not active")
    if kind == "vision":
        result = provider.request_vision_json("This is a connectivity check. Return JSON only, with any explanatory text in English.", {"task": "vision_model_check"}, [], ["ok"])
        model = provider.last_used_models.get("vision", AGNES_VISION_DEFAULT_MODEL)
    elif kind == "minimax":
        result = provider.request_vision_model_json(
            NVIDIA_MINIMAX_VISION_MODEL,
            "This is a MiniMax M3 connectivity check. Return JSON only, with any explanatory text in English.",
            {"task": "nvidia_minimax_vision_check"},
            [],
            ["ok"],
        )
        model = provider.last_used_models.get("vision", NVIDIA_MINIMAX_VISION_MODEL)
    else:
        result = provider.request_text_json("This is a text-model connectivity check. Return JSON only, with any explanatory text in English.", {"task": "text_model_check"}, ["ok"])
        model = provider.last_used_models.get("text", "z-ai/glm-5.2")
    report_path, json_path = write_masked_ai_check_report(
        f"nvidia_{kind}",
        {"ok": bool(result.get("ok", True)), "results": [{"kind": kind, "model": model, "ok": bool(result.get("ok", True)), "error": ""}]},
    )
    label = "Current vision" if kind == "vision" else kind.capitalize()
    return {"message": f"{label} model test completed: {model}", "result": {**current_result(), "report_path": str(report_path), "ai_model_check_json": str(json_path)}}


def action_test_all_ai(payload: Dict[str, Any]) -> Dict[str, Any]:
    action_save_ai_settings(payload)
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    if isinstance(provider, NvidiaDualProvider):
        result = provider.check_models()
        report_path, json_path = write_masked_ai_check_report("nvidia_dual", result)
        return {"message": "Tests completed for the selected vision model and z-ai/glm-5.2.", "result": {**current_result(), "report_path": str(report_path), "ai_model_check_json": str(json_path)}}
    if isinstance(provider, ZhipuProvider):
        return action_test_zhipu_ai()
    return {"message": "Offline placeholder mode is active; no AI API was called.", "result": current_result()}


def write_masked_ai_check_report(name: str, result: Dict[str, Any]) -> tuple[Path, Path]:
    stamp = timestamp()
    report_path = task_output_root() / "reports" / f"ai_model_check_{name}_{stamp}.md"
    json_path = task_output_root() / "reports" / f"ai_model_check_{name}_{stamp}.json"
    sanitized = {"checked_at": stamp, "api_key": "***masked***", "ok": bool(result.get("ok")), "results": []}
    for item in result.get("results", []):
        if not isinstance(item, dict):
            continue
        error = str(item.get("error", ""))
        for key_name in [
            "AGNES_API_KEY",
            "AGNES_VISION_API_KEY",
            "NVIDIA_VISION_API_KEY",
            "NVIDIA_MINIMAX_VISION_API_KEY",
            "NVIDIA_TEXT_API_KEY",
            "ZHIPU_API_KEY",
            "SERVERCHAN_SENDKEY",
            "WXPUSHER_SPT",
        ]:
            error = mask_secret(error, os.environ.get(key_name, ""))
        error = mask_known_secrets(error)
        sanitized["results"].append({"kind": str(item.get("kind", "")), "model": str(item.get("model", "")), "ok": bool(item.get("ok")), "error": error[:220]})
    write_json(json_path, sanitized)
    lines = ["# AI Model Connectivity Test", "", "- API Key: ***masked***", "", "| Type | Model | Result | Error |", "| --- | --- | --- | --- |"]
    for item in sanitized["results"]:
        lines.append(f"| {item['kind']} | {item['model']} | {'Available' if item['ok'] else 'Unavailable'} | {item['error'].replace('|', '/')} |")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, json_path


def action_collect_competitors(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = require_candidate()
    competitors = parse_manual_competitors(str(payload.get("manual_competitors", "")))
    APP_STATE.competitors = {
        "sources": competitors,
        "warnings": [] if len(competitors) >= 5 else [f"Only {len(competitors)} competitors were provided; the title output will note insufficient competitor coverage."],
    }
    paths = save_manual_competitors(
        task_output_root() / "competitor_sources",
        str(candidate.sku_code),
        competitors,
    )
    return {
        "message": f"Saved {len(competitors)} manual competitors; JSON: {paths['json_path']}; Markdown: {paths['markdown_path']}",
        "result": current_result(),
        "workbench": workbench_payload(),
    }


def action_generate_listing(payload: Dict[str, Any]) -> Dict[str, Any]:
    candidate = require_candidate()
    if APP_STATE.asset_manifest is None:
        action_inspect_assets(payload)
    if not APP_STATE.competitors.get("sources"):
        action_collect_competitors(payload)
    api_key = str(payload.get("api_key", "")).strip()
    if api_key:
        os.environ[APP_STATE.config.ai.api_key_env] = api_key
    store = APP_STATE.config.store(str(payload.get("store", "")))
    provider = get_ai_provider(APP_STATE.config.ai, PROJECT_ROOT / "prompts")
    ai_result = provider.generate_listing(candidate, APP_STATE.asset_manifest, APP_STATE.competitors.get("sources", []))
    APP_STATE.draft = build_listing_draft(
        candidate=candidate,
        store_name=store.name,
        template_key=store.template_key,
        description_template=APP_STATE.config.description_template(store.template_key),
        asset_manifest=APP_STATE.asset_manifest,
        competitors=APP_STATE.competitors.get("sources", []),
        ai_result=ai_result,
        keyword_range=current_seo_keyword_range(),
    )
    sku = safe_filename(str(candidate.sku_code))
    draft_path = task_output_root() / "listings" / f"{sku}_listing_draft.json"
    report_path = task_output_root() / "reports" / f"{sku}_report.md"
    write_json(draft_path, APP_STATE.draft)
    write_run_report(report_path, APP_STATE.draft)
    APP_STATE.draft_path = str(draft_path)
    APP_STATE.report_path = str(report_path)
    return {"message": "Listing draft generated", "result": current_result()}


def _representative_cdp_page(port: int) -> Dict[str, Any]:
    pages = [
        page
        for page in list_pages(port)
        if isinstance(page, dict)
        and str(page.get("type", "page") or "page") == "page"
        and str(page.get("webSocketDebuggerUrl", "") or "").strip()
    ]
    if not pages:
        raise RuntimeError(f"Ziniao window port {port} has no controllable page.")

    def page_score(page: Dict[str, Any]) -> tuple[int, int]:
        url = str(page.get("url", "") or "").lower()
        return (
            2 if "seller.shopee.com.my/portal/product/new" in url else 1 if "seller.shopee.com.my" in url else 0,
            1 if url.startswith("http") else 0,
        )

    return max(pages, key=page_score)


def _ziniao_window_label(
    port: int,
    page: Dict[str, Any],
    browser: str = "",
    store_name: str = "",
) -> str:
    title = re.sub(r"\s+", " ", str(page.get("title", "") or "")).strip()
    visible_store = re.sub(r"\s+", " ", str(store_name or "")).strip()
    visible_store = visible_store or title or str(browser or "").strip() or "store name unavailable"
    if len(visible_store) > 70:
        visible_store = visible_store[:67] + "..."
    return f"Port {port} | {visible_store}"


def _normalize_store_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _candidate_store_name(
    candidate: Any,
    expected_names: Iterable[str] = (),
) -> str:
    raw_process_title = getattr(candidate, "window_title", "")
    process_title = re.sub(
        r"\s+",
        " ",
        raw_process_title if isinstance(raw_process_title, str) else "",
    ).strip()
    expected = [str(name).strip() for name in expected_names if str(name).strip()]
    normalized_title = _normalize_store_name(process_title)
    for expected_name in expected:
        if normalized_title == _normalize_store_name(expected_name):
            return expected_name
    if expected or not process_title or "..." in process_title or "…" in process_title:
        detected = detect_ziniao_store_name(
            int(candidate.port),
            expected_names=expected,
        )
        if detected:
            return detected
    return process_title


def ziniao_window_choices(
    candidates: Optional[list[Any]] = None,
) -> list[Dict[str, Any]]:
    available_candidates = (
        candidates
        if candidates is not None
        else discover_cdp_candidates(verify=True)
    )
    with _TASK_REGISTRY_LOCK:
        bound_by_port = {
            int(state.cdp_port): state
            for state in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]
            if state.cdp_binding_confirmed and state.cdp_port
        }
    windows: list[Dict[str, Any]] = []
    current_state = active_app_state()
    for candidate in available_candidates:
        port = int(candidate.port)
        try:
            page = _representative_cdp_page(port)
            title = str(page.get("title", "") or "").strip()
            url = str(page.get("url", "") or "").strip()
            store_name = _candidate_store_name(candidate)
            label = _ziniao_window_label(port, page, candidate.browser, store_name)
        except Exception:
            title = ""
            url = ""
            store_name = _candidate_store_name(candidate)
        label = f"Port {port} | {store_name or 'store name unavailable'}"
        owner = bound_by_port.get(port)
        bound_to_current = owner is current_state
        owner_label = ""
        if owner is not None:
            owner_label = (
                f"task {owner.multi_slot}/{owner.multi_count}"
                if owner.task_id
                else "single-store mode"
            )
        windows.append(
            {
                "port": port,
                "process_id": int(candidate.process_id or 0),
                "title": title,
                "url": url,
                "store_name": store_name,
                "label": label,
                "available": owner is None or bound_to_current,
                "bound_to_current": bound_to_current,
                "bound_store": str(owner.cdp_bound_store_name if owner else ""),
                "bound_task_slot": int(owner.multi_slot if owner else 0),
                "bound_owner_label": owner_label,
            }
        )
    return windows


def _parse_cdp_port(payload: Dict[str, Any]) -> int:
    try:
        port = int(str(payload.get("cdp_port", "") or "").strip())
    except (TypeError, ValueError):
        port = 0
    if port <= 0:
        raise RuntimeError("Select a Ziniao store window from the Step 9 list first.")
    return port


def _available_window_for_binding(port: int) -> tuple[Any, Dict[str, Any]]:
    candidate = next(
        (
            item
            for item in discover_cdp_candidates(verify=True)
            if int(item.port) == int(port)
        ),
        None,
    )
    if candidate is None:
        raise RuntimeError("The selected Ziniao store window is closed or unreachable. Refresh the window list.")
    with _TASK_REGISTRY_LOCK:
        owner = next(
            (
                state
                for state in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]
                if state is not active_app_state()
                and state.cdp_binding_confirmed
                and int(state.cdp_port or 0) == int(port)
            ),
            None,
        )
    if owner is not None:
        owner_label = (
            f"task {owner.multi_slot}/{owner.multi_count}"
            if owner.task_id
            else "single-store mode"
        )
        raise RuntimeError(
            f"The selected Ziniao window is already bound to {owner_label} "
            f"({owner.cdp_bound_store_name or 'another store'}). Select another window."
        )
    return candidate, _representative_cdp_page(port)


def action_list_ziniao_windows() -> Dict[str, Any]:
    candidates = discover_cdp_candidates(verify=True)
    expected_store = (
        _draft_store_name_if_available()
        or str(APP_STATE.selected_store_name or "").strip()
    )
    previous_binding = (
        bool(APP_STATE.cdp_binding_confirmed),
        int(APP_STATE.cdp_port or 0),
    )
    recovered = _restore_exact_store_cdp_binding(
        active_app_state(),
        expected_store,
        candidates,
    )
    binding_changed = recovered and previous_binding != (
        bool(APP_STATE.cdp_binding_confirmed),
        int(APP_STATE.cdp_port or 0),
    )
    windows = ziniao_window_choices(candidates)
    if not windows:
        message = "No open, connectable Ziniao store window was found. Start the target store in Ziniao first."
    elif binding_changed:
        message = (
            f"Step 9 binding restored automatically by exact store name: "
            f'"{APP_STATE.cdp_bound_store_name}" uses port {APP_STATE.cdp_port}'
        )
    else:
        message = f"Found {len(windows)} Ziniao store windows. Locate and confirm the correct one before binding this task."
    return {
        "message": message,
        "result": {**current_result(), "ziniao_windows": windows},
    }


def action_preview_ziniao_window(payload: Dict[str, Any]) -> Dict[str, Any]:
    port = _parse_cdp_port(payload)
    _candidate, page = _available_window_for_binding(port)
    store_name = _expected_task_store(payload)
    if not store_name:
        raise RuntimeError("Select a store in Step 0 and load an SKU for that store in Step 1 first.")
    task_label = (
        f"task {APP_STATE.multi_slot}/{APP_STATE.multi_count}"
        if APP_STATE.task_id
        else "single-store task"
    )
    marker_text = f"Ziniao window match: {task_label} | Store {store_name} | Port {port}"
    marker_json = json.dumps(marker_text, ensure_ascii=False)
    client = CdpClient(str(page.get("webSocketDebuggerUrl", "") or ""))
    try:
        client.connect()
        client.command("Runtime.enable")
        try:
            client.command("Page.bringToFront", {})
        except Exception:
            pass
        client.evaluate(
            f"""
(() => {{
  const markerId = "codex-ziniao-binding-marker";
  document.getElementById(markerId)?.remove();
  const marker = document.createElement("div");
  marker.id = markerId;
  marker.textContent = {marker_json};
  Object.assign(marker.style, {{
    position: "fixed", left: "12px", right: "12px", top: "12px",
    zIndex: "2147483647", padding: "18px 24px", border: "4px solid #fff",
    borderRadius: "6px", background: "#d9480f", color: "#fff",
    fontFamily: "Microsoft YaHei, Arial, sans-serif", fontSize: "20px",
    fontWeight: "700", lineHeight: "1.5", textAlign: "center",
    boxShadow: "0 8px 28px rgba(0,0,0,.45)", pointerEvents: "none"
  }});
  document.documentElement.appendChild(marker);
  window.setTimeout(() => marker.remove(), 60000);
  window.focus();
  return {{ok: true, title: document.title, url: location.href}};
}})()
"""
        )
    finally:
        client.close()
    return {
        "message": (
            f"The Ziniao window on port {port} was brought to the foreground with a store marker. "
            "Verify the store visually, then click Bind to Current Task."
        ),
        "result": {
            **current_result(),
            "ziniao_windows": ziniao_window_choices(),
            "previewed_cdp_port": str(port),
        },
    }


def action_bind_ziniao_window(payload: Dict[str, Any]) -> Dict[str, Any]:
    port = _parse_cdp_port(payload)
    candidate, page = _available_window_for_binding(port)
    store_name = _expected_task_store(payload)
    if not store_name:
        raise RuntimeError("Select a store in Step 0 and load an SKU for that store in Step 1 first.")
    detected_store_name = _candidate_store_name(
        candidate,
        expected_names=[store_name],
    )
    label = _ziniao_window_label(port, page, candidate.browser, detected_store_name)
    with _TASK_REGISTRY_LOCK:
        owner = next(
            (
                state
                for state in [_DEFAULT_APP_STATE, *_TASK_STATES.values()]
                if state is not active_app_state()
                and state.cdp_binding_confirmed
                and int(state.cdp_port or 0) == port
            ),
            None,
        )
        if owner is not None:
            owner_label = (
            f"task {owner.multi_slot}/{owner.multi_count}"
                if owner.task_id
            else "single-store mode"
            )
            raise RuntimeError(
            f"This window was just bound by {owner_label} "
            f"({owner.cdp_bound_store_name or 'another store'}). Refresh and select another window."
            )
        APP_STATE.cdp_port = port
        APP_STATE.cdp_process_id = int(candidate.process_id or 0)
        APP_STATE.cdp_binding_confirmed = True
        APP_STATE.cdp_bound_store_name = store_name
        APP_STATE.cdp_bound_window_label = detected_store_name or label
    return {
        "message": f'Binding confirmed: store "{store_name}" is locked to Ziniao window port {port}',
        "result": {**current_result(), "ziniao_windows": ziniao_window_choices()},
    }


def action_auto_bind_ziniao_window(payload: Dict[str, Any]) -> Dict[str, Any]:
    store_name = str(payload.get("store", "") or "").strip()
    if not store_name:
        raise RuntimeError("Select a store in Step 0 first.")

    normalized_store_name = re.sub(r"\s+", " ", store_name).strip().casefold()
    candidates = discover_cdp_candidates(verify=True)
    matches = [
        candidate
        for candidate in candidates
        if re.sub(
            r"\s+",
            " ",
            _candidate_store_name(candidate, expected_names=[store_name]),
        ).strip().casefold()
        == normalized_store_name
    ]
    if not matches:
        detected = [
            f"Port {candidate.port} | {_candidate_store_name(candidate) or 'store name unavailable'}"
            for candidate in candidates
        ]
        detected_text = "; ".join(detected) if detected else "no connectable Ziniao store window found"
        raise RuntimeError(
            f'No Ziniao window exactly matched "{store_name}". Current probe results: {detected_text}'
        )
    if len(matches) > 1:
        ports = "、".join(str(candidate.port) for candidate in matches)
        raise RuntimeError(
            f'Multiple Ziniao windows matched "{store_name}" (ports {ports}). Confirm the correct one manually in Step 9.'
        )

    bind_payload = dict(payload)
    bind_payload["cdp_port"] = str(matches[0].port)
    result = action_bind_ziniao_window(bind_payload)
    result["message"] = (
        f'Step 9 automatic binding succeeded: store "{store_name}" is locked to Ziniao window port {matches[0].port}'
    )
    return result


def action_unbind_ziniao_window() -> Dict[str, Any]:
    previous_store = APP_STATE.cdp_bound_store_name
    _clear_cdp_binding(active_app_state())
    return {
        "message": f"Ziniao window binding removed{f' ({previous_store})' if previous_store else ''}",
        "result": {**current_result(), "ziniao_windows": ziniao_window_choices()},
    }


def action_validate_ziniao_binding(payload: Dict[str, Any]) -> Dict[str, Any]:
    store_name = _expected_task_store(payload)
    port = assigned_task_cdp_port(store_name)
    return {
        "message": f'Manual window binding is valid: store "{store_name}" is locked to Ziniao window port {port}',
        "result": current_result(),
    }


def action_connect_ziniao() -> Dict[str, Any]:
    return action_list_ziniao_windows()


def action_probe_shopee_page() -> Dict[str, Any]:
    cdp_port = assigned_task_cdp_port(_expected_task_store())
    probe = (
        run_real_page_probe(fill_title_description=False, cdp_port=cdp_port)
        if cdp_port is not None
        else run_real_page_probe(fill_title_description=False)
    )
    quill = probe.get("quill", {})
    artifacts = probe.get("artifacts", {})
    message = (
        "Probe completed: "
        f"title input={'detected' if probe.get('titleCandidates') else 'not detected'}; "
        f"description editor={'detected' if quill.get('hasEditor') else 'not detected'}; "
        f"image upload area={'detected' if probe.get('imageUploadDetected') else 'not detected'}; "
        f"variation area={'detected' if probe.get('variationDetected') else 'not detected'}; "
        f"price and stock table={'detected' if probe.get('priceStockDetected') else 'not detected'}; "
        f"logistics area={'detected' if probe.get('logisticsDetected') else 'not detected'}. "
        f"Report: {artifacts.get('report_path', '')}; "
        f"JSON：{artifacts.get('json_path', '')}；"
        f"HTML：{artifacts.get('html_path', '')}；"
        f"screenshot: {artifacts.get('screenshot_path', '')}"
    )
    return {
        "message": message,
        "result": {
            **current_result(),
            "report_path": str(artifacts.get("report_path", "")),
            "probe_json_path": str(artifacts.get("json_path", "")),
            "probe_html_path": str(artifacts.get("html_path", "")),
            "probe_screenshot_path": str(artifacts.get("screenshot_path", "")),
        },
    }


def _autofill_result_message(result: Any) -> str:
    message = str(result.message)
    if result.screenshot_path:
        message += f"; screenshot: {result.screenshot_path}"
    if result.html_path:
        message += f"；HTML：{result.html_path}"
    if result.diagnostics_path:
        message += f"; diagnostics: {result.diagnostics_path}"
    if result.log_path:
        message += f"; log: {result.log_path}"
    if result.report_path:
        message += f"; report: {result.report_path}"
    return message


def _remember_listing_result(
    result: Any,
    payload: Dict[str, Any],
    draft_path: Path,
) -> str:
    product_id = str(result.product_id or "").strip()
    if not product_id:
        raise RuntimeError("A write-back token cannot be created before the product ID is fetched.")
    store_name = _draft_store_name(draft_path)
    workbook_path = str(payload.get("workbook") or APP_STATE.config.workbook.path).strip()
    APP_STATE.selected_store_name = store_name
    saved_result = {
        "store_name": store_name,
        "sku_code": str(result.sku_code),
        "product_id": product_id,
        "listing_status": str(result.listing_status or "Unlisted"),
        "workbook_path": workbook_path,
    }
    token = secrets.token_urlsafe(24)
    with APP_STATE.listing_result_lock:
        APP_STATE.listing_results[token] = saved_result
        while len(APP_STATE.listing_results) > 100:
            APP_STATE.listing_results.pop(next(iter(APP_STATE.listing_results)))
        APP_STATE.last_listing_result = saved_result
        APP_STATE.last_listing_result_token = token
    return token


def action_auto_fill(payload: Dict[str, Any]) -> Dict[str, Any]:
    draft_path = APP_STATE.draft_path
    if not draft_path:
        latest = latest_listing_draft()
        if not latest:
            raise RuntimeError("Generate listing_draft.json first.")
        draft_path = str(latest)
    mode = str(payload.get("run_mode") or "dry_run")
    if mode == "save_delist":
        APP_STATE.last_listing_result = {}
        APP_STATE.last_workbook_update = {}
        APP_STATE.last_listing_result_token = ""
    if mode == "save_delist":
        required_store = _draft_store_name(Path(draft_path)) if APP_STATE.task_id else ""
        cdp_port = assigned_task_cdp_port(required_store)
        request_guard = current_action_request_guard()
        result = (
            run_save_delist_only_from_draft(
                Path(draft_path),
                cdp_port=cdp_port,
                cancellation_check=lambda: not is_action_request_current(request_guard),
            )
            if cdp_port is not None
            else run_save_delist_only_from_draft(
                Path(draft_path),
                cancellation_check=lambda: not is_action_request_current(request_guard),
            )
        )
    else:
        required_store = _draft_store_name(Path(draft_path)) if APP_STATE.task_id else ""
        cdp_port = assigned_task_cdp_port(required_store)
        result = (
            run_autofill_from_draft(Path(draft_path), mode=mode, cdp_port=cdp_port)
            if cdp_port is not None
            else run_autofill_from_draft(Path(draft_path), mode=mode)
        )
    if APP_STATE.task_id and result.cdp_port:
        APP_STATE.cdp_port = int(result.cdp_port)
    if result.ok and result.mode == "save_delist" and result.product_id:
        _remember_listing_result(result, payload, Path(draft_path))
    message = _autofill_result_message(result)
    if not result.ok:
        raise RuntimeError(message)
    return {"message": message, "result": {**current_result(), **result.to_dict()}}


def action_fetch_product_id(payload: Dict[str, Any]) -> Dict[str, Any]:
    draft_path = APP_STATE.draft_path
    if not draft_path:
        latest = latest_listing_draft()
        if not latest:
            raise RuntimeError("Generate listing_draft.json first.")
        draft_path = str(latest)
    draft = Path(draft_path)
    required_store = _draft_store_name(draft) if APP_STATE.task_id else ""
    cdp_port = assigned_task_cdp_port(required_store)
    request_guard = current_action_request_guard()
    result = run_fetch_product_id_from_draft(
        draft,
        cdp_port=cdp_port,
        cancellation_check=lambda: not is_action_request_current(request_guard),
    ) if cdp_port is not None else run_fetch_product_id_from_draft(
        draft,
        cancellation_check=lambda: not is_action_request_current(request_guard),
    )
    if APP_STATE.task_id and result.cdp_port:
        APP_STATE.cdp_port = int(result.cdp_port)
    message = _autofill_result_message(result)
    if not result.ok or not str(result.product_id or "").strip():
        raise RuntimeError(message)
    _remember_listing_result(result, payload, draft)
    return {"message": message, "result": {**current_result(), **result.to_dict()}}


def _draft_store_name(draft_path: Path) -> str:
    draft: Dict[str, Any] = {}
    if draft_path.is_file():
        try:
            loaded = json.loads(draft_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                draft = loaded
        except (OSError, json.JSONDecodeError):
            draft = {}
    if not draft and isinstance(APP_STATE.draft, dict):
        draft = APP_STATE.draft
    store = draft.get("store", {}) if isinstance(draft, dict) else {}
    store_name = str(store.get("name", "") if isinstance(store, dict) else "").strip()
    if not store_name:
        raise RuntimeError("The listing draft has no store name, so the workbook sheet cannot be determined.")
    return store_name


def action_record_listing_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = str(payload.get("listing_result_token", "")).strip()
    with APP_STATE.listing_result_lock:
        saved = dict(APP_STATE.listing_results.get(token, {}))
    if not saved:
        raise RuntimeError(
            "No product ID is available for write-back. Return to Step 13 and click Fetch Product ID or Retry Product ID Fetch."
        )

    update = append_listing_record(
        Path(str(saved.get("workbook_path", ""))),
        store_name=str(saved.get("store_name", "")),
        sku_code=str(saved.get("sku_code", "")),
        product_id=str(saved.get("product_id", "")),
    )
    with APP_STATE.listing_result_lock:
        APP_STATE.last_workbook_update = update.to_dict()
        if token in APP_STATE.listing_results:
            APP_STATE.listing_results[token]["workbook_update"] = update.to_dict()
    if APP_STATE.task_id and APP_STATE.reserved_listing_key:
        with _TASK_REGISTRY_LOCK:
            _SKU_RESERVATIONS.pop(APP_STATE.reserved_listing_key, None)
            APP_STATE.reserved_listing_key = None
    if update.appended:
        save_note = ""
        if update.write_mode == "open_workbook":
            app_name = update.spreadsheet_app or "Excel/WPS"
        save_note = f"; recalculated and saved automatically through the open {app_name} instance"
        message = (
            f"Workbook updated: sheet {update.sheet_name}, row {update.row_number}; "
            f"column A product ID {update.product_id}, column E SKU {update.sku_code}{save_note}"
        )
    else:
        save_note = ""
        if update.write_mode == "open_workbook":
            app_name = update.spreadsheet_app or "Excel/WPS"
        save_note = f"; recalculated and saved automatically through the open {app_name} instance"
        message = (
            f"Sheet {update.sheet_name}, row {update.row_number} already contains the same product ID and SKU. "
            f"No duplicate row was added{save_note}"
        )
    return {
        "message": message,
        "result": {
            **current_result(),
            "product_id": update.product_id,
            "listing_status": str(saved.get("listing_status", "")),
            "workbook_record_status": message,
            "workbook_sheet": update.sheet_name,
            "workbook_row": str(update.row_number),
            "workbook_path": update.workbook_path,
            "listing_result_token": token,
        },
    }


def action_cleanup_cache() -> Dict[str, Any]:
    state = active_app_state()
    with _TASK_REGISTRY_LOCK:
        active_multi_states = list(_TASK_STATES.values())

    deleted_files = 0
    deleted_bytes = 0
    cleaned_areas: list[str] = []
    skipped_areas: list[str] = []

    if state.task_id:
        output_root = task_output_root()
        files, size = _clear_generated_tree(output_root, [])
        deleted_files += files
        deleted_bytes += size
        cleaned_areas.append("current multi-store task output")
    else:
        output_root = PROJECT_ROOT / "outputs"
        protected_outputs = [
            PROJECT_ROOT / "outputs" / "multi_tasks" / item.task_id
            for item in active_multi_states
            if item.task_id
        ]
        files, size = _clear_generated_tree(output_root, protected_outputs)
        deleted_files += files
        deleted_bytes += size
        cleaned_areas.append("single-store history and closed multi-store task output")

    if state.task_id or active_multi_states:
        skipped_areas.append("shared logs while multi-store tasks are running")
    else:
        files, size = _clear_generated_tree(PROJECT_ROOT / "logs", [])
        deleted_files += files
        deleted_bytes += size
        cleaned_areas.append("old run logs")

    _reset_generated_task_state(state)
    freed_mb = deleted_bytes / (1024 * 1024)
    message = (
        f"Cache cleanup completed: deleted {deleted_files} files and freed {freed_mb:.2f} MB. "
        "API keys, store settings, Ziniao window bindings, program files, the listing workbook, and manual asset packs were preserved."
    )
    if skipped_areas:
        message += " The following areas were skipped to protect active tasks: " + ", ".join(skipped_areas) + "."
    return {
        "message": message,
        "result": {
            **current_result(),
            "cleanup_deleted_files": str(deleted_files),
            "cleanup_deleted_bytes": str(deleted_bytes),
            "cleanup_freed_mb": f"{freed_mb:.2f}",
            "cleanup_cleaned_areas": ", ".join(cleaned_areas),
            "cleanup_skipped_areas": ", ".join(skipped_areas),
        },
    }


def action_run_linear_shopee_stage(target_stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    draft_path = APP_STATE.draft_path
    if not draft_path:
        latest = latest_listing_draft()
        if not latest:
            raise RuntimeError("Generate listing_draft.json first.")
        draft_path = str(latest)
    APP_STATE.listing_runtime_status = {
        "state": "running",
        "stage": target_stage,
        "message": f"Running linear stage: {target_stage}",
    }
    required_store = _draft_store_name(Path(draft_path)) if APP_STATE.task_id else ""
    cdp_port = assigned_task_cdp_port(required_store)
    stage_result = (
        run_linear_stage_from_draft(Path(draft_path), target_stage, cdp_port=cdp_port)
        if cdp_port is not None
        else run_linear_stage_from_draft(Path(draft_path), target_stage)
    )
    if APP_STATE.task_id and stage_result.get("cdp_port"):
        APP_STATE.cdp_port = int(stage_result["cdp_port"])
    if not stage_result.get("ok"):
        APP_STATE.listing_runtime_status = {
            "state": "failed",
            "stage": target_stage,
            "message": str(stage_result.get("message", "Linear stage failed")),
        }
        raise RuntimeError(str(stage_result.get("message", "Linear stage failed")))
    if target_stage == "checklist":
        checklist = stage_result.get("checklist", {})
        APP_STATE.last_checklist = dict(checklist) if isinstance(checklist, dict) else {}
    APP_STATE.listing_runtime_status = {
        "state": "complete",
        "stage": target_stage,
        "message": str(stage_result.get("message", "Linear stage completed")),
    }
    result_payload = {
        **current_result(),
        "linear_stage": target_stage,
        "step1_status": stage_result.get("message", "") if target_stage == "step1" else "",
        "step2_status": stage_result.get("message", "") if target_stage == "step2" else "",
        "checklist": stage_result.get("checklist", {}),
        "checklist_can_save": bool(APP_STATE.last_checklist.get("canSaveDelist")),
        "screenshot_path": str(stage_result.get("screenshot_path", "")),
        "html_path": str(stage_result.get("html_path", "")),
        "report_path": str(stage_result.get("report_path", "")),
        "diagnostics_path": str(stage_result.get("diagnostics_path", "")),
        "cdp_port": str(stage_result.get("cdp_port", "")),
    }
    return {
            "message": str(stage_result.get("message", "Linear stage completed")),
        "result": result_payload,
        "workbench": workbench_payload(),
    }


def latest_listing_draft() -> Path | None:
    listing_dir = task_output_root() / "listings"
    if not listing_dir.exists():
        return None
    files = sorted(listing_dir.glob("*_listing_draft.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def require_candidate() -> CandidateSKU:
    if APP_STATE.current_candidate is None:
        raise RuntimeError("Select a candidate SKU first.")
    return APP_STATE.current_candidate


def current_result() -> Dict[str, str]:
    candidate = APP_STATE.current_candidate
    listing = APP_STATE.draft.get("listing", {}) if APP_STATE.draft else {}
    binding_result = {
        "cdp_port": str(APP_STATE.cdp_port or ""),
        "cdp_process_id": str(APP_STATE.cdp_process_id or ""),
        "cdp_binding_confirmed": "true" if APP_STATE.cdp_binding_confirmed else "false",
        "cdp_bound_store_name": APP_STATE.cdp_bound_store_name,
        "cdp_bound_window_label": APP_STATE.cdp_bound_window_label,
    }
    if candidate is None:
        return binding_result
    download_status = APP_STATE.asset_download_status or "Waiting for a manually supplied asset-pack path"
    manifest = APP_STATE.asset_manifest
    asset_folder_summary = (
        f"main {len(manifest.main_images)} | detail {len(manifest.detail_images)} | "
        f"English assets {len(manifest.english_images)} | SKU {len(manifest.sku_images)} | video {len(manifest.videos)}"
        if manifest
        else ""
    )
    saved = APP_STATE.last_listing_result
    workbook_update = APP_STATE.last_workbook_update
    if workbook_update:
        if workbook_update.get("appended"):
            workbook_record_status = (
                f"Written to row {workbook_update.get('row_number')} in {workbook_update.get('sheet_name')}"
            )
        else:
            workbook_record_status = (
                f"The same record already exists in row {workbook_update.get('row_number')} of {workbook_update.get('sheet_name')}; no duplicate was added"
            )
    else:
        workbook_record_status = "Waiting for Save and Delist to complete"
    return {
        "selected_store": str(APP_STATE.selected_store_name),
        "sku_code": str(candidate.sku_code),
        "product_name": str(candidate.product_name),
        "brand": str(candidate.brand),
        "prices": f"{candidate.price_1box} / {candidate.price_2box} / {candidate.price_3box}",
        "stock": str(candidate.overseas_available_stock),
        "title": str(listing.get("title", "")),
        "asset_path": APP_STATE.selected_asset_path,
        "asset_download_dir": str(Path(APP_STATE.selected_asset_path).parent) if APP_STATE.selected_asset_path else "",
        "asset_download_status": download_status,
        "asset_folder_summary": asset_folder_summary,
        "draft_path": APP_STATE.draft_path,
        "report_path": APP_STATE.report_path,
        "product_id": str(saved.get("product_id", "")),
        "listing_status": str(saved.get("listing_status", "")),
        "workbook_record_status": workbook_record_status,
        "workbook_sheet": str(workbook_update.get("sheet_name", "")),
        "workbook_row": str(workbook_update.get("row_number", "")),
        "listing_result_token": APP_STATE.last_listing_result_token,
        **binding_result,
    }


def open_folder(path: Path) -> Dict[str, Any]:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        webbrowser.open(path.as_uri())
    return {"message": f"Opened folder: {path}", "result": current_result()}


def escape_html(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _bind_available_server(
    preferred_port: int,
    max_attempts: int = 20,
) -> tuple[ThreadingHTTPServer, int]:
    last_error: Optional[OSError] = None
    for port in range(preferred_port, preferred_port + max_attempts):
        try:
            return ExclusiveThreadingHTTPServer(("127.0.0.1", port), RequestHandler), port
        except OSError as exc:
            error_code = getattr(exc, "winerror", None) or exc.errno
            if error_code not in {errno.EADDRINUSE, 10048}:
                raise
            last_error = exc
    raise RuntimeError(
        f"Ports {preferred_port} through {preferred_port + max_attempts - 1} are already in use"
    ) from last_error


def _read_app_server_info(
    url: str,
    timeout: float = 0.4,
) -> Optional[Dict[str, Any]]:
    try:
        with urlopen(f"{url}api/app-info", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("app") != "shopee_listing_app":
            return None
        return payload
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _is_current_server(url: str, timeout: float = 0.4) -> bool:
    payload = _read_app_server_info(url, timeout=timeout)
    return bool(
        payload
        and str(payload.get("release_id") or "").strip() == APP_RELEASE_ID
    )


def _find_current_server(
    preferred_port: int,
    max_attempts: int = 20,
) -> Optional[str]:
    for port in range(preferred_port, preferred_port + max_attempts):
        url = f"http://127.0.0.1:{port}/"
        if _is_current_server(url):
            return url
    return None


def _request_remote_shutdown(url: str, timeout: float = 1.5) -> bool:
    request = Request(
        f"{url}api/shutdown",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _wait_until_app_server_stops(url: str, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _read_app_server_info(url, timeout=0.2) is None:
            return True
        time.sleep(0.1)
    return _read_app_server_info(url, timeout=0.2) is None


def _windows_listening_pid(port: int) -> int:
    if os.name != "nt":
        return 0
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            encoding="mbcs",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    local_address = f"127.0.0.1:{port}"
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0].upper() == "TCP"
            and parts[1] == local_address
            and parts[-1].isdigit()
        ):
            return int(parts[-1])
    return 0


def _force_stop_confirmed_app_server(url: str, port: int) -> bool:
    if os.name != "nt" or _read_app_server_info(url, timeout=0.3) is None:
        return False
    payload = _read_app_server_info(url, timeout=0.3) or {}
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        pid = _windows_listening_pid(port)
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, PermissionError):
        return False
    return _wait_until_app_server_stops(url, timeout=3.0)


def _cleanup_redundant_app_servers(
    preferred_port: int,
    keep_url: Optional[str] = None,
    max_attempts: int = 20,
) -> None:
    for port in range(preferred_port, preferred_port + max_attempts):
        url = f"http://127.0.0.1:{port}/"
        if keep_url and url == keep_url:
            continue
        payload = _read_app_server_info(url)
        if payload is None:
            continue
        release_id = str(payload.get("release_id") or "older release").strip()
        print(f"Detected an existing application process at {url} ({release_id}); closing it")
        stopped = _request_remote_shutdown(url) and _wait_until_app_server_stops(url)
        if not stopped:
            stopped = _force_stop_confirmed_app_server(url, port)
        if stopped:
            print(f"Closed the existing application process at {url}")
        else:
            print(f"Could not close the existing process at {url}; continuing startup attempts")


def _schedule_server_shutdown(server: object, delay: float = 0.08) -> None:
    stop_event = getattr(server, "lifecycle_stop_event", None)
    if stop_event is not None:
        stop_event.set()

    def shutdown_after_response() -> None:
        time.sleep(delay)
        try:
            server.shutdown()  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return

    threading.Thread(
        target=shutdown_after_response,
        name="shopee-app-shutdown",
        daemon=True,
    ).start()


def _monitor_ui_lifecycle(server: ExclusiveThreadingHTTPServer) -> None:
    while not server.lifecycle_stop_event.wait(1.0):
        if server.ui_clients.should_shutdown():
            print("All application pages are closed; the background process is exiting automatically")
            server.lifecycle_stop_event.set()
            server.shutdown()
            return


def _open_app_url(url: str) -> None:
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except Exception:
        webbrowser.open_new_tab(url)


def run_server(port: int, open_browser: bool) -> int:
    ensure_output_dirs(PROJECT_ROOT)
    existing_url = _find_current_server(port)
    _cleanup_redundant_app_servers(port, keep_url=existing_url)
    if existing_url:
        print(f"The current application release is already running at {existing_url}")
        if open_browser:
            _open_app_url(existing_url)
        return 0
    server, bound_port = _bind_available_server(port)
    url = f"http://127.0.0.1:{bound_port}/"
    if bound_port != port:
        print(f"Port {port} was occupied by an older process; switched automatically to {bound_port}")
    print(f"Shopee AI Listing Assistant started: {url}")
    if open_browser:
        _open_app_url(url)
    if isinstance(server, ExclusiveThreadingHTTPServer):
        lifecycle_thread = threading.Thread(
            target=_monitor_ui_lifecycle,
            args=(server,),
            name="shopee-ui-lifecycle",
            daemon=True,
        )
        lifecycle_thread.start()
    try:
        server.serve_forever()
    finally:
        stop_event = getattr(server, "lifecycle_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        server.server_close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Local web interface for Shopee AI Listing Assistant")
    parser.add_argument("--check", action="store_true", help="Only verify that the web interface can load")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        build_home_html(build_initial_gui_state(PROJECT_ROOT / "config"))
        print("Web GUI check OK")
        return 0
    return run_server(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
