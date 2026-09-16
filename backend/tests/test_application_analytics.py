"""Tests for the application analytics.

Most of these are about *refusal*. It is easy to write a module that always
produces a number; the work is in the cases where it must not, because a
confident percentage computed from three data points will be believed and
acted on. The tests below pin the blanks as firmly as the figures.

Records are plain dictionaries in the tracker's output shape, so nothing here
needs a database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agents.application_analytics import (
    MIN_SAMPLE_FOR_FORECAST,
    MIN_SAMPLE_FOR_RATE,
    ApplicationAnalytics,
    wilson_interval,
)

BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)

DRAFT, SENT, INTERVIEW, OFFER, REJECTED = 0, 1, 2, 3, 4


def record(index=0, day=0, stage=SENT, score=70.0, gaps=None, title="AI Engineer"):
    """One application in the shape the tracker returns."""
    created = BASE + timedelta(days=day)
    timeline = [
        {"event": "created", "timestamp": created.isoformat(), "date": created.date().isoformat(), "status": "draft"}
    ]
    status = "draft"
    if stage >= SENT:
        timeline.append(
            {"event": "application_sent", "timestamp": created.isoformat(), "date": created.date().isoformat(), "status": "sent"}
        )
        status = "sent"
    if stage in (INTERVIEW, OFFER):
        heard = created + timedelta(days=6)
        timeline.append(
            {"event": "interview_scheduled", "timestamp": heard.isoformat(), "date": heard.date().isoformat(), "status": "interview"}
        )
        status = "interview"
    if stage == OFFER:
        won = created + timedelta(days=20)
        timeline.append(
            {"event": "offer_received", "timestamp": won.isoformat(), "date": won.date().isoformat(), "status": "offer"}
        )
        status = "offer"
    if stage == REJECTED:
        out = created + timedelta(days=10)
        timeline.append(
            {"event": "rejected", "timestamp": out.isoformat(), "date": out.date().isoformat(), "status": "rejected"}
        )
        status = "rejected"
    return {
        "app_id": "app_%d" % index,
        "job_id": "job_%d" % index,
        "job_title": title,
        "company": "C%d" % index,
        "match_score": score,
        "gaps_identified": list(gaps or []),
        "interview_prep_score": None,
        "current_status": status,
        "created_date": created.isoformat(),
        "updated_date": created.isoformat(),
        "notes": "",
        "timeline": timeline,
    }


def spread(count, stage=SENT, **kwargs):
    """``count`` applications three days apart, so a pace is measurable."""
    return [record(index=i, day=i * 3, stage=stage, **kwargs) for i in range(count)]


@pytest.fixture
def analytics():
    # The tracker is never reached: every call passes history explicitly.
    return ApplicationAnalytics(tracker=object())


class TestWilsonInterval:
    def test_none_without_trials(self):
        assert wilson_interval(0, 0) is None

    def test_brackets_the_observed_rate(self):
        low, high = wilson_interval(2, 8)
        assert low < 25.0 < high

    def test_is_wide_on_small_samples(self):
        low, high = wilson_interval(2, 8)
        assert high - low > 40.0, "8 observations cannot pin a rate tightly"

    def test_narrows_as_evidence_accumulates(self):
        small = wilson_interval(20, 80)
        large = wilson_interval(200, 800)
        assert (large[1] - large[0]) < (small[1] - small[0])

    def test_does_not_claim_certainty_from_zero_successes(self):
        """The textbook normal approximation returns [0, 0] here, which would
        assert that an offer is impossible on the strength of 8 applications."""
        low, high = wilson_interval(0, 8)
        assert low == 0.0
        assert high > 20.0

    def test_stays_inside_zero_and_one_hundred(self):
        for successes, trials in ((0, 1), (1, 1), (0, 3), (3, 3), (5, 5)):
            low, high = wilson_interval(successes, trials)
            assert 0.0 <= low <= high <= 100.0


class TestMetricsWithNoData:
    def test_everything_is_zero_or_absent_not_invented(self, analytics):
        metrics = analytics.calculate_success_metrics("me", [])
        assert metrics["total_applications"] == 0
        assert metrics["interviews_scheduled"] == 0

    def test_a_rate_with_no_denominator_is_none_not_zero(self, analytics):
        """0% reads as failure. The truth is that nothing has been measured."""
        metrics = analytics.calculate_success_metrics("me", [])
        assert metrics["interview_rate"] is None
        assert metrics["offer_rate"] is None

    def test_says_so_plainly(self, analytics):
        metrics = analytics.calculate_success_metrics("me", [])
        assert "No applications sent yet" in metrics["sample_size_warning"]

    def test_averages_are_none(self, analytics):
        metrics = analytics.calculate_success_metrics("me", [])
        assert metrics["avg_match_score_when_applied"] is None
        assert metrics["avg_match_score_when_interview"] is None


class TestMetricsCounting:
    def test_counts_the_stages(self, analytics):
        history = spread(3, SENT) + spread(2, INTERVIEW) + spread(1, OFFER)
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["total_applications"] == 6
        assert metrics["interviews_scheduled"] == 3, "an offer implies an interview"
        assert metrics["offers_received"] == 1

    def test_drafts_are_excluded_from_the_denominator(self, analytics):
        """An application never sent cannot have failed to get an interview."""
        history = spread(5, SENT) + spread(5, DRAFT)
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["total_applications"] == 10
        assert metrics["applications_sent"] == 5

    def test_interview_rate_divides_by_applications_sent(self, analytics):
        history = spread(2, INTERVIEW) + spread(6, SENT)
        assert analytics.calculate_success_metrics("me", history)["interview_rate"] == "25%"

    def test_offer_rate_divides_by_interviews(self, analytics):
        history = spread(1, OFFER) + spread(3, INTERVIEW)
        assert analytics.calculate_success_metrics("me", history)["offer_rate"] == "25%"

    def test_an_offer_counts_as_having_interviewed(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(1, OFFER))
        assert metrics["interviews_scheduled"] == 1

    def test_counts_rejections(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(3, REJECTED))
        assert metrics["rejections"] == 3

    def test_still_open_excludes_closed_applications(self, analytics):
        history = spread(2, SENT) + spread(2, REJECTED) + spread(1, OFFER)
        assert analytics.calculate_success_metrics("me", history)["still_open"] == 2


class TestMetricsHonesty:
    def test_a_thin_sample_carries_a_warning(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(2, SENT))
        assert metrics["sample_size_warning"]
        assert "2 applications" in metrics["sample_size_warning"]

    def test_a_rate_always_arrives_with_its_interval(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(8, SENT))
        assert metrics["interview_rate"] is not None
        assert metrics["interview_rate_confidence_95"] is not None

    def test_the_interval_is_honestly_wide(self, analytics):
        """2 from 8 is "25%", and the truth is anywhere from about 7% to 59%."""
        history = spread(2, INTERVIEW) + spread(6, SENT)
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["interview_rate"] == "25%"
        assert metrics["interview_rate_confidence_95"] == "7%-59%"

    def test_warns_when_the_offer_rate_rests_on_two_interviews(self, analytics):
        """The offer rate divides by interviews, so it can be far thinner than
        the interview rate printed directly above it."""
        history = spread(2, INTERVIEW) + spread(6, SENT)
        warning = analytics.calculate_success_metrics("me", history)["sample_size_warning"]
        assert "2 interviews" in warning

    def test_zero_offers_yields_a_usable_upper_bound(self, analytics):
        """The rule of three: nothing in 8 tries means the rate is below 3/8."""
        metrics = analytics.calculate_success_metrics("me", spread(8, SENT))
        assert metrics["offer_rate_upper_bound_95"] == "below 38%"

    def test_no_vacuous_bound_from_a_handful(self, analytics):
        """"Your offer rate is below 100%" is true of everyone."""
        metrics = analytics.calculate_success_metrics("me", spread(2, SENT))
        assert metrics.get("offer_rate_upper_bound_95") is None

    def test_no_bound_once_an_offer_exists(self, analytics):
        history = spread(1, OFFER) + spread(9, SENT)
        assert "offer_rate_upper_bound_95" not in analytics.calculate_success_metrics(
            "me", history
        )


class TestMatchScores:
    def test_averages_only_what_was_measured(self, analytics):
        history = spread(2, SENT, score=80.0) + [record(9, 9, SENT, score=None)]
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["avg_match_score_when_applied"] == 80.0

    def test_an_absent_score_does_not_drag_the_average_down(self, analytics):
        with_blank = analytics.calculate_success_metrics(
            "me", spread(2, SENT, score=80.0) + [record(9, 9, SENT, score=None)]
        )
        without = analytics.calculate_success_metrics("me", spread(2, SENT, score=80.0))
        assert with_blank["avg_match_score_when_applied"] == without["avg_match_score_when_applied"]

    def test_reports_the_interview_average_separately(self, analytics):
        history = spread(2, INTERVIEW, score=85.0) + spread(4, SENT, score=65.0)
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["avg_match_score_when_interview"] == 85.0
        assert metrics["avg_match_score_when_applied"] < 85.0


class TestDaysToInterview:
    def test_measures_the_gap_between_sending_and_hearing(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(3, INTERVIEW))
        assert metrics["days_to_interview"] == 6.0
        assert metrics["days_to_interview_observations"] == 3

    def test_none_when_nothing_has_come_back(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(4, SENT))
        assert metrics["days_to_interview"] is None
        assert metrics["days_to_interview_observations"] == 0

    def test_reports_a_median_too(self, analytics):
        metrics = analytics.calculate_success_metrics("me", spread(3, INTERVIEW))
        assert metrics["days_to_interview_median"] == 6.0


class TestBestJobType:
    def test_none_without_any_interviews(self, analytics):
        assert analytics.calculate_success_metrics("me", spread(5, SENT))["best_job_type"] is None

    def test_none_from_a_single_success(self, analytics):
        """One interview is a coincidence, not a pattern to chase."""
        history = [record(0, 0, INTERVIEW, title="RAG Engineer")] + spread(4, SENT)
        assert analytics.calculate_success_metrics("me", history)["best_job_type"] is None

    def test_names_a_title_that_has_worked_twice(self, analytics):
        history = [
            record(0, 0, INTERVIEW, title="RAG Systems Engineer"),
            record(1, 3, INTERVIEW, title="RAG Systems Engineer"),
            record(2, 6, SENT, title="Data Scientist"),
        ]
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["best_job_type"] == "RAG Systems Engineer"


class TestGaps:
    def test_collects_the_common_ones(self, analytics):
        history = spread(3, SENT, gaps=["LangGraph", "Kubernetes"])
        assert analytics.calculate_success_metrics("me", history)["common_gaps"][:2] == [
            "LangGraph",
            "Kubernetes",
        ]

    def test_tracks_gaps_in_rejections_separately(self, analytics):
        history = spread(2, REJECTED, gaps=["LangGraph"]) + spread(2, SENT, gaps=["Rust"])
        metrics = analytics.calculate_success_metrics("me", history)
        assert metrics["gaps_in_rejections"] == ["LangGraph"]

    def test_empty_when_no_gaps_recorded(self, analytics):
        assert analytics.calculate_success_metrics("me", spread(3, SENT))["common_gaps"] == []


class TestStrategy:
    def test_says_so_when_there_is_nothing_to_analyse(self, analytics):
        strategy = analytics.recommend_application_strategy("me", [])
        assert "No applications yet" in strategy["current_situation"]
        assert strategy["recommendations"]
        assert strategy["confidence"].startswith("none")

    def test_describes_the_real_situation(self, analytics):
        history = spread(2, INTERVIEW) + spread(6, SENT)
        strategy = analytics.recommend_application_strategy("me", history)
        assert "8 sent" in strategy["current_situation"]
        assert "2 reached interview" in strategy["current_situation"]

    def test_flags_drafts_that_were_never_sent(self, analytics):
        strategy = analytics.recommend_application_strategy("me", spread(3, DRAFT))
        assert "not sent" in (strategy["issue"] or "")

    def test_names_the_conversion_problem_when_there_is_one(self, analytics):
        strategy = analytics.recommend_application_strategy("me", spread(8, SENT))
        assert "not converting into interviews" in (strategy["issue"] or "")

    def test_distinguishes_interviews_not_converting(self, analytics):
        history = spread(3, INTERVIEW) + spread(5, SENT)
        strategy = analytics.recommend_application_strategy("me", history)
        assert "not converting" in (strategy["issue"] or "")
        assert any("preparation" in line for line in strategy["recommendations"])

    def test_recommendations_cite_numbers(self, analytics):
        history = spread(2, INTERVIEW) + spread(6, SENT)
        strategy = analytics.recommend_application_strategy("me", history)
        assert any("%" in line for line in strategy["recommendations"])

    def test_states_how_much_history_it_is_working_from(self, analytics):
        strategy = analytics.recommend_application_strategy("me", spread(4, SENT))
        assert strategy["based_on"] == "4 applications"
        assert strategy["confidence"].startswith("low")

    def test_confidence_grows_with_evidence(self, analytics):
        thin = analytics.recommend_application_strategy("me", spread(3, SENT))
        thick = analytics.recommend_application_strategy("me", spread(20, SENT))
        assert thin["confidence"] != thick["confidence"]

    def test_next_steps_are_numbered_and_actionable(self, analytics):
        strategy = analytics.recommend_application_strategy("me", spread(2, SENT))
        assert strategy["next_steps"][0].startswith("1. ")

    def test_only_raises_the_bar_when_the_history_supports_it(self, analytics):
        """No recommendation to aim higher when interviewed applications did
        not in fact score higher."""
        history = spread(2, INTERVIEW, score=70.0) + spread(6, SENT, score=70.0)
        strategy = analytics.recommend_application_strategy("me", history)
        assert not any("supported by your own history" in line for line in strategy["recommendations"])

    def test_raises_the_bar_when_they_did(self, analytics):
        history = spread(2, INTERVIEW, score=88.0) + spread(6, SENT, score=60.0)
        strategy = analytics.recommend_application_strategy("me", history)
        assert any("supported by your own history" in line for line in strategy["recommendations"])


class TestGapAdvice:
    def test_silent_on_too_few_rejections(self, analytics):
        history = spread(2, REJECTED, gaps=["LangGraph"])
        strategy = analytics.recommend_application_strategy("me", history)
        assert not any("clearest link" in line for line in strategy["recommendations"])

    def test_names_a_gap_that_dominates_rejections(self, analytics):
        history = spread(4, REJECTED, gaps=["LangGraph"]) + spread(4, SENT, gaps=["Rust"])
        strategy = analytics.recommend_application_strategy("me", history)
        assert any(
            "LangGraph" in line and "clearest link" in line
            for line in strategy["recommendations"]
        )

    def test_silent_when_the_gap_is_present_in_everything(self, analytics):
        """A skill missing from all twelve applications explains none of the
        three rejections, however impressive "3 of your 3" sounds.

        This is the sentence the module actually produced on its first run
        against realistic data.
        """
        history = spread(3, REJECTED, gaps=["LangGraph"]) + spread(9, SENT, gaps=["LangGraph"])
        strategy = analytics.recommend_application_strategy("me", history)
        assert not any("LangGraph" in line and "clearest link" in line
                       for line in strategy["recommendations"])

    def test_prefers_the_discriminating_gap_over_the_common_one(self, analytics):
        """Kubernetes is in every application; Rust is only in the rejections."""
        history = (
            spread(3, REJECTED, gaps=["Kubernetes", "Rust"])
            + spread(6, SENT, gaps=["Kubernetes"])
        )
        strategy = analytics.recommend_application_strategy("me", history)
        line = next(
            (line for line in strategy["recommendations"] if "clearest link" in line), ""
        )
        assert "Rust" in line
        assert "Kubernetes" not in line

    def test_next_step_names_the_same_gap_as_the_recommendation(self, analytics):
        """An earlier version printed "Rust has the clearest link" immediately
        above "close the gap that recurs most: Kubernetes"."""
        history = (
            spread(3, REJECTED, gaps=["Kubernetes", "Rust"])
            + spread(6, SENT, gaps=["Kubernetes"])
        )
        strategy = analytics.recommend_application_strategy("me", history)
        step = next((s for s in strategy["next_steps"] if "gap" in s), "")
        assert "Rust" in step
        assert "Kubernetes" not in step

    def test_frequency_fallback_says_it_is_only_frequency(self, analytics):
        history = spread(6, SENT, gaps=["Kubernetes"])
        strategy = analytics.recommend_application_strategy("me", history)
        step = next((s for s in strategy["next_steps"] if "gap" in s), "")
        assert "Kubernetes" in step
        assert "Nothing in the log yet links it to an outcome" in step


class TestReplyTime:
    def test_reports_a_real_waiting_time(self, analytics):
        strategy = analytics.recommend_application_strategy("me", spread(3, INTERVIEW))
        assert any("median of 6 days" in line for line in strategy["recommendations"])

    def test_silent_when_the_median_rounds_to_nothing(self, analytics):
        """"Replies take a median of 0 days, so silence before then is not
        news" is a sentence with no content in it."""
        history = [
            {
                "app_id": "a%d" % index,
                "job_title": "AI Engineer",
                "company": "C",
                "match_score": 70.0,
                "gaps_identified": [],
                "current_status": "interview",
                "created_date": BASE.isoformat(),
                "timeline": [
                    {"event": "application_sent", "timestamp": BASE.isoformat(), "status": "sent"},
                    {"event": "interview_scheduled", "timestamp": BASE.isoformat(), "status": "interview"},
                ],
            }
            for index in range(3)
        ]
        strategy = analytics.recommend_application_strategy("me", history)
        assert not any("median of" in line for line in strategy["recommendations"])


