"""Describe a resume on its own terms, with no job advert to compare it to.

Every other agent in this package answers "how well does this candidate fit
*that* advert". This one answers the question a user actually asks first:
**"what does my CV say about me?"**

It is deliberately separate from :mod:`agents.job_analyzer` because the two
have different failure modes. A job analyser that finds no requirements should
say so and score nothing. A resume profiler that finds no skills is looking at
a resume that genuinely lists none, and the useful answer is a list of things
to add -- not a zero.

The same honesty rule as the rest of the codebase applies throughout: a field
the resume does not state comes back as ``None`` or an empty list, never as a
zero or an invented guess. ``experience_years=None`` means "the CV never says",
which is a different fact from "no experience".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.base_agent import BaseAgent
from agents.match_calculator import extract_resume_education
from utils.logger import get_logger
from utils.skills import CONCEPT_SKILLS, find_skills

logger = get_logger(__name__)

#: How much resume text to hand the model. Long enough for any real CV, short
#: enough that a pasted-in portfolio does not blow the context window.
MAX_PROMPT_CHARS = 12000

#: Display groupings for the skill vocabulary in :mod:`utils.skills`. These
#: mirror the comment headings on ``KNOWN_SKILLS``; kept here rather than there
#: because they are a presentation concern, and the scorer must never start
#: treating a group as a requirement.
SKILL_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Languages", (
        "python", "java", "javascript", "typescript", "go", "rust", "c++",
        "c#", "ruby", "php", "scala", "kotlin", "swift", "bash",
    )),
    ("Data", (
        "sql", "nosql", "postgresql", "mysql", "mongodb", "redis",
        "elasticsearch", "snowflake", "spark", "airflow", "kafka",
    )),
    ("Web and APIs", (
        "fastapi", "django", "flask", "react", "vue", "angular", "node.js",
        "next.js", "svelte", "rest", "graphql", "grpc", "microservices",
    )),
    ("Infrastructure", (
        "docker", "kubernetes", "terraform", "ansible", "aws", "azure", "gcp",
        "ci/cd", "jenkins", "github actions", "linux", "nginx",
    )),
    ("AI and ML", (
        "langchain", "langgraph", "llamaindex", "pytorch", "tensorflow",
        "keras", "scikit-learn", "pandas", "numpy", "hugging face", "ollama",
        "rag", "llm", "nlp", "machine learning", "deep learning",
        "computer vision", "prompt engineering", "vector database",
        "chromadb", "pinecone", "embeddings",
    )),
    ("Ways of working", (
        "git", "agile", "scrum", "tdd", "unit testing", "system design",
    )),
)

#: ``(role, signal skills, search phrases)``. A resume is assigned the role
#: whose signals it matches most often. The phrases are what gets typed into a
#: job board on the user's behalf, so they are written the way adverts are
#: titled rather than the way skills are named.
ROLE_SIGNALS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("ai/ml engineer", (
        "langchain", "langgraph", "llamaindex", "pytorch", "tensorflow",
        "keras", "scikit-learn", "hugging face", "ollama", "rag", "llm",
        "nlp", "machine learning", "deep learning", "computer vision",
        "prompt engineering", "vector database", "chromadb", "pinecone",
        "embeddings",
    ), ("ai engineer", "machine learning engineer", "llm engineer")),
    ("data engineer", (
        "sql", "nosql", "postgresql", "mysql", "mongodb", "snowflake",
        "spark", "airflow", "kafka", "pandas", "numpy", "elasticsearch",
    ), ("data engineer", "analytics engineer")),
    ("backend developer", (
        "python", "java", "go", "rust", "c#", "ruby", "php", "scala",
        "fastapi", "django", "flask", "node.js", "rest", "graphql", "grpc",
        "microservices",
    ), ("backend developer", "backend engineer", "software engineer")),
    ("frontend developer", (
        "javascript", "typescript", "react", "vue", "angular", "next.js",
        "svelte",
    ), ("frontend developer", "react developer")),
    ("devops engineer", (
        "docker", "kubernetes", "terraform", "ansible", "aws", "azure", "gcp",
        "ci/cd", "jenkins", "github actions", "linux", "nginx",
    ), ("devops engineer", "site reliability engineer", "platform engineer")),
    ("mobile developer", (
        "swift", "kotlin",
    ), ("mobile developer", "android developer", "ios developer")),
)

#: A role needs at least this many signals before it is named. One shared
#: keyword is a coincidence, not a career.
MIN_ROLE_SIGNALS = 2

SENIORITY_ORDER = (
    "intern", "junior", "mid", "senior", "staff", "lead", "unknown",
)

#: Words that state seniority outright. Checked only when the resume gives no
#: number of years, and matched as whole words so "internal" is not an intern
#: and "principally" is not a principal.
_SENIORITY_WORDS: Tuple[Tuple[str, str], ...] = (
    ("lead", "lead"),
    ("principal", "lead"),
    ("head of", "lead"),
    ("staff engineer", "staff"),
    ("senior", "senior"),
    ("sr.", "senior"),
    ("mid-level", "mid"),
    ("junior", "junior"),
    ("jr.", "junior"),
    ("graduate", "junior"),
    ("fresher", "junior"),
    ("intern", "intern"),
    ("trainee", "intern"),
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
#: A run that *might* be a phone number. Deliberately loose, because the digit
#: count is what actually decides -- see :func:`_has_phone`. The stricter
#: pattern in the indexer wants three separated groups and so misses
#: ``+91 98765 43210``, which is how most of India writes a mobile number.
_PHONE_CANDIDATE_RE = re.compile(r"[+(]?\d[\d\s().-]{7,18}\d")
_YEARS_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE
)
#: A digit that is doing work in a bullet: a percentage, a multiplier, a count.
#: Used only to tell "I improved performance" from "I cut latency by 40%".
_METRIC_RE = re.compile(r"\d+\s*(?:%|x\b|k\b|m\b|ms\b|s\b|users?|requests?)", re.I)

_SECTION_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("experience", ("experience", "employment", "work history", "career")),
    ("education", ("education", "academic", "qualification")),
    ("projects", ("project", "portfolio")),
    ("skills", ("skills", "technologies", "technical summary", "tech stack")),
)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _clean_list(value: Any, limit: int) -> List[str]:
    """Coerce whatever the model returned into a short list of clean strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        text = _as_text(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def group_skills(skills: Sequence[str]) -> Dict[str, List[str]]:
    """Bucket a flat skill list for display. Empty groups are dropped.

    A group that would render as an empty row tells the reader nothing except
    that a category exists, so it is not returned at all.
    """
    lowered = {s.lower() for s in skills}
    grouped: Dict[str, List[str]] = {}
    for label, members in SKILL_GROUPS:
        hits = sorted(lowered.intersection(members))
        if hits:
            grouped[label] = hits
    unclassified = sorted(
        lowered.difference({m for _, members in SKILL_GROUPS for m in members})
    )
    if unclassified:
        grouped["Other"] = unclassified
    return grouped


def infer_role(skills: Sequence[str]) -> Tuple[str, List[str], List[str]]:
    """Work out the job family a skill list points at.

    Returns ``(role, suggested_titles, search_queries)``. A resume matching
    both the backend and frontend signals is called fullstack rather than
    being forced into whichever list happens to be longer.
    """
    lowered = {s.lower() for s in skills}
    scores: List[Tuple[int, str, Tuple[str, ...]]] = []
    for role, signals, phrases in ROLE_SIGNALS:
        hits = len(lowered.intersection(signals))
        if hits >= MIN_ROLE_SIGNALS:
            scores.append((hits, role, phrases))

    if not scores:
        return "unknown", [], []

    scores.sort(key=lambda row: -row[0])
    named = {row[1] for row in scores}
    if "backend developer" in named and "frontend developer" in named:
        top_role = "fullstack developer"
        phrases: List[str] = ["fullstack developer", "full stack engineer"]
    else:
        top_role = scores[0][1]
        phrases = list(scores[0][2])

    titles: List[str] = []
    for _, _, role_phrases in scores[:3]:
        for phrase in role_phrases:
            if phrase not in titles:
                titles.append(phrase)
    return top_role, titles[:5], phrases[:3]


def seniority_from(years: Optional[float], text: str) -> str:
    """Name a seniority band, preferring a stated number to a stated word.

    Returns ``"unknown"`` when the resume gives neither. That is a real
    answer: plenty of CVs never say, and inventing "junior" for them would be
    a guess presented as a fact.
    """
    if years is not None:
        if years >= 10:
            return "lead"
        if years >= 8:
            return "staff"
        if years >= 5:
            return "senior"
        if years >= 2:
            return "mid"
        return "junior"

    lowered = text.lower()
    for word, band in _SENIORITY_WORDS:
        if word in lowered:
            return band
    return "unknown"


def _sections_present(text: str) -> Dict[str, bool]:
    lowered = text.lower()
    return {
        name: any(word in lowered for word in words)
        for name, words in _SECTION_WORDS
    }


def _education(text: str) -> Optional[str]:
    """The highest qualification the CV names, or None if it names none.

    None rather than the extractor's "not specified" string, so the card can
    say "Not stated" instead of presenting an absent degree as a finding.
    """
    level = extract_resume_education(text)
    return None if level == "not specified" else level


def _has_phone(text: str) -> bool:
    """True when some run of digits is the right length to be a phone number.

    Counting digits rather than matching a shape is what makes this work
    across formats: ``+91 98765 43210``, ``+1 (555) 123-4567`` and
    ``020 7946 0018`` are the same ten-to-eleven digits differently spaced.
    """
    for match in _PHONE_CANDIDATE_RE.finditer(text):
        digits = sum(1 for ch in match.group(0) if ch.isdigit())
        if 9 <= digits <= 15:
            return True
    return False


def _improvements(
    text: str,
    skills: Sequence[str],
    years: Optional[float],
    sections: Dict[str, bool],
) -> List[str]:
    """Concrete, checkable faults in the document itself.

    Every item here is something the reader can act on this afternoon. None of
    them is career advice, because the agent has not been shown a job advert
    and is in no position to give any.
    """
    notes: List[str] = []
    if not _EMAIL_RE.search(text):
        notes.append(
            "No email address is on the CV. A recruiter who likes it cannot "
            "reply to it."
        )
    if not _has_phone(text):
        notes.append("No phone number is on the CV.")
    if years is None:
        notes.append(
            "The CV never states how many years you have worked. Screening "
            "filters key on that phrase, so add it in the form "
            "\"4 years of experience\"."
        )
    if len(skills) < 5:
        counted = (
            "one recognised technology is"
            if len(skills) == 1
            else "%d recognised technologies are" % len(skills)
        )
        notes.append(
            "Only %s named. List the languages, frameworks and databases you "
            "have actually used - keyword filters cannot infer them." % counted
        )
    if not sections.get("projects"):
        notes.append(
            "There is no projects section. It is the cheapest way to evidence "
            "a skill you have not been paid for yet."
        )
    if not sections.get("education"):
        notes.append("There is no education section.")
    if not _METRIC_RE.search(text):
        notes.append(
            "No bullet carries a number. \"Cut response time by 40%\" is "
            "read; \"improved performance\" is skimmed."
        )
    return notes[:5]


def _strengths(
    skills: Sequence[str],
    grouped: Dict[str, List[str]],
    years: Optional[float],
    sections: Dict[str, bool],
) -> List[str]:
    notes: List[str] = []
    if years is not None:
        notes.append("States %g years of experience outright." % years)
    broad = [label for label, members in grouped.items() if len(members) >= 3]
    for label in broad[:3]:
        notes.append(
            "%s is well covered: %s." % (label, ", ".join(grouped[label]))
        )
    concrete = [s for s in skills if s not in CONCEPT_SKILLS]
    if len(concrete) >= 8:
        notes.append(
            "Names %d concrete tools, which is plenty for a keyword screen."
            % len(concrete)
        )
    if sections.get("projects"):
        notes.append("Has a projects section backing the skill list up.")
    return notes[:5]


def _headline(
    role: str,
    seniority: str,
    years: Optional[float],
    skills: Sequence[str],
    grouped: Dict[str, List[str]],
) -> str:
    """One or two sentences of plain description, hedged where the CV is."""
    if not skills:
        return (
            "This CV does not name a single technology we recognise, so there "
            "is nothing here to describe yet. Add a skills section listing "
            "the languages and tools you have used."
        )

    if role == "unknown":
        opening = (
            "This CV names %d technologies but they do not cluster into one "
            "recognisable job family." % len(skills)
        )
    elif seniority == "unknown":
        opening = (
            "This CV reads as a %s. It does not state a seniority, so we are "
            "not guessing at one." % role
        )
    else:
        opening = "This CV reads as a %s %s." % (seniority, role)

    if years is not None:
        opening += " It states %g years of experience." % years

    strongest = max(grouped.items(), key=lambda kv: len(kv[1]))[0] if grouped else ""
    if strongest:
        opening += " The deepest area is %s." % strongest.lower()
    return opening


class ResumeProfilerAgent(BaseAgent):
    """Turn one resume into a description of the person behind it."""

    name = "resume_profiler"
    description = "Describes a resume on its own, with no job advert involved."
    prompt_name = "resume_review"
    required_inputs = ("resume_text",)

    def prompt_values(self, **inputs: Any) -> Dict[str, Any]:
        text = _as_text(inputs.get("resume_text"))
        return {"resume_text": text[:MAX_PROMPT_CHARS]}

    def parse(self, payload: Dict[str, Any], **inputs: Any) -> Dict[str, Any]:
        """Normalise the model's JSON, and re-derive anything it may have made up.

        The skill list is intersected with the known vocabulary rather than
        taken on trust: a model asked for "skills evidenced in the text" will
        still occasionally return one that is not in it, and a fabricated
        skill is worse than a missing one because it is the thing the user
        will be asked about in an interview.
        """
        text = _as_text(inputs.get("resume_text"))
        evidenced = find_skills(text)

        claimed = {s.lower() for s in _clean_list(payload.get("skills"), 60)}
        skills = sorted(claimed.intersection(evidenced)) or evidenced

        years = payload.get("experience_years")
        try:
            years = float(years) if years is not None else None
        except (TypeError, ValueError):
            years = None

        role = _as_text(payload.get("primary_role")).strip().lower()
        derived_role, derived_titles, derived_queries = infer_role(skills)
        grouped = group_skills(skills)

        seniority = _as_text(payload.get("seniority")).strip().lower()
        if seniority not in SENIORITY_ORDER:
            seniority = seniority_from(years, text)

        return {
            "headline": _as_text(payload.get("headline")).strip()
            or _headline(role or derived_role, seniority, years, skills, grouped),
            "primary_role": role or derived_role,
            "seniority": seniority,
            "experience_years": years,
            "education": _education(text),
            "skills": skills,
            "skill_groups": grouped,
            "strengths": _clean_list(payload.get("strengths"), 5),
            "improvements": _clean_list(payload.get("improvements"), 5),
            "suggested_roles": _clean_list(payload.get("suggested_roles"), 5)
            or derived_titles,
            "search_queries": _clean_list(payload.get("search_queries"), 4)
            or derived_queries,
        }

    def fallback(self, **inputs: Any) -> Dict[str, Any]:
        """Describe the resume with regexes and the shared skill vocabulary.

        This is what runs when no model is configured, and it is why the
        feature works at all on a laptop with no API key. It is narrower than
        the LLM path -- it cannot read prose about an unlisted technology --
        but nothing it reports is invented.
        """
        text = _as_text(inputs.get("resume_text"))
        skills = find_skills(text)
        grouped = group_skills(skills)

        stated = [float(v) for v in _YEARS_RE.findall(text)]
        years = max(stated) if stated else None

        role, titles, queries = infer_role(skills)
        seniority = seniority_from(years, text)
        sections = _sections_present(text)

        return {
            "headline": _headline(role, seniority, years, skills, grouped),
            "primary_role": role,
            "seniority": seniority,
            "experience_years": years,
            "education": _education(text),
            "skills": skills,
            "skill_groups": grouped,
            "strengths": _strengths(skills, grouped, years, sections),
            "improvements": _improvements(text, skills, years, sections),
            "suggested_roles": titles,
            "search_queries": queries,
        }


#: Shared instance. Agents here hold no per-request state.
resume_profiler = ResumeProfilerAgent()
