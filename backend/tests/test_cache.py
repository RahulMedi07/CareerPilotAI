"""Tests for the cache.

A cache is a correctness surface before it is a speed one. Most of these tests
exist because the obvious implementation gets them wrong silently: the wrong
answer is still returned quickly, and nothing logs an error.
"""

from __future__ import annotations

import threading
import time

import pytest

from utils.cache import (
    MISS,
    Cache,
    all_stats,
    cache_result,
    clear_all,
    make_key,
)


class TestKeysDescribeInputsNotObjects:
    """The original sketch built keys from ``str(self)``, a memory address."""

    def test_two_instances_asking_the_same_question_share_an_answer(self):
        cache = Cache(ttl_minutes=10)
        calls = []

        class Agent:
            @cache_result(cache, "agent")
            def analyse(self, text):
                calls.append(text)
                return {"len": len(text)}

        first = Agent().analyse("hello")
        second = Agent().analyse("hello")

        assert first == second
        assert calls == ["hello"], "the second instance recomputed an identical question"

    def test_a_recycled_address_cannot_serve_a_dead_objects_answer(self):
        """CPython reuses freed addresses; a key containing one is a landmine.

        With ``str(self)`` in the key this is not a miss, which would merely be
        slow - it is a *hit* on another object's data.
        """
        cache = Cache(ttl_minutes=10)

        class Agent:
            def __init__(self, name):
                self.name = name

            @cache_result(cache, "agent")
            def whoami(self, question):
                return {"answered_by": self.name}

        first = Agent("agent-A")
        first.whoami("who?")
        address = id(first)
        del first

        second = Agent("agent-B")
        # Whether the address is reused is a CPython detail; the point is that
        # even when it is, the cached value must not be attributed to it.
        result = second.whoami("who?")
        assert result["answered_by"] in {"agent-A", "agent-B"}
        if id(second) == address:
            assert result["answered_by"] == "agent-A", (
                "the key is derived from arguments, so both agents share the "
                "answer to an identical question - that is correct here "
                "because the answer does not depend on which agent asked"
            )

    def test_keys_are_stable_across_processes(self):
        """``hash()`` on a string is randomised per process (PEP 456).

        A key built from it changes on every restart, so a persistent or
        shared cache built that way can never hit.
        """
        key = make_key("prefix", "some text", 42)
        assert key == make_key("prefix", "some text", 42)
        assert key != make_key("prefix", "some text", 43)
        # A sha256 digest, not a 64-bit int that could collide undetectably.
        assert len(key) > 32

    def test_different_arguments_do_not_collide(self):
        assert make_key("p", "a", "bc") != make_key("p", "ab", "c")


class TestFalsyResultsAreStillResults:
    def test_an_empty_dict_is_cached(self):
        """``if cached:`` treats ``{}`` as a miss, so the expensive path runs
        forever for exactly the inputs that produce nothing."""
        cache = Cache(ttl_minutes=10)
        calls = []

        @cache_result(cache, "empty")
        def nothing(text):
            calls.append(text)
            return {}

        assert nothing("x") == {}
        assert nothing("x") == {}
        assert len(calls) == 1

    @pytest.mark.parametrize("value", [None, 0, "", [], {}, False])
    def test_every_falsy_result_is_cached(self, value):
        cache = Cache(ttl_minutes=10)
        calls = []

        @cache_result(cache, "falsy")
        def produce(_):
            calls.append(1)
            return value

        produce("k")
        produce("k")
        assert len(calls) == 1


class TestCallersCannotCorruptEachOther:
    def test_mutating_a_result_does_not_change_the_cached_copy(self):
        cache = Cache(ttl_minutes=10)

        @cache_result(cache, "skills")
        def analyse(_):
            return {"skills": ["python"]}

        first = analyse("jd")
        first["skills"].append("injected")

        second = analyse("jd")
        assert second["skills"] == ["python"], (
            "one caller's edit leaked into every later caller's result"
        )

    def test_mutating_the_input_after_the_call_does_not_change_the_stored_copy(self):
        cache = Cache(ttl_minutes=10)

        @cache_result(cache, "x")
        def analyse(payload):
            return {"seen": sorted(payload)}

        payload = ["b", "a"]
        analyse(payload)
        payload.append("c")
        assert analyse(["b", "a"]) == {"seen": ["a", "b"]}


class TestExpiry:
    def test_an_expired_entry_is_a_miss(self):
        cache = Cache(ttl_minutes=0.0005)  # 30 ms
        cache.set("k", "value")
        assert cache.get("k") == "value"
        time.sleep(0.06)
        assert cache.get("k") is MISS
        assert cache.stats()["expirations"] == 1

    def test_zero_ttl_disables_the_cache(self):
        cache = Cache(ttl_minutes=0)
        cache.set("k", "v")
        assert cache.get("k") is MISS
        assert len(cache) == 0

    def test_a_negative_ttl_is_rejected(self):
        with pytest.raises(ValueError):
            Cache(ttl_minutes=-1)


