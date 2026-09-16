"""The scoring engine: how well does this resume match this job?

The score is built from five weighted components rather than one number, so a
candidate can see *where* they fall short instead of just being told "62%".

Three rules shape the design:

* **No model is ever asked for the score.** A score has to be reproducible;
  the same resume and the same advert must give the same number every time.
  Everything here is arithmetic over evidence.
* **Components the advert never mentions are not scored.** If a posting says
  nothing about education, candidates are not silently capped below 100 for
  it. The unused weight is redistributed across the components that *are*
  specified — see :func:`_renormalise`.
* **Every match is explainable.** Each found item records the resume phrase
  that evidenced it and the rule that matched it, so a user can check the
  working rather than trusting it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from models.career_models import JobAnalysis, MatchResult
from utils.logger import get_logger, observed
from utils.skills import (
    find_skills,
    find_soft_skills,
    match_skill,
    normalise_skill,
    tech_stack,
)
from utils.validation import as_dict

logger = get_logger(__name__)

__all__ = [
    "MatchCalculator",
    "match_calculator",
    "ComponentScore",
    "COMPONENT_WEIGHTS",
    "APPLY_THRESHOLD",
    "MAYBE_THRESHOLD",
    "EDUCATION_RANK",
]


# ---------------------------------------------------------------------------
# Weights and bands
# ---------------------------------------------------------------------------

#: How much each component contributes to the overall match. Skills dominate
#: because they are what a hiring screen actually filters on.
COMPONENT_WEIGHTS: Dict[str, float] = {
    "skills": 0.40,
    "tech_stack": 0.25,
    "experience": 0.15,
    "soft_skills": 0.10,
    "education": 0.10,
}

#: The components that say something about *this* role rather than about
#: employment in general. Years of experience, a degree and a list of soft
#: skills are worth scoring alongside the others, but on their own they cannot
#: distinguish one advert from another: two years of anything satisfies a
#: request for two years. A score built only from these is not a match, and
#: :func:`_renormalise` withholds it.
_ROLE_SPECIFIC = ("skills", "tech_stack")

#: Recommendation bands, as percentages.
APPLY_THRESHOLD = 85.0
MAYBE_THRESHOLD = 65.0

RECOMMEND_APPLY = "APPLY"
RECOMMEND_MAYBE = "MAYBE"
RECOMMEND_SKIP = "SKIP"

#: Not a fourth band. An advert that states no skills, no technologies, no
#: years, no soft skills and no education leaves every dimension inapplicable,
#: so there is no average to take. That is a different fact from a bad match
#: and has to be reported as one -- see :func:`_renormalise`.
RECOMMEND_UNSCORED = "NOT_SCORED"

#: Ordering of qualifications, so "masters" can be seen to satisfy a request
#: for "bachelors". ``degree`` is an unspecified degree, so it sits with the
#: bachelors-level requirement it usually means in practice.
EDUCATION_RANK: Dict[str, int] = {
    "not required": 0,
    "not specified": 0,
    "bootcamp": 1,
    "degree": 2,
    "bachelors": 3,
    "masters": 4,
    "phd": 5,
}

#: Patterns for reading a candidate's highest qualification out of a resume.
#: Ordered most-demanding first so "BSc and an MSc" reports the MSc.
#:
#: The Indian spellings are not optional extras here: this product searches
#: only Indian vacancies, and "B.E." is one of the commonest degrees on an
#: Indian CV. Without it a resume reading "B.E. in Information Science" was
#: reported as having no education at all.
#:
#: "B.E." and "M.E." are matched only with their dots. Bare "be" and "me" are
#: ordinary English words, and a resume that says "happy to be contacted"
#: must not come back as a graduate. These two end in a full stop, so the
#: group closes with ``(?!\w)`` rather than ``\b``: a word boundary after a
#: dot demands a word character that a following space does not supply, and
#: the match fails on a qualification that reads exactly right.
_RESUME_EDUCATION = [
    ("phd", r"\b(ph\.?d|doctorate|dphil)\b"),
    (
        "masters",
        r"\b(master'?s?|m\.?sc|m\.?eng|m\.?s\b|mba|m\.?a\b|m\.?tech|mca|m\.e\.?|m\.?com)(?!\w)",
    ),
    (
        "bachelors",
        r"\b(bachelor'?s?|b\.?sc|b\.?eng|b\.?s\b|b\.?a\b|b\.?tech|bca|bba|b\.e\.?|b\.?com)(?!\w)",
    ),
    ("bootcamp", r"\b(bootcamp|boot camp|nanodegree)\b"),
    ("degree", r"\bdegree\b"),
]

#: "5 years", "5+ years", "over 6 years of experience".
_RESUME_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}?\s*experience",
    re.IGNORECASE,
)
_RESUME_YEARS_LOOSE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)

#: Above this a stated year count is a typo or a date, not a career length.
_MAX_PLAUSIBLE_YEARS = 50

#: A match below this similarity is reported but flagged as approximate.
_STRONG_MATCH = 0.9


# ---------------------------------------------------------------------------
# Component result
# ---------------------------------------------------------------------------


class ComponentScore(dict):
    """One row of the breakdown.

    A ``dict`` subclass rather than a dataclass so the whole report stays JSON
    serialisable without a conversion step, while still being constructed in
    one readable place.
    """

    def __init__(
        self,
        score: float,
        found: Any = None,
        missing: Any = None,
        weight: float = 0.0,
        applicable: bool = True,
        evidence: Optional[Dict[str, str]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            score=round(float(score), 1),
            found=found if found is not None else [],
            missing=missing if missing is not None else [],
            weight=round(weight, 3),
            applicable=applicable,
        )
        if evidence:
            self["evidence"] = evidence
        self.update(extra)


def _not_assessed(reason: str, weight: float) -> ComponentScore:
    """A component the advert did not specify.

    Scored 100 so it cannot drag the total down, but marked inapplicable so
    :func:`_renormalise` removes its weight entirely rather than gifting free
    marks.
    """
    return ComponentScore(
        score=100.0, weight=weight, applicable=False, reason=reason
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]


class _EvidenceFinder:
    """Locates the phrase in a resume that backs up a claimed skill.

    Prefers the RAG index when one is supplied, because a semantic search finds
    the passage that *demonstrates* a skill rather than the first place the word
    appears. Falls back to scanning sentences, which keeps the scorer usable
    with nothing but a block of text.
    """

    def __init__(self, resume_text: str = "", retriever: Any = None) -> None:
        self.retriever = retriever
        self._lines = _sentences(resume_text)
        # The skills and tech_stack components ask about the same names, and a
        # vector search is expensive. Look each one up once.
        self._cache: Dict[str, Optional[str]] = {}

    def find(self, skill: str) -> Optional[str]:
        """Return a line of the resume that evidences ``skill``, or ``None``.

        Tries the vector index first and falls back to a plain text scan, so
        evidence is still produced when nothing is indexed. Results are
        memoised per instance because the skills and tech_stack components ask
        about the same names and a vector search is not cheap.
        """
        key = skill.lower()
        if key not in self._cache:
            self._cache[key] = self._from_retriever(skill) or self._from_text(skill)
        return self._cache[key]

    def _from_retriever(self, skill: str) -> Optional[str]:
        if self.retriever is None:
            return None
        try:
            results = self.retriever.search_by_technology(skill, top_k=1)
        except Exception:  # a broken index must not sink the score
            logger.debug("Evidence lookup failed for '%s'", skill, exc_info=True)
            return None
        for result in results or []:
            content = getattr(result, "content", None) or getattr(result, "text", None)
            if content:
                return _shorten(str(content))
        return None

    def _from_text(self, skill: str) -> Optional[str]:
        core = normalise_skill(skill)
        if not core:
            return None
        pattern = re.compile(r"(?<!\w)" + re.escape(core) + r"(?!\w)", re.IGNORECASE)
        for line in self._lines:
            if pattern.search(line):
                return _shorten(line)
        # The resume may describe the skill rather than name it -- "built a
        # retrieval augmented generation pipeline" is evidence of RAG. Fall
        # back to the alias-aware vocabulary before giving up.
        for line in self._lines:
            if core in find_skills(line) or core in find_soft_skills(line):
                return _shorten(line)
        return None


def _shorten(text: str, limit: int = 160) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Input coercion
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    out: List[str] = []
    seen = set()
    for item in value:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _as_years(value: Any) -> int:
    """Read a year count from an int, a float or a string like "5+ years"."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        years = int(value)
    else:
        match = re.search(r"\d{1,2}", str(value or ""))
        if not match:
            return 0
        years = int(match.group())
    return years if 0 < years <= _MAX_PLAUSIBLE_YEARS else 0


