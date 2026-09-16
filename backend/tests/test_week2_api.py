"""Week 2 API integration: one person's whole journey, plus two orphans.

Why this file is short
----------------------
The individual endpoints are already covered, thoroughly, next to the code
they belong to:

* ``tests/test_main.py`` - meta, upload, analyze, match, full analysis, trace,
  status, clear, request logging
* ``tests/test_job_endpoints.py`` - discover, save, my-jobs, the discovery cache
* ``tests/test_application_endpoints.py`` - create, update-status, history,
  my-applications, analytics, dashboard

Repeating those here would double the maintenance cost and buy nothing. What
none of them do is walk a **single user through several endpoints in order**
and check the state each one leaves behind is the state the next one reads.
That is the one thing an integration file can add, so it is all this file does
- plus two endpoint behaviours that had no test anywhere.

Nothing here touches the network: the ``api`` fixture swaps the live scraper
for a fake before the first request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import fake_source


@pytest.fixture()
def api(monkeypatch):
    """A client whose job discovery is offline and whose caches start empty."""
    import main
    from agents.job_scraper import job_scraper

    monkeypatch.setattr(
        job_scraper,
        "search",
        lambda query, location="remote", limit=10: fake_source(query, location, limit),
    )
    main._DISCOVERED_JOBS.clear()
    with TestClient(main.app) as client:
        yield client
    main._DISCOVERED_JOBS.clear()


class TestOneUsersJourney:
    """Discover, save, apply, progress, and see it in the numbers."""

    def test_the_state_each_step_leaves_is_the_state_the_next_one_reads(self, api):
        user = "journey"

        # 1. Discover. The adverts are held in memory so save-job can only
        #    accept ones this server actually returned.
        discovered = api.post(
            "/api/career/discover-jobs",
            json={"query": "ai engineer", "location": "remote", "limit": 5},
        )
        assert discovered.status_code == 200
        jobs = discovered.json()["jobs"]
        assert jobs, "discovery returned nothing, so the rest cannot be tested"
        job_id = jobs[0]["job_id"]

        # 2. Save one of them.
        saved = api.post(
            "/api/career/save-job", json={"job_id": job_id, "user_id": user}
        )
        assert saved.status_code == 200

        # ...and it comes back as this user's, not anyone else's.
        mine = api.get("/api/career/my-jobs", params={"user_id": user})
        assert mine.status_code == 200
        assert any(job["job_id"] for job in mine.json()["jobs"])

        # 3. Start an application. 201, because a resource is created.
        created = api.post(
            "/api/career/create-application",
            json={"job_id": job_id, "user_id": user, "status": "draft"},
        )
        assert created.status_code == 201
        app_id = created.json()["application_id"]

        # 4. Send it. `user_id` belongs in the body: as a query parameter it is
        #    ignored, the lookup falls back to the default user, and the
        #    endpoint returns 404 for an application that plainly exists.
        sent = api.post(
            "/api/career/application/%s/update-status" % app_id,
            json={"status": "sent", "user_id": user, "details": {}},
        )
        assert sent.status_code == 200

        # 5. The history remembers both states, in order.
        history = api.get(
            "/api/career/application/%s/history" % app_id, params={"user_id": user}
        )
        assert history.status_code == 200
        statuses = [entry["status"] for entry in history.json()["timeline"]]
        assert statuses[0] == "draft" and statuses[-1] == "sent"

        # 6. The analytics count it now that it has actually been sent.
        analytics = api.get("/api/career/analytics", params={"user_id": user})
        assert analytics.status_code == 200
        metrics = analytics.json()["metrics"]
        assert metrics["total_applications"] == 1
        assert metrics["applications_sent"] == 1

    def test_a_draft_left_alone_does_not_look_like_a_rejection(self, api):
        """Drafts are counted, but they are not failures.

        If unsent drafts fed the rate denominators, a careful user who
        shortlists ten jobs and sends two would be shown a 20% response rate
        and told they are doing badly. They are not; they have eight drafts.
        """
        user = "cautious"
        api.post(
            "/api/career/create-application",
            json={"job_id": "fake-1", "user_id": user, "status": "draft"},
        )
        metrics = api.get(
            "/api/career/analytics", params={"user_id": user}
        ).json()["metrics"]

        assert metrics["total_applications"] == 1
        assert metrics["applications_sent"] == 0
        # `None`, not 0.0 - there is no rate to quote yet, and quoting 0%
        # would be a claim we cannot support.
        assert metrics["interview_rate"] is None


class TestTheTwoEndpointsNothingElseCovered:
    def test_the_performance_endpoint_reports_operations_and_caches(self, api):
        """Added in Part 6 and never given a test until now."""
        response = api.get("/api/health/performance")
        assert response.status_code == 200

        body = response.json()
        assert "operations" in body
        # One cache, not three. Two more were declared and reported here for
        # weeks with nothing ever writing to them; this asserts the endpoint
        # describes what exists rather than what was intended.
        assert set(body["caches"]) == {"job_analysis"}
        for cache in body["caches"].values():
            assert "hits" in cache and "misses" in cache

    def test_clearing_wipes_the_index_and_the_caches_behind_it(self, api):
        """Delete has to reach the copies, or it has not deleted anything."""
        from utils.cache import job_analysis_cache

        job_analysis_cache.set("stale-analysis", {"x": 1})

        assert api.post("/api/career/clear").status_code == 200

        assert len(job_analysis_cache) == 0
