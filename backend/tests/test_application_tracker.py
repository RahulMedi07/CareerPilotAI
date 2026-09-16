"""Tests for the application tracker.

Each test gets its own database in a temp directory, so nothing here touches
real applications and the tests cannot interfere with one another.
"""

from __future__ import annotations

import threading

import pytest

from agents.application_tracker import (
    APPLICATION_STATUSES,
    EVENTS,
    ApplicationError,
    ApplicationTracker,
    UnknownApplicationError,
    UnknownEventError,
    UnknownStatusError,
)


@pytest.fixture
def tracker(tmp_path):
    return ApplicationTracker(tmp_path / "apps.db")


def analysis(**kwargs):
    base = {
        "job_title": "AI Engineer",
        "company": "TechCorp",
        "match_score": 78,
        "gaps_identified": ["LangGraph", "Kubernetes"],
        "resume_version": "v2",
        "interview_prep_score": 60,
    }
    base.update(kwargs)
    return base


class TestCreating:
    def test_returns_an_id(self, tracker):
        assert tracker.create_application("me", "job_1", analysis()).startswith("app_")

    def test_ids_are_unique(self, tracker):
        first = tracker.create_application("me", "job_1", analysis())
        second = tracker.create_application("me", "job_1", analysis())
        assert first != second, "the same job applied to twice is two attempts"

    def test_stores_every_field_the_brief_names(self, tracker):
        app_id = tracker.create_application("me", "job_1", analysis())
        record = tracker.get_application(app_id)
        assert record["job_id"] == "job_1"
        assert record["match_score"] == 78
        assert record["gaps_identified"] == ["LangGraph", "Kubernetes"]
        assert record["resume_version_used"] == "v2"
        assert record["interview_prep_score"] == 60
        assert record["current_status"] == "draft"
        assert record["created_date"] and record["updated_date"]

    def test_defaults_to_draft(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.get_application(app_id)["current_status"] == "draft"

    def test_logs_a_creation_event_so_the_timeline_starts_at_the_start(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        timeline = tracker.get_application(app_id)["timeline"]
        assert [entry["event"] for entry in timeline] == ["created"]

    def test_requires_a_job_id(self, tracker):
        with pytest.raises(ApplicationError):
            tracker.create_application("me", "")

    def test_rejects_an_unknown_status(self, tracker):
        with pytest.raises(UnknownStatusError):
            tracker.create_application("me", "job_1", None, "banana")

    def test_rejects_a_malformed_user_id(self, tracker):
        with pytest.raises(ApplicationError):
            tracker.create_application("bad id!", "job_1")

    def test_works_with_no_analysis_at_all(self, tracker):
        """An application can be tracked before anything has been analysed."""
        record = tracker.get_application(tracker.create_application("me", "job_1"))
        assert record["match_score"] is None
        assert record["gaps_identified"] == []

    def test_an_absent_score_is_none_not_zero(self, tracker):
        """Zero and "not measured" are different facts."""
        app_id = tracker.create_application("me", "job_1", {"job_title": "X"})
        assert tracker.get_application(app_id)["match_score"] is None

    def test_a_real_zero_score_is_kept(self, tracker):
        app_id = tracker.create_application("me", "job_1", {"match_score": 0})
        assert tracker.get_application(app_id)["match_score"] == 0


class TestGapNormalisation:
    """Different stages spell gaps three ways; the tracker stores one."""

    @pytest.mark.parametrize(
        "raw",
        [
            ["LangGraph"],
            [{"skill": "LangGraph"}],
            [{"name": "LangGraph"}],
            [{"gap": "LangGraph"}],
            "LangGraph",
        ],
    )
    def test_every_shape_lands_as_a_name(self, tracker, raw):
        app_id = tracker.create_application("me", "job_1", {"gaps_identified": raw})
        assert tracker.get_application(app_id)["gaps_identified"] == ["LangGraph"]

    def test_reads_missing_skills_when_gaps_absent(self, tracker):
        app_id = tracker.create_application("me", "job_1", {"missing_skills": ["Docker"]})
        assert tracker.get_application(app_id)["gaps_identified"] == ["Docker"]

    def test_does_not_repeat_a_gap(self, tracker):
        app_id = tracker.create_application(
            "me", "job_1", {"gaps_identified": ["Docker", "Docker"]}
        )
        assert tracker.get_application(app_id)["gaps_identified"] == ["Docker"]


class TestEvents:
    def test_logs_an_event(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(app_id, "analysis_completed", {"score": 78})
        timeline = tracker.get_application(app_id)["timeline"]
        assert timeline[-1]["event"] == "analysis_completed"
        assert timeline[-1]["details"] == {"score": 78}

    def test_rejects_an_unknown_event(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        with pytest.raises(UnknownEventError):
            tracker.log_application_event(app_id, "went_for_a_walk")

    def test_rejects_an_unknown_application(self, tracker):
        with pytest.raises(UnknownApplicationError):
            tracker.log_application_event("app_nope", "analysis_completed")

    @pytest.mark.parametrize("event", EVENTS)
    def test_every_documented_event_is_accepted(self, tracker, event):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.log_application_event(app_id, event) > 0

    def test_events_keep_their_order(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        for event in ("analysis_completed", "resume_tailored", "application_sent"):
            tracker.log_application_event(app_id, event)
        assert [entry["event"] for entry in tracker.get_application(app_id)["timeline"]] == [
            "created",
            "analysis_completed",
            "resume_tailored",
            "application_sent",
        ]

    def test_the_log_is_append_only(self, tracker):
        """Nothing in the public surface can edit or remove an earlier event."""
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(app_id, "application_sent")
        before = tracker.get_application(app_id)["timeline"]
        tracker.update_application_status(app_id, "rejected")
        after = tracker.get_application(app_id)["timeline"]
        assert after[: len(before)] == before

    def test_details_survive_a_round_trip(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        payload = {"interviewer": "John", "difficulty": "HARD", "next_round": "True"}
        tracker.log_application_event(app_id, "interview_completed", payload)
        stored = tracker.get_application(app_id)["timeline"][-1]["details"]
        assert stored["interviewer"] == "John"
        assert stored["difficulty"] == "HARD"


class TestInterviews:
    def test_an_interview_event_records_an_interview(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(
            app_id,
            "interview_completed",
            {
                "interviewer": "John",
                "difficulty": "HARD",
                "performance": "GOOD",
                "next_round": "True",
            },
        )
        interviews = tracker.get_application(app_id)["interviews"]
        assert len(interviews) == 1
        assert interviews[0]["interviewer"] == "John"
        assert interviews[0]["performance_rating"] == "GOOD"

    def test_the_briefs_string_true_is_read_as_a_boolean(self, tracker):
        """The brief's own example passes the string "True", not a bool."""
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(
            app_id, "interview_completed", {"next_round": "True"}
        )
        assert tracker.get_application(app_id)["interviews"][0]["next_round"] is True

    @pytest.mark.parametrize("value", ["False", "no", "", None, False, 0])
    def test_anything_else_is_not_a_next_round(self, tracker, value):
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(
            app_id, "interview_completed", {"next_round": value}
        )
        assert tracker.get_application(app_id)["interviews"][0]["next_round"] is False

    def test_no_interviews_when_none_happened(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.get_application(app_id)["interviews"] == []


class TestStatus:
    def test_updates_and_reports(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.update_application_status(app_id, "sent") is True
        assert tracker.get_application(app_id)["current_status"] == "sent"

    def test_returns_false_for_an_unknown_application(self, tracker):
        assert tracker.update_application_status("app_nope", "sent") is False

    def test_rejects_an_unknown_status(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        with pytest.raises(UnknownStatusError):
            tracker.update_application_status(app_id, "banana")

    @pytest.mark.parametrize("status", APPLICATION_STATUSES)
    def test_every_documented_status_is_accepted(self, tracker, status):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.update_application_status(app_id, status) is True

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("interview_scheduled", "interview"),
            ("interview_completed", "interview"),
            ("offer_received", "offer"),
            ("applied", "sent"),
            ("application_sent", "sent"),
            ("INTERVIEW", "interview"),
            (" sent ", "sent"),
        ],
    )
    def test_accepts_the_synonyms_people_actually_pass(self, tracker, given, expected):
        """The brief's own example passes an event name where a status goes."""
        app_id = tracker.create_application("me", "job_1")
        tracker.update_application_status(app_id, given)
        assert tracker.get_application(app_id)["current_status"] == expected

    def test_the_word_the_caller_used_is_what_gets_logged(self, tracker):
        """"scheduled" and "completed" are both status=interview, and are not
        remotely the same fact."""
        app_id = tracker.create_application("me", "job_1")
        tracker.update_application_status(app_id, "interview_completed")
        assert tracker.get_application(app_id)["timeline"][-1]["event"] == (
            "interview_completed"
        )

    def test_a_status_change_always_leaves_an_event(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        tracker.update_application_status(app_id, "sent")
        timeline = tracker.get_application(app_id)["timeline"]
        assert timeline[-1]["event"] == "application_sent"
        assert timeline[-1]["status"] == "sent"

    def test_the_event_records_where_it_came_from(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        tracker.update_application_status(app_id, "sent")
        details = tracker.get_application(app_id)["timeline"][-1]["details"]
        assert details["from"] == "draft"
        assert details["to"] == "sent"

    def test_scoping_to_a_user_prevents_a_cross_namespace_update(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.update_application_status(app_id, "sent", None, "someone_else") is False
        assert tracker.get_application(app_id)["current_status"] == "draft"

    def test_an_interview_completed_status_also_records_the_interview(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        tracker.update_application_status(
            app_id, "interview_completed", {"interviewer": "Ada"}
        )
        assert tracker.get_application(app_id)["interviews"][0]["interviewer"] == "Ada"


class TestHistory:
    def test_empty_for_a_new_user(self, tracker):
        assert tracker.get_application_history("nobody") == []

    def test_returns_the_shape_the_brief_asks_for(self, tracker):
        app_id = tracker.create_application("me", "job_1", analysis())
        tracker.update_application_status(app_id, "sent")
        record = tracker.get_application_history("me")[0]
        assert record["job_title"] == "AI Engineer"
        assert record["company"] == "TechCorp"
        assert record["match_score"] == 78
        assert record["current_status"] == "sent"
        assert all({"date", "event", "status"} <= set(entry) for entry in record["timeline"])

    def test_newest_first(self, tracker):
        first = tracker.create_application("me", "job_1", {"job_title": "First"})
        second = tracker.create_application("me", "job_2", {"job_title": "Second"})
        ids = [record["app_id"] for record in tracker.get_application_history("me")]
        assert ids.index(second) < ids.index(first)

    def test_each_application_keeps_its_own_timeline(self, tracker):
        first = tracker.create_application("me", "job_1")
        second = tracker.create_application("me", "job_2")
        tracker.log_application_event(first, "application_sent")
        by_id = {record["app_id"]: record for record in tracker.get_application_history("me")}
        assert len(by_id[first]["timeline"]) == 2
        assert len(by_id[second]["timeline"]) == 1

    def test_users_are_separate(self, tracker):
        tracker.create_application("me", "job_1")
        tracker.create_application("you", "job_2")
        assert len(tracker.get_application_history("me")) == 1
        assert len(tracker.get_application_history("you")) == 1

    def test_respects_a_limit(self, tracker):
        for index in range(5):
            tracker.create_application("me", "job_%d" % index)
        assert len(tracker.get_application_history("me", limit=2)) == 2

    def test_a_silly_limit_is_clamped_not_obeyed(self, tracker):
        tracker.create_application("me", "job_1")
        assert len(tracker.get_application_history("me", limit=10 ** 9)) == 1

    def test_filters_by_status(self, tracker):
        first = tracker.create_application("me", "job_1")
        tracker.create_application("me", "job_2")
        tracker.update_application_status(first, "sent")
        sent = tracker.get_applications_by_status("me", "sent")
        assert [record["app_id"] for record in sent] == [first]

    def test_unknown_application_is_none(self, tracker):
        assert tracker.get_application("app_nope") is None

    def test_scoping_to_the_wrong_user_finds_nothing(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.get_application(app_id, "someone_else") is None


class TestCounts:
    def test_counts_applications(self, tracker):
        for index in range(3):
            tracker.create_application("me", "job_%d" % index)
        assert tracker.count_applications("me") == 3

    def test_status_counts_include_zeros(self, tracker):
        tracker.create_application("me", "job_1")
        counts = tracker.status_counts("me")
        assert set(counts) == set(APPLICATION_STATUSES)
        assert counts["draft"] == 1
        assert counts["offer"] == 0

    def test_counts_are_per_user(self, tracker):
        tracker.create_application("me", "job_1")
        assert tracker.count_applications("someone_else") == 0


class TestDeleting:
    def test_deletes(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.delete_application(app_id) is True
        assert tracker.get_application(app_id) is None

    def test_returns_false_when_absent(self, tracker):
        assert tracker.delete_application("app_nope") is False

    def test_events_go_with_it(self, tracker):
        """The cascade is declared in the schema; this proves it is switched on."""
        app_id = tracker.create_application("me", "job_1")
        tracker.log_application_event(app_id, "application_sent")
        tracker.delete_application(app_id)
        with tracker._connect() as connection:
            rows = connection.execute(
                "SELECT COUNT(*) AS n FROM application_events WHERE application_id = ?",
                (app_id,),
            ).fetchone()
        assert rows["n"] == 0

    def test_clear_user_removes_only_that_user(self, tracker):
        tracker.create_application("me", "job_1")
        tracker.create_application("you", "job_2")
        assert tracker.clear_user("me") == 1
        assert tracker.count_applications("you") == 1


class TestNotes:
    def test_adds_a_note(self, tracker):
        app_id = tracker.create_application("me", "job_1")
        assert tracker.add_note(app_id, "Referred by Sam") is True
        assert tracker.get_application(app_id)["notes"] == "Referred by Sam"

    def test_returns_false_when_absent(self, tracker):
        assert tracker.add_note("app_nope", "x") is False


class TestSafety:
    @pytest.mark.parametrize(
        "nasty",
        [
            "'; DROP TABLE applications; --",
            "1 OR 1=1",
            "me' UNION SELECT * FROM applications --",
        ],
    )
    def test_injection_in_a_user_id_is_rejected_not_executed(self, tracker, nasty):
        tracker.create_application("me", "job_1")
        with pytest.raises(ApplicationError):
            tracker.get_application_history(nasty)
        assert tracker.count_applications("me") == 1

    def test_injection_in_a_job_id_is_stored_as_text(self, tracker):
        app_id = tracker.create_application("me", "'; DROP TABLE applications; --")
        assert tracker.get_application(app_id)["job_id"] == "'; DROP TABLE applications; --"
        assert tracker.count_applications("me") == 1

    def test_injection_in_a_status_filter_is_rejected(self, tracker):
        with pytest.raises(UnknownStatusError):
            tracker.get_applications_by_status("me", "sent'; DROP TABLE applications; --")

    def test_survives_concurrent_writers(self, tracker):
        """It is called from a thread pool, so it has to survive one."""
        errors = []

        def worker(index):
            try:
                app_id = tracker.create_application("me", "job_%d" % index)
                tracker.log_application_event(app_id, "application_sent")
            except Exception as exc:  # noqa: BLE001 - the assertion is the point
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert tracker.count_applications("me") == 8
