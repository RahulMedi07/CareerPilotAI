"""Turn a list of gaps and a number of days into a day-by-day study plan.

The brief asks for a plan like "Day 1-2: LangGraph basics (4 hours), Day 3:
LangGraph advanced, Day 4: build a small project, Day 5: rest/practice". That
is the right shape, and it is what this produces. Three things about it are
worth stating up front, because each is a decision that could have gone the
other way.

**It will refuse a window that does not fit.** The obvious implementation of
``estimate_effort`` is ``total_hours / available_days``. Ask it for thirty days
of Kubernetes in two days and it returns "38 hours a day" without blinking - a
number that is arithmetically correct, physically impossible, and worse than no
answer because it looks like a plan. Anything above
:data:`MAX_SUSTAINABLE_HOURS` is reported as not fitting, with the number of
days that would fit instead.

**It does not invent resources.** The brief asks for YouTube tutorials and
Medium articles. This module has no verified URL for either, and the rule in
this codebase is that a confidently wrong link costs more trust than a missing
one. So it reuses the nineteen documentation links from
:mod:`agents.gap_detector` - each of which was actually requested and returned
200 before being written down - and for anything else it names *what to search
for* rather than fabricating a link to it. :meth:`find_best_resources` reports
the categories it cannot fill rather than quietly returning a short list.

**It schedules consolidation, not just contact hours.** A plan that fills every
day to the brim is the plan people abandon on day three. Longer paths get a
lighter review day rather than new material, which is also when what you
learned earlier actually sticks.

The hours conversion is the one soft number here, and it is stated rather than
buried: :data:`PART_TIME_HOURS_PER_DAY` treats the gap detector's
``learning_time_days`` - which it defines as calendar days of part-time study -
as two hours of real work each. Halving the days therefore doubles the daily
load, which is the honest arithmetic even when the result is unwelcome.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from agents.gap_detector import (
    _DOC_URLS,
    _PRACTICE_PROJECTS,
    _RESOURCES,
    BASE_LEARNING_DAYS,
    CRITICAL,
    DEFAULT_LEARNING_DAYS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

#: What the gap detector's "calendar days of part-time study" is worth in
#: actual hours at the keyboard. Everything else here is derived from this, so
#: it is a constant rather than a magic 2 scattered through the arithmetic.
PART_TIME_HOURS_PER_DAY = 2.0

#: Above this, a schedule stops being a schedule. Nobody sustains nine hours a
#: day of new material alongside a job, and a plan that assumes they will is a
#: plan that fails on day two and takes the candidate's confidence with it.
MAX_SUSTAINABLE_HOURS = 8.0

#: Above this the plan still fits, but it is worth saying out loud that it is
#: demanding. Below it, no comment is needed.
COMFORTABLE_HOURS = 4.0

#: Review days start appearing in plans at least this long. Shorter than this
#: and a rest day is a meaningful fraction of the whole window.
MIN_DAYS_FOR_REVIEW = 5

#: Every Nth day is consolidation rather than new material.
REVIEW_EVERY = 4

EASY = "EASY"
MEDIUM = "MEDIUM"
HARD = "HARD"

#: Phase names, in the order a skill is actually learned.
_PHASE_BASICS = "basics"
_PHASE_DEEPER = "deeper"
_PHASE_BUILD = "build"
_PHASE_REVIEW = "review"

_PHASE_DIFFICULTY = {
    _PHASE_BASICS: EASY,
    _PHASE_DEEPER: MEDIUM,
    _PHASE_BUILD: HARD,
    _PHASE_REVIEW: EASY,
}

#: The resource categories the brief asks for, and whether this module can
#: honestly fill each one. Reported as-is by `find_best_resources` so the gap
#: between what was asked for and what exists is visible rather than papered
#: over with plausible-looking links.
_CATEGORIES = ("official_docs", "guided_resources", "practice_project")
_UNVERIFIED_CATEGORIES = ("youtube", "articles")


def _canonical(skill: str) -> str:
    """Lowercase key used by the gap detector's lookup tables."""
    return str(skill or "").strip().lower()


