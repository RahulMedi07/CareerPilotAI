"""Tests for the job enricher.

No LLM and no network: a stub analyzer and a stub matcher are injected, so
these tests describe the enricher's own behaviour rather than the quality of
whatever model happens to be installed.
"""

from __future__ import annotations

import pytest

from agents.job_enricher import EASY, HARD, MEDIUM, JobEnricher, _match_reasons


class StubAnalyzer:
    """Returns whatever it was told to, and counts calls."""

    def __init__(self, analysis=None):
        self.analysis = analysis or {}
        self.calls = 0

    def analyze(self, text):
        self.calls += 1
        result = {
            "title": "Engineer",
            "required_skills": ["python"],
            "preferred_skills": [],
            "experience_years": 0,
            "seniority": "",
            "confidence": 0.8,
        }
        result.update(self.analysis)
        return result


class StubMatcher:
    def __init__(self, score=72.0, confidence=75.0):
        self.score = score
        self.confidence = confidence

    def calculate_match(self, resume_data, analysis):
        return {
            "overall_match": self.score,
            "confidence": self.confidence,
            "matched_skills": ["python"],
            "missing_skills": ["docker"],
            "recommendation": "MAYBE",
        }


def enricher(analysis=None, score=72.0, confidence=75.0):
    return JobEnricher(
        analyzer=StubAnalyzer(analysis), matcher=StubMatcher(score, confidence)
    )


def job(**kwargs):
    base = {
        "job_id": "job_1",
        "title": "Engineer",
        "company": "Corp",
        "description": "Python work.",
        "url": "https://example.com/1",
        "source": "Test",
    }
    base.update(kwargs)
    return base


class TestEnrichJob:
    def test_adds_an_analysis(self):
        assert "analysis" in enricher().enrich_job(job())

    def test_does_not_mutate_the_input(self):
        original = job()
        enricher().enrich_job(original)
        assert "analysis" not in original

    def test_keeps_the_original_fields(self):
        result = enricher().enrich_job(job())
        assert result["title"] == "Engineer"
        assert result["url"] == "https://example.com/1"

    def test_survives_a_broken_analyzer(self):
        """One bad advert must not take down a whole search."""

        class Exploding:
            def analyze(self, text):
                raise RuntimeError("boom")

        result = JobEnricher(analyzer=Exploding()).enrich_job(job())
        assert result["analysis"]["required_skills"] == []

    @pytest.mark.parametrize("bad", [None, {}, {"title": None}, {"description": None}])
    def test_does_not_crash_on_junk(self, bad):
        assert isinstance(enricher().enrich_job(bad), dict)


class TestDifficulty:
    @pytest.mark.parametrize(
        "analysis,expected",
        [
            ({"experience_years": 0, "required_skills": ["python"]}, EASY),
            ({"experience_years": 3, "required_skills": ["python"]}, EASY),
            ({"experience_years": 6, "required_skills": ["python"]}, MEDIUM),
            ({"experience_years": 10, "required_skills": ["a"] * 12}, HARD),
        ],
    )
    def test_years_and_breadth_drive_it(self, analysis, expected):
        result = enricher(analysis).enrich_job(job())
        assert result["analysis"]["difficulty"] == expected

    def test_a_senior_title_counts_even_when_seniority_is_blank(self):
        """The analyzer's fallback often leaves `seniority` empty.

        Reading only that field reported a "Senior AI Engineer" as EASY.
        """
        plain = enricher({"title": "Engineer", "experience_years": 4})
        senior = enricher({"title": "Senior Engineer", "experience_years": 4})
        assert plain.enrich_job(job())["analysis"]["difficulty"] == EASY
        assert senior.enrich_job(job())["analysis"]["difficulty"] == MEDIUM


