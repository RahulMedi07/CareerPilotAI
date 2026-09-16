"""Turn a raw advert into something worth reading, and sort a pile of them.

The scraper hands back prose. This module runs it through the job analyser,
pulls out the few facts a candidate scans for first - salary, seniority,
whether it is really remote - and then buckets a whole search by how well it
fits the person doing the searching.

Two rules govern everything here.

**Absence is reported as absence.** Most adverts do not state a salary. The
honest answer is then ``None``, not a guessed band: a candidate who sees
"80k-120k" has been told something, and if we inferred it from the job title
we have told them something we made up. Every extracted field is either
quoted from the advert or missing.

**Difficulty is about the advert, not the candidate.** A role is HARD because
it demands twelve years and a doctorate, not because the reader lacks them.
Fit is a separate axis, computed separately, and mixing the two would produce
the nonsense of a junior role marked "easy" for someone unqualified for it.

Threading is used for batch work because the cost is almost entirely waiting -
the analyser is CPU-light and the LLM call, when enabled, is network-bound.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

from utils.logger import get_logger
from utils.validation import as_dict, as_float, as_int, as_list

logger = get_logger(__name__)

__all__ = [
    "JobEnricher",
    "job_enricher",
    "EASY",
    "MEDIUM",
    "HARD",
    "CATEGORIES",
]

EASY = "EASY"
MEDIUM = "MEDIUM"
HARD = "HARD"

#: Fit buckets, in the order a candidate should read them.
CATEGORIES = ("perfect_match", "good_fit", "stretch_goal", "learning_needed")

PERFECT_MATCH_MIN = 80.0
GOOD_FIT_MIN = 60.0
STRETCH_GOAL_MIN = 40.0

#: Below this confidence the advert was too thin to place in the top band.
#: Mirrored in ``JobCard.tsx``, which greys the percentage at the same line.
LOW_CONFIDENCE_MAX = 60.0

#: Enough workers to overlap the waiting, few enough to stay polite if any of
#: them ends up making a network call.
DEFAULT_MAX_WORKERS = 10

# --- Salary ----------------------------------------------------------------

#: Matches the ways adverts actually write pay. Deliberately narrow: it is
#: better to miss a salary than to report a version number as one.
_SALARY_RANGE = re.compile(
    r"""(?ix)
    (?P<currency>[$\u00a3\u20ac\u20b9]|USD|EUR|GBP|INR|Rs\.?)?\s?
    (?P<low>\d{4,7}|\d{1,3}(?:[,\u202f]\d{3})*(?:\.\d+)?|\d{2,3}(?:\.\d+)?)\s?
    (?P<lowunit>k|K|lakh|lakhs|LPA)?\s?
    (?:-|\u2013|\u2014|\bto\b)\s?
    (?P<currency2>[$\u00a3\u20ac\u20b9]|USD|EUR|GBP|INR|Rs\.?)?\s?
    (?P<high>\d{4,7}|\d{1,3}(?:[,\u202f]\d{3})*(?:\.\d+)?|\d{2,3}(?:\.\d+)?)\s?
    (?P<highunit>k|K|lakh|lakhs|LPA)?
    """
)

#: A salary must look like money, not like a date range or a version bump.
#:
#: The symbols are a separate alternative rather than members of the
#: word-boundary group. ``\b\$\b`` can never match, because ``$`` is not a
#: word character and ``\b`` needs one on each side - so every symbol in the
#: group was dead weight and an advert reading "Remote role. $80k-$120k" was
#: reported as stating no salary at all.
_SALARY_CONTEXT = re.compile(
    r"(?i)(?:\b(?:salary|compensation|pay|package|remuneration|ctc|base|"
    r"offer(?:ing)?|usd|eur|gbp|inr|lpa|lakh|lakhs)\b|[$\u00a3\u20ac\u20b9])"
)

#: Nouns that turn a number into a count rather than a sum of money. The word
#: "salary" appearing earlier in the sentence is not enough on its own:
#: "Salary depends. We have 10000-20000 users" was being reported as a pay
#: band of 10,000-20,000.
_COUNT_NOUN_AFTER = re.compile(
    r"(?i)^\s*(?:\+\s*)?(users?|customers?|clients?|employees?|engineers?|"
    r"people|developers?|companies|teams?|seats?|licen[cs]es?|requests?|rows?|"
    r"records?|documents?|items?|products?|students?|members?|hours?|days?|"
    r"weeks?|months?|years?|sq\.?\s?ft|kms?|miles?)\b"
)

_REMOTE_YES = re.compile(
    r"(?i)\b(fully[- ]remote|100%\s*remote|remote[- ]first|work from home|wfh|"
    r"remote\b(?!\s*(?:not|no)\b))"
)
_REMOTE_NO = re.compile(
    r"(?i)\b(on[- ]?site|in[- ]office|no remote|not remote|hybrid|"
    r"office[- ]based|in person)\b"
)


class JobEnricher:
    """Analyses adverts and groups them by fit."""

    label = "Job Enricher"

    def __init__(
        self,
        analyzer: Any = None,
        matcher: Any = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        """Both collaborators are injectable so tests need no LLM and no model."""
        self._analyzer = analyzer
        self._matcher = matcher
        self.max_workers = max(1, as_int(max_workers, DEFAULT_MAX_WORKERS))

    # -- Collaborators, imported late so this module stays cheap ---------

    @property
    def analyzer(self) -> Any:
        """The job analyzer, imported on first use.

        Enrichment does not reimplement requirement extraction; it asks the
        analyzer, so there is one definition of what a required skill is.
        """
        if self._analyzer is None:
            from agents.job_analyzer import job_analyzer_agent

            self._analyzer = job_analyzer_agent
        return self._analyzer

    @property
    def matcher(self) -> Any:
        """The match calculator, imported on first use.

        Scoring an advert against a resume happens in exactly one place. This
        module adds ``match_to_user`` by calling that, never by scoring itself.
        """
        if self._matcher is None:
            from agents.match_calculator import match_calculator

            self._matcher = match_calculator
        return self._matcher

    # -- Single job ------------------------------------------------------

    def enrich_job(
        self,
        job_posting: Dict[str, Any],
        resume_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add an ``analysis`` block to one advert.

        The original record is never mutated - the caller may be holding it in
        a list it iterates again - and it is never replaced either: enrichment
        that loses the advert's ``url`` would strip the attribution the source
        requires.

        Passing ``resume_data`` additionally scores the advert against the
        candidate and fills ``match_to_user``.
        """
        job = as_dict(job_posting, "job_posting")
        text = self._job_text(job)

        enriched = dict(job)

        if not text.strip():
            enriched["analysis"] = _empty_analysis("the advert had no readable text")
            enriched["match_to_user"] = None
            return enriched

        try:
            analysis = as_dict(self.analyzer.analyze(text), "analysis")
        except Exception as exc:  # noqa: BLE001 - one bad advert must not stop a batch
            logger.warning("Could not analyse %r: %s", job.get("title"), exc)
            enriched["analysis"] = _empty_analysis("analysis failed: %s" % exc)
            enriched["match_to_user"] = None
            return enriched

        analysis["difficulty"] = self._difficulty(analysis)
        analysis["estimated_salary_range"] = self._salary(text)
        analysis["remote"] = self._remote(text, job)
        analysis["skill_breakdown"] = self._skill_breakdown(analysis)
        analysis["source_terms"] = _terms_for(job.get("source"))

        enriched["analysis"] = analysis
        enriched["match_to_user"] = None

        if resume_data:
            enriched["match_to_user"] = self._match(resume_data, analysis)

        return enriched

    def _job_text(self, job: Dict[str, Any]) -> str:
        """Title and company are part of the advert and carry real signal."""
        parts = [
            str(job.get("title") or ""),
            str(job.get("company") or ""),
            str(job.get("description") or ""),
        ]
        return "\n".join(p for p in parts if p.strip())

    # -- Derived fields --------------------------------------------------

    def _difficulty(self, analysis: Dict[str, Any]) -> str:
        """How demanding the advert is, on its own terms.

        Years asked for dominates, because it is the one requirement a
        candidate cannot close by studying at the weekend. Breadth of the
        stack and an explicitly senior title nudge it.
        """
        years = as_float(analysis.get("experience_years"), 0.0)
        required = len(as_list(analysis.get("required_skills")))
        # The analyzer's fallback path often leaves `seniority` blank, and the
        # title usually says it outright. Reading both stops a "Senior AI
        # Engineer" being reported as EASY simply because one field was empty.
        seniority = "%s %s" % (
            str(analysis.get("seniority") or ""),
            str(analysis.get("title") or ""),
        )
        seniority = seniority.lower()

        score = 0
        if years >= 8:
            score += 3
        elif years >= 5:
            score += 2
        elif years >= 3:
            score += 1

        if required >= 12:
            score += 2
        elif required >= 7:
            score += 1

        if any(word in seniority for word in ("principal", "staff", "lead", "senior")):
            score += 1
        elif any(word in seniority for word in ("junior", "intern", "graduate", "entry")):
            score -= 1

        if score >= 4:
            return HARD
        if score >= 2:
            return MEDIUM
        return EASY

    def _salary(self, text: str) -> Optional[str]:
        """The pay range the advert states, or ``None``.

        Most adverts do not state one. Returning ``None`` is the whole point:
        an invented band is worse than a blank, because the candidate will
        plan around it and find out at the offer stage.
        """
        for match in _SALARY_RANGE.finditer(text):
            window = text[max(0, match.start() - 60) : match.end() + 30]
            if not _SALARY_CONTEXT.search(window):
                continue
            if _COUNT_NOUN_AFTER.match(text[match.end() : match.end() + 24]):
                continue

            low_raw, high_raw = match.group("low"), match.group("high")
            low = as_float(low_raw.replace(",", "").replace("\u202f", ""), 0.0)
            high = as_float(high_raw.replace(",", "").replace("\u202f", ""), 0.0)
            if low <= 0 or high <= low:
                continue

            unit = (match.group("highunit") or match.group("lowunit") or "").lower()
            currency = (match.group("currency") or match.group("currency2") or "").strip()

            # "2020 - 2024" is a date range, and "3 - 5" next to the word
            # "salary" is still not a salary.
            if not unit and high < 1000 and not currency:
                continue
            if not unit and 1900 <= low <= 2100 and 1900 <= high <= 2100:
                continue

            # "k" reads naturally on both figures ("90k-130k"), but a word
            # unit does not: "15lpa-25lpa" is not how anyone writes it.
            if unit in ("lakh", "lakhs", "lpa"):
                return ("%s%s-%s %s" % (
                    currency, _trim(low), _trim(high), unit.upper()
                )).strip()
            return (
                "%s%s%s-%s%s"
                % (currency, _trim(low), unit, _trim(high), unit)
            ).strip()
        return None

    def _remote(self, text: str, job: Dict[str, Any]) -> Optional[bool]:
        """True, False, or None when the advert does not say."""
        flag = job.get("remote")
        if isinstance(flag, bool):
            return flag

        location = str(job.get("location") or "").lower()
        if "remote" in location or "anywhere" in location:
            return True

        if _REMOTE_NO.search(text):
            return False
        if _REMOTE_YES.search(text):
            return True
        return None

    def _skill_breakdown(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Split the requirements into the shapes a reader compares against."""
        required = as_list(analysis.get("required_skills"))
        preferred = as_list(analysis.get("preferred_skills"))
        stack = as_list(analysis.get("tech_stack"))
        return {
            "required": required,
            "preferred": preferred,
            "tech_stack": stack,
            "required_count": len(required),
            "preferred_count": len(preferred),
            "total_distinct": len({str(s).lower() for s in required + preferred + stack}),
        }

    def _match(
        self, resume_data: Dict[str, Any], analysis: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            result = as_dict(
                self.matcher.calculate_match(resume_data, analysis), "match"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not score advert against resume: %s", exc)
            return None

        # ``overall_match`` is None when the advert could not be scored at all,
        # and that has to survive the trip to the browser. Defaulting it to 0.0
        # here -- which is what this line used to do -- turned "we could not
        # tell" into "you are a 0% match" on the card, filed the advert under
        # "Learning needed" instead of "Not scored", and did it in the one
        # place the rest of the app is careful about.
        raw_score = result.get("overall_match")
        score = None if raw_score is None else as_float(raw_score, 0.0)
        matched = as_list(result.get("matched_skills"))
        missing = as_list(result.get("missing_skills"))

        # The calculator scores how well the advert matches and, separately,
        # how much of the advert it managed to read. Dropping the second turned
        # "the one skill we found, you have" into a confident "100% match".
        raw_confidence = result.get("confidence")
        confidence = None if raw_confidence is None else as_float(raw_confidence, 0.0)
        return {
            "score": None if score is None else round(score, 1),
            "percentage": "Not scored" if score is None else "%d%%" % round(score),
            "confidence": None if confidence is None else round(confidence, 1),
            "recommendation": result.get("recommendation"),
            "matched_skills": matched,
            "missing_skills": missing,
            "reasons": _match_reasons(score, matched, missing, analysis),
        }

    # -- Batch -----------------------------------------------------------

    def batch_enrich_jobs(
        self,
        jobs: Sequence[Dict[str, Any]],
        resume_data: Optional[Dict[str, Any]] = None,
        max_workers: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Enrich many adverts at once, preserving input order.

        Order is restored explicitly after the pool returns. Completion order
        is arbitrary, and a search whose results reshuffle on every call for
        no visible reason is a bug report waiting to happen.

        One advert failing costs that advert only; the rest of the batch is
        still returned.
        """
        items = [j for j in as_list(jobs) if isinstance(j, dict)]
        if not items:
            return []

        workers = max(1, as_int(max_workers, self.max_workers))
        workers = min(workers, len(items))

        if workers == 1:
            return [self.enrich_job(job, resume_data) for job in items]

        results: List[Optional[Dict[str, Any]]] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.enrich_job, job, resume_data): index
                for index, job in enumerate(items)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Enrichment failed for advert %d: %s", index, exc)
                    fallback = dict(items[index])
                    fallback["analysis"] = _empty_analysis("enrichment failed: %s" % exc)
                    fallback["match_to_user"] = None
                    results[index] = fallback

        logger.info("Enriched %d advert(s) with %d worker(s)", len(items), workers)
        return [r for r in results if r is not None]

    # -- Categorisation --------------------------------------------------

    def categorize_jobs(
        self, enriched_jobs: Sequence[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Bucket adverts by how well they fit the candidate.

        An advert with no match score cannot be placed on a fit scale, so it
        goes to ``unscored`` rather than being quietly dropped or - worse -
        defaulted to zero and presented as a poor fit it was never measured
        against.
        """
        buckets: Dict[str, List[Dict[str, Any]]] = {name: [] for name in CATEGORIES}
        buckets["unscored"] = []

        for job in as_list(enriched_jobs):
            if not isinstance(job, dict):
                continue
            match = job.get("match_to_user")
            if not isinstance(match, dict) or match.get("score") is None:
                buckets["unscored"].append(job)
                continue

            score = as_float(match.get("score"), 0.0)
            confidence = match.get("confidence")
            barely_read = (
                confidence is not None
                and as_float(confidence, 0.0) < LOW_CONFIDENCE_MAX
            )

            # "Perfect match" is a promise to the reader, and an advert we
            # could barely read has not earned it however the arithmetic came
            # out. A German-language posting yielding one legible skill scored
            # 100 and was filed here, two lines under a filter chip counting it
            # as a perfect match.
            if score >= PERFECT_MATCH_MIN and not barely_read:
                buckets["perfect_match"].append(job)
            elif score >= GOOD_FIT_MIN:
                buckets["good_fit"].append(job)
            elif score >= STRETCH_GOAL_MIN:
                buckets["stretch_goal"].append(job)
            else:
                buckets["learning_needed"].append(job)

        for name in buckets:
            buckets[name].sort(
                key=lambda j: as_float(
                    as_dict(j.get("match_to_user")).get("score"), 0.0
                ),
                reverse=True,
            )

        buckets["by_difficulty"] = _count_by_difficulty(enriched_jobs)  # type: ignore[assignment]
        buckets["counts"] = {  # type: ignore[assignment]
            name: len(buckets[name]) for name in list(CATEGORIES) + ["unscored"]
        }
        return buckets


# --- Helpers ---------------------------------------------------------------


def _empty_analysis(reason: str) -> Dict[str, Any]:
    """A shaped, honest blank.

    Every key the happy path returns is present, so a caller never has to
    branch on whether analysis succeeded, and ``unavailable`` says why rather
    than leaving them to guess from a zero.
    """
    return {
        "required_skills": [],
        "preferred_skills": [],
        "tech_stack": [],
        "experience_years": None,
        "difficulty": None,
        "estimated_salary_range": None,
        "remote": None,
        "skill_breakdown": {
            "required": [], "preferred": [], "tech_stack": [],
            "required_count": 0, "preferred_count": 0, "total_distinct": 0,
        },
        "unavailable": reason,
    }


def _terms_for(source: Any) -> Optional[str]:
    from agents.job_scraper import SOURCE_TERMS

    return SOURCE_TERMS.get(str(source or ""))


def _humanise(skills: Sequence[Any], limit: int = 4) -> str:
    """Name a few skills in prose, and say how many more there were."""
    names = [str(s).strip() for s in skills if str(s).strip()]
    shown = names[:limit]
    rest = len(names) - len(shown)
    joined = ", ".join(shown)
    if rest > 0:
        return "%s and %d more" % (joined, rest)
    return joined


def _match_reasons(
    score: Optional[float],
    matched: Sequence[Any],
    missing: Sequence[Any],
    analysis: Dict[str, Any],
) -> List[str]:
    """Plain-English answers to "why should I apply for this job?".

    Every line is derived from something already computed - the skills that
    overlap, the ones that do not, the seniority the advert asked for. None of
    it is generated, so none of it can be invented, and a user who disagrees
    with a line can check it against their own resume in a second.

    The gap is stated in the same breath as the overlap. A list of reasons to
    apply with the reasons not to left off is advertising, and the user is the
    one who would sit in the interview being asked about the missing half.
    """
    reasons: List[str] = []

    matched_names = [str(s).strip() for s in matched if str(s).strip()]
    missing_names = [str(s).strip() for s in missing if str(s).strip()]
    total = len(matched_names) + len(missing_names)

    if matched_names:
        reasons.append(
            "You already have %d of the %d skills it asks for: %s."
            % (len(matched_names), total, _humanise(matched_names))
        )
    elif total:
        reasons.append(
            "None of the %d skills it asks for appear on your resume." % total
        )
    else:
        # No skill list means the advert was too vague to extract one, which
        # is a fact about the advert and worth saying rather than hiding.
        reasons.append(
            "The advert did not list its skills clearly enough to compare."
        )

    if missing_names:
        reasons.append(
            "You would be learning on the job: %s." % _humanise(missing_names)
        )

    role_type = str(analysis.get("role_type") or "").strip().lower()
    # "general" is the analyser's way of saying it could not tell. Printing
    # "It is a general role." spends a line of the user's attention on an
    # admission of ignorance dressed up as a finding.
    if role_type and role_type != "general":
        reasons.append("It is a %s role." % role_type.replace("_", " "))

    seniority = str(analysis.get("seniority") or "").strip().lower()
    # Same again, and worse: the analyser stores a missing seniority as the
    # literal string "unknown", which rendered as "The advert is pitched at
    # unknown level." A blank is not a value.
    if seniority and seniority != "unknown":
        reasons.append("The advert is pitched at %s level." % seniority)

    # ``score`` is None when the advert could not be scored, in which case
    # there is no band to place it in and both lines below would be inventing
    # one. The first reason above already told the reader why.
    if score is None:
        pass
    elif score >= 80 and total:
        # Only meaningful when there were skills to compare. A high score on
        # an advert whose skills could not be read is an artefact of the
        # scoring, and the first line above has already said so; claiming a
        # close match underneath it contradicts that in the same panel.
        reasons.append("On skills alone this is one of the closest matches found.")
    elif score < 40 and total:
        reasons.append(
            "This is a stretch - most of what it wants is not on your resume yet."
        )

    return reasons


def _trim(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _count_by_difficulty(jobs: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {EASY: 0, MEDIUM: 0, HARD: 0, "unknown": 0}
    for job in as_list(jobs):
        if not isinstance(job, dict):
            continue
        difficulty = as_dict(job.get("analysis")).get("difficulty")
        counts[difficulty if difficulty in counts else "unknown"] += 1
    return counts


#: Shared instance.
job_enricher = JobEnricher()
