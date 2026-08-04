from concurrent.futures import ThreadPoolExecutor
import http.client
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.nvidia_request_control import (
    AIResponseCache,
    NvidiaRateLimitExhausted,
    NvidiaRequestCancelled,
    NvidiaRequestController,
    is_rate_limit_error,
    is_transient_network_error,
)


class _RateLimitError(RuntimeError):
    code = 429

    def __init__(self, retry_after=""):
        super().__init__("Too Many Requests")
        self.headers = {"Retry-After": retry_after} if retry_after else {}


def _record_order(order, lock, label):
    with lock:
        order.append(label)
    return label


class NvidiaRequestControlTests(unittest.TestCase):
    def test_recognizes_rate_limit_codes_and_messages(self):
        self.assertTrue(is_rate_limit_error(_RateLimitError()))
        self.assertTrue(is_rate_limit_error(RuntimeError("quota temporarily exceeded")))
        self.assertTrue(is_rate_limit_error(RuntimeError("too many requests; try again later")))
        self.assertFalse(is_rate_limit_error(RuntimeError("invalid JSON")))

    def test_recognizes_transient_network_failures(self):
        self.assertTrue(
            is_transient_network_error(
                urllib.error.URLError(ConnectionResetError(10054, "remote reset"))
            )
        )
        self.assertTrue(
            is_transient_network_error(http.client.IncompleteRead(b"", 100))
        )
        self.assertTrue(
            is_transient_network_error(
                RuntimeError("Remote end closed connection without response")
            )
        )
        self.assertTrue(is_transient_network_error(RuntimeError("HTTP 504:")))
        self.assertFalse(is_transient_network_error(RuntimeError("invalid JSON")))

    def test_retries_transient_network_failure_with_same_request(self):
        now = [100.0]
        sleeps = []
        statuses = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        controller = NvidiaRequestController(
            safe_requests_per_minute=35,
            clock=lambda: now[0],
            sleep=sleep,
            status_callback=statuses.append,
        )
        attempts = [0]

        def request():
            attempts[0] += 1
            if attempts[0] == 1:
                raise urllib.error.URLError(
                    ConnectionResetError(10054, "remote reset")
                )
            return {"ok": True}

        result = controller.execute(
            request,
            model="agnes-model",
            step="generate-keywords",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts[0], 2)
        self.assertEqual(sleeps, [2.0])
        self.assertTrue(
            any("connection was interrupted" in str(item["message"]) for item in statuses)
        )

    def test_retries_with_retry_after_then_returns_success(self):
        now = [100.0]
        sleeps = []
        statuses = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        controller = NvidiaRequestController(
            safe_requests_per_minute=35,
            clock=lambda: now[0],
            sleep=sleep,
            status_callback=statuses.append,
        )
        attempts = [0]

        def request():
            attempts[0] += 1
            if attempts[0] == 1:
                raise _RateLimitError("7")
            return {"ok": True}

        result = controller.execute(request, model="vision-model", step="vision")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(sleeps, [7.0])
        self.assertTrue(any(item["rate_limited"] for item in statuses))
        self.assertEqual(controller.rate_limit_report["retry_count"], 1)

    def test_raises_after_four_automatic_retries(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        controller = NvidiaRequestController(35, clock=lambda: now[0], sleep=sleep)

        with self.assertRaises(NvidiaRateLimitExhausted) as ctx:
            controller.execute(lambda: (_ for _ in ()).throw(_RateLimitError()), model="text-model", step="title")

        self.assertEqual(sleeps, [5.0, 15.0, 30.0, 60.0])
        self.assertEqual(ctx.exception.report["retry_count"], 4)
        self.assertFalse(ctx.exception.report["blocked_listing_flow"])

    def test_allows_parallel_requests_while_reserving_each_rate_limit_slot(self):
        controller = NvidiaRequestController(35, 40)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def request():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"ok": True}

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(
                    lambda _index: controller.execute(
                        request,
                        model="vision-model",
                        step="vision",
                        max_retries=0,
                    ),
                    range(4),
                )
            )

        self.assertEqual(results, [{"ok": True}] * 4)
        self.assertGreaterEqual(max_active, 2)
        self.assertEqual(controller.status()["recent_60s_requests"], 4)

    def test_request_batches_are_dispatched_in_submission_order(self):
        controller = NvidiaRequestController(40, 40)
        first_batch = controller.begin_batch("store-a", "analyze-images", 2)
        second_batch = controller.begin_batch("store-b", "analyze-images", 1)
        order = []
        order_lock = threading.Lock()

        def execute(label, batch_id, task_id):
            return controller.execute(
                lambda: _record_order(order, order_lock, label),
                model="vision-model",
                step="analyze-images",
                max_retries=0,
                batch_id=batch_id,
                task_id=task_id,
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            second_future = executor.submit(execute, "B", second_batch, "store-b")
            time.sleep(0.03)
            first_futures = [
                executor.submit(execute, "A", first_batch, "store-a")
                for _index in range(2)
            ]
            results = [future.result(timeout=2) for future in first_futures]
            results.append(second_future.result(timeout=2))

        self.assertEqual(results, ["A", "A", "B"])
        self.assertEqual(order, ["A", "A", "B"])
        self.assertEqual(controller.status()["batch_queue_length"], 0)

    def test_finishing_empty_batch_releases_the_next_batch(self):
        controller = NvidiaRequestController(40, 40)
        cached_batch = controller.begin_batch("store-a", "analyze-images", 20)
        next_batch = controller.begin_batch("store-b", "generate-title", 1)
        controller.finish_batch(cached_batch)

        result = controller.execute(
            lambda: {"ok": True},
            model="text-model",
            step="generate-title",
            max_retries=0,
            batch_id=next_batch,
            task_id="store-b",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(controller.status()["batch_queue_length"], 0)

    def test_cancelled_request_stops_before_another_rate_limit_retry(self):
        now = [0.0]
        sleeps = []
        cancelled = [False]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
            cancelled[0] = True

        controller = NvidiaRequestController(
            35,
            clock=lambda: now[0],
            sleep=sleep,
        )

        with self.assertRaises(NvidiaRequestCancelled):
            controller.execute(
                lambda: (_ for _ in ()).throw(_RateLimitError()),
                model="text-model",
                step="title",
                cancellation_check=lambda: cancelled[0],
            )

        self.assertEqual(sleeps, [5.0])

    def test_success_cache_reuses_same_prompt_payload_and_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "asset.jpg"
            image_path.write_bytes(b"image-bytes")
            cache = AIResponseCache(Path(temp_dir) / "cache")
            key = cache.make_key("model", "prompt", {"task": "vision"}, [str(image_path)])

            self.assertIsNone(cache.load(key))
            cache.save(key, {"main_image": "asset.jpg"})
            self.assertEqual(cache.load(key), {"main_image": "asset.jpg"})
            self.assertEqual(key, cache.make_key("model", "prompt", {"task": "vision"}, [str(image_path)]))


if __name__ == "__main__":
    unittest.main()