class TestPredictionRefusal:
    def test_no_forecast_without_applications(self, analytics):
        prediction = analytics.predict_offer_probability("me", [])
        assert prediction["offer_probability_next_month"] is None
        assert prediction["estimated_time_to_offer"] is None
        assert "nothing to forecast from" in prediction["basis"]

    def test_no_forecast_without_a_single_offer(self, analytics):
        """There is no rate to project from zero observations of the event."""
        prediction = analytics.predict_offer_probability("me", spread(20, INTERVIEW))
        assert prediction["offer_probability_next_month"] is None
        assert prediction["estimated_time_to_offer"] is None
        assert "No offers yet" in prediction["basis"]

    def test_no_forecast_below_the_minimum_sample(self, analytics):
        history = spread(1, OFFER) + spread(3, SENT)
        prediction = analytics.predict_offer_probability("me", history)
        assert prediction["offer_probability_next_month"] is None

    def test_offers_the_upper_bound_instead(self, analytics):
        prediction = analytics.predict_offer_probability("me", spread(20, SENT))
        assert "below" in prediction["offer_rate_upper_bound_95"]

    def test_still_reports_the_real_stats_while_refusing(self, analytics):
        prediction = analytics.predict_offer_probability("me", spread(20, INTERVIEW))
        assert prediction["current_stats"]["applications_sent"] == 20
        assert prediction["current_stats"]["interview_rate"] == "100%"

    def test_still_says_what_would_have_to_change(self, analytics):
        prediction = analytics.predict_offer_probability("me", spread(20, SENT))
        assert prediction["what_needs_to_happen"]