def extract_resume_years(text: str) -> int:
    """Longest plausible span of experience claimed in a resume."""
    if not text:
        return 0
    candidates = [int(m) for m in _RESUME_YEARS.findall(text)]
    if not candidates:
        candidates = [int(m) for m in _RESUME_YEARS_LOOSE.findall(text)]
    plausible = [y for y in candidates if 0 < y <= _MAX_PLAUSIBLE_YEARS]
    return max(plausible) if plausible else 0


def extract_resume_education(text: str) -> str:
    """Highest qualification named in a resume."""
    if not text:
        return "not specified"
    lowered = text.lower()
    for label, pattern in _RESUME_EDUCATION:
        if re.search(pattern, lowered):
            return label
    return "not specified"


def _education_key(value: Any) -> str:
    """Strip the "(or equivalent experience)" suffix down to the bare level."""
    text = str(value or "").strip().lower()
    return text.split("(")[0].strip() or "not specified"


# ---------------------------------------------------------------------------
# The calculator
# ---------------------------------------------------------------------------


class MatchCalculator:
    """Scores a resume against an analyzed job description.

    The primary entry point is :meth:`calculate_match`, which takes and returns
    plain dictionaries so it can be called from the graph, an API handler or a
    test without any model objects in the way.
    """

    weights = COMPONENT_WEIGHTS

    # -- component scorers ------------------------------------------------

    def _match_list(
        self,
        candidate: Sequence[str],
        required: Sequence[str],
        evidence: Optional[_EvidenceFinder] = None,
    ) -> Tuple[List[str], List[str], Dict[str, str], float, List[Dict[str, Any]]]:
        """Compare two skill lists with fuzzy matching.

        Returns ``(found, missing, evidence, score, detail)``. Partial credit is
        given for approximate matches, so a resume that says "kubernets" is not
        treated as identical to one that says "kubernetes", but is not treated
        as a total miss either.
        """
        found: List[str] = []
        missing: List[str] = []
        proof: Dict[str, str] = {}
        detail: List[Dict[str, Any]] = []
        earned = 0.0

        for want in required:
            hit = match_skill(want, candidate)
            if hit is None:
                missing.append(want)
                continue

            matched_name, similarity, reason = hit
            found.append(want)
            earned += similarity
            detail.append(
                {
                    "required": want,
                    "matched": matched_name,
                    "similarity": round(similarity, 2),
                    "reason": reason,
                    "exact": similarity >= _STRONG_MATCH,
                }
            )
            if evidence is not None:
                snippet = evidence.find(matched_name)
                if snippet:
                    proof[want] = snippet

        score = (earned / len(required) * 100.0) if required else 100.0
        return found, missing, proof, score, detail

    def _calculate_skill_match(
        self,
        resume_skills: Sequence[str],
        required_skills: Sequence[str],
        evidence: Optional[_EvidenceFinder] = None,
    ) -> ComponentScore:
        """How many of the required hard skills the candidate evidences."""
        weight = self.weights["skills"]
        if not required_skills:
            return _not_assessed("the advert named no required skills", weight)

        found, missing, proof, score, detail = self._match_list(
            resume_skills, required_skills, evidence
        )
        return ComponentScore(
            score=score,
            found=found,
            missing=missing,
            weight=weight,
            evidence=proof,
            matches=detail,
        )

    def _calculate_tech_match(
        self,
        resume_tech: Sequence[str],
        required_tech: Sequence[str],
        evidence: Optional[_EvidenceFinder] = None,
    ) -> ComponentScore:
        """Same comparison as skills, narrowed to concrete tools."""
        weight = self.weights["tech_stack"]
        if not required_tech:
            return _not_assessed("the advert named no specific technologies", weight)

        found, missing, proof, score, detail = self._match_list(
            resume_tech, required_tech, evidence
        )
        return ComponentScore(
            score=score,
            found=found,
            missing=missing,
            weight=weight,
            evidence=proof,
            matches=detail,
        )

    def _calculate_experience_match(
        self,
        resume_exp: Any,
        required_exp: Any,
    ) -> ComponentScore:
        """Years held against years wanted.

        Exceeding the requirement is a full match, not a bonus — being
        over-qualified does not make you a better fit than qualified. Falling
        short scores proportionally, with a floor, because most adverts treat
        the number as a guideline rather than a gate.
        """
        weight = self.weights["experience"]
        have = _as_years(resume_exp)
        want = _as_years(required_exp)

        if want <= 0:
            return _not_assessed(
                "the advert did not ask for a number of years", weight
            )

        if have <= 0:
            return ComponentScore(
                score=0.0,
                found="not stated",
                missing=f"{want} years",
                required=f"{want} years",
                weight=weight,
                note="no length of experience found in the resume",
            )

        if have >= want:
            score = 100.0
        else:
            # A candidate with 4 of 5 years keeps most of the credit; one with
            # 1 of 10 keeps little. Squaring would be too harsh, linear too kind.
            score = max(20.0, (have / want) * 100.0)

        return ComponentScore(
            score=score,
            found=f"{have} years",
            missing=[] if have >= want else f"{want - have} more years",
            required=f"{want} years",
            weight=weight,
            years_found=have,
            years_required=want,
            meets_requirement=have >= want,
        )

    def _calculate_soft_skill_match(
        self,
        resume_soft: Sequence[str],
        required_soft: Sequence[str],
        evidence: Optional[_EvidenceFinder] = None,
    ) -> ComponentScore:
        """Communication, leadership and the rest.

        Scored more leniently than hard skills: a resume rarely lists "empathy"
        even when the candidate has it, so absence is weak evidence.
        """
        weight = self.weights["soft_skills"]
        if not required_soft:
            return _not_assessed("the advert named no soft skills", weight)

        found, missing, proof, raw, _ = self._match_list(
            resume_soft, required_soft, evidence
        )
        if not found:
            # Most engineering resumes name no soft skills at all -- they
            # describe achievements, not adjectives. Scoring that as a hard
            # zero at full weight asserted the candidate lacks communication
            # on the strength of a missing word, and contradicted this
            # method's own premise that absence is weak evidence. It also
            # rewarded the wrong thing: writing "team player" once beat
            # describing four years of leading a team.
            #
            # Missing evidence is not evidence of absence, so the component is
            # left unassessed and its weight moves to what can actually be
            # measured. `missing` is still populated so the advice layer can
            # tell the candidate exactly what to add.
            component = _not_assessed(
                "your resume names none of the soft skills asked for; the "
                "words being absent is not evidence the skills are",
                weight,
            )
            component["missing"] = missing
            return component

        # Showing any of the asked-for soft skills earns a passing mark.
        score = min(100.0, raw + 25.0)
        return ComponentScore(
            score=score,
            found=found,
            missing=missing,
            weight=weight,
            evidence=proof,
        )

    def _calculate_education_match(
        self,
        resume_education: Any,
        required_education: Any,
    ) -> ComponentScore:
        """Whether the qualification held meets the one asked for."""
        weight = self.weights["education"]
        want_raw = str(required_education or "not specified").strip().lower()
        want = _education_key(want_raw)
        have = _education_key(resume_education)

        if want in ("not specified", "") or want not in EDUCATION_RANK:
            return _not_assessed("the advert stated no education requirement", weight)
        if want == "not required":
            return _not_assessed("the advert waived the education requirement", weight)

        want_rank = EDUCATION_RANK[want]
        have_rank = EDUCATION_RANK.get(have, 0)
        # "or equivalent experience" means a shortfall is forgiven, not ignored.
        negotiable = "equivalent" in want_raw

        if have_rank >= want_rank:
            score = 100.0
        elif negotiable:
            score = 75.0
        elif have_rank == 0:
            score = 0.0
        else:
            # One level short is a near miss; three levels short is not.
            score = max(0.0, 100.0 - (want_rank - have_rank) * 30.0)

        return ComponentScore(
            score=score,
            found=have,
            missing=[] if have_rank >= want_rank else want,
            required=want_raw,
            weight=weight,
            meets_requirement=have_rank >= want_rank or negotiable,
        )

    # -- recommendation ---------------------------------------------------

    @staticmethod
    def _generate_recommendation(match_score: Optional[float]) -> str:
        """Turn a percentage into APPLY / MAYBE / SKIP.

        ``None`` means nothing was assessed, which is not a verdict of any
        strength, so it gets its own value rather than being folded into SKIP.
        """
        if match_score is None:
            return RECOMMEND_UNSCORED
        if match_score >= APPLY_THRESHOLD:
            return RECOMMEND_APPLY
        if match_score >= MAYBE_THRESHOLD:
            return RECOMMEND_MAYBE
        return RECOMMEND_SKIP

    @staticmethod
    def _advice(
        breakdown: Dict[str, ComponentScore], overall: Optional[float]
    ) -> List[str]:
        """Plain-language next steps, ordered by what would help most."""
        tips: List[str] = []

        if overall is None:
            # Advice keyed off a score there isn't would be invented. The one
            # honest thing to say is what stopped the scoring.
            return [
                "This advert states no skills, technologies, years of "
                "experience or qualifications, so there was nothing to check "
                "your resume against. Paste the full posting, or judge this "
                "one yourself."
            ]

        gaps: List[Tuple[float, str]] = []
        for name in ("skills", "tech_stack"):
            component = breakdown.get(name) or {}
            missing = component.get("missing") or []
            if component.get("applicable") and isinstance(missing, list) and missing:
                lost = (100.0 - component["score"]) * component["weight"]
                gaps.append((lost, f"{', '.join(missing[:5])}"))
        gaps.sort(reverse=True)
        if gaps:
            tips.append(
                f"Closest wins: evidence these on your resume — {gaps[0][1]}."
            )

        experience = breakdown.get("experience") or {}
        if experience.get("applicable") and not experience.get("meets_requirement", True):
            tips.append(
                f"The advert asks for {experience.get('required')}; your resume "
                f"shows {experience.get('found')}. Lead with your strongest "
                "relevant projects to offset the difference."
            )

        education = breakdown.get("education") or {}
        if education.get("applicable") and not education.get("meets_requirement", True):
            tips.append(
                f"A {education.get('required')} is requested. If you have "
                "equivalent experience, say so explicitly."
            )

        soft = breakdown.get("soft_skills") or {}
        # Deliberately not gated on `applicable`: a resume naming none of the
        # asked-for soft skills is left unassessed rather than scored zero,
        # and that is precisely the candidate who most needs this advice.
        if soft.get("missing"):
            missing = soft["missing"]
            tips.append(
                f"Work {', '.join(missing[:3])} into your achievement bullets — "
                "they are asked for but not shown."
            )

        if overall >= APPLY_THRESHOLD:
            tips.append("Strong match. Tailor the summary line and apply.")
        elif overall >= MAYBE_THRESHOLD:
            tips.append(
                "Worth applying if the missing items are ones you can honestly "
                "claim. Quantify the achievements behind your matched skills."
            )
        else:
            tips.append(
                "Weak match as written. Either target a closer role or rewrite "
                "around the requirements you do meet."
            )
        return tips

    # -- confidence -------------------------------------------------------

    @staticmethod
    def _confidence(
        breakdown: Dict[str, ComponentScore],
        resume_skills: Sequence[str],
        job_confidence: Any,
    ) -> float:
        """How much the score itself should be trusted, 0-100.

        Low confidence means thin input — a vague advert or a sparse resume —
        not a low match. The two are reported separately on purpose.
        """
        assessed = [c for c in breakdown.values() if c.get("applicable")]
        coverage = len(assessed) / len(COMPONENT_WEIGHTS)

        # A resume with three recognised skills gives a thinner reading than one
        # with a dozen.
        depth = min(1.0, len(resume_skills) / 8.0)

        # The job analysis reports its own extraction confidence as 0.0-1.0.
        try:
            job_factor = float(job_confidence)
        except (TypeError, ValueError):
            job_factor = 0.0
        if job_factor > 1.0:  # already a percentage
            job_factor /= 100.0
        job_factor = max(0.0, min(1.0, job_factor)) if job_confidence is not None else 0.5

        score = (coverage * 0.5 + depth * 0.25 + job_factor * 0.25) * 100.0
        return round(max(0.0, min(100.0, score)), 1)

    # -- entry point ------------------------------------------------------

    @observed("calculate_match")
    def calculate_match(
        self,
        resume_data: Dict[str, Any],
        job_analysis: Dict[str, Any],
        retriever: Any = None,
    ) -> Dict[str, Any]:
        """Score a resume against an analyzed job description.

        ``resume_data`` accepts ``skills``, ``resume_text`` (or ``text``),
        ``experience_years``, ``education``, ``soft_skills`` and ``tech_stack``.
        Anything missing is derived from the text where possible, so a caller
        can pass nothing but ``{"resume_text": ...}``.

        ``job_analysis`` is the dict produced by
        :meth:`~agents.job_analyzer.JobAnalyzerAgent.analyze`.

        Pass ``retriever`` (a ``ResumeIndexer``) to have supporting evidence
        pulled from the RAG index instead of scanned from the raw text.
        """
        resume_data = as_dict(resume_data, "resume_data")
        job_analysis = as_dict(job_analysis, "job_analysis")

        resume_text = str(
            resume_data.get("resume_text") or resume_data.get("text") or ""
        )
        evidence = _EvidenceFinder(resume_text, retriever)

        # -- resume side --------------------------------------------------
        resume_skills = _as_list(resume_data.get("skills"))
        if not resume_skills and resume_text:
            resume_skills = find_skills(resume_text)

        resume_tech = _as_list(resume_data.get("tech_stack")) or tech_stack(resume_skills)

        resume_soft = _as_list(resume_data.get("soft_skills"))
        if not resume_soft and resume_text:
            resume_soft = find_soft_skills(resume_text)

        resume_years = _as_years(resume_data.get("experience_years"))
        if not resume_years and resume_text:
            resume_years = extract_resume_years(resume_text)

        resume_education = resume_data.get("education")
        if not resume_education and resume_text:
            resume_education = extract_resume_education(resume_text)

        # -- job side ------------------------------------------------------
        required_skills = _as_list(job_analysis.get("required_skills"))
        required_tech = _as_list(job_analysis.get("tech_stack"))
        if not required_tech and required_skills:
            required_tech = tech_stack(required_skills)

        breakdown: Dict[str, ComponentScore] = {
            "skills": self._calculate_skill_match(
                resume_skills, required_skills, evidence
            ),
            "tech_stack": self._calculate_tech_match(
                resume_tech, required_tech, evidence
            ),
            "experience": self._calculate_experience_match(
                resume_years, job_analysis.get("experience_years")
            ),
            "soft_skills": self._calculate_soft_skill_match(
                resume_soft, _as_list(job_analysis.get("soft_skills")), evidence
            ),
            "education": self._calculate_education_match(
                resume_education, job_analysis.get("education")
            ),
        }

        overall = _renormalise(breakdown)
        recommendation = self._generate_recommendation(overall)
        confidence = self._confidence(
            breakdown, resume_skills, job_analysis.get("confidence")
        )

        matched = list(breakdown["skills"].get("found") or [])
        missing = list(breakdown["skills"].get("missing") or [])

        report: Dict[str, Any] = {
            "overall_match": overall,
            "match_breakdown": {name: dict(c) for name, c in breakdown.items()},
            "recommendation": recommendation,
            "confidence": confidence,
            # Flattened views the graph and the API response model use.
            "matched_skills": matched,
            "missing_skills": missing,
            "recommendations": self._advice(breakdown, overall),
            "job_title": job_analysis.get("title") or "Unknown role",
        }
        logger.info(
            "Match %s (%s, confidence %.0f%%) for '%s'",
            "not assessed" if overall is None else "%.1f%%" % overall,
            recommendation,
            confidence,
            report["job_title"],
        )
        return report

    # -- backwards-compatible wrapper -------------------------------------

    def calculate(
        self,
        resume_id: str,
        resume_text: str,
        analysis: JobAnalysis,
    ) -> MatchResult:
        """Pydantic-flavoured wrapper around :meth:`calculate_match`.

        Kept so the API models and existing callers keep working. It delegates
        rather than reimplementing, so there is only ever one scoring engine to
        reason about.
        """
        job_analysis = {
            "title": analysis.title,
            "required_skills": [s.name for s in analysis.required_skills],
            "preferred_skills": [s.name for s in analysis.preferred_skills],
            "seniority": analysis.seniority,
        }
        report = self.calculate_match({"resume_text": resume_text}, job_analysis)

        # Preferred skills are not part of the weighted score, but callers of
        # this older API expect them reflected in the matched/missing lists.
        preferred = [s.name for s in analysis.preferred_skills]
        resume_skills = find_skills(resume_text)
        preferred_hits = [p for p in preferred if match_skill(p, resume_skills)]

        return MatchResult(
            resume_id=resume_id,
            job_title=analysis.title,
            score=report["overall_match"],
            matched_skills=report["matched_skills"] + preferred_hits,
            missing_skills=(
                report["missing_skills"]
                + [p for p in preferred if p not in preferred_hits]
            ),
            recommendations=report["recommendations"],
        )