class TestSalary:
    """An invented salary is worse than a blank one."""

    @pytest.mark.parametrize(
        "text",
        [
            "We offer a competitive package.",
            "Founded in 2019, we serve 5000 customers.",
            "The role covers 2024-2026 roadmap work.",
            "Team of 10-20 engineers.",
            "We serve 100-200 clients.",
            "Version 2.1-3.0 of the platform.",
            "Ticket #10234-10999 tracks this work.",
            "Postcode 90210-90310 delivery area.",
            # The word "salary" earlier in the sentence must not turn a
            # headcount into a pay band.
            "Salary depends on experience. We have 10000-20000 users.",
            "Pay is fair. The office is 5000-6000 sq ft.",
            "",
        ],
    )
    def test_returns_none_when_no_salary_is_stated(self, text):
        result = enricher().enrich_job(job(description=text))
        assert result["analysis"]["estimated_salary_range"] is None

    @pytest.mark.parametrize(
        "text",
        [
            "Salary: $120,000 - $160,000 per year",
            "Compensation 90k-130k USD",
            "We pay £50,000 to £70,000",
            # A currency symbol repeated on both figures is one of the most
            # common advert formats, and was silently missed: the context
            # check spelled the symbols as \b$\b, which can never match.
            "Remote role. $80k-$120k",
            "$80k - $120k",
            "\u20ac60,000-\u20ac80,000",
            # Figures written without a thousands separator.
            "Salary 50000-70000",
            "Range: 80000-120000 EUR",
        ],
    )
    def test_finds_a_stated_range(self, text):
        result = enricher().enrich_job(job(description=text))
        assert result["analysis"]["estimated_salary_range"] is not None

    def test_keeps_the_currency_symbol_when_it_is_repeated(self):
        result = enricher().enrich_job(job(description="Remote. $80k-$120k"))
        assert result["analysis"]["estimated_salary_range"] == "$80k-120k"

    def test_writes_a_word_unit_once_not_on_both_figures(self):
        """"15lpa-25lpa" is not how anyone writes a salary."""
        result = enricher().enrich_job(job(description="\u20b915-25 LPA"))
        assert result["analysis"]["estimated_salary_range"] == "\u20b915-25 LPA"


class TestRemote:
    """Three states, because "not stated" is not the same as "not remote"."""

    def test_remote_is_true_when_said(self):
        result = enricher().enrich_job(job(description="This is a fully remote role."))
        assert result["analysis"]["remote"] is True

    def test_remote_is_false_when_denied(self):
        result = enricher().enrich_job(
            job(description="This role is onsite only, no remote work.")
        )
        assert result["analysis"]["remote"] is False

    def test_remote_is_none_when_unstated(self):
        result = enricher().enrich_job(job(description="We build software."))
        assert result["analysis"]["remote"] is None


class TestMatching:
    def test_no_resume_means_no_score_rather_than_a_zero(self):
        """A zero would read as "bad fit"; the truth is "not compared"."""
        result = enricher().enrich_job(job())
        assert not result.get("match_to_user")

    def test_a_resume_produces_a_score(self):
        result = enricher(score=88.0).enrich_job(job(), {"resume_text": "python"})
        assert result["match_to_user"]["score"] == 88.0

    def test_an_unscorable_advert_keeps_its_null_rather_than_becoming_zero(self):
        # The matcher returns None when it could not assess the advert. That
        # used to be coerced to 0.0 here, so the card showed "0% Match" and the
        # advert was filed under "Learning needed" -- a measurement the app
        # never made, presented as a bad one.
        result = enricher(score=None).enrich_job(job(), {"resume_text": "python"})
        assert result["match_to_user"]["score"] is None
        assert result["match_to_user"]["percentage"] == "Not scored"

    def test_an_unscorable_advert_is_bucketed_as_unscored(self):
        enriched = enricher(score=None).enrich_job(job(), {"resume_text": "python"})
        buckets = enricher().categorize_jobs([enriched])
        assert len(buckets["unscored"]) == 1
        assert buckets["learning_needed"] == []

    def test_an_unscored_advert_is_not_told_it_is_a_stretch(self):
        # Both band lines describe where a score sits. With no score there is
        # no band, and "most of what it wants is not on your resume yet" would
        # be a claim about a comparison that never happened.
        reasons = enricher(score=None).enrich_job(
            job(), {"resume_text": "python"}
        )["match_to_user"]["reasons"]
        assert not any("stretch" in r for r in reasons)
        assert not any("closest matches" in r for r in reasons)


