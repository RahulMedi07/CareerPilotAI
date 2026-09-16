"""What the application history actually supports saying.

This module exists to answer "how is the job hunt going", and the hard part
is not the arithmetic. It is refusing to answer when the data cannot carry
the answer.

**Why there are confidence intervals in a job-hunting app.** Two interviews
from eight applications is "25%", and that number feels solid because it is
printed to the same number of decimal places as a number computed from eight
thousand. It is not solid. The 95% interval around it runs from roughly 7% to
59%. Someone told "your interview rate is 25%" will compare that against an
article saying the average is 20% and conclude they are doing well. Someone
told "25%, but on eight applications the truth is somewhere between 7% and
59%" knows the only useful thing here: apply more, then look again.

**Why some fields come back ``None``.** The brief asks for an offer
probability for next month and an estimated time to offer. With no offers
ever observed there is nothing to estimate from - any number would be
invented, and an invented forecast is worse than a blank one because people
plan around forecasts. They stop applying because the model said three weeks.
So the point estimate is withheld until the data supports it, and what is
returned instead is the strongest thing that *is* true: a 95% upper bound
from the rule of three, which says that if you have applied twenty times with
no offer, your per-application offer rate is probably below 15%. That is a
real statement derived from real data, and it is more useful than a
confident-sounding "65%".

This is the same rule the rest of the project follows for salaries and remote
flags: state what is known, mark what is not, and never let a blank become a
zero on the way to an average.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ApplicationAnalytics",
    "application_analytics",
    "MIN_SAMPLE_FOR_RATE",
    "MIN_SAMPLE_FOR_FORECAST",
    "wilson_interval",
]

#: Below this many applications a rate is reported alongside a warning rather
#: than on its own. Five is not a magic number - it is the point at which the
#: interval stops being wider than the entire range of plausible answers.
MIN_SAMPLE_FOR_RATE = 5

#: Below this, no forecast is offered at all. Ten applications with at least
#: one offer is thin; nine with none is nothing.
MIN_SAMPLE_FOR_FORECAST = 10

#: An application pace is only measurable over a window at least this long.
#: A fortnight is the shortest span in which "applications per month" is a
#: description rather than an extrapolation.
MIN_DAYS_FOR_PACE = 14.0

#: A match score at or above this is where interviews actually start coming,
#: on the evidence this project has. Used only as a fallback when the user's
#: own history is too thin to compute their personal threshold.
DEFAULT_TARGET_MATCH = 75.0

_DAY = 86400.0


def wilson_interval(
    successes: int, trials: int, z: float = 1.96
) -> Optional[Tuple[float, float]]:
    """A 95% confidence interval for a proportion, as percentages.

    Wilson rather than the textbook normal approximation, because the
    textbook one is wrong exactly where this application lives: small
    samples and proportions near 0 or 1. On 0 offers from 8 applications the
    normal approximation returns the interval [0%, 0%] - it claims certainty
    that you will never receive an offer, from eight data points. Wilson
    returns [0%, 32%], which is the honest answer.
    """
    if trials <= 0:
        return None
    proportion = successes / float(trials)
    denominator = 1.0 + (z * z) / trials
    centre = (proportion + (z * z) / (2.0 * trials)) / denominator
    spread = z * math.sqrt(
        (proportion * (1.0 - proportion) + (z * z) / (4.0 * trials)) / trials
    )
    margin = spread / denominator
    return (
        round(max(0.0, centre - margin) * 100.0, 1),
        round(min(1.0, centre + margin) * 100.0, 1),
    )


def _rule_of_three(trials: int) -> Optional[float]:
    """95% upper bound on a rate when nothing has been observed yet.

    If an event has not happened in ``n`` independent tries, its probability
    is below ``3/n`` with 95% confidence. This is the one honest thing that
    can be said about an offer rate before the first offer arrives.

    Returns ``None`` below four trials, where the bound reaches 100% and
    stops being a statement: "your offer rate is below 100%" is true of
    everyone and tells the reader nothing.
    """
    if trials < 4:
        return None
    return round(min(1.0, 3.0 / trials) * 100.0, 1)


def _pct(numerator: int, denominator: int) -> Optional[str]:
    """A percentage string, or ``None`` when there is nothing to divide by.

    Zero applications is not a 0% interview rate. It is no rate at all, and
    printing "0%" invites the reader to conclude something has gone wrong
    with them rather than that they have not started.
    """
    if denominator <= 0:
        return None
    return "%d%%" % round(100.0 * numerator / denominator)


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 1)
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 1)


def _parse(timestamp: Any) -> Optional[datetime]:
    text = str(timestamp or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _first_event(record: Dict[str, Any], *events: str) -> Optional[datetime]:
    for entry in record.get("timeline") or []:
        if entry.get("event") in events:
            moment = _parse(entry.get("timestamp") or entry.get("date"))
            if moment is not None:
                return moment
    return None


def _has_event(record: Dict[str, Any], *events: str) -> bool:
    return any((entry.get("event") in events) for entry in record.get("timeline") or [])


def _progress(record: Dict[str, Any]) -> Dict[str, bool]:
    """How far one application actually got.

    Read from the event log first and the status second. Status alone cannot
    distinguish "rejected after an interview" from "rejected on paper", and
    those two say completely different things about what to change.
    """
    status = str(record.get("current_status") or "").lower()
    applied = _has_event(record, "application_sent") or status in (
        "sent", "interview", "rejected", "offer",
    )
    interviewed = _has_event(
        record, "interview_scheduled", "interview_completed"
    ) or status in ("interview", "offer")
    offered = _has_event(record, "offer_received") or status == "offer"
    return {
        "applied": applied,
        "interviewed": interviewed,
        "offered": offered,
        "rejected": _has_event(record, "rejected") or status == "rejected",
        "open": status not in ("rejected", "offer"),
    }


class ApplicationAnalytics:
    """Rates, patterns and - where the data allows it - a forecast.

    Args:
        tracker: Where history comes from. Injectable so tests need no
            database and no fixtures beyond a list of dictionaries.
    """

    label = "Application Analytics"

    def __init__(self, tracker: Any = None) -> None:
        self._tracker = tracker

    @property
    def tracker(self) -> Any:
        """The application store, imported on first use.

        Analytics never writes; it reads history from the tracker and derives
        everything else, so the stored record stays the single source of truth.
        """
        if self._tracker is None:
            from agents.application_tracker import application_tracker

            self._tracker = application_tracker
        return self._tracker

    def _history(self, user_id: str) -> List[Dict[str, Any]]:
        return self.tracker.get_application_history(user_id) or []

    # -- Metrics ---------------------------------------------------------

    def calculate_success_metrics(
        self, user_id: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Counts, rates, and how much to trust them."""
        records = self._history(user_id) if history is None else list(history)
        stages = [_progress(record) for record in records]

        total = len(records)
        applied = sum(1 for stage in stages if stage["applied"])
        interviews = sum(1 for stage in stages if stage["interviewed"])
        offers = sum(1 for stage in stages if stage["offered"])
        rejections = sum(1 for stage in stages if stage["rejected"])

        # Drafts are excluded from the denominator. An application never sent
        # cannot have led to an interview, and counting it as a failure to get
        # one would punish the user for having a shortlist.
        interview_interval = wilson_interval(interviews, applied)
        offer_interval = wilson_interval(offers, interviews)

        scores_applied = [
            float(record["match_score"])
            for record, stage in zip(records, stages)
            if stage["applied"] and record.get("match_score") is not None
        ]
        scores_interview = [
            float(record["match_score"])
            for record, stage in zip(records, stages)
            if stage["interviewed"] and record.get("match_score") is not None
        ]

        gaps_all = Counter()
        gaps_rejected = Counter()
        for record, stage in zip(records, stages):
            names = [str(name) for name in (record.get("gaps_identified") or [])]
            gaps_all.update(names)
            if stage["rejected"]:
                gaps_rejected.update(names)

        days = self._days_to_interview(records)

        metrics: Dict[str, Any] = {
            "total_applications": total,
            "applications_sent": applied,
            "interviews_scheduled": interviews,
            "interview_rate": _pct(interviews, applied),
            "offers_received": offers,
            "offer_rate": _pct(offers, interviews),
            "rejections": rejections,
            "still_open": sum(1 for stage in stages if stage["open"] and stage["applied"]),
            "avg_match_score_when_applied": _mean(scores_applied),
            "avg_match_score_when_interview": _mean(scores_interview),
            "best_job_type": self._best_job_type(records, stages),
            "common_gaps": [name for name, _ in gaps_all.most_common(5)],
            "gaps_in_rejections": [name for name, _ in gaps_rejected.most_common(5)],
            "days_to_interview": days["mean"],
            "days_to_interview_median": days["median"],
            "days_to_interview_observations": days["count"],
            # Everything below is the honesty apparatus. It is part of the
            # answer, not a footnote to it.
            "interview_rate_confidence_95": self._interval_text(interview_interval),
            "offer_rate_confidence_95": self._interval_text(offer_interval),
            "sample_size_warning": self._warning(applied, interviews),
        }

        if offers == 0 and applied > 0:
            metrics["offer_rate_upper_bound_95"] = self._bound_text(_rule_of_three(applied))
        return metrics

    @staticmethod
    def _interval_text(interval: Optional[Tuple[float, float]]) -> Optional[str]:
        if interval is None:
            return None
        return "%.0f%%-%.0f%%" % interval

    @staticmethod
    def _bound_text(bound: Optional[float]) -> Optional[str]:
        if bound is None:
            return None
        return "below %.0f%%" % bound

    @staticmethod
    def _warning(applied: int, interviews: int) -> Optional[str]:
        """Say plainly when the numbers above are too thin to act on."""
        if applied == 0:
            return "No applications sent yet, so there are no rates to report."
        if applied < MIN_SAMPLE_FOR_RATE:
            return (
                "Only %d application%s sent. Every rate on this page could "
                "change completely with the next one - treat them as a record "
                "of what happened, not as a measurement of how you are doing."
                % (applied, "" if applied == 1 else "s")
            )
        if interviews == 0:
            return (
                "No interviews yet from %d applications. That is a small "
                "enough number that it is not yet evidence of a problem."
                % applied
            )
        if interviews < MIN_SAMPLE_FOR_RATE:
            # The offer rate divides by interviews, not by applications, so it
            # can be resting on two data points while the interview rate above
            # it rests on twenty. Without this the reader sees "offer rate 0%"
            # in the same typeface as everything else and believes it.
            return (
                "The offer rate below is calculated on %d interview%s. That is "
                "too few to mean anything yet, however confident the "
                "percentage looks." % (interviews, "" if interviews == 1 else "s")
            )
        return None

    @staticmethod
    def _days_to_interview(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Days from sending to hearing back, over applications where both happened."""
        spans: List[float] = []
        for record in records:
            sent = _first_event(record, "application_sent")
            heard = _first_event(record, "interview_scheduled", "interview_completed")
            if sent is not None and heard is not None and heard >= sent:
                spans.append((heard - sent).total_seconds() / _DAY)
        return {"mean": _mean(spans), "median": _median(spans), "count": len(spans)}

    @staticmethod
    def _best_job_type(
        records: List[Dict[str, Any]], stages: List[Dict[str, bool]]
    ) -> Optional[str]:
        """The job title that has actually got this person interviews.

        ``None`` until at least two have. One interview does not identify a
        pattern, and naming a "best job type" off a single success would send
        someone chasing a coincidence.
        """
        titles = Counter(
            str(record.get("job_title") or "").strip().lower()
            for record, stage in zip(records, stages)
            if stage["interviewed"] and str(record.get("job_title") or "").strip()
        )
        if not titles:
            return None
        title, count = titles.most_common(1)[0]
        if count < 2:
            return None
        for record in records:
            if str(record.get("job_title") or "").strip().lower() == title:
                return str(record["job_title"]).strip()
        return None

    # -- Strategy --------------------------------------------------------

    def recommend_application_strategy(
        self, user_id: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """What to do next, derived from what has actually happened."""
        records = self._history(user_id) if history is None else list(history)
        metrics = self.calculate_success_metrics(user_id, records)
        stages = [_progress(record) for record in records]

        applied = metrics["applications_sent"]
        interviews = metrics["interviews_scheduled"]
        offers = metrics["offers_received"]

        situation = (
            "No applications yet."
            if not records
            else "Tracking %d application%s: %d sent, %d reached interview, %d offer%s."
            % (
                len(records),
                "" if len(records) == 1 else "s",
                applied,
                interviews,
                offers,
                "" if offers == 1 else "s",
            )
        )

        issue, recommendations, next_steps = self._diagnose(metrics, records, stages)

        return {
            "current_situation": situation,
            "issue": issue,
            "recommendations": recommendations,
            "next_steps": next_steps,
            "based_on": "%d application%s" % (len(records), "" if len(records) == 1 else "s"),
            "confidence": self._confidence(applied),
        }

    @staticmethod
    def _confidence(applied: int) -> str:
        if applied == 0:
            return "none - nothing to learn from yet"
        if applied < MIN_SAMPLE_FOR_RATE:
            return "low - too few applications to see a pattern"
        if applied < MIN_SAMPLE_FOR_FORECAST:
            return "moderate - a pattern is forming but could still be noise"
        return "reasonable for a personal history, which is still a small sample"

    def _diagnose(
        self,
        metrics: Dict[str, Any],
        records: List[Dict[str, Any]],
        stages: List[Dict[str, bool]],
    ) -> Tuple[Optional[str], List[str], List[str]]:
        """The one place that turns numbers into sentences.

        Every sentence here has to be traceable to a number above it. Advice
        that is true of everyone ("keep going, stay positive") is not advice.
        """
        applied = metrics["applications_sent"]
        interviews = metrics["interviews_scheduled"]
        offers = metrics["offers_received"]
        drafts = len(records) - applied
        recommendations: List[str] = []
        next_steps: List[str] = []

        if not records:
            return (
                None,
                ["Nothing tracked yet. Analyse a job, then create an application "
                 "to start building a history worth reading."],
                ["1. Run an analysis on a job you are interested in",
                 "2. Create an application from it",
                 "3. Come back once five or so have been sent"],
            )

        if drafts and not applied:
            return (
                "Applications are being created but not sent.",
                ["%d application%s sitting in draft and none sent. The tracker "
                 "can measure a lot of things, but not an application that never "
                 "went anywhere." % (drafts, "" if drafts == 1 else "s")],
                ["1. Send the drafts, or delete the ones you have thought better of"],
            )

        issue: Optional[str] = None
        applied_avg = metrics["avg_match_score_when_applied"]
        interview_avg = metrics["avg_match_score_when_interview"]

        # The central question: are applications turning into interviews?
        if applied >= MIN_SAMPLE_FOR_RATE and interviews == 0:
            issue = "Applications are not converting into interviews."
            recommendations.append(
                "%d sent, none reached interview. The 95%% confidence interval "
                "on your interview rate is %s, so the honest reading is that it "
                "is low, not that it is zero."
                % (applied, metrics["interview_rate_confidence_95"] or "unknown")
            )
            if applied_avg is not None and applied_avg < DEFAULT_TARGET_MATCH:
                recommendations.append(
                    "Your average match score when applying is %.0f%%. Applying "
                    "where the match is %.0f%%+ is the single change most likely "
                    "to move this." % (applied_avg, DEFAULT_TARGET_MATCH)
                )
        elif interviews:
            recommendations.append(
                "%d of %d applications reached interview (%s). On this many, the "
                "true rate is somewhere in %s."
                % (
                    interviews, applied, metrics["interview_rate"] or "n/a",
                    metrics["interview_rate_confidence_95"] or "an unknown range",
                )
            )
            if not offers and interviews >= 2:
                issue = "Interviews are happening but not converting."
                recommendations.append(
                    "You are getting in the room - %d times - and not yet through "
                    "it. That points at interview preparation rather than at which "
                    "jobs you are picking." % interviews
                )

        # Does the evidence support raising the bar? Only say so if the
        # interviewed applications really did score higher.
        if (
            applied_avg is not None
            and interview_avg is not None
            and interview_avg - applied_avg >= 5.0
        ):
            recommendations.append(
                "Applications that reached interview averaged %.0f%% against "
                "%.0f%% overall - a %.0f point difference. Aiming above %.0f%% "
                "is supported by your own history."
                % (interview_avg, applied_avg, interview_avg - applied_avg, interview_avg)
            )

        gap_advice = self._gap_advice(records, stages)
        if gap_advice:
            recommendations.append(gap_advice)

        days = metrics["days_to_interview_median"]
        if (
            days is not None
            and days >= 1.0
            and metrics["days_to_interview_observations"] >= 2
        ):
            # Below a day the sentence says nothing - "replies take a median
            # of 0 days, so silence before then is not news" is not advice.
            recommendations.append(
                "Replies have taken a median of %.0f days over %d applications, "
                "so silence before then is not news."
                % (days, metrics["days_to_interview_observations"])
            )

        if metrics["sample_size_warning"]:
            recommendations.append(metrics["sample_size_warning"])

        next_steps = self._next_steps(metrics, records, stages)
        return issue, recommendations, next_steps

    #: How much more common a gap must be among rejections than among
    #: everything else before it is worth naming. Twenty-five percentage
    #: points is arbitrary but not accidental: below that, the difference on
    #: a handful of applications is indistinguishable from chance.
    LIFT_THRESHOLD = 0.25

    @staticmethod
    def _discriminating_gap(
        records: List[Dict[str, Any]],
        stages: List[Dict[str, bool]],
    ) -> Optional[Tuple[str, int, int, int, int]]:
        """Find the gap that separates rejections from everything else.

        Returns ``(name, in_rejections, elsewhere, n_rejected, n_others)`` or
        ``None`` when no gap stands out. Both the recommendation text and the
        next-step list read this, so they cannot disagree about which skill
        matters - an earlier version computed them separately and printed
        "Kubernetes has the clearest link" directly above "close the gap that
        recurs most: LangGraph".
        """
        rejected = [
            record for record, stage in zip(records, stages) if stage["rejected"]
        ]
        others = [
            record for record, stage in zip(records, stages) if not stage["rejected"]
        ]
        if len(rejected) < 3:
            return None

        counts = Counter()
        for record in rejected:
            counts.update(str(name) for name in (record.get("gaps_identified") or []))

        for name, count in counts.most_common():
            if count < 3 or count < len(rejected) * 0.5:
                continue
            elsewhere = sum(
                1 for record in others if name in (record.get("gaps_identified") or [])
            )
            other_rate = (elsewhere / float(len(others))) if others else 0.0
            if count / float(len(rejected)) - other_rate < ApplicationAnalytics.LIFT_THRESHOLD:
                # Present everywhere, so it explains nothing.
                continue
            return name, count, elsewhere, len(rejected), len(others)
        return None

    @staticmethod
    def _gap_advice(
        records: List[Dict[str, Any]],
        stages: List[Dict[str, bool]],
    ) -> Optional[str]:
        """Name a skill only when it is disproportionately present in failures.

        The brief's example says "Learn LangGraph (appears in 6 rejections)".
        Appearing in six rejections is not on its own a reason to learn
        anything. If that skill is also missing from every application that
        *succeeded*, it is simply a skill you do not have, and it is doing no
        work in explaining the rejections.

        So the test is a comparison, not a count. On a first run of this
        module against realistic data it happily reported "LangGraph is
        missing in 3 of your 3 rejections (and in 9 that were not rejected)" -
        a sentence that sounds like a finding and contains none, because the
        skill was missing from all twelve applications.
        """
        found = ApplicationAnalytics._discriminating_gap(records, stages)
        if not found:
            return None
        name, count, elsewhere, n_rejected, n_others = found
        return (
            "%s is missing in %d of your %d rejections but only %d of the "
            "%d applications that were not rejected. That gap has the "
            "clearest link to an outcome."
            % (name, count, n_rejected, elsewhere, n_others)
        )

    @staticmethod
    def _next_steps(
        metrics: Dict[str, Any],
        records: List[Dict[str, Any]],
        stages: List[Dict[str, bool]],
    ) -> List[str]:
        steps: List[str] = []
        applied = metrics["applications_sent"]
        interviews = metrics["interviews_scheduled"]

        upcoming = [
            record
            for record, stage in zip(records, stages)
            if stage["interviewed"] and stage["open"]
        ]
        if upcoming:
            steps.append(
                "Prepare for the %d interview%s still live - that is the nearest "
                "thing to an offer you have."
                % (len(upcoming), "" if len(upcoming) == 1 else "s")
            )
        if applied < MIN_SAMPLE_FOR_RATE:
            steps.append(
                "Send %d more application%s before reading anything into the "
                "rates above."
                % (MIN_SAMPLE_FOR_RATE - applied, "" if MIN_SAMPLE_FOR_RATE - applied == 1 else "s")
            )
        found = ApplicationAnalytics._discriminating_gap(records, stages)
        if found:
            # The gap that separates rejections from the rest, not merely the
            # most frequent one - those are often different skills.
            steps.append("Close the gap that most often accompanies rejection: %s." % found[0])
        else:
            gaps = metrics["gaps_in_rejections"] or metrics["common_gaps"]
            if gaps:
                steps.append(
                    "Close the most common gap: %s. Nothing in the log yet "
                    "links it to an outcome - it is simply the one that keeps "
                    "coming up." % gaps[0]
                )
        if interviews and not metrics["offers_received"]:
            steps.append("Run the interview preparation step before the next one.")
        if not steps:
            steps.append("Keep the tracker current - the numbers are only as good as the log.")
        return ["%d. %s" % (index, text) for index, text in enumerate(steps, start=1)]

    # -- Forecast --------------------------------------------------------

    def predict_offer_probability(
        self, user_id: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """A forecast, or a plain statement that one cannot be made.

        Withholding the number is the feature. See the module docstring.
        """
        records = self._history(user_id) if history is None else list(history)
        metrics = self.calculate_success_metrics(user_id, records)

        applied = metrics["applications_sent"]
        interviews = metrics["interviews_scheduled"]
        offers = metrics["offers_received"]

        prediction: Dict[str, Any] = {
            "current_stats": {
                "applications_sent": applied,
                "interviews_scheduled": interviews,
                "offers_received": offers,
                "interview_rate": metrics["interview_rate"],
                "interview_rate_confidence_95": metrics["interview_rate_confidence_95"],
            },
            "offer_probability_next_month": None,
            "estimated_time_to_offer": None,
            "what_needs_to_happen": [],
            "basis": "",
        }

        if applied < MIN_SAMPLE_FOR_FORECAST or offers == 0:
            prediction["basis"] = self._why_no_forecast(applied, interviews, offers)
            bound = _rule_of_three(applied) if applied else None
            if bound is not None:
                prediction["offer_rate_upper_bound_95"] = (
                    "Per application, probably below %.0f%% - the strongest "
                    "statement %d applications with no offer will support."
                    % (bound, applied)
                )
            prediction["what_needs_to_happen"] = self._requirements(metrics)
            return prediction

        # Enough history to say something. The per-application offer rate,
        # applied to the pace this person has actually kept.
        rate = offers / float(applied)
        pace = self._applications_per_month(records)
        prediction["offer_rate_confidence_95"] = self._interval_text(
            wilson_interval(offers, applied)
        )
        prediction["what_needs_to_happen"] = self._requirements(metrics)

        if pace is None:
            # A month's worth of applying cannot be inferred from a few days
            # of it. Twenty applications sent in one sitting is not a pace of
            # twenty a month; it is one sitting, and projecting it forward
            # produced an "86% chance of an offer next month" in testing.
            prediction["basis"] = (
                "%d offer%s from %d applications, but they span %s - too short "
                "a window to read a monthly pace from. The per-application "
                "rate below is real; a monthly probability would be an "
                "extrapolation from a few days."
                % (
                    offers, "" if offers == 1 else "s", applied,
                    self._span_text(records),
                )
            )
            prediction["offer_rate_per_application"] = "%d%%" % round(rate * 100.0)
            return prediction

        expected = rate * pace
        probability = 1.0 - math.exp(-expected) if expected > 0 else 0.0

        prediction["offer_probability_next_month"] = "%d%%" % round(probability * 100.0)
        prediction["estimated_time_to_offer"] = self._time_to_offer(rate, pace)

        # The single percentage above is built on a rate that is itself
        # uncertain. Running the confidence bounds through the same
        # arithmetic shows how wide that makes it: one offer from twelve
        # applications yields "54%", but the honest span is 17%-98%, which
        # is a way of saying the number is not yet worth much.
        interval = wilson_interval(offers, applied)
        if interval is not None:
            low_p = 1.0 - math.exp(-(interval[0] / 100.0) * pace)
            high_p = 1.0 - math.exp(-(interval[1] / 100.0) * pace)
            prediction["offer_probability_confidence_95"] = "%d%%-%d%%" % (
                round(low_p * 100.0),
                round(high_p * 100.0),
            )

        prediction["basis"] = (
            "%d offer%s from %d applications at about %.1f applications a month. "
            "This is a projection of your own past rate, not a model of the job "
            "market, and it assumes you keep applying at the same pace to the "
            "same sort of role."
            % (offers, "" if offers == 1 else "s", applied, pace)
        )
        return prediction

    @staticmethod
    def _span_text(records: List[Dict[str, Any]]) -> str:
        moments = [
            _parse(record.get("created_date"))
            for record in records
            if _parse(record.get("created_date")) is not None
        ]
        if len(moments) < 2:
            return "a single day"
        days = int((max(moments) - min(moments)).total_seconds() / _DAY)
        return "a single day" if days < 1 else "%d day%s" % (days, "" if days == 1 else "s")

    @staticmethod
    def _why_no_forecast(applied: int, interviews: int, offers: int) -> str:
        if applied == 0:
            return (
                "No applications sent, so there is nothing to forecast from. A "
                "number here would be invented."
            )
        if offers == 0:
            return (
                "No offers yet, so there is no rate to project. %d application%s "
                "and %d interview%s tell you the process is moving; they do not "
                "tell you when an offer arrives, and any date given here would "
                "be a guess dressed as a prediction."
                % (
                    applied, "" if applied == 1 else "s",
                    interviews, "" if interviews == 1 else "s",
                )
            )
        return (
            "Only %d applications. A forecast needs at least %d before it is "
            "worth more than the paper it is printed on."
            % (applied, MIN_SAMPLE_FOR_FORECAST)
        )

    @staticmethod
    def _applications_per_month(records: List[Dict[str, Any]]) -> Optional[float]:
        """The pace actually kept, or ``None`` if it cannot be known yet.

        Requires at least a fortnight between the first application and the
        last. Below that there is no pace to measure - only a burst - and
        multiplying a burst up to a month is how a forecast becomes fiction.
        """
        moments = [
            _parse(record.get("created_date"))
            for record in records
            if _parse(record.get("created_date")) is not None
        ]
        if len(moments) < 2:
            return None
        span_days = (max(moments) - min(moments)).total_seconds() / _DAY
        if span_days < MIN_DAYS_FOR_PACE:
            return None
        return max(0.5, len(moments) * 30.0 / span_days)

    @staticmethod
    def _time_to_offer(rate: float, pace: float) -> Optional[str]:
        per_month = rate * pace
        if per_month <= 0:
            return None
        weeks = (1.0 / per_month) * 4.35
        if weeks <= 1:
            return "about a week at your current pace"
        if weeks > 52:
            return "more than a year at your current pace and rate"
        return "roughly %d weeks at your current pace" % round(weeks)

    @staticmethod
    def _requirements(metrics: Dict[str, Any]) -> List[str]:
        """What would actually have to change, named from the data."""
        needs: List[str] = []
        applied = metrics["applications_sent"]
        applied_avg = metrics["avg_match_score_when_applied"]

        if applied < MIN_SAMPLE_FOR_FORECAST:
            needs.append(
                "Send %d more applications - below that, nothing here is measurable."
                % (MIN_SAMPLE_FOR_FORECAST - applied)
            )
        if applied_avg is not None and applied_avg < DEFAULT_TARGET_MATCH:
            needs.append(
                "Raise the average match score you apply at from %.0f%% towards %.0f%%."
                % (applied_avg, DEFAULT_TARGET_MATCH)
            )
        gaps = metrics["gaps_in_rejections"] or metrics["common_gaps"]
        if gaps:
            needs.append("Close the recurring gap: %s." % ", ".join(gaps[:2]))
        if metrics["interviews_scheduled"] and not metrics["offers_received"]:
            needs.append("Convert one of the interviews you are already getting.")
        if not needs:
            needs.append("Keep the pace and the standard you are already applying at.")
        return needs


#: Shared instance reading from the configured tracker.
application_analytics = ApplicationAnalytics()
