"""Week 2 integration tests: the seams between components.

Scope, and what is deliberately *not* here
------------------------------------------
Every component in this project already has its own test file, and those files
are thorough - the cache alone has its own suite. Re-asserting their contents
here would not add coverage; it would add a second place to update when
behaviour changes, and two copies of a fact drift apart. So this file only
holds tests that need **more than one component wired together**, where the
bug can only appear at the join:

* the seven-agent workflow producing a coherent result end to end
* an agent's exception surviving the trip out through HTTP with the right
  status and without leaking its text
* a cache hit not breaking the *next* call into the same agent
* clearing the index actually clearing the caches behind it

Single-component behaviour lives with its component:
``tests/test_cache.py``, ``tests/test_job_scraper.py``,
``tests/test_application_tracker.py``, ``tests/test_application_analytics.py``.

Placement
---------
In ``tests/`` rather than at the backend root on purpose. ``pytest.ini`` sets
``testpaths = tests``, so a file at the root is only collected when named
explicitly - it would sit out every ordinary ``pytest`` run, which is the
opposite of what an integration suite is for. The root-level ``test_week1.py``
and friends are runnable demo scripts, not pytest modules.
"""

from __future__ import annotations

import pytest

from tests.conftest import SAMPLE_JD, SAMPLE_RESUME


class TestTheWholePipeline:
    """All seven agents, one call, one coherent answer."""

    def test_the_complete_workflow_runs_every_stage(self):
        from agents.complete_workflow import complete_workflow

        result = complete_workflow.run_complete_analysis(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD
        )

        # The brief asserts `status == 'success'`. The workflow reports
        # 'completed'; 'success' is not one of its states. Asserting the
        # sketched value would fail against working code.
        assert result["status"] == "completed"

        # Likewise the key names: this pipeline returns `match_result` and
        # `resume_optimizations`, not `match` and `optimizations`.
        for key in (
            "match_result",
            "gaps",
            "resume_optimizations",
            "interview_prep",
            "learning_plan",
            "recommendation",
            "execution_trace",
        ):
            assert key in result, "missing %s" % key

    def test_a_learning_plan_key_is_always_present_even_when_empty(self):
        """Present-but-null and absent are different, and callers read this.

        A plan is only generated when the gaps are learnable in the time a
        real advert stays open. When they are not, the key stays and the value
        is ``None`` rather than the key vanishing, so a frontend can tell
        "no plan needed" from "this pipeline is an older version".
        """
        from agents.complete_workflow import complete_workflow

        result = complete_workflow.run_complete_analysis(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD
        )
        assert "learning_plan" in result

    def test_the_trace_records_what_ran_and_what_was_skipped(self):
        from agents.complete_workflow import complete_workflow

        result = complete_workflow.run_complete_analysis(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD
        )
        # `nodes_run` is the list of node names, not a count.
        assert len(result["nodes_run"]) > 0
        assert result["nodes_failed"] == []
        assert isinstance(result["path"], list) and result["path"]

    def test_the_linear_and_branching_runs_agree_on_the_score(self):
        """Changing the engine underneath must not change the contract."""
        from agents.complete_workflow import complete_workflow

        branching = complete_workflow.run_complete_analysis(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD, advanced=True
        )
        linear = complete_workflow.run_complete_analysis(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JD, advanced=False
        )
        assert branching["match_score"] == linear["match_score"]

    def test_an_empty_run_is_reported_not_raised(self):
        from agents.complete_workflow import complete_workflow

        result = complete_workflow.run_complete_analysis()
        assert result["status"] != "completed"
        assert "trace" in result


class TestFailuresSurviveTheTripOutThroughHttp:
    """The brief expects `analyze("")` to return `{'status': 'validation_error'}`.

    It raises. That was a deliberate decision in Part 5 and is still the right
    one: an empty advert is a caller mistake, and returning a dictionary that
    *looks* like an analysis means every caller must remember to check a status
    field before reading `required_skills`. The ones that forget get a
    confusing `KeyError` far from the cause. The exception carries the same
    information and cannot be ignored by accident. `main.py` turns it into a
    422 at the boundary, which is where an HTTP status belongs.
    """

    def test_an_empty_advert_raises_rather_than_returning_a_status_field(self):
        from agents.job_analyzer import JobAnalyzerAgent
        from utils.error_handling import CareerPilotException

        with pytest.raises(CareerPilotException):
            JobAnalyzerAgent().analyze("")

    def test_the_api_turns_that_into_a_422_not_a_500(self, client):
        response = client.post("/api/career/analyze-job", json={"job_description": ""})
        assert response.status_code == 422

    def test_an_unexpected_failure_returns_a_reference_not_a_stack_trace(
        self, monkeypatch
    ):
        from fastapi.testclient import TestClient

        import main
        from agents.job_analyzer import job_analyzer_agent

        def explode(*args, **kwargs):
            raise RuntimeError("database on fire: user=admin password=hunter2")

        monkeypatch.setattr(job_analyzer_agent, "analyze", explode)
        # `raise_server_exceptions=False` makes the client behave like a real
        # HTTP caller. The default re-raises inside the test process, which
        # tests the exception rather than the response the user would get.
        with TestClient(main.app, raise_server_exceptions=False) as probe:
            response = probe.post(
                "/api/career/analyze-job", json={"job_description": SAMPLE_JD}
            )
        assert response.status_code == 500
        body = response.text
        assert "hunter2" not in body, "the exception text leaked to the caller"
        assert "on fire" not in body

    def test_every_agent_failure_is_a_careerpilot_exception(self):
        """One family, so a caller can catch the lot without listing them."""
        from agents.job_analyzer import EmptyJobDescriptionError
        from utils.error_handling import CareerPilotException

        assert issubclass(EmptyJobDescriptionError, CareerPilotException)


class TestTheCacheDoesNotBreakItsNeighbours:
    """A cache is a correctness surface, not only a speed one.

    ``tests/test_cache.py`` covers the cache itself. These two cover what it
    touches: the agent whose state a cache hit skips past, and the delete
    button that has to reach it.
    """

    def test_a_cache_hit_does_not_break_the_follow_up_call(self):
        """`extract_requirements()` reads state that a cache hit skips past.

        Caching `analyze()` whole - which is what the brief sketched - means a
        hit never runs the body, so the agent's remembered advert is never set,
        and the very next `extract_requirements()` raises "call analyze()
        first" immediately after a successful `analyze()`.
        """
        from agents.job_analyzer import JobAnalyzerAgent

        agent = JobAnalyzerAgent()
        agent.analyze(SAMPLE_JD)
        agent.analyze(SAMPLE_JD)  # served from cache
        assert agent.extract_requirements()["required_skills"]

    def test_clearing_the_index_clears_the_caches(self, client):
        """A cache that survives the delete button is a copy of deleted data."""
        from utils.cache import job_analysis_cache

        job_analysis_cache.set("leftover", {"stale": True})
        client.post("/api/career/clear")
        assert len(job_analysis_cache) == 0
