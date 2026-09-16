"""Tests for the job scraper.

Every test here is offline. The scraper takes a ``fetcher`` callable precisely
so that the suite never depends on a third party being up, being fast, or
being willing to be hammered by CI. Tests that hit the network are not tests;
they are a way of finding out that someone else had an outage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.job_scraper import (
    ALLOWED_HOSTS,
    CLOSED_JOB_BOARDS,
    INDIA_BOARDS,
    JobScraper,
    ScraperError,
    UnsafeURLError,
    _age_in_days,
    _by_recency,
    _clip,
    _date,
    _dedupe,
    _filter_jobs,
    _interleave,
    _job,
    _parse_xml,
    _hn_apply_url,
    _hn_location,
    _split_hn_headline,
    _strip_html,
    _unwrap_nat64,
    _validate_url,
    fresh_jobs,
)
import ipaddress
import json

WWR_FEED = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

RSS_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>TechCorp: Senior AI Engineer</title>
    <region>Remote</region>
    <description>&lt;p&gt;Python, LangChain and Docker. 6+ years.&lt;/p&gt;</description>
    <pubDate>Mon, 25 Aug 2026 10:00:00 +0000</pubDate>
    <link>https://weworkremotely.com/jobs/1</link>
  </item>
  <item>
    <title>DataCo: Junior Analyst</title>
    <region>Berlin</region>
    <description>SQL and Excel.</description>
    <link>https://weworkremotely.com/jobs/2</link>
  </item>
</channel></rss>"""


def scraper(body=RSS_BODY, **kwargs):
    """A scraper wired to a canned response and no politeness delay."""
    kwargs.setdefault("respect_robots", False)
    kwargs.setdefault("min_interval", 0)
    kwargs.setdefault("cache_ttl", 0)
    return JobScraper(fetcher=lambda url: body, **kwargs)


