"""Tests for the performance monitor."""

from __future__ import annotations

import threading
import time

import pytest

from utils.performance_monitor import (
    PerformanceRegistry,
    monitor_performance,
    performance_registry,
)


class TestRecording:
    def test_a_call_is_recorded(self):
        registry = PerformanceRegistry()
        registry.record("op", 12.5, failed=False)
        snapshot = registry.snapshot("op")
        assert snapshot["calls"] == 1
        assert snapshot["failures"] == 0
        assert snapshot["p50_ms"] == 12.5

    def test_an_unknown_operation_reports_nothing_rather_than_raising(self):
        assert PerformanceRegistry().snapshot("never-called") == {}

    def test_failures_are_counted_separately(self):
        registry = PerformanceRegistry()
        registry.record("op", 1.0, failed=False)
        registry.record("op", 2.0, failed=True)
        snapshot = registry.snapshot("op")
        assert snapshot["calls"] == 2
        assert snapshot["failures"] == 1

    def test_the_window_is_bounded(self):
        """A registry that grows forever is a slow memory leak in a
        long-running process."""
        registry = PerformanceRegistry(window=10)
        for i in range(500):
            registry.record("op", float(i), failed=False)
        assert registry.snapshot("op")["window"] == 10
        assert registry.snapshot("op")["calls"] == 500

    def test_percentiles_reflect_the_recent_window_not_all_time(self):
        registry = PerformanceRegistry(window=5)
        for _ in range(20):
            registry.record("op", 1000.0, failed=False)
        for _ in range(5):
            registry.record("op", 1.0, failed=False)
        assert registry.snapshot("op")["p95_ms"] == 1.0


class TestPercentiles:
    def test_p50_and_p95_on_a_known_distribution(self):
        registry = PerformanceRegistry()
        for value in range(1, 101):
            registry.record("op", float(value), failed=False)
        snapshot = registry.snapshot("op")
        assert snapshot["min_ms"] == 1.0
        assert snapshot["max_ms"] == 100.0
        assert 49.0 <= snapshot["p50_ms"] <= 51.0
        assert 94.0 <= snapshot["p95_ms"] <= 96.0

    def test_a_single_sample_is_every_percentile(self):
        registry = PerformanceRegistry()
        registry.record("op", 7.0, failed=False)
        snapshot = registry.snapshot("op")
        assert snapshot["p50_ms"] == snapshot["p95_ms"] == 7.0


class TestTheDecorator:
    def test_the_return_value_is_untouched(self):
        @monitor_performance("test.passthrough")
        def work():
            return {"answer": 42}

        assert work() == {"answer": 42}

    def test_a_failure_is_re_raised_not_swallowed(self):
        performance_registry.reset()

        @monitor_performance("test.failure")
        def work():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            work()

        snapshot = performance_registry.snapshot("test.failure")
        assert snapshot["calls"] == 1
        assert snapshot["failures"] == 1, "a failed call was not timed"

    def test_a_slow_call_is_still_timed(self):
        performance_registry.reset()

        @monitor_performance("test.slow")
        def work():
            time.sleep(0.02)

        work()
        assert performance_registry.snapshot("test.slow")["p50_ms"] >= 15.0

    def test_durations_are_never_negative(self):
        """``time.time()`` can go backwards when the clock is corrected;
        ``perf_counter`` cannot, which is why it is used."""
        performance_registry.reset()

        @monitor_performance("test.monotonic")
        def work():
            return 1

        for _ in range(50):
            work()
        assert performance_registry.snapshot("test.monotonic")["min_ms"] >= 0.0

    def test_metadata_is_preserved(self):
        @monitor_performance("test.meta")
        def documented():
            """Docs."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Docs."


class TestReport:
    def test_the_report_is_ordered_by_p95_worst_first(self):
        registry = PerformanceRegistry()
        registry.record("fast", 1.0, failed=False)
        registry.record("slow", 900.0, failed=False)
        registry.record("medium", 50.0, failed=False)
        names = [row["operation"] for row in registry.report()]
        assert names == ["slow", "medium", "fast"]

    def test_an_empty_registry_reports_an_empty_list(self):
        assert PerformanceRegistry().report() == []

    def test_the_report_carries_no_arguments_or_results(self):
        """It is served on an unauthenticated endpoint."""
        registry = PerformanceRegistry()
        registry.record("op", 1.0, failed=False)
        rendered = repr(registry.report())
        assert "resume" not in rendered.lower()


class TestThreadSafety:
    def test_concurrent_recording_loses_nothing(self):
        registry = PerformanceRegistry(window=1024)

        def hammer():
            for _ in range(200):
                registry.record("op", 1.0, failed=False)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert registry.snapshot("op")["calls"] == 1600
