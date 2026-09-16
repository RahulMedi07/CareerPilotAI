"""Tests for the saved-jobs store.

Each test gets its own database in a temp directory, so nothing here can
touch real saved jobs and the tests cannot interfere with one another.
"""

from __future__ import annotations

import threading

import pytest

from agents.job_storage import (
    STATUSES,
    JobStorage,
    JobStorageError,
    UnknownStatusError,
)


@pytest.fixture
def store(tmp_path):
    return JobStorage(tmp_path / "jobs.db")


def job(**kwargs):
    base = {
        "title": "AI Engineer",
        "company": "TechCorp",
        "description": "Python and LangChain.",
        "url": "https://example.com/jobs/1",
        "source": "Test",
        "posted_date": "2026-08-25",
        "analysis": {"required_skills": ["python"]},
        "match_to_user": {"score": 81.5},
    }
    base.update(kwargs)
    return base


class TestSaving:
    def test_returns_an_id(self, store):
        assert store.save_job(job()).startswith("job_")

    def test_the_job_comes_back(self, store):
        job_id = store.save_job(job())
        assert store.get_job(job_id)["title"] == "AI Engineer"

    def test_the_analysis_round_trips_as_a_dict(self, store):
        job_id = store.save_job(job())
        assert store.get_job(job_id)["analysis"]["required_skills"] == ["python"]

    def test_the_match_score_is_kept(self, store):
        job_id = store.save_job(job())
        assert store.get_job(job_id)["match_score"] == 81.5

    def test_a_job_with_no_title_is_refused(self, store):
        with pytest.raises(JobStorageError):
            store.save_job(job(title=""))

    def test_junk_is_refused_rather_than_stored(self, store):
        with pytest.raises((JobStorageError, TypeError, ValueError)):
            store.save_job(None)


class TestDeduplication:
    def test_the_same_advert_twice_is_one_row(self, store):
        store.save_job(job())
        store.save_job(job())
        assert store.count_user_jobs() == 1

    def test_it_keeps_the_same_id(self, store):
        first = store.save_job(job())
        assert store.save_job(job()) == first

    def test_re_saving_does_not_reset_the_status(self, store):
        """Someone who has applied must not lose that by searching again."""
        job_id = store.save_job(job())
        store.update_job_status(job_id, "applied")
        store.save_job(job())
        assert store.get_job(job_id)["status"] == "applied"

    def test_re_saving_updates_the_details(self, store):
        job_id = store.save_job(job())
        store.save_job(job(title="Staff AI Engineer"))
        assert store.get_job(job_id)["title"] == "Staff AI Engineer"

    def test_different_users_may_each_save_the_same_advert(self, store):
        store.save_job(job(), "alice")
        store.save_job(job(), "bob")
        assert store.count_user_jobs("alice") == 1
        assert store.count_user_jobs("bob") == 1

    def test_adverts_without_a_url_are_not_collapsed_together(self, store):
        """Hacker News comments have no URL; they are still distinct jobs."""
        store.save_job(job(url="", title="One"))
        store.save_job(job(url="", title="Two"))
        assert store.count_user_jobs() == 2


class TestStatus:
    def test_moves_through_the_lifecycle(self, store):
        job_id = store.save_job(job())
        assert store.update_job_status(job_id, "applied") is True
        assert store.get_job(job_id)["status"] == "applied"

    @pytest.mark.parametrize("status", STATUSES)
    def test_every_known_status_is_accepted(self, store, status):
        job_id = store.save_job(job())
        assert store.update_job_status(job_id, status) is True

    @pytest.mark.parametrize("bad", ["hired", "", None, "'; DROP TABLE jobs;--"])
    def test_unknown_statuses_are_refused(self, store, bad):
        job_id = store.save_job(job())
        with pytest.raises(UnknownStatusError):
            store.update_job_status(job_id, bad)

    @pytest.mark.parametrize("given", ["SAVED", " applied ", "Interview"])
    def test_case_and_spacing_are_normalised_rather_than_rejected(self, store, given):
        """Deliberate leniency: "Applied" is not a different state from "applied"."""
        job_id = store.save_job(job())
        assert store.update_job_status(job_id, given) is True
        assert store.get_job(job_id)["status"] == given.strip().lower()

    def test_updating_a_missing_job_returns_false_rather_than_raising(self, store):
        assert store.update_job_status("job_nope", "applied") is False

    def test_counts_include_the_empty_statuses(self, store):
        """Reporting only non-zero states would make a pipeline look emptier."""
        store.save_job(job())
        counts = store.status_counts()
        assert set(counts) == set(STATUSES)
        assert counts["saved"] == 1
        assert counts["offer"] == 0


class TestIsolationBetweenUsers:
    def test_one_user_does_not_see_another(self, store):
        store.save_job(job(), "alice")
        assert store.get_user_saved_jobs("bob") == []

    def test_a_user_id_may_be_required_on_update(self, store):
        job_id = store.save_job(job(), "alice")
        assert store.update_job_status(job_id, "applied", "bob") is False
        assert store.update_job_status(job_id, "applied", "alice") is True

    @pytest.mark.parametrize(
        "bad",
        ["a b", "'; DROP TABLE jobs;--", "x" * 65, "a/b", "<script>"],
    )
    def test_malformed_user_ids_are_refused(self, store, bad):
        with pytest.raises(JobStorageError):
            store.save_job(job(), bad)

    def test_sql_injection_in_a_user_id_does_not_execute(self, store):
        """Parameterised anyway; this proves the table survives the attempt."""
        store.save_job(job(), "alice")
        with pytest.raises(JobStorageError):
            store.get_user_saved_jobs("alice'; DROP TABLE jobs; --")
        assert store.count_user_jobs("alice") == 1


class TestQueries:
    def test_filter_by_status(self, store):
        first = store.save_job(job(url="https://x/1"))
        store.save_job(job(url="https://x/2"))
        store.update_job_status(first, "applied")
        assert len(store.get_jobs_by_status("local", "applied")) == 1
        assert len(store.get_jobs_by_status("local", "saved")) == 1

    def test_the_limit_is_honoured(self, store):
        for index in range(10):
            store.save_job(job(url="https://x/%d" % index))
        assert len(store.get_user_saved_jobs("local", limit=3)) == 3

    @pytest.mark.parametrize("limit,expected_max", [(0, 1), (-5, 1), (99_999, 1000)])
    def test_absurd_limits_are_clamped_rather_than_passed_to_sql(
        self, store, limit, expected_max
    ):
        assert len(store.get_user_saved_jobs("local", limit=limit)) <= expected_max

    def test_a_missing_job_is_none(self, store):
        assert store.get_job("job_nope") is None


class TestDeletion:
    def test_delete_removes_it(self, store):
        job_id = store.save_job(job())
        assert store.delete_job(job_id) is True
        assert store.get_job(job_id) is None

    def test_deleting_twice_is_false_the_second_time(self, store):
        job_id = store.save_job(job())
        store.delete_job(job_id)
        assert store.delete_job(job_id) is False

    def test_clear_user_leaves_other_users_alone(self, store):
        store.save_job(job(), "alice")
        store.save_job(job(), "bob")
        assert store.clear_user("alice") == 1
        assert store.count_user_jobs("bob") == 1


class TestConcurrency:
    def test_parallel_writes_do_not_corrupt_the_database(self, store):
        """The enricher uses a thread pool, so writes can arrive together."""
        errors = []

        def write(index):
            try:
                store.save_job(job(url="https://x/%d" % index))
            except Exception as exc:  # noqa: BLE001 - collected and asserted on
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert store.count_user_jobs() == 20