class LearningPathAgent:
    """Builds day-by-day study plans from gaps.

    Stateless; the module-level :data:`learning_path_agent` is the shared
    instance, and constructing another is cheap.
    """

    label = "Learning Path"

    # -- Resources --------------------------------------------------------

    def find_best_resources(self, gap_skill: str) -> Dict[str, Any]:
        """The best *verified* resources for one skill.

        Returns the official documentation URL when one has been checked, the
        curated named starting points, and one project to build. ``missing``
        names the categories the brief asked for that could not be filled
        honestly - which is the point of returning it rather than silently
        shipping a shorter list.
        """
        key = _canonical(gap_skill)
        docs = _DOC_URLS.get(key)
        guided = list(_RESOURCES.get(key) or [])
        project = _PRACTICE_PROJECTS.get(key)

        missing = [
            name
            for name, value in (
                ("official_docs", docs),
                ("guided_resources", guided),
                ("practice_project", project),
            )
            if not value
        ]

        return {
            "skill": gap_skill,
            "official_docs": docs,
            "guided_resources": guided,
            "practice_project": project,
            "search_for": None if docs else self._search_hint(gap_skill),
            "missing": missing,
            # Named, not linked, and the reason is given rather than implied.
            "unverified_categories": list(_UNVERIFIED_CATEGORIES),
            "note": (
                "Video courses and blog posts are deliberately not linked: no "
                "URL for them has been verified, and a confidently wrong link "
                "is worse than none. Search the terms above instead."
            ),
        }

    @staticmethod
    def _search_hint(skill: str) -> str:
        return "%s official documentation" % skill

    # -- Effort -----------------------------------------------------------

    def estimate_effort(
        self,
        gap_skill: Any,
        available_days: int,
        learning_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """How many hours a day this skill needs to fit the window.

        ``gap_skill`` may be a gap dict from the detector (in which case its
        ``learning_time_days`` is used) or a bare skill name with
        ``learning_days`` supplied alongside.

        Returns ``fits: False`` rather than an impossible number when the
        window is too short. A caller that wants the plan anyway can read
        ``days_needed`` and ask again.
        """
        name, needed = self._skill_and_days(gap_skill, learning_days)
        total_hours = needed * PART_TIME_HOURS_PER_DAY

        try:
            days = int(available_days)
        except (TypeError, ValueError):
            days = 0

        if days <= 0:
            return {
                "skill": name,
                "fits": False,
                "hours_per_day": None,
                "total_hours": round(total_hours, 1),
                "days_needed": needed,
                "reason": "No days were made available, so nothing can be scheduled.",
            }

        hours_per_day = total_hours / float(days)

        if hours_per_day > MAX_SUSTAINABLE_HOURS:
            return {
                "skill": name,
                "fits": False,
                "hours_per_day": None,
                "required_hours_per_day": round(hours_per_day, 1),
                "total_hours": round(total_hours, 1),
                "days_needed": needed,
                "days_available": days,
                "reason": (
                    "%s needs about %.0f hours. In %d day%s that is %.1f hours "
                    "a day, which is not a schedule anyone keeps. It needs "
                    "about %d days at a sustainable pace."
                    % (
                        name,
                        total_hours,
                        days,
                        "" if days == 1 else "s",
                        hours_per_day,
                        needed,
                    )
                ),
            }

        result: Dict[str, Any] = {
            "skill": name,
            "fits": True,
            "hours_per_day": round(hours_per_day, 1),
            "total_hours": round(total_hours, 1),
            "days_needed": needed,
            "days_available": days,
            "reason": (
                "%.0f hours of study spread over %d day%s."
                % (total_hours, days, "" if days == 1 else "s")
            ),
        }
        if hours_per_day > COMFORTABLE_HOURS:
            result["warning"] = (
                "%.1f hours a day alongside a job is demanding. It is "
                "achievable for a short stretch and not much longer."
                % hours_per_day
            )
        return result

    @staticmethod
    def _skill_and_days(gap: Any, learning_days: Optional[int]) -> tuple:
        """Pull ``(name, days)`` out of a gap dict or a bare skill name."""
        if isinstance(gap, dict):
            name = str(gap.get("skill") or gap.get("skill_id") or "this skill")
            days = gap.get("learning_time_days")
        else:
            name = str(gap or "this skill")
            days = learning_days

        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 0

        if days <= 0:
            # A caller who names a skill without costing it is not saying "one
            # day". Assuming that made estimate_effort agree to almost any
            # window: CI/CD in two days came back as a comfortable two hours,
            # when the gap detector's own table puts it at ten days. Use that
            # table, and its documented default for anything not in it.
            days = BASE_LEARNING_DAYS.get(
                name.strip().lower(), DEFAULT_LEARNING_DAYS
            )
        return name, max(days, 1)

    # -- Plans ------------------------------------------------------------

    def create_learning_path(
        self,
        gaps: Sequence[Any],
        available_days: int = 14,
        critical_only: bool = True,
    ) -> Dict[str, Any]:
        """A day-by-day plan across several gaps.

        Time is divided between skills in proportion to what each needs, so a
        ten-day gap gets roughly five times the days of a two-day one rather
        than an equal slice. Skills are taken in order of how long they take,
        shortest first: finishing something early is what keeps a two-week plan
        alive to week two.
        """
        selected = self._select(gaps, critical_only)
        try:
            window = int(available_days)
        except (TypeError, ValueError):
            window = 0

        if not selected:
            return self._empty(
                window,
                "No gaps were passed in, so there is nothing to schedule.",
            )
        if window <= 0:
            return self._empty(
                window,
                "No days were made available, so nothing can be scheduled.",
            )

        needed = sum(days for _, days in selected)
        total_hours = needed * PART_TIME_HOURS_PER_DAY
        hours_per_day = total_hours / float(window)

        if hours_per_day > MAX_SUSTAINABLE_HOURS:
            # Say what *would* fit rather than returning nothing. A plan for
            # the two skills that are reachable beats a refusal for all four.
            reachable = self._reachable(selected, window)
            plan = self._empty(
                window,
                "%s need about %.0f hours between them. In %d days that is "
                "%.1f hours a day, which is not a plan anyone follows."
                % (
                    self._names(selected),
                    total_hours,
                    window,
                    hours_per_day,
                ),
            )
            plan["fits"] = False
            plan["days_needed"] = needed
            plan["required_hours_per_day"] = round(hours_per_day, 1)
            plan["skills_that_would_fit"] = [name for name, _ in reachable]
            plan["skills_out_of_reach"] = [
                name for name, _ in selected if name not in dict(reachable)
            ]
            return plan

        # Only stretch across the whole window when the work actually needs
        # it. Spreading nine days of study over fourteen does not teach
        # anything extra - it just invents four days of "in more depth" to
        # fill the calendar, and a plan padded with filler is one you stop
        # believing on day six. Finish in nine and keep the rest as slack.
        span = min(window, needed)
        if needed <= window:
            hours_per_day = PART_TIME_HOURS_PER_DAY

        days = self._schedule(selected, span)
        skills = [name for name, _ in selected]

        plan = {
            "total_days": len(days),
            "daily_commitment_hours": round(hours_per_day, 1),
            "total_hours": round(total_hours, 1),
            "days": days,
            "skills": skills,
            "fits": True,
            "days_needed": needed,
            "days_available": window,
            "days_spare": max(0, window - len(days)),
            "summary": (
                "%d day%s covering %s at about %.1f hours a day."
                % (
                    len(days),
                    "" if len(days) == 1 else "s",
                    self._names(selected),
                    hours_per_day,
                )
            ),
        }
        if window > len(days):
            plan["slack_note"] = (
                "That leaves %d day(s) of the %d-day window spare - room for "
                "the days this slips, because some of them will."
                % (window - len(days), window)
            )
        if hours_per_day > COMFORTABLE_HOURS:
            plan["warning"] = (
                "%.1f hours a day alongside a job is demanding. Dropping the "
                "longest skill would bring it down." % hours_per_day
            )
        if needed > window:
            plan["compressed"] = True
            plan["note"] = (
                "This compresses about %d days of part-time study into %d. It "
                "fits, but there is no slack in it." % (needed, window)
            )
        return plan

    # -- Plan construction ------------------------------------------------

    def _select(self, gaps: Sequence[Any], critical_only: bool) -> List[tuple]:
        """``[(name, days)]``, shortest first, filtered to what matters."""
        chosen: List[tuple] = []
        for gap in gaps or []:
            if (
                critical_only
                and isinstance(gap, dict)
                and gap.get("importance")
                and str(gap.get("importance")).upper() != CRITICAL
            ):
                continue
            name, days = self._skill_and_days(gap, None)
            chosen.append((name, days))
        # Shortest first: an early finish is what sustains the rest.
        chosen.sort(key=lambda pair: (pair[1], pair[0]))
        return chosen

    @staticmethod
    def _reachable(selected: List[tuple], window: int) -> List[tuple]:
        """The longest prefix of ``selected`` that fits the window."""
        budget = window * (MAX_SUSTAINABLE_HOURS / PART_TIME_HOURS_PER_DAY)
        out: List[tuple] = []
        spent = 0.0
        for name, days in selected:
            if spent + days > budget:
                break
            out.append((name, days))
            spent += days
        return out

    @staticmethod
    def _names(selected: List[tuple]) -> str:
        names = [name for name, _ in selected]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]

    def _schedule(self, selected: List[tuple], window: int) -> List[Dict[str, Any]]:
        """Lay the skills out across the days, proportionally."""
        allocations = self._allocate(selected, window)
        hours = (
            sum(days for _, days in selected) * PART_TIME_HOURS_PER_DAY
        ) / float(window)

        days: List[Dict[str, Any]] = []
        day_number = 1
        for (name, _), share in zip(selected, allocations):
            phases = self._phases(share)
            for index, phase in enumerate(phases):
                is_review = phase == _PHASE_REVIEW
                # A phase spanning several days is one block, and saying
                # "Learn LangGraph basics" on two consecutive lines reads as a
                # bug rather than as a two-day block. The brief's own example
                # writes it as a range ("Day 1-2"); this says which part of it
                # each day is.
                span = phases.count(phase)
                part = phases[: index + 1].count(phase)
                focus = self._focus(name, phase)
                if span > 1:
                    focus += " (day %d of %d)" % (part, span)
                days.append(
                    {
                        "day": day_number,
                        "skill": name,
                        "focus": focus,
                        "time_hours": round(
                            hours * (0.5 if is_review else 1.0), 1
                        ),
                        "resources": self._day_resources(name, phase),
                        "deliverable": self._deliverable(name, phase),
                        "difficulty": _PHASE_DIFFICULTY[phase],
                        "phase": phase,
                    }
                )
                day_number += 1
        return days

    @staticmethod
    def _allocate(selected: List[tuple], window: int) -> List[int]:
        """Split ``window`` days between skills in proportion to need.

        Every skill gets at least one day - a skill allotted zero days is not
        in the plan, and silently dropping it would be the plan lying about
        its own coverage.
        """
        total = sum(days for _, days in selected) or 1
        shares = [
            max(1, int(round(window * (days / float(total)))))
            for _, days in selected
        ]

        # Rounding and the floor of 1 can overshoot the window. Trim from the
        # longest allocation, which is the one that misses a day least.
        while sum(shares) > window and max(shares) > 1:
            shares[shares.index(max(shares))] -= 1
        # Or undershoot: hand the spare days to the skill that needs most.
        while sum(shares) < window:
            longest = max(range(len(shares)), key=lambda i: selected[i][1])
            shares[longest] += 1
        return shares

    @staticmethod
    def _phases(days: int) -> List[str]:
        """Which phase each day of a skill's allocation is spent in."""
        if days <= 1:
            return [_PHASE_BASICS]
        if days == 2:
            return [_PHASE_BASICS, _PHASE_BUILD]
        if days == 3:
            return [_PHASE_BASICS, _PHASE_DEEPER, _PHASE_BUILD]

        phases: List[str] = [_PHASE_BASICS, _PHASE_BASICS, _PHASE_DEEPER]
        while len(phases) < days - 1:
            # Consolidation days, so the plan survives contact with a week of
            # work. New material every single day is how plans get abandoned.
            if (
                len(phases) + 1
            ) % REVIEW_EVERY == 0 and days >= MIN_DAYS_FOR_REVIEW:
                phases.append(_PHASE_REVIEW)
            else:
                phases.append(_PHASE_DEEPER)
        phases.append(_PHASE_BUILD)
        return phases[:days]

    @staticmethod
    def _focus(skill: str, phase: str) -> str:
        return {
            _PHASE_BASICS: "Learn %s basics" % skill,
            _PHASE_DEEPER: "%s in more depth" % skill,
            _PHASE_BUILD: "Build something small with %s" % skill,
            _PHASE_REVIEW: "Review and practise %s" % skill,
        }[phase]

    def _day_resources(self, skill: str, phase: str) -> List[str]:
        found = self.find_best_resources(skill)
        if phase == _PHASE_BUILD:
            project = found["practice_project"]
            return [project] if project else ["Build the smallest useful thing"]
        if phase == _PHASE_REVIEW:
            return ["Revisit what you built; redo the parts you had to look up"]

        resources = list(found["guided_resources"])
        if found["official_docs"]:
            resources.insert(0, found["official_docs"])
        elif found["search_for"]:
            resources.append("Search: %s" % found["search_for"])
        return resources[:3]

    @staticmethod
    def _deliverable(skill: str, phase: str) -> str:
        return {
            _PHASE_BASICS: "Explain what %s does and when to reach for it" % skill,
            _PHASE_DEEPER: "Work through a guided example without copying it",
            _PHASE_BUILD: "Something running that you could demo",
            _PHASE_REVIEW: "The parts you had to look up, from memory",
        }[phase]

    @staticmethod
    def _empty(window: int, reason: str) -> Dict[str, Any]:
        return {
            "total_days": 0,
            "daily_commitment_hours": 0.0,
            "total_hours": 0.0,
            "days": [],
            "skills": [],
            "fits": False,
            "days_available": max(window, 0),
            "summary": reason,
            "reason": reason,
        }


#: Shared instance.
learning_path_agent = LearningPathAgent()