def _renormalise(breakdown: Dict[str, ComponentScore]) -> Optional[float]:
    """Combine the components, ignoring the ones the advert never specified.

    Without this, a posting that says nothing about education would cap every
    candidate at 90%, which would make the number meaningless.

    Returns ``None`` when *no* component could be assessed. This used to return
    ``0.0``, which the rest of the app could not tell apart from a genuine
    zero, so a vague advert -- one naming no skills, no stack, no years, no
    soft skills and no degree -- was reported to the reader as "0% - SKIP"
    directly above a breakdown whose every row said "Not counted". Nothing was
    measured, so there is no mean to return; an empty average is undefined, not
    zero.

    It also returns ``None`` when the only things assessed were the ones that
    are not about this job in particular. Measured on a live search: a
    "Freelance Copywriter" advert scored **100% - APPLY** against an AI/ML
    developer's CV, and sat at the top of the results. The advert named no
    skills and no stack, so the sole applicable component was experience -- it
    asked for 2 years, the CV has 2 years, and two years of anything matches
    two years of anything. Years, a degree and "good communication" describe
    every job ever posted; skills and tech stack are what make a score a
    statement about *this* one.

    So a number is only returned when at least one role-specific component was
    assessed. This is the same rule as the paragraph above, applied one level
    up: not "did we measure anything" but "did we measure anything that
    distinguishes this advert from any other".
    """
    applicable = {
        name: c for name, c in breakdown.items() if c.get("applicable")
    }
    if not applicable:
        # Nothing to go on: neither a match nor a mismatch.
        return None

    if not any(name in applicable for name in _ROLE_SPECIFIC):
        # Only the generic components were assessable. See the docstring.
        return None

    total_weight = sum(c["weight"] for c in applicable.values())
    if total_weight <= 0:
        # Same situation reached by a different route: the assessed components
        # carry no weight between them, so the division has no denominator.
        return None

    weighted = sum(c["score"] * c["weight"] for c in applicable.values())
    return round(weighted / total_weight, 1)


match_calculator = MatchCalculator()
