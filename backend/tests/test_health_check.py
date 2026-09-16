"""Tests for the dependency probes and the /api/health/full endpoint.

The behaviours pinned here are the ones that cost something when they are
wrong: a probe must not be expensive, must not leak internals, must not report
the whole service dead because an optional part is missing, and must not let
one hung dependency hang the endpoint.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from main import app
from utils.health_check import (
    DEGRADED,
    HEALTHY,
    UNHEALTHY,
    HealthCheck,
)


def run(coro):
    """Drive a coroutine without pytest-asyncio, which is not a dependency."""
    return asyncio.run(coro)


class Boom:
    """A probe that fails with something revealing."""

    def __call__(self):
        raise RuntimeError(
            "could not open /Users/someone/secrets/jobs.db as user admin:hunter2"
        )


class TestProbesReport:
    def test_each_probe_returns_a_verdict_rather_than_raising(self):
        checker = HealthCheck()
        for probe in (
            checker.check_rag_system,
            checker.check_llm,
            checker.check_database,
        ):
            result = probe()
            assert result["status"] in (HEALTHY, DEGRADED, UNHEALTHY)
            assert "service" in result and "duration_ms" in result

    def test_the_rag_probe_counts_rather_than_searching(self):
        """A search loads the embedding model: measured at ~8s on a cold process.

        Fifteen times the cost of ``count()`` to prove the same reachability,
        on an endpoint built to be polled.
        """
        # ``rag.resume_indexer`` as an attribute of the package is the
        # singleton, not the module - the package re-exports it under the same
        # name. sys.modules gets the module itself.
        indexer_module = sys.modules["rag.resume_indexer"]

        calls = []
        original_count = indexer_module.resume_indexer.count
        original_search = indexer_module.resume_indexer.search
        indexer_module.resume_indexer.count = lambda: calls.append("count") or 3
        indexer_module.resume_indexer.search = lambda *a, **k: calls.append("search")
        try:
            HealthCheck().check_rag_system()
        finally:
            indexer_module.resume_indexer.count = original_count
            indexer_module.resume_indexer.search = original_search
        assert calls == ["count"]

    def test_the_llm_probe_does_not_send_a_prompt(self):
        """A real prompt runs against a 120s timeout, unauthenticated."""
        import agents.ollama_handler as handler_module

        calls = []
        client = handler_module.llm_client
        original_backend = client.available_backend
        original_generate = client.generate
        client.available_backend = lambda *a, **k: calls.append("probe") or "ollama"
        client.generate = lambda *a, **k: calls.append("prompt")
        try:
            HealthCheck().check_llm()
        finally:
            client.available_backend = original_backend
            client.generate = original_generate
        assert calls == ["probe"]

    def test_a_key_only_backend_says_so_rather_than_implying_a_reply(self):
        """`healthy` off a configured key is not the same as a model answering.

        Gemini and Claude report availability from a key with no network call,
        so a rate-limited free tier fails every request and still shows green.
        The chip stays healthy - the fallback path really does work - but the
        note has to say what was checked.
        """
        import agents.ollama_handler as handler_module

        client = handler_module.llm_client
        original_backend = client.available_backend
        try:
            client.available_backend = lambda *a, **k: "gemini"
            report = HealthCheck().check_llm()
        finally:
            client.available_backend = original_backend

        assert report["status"] == "healthy"
        assert report["backend"] == "gemini"
        assert "not a live call" in report["note"]

    def test_ollama_is_not_labelled_key_only(self):
        """Its probe really does reach the daemon, so it needs no caveat."""
        import agents.ollama_handler as handler_module

        client = handler_module.llm_client
        original_backend = client.available_backend
        try:
            client.available_backend = lambda *a, **k: "ollama"
            report = HealthCheck().check_llm()
        finally:
            client.available_backend = original_backend

        assert report["status"] == "healthy"
        assert report["note"] is None

    def test_no_backend_at_all_is_degraded_not_healthy(self):
        import agents.ollama_handler as handler_module

        client = handler_module.llm_client
        original_backend = client.available_backend
        try:
            client.available_backend = lambda *a, **k: None
            report = HealthCheck().check_llm()
        finally:
            client.available_backend = original_backend

        assert report["status"] == "degraded"
        assert report["required"] is False
        assert "deterministic" in report["note"]


class TestFailuresAreReportedWithoutLeaking:
    def test_the_exception_text_never_reaches_the_caller(self):
        checker = HealthCheck()
        checker.check_database = Boom()
        report = run(checker.full_health_check())
        body = str(report)
        assert "hunter2" not in body
        assert "/Users/someone" not in body

    def test_the_caller_gets_an_id_that_ties_to_the_log(self):
        checker = HealthCheck()
        checker.check_database = Boom()
        report = run(checker.full_health_check())
        database = next(s for s in report["services"] if s["service"] == "database")
        assert database["status"] == UNHEALTHY
        assert len(database["error_id"]) == 8
        assert database["error_type"] == "RuntimeError"


class TestAContendedImportIsNotAFailure:
    """A probe thread meeting a module another thread is still importing.

    CPython does not wait for that lock, it raises ``_DeadlockError``. The
    probes could not tell it apart from a dead dependency and reported the
    database as unhealthy while SQLite was serving queries normally. Observed
    once on a real start-up, which is what these pin.
    """

    @staticmethod
    def _deadlock() -> RuntimeError:
        from importlib._bootstrap import _DeadlockError

        return _DeadlockError("deadlock detected by _ModuleLock('agents.x')")

    def test_it_subclasses_runtime_error_and_not_import_error(self):
        """The obvious guess is wrong, and guessing it costs the whole fix."""
        error = self._deadlock()
        assert isinstance(error, RuntimeError)
        assert not isinstance(error, ImportError)

    def test_the_import_is_tried_again_and_the_probe_recovers(self, monkeypatch):
        import utils.health_check as module

        monkeypatch.setattr(module, "IMPORT_RETRY_SECONDS", 0)
        attempts = []

        def flaky(name):
            attempts.append(name)
            if len(attempts) == 1:
                raise self._deadlock()
            return SimpleNamespace(thing="loaded")

        monkeypatch.setattr(module.importlib, "import_module", flaky)
        assert module._lazy_import("agents.application_tracker", "thing") == "loaded"
        assert len(attempts) == 2

    def test_an_ordinary_runtime_error_is_not_retried(self, monkeypatch):
        """Retrying a genuine fault only delays the report of it."""
        import utils.health_check as module

        monkeypatch.setattr(module, "IMPORT_RETRY_SECONDS", 0)
        attempts = []

        def broken(name):
            attempts.append(name)
            raise RuntimeError("the database file is corrupt")

        monkeypatch.setattr(module.importlib, "import_module", broken)
        with pytest.raises(RuntimeError, match="corrupt"):
            module._lazy_import("agents.application_tracker", "thing")
        assert len(attempts) == 1

    def test_an_import_that_stays_locked_is_still_reported(self, monkeypatch):
        """One retry, not a loop: a probe must never become the hang."""
        import utils.health_check as module

        monkeypatch.setattr(module, "IMPORT_RETRY_SECONDS", 0)
        attempts = []

        def always_locked(name):
            attempts.append(name)
            raise self._deadlock()

        monkeypatch.setattr(module.importlib, "import_module", always_locked)
        with pytest.raises(RuntimeError):
            module._lazy_import("agents.application_tracker", "thing")
        assert len(attempts) == 2

    def test_the_database_probe_survives_one_contended_import(self, monkeypatch):
        """The end the user sees: a status page that does not cry wolf."""
        import utils.health_check as module

        monkeypatch.setattr(module, "IMPORT_RETRY_SECONDS", 0)
        real = module.importlib.import_module
        seen = []

        def flaky(name):
            seen.append(name)
            if len(seen) == 1:
                raise self._deadlock()
            return real(name)

        monkeypatch.setattr(module.importlib, "import_module", flaky)
        assert HealthCheck().check_database()["status"] == HEALTHY


class TestOverallStatus:
    def test_a_missing_model_is_degraded_not_unhealthy(self):
        """This service is designed to answer without an LLM at all."""
        checker = HealthCheck()
        checker.check_llm = lambda: {
            "service": "llm",
            "status": DEGRADED,
            "required": False,
            "duration_ms": 1.0,
        }
        report = run(checker.full_health_check())
        assert report["overall_status"] == DEGRADED

    def test_a_failed_required_service_is_unhealthy(self):
        checker = HealthCheck()
        checker.check_database = Boom()
        assert run(checker.full_health_check())["overall_status"] == UNHEALTHY

    def test_everything_up_is_healthy(self):
        checker = HealthCheck()
        for name in ("check_rag_system", "check_llm", "check_database"):
            setattr(
                checker,
                name,
                lambda n=name: {
                    "service": n,
                    "status": HEALTHY,
                    "required": True,
                    "duration_ms": 1.0,
                },
            )
        assert run(checker.full_health_check())["overall_status"] == HEALTHY


class TestOneSlowProbeCannotHangTheEndpoint:
    def test_a_hung_probe_times_out(self, monkeypatch):
        monkeypatch.setattr("utils.health_check.PROBE_TIMEOUT_SECONDS", 0.05)
        checker = HealthCheck()

        def hangs():
            import time

            time.sleep(5)

        result = run(checker._run("database", hangs))
        assert result["status"] == UNHEALTHY
        assert "timed out" in result["detail"]


class TestProbesRunConcurrently:
    def test_the_total_is_nearer_the_slowest_than_the_sum(self):
        import time

        def slow(name):
            def probe():
                time.sleep(0.2)
                return {
                    "service": name,
                    "status": HEALTHY,
                    "required": True,
                    "duration_ms": 200.0,
                }

            return probe

        checker = HealthCheck()
        checker.check_rag_system = slow("rag")
        checker.check_llm = slow("llm")
        checker.check_database = slow("database")
        report = run(checker.full_health_check())
        # Sequential would be ~600ms. Allow generous headroom for a loaded CI box.
        assert report["duration_ms"] < 450, "the probes did not run concurrently"


class TestTheEndpoint:
    def test_it_answers_and_names_every_service(self):
        with TestClient(app) as client:
            body = client.get("/api/health/full").json()
        assert {s["service"] for s in body["services"]} == {"rag", "llm", "database"}

    def test_a_degraded_service_still_serves_traffic(self):
        """503 here would pull a correct, working instance out of the pool."""
        with TestClient(app) as client:
            response = client.get("/api/health/full")
        if response.json()["overall_status"] == DEGRADED:
            assert response.status_code == 200

    def test_a_dead_required_dependency_returns_503(self, monkeypatch):
        monkeypatch.setattr(
            "utils.health_check.health_check.check_database", Boom()
        )
        with TestClient(app) as client:
            response = client.get("/api/health/full")
        assert response.status_code == 503
        assert response.json()["overall_status"] == UNHEALTHY

    def test_the_simple_health_endpoint_is_untouched(self):
        """Liveness must stay trivial: no dependency can make it fail."""
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200

    @pytest.mark.parametrize("field", ["overall_status", "services", "timestamp"])
    def test_the_shape_is_stable(self, field):
        with TestClient(app) as client:
            assert field in client.get("/api/health/full").json()
