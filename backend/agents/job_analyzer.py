"""Reading a job advert and turning it into structured requirements.

Two classes live here, and the split is deliberate:

* :class:`JobAnalyzer` is the original keyword engine. It is pure, fast, needs
  no model, and produces a :class:`~models.career_models.JobAnalysis`.
* :class:`JobAnalyzerAgent` is the full agent. It asks an LLM first and falls
  back to :class:`JobAnalyzer` plus the extractors below when no model answers.
  It returns a plain dict with the richer fields: tech stack, years of
  experience, soft skills, education, role type and a confidence score.

The agent lives next to the engine it degrades to, rather than in
``base_agent.py`` with its siblings, because ``base_agent`` must not import
this module — that would make the dependency circular.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from agents.base_agent import (
    AgentError,
    BaseAgent,
    _clean_skill_list,
    _clean_str_list,
    _guess_title,
)
from models.career_models import JobAnalysis, JobDescription, Skill
from utils.cache import cache_result, job_analysis_cache
from utils.logger import get_logger, observed
from utils.skills import (
    KNOWN_SKILLS,
    find_skills as _find_skills,
    find_soft_skills,
    tech_stack as _tech_stack,
)

logger = get_logger(__name__)

__all__ = [
    "JobAnalyzer",
    "JobAnalyzerAgent",
    "JobAnalysisError",
    "EmptyJobDescriptionError",
    "MalformedJobDescriptionError",
    "job_analyzer",
    "job_analyzer_agent",
    "KNOWN_SKILLS",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JobAnalysisError(AgentError):
    """Base class for job-analysis failures."""


class EmptyJobDescriptionError(JobAnalysisError):
    """Nothing was supplied to analyse."""


class MalformedJobDescriptionError(JobAnalysisError):
    """The text is not readable prose — binary junk, mojibake, or too short."""


# ---------------------------------------------------------------------------
# Seniority
# ---------------------------------------------------------------------------

SENIORITY_PATTERNS = {
    "intern": r"\bintern(ship)?\b",
    "junior": r"\b(junior|entry[- ]level|associate)\b",
    "mid": r"\b(mid[- ]level|intermediate)\b",
    "senior": r"\bsenior\b",
    "staff": r"\b(staff|principal)\b",
    "lead": r"\b(lead|manager|head of)\b",
}

#: Used only to break ties when two levels are named at the same position.
_SENIORITY_RANK = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "staff": 4, "lead": 5}


def _detect_seniority(text: str) -> Optional[str]:
    """The seniority of the role itself.

    Takes the **earliest** level mentioned rather than the first pattern in the
    dict. Postings name the role's own level up front and mention other levels
    later in passing — "Senior Engineer ... you will mentor junior engineers"
    is a senior role, not a junior one.
    """
    lowered = text.lower()

    best: Optional[Tuple[int, int, str]] = None
    for level, pattern in SENIORITY_PATTERNS.items():
        match = re.search(pattern, lowered)
        if match is None:
            continue
        # Earliest position wins; on a tie the more senior label wins.
        candidate = (match.start(), -_SENIORITY_RANK[level], level)
        if best is None or candidate < best:
            best = candidate

    return best[2] if best else None


def _split_sections(description: str) -> Tuple[str, str]:
    """Split a description into (required, preferred) sections when possible."""
    lowered = description.lower()
    markers = ["preferred", "nice to have", "bonus", "plus:"]
    for marker in markers:
        idx = lowered.find(marker)
        if idx != -1:
            return description[:idx], description[idx:]
    return description, ""


def _extract_responsibilities(description: str) -> List[str]:
    lines = [line.strip(" -*\u2022\t") for line in description.splitlines()]
    return [line for line in lines if len(line) > 20][:15]


# ---------------------------------------------------------------------------
# Years of experience
# ---------------------------------------------------------------------------

#: "3-5 years", "3 to 5 years" — the lower bound is the actual requirement.
_YEAR_RANGE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*years?")
#: "5+ years", "at least 5 years", "minimum of 5 years".
_YEAR_SINGLE = re.compile(r"(\d{1,2})\s*\+?\s*years?")

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_YEAR_WORDS = re.compile(r"\b(" + "|".join(_WORD_NUMBERS) + r")\s*\+?\s*years?")

#: Anything above this is a typo or a date, not a requirement.
_MAX_PLAUSIBLE_YEARS = 40


def extract_experience_years(text: str) -> int:
    """Years of experience the posting asks for, or 0 when it does not say.

    A posting often states several figures — "7+ years overall, 2+ years with
    Kubernetes". The role's real bar is the largest of them, so we take the
    max. For a *range* ("3-5 years") the lower bound is what you must clear,
    so that is the figure that goes into the comparison.
    """
    if not text:
        return 0

    lowered = text.lower()
    candidates: List[int] = []

    for low, _high in _YEAR_RANGE.findall(lowered):
        candidates.append(int(low))

    # Blank the ranges out so "3-5 years" is not also read as a bare "5 years".
    without_ranges = _YEAR_RANGE.sub(" ", lowered)
    for value in _YEAR_SINGLE.findall(without_ranges):
        candidates.append(int(value))
    for word in _YEAR_WORDS.findall(without_ranges):
        candidates.append(_WORD_NUMBERS[word])

    plausible = [n for n in candidates if 0 < n <= _MAX_PLAUSIBLE_YEARS]
    return max(plausible) if plausible else 0


def experience_level(years: int, seniority: Optional[str] = None) -> str:
    """Turn a year count into a band. Falls back to the stated seniority."""
    if years <= 0:
        return seniority or "not specified"
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    if years < 8:
        return "senior"
    return "lead"


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

#: Ordered most demanding first, so the highest requirement mentioned wins.
_EDUCATION_PATTERNS = [
    ("phd", r"\b(ph\.?d|doctorate|doctoral)\b"),
    ("masters", r"\b(master'?s?|m\.?sc|mba)\b"),
    ("bachelors", r"\b(bachelor'?s?|b\.?sc|undergraduate degree)\b"),
    ("degree", r"\b(degree in|university degree|college degree)\b"),
    ("bootcamp", r"\bbootcamp\b"),
]

_EQUIVALENT_EXPERIENCE = re.compile(
    r"\bor equivalent(?:\s+(?:practical\s+)?experience)?\b|"
    r"\bequivalent practical experience\b|"
    r"\bdegree not required\b"
)


def extract_education(text: str) -> str:
    """The highest qualification the posting asks for, as a plain string."""
    if not text:
        return "not specified"

    lowered = text.lower()
    for label, pattern in _EDUCATION_PATTERNS:
        if re.search(pattern, lowered):
            if _EQUIVALENT_EXPERIENCE.search(lowered):
                return f"{label} (or equivalent experience)"
            return label

    if _EQUIVALENT_EXPERIENCE.search(lowered):
        return "not required"
    return "not specified"


# ---------------------------------------------------------------------------
# Role type
# ---------------------------------------------------------------------------

_ROLE_PATTERNS = {
    "ai/ml": [
        r"\b(machine learning|ml engineer|ai engineer|deep learning|nlp|llm|rag)\b",
        r"\b(data scientist|computer vision|generative ai|prompt engineer)\b",
    ],
    "data": [
        r"\b(data engineer|etl|data pipeline|data warehouse|analytics engineer)\b",
        r"\b(business intelligence|dbt)\b",
    ],
    "devops": [
        r"\b(devops|sre|site reliability|platform engineer|infrastructure engineer)\b",
        r"\b(cloud engineer)\b",
    ],
    "frontend": [
        r"\b(frontend|front[- ]end|ui engineer|web designer)\b",
        r"\b(react|vue|angular|svelte|css)\b",
    ],
    "backend": [
        r"\b(backend|back[- ]end|server[- ]side|api engineer)\b",
        r"\b(microservices|distributed systems)\b",
    ],
    "mobile": [r"\b(mobile developer|ios|android|react native|flutter)\b"],
    "security": [r"\b(security engineer|appsec|penetration test|cybersecurity)\b"],
    "qa": [r"\b(qa engineer|quality assurance|test automation|sdet)\b"],
}

_FULLSTACK = re.compile(r"\b(full[- ]?stack)\b")


def detect_role_type(text: str) -> str:
    """Classify the role's focus area.

    Scored rather than first-match: a posting that mentions React once but
    microservices five times is a backend role.
    """
    if not text:
        return "general"

    lowered = text.lower()

    # An explicit "full-stack" beats any keyword tally.
    if _FULLSTACK.search(lowered):
        return "fullstack"

    scores: Dict[str, int] = {}
    for role, patterns in _ROLE_PATTERNS.items():
        hits = sum(len(re.findall(pattern, lowered)) for pattern in patterns)
        if hits:
            scores[role] = hits

    if not scores:
        return "general"

    # Front and back mentioned about equally usually means full-stack.
    front, back = scores.get("frontend", 0), scores.get("backend", 0)
    if front and back and abs(front - back) <= 1:
        return "fullstack"

    best = max(scores.values())
    return sorted(role for role, hits in scores.items() if hits == best)[0]


# ---------------------------------------------------------------------------
# Company size
# ---------------------------------------------------------------------------

_COMPANY_SIZE_PATTERNS = {
    "startup": r"\b(startup|start[- ]up|seed stage|series a|early stage|founding team)\b",
    "scaleup": r"\b(scale[- ]?up|series [b-d]\b|high[- ]growth|hyper[- ]growth)\b",
    "enterprise": (
        r"\b(enterprise|fortune \d+|multinational|global organi[sz]ation|"
        r"large organi[sz]ation)\b"
    ),
}


def detect_company_size(text: str) -> str:
    """A rough read on company stage, or ``"unknown"``."""
    if not text:
        return "unknown"

    lowered = text.lower()
    for label, pattern in _COMPANY_SIZE_PATTERNS.items():
        if re.search(pattern, lowered):
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

#: Below this there is nothing meaningful to analyse.
MIN_DESCRIPTION_CHARS = 20
#: Readable prose is mostly letters. Binary junk and mojibake are not.
MIN_ALPHA_RATIO = 0.5


def validate_description(text: Any) -> str:
    """Check the input is prose we can actually read, and return it trimmed."""
    if not isinstance(text, str) or not text.strip():
        raise EmptyJobDescriptionError("The job description is empty.")

    cleaned = text.strip()
    if len(cleaned) < MIN_DESCRIPTION_CHARS:
        raise MalformedJobDescriptionError(
            f"The job description is too short to analyse "
            f"({len(cleaned)} characters, need at least {MIN_DESCRIPTION_CHARS})."
        )

    dense = [c for c in cleaned if not c.isspace()]
    alpha_ratio = sum(c.isalpha() for c in dense) / len(dense) if dense else 0.0
    if alpha_ratio < MIN_ALPHA_RATIO:
        raise MalformedJobDescriptionError(
            f"The job description does not look like readable text "
            f"(only {alpha_ratio:.0%} letters)."
        )
    return cleaned


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

#: How much each recovered signal contributes. Sums to 1.0.
_CONFIDENCE_WEIGHTS = {
    "skills": 0.30,
    "tech_stack": 0.10,
    "experience": 0.15,
    "seniority": 0.15,
    "role_type": 0.15,
    "education": 0.10,
    "soft_skills": 0.05,
}

#: Keyword matching is genuinely blunter than a model that read the prose, so
#: the deterministic path is discounted rather than claiming equal certainty.
_SOURCE_FACTOR = {"llm": 1.0, "fallback": 0.85}


def score_confidence(analysis: Dict[str, Any], source: str = "fallback") -> float:
    """How much of the structure we actually recovered, 0.0-1.0.

    This measures *completeness of extraction*, not correctness. A terse advert
    scores low because there was little to find, which is the honest signal for
    a caller deciding how much to trust the result.
    """
    skills = analysis.get("required_skills") or []
    if len(skills) >= 5:
        total = _CONFIDENCE_WEIGHTS["skills"]
    elif len(skills) >= 3:
        total = _CONFIDENCE_WEIGHTS["skills"] * 0.73
    elif skills:
        total = _CONFIDENCE_WEIGHTS["skills"] * 0.4
    else:
        total = 0.0

    if analysis.get("tech_stack"):
        total += _CONFIDENCE_WEIGHTS["tech_stack"]
    if analysis.get("experience_years"):
        total += _CONFIDENCE_WEIGHTS["experience"]
    if analysis.get("seniority") and analysis["seniority"] != "unknown":
        total += _CONFIDENCE_WEIGHTS["seniority"]
    if analysis.get("role_type") and analysis["role_type"] != "general":
        total += _CONFIDENCE_WEIGHTS["role_type"]
    if (analysis.get("education") or "not specified") != "not specified":
        total += _CONFIDENCE_WEIGHTS["education"]
    if analysis.get("soft_skills"):
        total += _CONFIDENCE_WEIGHTS["soft_skills"]

    total *= _SOURCE_FACTOR.get(source, _SOURCE_FACTOR["fallback"])
    return round(max(0.0, min(1.0, total)), 2)


# ---------------------------------------------------------------------------
# The keyword engine (unchanged behaviour, now also the agent's fallback)
# ---------------------------------------------------------------------------


class JobAnalyzer:
    """Analyzes job descriptions into structured `JobAnalysis` objects."""

    def analyze(self, job: JobDescription) -> JobAnalysis:
        """Turn an advert into structured requirements using keywords only.

        No language model is involved: this is the deterministic engine, used
        directly when no model is configured and as the fallback when one is
        configured but unreachable. That is why it never raises on odd input -
        an empty result is a valid answer here, and the caller above decides
        whether that is worth an error.
        """
        required_text, preferred_text = _split_sections(job.description)
        required = _find_skills(required_text)
        preferred = [s for s in _find_skills(preferred_text) if s not in required]

        analysis = JobAnalysis(
            title=job.title,
            company=job.company,
            required_skills=[Skill(name=name) for name in required],
            preferred_skills=[Skill(name=name) for name in preferred],
            responsibilities=_extract_responsibilities(job.description),
            seniority=_detect_seniority(f"{job.title}\n{job.description}"),
            keywords=sorted(set(required + preferred)),
        )
        logger.info(
            "Analyzed job '%s': %d required / %d preferred skills",
            job.title,
            len(analysis.required_skills),
            len(analysis.preferred_skills),
        )
        return analysis


job_analyzer = JobAnalyzer()


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class JobAnalyzerAgent(BaseAgent):
    """Parses a job description into the requirements a resume is matched against.

    Asks the LLM first; falls back to the keyword engine and the extractors in
    this module. Either path produces the same output shape, so callers never
    have to know which one ran — only ``source`` and ``confidence`` differ.
    """

    name = "analyze_job"
    label = "Job Analyzer"
    description = (
        "Analyse a job description and return its required skills, tech stack, "
        "years of experience, soft skills, education, role type and seniority."
    )
    prompt_name = "job_analysis"
    required_inputs = ("job_description",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: The last text analysed, so ``extract_requirements()`` can be called
        #: with no arguments straight after ``analyze()``.
        self._last_description: str = ""
        #: Whether a caller supplied its own LLM. See ``_backend_fingerprint``.
        self._llm_was_injected = self._llm is not None

    # -- Public API -------------------------------------------------------

    @observed("analyze_job")
    def analyze(self, job_description: str) -> Dict[str, Any]:
        """Full analysis of a job description.

        Returns the eight documented keys plus ``preferred_skills``,
        ``experience_level``, ``company_size``, ``responsibilities``, ``title``
        and ``source``.

        Raises :class:`EmptyJobDescriptionError` or
        :class:`MalformedJobDescriptionError` for unusable input. An LLM
        timeout is *not* an error — it degrades to the keyword path.

        Results are cached on the advert text. Note that the caching sits on
        :meth:`_analyze_cleaned`, not on this method: a cache hit skips the
        decorated body entirely, and the assignment to ``_last_description``
        below is what :meth:`extract_requirements` reads when called with no
        argument. Decorating ``analyze`` directly - the obvious placement -
        makes ``extract_requirements()`` raise "No job description available.
        Call analyze() first" *immediately after* a successful ``analyze()``,
        whenever the advert has been seen before. That was reproduced, not
        theorised.
        """
        cleaned = validate_description(job_description)
        self._last_description = cleaned
        fingerprint = self._backend_fingerprint()
        if fingerprint is None:
            return self._analyze_uncached(cleaned)
        return self._analyze_cleaned(cleaned, fingerprint)

    def _backend_fingerprint(self) -> Optional[str]:
        """Names *what would answer*, or ``None`` when it cannot be named.

        Caching on the advert text alone is wrong, and the existing agent tests
        caught it rather than any reasoning of mine. The analysis does not
        depend only on the text: it depends on whether a language model is
        attached and reachable. Cache on text alone and the first analysis run
        while Ollama is down is replayed to everyone for the next two hours -
        keyword-quality output, ``source: "fallback"``, no way to get a better
        answer once the model returns.

        ``None`` means "do not cache". It is returned when the caller supplied
        its own LLM, because two different injected clients cannot be told
        apart in a key without putting object identity in it - and identity in
        a cache key is the bug this whole module exists to avoid: addresses are
        unstable across restarts and are *recycled*, so a fresh client landing
        on a freed address would be served the dead one's answers. Declining to
        cache is the honest answer to "I cannot describe this input", and it
        costs the server nothing: the injected path is tests and bespoke
        callers. The server uses the default client, which is described fully
        by the configured model plus whether it is reachable.
        """
        if self._llm_was_injected:
            return None
        if not getattr(self, "use_llm", False):
            return "fallback"
        try:
            llm = self.llm
            if not llm.is_available():
                return "fallback"
        except Exception:
            return "fallback"
        model = getattr(getattr(self, "config", None), "model", None)
        return "llm:%s:%s" % (getattr(llm, "last_backend", None) or "default", model)

    @cache_result(job_analysis_cache, "job_analysis")
    def _analyze_cleaned(self, cleaned: str, backend: str) -> Dict[str, Any]:
        """Cached entry point. ``backend`` is key material, not a parameter.

        It is never read: it is in the signature so that results produced
        without a model are not replayed once a model is available.
        """
        del backend
        return self._analyze_uncached(cleaned)

    def _analyze_uncached(self, cleaned: str) -> Dict[str, Any]:
        result = self.run(job_description=cleaned)
        output = dict(result.output)
        output["source"] = result.source
        if result.warning:
            output["warning"] = result.warning
        return output

    def extract_requirements(
        self, job_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Just the requirements, in the shape the matcher consumes.

        Call it with no argument to reuse the text given to the last
        :meth:`analyze`.
        """
        text = job_description if job_description is not None else self._last_description
        if not text:
            raise EmptyJobDescriptionError(
                "No job description available. Call analyze() first, or pass "
                "the text in directly."
            )

        analysis = self.analyze(text)
        return {
            "required_skills": analysis["required_skills"],
            "tech_stack": analysis["tech_stack"],
            "experience_level": analysis["experience_level"],
            "soft_skills": analysis["soft_skills"],
            "education": analysis["education"],
            "role_type": analysis["role_type"],
        }

    def trace_fields(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """The extra columns this agent contributes to the execution trace."""
        return {
            "label": self.label,
            "skills_extracted": len(output.get("required_skills") or []),
            "confidence": output.get("confidence", 0.0),
        }

    # -- BaseAgent hooks --------------------------------------------------

    def parse(self, payload: Dict[str, Any], **inputs: Any) -> Dict[str, Any]:
        """Normalise the model's JSON, filling any gaps from the raw text."""
        description = inputs.get("job_description") or ""

        required = _clean_skill_list(payload.get("required_skills"))
        if not required:
            # A model returning no skills has almost certainly mis-formatted its
            # answer rather than read a job with no requirements at all.
            raise ValueError("Model returned no required skills")

        # ...and a model returning only things that are not technologies has
        # done the same, less obviously.
        #
        # Asked to read "Backend Engineer. Python, FastAPI, Kubernetes and
        # PostgreSQL required", the model answered with a single required
        # skill: "backend engineering". That passes the emptiness check above
        # while being useless to everything downstream, which works by
        # intersecting the advert's skills with the resume's. The observed
        # result was an interview-prep page offering zero technical questions
        # for an advert naming four technologies the candidate has three of,
        # and the advice "build one small thing with Backend".
        #
        # The rules-based extractor reads this advert correctly, so raising
        # here hands over to it rather than losing the analysis.
        if not any(_find_skills(skill) for skill in required):
            raise ValueError(
                "Model returned no recognisable technologies: %s" % ", ".join(required)
            )
        preferred = [
            s
            for s in _clean_skill_list(payload.get("preferred_skills"))
            if s not in set(required)
        ]

        years = _coerce_years(payload.get("experience_years")) or extract_experience_years(
            description
        )
        seniority = _clean_level(payload.get("seniority")) or _detect_seniority(description)
        education = _clean_education(payload.get("education")) or extract_education(
            description
        )

        analysis: Dict[str, Any] = {
            "title": str(payload.get("title") or "").strip() or _guess_title(description),
            "required_skills": required,
            "preferred_skills": preferred,
            "tech_stack": _clean_skill_list(payload.get("tech_stack"))
            or _tech_stack(required),
            "experience_years": years,
            "experience_level": experience_level(years, seniority),
            "soft_skills": _clean_skill_list(payload.get("soft_skills"))
            or find_soft_skills(description),
            "education": education,
            "role_type": _clean_role(payload.get("role_type"))
            or detect_role_type(description),
            "seniority": seniority or "unknown",
            "company_size": detect_company_size(description),
            "responsibilities": _clean_str_list(payload.get("responsibilities"))
            or _extract_responsibilities(description),
        }
        analysis["confidence"] = score_confidence(analysis, source="llm")
        return analysis

    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        """Keyword extraction. No model, no network, fully deterministic."""
        description = validate_description(inputs.get("job_description"))
        title = inputs.get("job_title") or _guess_title(description)

        base = job_analyzer.analyze(
            JobDescription(title=title, description=description)
        )
        required = [s.name for s in base.required_skills]
        years = extract_experience_years(description)
        seniority = base.seniority

        analysis: Dict[str, Any] = {
            "title": base.title,
            "required_skills": required,
            "preferred_skills": [s.name for s in base.preferred_skills],
            "tech_stack": _tech_stack(required),
            "experience_years": years,
            "experience_level": experience_level(years, seniority),
            "soft_skills": find_soft_skills(description),
            "education": extract_education(description),
            "role_type": detect_role_type(f"{title}\n{description}"),
            "seniority": seniority or "unknown",
            "company_size": detect_company_size(description),
            "responsibilities": base.responsibilities,
        }
        analysis["confidence"] = score_confidence(analysis, source="fallback")

        logger.info(
            "Job Analyzer: %d skill(s), role=%s, confidence=%.2f",
            len(required),
            analysis["role_type"],
            analysis["confidence"],
        )
        return analysis


# ---------------------------------------------------------------------------
# Normalisation helpers for whatever the model returns
# ---------------------------------------------------------------------------

_VALID_ROLES = set(_ROLE_PATTERNS) | {"fullstack", "general"}
_VALID_EDUCATION = {"phd", "masters", "bachelors", "degree", "bootcamp", "not required"}


def _coerce_years(value: Any) -> int:
    """Models return 5, "5", "5+ years" or nonsense. Accept the first three."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        years = int(value)
    else:
        match = re.search(r"\d{1,2}", str(value))
        if not match:
            return 0
        years = int(match.group())
    return years if 0 < years <= _MAX_PLAUSIBLE_YEARS else 0


def _clean_level(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if text in SENIORITY_PATTERNS else None


def _clean_role(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    text = text.replace("full-stack", "fullstack").replace("full stack", "fullstack")
    text = text.replace("ml/ai", "ai/ml").replace("ai / ml", "ai/ml")
    return text if text in _VALID_ROLES else None


def _clean_education(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text.split(" (")[0] in _VALID_EDUCATION:
        return text
    return None


job_analyzer_agent = JobAnalyzerAgent()
