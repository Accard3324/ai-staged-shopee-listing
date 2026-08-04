from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, TypeVar
import uuid


T = TypeVar("T")
_CURRENT_REQUEST_BATCH_ID: ContextVar[str] = ContextVar("nvidia_request_batch_id", default="")
_CURRENT_REQUEST_TASK_ID: ContextVar[str] = ContextVar("nvidia_request_task_id", default="")
BACKOFF_SECONDS = (5.0, 15.0, 30.0, 60.0)
NETWORK_BACKOFF_SECONDS = (2.0, 5.0, 10.0, 20.0)
RATE_LIMIT_SIGNALS = (
    "too many requests",
    "rate limit",
    "request limit exceeded",
    "quota temporarily exceeded",
    "please retry later",
)
TRANSIENT_NETWORK_SIGNALS = (
    "winerror 10053",
    "winerror 10054",
    "winerror 10060",
    "connection aborted",
    "connection reset",
    "connection timed out",
    "incompleteread",
    "read operation timed out",
    "remote end closed connection",
    "temporarily unavailable",
    "the remote host forcibly closed",
)
TRANSIENT_HTTP_SIGNALS = (
    "http 408:",
    "http 425:",
    "http 500:",
    "http 502:",
    "http 503:",
    "http 504:",
)


def is_rate_limit_error(error: BaseException) -> bool:
    code = getattr(error, "code", None) or getattr(error, "status", None) or getattr(error, "status_code", None)
    if str(code) == "429":
        return True
    text = str(error).lower()
    return any(signal in text for signal in RATE_LIMIT_SIGNALS)