class TestHowMuchOfTheAdvertWasRead:
    """`confidence` is how legible the advert was, not how good the fit is.

    The calculator has always reported the two separately and on purpose. The
    enricher used to keep the score and drop the confidence, so a German-
    language advert that yielded a single readable skill the candidate happened
    to have reached the card as a confident 100% match against a junior CV.
    """

    def test_the_confidence_reaches_the_card(self):
        result = enricher(score=100.0, confidence=50.0).enrich_job(
            job(), {"resume_text": "python"}
        )
        assert result["match_to_user"]["confidence"] == 50.0

    def test_a_thin_advert_keeps_its_score_rather_than_losing_it(self):
        """Suppressing the number would hide a real match behind a caveat."""
        result = enricher(score=100.0, confidence=50.0).enrich_job(
            job(), {"resume_text": "python"}
        )
        assert result["match_to_user"]["score"] == 100.0
        assert result["match_to_user"]["percentage"] == "100%"

    def test_a_matcher_that_reports_no_confidence_yields_null_not_zero(self):
        """Zero would read as "we understood nothing", which is a claim."""
        result = enricher(score=80.0, confidence=None).enrich_job(
            job(), {"resume_text": "python"}
        )
        assert result["match_to_user"]["confidence"] is None

    def test_a_barely_read_advert_is_not_filed_as_a_perfect_match(self):
        """The card said "treat loosely" while the filter chip said "perfect"."""
        enriched = enricher(score=100.0, confidence=50.0).enrich_job(
            job(), {"resume_text": "python"}
        )
        buckets = enricher().categorize_jobs([enriched])
        assert buckets["perfect_match"] == []
        assert len(buckets["good_fit"]) == 1

    def test_a_well_read_advert_still_reaches_the_top_band(self):
        """The guard must not quietly empty the bucket it protects."""
        enriched = enricher(score=100.0, confidence=85.0).enrich_job(
            job(), {"resume_text": "python"}
        )
        buckets = enricher().categorize_jobs([enriched])
        assert len(buckets["perfect_match"]) == 1

    def test_an_advert_with_no_confidence_reported_is_left_alone(self):
        """Absent confidence is not evidence of a thin advert."""
        enriched = enricher(score=100.0, confidence=None).enrich_job(
            job(), {"resume_text": "python"}
        )
        buckets = enricher().categorize_jobs([enriched])
        assert len(buckets["perfect_match"]) == 1


