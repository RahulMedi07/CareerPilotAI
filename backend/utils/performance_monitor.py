"""Timing that can be aggregated, not just logged.

``@observed`` (``utils/logger``) already writes one JSON line per agent call.
That is the right tool for *this request went wrong*; it is the wrong tool for
*is the p95 drifting*, because answering that means shipping and querying the
logs. This module keeps a small bounded window of recent durations in process so
the numbers can be read straight off an endpoint.

Two deliberate differences from the usual sketch:

- **``time.perf_counter``, not ``time.time``.** ``time.time`` follows the wall
  clock, so an NTP correction or a DST change during a call yields a negative or
  wildly inflated duration. ``perf_counter`` is monotonic and is the documented
  tool for measuring intervals.
- **No ``status_code`` field.** An agent method has no idea whether it is being
  called over HTTP, from the workflow, or from a benchmark. Recording a
  hard-coded ``200`` next to a duration invents a fact, and it would read as
  ``200`` on the failure path too, which is worse than omitting it.

Percentiles come from a fixed-size deque per operation, so memory is bounded no
matter how long the process runs, and the window naturally follows recent
behaviour rather than being dominated by start-up outliers.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from functools import wraps
from typing import Any, Callable, Deque, Dict, List, TypeVar

from utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

WINDOW = 256
SLOW_CALL_MS = 1000.0


def _percentile(ordered: List[float], fraction: float) -> float:
    """Nearest-rank percentile of an already-sorted list."""
    if not ordered:
        return 0.0
    index = int(round(fraction * (len(ordered) - 1)))
    return ordered[index]


class PerformanceRegistry:
    """Recent durations per operation, with counts of failures."""

    def __init__(self, window: int = WINDOW) -> None:
        self.window = window
        self._samples: Dict[str, Deque[float]] = {}
        self._calls: Dict[str, int] = {}
        self._failures: Dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, operation: str, duration_ms: float, failed: bool = False) -> None:
        """Log one timing sample.

        Samples are kept in a bounded deque, so a long-running process reports
        recent behaviour rather than an average dragged around by the first
        cold call it ever made. Failures are counted separately because a fast
        failure would otherwise flatter the numbers.
        """
        with self._lock:
            samples = self._samples.get(operation)
            if samples is None:
                samples = self._samples[operation] = deque(maxlen=self.window)
            samples.append(duration_ms)
            self._calls[operation] = self._calls.get(operation, 0) + 1
            if failed:
                self._failures[operation] = self._failures.get(operation, 0) + 1

    def snapshot(self, operation: str) -> Dict[str, Any]:
        """Percentiles for one operation, or ``{}`` if it has never run.

        Empty rather than ``None`` so callers can use ``.get()`` on the result
        without a separate existence check - a monitoring helper that raises
        ``AttributeError`` when an operation has not been exercised yet would
        be a monitoring helper that breaks the thing it monitors.
        """
        with self._lock:
            samples = self._samples.get(operation)
            if not samples:
                return {}
            ordered = sorted(samples)
            calls = self._calls.get(operation, 0)
            failures = self._failures.get(operation, 0)
            return {
                "operation": operation,
                "calls": calls,
                "failures": failures,
                "window": len(ordered),
                "min_ms": round(ordered[0], 3),
                "p50_ms": round(_percentile(ordered, 0.50), 3),
                "p95_ms": round(_percentile(ordered, 0.95), 3),
                "max_ms": round(ordered[-1], 3),
                "mean_ms": round(sum(ordered) / len(ordered), 3),
            }

    def report(self) -> List[Dict[str, Any]]:
        """Every operation seen, slowest p95 first."""
        with self._lock:
            names = list(self._samples)
        rows = [s for s in (self.snapshot(name) for name in names) if s]
        return sorted(rows, key=lambda row: row["p95_ms"], reverse=True)

    def reset(self) -> None:
        """Discard every recorded sample, call count and failure count."""
        with self._lock:
            self._samples.clear()
            self._calls.clear()
            self._failures.clear()


performance_registry = PerformanceRegistry()


def monitor_performance(operation_name: str) -> Callable[[F], F]:
    """Record how long a call took, whether or not it succeeded.

    The exception is re-raised untouched; a monitor that alters control flow is
    not a monitor. Failures are recorded too, because an operation that gets
    fast by starting to fail early is the single most misleading thing a
    latency graph can show.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            failed = False
            try:
                return func(*args, **kwargs)
            except Exception:
                failed = True
                raise
            finally:
                duration_ms = (time.perf_counter() - started) * 1000.0
                performance_registry.record(operation_name, duration_ms, failed)
                if duration_ms >= SLOW_CALL_MS:
                    logger.warning(
                        "Slow operation: %s took %.0f ms", operation_name, duration_ms
                    )

        return wrapper  # type: ignore[return-value]

    return decorator