def is_transient_network_error(error: BaseException) -> bool:
    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(
            current,
            (
                TimeoutError,
                ConnectionError,
                http.client.IncompleteRead,
                http.client.RemoteDisconnected,
            ),
        ):
            return True
        if getattr(current, "winerror", None) in {10053, 10054, 10060}:
            return True
        text = str(current).lower()
        if text.startswith(TRANSIENT_HTTP_SIGNALS):
            return True
        if any(signal in text for signal in TRANSIENT_NETWORK_SIGNALS):
            return True
        for nested in (
            getattr(current, "reason", None),
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def retry_after_seconds(error: BaseException) -> Optional[float]:
    headers = getattr(error, "headers", None)
    if headers is None:
        return None
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


class NvidiaRateLimitExhausted(RuntimeError):
    def __init__(self, report: Mapping[str, object]):
        self.report = dict(report)
        super().__init__(
            f"AI API rate limit remained after {self.report.get('retry_count', 0)} retries "
            f"for {self.report.get('step', 'unknown step')}"
        )


class NvidiaRequestCancelled(RuntimeError):
    pass


@dataclass
class NvidiaRequestBatch:
    batch_id: str
    task_id: str
    label: str
    expected_requests: int
    submitted_requests: int = 0
    created_at: float = 0.0


@contextmanager
def nvidia_request_batch_scope(batch_id: str, task_id: str):
    batch_token = _CURRENT_REQUEST_BATCH_ID.set(str(batch_id or ""))
    task_token = _CURRENT_REQUEST_TASK_ID.set(str(task_id or ""))
    try:
        yield
    finally:
        _CURRENT_REQUEST_BATCH_ID.reset(batch_token)
        _CURRENT_REQUEST_TASK_ID.reset(task_token)


def current_nvidia_request_batch_id() -> str:
    return _CURRENT_REQUEST_BATCH_ID.get()


def current_nvidia_request_task_id() -> str:
    return _CURRENT_REQUEST_TASK_ID.get()


class NvidiaRequestController:
    """Reserve request slots safely while allowing concurrent AI calls."""

    def __init__(
        self,
        safe_requests_per_minute: int = 35,
        max_requests_per_minute: int = 40,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ):
        self.safe_requests_per_minute = max(1, int(safe_requests_per_minute))
        self.max_requests_per_minute = max(self.safe_requests_per_minute, int(max_requests_per_minute))
        self.clock = clock
        self.sleep = sleep
        self.status_callback = status_callback
        self._request_times: deque[float] = deque()
        self._slot_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._batch_condition = threading.Condition(threading.RLock())
        self._batch_queue: deque[str] = deque()
        self._batches: Dict[str, NvidiaRequestBatch] = {}
        self._status: Dict[str, object] = {
            "recent_60s_requests": 0,
            "rate_limited": False,
            "estimated_wait_seconds": 0.0,
            "message": "AI API queue is ready",
            "retry_attempt": 0,
            "retry_max": len(BACKOFF_SECONDS),
        }
        self.rate_limit_report: Dict[str, object] = {
            "encountered": False,
            "model": "",
            "step": "",
            "retry_count": 0,
            "fallback_used": "",
            "blocked_listing_flow": False,
        }

    def configure(self, safe_requests_per_minute: int, max_requests_per_minute: int) -> None:
        self.safe_requests_per_minute = max(1, int(safe_requests_per_minute))
        self.max_requests_per_minute = max(self.safe_requests_per_minute, int(max_requests_per_minute))

    def status(self, task_id: str = "") -> Dict[str, object]:
        recent_count = self._recent_count()
        with self._state_lock:
            status = dict(self._status)
        status["recent_60s_requests"] = recent_count
        status["safe_requests_per_minute"] = self.safe_requests_per_minute
        status["max_requests_per_minute"] = self.max_requests_per_minute
        status.update(self._batch_status(task_id))
        return status

    def begin_batch(self, task_id: str, label: str, expected_requests: int = 1) -> str:
        batch = NvidiaRequestBatch(
            batch_id=uuid.uuid4().hex,
            task_id=str(task_id or "single"),
            label=str(label or "AI request"),
            expected_requests=max(1, int(expected_requests)),
            created_at=self.clock(),
        )
        with self._batch_condition:
            self._batches[batch.batch_id] = batch
            self._batch_queue.append(batch.batch_id)
            self._batch_condition.notify_all()
        return batch.batch_id

    def finish_batch(self, batch_id: str) -> None:
        if not batch_id:
            return
        with self._batch_condition:
            self._remove_batch_unlocked(batch_id)
            self._batch_condition.notify_all()

    def execute(
        self,
        request: Callable[[], T],
        *,
        model: str,
        step: str,
        max_retries: int = 4,
        batch_id: str = "",
        task_id: str = "",
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        cancellation_check: Optional[Callable[[], bool]] = None,
    ) -> T:
        retry_limit = min(
            max(0, int(max_retries)),
            max(len(BACKOFF_SECONDS), len(NETWORK_BACKOFF_SECONDS)),
        )
        for attempt in range(retry_limit + 1):
            self._raise_if_cancelled(cancellation_check)
            active_batch_id = batch_id if attempt == 0 else ""
            self._reserve_slot(
                model=model,
                step=step,
                batch_id=active_batch_id,
                task_id=task_id,
                status_callback=status_callback,
                cancellation_check=cancellation_check,
            )
            self._raise_if_cancelled(cancellation_check)
            try:
                result = request()
                self._raise_if_cancelled(cancellation_check)
                self._publish(
                    rate_limited=False,
                    estimated_wait_seconds=0.0,
                    message="AI API request completed",
                    retry_attempt=attempt,
                    model=model,
                    step=step,
                    task_id=task_id,
                    status_callback=status_callback,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                rate_limited = is_rate_limit_error(exc)
                transient_network_error = is_transient_network_error(exc)
                if not rate_limited and not transient_network_error:
                    raise
                if transient_network_error and not rate_limited:
                    if attempt >= retry_limit:
                        raise
                    wait_seconds = NETWORK_BACKOFF_SECONDS[attempt]
                    self._publish(
                        rate_limited=False,
                        estimated_wait_seconds=wait_seconds,
                        message=(
                            "The AI API connection was interrupted. Retrying the same model: "
                            f"attempt {attempt + 1}/{retry_limit}"
                        ),
                        retry_attempt=attempt + 1,
                        model=model,
                        step=step,
                        task_id=task_id,
                        status_callback=status_callback,
                    )
                    self._interruptible_sleep(wait_seconds, cancellation_check)
                    continue
                report = {
                    "encountered": True,
                    "model": model,
                    "step": step,
                    "retry_count": min(attempt + 1, retry_limit),
                    "fallback_used": "",
                    "blocked_listing_flow": False,
                }
                self.rate_limit_report = report
                if attempt >= retry_limit:
                    self._publish(
                        rate_limited=True,
                        estimated_wait_seconds=0.0,
                        message="AI API rate-limit retries were exhausted",
                        retry_attempt=retry_limit,
                        model=model,
                        step=step,
                        task_id=task_id,
                        status_callback=status_callback,
                    )
                    raise NvidiaRateLimitExhausted(report) from None
                wait_seconds = retry_after_seconds(exc)
                if wait_seconds is None:
                    wait_seconds = BACKOFF_SECONDS[attempt]
                self._publish(
                    rate_limited=True,
                    estimated_wait_seconds=wait_seconds,
                    message=f"AI API rate limited. Waiting before retry {attempt + 1}/{retry_limit}",
                    retry_attempt=attempt + 1,
                    model=model,
                    step=step,
                    task_id=task_id,
                    status_callback=status_callback,
                )
                self._interruptible_sleep(wait_seconds, cancellation_check)
        raise RuntimeError("AI request controller reached an invalid state")

    def _reserve_slot(
        self,
        *,
        model: str,
        step: str,
        batch_id: str = "",
        task_id: str = "",
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        cancellation_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        effective_batch_id = self._wait_for_batch_turn(
            batch_id=batch_id,
            task_id=task_id,
            label=step,
            model=model,
            status_callback=status_callback,
            cancellation_check=cancellation_check,
        )
        while True:
            self._raise_if_cancelled(cancellation_check)
            with self._slot_lock:
                now = self.clock()
                self._purge_unlocked(now)
                if len(self._request_times) < self.safe_requests_per_minute:
                    self._request_times.append(now)
                    self._mark_batch_request_submitted(effective_batch_id)
                    return
                wait_seconds = max(0.01, 60.0 - (now - self._request_times[0]))
            self._publish(
                rate_limited=True,
                estimated_wait_seconds=wait_seconds,
                message="The software request-rate safety threshold was reached; waiting for an available slot",
                retry_attempt=0,
                model=model,
                step=step,
                task_id=task_id,
                status_callback=status_callback,
            )
            self._interruptible_sleep(wait_seconds, cancellation_check)

    def _wait_for_batch_turn(
        self,
        *,
        batch_id: str,
        task_id: str,
        label: str,
        model: str,
        status_callback: Optional[Callable[[Dict[str, object]], None]],
        cancellation_check: Optional[Callable[[], bool]],
    ) -> str:
        effective_batch_id = batch_id
        with self._batch_condition:
            if not effective_batch_id or effective_batch_id not in self._batches:
                effective_batch_id = self.begin_batch(task_id, label, 1)
            while self._batch_queue and self._batch_queue[0] != effective_batch_id:
                self._raise_if_cancelled(cancellation_check)
                if effective_batch_id not in self._batches:
                    raise NvidiaRequestCancelled("The AI request was cancelled")
                batch = self._batches.get(effective_batch_id)
                position = list(self._batch_queue).index(effective_batch_id) + 1
                self._publish(
                    rate_limited=False,
                    estimated_wait_seconds=0.0,
                    message=f"The AI request batch is queued behind {position - 1} batch(es)",
                    retry_attempt=0,
                    model=model,
                    step=label,
                    task_id=batch.task_id if batch else task_id,
                    status_callback=status_callback,
                )
                self._batch_condition.wait(timeout=0.25)
            self._raise_if_cancelled(cancellation_check)
        return effective_batch_id

    def _interruptible_sleep(
        self,
        seconds: float,
        cancellation_check: Optional[Callable[[], bool]],
    ) -> None:
        wait_seconds = max(0.0, float(seconds))
        if not cancellation_check or self.sleep is not time.sleep:
            self.sleep(wait_seconds)
            self._raise_if_cancelled(cancellation_check)
            return
        deadline = self.clock() + wait_seconds
        while True:
            self._raise_if_cancelled(cancellation_check)
            remaining = deadline - self.clock()
            if remaining <= 0:
                return
            self.sleep(min(0.25, remaining))

    @staticmethod
    def _raise_if_cancelled(
        cancellation_check: Optional[Callable[[], bool]],
    ) -> None:
        if cancellation_check and cancellation_check():
            raise NvidiaRequestCancelled("The AI request was cancelled by a newer retry or by the user")

    def _mark_batch_request_submitted(self, batch_id: str) -> None:
        if not batch_id:
            return
        with self._batch_condition:
            batch = self._batches.get(batch_id)
            if batch is None:
                return
            batch.submitted_requests += 1
            if batch.submitted_requests >= batch.expected_requests:
                self._remove_batch_unlocked(batch_id)
            self._batch_condition.notify_all()

    def _remove_batch_unlocked(self, batch_id: str) -> None:
        self._batches.pop(batch_id, None)
        try:
            self._batch_queue.remove(batch_id)
        except ValueError:
            pass

    def _batch_status(self, task_id: str = "") -> Dict[str, object]:
        with self._batch_condition:
            queue = [
                self._batches[batch_id]
                for batch_id in self._batch_queue
                if batch_id in self._batches
            ]
        current = queue[0] if queue else None
        task_position = 0
        if task_id:
            task_position = next(
                (index for index, batch in enumerate(queue, start=1) if batch.task_id == task_id),
                0,
            )
        return {
            "batch_queue_length": len(queue),
            "current_batch_task_id": current.task_id if current else "",
            "current_batch_label": current.label if current else "",
            "current_batch_submitted": current.submitted_requests if current else 0,
            "current_batch_expected": current.expected_requests if current else 0,
            "task_queue_position": task_position,
        }

    def _recent_count(self) -> int:
        with self._slot_lock:
            self._purge_unlocked(self.clock())
            return len(self._request_times)

    def _purge_unlocked(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] >= 60.0:
            self._request_times.popleft()

    def _publish(
        self,
        *,
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
        **updates: object,
    ) -> None:
        recent_count = self._recent_count()
        with self._state_lock:
            self._status.update(updates)
            self._status["recent_60s_requests"] = recent_count
            payload = dict(self._status)
        payload.update(self._batch_status(str(updates.get("task_id", ""))))
        payload["safe_requests_per_minute"] = self.safe_requests_per_minute
        payload["max_requests_per_minute"] = self.max_requests_per_minute
        if status_callback:
            status_callback(payload)
        if self.status_callback:
            self.status_callback(payload)


class AIResponseCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def make_key(
        self,
        model: str,
        system_prompt: str,
        user_payload: Mapping[str, object],
        image_paths: Iterable[str] = (),
    ) -> str:
        images = []
        for raw_path in image_paths:
            path = Path(raw_path)
            if not path.is_file():
                images.append({"path": str(path), "sha256": "missing"})
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            images.append({"name": path.name, "sha256": digest})
        payload = {
            "model": model,
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "images": images,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def load(self, key: str) -> Optional[Dict[str, object]]:
        path = self.cache_dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, key: str, value: Mapping[str, object]) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


_GLOBAL_CONTROLLER = NvidiaRequestController()


def get_nvidia_request_controller() -> NvidiaRequestController:
    safe = int(
        os.environ.get("AI_API_SAFE_REQUESTS_PER_MINUTE")
        or os.environ.get("NVIDIA_API_SAFE_REQUESTS_PER_MINUTE", "35")
        or "35"
    )
    maximum = int(
        os.environ.get("AI_API_MAX_REQUESTS_PER_MINUTE")
        or os.environ.get("NVIDIA_API_MAX_REQUESTS_PER_MINUTE", "40")
        or "40"
    )
    _GLOBAL_CONTROLLER.configure(safe, maximum)
    return _GLOBAL_CONTROLLER