class TestWhyApply:
    """The plain-English answer to "why should I apply for this one?"."""

    def _reasons(self, score=72.0, analysis=None):
        result = enricher(analysis=analysis, score=score).enrich_job(
            job(), {"resume_text": "python"}
        )
        return result["match_to_user"]["reasons"]

    def test_reasons_are_produced_alongside_the_score(self):
        assert self._reasons()

    def test_the_overlap_is_named_not_just_counted(self):
        # "You match 1 of 2 skills" is a statistic. Naming python is what
        # lets someone decide in five seconds whether to read further.
        assert any("python" in reason.lower() for reason in self._reasons())

    def test_the_gaps_are_stated_too(self):
        """A list of reasons to apply with the reasons against left off is an
        advert, not advice. Docker is missing and the card says so."""
        assert any("docker" in reason.lower() for reason in self._reasons())

    def test_a_weak_match_is_called_a_stretch(self):
        assert any("stretch" in reason.lower() for reason in self._reasons(score=25.0))

    def test_a_strong_match_says_so(self):
        assert any("closest" in reason.lower() for reason in self._reasons(score=92.0))

    def test_an_unscored_advert_has_no_reasons_invented_for_it(self):
        # No resume means nothing was compared, so there is nothing truthful
        # to say about why it fits.
        result = enricher().enrich_job(job())
        assert not result.get("match_to_user")

    def test_an_unknown_seniority_is_left_out_rather_than_printed(self):
        """Seen live: "The advert is pitched at unknown level."

        The analyser stores a seniority it could not determine as the literal
        string "unknown". A blank is not a value, and printing it spends a
        line of the panel telling the user nothing.
        """
        reasons = self._reasons(
            analysis={
                "title": "T",
                "required_skills": ["python"],
                "seniority": "unknown",
                "role_type": "general",
                "confidence": 0.5,
            }
        )
        joined = " ".join(reasons).lower()
        assert "unknown level" not in joined
        assert "general role" not in joined

    def test_a_high_score_on_an_unreadable_advert_is_not_sold_as_a_close_match(self):
        """Seen live, and self-contradictory on the same card.

        The panel said "The advert did not list its skills clearly enough to
        compare" and then, four lines down, "On skills alone this is one of
        the closest matches found". Both cannot be true. With no skills to
        compare, the score is an artefact and the claim is unfounded.
        """
        # Straight to the helper: the stub matcher hard-codes an overlap, and
        # the case under test is the one where there is none.
        joined = " ".join(_match_reasons(92.0, [], [], {})).lower()
        assert "clearly enough to compare" in joined
        assert "closest" not in joined


class TestBatch:
    def test_order_is_preserved(self):
        """Threads finish out of order; the caller's list must not be reshuffled."""
        jobs = [job(job_id="job_%d" % i, title="Role %d" % i, url="https://x/%d" % i)
                for i in range(20)]
        result = enricher().batch_enrich_jobs(jobs)
        assert [item["title"] for item in result] == [item["title"] for item in jobs]

    def test_every_job_comes_back(self):
        jobs = [job(url="https://x/%d" % i) for i in range(7)]
        assert len(enricher().batch_enrich_jobs(jobs)) == 7

    def test_an_empty_list_is_fine(self):
        assert enricher().batch_enrich_jobs([]) == []

    def test_one_failure_does_not_lose_the_others(self):
        class Flaky:
            def __init__(self):
                self.seen = 0

            def analyze(self, text):
                self.seen += 1
                if self.seen == 2:
                    raise RuntimeError("boom")
                return {"title": "T", "required_skills": [], "confidence": 0.5}

        jobs = [job(url="https://x/%d" % i) for i in range(4)]
        result = JobEnricher(analyzer=Flaky()).batch_enrich_jobs(jobs)
        assert len(result) == 4


class TestCategorize:
    def _scored(self, scores):
        engine = enricher()
        out = []
        for index, score in enumerate(scores):
            item = engine.enrich_job(job(url="https://x/%d" % index))
            item["match_to_user"] = {"score": score}
            out.append(item)
        return out

    def test_buckets_by_score(self):
        result = enricher().categorize_jobs(self._scored([95.0, 70.0, 45.0, 10.0]))
        assert result["counts"]["perfect_match"] == 1
        assert result["counts"]["good_fit"] == 1
        assert result["counts"]["stretch_goal"] == 1
        assert result["counts"]["learning_needed"] == 1

    def test_unscored_jobs_are_separated_not_dumped_in_the_bottom_bucket(self):
        """Filing "not compared" under "learning needed" would be a lie."""
        jobs = [enricher().enrich_job(job())]
        result = enricher().categorize_jobs(jobs)
        assert len(result["unscored"]) == 1
        assert result["counts"]["learning_needed"] == 0

    def test_counts_by_difficulty(self):
        result = enricher().categorize_jobs(self._scored([95.0, 70.0]))
        assert sum(result["by_difficulty"].values()) == 2

    def test_empty_input(self):
        result = enricher().categorize_jobs([])
        assert result["counts"]["perfect_match"] == 0