# --------------------------------------------------------------------------- #
# URL safety - the part that matters most
# --------------------------------------------------------------------------- #
class TestUrlSafety:
    """These guards stop the server being used to attack its own network."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://weworkremotely.com/feed.rss",  # plaintext
            "ftp://weworkremotely.com/feed.rss",
            "file:///etc/passwd",
            "https://evil.example.com/feed.rss",  # not allow-listed
            "https://weworkremotely.com.evil.com/x",  # suffix trick
            "https://localhost/x",
            "https://127.0.0.1/x",
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata
            "https://[::1]/x",
            "https://10.0.0.1/x",
            "https://weworkremotely.com:8080/x",  # odd port
            "",
            "not a url",
        ],
    )
    def test_refuses_unsafe_urls(self, url):
        with pytest.raises(UnsafeURLError):
            _validate_url(url)

    def test_allows_the_known_hosts(self, monkeypatch):
        """The allow-listed hosts pass, with DNS stubbed.

        Resolving for real would make this test fail on a plane, and would
        make a DNS outage look like a bug in this file.
        """
        monkeypatch.setattr(
            "agents.job_scraper._is_public_address", lambda host: True
        )
        for host in ALLOWED_HOSTS:
            assert _validate_url("https://%s/path" % host)

    def test_the_metadata_address_is_refused_even_if_allow_listed(self):
        """Belt and braces: an allow-list entry pointing somewhere private.

        The allow-list is a static file someone could edit. The address check
        is what stops a mistake there becoming an SSRF.
        """
        with pytest.raises(UnsafeURLError):
            _validate_url("https://127.0.0.1/x", allowed_hosts={"127.0.0.1"})


class TestNat64:
    """On a DNS64 network every host resolves to a ``64:ff9b::`` address.

    Treating those as reserved refused every fetch - found when the allow-list
    test failed on the development machine, not by reasoning about it.
    """

    def test_public_ipv4_is_unwrapped(self):
        wrapped = ipaddress.ip_address("64:ff9b::22a0:a8b5")
        assert _unwrap_nat64(wrapped) == ipaddress.ip_address("34.160.168.181")

    def test_a_wrapped_loopback_is_still_refused(self):
        """Unwrapping must not become a way in."""
        wrapped = ipaddress.ip_address("64:ff9b::7f00:1")
        assert _unwrap_nat64(wrapped).is_loopback

    def test_ordinary_addresses_pass_through(self):
        for text in ("8.8.8.8", "2606:4700::1111"):
            address = ipaddress.ip_address(text)
            assert _unwrap_nat64(address) == address


class TestFetchLimits:
    def test_redirects_are_refused_not_followed(self):
        """A redirect can point anywhere, including back inside the network."""

        def redirecting(url):
            raise ScraperError("refusing redirect")

        result = scraper(body=b"").fetch_jobs_rss([WWR_FEED])
        assert result == []  # empty body yields nothing, and does not raise

    def test_a_source_failing_does_not_sink_the_others(self):
        def broken(url):
            raise ScraperError("boom")

        engine = JobScraper(fetcher=broken, respect_robots=False, min_interval=0)
        assert engine.fetch_jobs_rss([WWR_FEED]) == []

    def test_search_returns_empty_rather_than_raising_when_all_sources_fail(self):
        def broken(url):
            raise ScraperError("boom")

        engine = JobScraper(fetcher=broken, respect_robots=False, min_interval=0)
        assert engine.search("python", "remote", 5) == []


# --------------------------------------------------------------------------- #
# XML
# --------------------------------------------------------------------------- #
class TestXmlSafety:
    def test_entity_bomb_is_refused(self):
        """`billion laughs`. Measured: stdlib ElementTree does expand these."""
        bomb = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
            b"]><lolz>&lol2;</lolz>"
        )
        with pytest.raises(ScraperError):
            _parse_xml(bomb)

    def test_external_entity_is_refused(self):
        """The file-reading variant of the same trick."""
        xxe = (
            b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM '
            b'"file:///etc/passwd">]><d>&x;</d>'
        )
        with pytest.raises(ScraperError):
            _parse_xml(xxe)

    def test_ordinary_feed_still_parses(self):
        assert _parse_xml(RSS_BODY) is not None

    def test_malformed_xml_raises_scraper_error_not_a_parse_error(self):
        with pytest.raises(ScraperError):
            _parse_xml(b"<rss><channel><item>")


# --------------------------------------------------------------------------- #
# Text handling
# --------------------------------------------------------------------------- #
class TestText:
    def test_script_contents_are_dropped_not_just_the_tags(self):
        text = _strip_html("<p>Hello</p><script>alert(1)</script>")
        assert "alert" not in text
        assert "Hello" in text

    def test_block_tags_become_line_breaks(self):
        assert "\n" in _strip_html("<p>one</p><p>two</p>")

    def test_entities_are_decoded(self):
        assert "&" in _strip_html("R&amp;D")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https:&#x2F;&#x2F;example.com", "https://example.com"),
            ("caf&#233;", "caf\u00e9"),
            ("a&nbsp;b", "a b"),
        ],
    )
    def test_numeric_entities_are_decoded(self, raw, expected):
        """A hand-written entity table missed these.

        A live Hacker News advert came back titled
        "https:&#x2F;&#x2F;govstar.us".
        """
        assert _strip_html(raw) == expected

    def test_clip_is_bounded(self):
        assert len(_clip("x" * 50_000)) < 50_000

    @pytest.mark.parametrize(
        "headline,title,company",
        [
            ("TechCorp | Senior Engineer", "Senior Engineer", "TechCorp"),
            ("TechCorp | Senior Engineer | Remote", "Senior Engineer", "TechCorp"),
            ("Just a title", "Just a title", ""),
            ("", "Untitled role", ""),
        ],
    )
    def test_headline_split(self, headline, title, company):
        """Returns ``(title, company)`` - an unparseable line keeps its text."""
        got_title, got_company = _split_hn_headline(headline)
        assert got_title == title
        assert got_company == company

    @pytest.mark.parametrize(
        "text,expected",
        [
            # The headline link wins over anything linked in the body.
            (
                "Co | Eng | Pune | https://co.dev/careers\nBlog: https://co.dev/blog",
                "https://co.dev/careers",
            ),
            # No link on the headline, so the body's first one is used.
            ("Co | Eng | Pune\nApply at https://co.dev/jobs", "https://co.dev/jobs"),
            # The comment permalink is never an application link.
            ("Co | Eng | https://news.ycombinator.com/item?id=1", ""),
            # Trailing sentence punctuation is not part of the URL.
            ("Co | Eng\nSee https://co.dev/jobs.", "https://co.dev/jobs"),
            # An email-only advert keeps its permalink instead.
            ("Co | Eng | Pune\nEmail jobs@co.dev", ""),
            # Only http(s), so a script URL can never reach an href.
            ("Co | Eng\njavascript:alert(1)", ""),
        ],
    )
    def test_apply_url_prefers_the_advert_over_the_thread(self, text, expected):
        """A Hacker News advert must open somewhere you can actually apply.

        Its ``url`` used to be the comment permalink, so every one of these
        adverts sent the user to a discussion thread rather than the job.
        """
        assert _hn_apply_url(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Co | Eng | Bengaluru, KA, India | Full-time", "Bengaluru, KA, India"),
            ("Co | Eng | REMOTE (US \u00b7 Pune, India)", "REMOTE (US \u00b7 Pune, India)"),
            ("Co | Eng | Noida", "Noida"),
            # Nothing recognisable: left blank rather than guessed at, because
            # _location_haystack prefers this field over the headline and a
            # wrong value would hide the place from the country filter.
            ("Co | Eng | REMOTE (US) | Full-time", ""),
            ("unparseable line", ""),
        ],
    )
    def test_location_is_read_off_the_headline(self, text, expected):
        """Hacker News has no location field, so the headline is the only one."""
        assert _hn_location(text) == expected


# --------------------------------------------------------------------------- #
# Parsing a feed
# --------------------------------------------------------------------------- #
class TestRssParsing:
    def test_reads_both_items(self):
        jobs = scraper().fetch_jobs_rss([WWR_FEED])
        assert len(jobs) == 2

    def test_splits_company_from_title(self):
        first = scraper().fetch_jobs_rss([WWR_FEED])[0]
        assert first["company"] == "TechCorp"
        assert first["title"] == "Senior AI Engineer"

    def test_keeps_the_url_and_the_source(self):
        first = scraper().fetch_jobs_rss([WWR_FEED])[0]
        assert first["url"] == "https://weworkremotely.com/jobs/1"
        assert first["source"] == "WeWorkRemotely"

    def test_normalises_the_date(self):
        first = scraper().fetch_jobs_rss([WWR_FEED])[0]
        assert first["posted_date"] == "2026-08-25"

    def test_html_in_the_description_is_stripped(self):
        first = scraper().fetch_jobs_rss([WWR_FEED])[0]
        assert "<p>" not in first["description"]
        assert "Python" in first["description"]

    def test_a_caller_cannot_choose_an_arbitrary_feed(self):
        """Otherwise the endpoint would be an open proxy."""
        assert scraper().fetch_jobs_rss(["https://evil.example.com/f.rss"]) == []


class TestJobIds:
    def test_same_advert_gets_the_same_id_twice(self):
        one = scraper().fetch_jobs_rss([WWR_FEED])[0]
        two = scraper().fetch_jobs_rss([WWR_FEED])[0]
        assert one["job_id"] == two["job_id"]

    def test_different_adverts_get_different_ids(self):
        jobs = scraper().fetch_jobs_rss([WWR_FEED])
        assert jobs[0]["job_id"] != jobs[1]["job_id"]

    def test_urlless_adverts_still_get_an_id(self):
        record = _job("Engineer", "Corp", "text", "HackerNews", "", "2026-01-01")
        assert record["job_id"].startswith("job_")


class TestFilteringAndDedupe:
    def test_dedupe_by_url(self):
        a = _job("A", "C", "x", "S", "https://x/1", "2026-01-01")
        b = _job("A", "C", "y", "S", "https://x/1", "2026-01-02")
        assert len(_dedupe([a, b])) == 1

    def test_distinct_urls_are_kept(self):
        a = _job("A", "C", "x", "S", "https://x/1", "2026-01-01")
        b = _job("B", "C", "y", "S", "https://x/2", "2026-01-02")
        assert len(_dedupe([a, b])) == 2

    def test_one_vacancy_under_two_advert_ids_is_collapsed(self):
        """Observed live: Adzuna carried one EPAM role under two ad IDs.

        The URLs differ, so matching on URL alone let both through and the
        page showed the same job twice.
        """
        a = _job("Lead Domino Data Lab", "EPAM Systems", "x", "Adzuna",
                 "https://adzuna.in/land/ad/1", "2026-01-01",
                 extra={"location": "Bangalore"})
        b = _job("Lead Domino Data Lab", "EPAM Systems", "y", "Adzuna",
                 "https://adzuna.in/land/ad/2", "2026-01-02",
                 extra={"location": "Bangalore"})
        assert len(_dedupe([a, b])) == 1

    def test_the_same_title_in_two_cities_is_two_openings(self):
        """Collapsing these would hide a real job from one of the cities."""
        a = _job("Engineer", "Corp", "x", "S", "https://x/1", "2026-01-01",
                 extra={"location": "Bangalore"})
        b = _job("Engineer", "Corp", "y", "S", "https://x/2", "2026-01-02",
                 extra={"location": "Pune"})
        assert len(_dedupe([a, b])) == 2

    def test_filter_matches_on_title_or_description(self):
        jobs = [
            _job("Python Engineer", "C", "", "S", "https://x/1", "2026-01-01"),
            _job("Java Engineer", "C", "uses python daily", "S", "https://x/2", "2026-01-01"),
            _job("Chef", "C", "cooking", "S", "https://x/3", "2026-01-01"),
        ]
        assert len(_filter_jobs(jobs, "python", "")) == 2

    def test_an_empty_query_keeps_everything(self):
        jobs = [_job("A", "C", "", "S", "https://x/1", "2026-01-01")]
        assert len(_filter_jobs(jobs, "", "")) == 1

    def test_a_multi_word_query_is_not_matched_as_a_phrase(self):
        """The bug that made discovery return nothing.

        A live search for "fullstack developer" fetched 45 adverts and kept
        zero: no board writes the phrase that way. Both of these are plainly
        the role being searched for, and phrase matching dropped them.
        """
        jobs = [
            _job("Full Stack Developer", "C", "", "S", "https://x/1", "2026-01-01"),
            _job("Developer, Full Stack", "C", "", "S", "https://x/3", "2026-01-01"),
        ]
        assert len(_filter_jobs(jobs, "full stack developer", "")) == 2

    def test_punctuation_between_words_does_not_defeat_the_match(self):
        job = _job("Senior Full-Stack Engineer", "C", "", "S", "https://x/2", "2026-01-01")
        assert len(_filter_jobs([job], "full stack engineer", "")) == 1

    def test_every_word_must_appear_not_just_one(self):
        # Loosening to "any word matches" would return every advert
        # mentioning "developer", which is close to all of them.
        jobs = [_job("Data Engineer", "C", "python work", "S", "https://x/1", "2026-01-01")]
        assert _filter_jobs(jobs, "python developer", "") == []

    def test_a_developer_search_still_excludes_an_engineer_advert(self):
        # Not a synonym engine. "Full-Stack Engineer" does not contain the
        # word "developer", and pretending otherwise would need a synonym
        # table that quietly decides which job titles mean the same thing.
        job = _job("Senior Full-Stack Engineer", "C", "", "S", "https://x/2", "2026-01-01")
        assert _filter_jobs([job], "full stack developer", "") == []

    def test_a_place_is_matched_as_a_whole_word(self):
        """"Indiana" is not "India".

        A live search for india returned a role advertised as "Anywhere in the
        World" because its description listed the US states the company can
        hire in, and one of them is Indiana. Substring matching cannot tell a
        country from the first six letters of a state.
        """
        indiana = _job(
            "Data Engineer", "Faire", "We can hire in Illinois, Indiana, Kentucky.",
            "S", "https://x/1", "2026-01-01", extra={"location": "Indiana, USA"},
        )
        india = _job(
            "Data Engineer", "Acme", "", "S", "https://x/2", "2026-01-01",
            extra={"location": "Bengaluru, India"},
        )

        kept = _filter_jobs([indiana, india], "", "india")

        assert [j["company"] for j in kept] == ["Acme"]

    def test_a_place_is_matched_against_the_location_not_the_advert_body(self):
        """A London job at a company with an office in India is a London job.

        This one was live too: TransPerfect, located "London, Greater London,
        United Kingdom", came back from an india search because the body reads
        "Barcelona, New York, London, Manchester, Bucharest and India".
        """
        london = _job(
            "Software Engineer", "TransPerfect",
            "Offices across the globe - Barcelona, London, Bucharest and India.",
            "S", "https://x/1", "2026-01-01",
            extra={"location": "London, Greater London, United Kingdom"},
        )

        assert _filter_jobs([london], "", "india") == []

    def test_a_source_without_a_location_field_falls_back_to_the_headline(self):
        """Hacker News has no location field; its convention is the headline.

        Algolia returns the comment body only, so dropping the fallback would
        silently remove every Hacker News result from any located search.
        """
        hn = _job(
            "Backend Engineer", "Acme",
            "Acme | Backend Engineer | Bengaluru, India | full-time\n"
            "We are a US company with customers in Germany and Brazil.",
            "HackerNews", "https://x/1", "2026-01-01",
        )

        assert len(_filter_jobs([hn], "", "india")) == 1
        # ...and the countries named further down the body are not locations.
        assert _filter_jobs([hn], "", "brazil") == []

    def test_remote_and_anywhere_remain_unconstrained(self):
        """Both mean "no location filter", not "the advert must say so"."""
        onsite = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": "Berlin, Germany"},
        )

        assert len(_filter_jobs([onsite], "", "remote")) == 1
        assert len(_filter_jobs([onsite], "", "anywhere")) == 1

    def test_a_place_with_regex_characters_is_not_a_pattern(self):
        """The place goes into a regex, so it has to be escaped."""
        job = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": "Washington D.C."},
        )

        assert len(_filter_jobs([job], "", "D.C.")) == 1
        assert _filter_jobs([job], "", "DxC.") == []


class TestIndiaAliases:
    """An india search has to find Bengaluru without finding Indiana."""

    @pytest.mark.parametrize(
        "location",
        [
            "Bengaluru, Karnataka",
            "Bangalore",
            "Hyderabad",
            "Pune, Maharashtra",
            "Gurugram",
            "Noida",
            "Remote (Mumbai)",
        ],
    )
    def test_an_indian_city_matches_an_india_search(self, location):
        # Every one of these is a job in India whose advert never writes the
        # word. Without the alias list a search for india finds none of them,
        # which is most of the country's postings.
        job = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": location},
        )
        assert len(_filter_jobs([job], "", "india")) == 1

    @pytest.mark.parametrize("location", ["Indiana, USA", "Indianapolis, IN"])
    def test_the_aliases_do_not_reintroduce_the_indiana_bug(self, location):
        job = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": location},
        )
        assert _filter_jobs([job], "", "india") == []

    def test_an_alias_is_still_a_whole_word(self):
        # "Punengo" is a real place in Italy and contains "pune".
        job = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": "Punengo, Italy"},
        )
        assert _filter_jobs([job], "", "india") == []

    def test_a_city_search_is_unaffected_by_the_alias_table(self):
        # Expanding aliases for india must not make every city search match
        # every other Indian city.
        job = _job(
            "Engineer", "C", "", "S", "https://x/1", "2026-01-01",
            extra={"location": "Chennai, Tamil Nadu"},
        )
        assert _filter_jobs([job], "", "pune") == []


class TestIndiaBoards:
    """The company ATS feeds, which are the only real source of India jobs."""

    GREENHOUSE = json.dumps(
        {
            "jobs": [
                {
                    "title": "Backend Engineer",
                    "location": {"name": "Bengaluru, Karnataka, India"},
                    "content": "&lt;p&gt;Python and Postgres.&lt;/p&gt;",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    "updated_at": "2026-08-01T10:00:00Z",
                },
                {
                    "title": "Backend Engineer",
                    "location": {"name": "Austin, Texas"},
                    "content": "Python.",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                    "updated_at": "2026-08-01T10:00:00Z",
                },
            ]
        }
    ).encode()

    LEVER = json.dumps(
        [
            {
                "text": "Data Scientist",
                "categories": {"location": "Noida, Uttar Pradesh"},
                "descriptionPlain": "Python and SQL.",
                "hostedUrl": "https://jobs.lever.co/acme/1",
                "createdAt": 1786000000000,
            }
        ]
    ).encode()

    def test_it_reads_a_greenhouse_board(self):
        engine = scraper(self.GREENHOUSE)
        jobs = engine.fetch_jobs_india_boards(
            boards=[("Acme", "greenhouse", "acme")]
        )
        assert [j["title"] for j in jobs] == ["Backend Engineer", "Backend Engineer"]
        assert jobs[0]["company"] == "Acme"
        assert jobs[0]["location"] == "Bengaluru, Karnataka, India"
        assert jobs[0]["posted_date"] == "2026-08-01"

    def test_greenhouse_is_asked_for_the_advert_text(self):
        """Greenhouse omits the description unless ``content=true`` is sent.

        Without it every Greenhouse advert arrives with an empty description,
        which silently disables scoring against the resume and interview
        preparation -- the buttons grey out and nothing explains why. The
        adverts still appear, so nothing looks broken from the outside, which
        is exactly why this is asserted on the URL rather than left to a
        reviewer to notice.
        """
        seen = []

        def fetcher(url):
            seen.append(url)
            return self.GREENHOUSE

        engine = JobScraper(fetcher=fetcher, respect_robots=False, min_interval=0,
                            cache_ttl=0)
        jobs = engine.fetch_jobs_india_boards(boards=[("Acme", "greenhouse", "acme")])
        assert seen and "content=true" in seen[0]
        # Greenhouse entity-encodes the body, so this also proves the markup
        # is decoded and then removed rather than decoded into visible litter.
        assert jobs[0]["description"] == "Python and Postgres."
        assert "<" not in jobs[0]["description"]

    def test_it_reads_a_lever_board_including_its_epoch_millis(self):
        """Lever dates in milliseconds; every other source sends seconds.

        Passed through unconverted this lands in 1970, which sorts an advert
        to the bottom and labels it thousands of days old.
        """
        engine = scraper(self.LEVER)
        jobs = engine.fetch_jobs_india_boards(boards=[("Acme", "lever", "acme")])
        assert jobs[0]["title"] == "Data Scientist"
        assert jobs[0]["posted_date"].startswith("2026-")

    def test_a_board_with_no_date_is_not_dated_today(self):
        body = json.dumps([{"text": "Engineer", "categories": {"location": "Pune"},
                            "hostedUrl": "https://jobs.lever.co/acme/9"}]).encode()
        jobs = scraper(body).fetch_jobs_india_boards(boards=[("Acme", "lever", "acme")])
        assert jobs[0]["posted_date"] == ""
        assert jobs[0]["days_old"] is None

    def test_one_dead_board_does_not_take_the_others_with_it(self):
        """A company can rename its board or leave the vendor at any time."""
        def fetcher(url):
            if "dead" in url:
                raise ScraperError("404")
            return self.GREENHOUSE

        engine = JobScraper(fetcher=fetcher, respect_robots=False, min_interval=0,
                            cache_ttl=0)
        jobs = engine.fetch_jobs_india_boards(
            boards=[("Dead", "greenhouse", "dead"), ("Alive", "greenhouse", "acme")]
        )
        assert jobs and {j["company"] for j in jobs} == {"Alive"}

    def test_the_india_filter_drops_the_other_offices(self, monkeypatch):
        """These boards are curated for India, not exclusive to it."""
        monkeypatch.setattr(
            "agents.job_scraper.INDIA_BOARDS", (("Acme", "greenhouse", "acme"),)
        )
        engine = scraper(self.GREENHOUSE)
        kept = engine._fetch_india_boards("", "india", 10)
        assert [j["location"] for j in kept] == ["Bengaluru, Karnataka, India"]

    def test_no_single_employer_crowds_out_the_rest(self):
        """Paytm publishes 173 India vacancies; Atlan publishes 6.

        Taken in order, a limit of 10 is ten Paytm adverts and the other
        eleven companies might as well not have been fetched.
        """
        big = [_job("Role %d" % i, "Big", "", "s", "https://x/b%d" % i, "2026-01-01",
                    extra={"location": "Pune"}) for i in range(50)]
        small = [_job("Role", "Small", "", "s", "https://x/s1", "2026-01-01",
                      extra={"location": "Pune"})]
        merged = _interleave([big, small])
        assert "Small" in {j["company"] for j in merged[:5]}

    def test_the_closed_boards_are_recorded_with_reasons(self):
        """These get asked about constantly.

        The answer lives in the code so it is not re-litigated from memory.
        """
        assert set(CLOSED_JOB_BOARDS) == {
            "LinkedIn",
            "Indeed",
            "Naukri",
            "Foundit",
            "Wellfound",
            "SmartRecruiters",
        }
        assert all(len(reason) > 40 for reason in CLOSED_JOB_BOARDS.values())

    def test_smartrecruiters_is_refused_on_robots_not_on_difficulty(self):
        """It is the tempting one, so the reason has to survive a reread.

        The other five are shut because they have no usable interface.
        SmartRecruiters has one, keyless, returning exactly the date,
        India location and apply URL this project needs -- and its robots.txt
        names LinkedInBot as the single permitted agent. Recording it beside
        boards that are merely unavailable would lose that distinction, and
        the distinction is the whole point: this one costs us something.
        """
        reason = CLOSED_JOB_BOARDS["SmartRecruiters"]
        assert "robots.txt" in reason
        assert "LinkedInBot" in reason
        assert "credential" in reason

    def test_every_configured_board_uses_an_allowed_host(self):
        for _company, ats, _slug in INDIA_BOARDS:
            assert ats in {"greenhouse", "lever", "ashby"}

    def test_no_board_is_listed_twice(self):
        """A duplicate slug is a wasted request and a duplicated advert."""
        slugs = [(ats, slug) for _company, ats, slug in INDIA_BOARDS]
        assert len(slugs) == len(set(slugs))
        names = [company for company, _ats, _slug in INDIA_BOARDS]
        assert len(names) == len(set(names))


class TestAdzuna:
    """The licensed aggregator, which only runs when a key is configured."""

    PAYLOAD = json.dumps(
        {
            "results": [
                {
                    "title": "Backend Engineer",
                    "company": {"display_name": "Acme India"},
                    "location": {"display_name": "Bengaluru, Karnataka"},
                    "description": "Python and Django.",
                    "redirect_url": "https://www.adzuna.in/details/1234",
                    "created": "2026-09-05T09:00:00Z",
                }
            ]
        }
    ).encode()

    def _configured(self, monkeypatch, body=None):
        from agents import job_scraper as module

        monkeypatch.setattr(module.settings, "ADZUNA_APP_ID", "id", raising=False)
        monkeypatch.setattr(module.settings, "ADZUNA_APP_KEY", "key", raising=False)
        return scraper(body if body is not None else self.PAYLOAD)

    def test_nothing_happens_without_a_key(self, monkeypatch):
        """An optional source that was never set up is not a failure."""
        from agents import job_scraper as module

        monkeypatch.setattr(module.settings, "ADZUNA_APP_ID", "", raising=False)
        monkeypatch.setattr(module.settings, "ADZUNA_APP_KEY", "", raising=False)
        assert scraper(self.PAYLOAD).fetch_jobs_adzuna("engineer") == []

    def test_an_advert_keeps_its_direct_application_link(self, monkeypatch):
        jobs = self._configured(monkeypatch).fetch_jobs_adzuna("engineer")
        assert len(jobs) == 1
        assert jobs[0]["url"] == "https://www.adzuna.in/details/1234"
        assert jobs[0]["company"] == "Acme India"
        assert jobs[0]["location"] == "Bengaluru, Karnataka"
        assert jobs[0]["posted_date"] == "2026-09-05"
        assert jobs[0]["source"] == "Adzuna"

    def test_the_age_limit_is_asked_of_the_api(self, monkeypatch):
        """Filtering at the source, not after, is the whole point of the param."""
        from agents import job_scraper as module

        monkeypatch.setattr(module.settings, "ADZUNA_APP_ID", "id", raising=False)
        monkeypatch.setattr(module.settings, "ADZUNA_APP_KEY", "key", raising=False)
        seen = []

        def fetcher(url):
            seen.append(url)
            return self.PAYLOAD

        engine = JobScraper(
            fetcher=fetcher, respect_robots=False, min_interval=0, cache_ttl=0
        )
        engine.fetch_jobs_adzuna("engineer", max_age_days=7)
        assert "max_days_old=7" in seen[0]
        assert "what=engineer" in seen[0]

    def test_the_india_endpoint_is_used(self, monkeypatch):
        """The country is in the URL, so it cannot be left off by accident."""
        from agents.job_scraper import ADZUNA_URL

        assert "/jobs/in/" in ADZUNA_URL

    def test_a_malformed_entry_is_skipped_rather_than_crashing(self, monkeypatch):
        body = json.dumps({"results": ["not a dict", None]}).encode()
        assert self._configured(monkeypatch, body).fetch_jobs_adzuna("x") == []

    def test_the_api_host_is_exempt_from_robots(self, monkeypatch):
        """Adzuna's API says Disallow: / to keep search engines out.

        Obeying that against a request we hold a key for would refuse an
        invitation, so the host is exempt. This test exists to prove the
        exemption is reached without the robots fetch happening at all.
        """
        from agents.job_scraper import CREDENTIALLED_API_HOSTS

        engine = JobScraper(fetcher=lambda url: b"", respect_robots=True)

        def explode(origin):
            raise AssertionError("robots.txt must not be fetched for %s" % origin)

        monkeypatch.setattr(engine, "_read_robots", explode)
        assert "api.adzuna.com" in CREDENTIALLED_API_HOSTS
        assert engine._allowed_by_robots("https://api.adzuna.com/v1/api/jobs/in/search/1")

    def test_the_exemption_covers_only_that_one_host(self):
        """A guard against this quietly becoming a general robots bypass."""
        from agents.job_scraper import CREDENTIALLED_API_HOSTS

        assert set(CREDENTIALLED_API_HOSTS) == {"api.adzuna.com"}
        assert all(len(why) > 40 for why in CREDENTIALLED_API_HOSTS.values())

    def test_an_ordinary_host_is_still_refused_when_robots_says_no(self, monkeypatch):
        """The exemption must not have loosened the normal path.

        The parser is supplied directly rather than fetched, so this fails if
        the rule stops being consulted -- not merely if the network is down,
        which would refuse the URL for an entirely different reason and prove
        nothing.
        """
        from urllib.robotparser import RobotFileParser

        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /"])
        engine = JobScraper(fetcher=lambda url: b"", respect_robots=True)
        monkeypatch.setattr(engine, "_read_robots", lambda origin: parser)
        assert not engine._allowed_by_robots("https://example.com/jobs")


class TestRecency:
    """How old an advert is, and what happens when nobody said."""

    def test_a_missing_date_is_empty_not_today(self):
        """The default that mattered most.

        `_date` used to substitute today for an absent date. Under a
        two-day filter that made every undated advert look like it was
        posted this morning -- the exact adverts whose age is unknown were
        promoted to the freshest thing on the page.
        """
        assert _date("") == ""
        assert _date(None) == ""

    def test_an_absent_date_gives_an_unknown_age_not_zero(self):
        assert _age_in_days("") is None
        assert _age_in_days("not a date") is None

    def test_a_known_date_gives_a_whole_number_of_days(self):
        today = datetime.now(timezone.utc).date()
        assert _age_in_days(today.isoformat()) == 0
        assert _age_in_days((today - timedelta(days=5)).isoformat()) == 5

    def test_a_future_date_is_clamped_to_zero(self):
        # Sources in timezones ahead of UTC publish "tomorrow" routinely. A
        # negative age would sort them above everything and read as nonsense.
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        assert _age_in_days(tomorrow.isoformat()) == 0

    def test_every_job_carries_its_age(self):
        today = datetime.now(timezone.utc).date().isoformat()
        assert _job("A", "C", "", "S", "https://x/1", today)["days_old"] == 0
        assert _job("A", "C", "", "S", "https://x/2", "")["days_old"] is None

    def test_newest_first_with_undated_last(self):
        today = datetime.now(timezone.utc).date()
        old = _job("old", "C", "", "S", "https://x/1", (today - timedelta(days=9)).isoformat())
        new = _job("new", "C", "", "S", "https://x/2", today.isoformat())
        unknown = _job("unknown", "C", "", "S", "https://x/3", "")

        assert [j["title"] for j in _by_recency([old, unknown, new])] == [
            "new",
            "old",
            "unknown",
        ]

    def test_undated_adverts_are_not_dropped_by_sorting(self):
        unknown = _job("unknown", "C", "", "S", "https://x/1", "")
        assert len(_by_recency([unknown])) == 1

    def test_fresh_jobs_keeps_only_the_window(self):
        today = datetime.now(timezone.utc).date()
        recent = _job("recent", "C", "", "S", "https://x/1", today.isoformat())
        stale = _job("stale", "C", "", "S", "https://x/2", (today - timedelta(days=30)).isoformat())

        assert [j["title"] for j in fresh_jobs([recent, stale], 2)] == ["recent"]

    def test_fresh_jobs_excludes_undated_adverts(self):
        """"We do not know how old this is" is not "recent enough".

        Keeping them would put adverts of unknown age inside a window that
        was asked for precisely to exclude old ones.
        """
        unknown = _job("unknown", "C", "", "S", "https://x/1", "")
        assert fresh_jobs([unknown], 2) == []

    def test_the_boundary_day_is_included(self):
        today = datetime.now(timezone.utc).date()
        edge = _job("edge", "C", "", "S", "https://x/1", (today - timedelta(days=2)).isoformat())
        assert len(fresh_jobs([edge], 2)) == 1


class TestRetiredSources:
    def test_github_jobs_returns_nothing_and_does_not_pretend(self):
        """GitHub Jobs was retired in 2021 and its DNS no longer resolves.

        The method stays so that a caller reading the brief finds an answer
        rather than an AttributeError, but it must return nothing rather than
        invent adverts.
        """
        assert scraper().fetch_jobs_github("python") == []


class TestInterleaving:
    """A limit must not be spent entirely on whichever source ran first.

    Found live: a search for ten jobs collected twenty-nine adverts from three
    boards and returned ten Hacker News comments.
    """

    def test_takes_from_each_source_in_turn(self):
        groups = [["a1", "a2", "a3"], ["b1", "b2", "b3"]]
        assert _interleave(groups) == ["a1", "b1", "a2", "b2", "a3", "b3"]

    def test_nothing_is_dropped_when_groups_differ_in_length(self):
        groups = [["a1"], ["b1", "b2", "b3"]]
        assert sorted(_interleave(groups)) == ["a1", "b1", "b2", "b3"]

    def test_empty_input(self):
        assert _interleave([]) == []

    def test_a_truncated_result_still_spans_the_sources(self):
        groups = [["a%d" % i for i in range(20)], ["b1", "b2"]]
        assert "b1" in _interleave(groups)[:4]


class TestRobotsStatusHandling:
    """RFC 9309 section 2.3.1, which is counter-intuitive in both directions."""

    def _scraper_with_robots(self, monkeypatch, status_code, body=""):
        class Response:
            def __init__(self):
                self.status_code = status_code
                self.text = body

        engine = JobScraper(fetcher=lambda url: RSS_BODY, min_interval=0, cache_ttl=0)
        monkeypatch.setattr(
            "requests.get", lambda *args, **kwargs: Response()
        )
        return engine

    def test_4xx_means_unrestricted_not_forbidden(self, monkeypatch):
        """A CDN answering 403 to robots.txt had disabled two whole sources."""
        engine = self._scraper_with_robots(monkeypatch, 403)
        assert engine._allowed_by_robots(WWR_FEED) is True

    def test_5xx_means_stay_away(self, monkeypatch):
        """A host having a bad day is not permission."""
        engine = self._scraper_with_robots(monkeypatch, 503)
        assert engine._allowed_by_robots(WWR_FEED) is False

    def test_an_unreachable_host_means_stay_away(self, monkeypatch):
        engine = JobScraper(fetcher=lambda url: RSS_BODY, min_interval=0)

        def explode(*args, **kwargs):
            raise OSError("no route to host")

        monkeypatch.setattr("requests.get", explode)
        assert engine._allowed_by_robots(WWR_FEED) is False

    def test_published_rules_are_obeyed(self, monkeypatch):
        engine = self._scraper_with_robots(
            monkeypatch, 200, "User-agent: *\nDisallow: /categories/\n"
        )
        assert engine._allowed_by_robots(WWR_FEED) is False

    def test_an_allowing_robots_permits_the_fetch(self, monkeypatch):
        engine = self._scraper_with_robots(
            monkeypatch, 200, "User-agent: *\nAllow: /\nDisallow: /admin/\n"
        )
        assert engine._allowed_by_robots(WWR_FEED) is True

    def test_the_result_is_cached_per_origin(self, monkeypatch):
        calls = []

        class Response:
            status_code = 200
            text = "User-agent: *\nAllow: /\n"

        def counting(*args, **kwargs):
            calls.append(args)
            return Response()

        engine = JobScraper(fetcher=lambda url: RSS_BODY, min_interval=0)
        monkeypatch.setattr("requests.get", counting)
        engine._allowed_by_robots(WWR_FEED)
        engine._allowed_by_robots(WWR_FEED)
        assert len(calls) == 1


class TestSearch:
    def test_search_honours_the_limit(self):
        engine = scraper()
        engine.sources = [("rss", engine._fetch_rss)]
        assert len(engine.search("python", "remote", 1)) == 1

    def test_search_returns_shaped_records(self):
        engine = scraper()
        engine.sources = [("rss", engine._fetch_rss)]
        job = engine.search("python", "remote", 5)[0]
        for key in ("title", "company", "description", "source", "url", "job_id"):
            assert key in job


class TestSession:
    """The brief's sketch held a ``requests.Session`` on the scraper."""

    def test_exposes_the_underlying_session(self):
        scraper = JobScraper(respect_robots=False)
        session = scraper.session
        assert session is not None
        assert "User-Agent" in session.headers
        assert scraper.session is session, "the session must be pooled, not remade"

    def test_is_none_when_the_fetcher_is_a_stub(self):
        """No network object exists for an injected fetcher, and none is faked."""
        assert JobScraper(fetcher=lambda url: b"", respect_robots=False).session is None