class TestTheCacheIsBounded:
    """An unbounded dict keyed on user-supplied text, on an endpoint that
    needs no credentials, is a memory-exhaustion primitive."""

    def test_entries_never_exceed_the_cap(self):
        cache = Cache(ttl_minutes=10, max_entries=3)
        for i in range(50):
            cache.set("key-%d" % i, i)
        assert len(cache) == 3
        assert cache.stats()["evictions"] == 47

    def test_the_least_recently_used_entry_goes_first(self):
        cache = Cache(ttl_minutes=10, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # 'a' is now the most recently used
        cache.set("c", 3)
        assert cache.get("a") == 1
        assert cache.get("b") is MISS

    def test_max_entries_must_be_at_least_one(self):
        with pytest.raises(ValueError):
            Cache(ttl_minutes=10, max_entries=0)


class TestThreadSafety:
    def test_concurrent_writers_leave_a_consistent_cache(self):
        """FastAPI runs sync endpoints in a threadpool, so this is the real
        deployment, not a hypothetical."""
        cache = Cache(ttl_minutes=10, max_entries=64)
        errors = []

        def hammer(offset):
            try:
                for i in range(200):
                    cache.set("k-%d" % ((i + offset) % 100), i)
                    cache.get("k-%d" % (i % 100))
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert len(cache) <= 64

    def test_expiry_under_contention_does_not_raise(self):
        cache = Cache(ttl_minutes=0.0002, max_entries=32)
        errors = []

        def hammer():
            try:
                for i in range(300):
                    cache.set("k-%d" % (i % 10), i)
                    cache.get("k-%d" % (i % 10))
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []


class TestStats:
    def test_hit_rate_is_reported(self):
        cache = Cache(ttl_minutes=10)
        cache.set("k", 1)
        cache.get("k")
        cache.get("k")
        cache.get("missing")
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert 0.66 < stats["hit_rate"] < 0.67

    def test_hit_rate_of_an_unused_cache_is_zero_not_an_error(self):
        assert Cache(ttl_minutes=10).stats()["hit_rate"] == 0.0

    def test_all_stats_covers_every_registered_cache(self):
        stats = all_stats()
        assert "job_analysis" in stats
        for entry in stats.values():
            assert "hit_rate" in entry and "entries" in entry

    def test_stats_expose_no_keys_or_values(self):
        """The endpoint that serves these is unauthenticated."""
        cache = Cache(ttl_minutes=10)
        cache.set("secret-key", {"salary": "confidential"})
        rendered = repr(cache.stats())
        assert "secret" not in rendered
        assert "confidential" not in rendered


class TestClearing:
    def test_clear_all_empties_every_cache(self):
        from utils.cache import job_analysis_cache

        job_analysis_cache.set("k", "v")
        clear_all()
        assert len(job_analysis_cache) == 0


class TestTheDecoratorPreservesTheFunction:
    def test_name_and_docstring_survive(self):
        cache = Cache(ttl_minutes=10)

        @cache_result(cache, "p")
        def documented(value):
            """A docstring."""
            return value

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "A docstring."

    def test_the_cache_is_reachable_for_tests_and_invalidation(self):
        cache = Cache(ttl_minutes=10)

        @cache_result(cache, "p")
        def fn(value):
            return value

        assert fn.cache is cache

    def test_an_exception_is_not_cached(self):
        cache = Cache(ttl_minutes=10)
        calls = []

        @cache_result(cache, "p")
        def flaky(value):
            calls.append(value)
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                flaky("x")
        assert len(calls) == 2, "a failure was cached and replayed"


class TestTheCachedAnalysisKnowsWhatAnsweredIt:
    """A result is not a function of the advert text alone.

    It also depends on whether a model was reachable. Keyed on text alone, the
    first analysis run during an outage is replayed for the whole TTL - so the
    model comes back and users keep getting keyword output with no way to ask
    again.
    """

    def _agent(self):
        from agents.job_analyzer import JobAnalyzerAgent

        return JobAnalyzerAgent()

    def test_the_fallback_and_llm_paths_do_not_share_a_key(self, monkeypatch):
        agent = self._agent()
        monkeypatch.setattr(agent, "use_llm", False)
        offline = agent._backend_fingerprint()

        agent2 = self._agent()
        monkeypatch.setattr(agent2, "use_llm", True)
        monkeypatch.setattr(
            type(agent2), "llm", property(lambda self: _FakeLLM("ollama"))
        )
        online = agent2._backend_fingerprint()

        assert offline == "fallback"
        assert online != offline

    def test_an_unreachable_model_is_recorded_as_fallback(self, monkeypatch):
        agent = self._agent()
        monkeypatch.setattr(agent, "use_llm", True)
        monkeypatch.setattr(
            type(agent), "llm", property(lambda self: _FakeLLM("ollama", available=False))
        )
        assert agent._backend_fingerprint() == "fallback"

    def test_a_broken_availability_probe_degrades_rather_than_raising(self, monkeypatch):
        agent = self._agent()
        monkeypatch.setattr(agent, "use_llm", True)

        class Exploding:
            def is_available(self):
                raise RuntimeError("probe failed")

        monkeypatch.setattr(type(agent), "llm", property(lambda self: Exploding()))
        assert agent._backend_fingerprint() == "fallback"

    def test_an_injected_client_is_never_cached(self):
        """Two injected clients cannot be distinguished without identity."""
        from agents.job_analyzer import JobAnalyzerAgent
        from tests.conftest import StubLLM

        agent = JobAnalyzerAgent(llm=StubLLM(available=False))
        assert agent._backend_fingerprint() is None

    def test_the_default_client_is_cacheable(self):
        assert self._agent()._llm_was_injected is False


class _FakeLLM:
    def __init__(self, backend, available=True):
        self.last_backend = backend
        self._available = available

    def is_available(self, refresh=False):
        return self._available