class TestPredictionPace:
    def test_refuses_a_monthly_rate_from_a_single_day(self, analytics):
        """20 applications sent in one sitting is not a pace of 20 a month.

        Projecting it forward produced an "86% chance of an offer next month"
        before this was fixed.
        """
        history = [record(i, 0, OFFER if i < 2 else SENT) for i in range(20)]
        prediction = analytics.predict_offer_probability("me", history)
        assert prediction["offer_probability_next_month"] is None
        assert "too short a window" in prediction["basis"]

    def test_gives_the_per_application_rate_anyway(self, analytics):
        history = [record(i, 0, OFFER if i < 2 else SENT) for i in range(20)]
        prediction = analytics.predict_offer_probability("me", history)
        assert prediction["offer_rate_per_application"] == "10%"

    def test_forecasts_once_the_window_is_long_enough(self, analytics):
        history = [record(i, i * 3, OFFER if i < 2 else SENT) for i in range(20)]
        prediction = analytics.predict_offer_probability("me", history)
        assert prediction["offer_probability_next_month"] is not None
        assert prediction["estimated_time_to_offer"] is not None

    def test_the_forecast_says_what_it_rests_on(self, analytics):
        history = [record(i, i * 3, OFFER if i < 2 else SENT) for i in range(20)]
        basis = analytics.predict_offer_probability("me", history)["basis"]
        assert "applications a month" in basis
        assert "not a model of the job market" in basis

    def test_the_probability_is_a_percentage_string(self, analytics):
        history = [record(i, i * 3, OFFER if i < 2 else SENT) for i in range(20)]
        assert analytics.predict_offer_probability("me", history)[
            "offer_probability_next_month"
        ].endswith("%")

    def test_a_better_rate_predicts_sooner(self, analytics):
        poor = [record(i, i * 3, OFFER if i < 1 else SENT) for i in range(20)]
        good = [record(i, i * 3, OFFER if i < 6 else SENT) for i in range(20)]
        low = int(analytics.predict_offer_probability("me", poor)["offer_probability_next_month"].rstrip("%"))
        high = int(analytics.predict_offer_probability("me", good)["offer_probability_next_month"].rstrip("%"))
        assert high > low

    def test_the_probability_carries_its_own_range(self, analytics):
        """The headline percentage is built on an uncertain rate, so it is an
        uncertain percentage. Reporting it bare overstates what is known."""
        history = [record(i, i * 3, OFFER if i < 1 else SENT) for i in range(20)]
        prediction = analytics.predict_offer_probability("me", history)
        span = prediction["offer_probability_confidence_95"]
        low, high = (int(part.rstrip("%")) for part in span.split("-"))
        point = int(prediction["offer_probability_next_month"].rstrip("%"))
        assert low <= point <= high
        assert high - low > 20  # one offer from twenty says very little

    def test_the_range_narrows_as_evidence_accumulates(self, analytics):
        thin = [record(i, i * 3, OFFER if i < 1 else SENT) for i in range(12)]
        thick = [record(i, i, OFFER if i % 12 == 0 else SENT) for i in range(96)]

        def width(history):
            span = analytics.predict_offer_probability("me", history)[
                "offer_probability_confidence_95"
            ]
            low, high = (int(part.rstrip("%")) for part in span.split("-"))
            return high - low

        assert width(thick) < width(thin)


class TestConstants:
    def test_the_thresholds_are_ordered(self):
        assert MIN_SAMPLE_FOR_RATE < MIN_SAMPLE_FOR_FORECAST
