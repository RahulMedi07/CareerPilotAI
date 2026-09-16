"""Tests for the six application-tracking endpoints.

The tracker is replaced with one pointing at a temp database, so these
exercise the HTTP layer -- status codes, validation, wiring, error mapping --
without touching real data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.application_analytics import ApplicationAnalytics
from agents.application_tracker import ApplicationTracker
from main import app

BASE = "/api/career"


@pytest.fixture
def client(monkeypatch, tmp_path):
    tracker = ApplicationTracker(tmp_path / "apps.db")
    analytics = ApplicationAnalytics(tracker=tracker)
    monkeypatch.setattr("agents.application_tracker.application_tracker", tracker)
    monkeypatch.setattr("agents.application_analytics.application_analytics", analytics)
    with TestClient(app) as test_client:
        yield test_client


def create(client, **kwargs):
    payload = {
        "job_id": "job_1",
        "analysis_data": {
            "job_title": "AI Engineer",
            "company": "TechCorp",
            "match_score": 78,
            "gaps_identified": ["LangGraph"],
        },
    }
    payload.update(kwargs)
    return client.post("%s/create-application" % BASE, json=payload)


class TestCreate:
    def test_creates_and_returns_an_id(self, client):
        response = create(client)
        assert response.status_code == 201
        assert response.json()["application_id"].startswith("app_")

    def test_job_id_is_required(self, client):
        assert client.post("%s/create-application" % BASE, json={}).status_code == 422

    def test_an_empty_job_id_is_refused(self, client):
        assert create(client, job_id="").status_code == 422

    def test_analysis_data_is_optional(self, client):
        response = client.post(
            "%s/create-application" % BASE, json={"job_id": "job_1"}
        )
        assert response.status_code == 201

    def test_an_unknown_status_is_a_400(self, client):
        assert create(client, status="banana").status_code == 400

    def test_a_malformed_user_id_in_the_body_is_ignored(self, client):
        """The body no longer chooses the owner, so its value cannot break it."""
        assert create(client, user_id="bad id!").status_code == 201

    def test_an_overlong_user_id_in_the_body_is_ignored(self, client):
        """It used to be refused by a length rule. Now there is no field to hit.

        The 422 this once asserted was validation doing its job on a field that
        chose the owner. That field is gone, so the request succeeds and the
        owner is the signed-in account either way.
        """
        assert create(client, user_id="x" * 200).status_code == 201


class TestUpdateStatus:
    def test_updates(self, client):
        app_id = create(client).json()["application_id"]
        response = client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "sent"}
        )
        assert response.status_code == 200
        assert response.json()["updated"] is True

    def test_unknown_application_is_a_404(self, client):
        response = client.post(
            "%s/application/app_nope/update-status" % BASE, json={"status": "sent"}
        )
        assert response.status_code == 404

    def test_unknown_status_is_a_400(self, client):
        app_id = create(client).json()["application_id"]
        response = client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "banana"}
        )
        assert response.status_code == 400

    def test_a_missing_status_is_a_422(self, client):
        app_id = create(client).json()["application_id"]
        response = client.post("%s/application/%s/update-status" % (BASE, app_id), json={})
        assert response.status_code == 422

    def test_accepts_the_briefs_own_example(self, client):
        """The brief passes "interview_scheduled", which is an event name."""
        app_id = create(client).json()["application_id"]
        response = client.post(
            "%s/application/%s/update-status" % (BASE, app_id),
            json={"status": "interview_scheduled", "details": {"interviewer": "John"}},
        )
        assert response.status_code == 200

    def test_the_change_is_visible_afterwards(self, client):
        app_id = create(client).json()["application_id"]
        client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "sent"}
        )
        history = client.get("%s/application/%s/history" % (BASE, app_id)).json()
        assert history["current_status"] == "sent"

    def test_a_body_user_id_cannot_redirect_the_update(self, client):
        """Sending someone else's id used to pick whose row was updated.

        It now updates the signed-in account's own application, because the
        id comes from the session. See test_auth.py for the matching check
        that a *real* second account still gets a 404.
        """
        app_id = create(client, user_id="me").json()["application_id"]
        response = client.post(
            "%s/application/%s/update-status" % (BASE, app_id),
            json={"status": "sent", "user_id": "someone_else"},
        )
        assert response.status_code == 200


class TestHistory:
    def test_returns_the_timeline(self, client):
        app_id = create(client).json()["application_id"]
        client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "sent"}
        )
        body = client.get("%s/application/%s/history" % (BASE, app_id)).json()
        assert body["job_title"] == "AI Engineer"
        assert body["company"] == "TechCorp"
        assert [entry["event"] for entry in body["timeline"]] == [
            "created",
            "application_sent",
        ]

    def test_unknown_application_is_a_404(self, client):
        assert client.get("%s/application/app_nope/history" % BASE).status_code == 404

    def test_includes_interviews(self, client):
        app_id = create(client).json()["application_id"]
        client.post(
            "%s/application/%s/update-status" % (BASE, app_id),
            json={"status": "interview_completed", "details": {"interviewer": "John"}},
        )
        body = client.get("%s/application/%s/history" % (BASE, app_id)).json()
        assert body["interviews"][0]["interviewer"] == "John"

    def test_carries_the_gaps(self, client):
        app_id = create(client).json()["application_id"]
        body = client.get("%s/application/%s/history" % (BASE, app_id)).json()
        assert body["gaps_identified"] == ["LangGraph"]


class TestMyApplications:
    def test_empty_to_begin_with(self, client):
        body = client.get("%s/my-applications" % BASE).json()
        assert body["total"] == 0
        assert body["applications"] == []

    def test_lists_what_was_created(self, client):
        create(client)
        create(client, job_id="job_2")
        assert client.get("%s/my-applications" % BASE).json()["total"] == 2

    def test_filters_by_status(self, client):
        app_id = create(client).json()["application_id"]
        create(client, job_id="job_2")
        client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "sent"}
        )
        body = client.get("%s/my-applications?status=sent" % BASE).json()
        assert body["total"] == 1

    def test_an_unknown_status_filter_is_a_400(self, client):
        assert client.get("%s/my-applications?status=banana" % BASE).status_code == 400

    def test_a_query_user_id_cannot_reach_another_account(self, client):
        """``?user_id=you`` used to read someone else's list. Now it is ignored."""
        create(client, user_id="me")
        body = client.get("%s/my-applications?user_id=you" % BASE).json()
        assert body["total"] == 1
        assert body["user_id"] == "local"

    def test_status_counts_come_back(self, client):
        create(client)
        counts = client.get("%s/my-applications" % BASE).json()["status_counts"]
        assert counts["draft"] == 1

    def test_a_silly_limit_is_refused(self, client):
        assert client.get("%s/my-applications?limit=100000" % BASE).status_code == 422


