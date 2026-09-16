"""Tests for the three job-discovery endpoints.

The scraper and the store are both replaced with local doubles, so these
tests exercise the HTTP layer -- status codes, validation, wiring -- without
touching the network or a real database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import main
from agents.job_scraper import JobScraper
from agents.job_storage import JobStorage

def _rss_date(days_ago: int) -> str:
    """A pubDate in the format a real feed sends."""
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return when.strftime("%a, %d %b %Y %H:%M:%S +0000")


#: One advert posted yesterday and one carrying no date at all.
#:
#: The date is relative rather than written out: discovery now shows only what
#: it can prove was posted in the last seven days, so a fixed date would make
#: this feed age out and take the whole file with it. The undated second item
#: is deliberate and must never appear in a result -- "no date" is not
#: evidence of being recent.
RSS_BODY = ("""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>TechCorp: Senior AI Engineer</title>
    <region>Remote</region>
    <description>Python, LangChain and Docker. 6+ years. $120,000 - $160,000.</description>
    <pubDate>%s</pubDate>
    <link>https://weworkremotely.com/jobs/1</link>
  </item>
  <item>
    <title>DataCo: Analyst</title>
    <region>Berlin</region>
    <description>SQL work.</description>
    <link>https://weworkremotely.com/jobs/2</link>
  </item>