class TestAnalytics:
    def test_answers_with_no_history(self, client):
        body = client.get("%s/analytics" % BASE).json()
        assert body["metrics"]["total_applications"] == 0

    def test_a_rate_with_no_denominator_is_null_not_zero(self, client):
        """0% would be read as failure. Nothing has been measured."""
        body = client.get("%s/analytics" % BASE).json()
        assert body["metrics"]["interview_rate"] is None

    def test_refuses_to_forecast_from_nothing(self, client):
        body = client.get("%s/analytics" % BASE).json()
        assert body["prediction"]["offer_probability_next_month"] is None
        assert body["prediction"]["basis"]

    def test_reports_real_counts(self, client):
        app_id = create(client).json()["application_id"]
        client.post(
            "%s/application/%s/update-status" % (BASE, app_id), json={"status": "sent"}
        )
        body = client.get("%s/analytics" % BASE).json()
        assert body["metrics"]["applications_sent"] == 1

    def test_carries_the_sample_warning(self, client):
        create(client)
        body = client.get("%s/analytics" % BASE).json()
        assert body["metrics"]["sample_size_warning"]

    def test_includes_a_strategy(self, client):
        create(client)
        body = client.get("%s/analytics" % BASE).json()
        assert body["strategy"]["recommendations"]
        assert body["strategy"]["confidence"]


class TestDashboardRemoved:
    def test_the_endpoint_is_gone(self, client):
        """The screen it fed was removed before this audit; nothing called it.

        The agent behind it has since been deleted too, along with the job
        hunt pipeline that was its only remaining caller.
        """
        assert client.get("%s/dashboard" % BASE).status_code == 404