</channel></rss>""" % _rss_date(1)).encode()


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """A scraper reading a canned feed and a store in a temp directory."""
    scraper = JobScraper(
        fetcher=lambda url: RSS_BODY,
        respect_robots=False,
        min_interval=0,
        cache_ttl=0,
    )
    scraper.sources = [("rss", scraper._fetch_rss)]
    monkeypatch.setattr("agents.job_scraper.job_scraper", scraper)
    monkeypatch.setattr(
        "agents.job_storage.job_storage", JobStorage(tmp_path / "jobs.db")
    )
    # No resume: keeps these tests independent of the ML stack.
    monkeypatch.setattr(main, "_resume_data_or_none", lambda indexer: None)
    main._DISCOVERED_JOBS.clear()
    yield
    main._DISCOVERED_JOBS.clear()


@pytest.fixture
def discovered(client, wired):
    """One completed discovery call, returning the parsed body.

    ``location`` is named rather than defaulted because the canned feed above
    is a remote board -- "Remote" and "Berlin". The endpoint now defaults to
    India, which is correct for the product and would filter this fixture down
    to nothing, testing the location filter instead of what these tests are
    for.
    """
    response = client.post(
        "/api/career/discover-jobs",
        json={"query": "python", "limit": 10, "location": "remote"},
    )
    assert response.status_code == 200
    return response.json()


class TestDiscover:
    def test_returns_jobs(self, discovered):
        assert discovered["total_found"] >= 1
        assert discovered["jobs"]

    def test_names_the_sources_it_used(self, discovered):
        assert "WeWorkRemotely" in discovered["sources_used"]

    def test_passes_on_the_attribution_terms(self, discovered):
        """At least one source requires credit as a condition of use."""
        assert discovered["attribution"]

    def test_says_plainly_that_nothing_was_scored(self, discovered):
        """With no resume indexed, a score would be invented."""
        assert discovered["scored_against_resume"] is False

    def test_every_job_carries_an_analysis(self, discovered):
        assert all("analysis" in job for job in discovered["jobs"])

    def test_every_job_carries_an_id(self, discovered):
        assert all(job["job_id"] for job in discovered["jobs"])

    def test_jobs_are_categorized(self, discovered):
        assert "counts" in discovered["categorized"]

    def test_the_limit_is_applied(self, client, wired):
        response = client.post(
            "/api/career/discover-jobs", json={"query": "", "limit": 1}
        )
        # An empty query is refused outright; use a real one.
        response = client.post(
            "/api/career/discover-jobs",
            json={"query": "e", "limit": 1, "location": "remote"},
        )
        assert len(response.json()["jobs"]) <= 1

    def test_india_is_the_default_place_to_look(self, client, wired):
        """The user of this app is looking for work in India.

        "remote" was the old default and means "no location constraint", which
        returned adverts nobody here can take. The canned feed is a remote
        board with nothing in India, so defaulting correctly empties it.
        """
        body = client.post(
            "/api/career/discover-jobs", json={"query": "python"}
        ).json()
        assert body["jobs"] == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"query": ""},
            {"query": "x", "limit": 0},
            {"query": "x", "limit": 999},
            {"query": "x" * 500},
        ],
    )
    def test_bad_input_is_refused(self, client, wired, payload):
        assert client.post("/api/career/discover-jobs", json=payload).status_code == 422

    def test_a_caller_cannot_name_a_url_to_fetch(self, client, wired):
        """The field does not exist; supplying it must not reach the fetcher.

        If this ever starts passing a URL through, the endpoint has become an
        open proxy onto the server's own network.
        """
        response = client.post(
            "/api/career/discover-jobs",
            json={"query": "x", "url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert response.status_code == 200
        assert "169.254" not in response.text

    def test_can_be_switched_off(self, client, wired, monkeypatch):
        monkeypatch.setattr(main.settings, "JOB_DISCOVERY_ENABLED", False)
        response = client.post("/api/career/discover-jobs", json={"query": "x"})
        assert response.status_code == 503

class TestFreshness:
    """The two-day window, and what happens when it finds nothing.

    The sources behind discovery are remote-first and largely US/EU facing,
    so "posted in India in the last two days" can legitimately match nothing.
    An empty page is indistinguishable from a broken search, so the window
    widens -- and every widening has to be said out loud, because a list
    quietly padded with month-old adverts is worse than a short one.
    """

    @staticmethod
    def _aged(*ages):
        today = datetime.now(timezone.utc).date()
        jobs = []
        for index, age in enumerate(ages):
            posted = "" if age is None else (today - timedelta(days=age)).isoformat()
            jobs.append(
                {
                    "job_id": "job_%d" % index,
                    "title": "Role %d" % index,
                    "posted_date": posted,
                    "days_old": age,
                }
            )
        return jobs

    def test_no_request_means_the_ceiling_still_applies(self):
        """Omitting the window must not mean "any age".

        The app promises jobs from the last seven days. A caller that leaves
        the field out gets that promise kept, not an unbounded list.
        """
        kept, used, note = main._apply_freshness(self._aged(0, 90), None)
        assert [job["days_old"] for job in kept] == [0]
        assert used == 7
        assert note is not None

    def test_a_satisfied_window_says_nothing(self):
        # Silence is the correct output when the user got what they asked
        # for. A note on every search would train people to ignore it.
        kept, used, note = main._apply_freshness(self._aged(0, 1, 2, 40), 2)
        assert len(kept) == 3
        assert used == 2
        assert note is None

    def test_a_thin_window_widens_to_the_ceiling_and_admits_it(self):
        kept, used, note = main._apply_freshness(self._aged(1, 5, 6, 7, 200), 2)
        assert used == 7
        assert len(kept) == 4
        assert note is not None
        assert "last 2 days" in note
        assert "7 days" in note

    def test_the_note_reports_the_real_count_from_the_narrow_window(self):
        _, _, note = main._apply_freshness(self._aged(1, 5, 6, 7), 2)
        assert "Only 1 advert(s)" in note

    def test_the_window_never_opens_past_seven_days(self):
        """The old code dropped the filter here and showed all three.

        Nothing in this list is inside a week, so the honest answer is an
        empty page with a reason. Three adverts between 100 and 300 days old,
        shown under a heading that says seven days, is the failure this
        ceiling exists to prevent.
        """
        kept, used, note = main._apply_freshness(self._aged(100, 200, 300), 2)
        assert kept == []
        assert used == 7
        assert "last 7 days" in note

    def test_a_request_wider_than_the_ceiling_is_cut_down_to_it(self):
        kept, used, note = main._apply_freshness(self._aged(1, 20, 200), 90)
        assert [job["days_old"] for job in kept] == [1]
        assert used == 7
        assert "last 7 days" in note

    def test_nothing_at_all_produces_no_false_reassurance(self):
        kept, used, note = main._apply_freshness([], 2)
        assert kept == []
        # The ceiling, not the 2 asked for: a wider retry could not help
        # either, and saying "last 2 days" would suggest it might.
        assert used == 7
        assert "last 7 days" in note

    def test_undated_adverts_are_never_shown(self):
        """"We do not know how old this is" is not "recent enough".

        There is no longer any path that admits them: the filter is never
        dropped, so an advert whose feed stated no date cannot appear.
        """
        kept, _, _ = main._apply_freshness(self._aged(0, 1, 2, None), 2)
        assert all(job["days_old"] is not None for job in kept)

        kept, used, _ = main._apply_freshness(self._aged(400, None), 2)
        assert kept == []
        assert used == 7

    def test_the_endpoint_reports_the_window_it_used(self, client, wired):
        response = client.post(
            "/api/career/discover-jobs",
            json={
                "query": "python",
                "limit": 10,
                "max_age_days": 2,
                "location": "remote",
            },
        )
        assert response.status_code == 200
        body = response.json()
        # Present in the contract whether or not it was widened, so the UI
        # never has to guess which window produced the list it is showing.
        assert "max_age_days_used" in body
        assert "freshness_note" in body
        assert "undated_count" in body

    def test_scoring_reads_the_callers_own_index(self, client, wired, monkeypatch):
        """Adverts are scored against *your* resume, not a shared collection.

        This was the one place discovery could still reach for the module-level
        ``resume_indexer``, which every account shares. If it did, one person's
        adverts would be scored against whichever resume happened to be sitting
        in the default collection.

        The spy records the indexer the endpoint handed over, so the assertion
        is about the wiring rather than about anything the ML stack computes.
        """
        sentinel = object()
        received = []

        main.app.dependency_overrides[main.get_indexer] = lambda: sentinel
        monkeypatch.setattr(
            main,
            "_resume_data_or_none",
            lambda indexer: received.append(indexer) or None,
        )
        try:
            response = client.post(
                "/api/career/discover-jobs",
                json={"query": "python", "limit": 1, "location": "remote"},
            )
        finally:
            main.app.dependency_overrides.pop(main.get_indexer, None)

        assert response.status_code == 200
        assert received == [sentinel]

    def test_the_resume_reader_takes_the_indexer_it_is_given(self):
        """``_resume_data_or_none`` must never import its own indexer."""

        class Stub:
            def is_empty(self):
                return False

            def get_full_context(self):
                return "Python, FastAPI, Postgres."

        assert main._resume_data_or_none(Stub()) == {
            "resume_text": "Python, FastAPI, Postgres."
        }

    def test_an_empty_index_scores_nothing_rather_than_zero(self):
        class Empty:
            def is_empty(self):
                return True

            def get_full_context(self):
                raise AssertionError("an empty index should not be read")

        assert main._resume_data_or_none(Empty()) is None


class TestSaveJob:
    def test_saves_a_discovered_job(self, client, discovered):
        job_id = discovered["jobs"][0]["job_id"]
        response = client.post("/api/career/save-job", json={"job_id": job_id})
        assert response.status_code == 200
        assert response.json()["saved"] is True
        assert response.json()["user_jobs_count"] == 1

    def test_saving_twice_does_not_duplicate(self, client, discovered):
        job_id = discovered["jobs"][0]["job_id"]
        client.post("/api/career/save-job", json={"job_id": job_id})
        second = client.post("/api/career/save-job", json={"job_id": job_id})
        assert second.json()["user_jobs_count"] == 1

    def test_an_unknown_id_is_a_404(self, client, wired):
        response = client.post("/api/career/save-job", json={"job_id": "job_nope"})
        assert response.status_code == 404

    def test_a_bad_user_id_in_the_body_is_ignored(self, client, discovered):
        """The body no longer chooses the owner, so its value cannot break it."""
        job_id = discovered["jobs"][0]["job_id"]
        response = client.post(
            "/api/career/save-job", json={"job_id": job_id, "user_id": "a b"}
        )
        assert response.status_code == 200

    def test_a_bad_status_is_refused(self, client, discovered):
        job_id = discovered["jobs"][0]["job_id"]
        response = client.post(
            "/api/career/save-job", json={"job_id": job_id, "status": "hired"}
        )
        assert response.status_code == 400


class TestMyJobs:
    def test_empty_to_begin_with(self, client, wired):
        response = client.get("/api/career/my-jobs")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_lists_what_was_saved(self, client, discovered):
        job_id = discovered["jobs"][0]["job_id"]
        client.post("/api/career/save-job", json={"job_id": job_id, "user_id": "alice"})
        response = client.get("/api/career/my-jobs", params={"user_id": "alice"})
        assert response.json()["total"] == 1

    def test_a_query_user_id_cannot_reach_another_account(self, client, discovered):
        """``?user_id=bob`` used to read a different list. Now it is ignored."""
        job_id = discovered["jobs"][0]["job_id"]
        client.post("/api/career/save-job", json={"job_id": job_id, "user_id": "alice"})
        response = client.get("/api/career/my-jobs", params={"user_id": "bob"})
        assert response.json()["total"] == 1
        assert response.json()["user_id"] == "local"

    def test_reports_counts_for_every_status(self, client, discovered):
        response = client.get("/api/career/my-jobs")
        assert "offer" in response.json()["status_counts"]

    def test_filtering_by_status(self, client, discovered):
        job_id = discovered["jobs"][0]["job_id"]
        client.post(
            "/api/career/save-job", json={"job_id": job_id, "status": "applied"}
        )
        assert client.get(
            "/api/career/my-jobs", params={"status": "applied"}
        ).json()["total"] == 1
        assert client.get(
            "/api/career/my-jobs", params={"status": "offer"}
        ).json()["total"] == 0

    def test_an_unknown_status_filter_is_a_400(self, client, wired):
        response = client.get("/api/career/my-jobs", params={"status": "hired"})
        assert response.status_code == 400

    def test_a_bad_user_id_in_the_query_is_ignored(self, client, wired):
        assert client.get(
            "/api/career/my-jobs", params={"user_id": "a b"}
        ).status_code == 200


class TestDiscoveredJobCache:
    def test_the_cache_is_bounded(self, wired):
        """A long-running server must not accumulate every advert it sees."""
        main._remember_jobs(
            [{"job_id": "job_%d" % index} for index in range(main.DISCOVERED_JOBS_LIMIT + 50)]
        )
        assert len(main._DISCOVERED_JOBS) == main.DISCOVERED_JOBS_LIMIT

    def test_the_oldest_go_first(self, wired):
        main._remember_jobs(
            [{"job_id": "job_%d" % index} for index in range(main.DISCOVERED_JOBS_LIMIT + 1)]
        )
        assert "job_0" not in main._DISCOVERED_JOBS
        assert "job_%d" % main.DISCOVERED_JOBS_LIMIT in main._DISCOVERED_JOBS
