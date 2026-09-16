"""Rewrite suggestions that tailor a resume to one specific advert.

The other agents describe the candidate. This one argues on their behalf: same
career, told in the language the employer used, with the relevant parts moved
to the top.

**Two rules constrain everything here, and they are not negotiable.**

1. *Never invent an achievement.* It is trivial to turn "Built RAG system with
   LangChain" into "...processing 10K+ documents at 95% retrieval accuracy",
   and the result reads wonderfully. It is also a fabrication that the
   candidate will have to defend in an interview. So where a metric belongs,
   this module emits a **placeholder** - ``[NUMBER]``, ``[PERCENTAGE]`` - for
   the candidate to fill in from their own memory. The suggestion stays
   copy-pasteable; the number stays theirs.

2. *Never suggest a keyword the resume cannot support.* Adding "LangGraph" to
   a skills list because the advert wants it is lying, and it is the specific
   lie that collapses in a technical screen. Keywords are only suggested when
   the resume already evidences the skill and merely under-sells it. Skills
   the gap detector flagged as missing are excluded and reported separately
   under ``keywords_blocked_by_gaps``.

Everything is deterministic and offline: same resume plus same advert gives the
same advice, and the wording rules live in editable tables rather than inside a
prompt.

Example:
    >>> report = resume_optimizer.optimize_resume(resume, job, gaps, match)
    >>> report["improvements"][0]["suggested"]
    'AI/ML Engineer specialising in LangChain, RAG and embeddings...'
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from rag.resume_indexer import Section, split_bullets, split_into_sections
from utils.logger import get_logger, observed
from utils.skills import find_skills, match_skill, normalise_skill
from utils.validation import as_dict

logger = get_logger(__name__)

__all__ = [
    "ResumeOptimizerAgent",
    "resume_optimizer",
    "HIGH",
    "MEDIUM",
    "LOW",
    "WEAK_VERBS",
    "PLACEHOLDERS",
]


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

_IMPACT_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: A skill named this often in an advert is what the role is actually about.
HEAVILY_STRESSED = 3

#: Placeholders the candidate must replace. Listed on every suggestion that
#: contains one so they cannot be pasted in unnoticed.
PLACEHOLDERS = ("[NUMBER]", "[PERCENTAGE]", "[TIMEFRAME]", "[SCALE]", "[RESULT]")

#: Openings that describe activity rather than accomplishment. The replacement
#: is not decoration - "responsible for" says you held a role, "owned" says you
#: were accountable for an outcome, and only one of those is worth reading.
WEAK_VERBS: Dict[str, str] = {
    "responsible for": "Owned",
    "worked on": "Delivered",
    "helped with": "Drove",
    "helped": "Drove",
    "assisted with": "Supported",
    "assisted": "Supported",
    "participated in": "Contributed to",
    "involved in": "Contributed to",
    "worked with": "Applied",
    "used": "Applied",
    "utilised": "Applied",
    "utilized": "Applied",
    "made": "Developed",
    "did": "Executed",
    "handled": "Managed",
    "took part in": "Contributed to",
    "learned": "Adopted",
    "familiar with": "Applied",
    "exposure to": "Applied",
    "built": "Engineered",
    "created": "Designed",
    "wrote": "Authored",
    "worked as": "Served as",
}

#: Verbs that already carry weight; leave them alone.
_STRONG_VERBS = {
    "architected", "engineered", "designed", "led", "owned", "delivered",
    "shipped", "scaled", "optimised", "optimized", "automated", "reduced",
    "increased", "improved", "launched", "drove", "established", "migrated",
    "rebuilt", "authored", "mentored", "spearheaded", "developed", "deployed",
}

#: Anything matching these counts as a real, checkable number.
_METRIC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*%|\$\s*\d|\b\d{1,3}(?:,\d{3})+\b|\b\d+\s*(?:k|m|bn|x)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds|minutes|hours|days|weeks|months|years)\b"
    # A bare number counts, except a calendar year. "(2022-2023)" is when the
    # job happened, not evidence of what it achieved, and counting it would
    # let every dated role masquerade as a quantified one.
    r"|\b(?!(?:19|20)\d{2}\b)\d+(?:\.\d+)?\b)",
    re.IGNORECASE,
)

#: Sections in the order that serves a technical application. Anything not
#: listed keeps its original position relative to these.
_IDEAL_ORDER = [
    Section.SUMMARY,
    Section.SKILLS,
    Section.EXPERIENCE,
    Section.PROJECTS,
    Section.ACHIEVEMENTS,
    Section.EDUCATION,
    Section.OTHER,
]

#: Skills nobody is hired *for*. They belong on the resume, but a headline
#: built on "Git" tells the reader nothing they did not already assume.
_COMMODITY_SKILLS = {
    "git", "github", "gitlab", "jira", "agile", "scrum", "linux", "excel",
    "word", "powerpoint", "windows", "macos", "vscode", "slack",
}

_SECTION_LABELS = {
    Section.SUMMARY: "Professional Summary",
    Section.SKILLS: "Skills",
    Section.EXPERIENCE: "Experience",
    Section.PROJECTS: "Projects",
    Section.ACHIEVEMENTS: "Achievements",
    Section.EDUCATION: "Education",
    Section.OTHER: "Other",
}

#: Words that mark a line as junior framing worth moving below stronger work.
_DOWNPLAY_MARKERS = (
    "intern", "internship", "trainee", "coursework", "bootcamp",
    "hobby", "personal interest", "workshop attended",
)

#: Display spellings, mirroring the gap detector's table for the names that
#: `.title()` gets wrong.
_DISPLAY_NAMES: Dict[str, str] = {
    "ci/cd": "CI/CD", "aws": "AWS", "gcp": "GCP", "sql": "SQL",
    "nosql": "NoSQL", "rest": "REST", "graphql": "GraphQL", "grpc": "gRPC",
    "llm": "LLM", "nlp": "NLP", "rag": "RAG", "mcp": "MCP", "tdd": "TDD",
    "api": "API", "etl": "ETL", "html": "HTML", "css": "CSS",
    "javascript": "JavaScript", "typescript": "TypeScript",
    "node.js": "Node.js", "next.js": "Next.js", "c++": "C++", "c#": "C#",
    "postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite",
    "mongodb": "MongoDB", "chromadb": "ChromaDB", "faiss": "FAISS",
    "langchain": "LangChain", "langgraph": "LangGraph",
    "llamaindex": "LlamaIndex", "pytorch": "PyTorch",
    "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn",
    "fastapi": "FastAPI", "github actions": "GitHub Actions",
    "hugging face": "Hugging Face", "devops": "DevOps",
    "machine learning": "Machine Learning", "deep learning": "Deep Learning",
    "computer vision": "Computer Vision", "vector database": "Vector Databases",
    "embeddings": "Embeddings", "prompt engineering": "Prompt Engineering",
}


def _display(skill: str) -> str:
    """Present a canonical skill the way a human would write it."""
    key = skill.strip().lower()
    if key in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[key]
    return " ".join(word.capitalize() for word in key.split())


def _count_word(lowered: str, skill: str) -> int:
    """Count whole-word occurrences of a skill in already-lowercased text.

    Plain substring counting would report "Go" inside "Django" and "R" inside
    every other word, so occurrences are bounded by anything that is not
    alphanumeric. Lookarounds are used rather than ``\\b`` because several real
    skill names end in punctuation - ``c++``, ``ci/cd``, ``node.js`` - where
    ``\\b`` either fails or matches in the wrong place.
    """
    if not lowered or not skill:
        return 0
    pattern = r"(?<![a-z0-9])" + re.escape(skill.strip().lower()) + r"(?![a-z0-9])"
    try:
        return len(re.findall(pattern, lowered))
    except re.error:  # pragma: no cover - only reachable via a corrupt skill name
        return 0


def _clean(values: Any) -> List[str]:
    """Normalise anything list-shaped into canonical skill names."""
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    out: List[str] = []
    for value in values:
        name = normalise_skill(str(value))
        if name and name not in out:
            out.append(name)
    return out


def _sentence(text: str) -> str:
    """Tidy spacing and guarantee terminal punctuation."""
    clean = " ".join(str(text).split()).strip()
    if clean and clean[-1] not in ".!?":
        clean += "."
    return clean


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class ResumeOptimizerAgent:
    """Turns a resume and an advert into concrete, paste-ready edits.

    Follows the same shape as :class:`~agents.match_calculator.MatchCalculator`
    and :class:`~agents.gap_detector.GapDetectorAgent`: plain dicts in, plain
    dict out, no model objects in the way.
    """

    label = "Resume Optimizer"
    max_improvements = 12

    # -- Public API --------------------------------------------------------- #
    @observed("optimize_resume")
    def optimize_resume(
        self,
        resume_data: Dict[str, Any],
        job_analysis: Dict[str, Any],
        gaps: Optional[Dict[str, Any]] = None,
        match_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Suggest edits that tailor this resume to this advert.

        Args:
            resume_data: ``{"resume_text": "..."}`` and/or ``{"skills": [...]}``.
                The text is what makes the interesting suggestions possible;
                with only a skills list the advice is necessarily thinner.
            job_analysis: Output of :meth:`JobAnalyzerAgent.analyze`.
            gaps: Optional output of :meth:`GapDetectorAgent.detect_gaps`. Used
                to *exclude* keywords the candidate cannot honestly claim.
            match_data: Optional output of :meth:`MatchCalculator.calculate_match`.
                Its ``found`` lists confirm which skills the resume evidences.

        Returns:
            A dict with ``resume_title``, ``improvements``,
            ``projects_to_highlight``, ``keywords_to_add``,
            ``keywords_to_remove``, ``reordering``, ``tailored_summary`` and
            ``confidence``.
        """
        # See utils.validation: a wrong-shaped argument degrades the report
        # rather than ending the run.
        resume_data = as_dict(resume_data, "resume_data")
        job_analysis = as_dict(job_analysis, "job_analysis")
        gaps = as_dict(gaps, "gaps") or None
        match_data = as_dict(match_data, "match_data") or None

        text = str(resume_data.get("resume_text") or "").strip()
        sections = self._sections(text)

        jd_keywords = self._generate_keyword_suggestions(job_analysis)
        resume_skills = self._resume_skills(resume_data, text, match_data)
        blocked = self._blocked_skills(gaps, match_data)

        improvements: List[Dict[str, Any]] = []
        for section, body in sections:
            improvements.extend(
                self._analyze_section(
                    section,
                    jd_keywords,
                    body=body,
                    resume_skills=resume_skills,
                )
            )

        improvements.extend(
            self._emphasis_improvements(text, jd_keywords, resume_skills)
        )
        improvements = self._rank(improvements)[: self.max_improvements]

        projects = self._match_projects_to_jd(
            self._parse_projects(sections), job_analysis
        )
        summary = self._create_tailored_summary(
            resume_data, match_data, job_analysis, resume_skills, text
        )

        report = {
            "resume_title": self._resume_title(job_analysis, resume_skills, jd_keywords),
            "improvements": improvements,
            "projects_to_highlight": projects,
            "keywords_to_add": self._keywords_to_add(
                jd_keywords, resume_skills, text, blocked
            ),
            "keywords_to_remove": self._keywords_to_remove(
                resume_skills, jd_keywords, job_analysis
            ),
            "keywords_blocked_by_gaps": [_display(s) for s in sorted(blocked)],
            "keyword_density": self._keyword_density_analysis(
                text, jd_keywords, resume_skills, blocked
            ),
            "reordering": self._reordering(sections, jd_keywords),
            "tailored_summary": summary,
            "confidence": self._confidence(text, sections, job_analysis, match_data),
            "high_impact_count": sum(1 for i in improvements if i["impact"] == HIGH),
            "honesty_note": (
                "Placeholders in square brackets are yours to fill in. Never "
                "paste a number you cannot defend, and do not add a skill you "
                "have not used."
            ),
            "source": "rules",
        }

        logger.info(
            "Resume optimiser: %d suggestion(s), %d high impact, confidence %.2f",
            len(improvements),
            report["high_impact_count"],
            report["confidence"],
        )
        return report

    # -- Required-by-spec internals ----------------------------------------- #
    def _analyze_section(
        self,
        section: Any,
        jd_keywords: Sequence[str],
        body: str = "",
        resume_skills: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Suggest edits for one section of the resume.

        Args:
            section: A :class:`Section` member, or its string value.
            jd_keywords: Skills the advert asked for, most-stressed first.
            body: The section's text.
            resume_skills: Everything the resume evidences, for honesty checks.
            advert: Raw advert text, used for keyword weighting.
        """
        section = self._as_section(section)
        label = _SECTION_LABELS.get(section, str(section).title())
        skills = resume_skills or set()
        suggestions: List[Dict[str, Any]] = []

        if section is Section.SUMMARY:
            suggestions.extend(self._summary_improvements(label, body, jd_keywords, skills))
        elif section in (Section.EXPERIENCE, Section.PROJECTS, Section.ACHIEVEMENTS):
            suggestions.extend(self._bullet_improvements(label, body, jd_keywords, skills))
        elif section is Section.SKILLS:
            suggestions.extend(self._skills_improvements(label, body, jd_keywords, skills))

        return suggestions

    def _extract_metrics(self, descriptions: Iterable[str]) -> Dict[str, Any]:
        """Find which lines already carry numbers, and which are asking for one.

        A resume that quantifies nothing reads as a list of responsibilities.
        The useful signal is not "does this resume have numbers" but "which
        specific lines would be stronger with one", so both halves are returned.
        """
        quantified: List[str] = []
        unquantified: List[str] = []

        for line in descriptions:
            text = str(line).strip()
            if not text:
                continue
            if self._has_metric(text):
                quantified.append(text)
            else:
                unquantified.append(text)

        total = len(quantified) + len(unquantified)
        return {
            "quantified": quantified,
            "unquantified": unquantified,
            "total": total,
            "ratio": round(len(quantified) / total, 2) if total else 0.0,
        }

    def _keyword_density_analysis(
        self,
        text: str,
        jd_keywords: Sequence[Tuple[str, int]],
        resume_skills: Set[str],
        blocked: Set[str],
        limit: int = 12,
    ) -> List[Dict[str, Any]]:
        """How often the advert says a word, against how often the resume does.

        This is counting, not judgement: both numbers are shown so the
        candidate can disagree with the verdict. A screen that says "LangChain:
        8 in the advert, 1 on your resume" is more use than one that says
        "increase LangChain", because it shows the size of the difference.

        A keyword the candidate cannot honestly claim is still listed -- with
        the count that proves it matters -- but the action says learn it, not
        add it. Silently dropping it would hide the most important row on the
        screen.
        """
        lowered = (text or "").lower()
        rows: List[Dict[str, Any]] = []

        for skill, jd_count in list(jd_keywords)[:limit]:
            resume_count = _count_word(lowered, skill)
            evidenced = skill in resume_skills

            if skill in blocked:
                verdict, action = (
                    "gap",
                    f"Marked as a gap - learn {_display(skill)} before claiming it.",
                )
            elif resume_count == 0 and not evidenced:
                verdict, action = (
                    "absent",
                    f"Not on your resume. Only add {_display(skill)} if you have used it.",
                )
            elif resume_count == 0 and evidenced:
                verdict, action = (
                    "implied",
                    f"Your experience covers {_display(skill)} but never names it - "
                    "use the advert's word.",
                )
            elif jd_count >= HEAVILY_STRESSED and resume_count < 2:
                verdict, action = (
                    "under-used",
                    f"Named once against {jd_count} in the advert - work it into "
                    "a second bullet where it is true.",
                )
            else:
                verdict, action = ("balanced", "Good balance - leave it alone.")

            rows.append(
                {
                    "keyword": _display(skill),
                    "in_resume": resume_count,
                    "in_job_advert": jd_count,
                    "verdict": verdict,
                    "action": action,
                }
            )

        return rows

    def _match_projects_to_jd(
        self, projects: Sequence[Dict[str, Any]], job_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Score each project on how directly it answers the advert.

        Required skills are worth more than preferred ones, because a project
        demonstrating a hard requirement is the single most persuasive thing on
        a technical resume.
        """
        required = set(_clean(job_analysis.get("required_skills")))
        preferred = set(_clean(job_analysis.get("preferred_skills")))
        stack = set(_clean(job_analysis.get("tech_stack")))
        if not (required or preferred):
            return []

        scored: List[Dict[str, Any]] = []
        for project in projects:
            project_skills = set(_clean(find_skills(project["text"])))
            hits_required = sorted(project_skills & required)
            hits_preferred = sorted(project_skills & preferred)
            hits_stack = sorted(project_skills & stack)

            if not (hits_required or hits_preferred):
                continue

            # Scored against what one project can plausibly demonstrate, not
            # against the whole requirement list. An advert naming eleven
            # skills would otherwise cap every honest project at ~30%, and
            # every suggestion would come back "drop this".
            reach = max(1, min(len(required), 3)) if required else 1
            coverage = min(1.0, len(hits_required) / reach)
            score = coverage * 70 + len(hits_stack) * 12 + len(hits_preferred) * 5
            score = int(min(100, round(score)))

            scored.append(
                {
                    "project": project["name"],
                    "relevance_score": score,
                    "matched_skills": [_display(s) for s in hits_required + hits_preferred],
                    "why": self._project_why(hits_required, hits_stack, hits_preferred),
                    "suggestion": self._project_suggestion(score, project["position"]),
                }
            )

        scored.sort(key=lambda p: (-p["relevance_score"], p["project"]))
        return scored

    def _generate_keyword_suggestions(
        self, jd_analysis: Dict[str, Any]
    ) -> List[Tuple[str, int]]:
        """The advert's vocabulary, ordered by how hard it leans on each word.

        Returns ``(skill, mentions)`` pairs. Repetition is the clearest signal
        an employer gives about what the role is really about, so a skill named
        eight times should shape the resume more than one named once.
        """
        advert = str(jd_analysis.get("job_description") or "").lower()
        required = _clean(jd_analysis.get("required_skills"))
        preferred = _clean(jd_analysis.get("preferred_skills"))
        stack = set(_clean(jd_analysis.get("tech_stack")))

        weighted: List[Tuple[str, int]] = []
        for skill in required + [s for s in preferred if s not in required]:
            mentions = advert.count(skill) if advert else 0
            # Without the raw advert, fall back to structure: core-stack and
            # required skills still outrank preferred ones.
            if not advert:
                mentions = 3 if skill in stack else (2 if skill in required else 1)
            weighted.append((skill, mentions))

        weighted.sort(key=lambda pair: (-pair[1], pair[0]))
        return weighted

    def _suggest_wording(
        self,
        original_text: str,
        jd_keywords: Sequence[str],
        resume_skills: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Rewrite one line: stronger verb, advert's vocabulary, room for a metric.

        Returns the rewrite plus the reasons for it, so the caller can explain
        the change rather than merely assert it. Returns ``changed: False`` when
        the line is already doing its job.
        """
        original = " ".join(str(original_text).split())
        if not original:
            return {"changed": False, "suggested": original, "reasons": [], "placeholders": []}

        suggested = original
        reasons: List[str] = []

        verb_swap = self._upgrade_verb(suggested)
        if verb_swap:
            suggested = verb_swap["text"]
            reasons.append(
                f"'{verb_swap['from']}' describes activity; "
                f"'{verb_swap['to']}' describes ownership"
            )

        allowed = resume_skills if resume_skills is not None else set()
        woven = self._weave_keywords(suggested, jd_keywords, allowed)
        if woven:
            suggested = woven["text"]
            reasons.append(
                "uses the advert's own wording for "
                + ", ".join(_display(s) for s in woven["skills"])
            )

        placeholders: List[str] = []
        if self._wants_metric(suggested) and not self._has_metric(suggested):
            suggested = self._add_metric_slot(suggested)
            placeholders = [p for p in PLACEHOLDERS if p in suggested]
            if placeholders:
                reasons.append(
                    "a number makes the claim checkable - fill in "
                    + ", ".join(placeholders)
                )

        return {
            "changed": suggested != original,
            "suggested": _sentence(suggested),
            "reasons": reasons,
            "placeholders": placeholders,
        }

    def _create_tailored_summary(
        self,
        resume: Dict[str, Any],
        match: Optional[Dict[str, Any]],
        job_analysis: Optional[Dict[str, Any]] = None,
        resume_skills: Optional[Set[str]] = None,
        text: str = "",
    ) -> str:
        """Write a professional summary built only from what the resume proves.

        Every skill named here is one the resume already evidences. The advert
        decides the *order and emphasis*, never the content - otherwise the
        summary becomes a wish list.
        """
        job_analysis = job_analysis or {}
        text = text or str(resume.get("resume_text") or "")
        skills = resume_skills if resume_skills is not None else self._resume_skills(
            resume, text, match
        )

        title = self._role_noun(job_analysis)
        years = self._years(resume, text)
        headline_skills = [
            s for s, _ in self._generate_keyword_suggestions(job_analysis) if s in skills
        ][:4]
        if not headline_skills:
            headline_skills = sorted(skills)[:4]

        parts: List[str] = []
        opening = title
        if years:
            opening = f"{title} with {years} of experience"
        if headline_skills:
            opening += " specialising in " + self._join(
                [_display(s) for s in headline_skills[:3]]
            )
        parts.append(_sentence(opening))

        supporting = [
            s
            for s in dict.fromkeys(list(headline_skills[3:]) + sorted(skills))
            if s not in headline_skills[:3]
        ]
        if supporting:
            parts.append(
                _sentence(
                    "Hands-on with " + self._join([_display(s) for s in supporting[:4]])
                )
            )

        parts.append(
            _sentence(
                "Delivered [RESULT] on [NUMBER] projects - replace this line with "
                "your strongest measurable outcome"
            )
        )

        # Deliberately nothing here about skills the candidate is "currently
        # learning". Only they know whether that is true, and a summary that
        # gestures at a gap invites exactly the question they cannot answer.
        return " ".join(parts)

    # -- Improvement builders ------------------------------------------------ #
    def _summary_improvements(
        self, label: str, body: str, jd_keywords: Sequence[Tuple[str, int]], skills: Set[str]
    ) -> List[Dict[str, Any]]:
        current = " ".join(body.split())
        if not current:
            return []

        wanted = [s for s, _ in jd_keywords if s in skills]
        present = [s for s in wanted if s in current.lower()]
        missing = [s for s in wanted if s not in present][:5]
        if not missing:
            return []

        rewrite = self._suggest_wording(current, [s for s, _ in jd_keywords], skills)
        return [
            {
                "section": label,
                "current": current,
                "suggested": rewrite["suggested"],
                "why": (
                    "Your summary is the first thing read and currently omits "
                    + str(len(missing))
                    + " skill(s) the advert asks for that you already have: "
                    + self._join([_display(s) for s in missing])
                ),
                "impact": HIGH,
                "placeholders": rewrite["placeholders"],
                "needs_your_input": bool(rewrite["placeholders"]),
            }
        ]

    def _bullet_improvements(
        self, label: str, body: str, jd_keywords: Sequence[Tuple[str, int]], skills: Set[str]
    ) -> List[Dict[str, Any]]:
        bullets = split_bullets(body)
        if not bullets:
            return []

        metrics = self._extract_metrics(bullets)
        keywords = [s for s, _ in jd_keywords]
        out: List[Dict[str, Any]] = []

        for position, line in enumerate(bullets, start=1):
            if len(line) < 12:
                continue
            rewrite = self._suggest_wording(line, keywords, skills)
            if not rewrite["changed"]:
                continue

            relevant = bool(set(_clean(find_skills(line))) & set(keywords))
            impact = HIGH if relevant and rewrite["placeholders"] else (
                MEDIUM if relevant else LOW
            )

            out.append(
                {
                    "section": label,
                    "position": position,
                    "current_description": line,
                    "suggested_description": rewrite["suggested"],
                    "why": self._capitalise(self._join(rewrite["reasons"])),
                    "impact": impact,
                    "placeholders": rewrite["placeholders"],
                    "needs_your_input": bool(rewrite["placeholders"]),
                }
            )

        if metrics["total"] >= 3 and metrics["ratio"] < 0.34:
            out.insert(
                0,
                {
                    "section": label,
                    "current": f"{len(metrics['unquantified'])} of {metrics['total']} lines carry no number",
                    "suggested": "Add a figure to at least half of these lines.",
                    "why": (
                        "Unquantified bullets read as a job description rather than "
                        "a record of what you achieved. Scale, latency, volume, "
                        "accuracy and time saved are all fair game."
                    ),
                    "impact": HIGH,
                    "placeholders": [],
                    "needs_your_input": True,
                },
            )
        return out

    def _skills_improvements(
        self, label: str, body: str, jd_keywords: Sequence[Tuple[str, int]], skills: Set[str]
    ) -> List[Dict[str, Any]]:
        current = " ".join(body.split())
        if not current:
            return []

        lead = [s for s, mentions in jd_keywords if s in skills][:6]
        if not lead:
            return []

        first_listed = _clean(find_skills(current))[:3]
        if first_listed and set(first_listed) == set(lead[: len(first_listed)]):
            return []

        return [
            {
                "section": label,
                "current": current,
                "suggested": self._join([_display(s) for s in lead])
                + (" | " + current if current else ""),
                "why": (
                    "Skills are skim-read left to right. Leading with "
                    + self._join([_display(s) for s in lead[:3]])
                    + " puts the advert's own priorities in the first line."
                ),
                "impact": MEDIUM,
                "placeholders": [],
                "needs_your_input": False,
            }
        ]

    def _emphasis_improvements(
        self,
        text: str,
        jd_keywords: Sequence[Tuple[str, int]],
        skills: Set[str],
    ) -> List[Dict[str, Any]]:
        """Flag skills the advert stresses that the resume barely mentions.

        This is the "RAG ten times in the advert, once on the resume" case:
        the candidate has the skill, and is under-selling exactly the thing the
        employer cares most about.
        """
        if not text:
            return []

        haystack = text.lower()
        out: List[Dict[str, Any]] = []

        for skill, mentions in jd_keywords:
            if mentions < HEAVILY_STRESSED or skill not in skills:
                continue
            appearances = haystack.count(skill)
            if appearances >= 2:
                continue
            out.append(
                {
                    "section": "Whole resume",
                    "current": (
                        f"{_display(skill)} appears "
                        f"{'once' if appearances == 1 else 'not at all'} in your resume"
                    ),
                    "suggested": (
                        f"Work {_display(skill)} into your summary, your skills line "
                        f"and at least one achievement bullet."
                    ),
                    "why": (
                        f"The advert names {_display(skill)} {mentions} times - it is "
                        "what the role is about, and you have the experience but are "
                        "under-selling it."
                    ),
                    "impact": HIGH,
                    "placeholders": [],
                    "needs_your_input": False,
                }
            )
        return out

    # -- Keyword advice ------------------------------------------------------ #
    def _keywords_to_add(
        self,
        jd_keywords: Sequence[Tuple[str, int]],
        resume_skills: Set[str],
        text: str,
        blocked: Set[str],
    ) -> List[str]:
        """Advert vocabulary the candidate has earned but is not using.

        Deliberately excludes anything in `blocked`: suggesting a keyword for a
        skill the candidate lacks is telling them to lie.
        """
        haystack = text.lower()
        out: List[str] = []
        for skill, _mentions in jd_keywords:
            if skill in blocked or skill not in resume_skills:
                continue
            if haystack and haystack.count(skill) >= 2:
                continue
            out.append(_display(skill))
        return out

    def _keywords_to_remove(
        self,
        resume_skills: Set[str],
        jd_keywords: Sequence[Tuple[str, int]],
        job_analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Skills worth demoting for this application.

        Never framed as deletion. The experience is real and will matter for a
        different advert; it is only competing for space in this one.
        """
        wanted = {s for s, _ in jd_keywords}
        wanted |= set(_clean(job_analysis.get("tech_stack")))

        out: List[Dict[str, Any]] = []
        for skill in sorted(resume_skills):
            if skill in wanted:
                continue
            # Anything the advert would recognise as adjacent stays put. Both
            # tests matter: name similarity catches "Postgres"/"PostgreSQL",
            # and family membership catches PostgreSQL against a SQL
            # requirement. Telling someone to bury PostgreSQL for a role that
            # asks for SQL is worse than saying nothing.
            if match_skill(skill, wanted) is not None:
                continue
            if self._is_related(skill, wanted):
                continue
            out.append(
                {
                    "keyword": _display(skill),
                    "action": "move to a secondary line",
                    "why": (
                        f"{_display(skill)} is not mentioned in this advert. Keep it "
                        "on your master resume - it is only competing for space here."
                    ),
                }
            )
        return out[:8]

    # -- Ordering ------------------------------------------------------------ #
    def _reordering(
        self,
        sections: Sequence[Tuple[Any, str]],
        jd_keywords: Sequence[Tuple[str, int]],
    ) -> Dict[str, List[str]]:
        """Which blocks to lift and which to sink."""
        move_up: List[str] = []
        move_down: List[str] = []
        keywords = {s for s, _ in jd_keywords}

        # Section.OTHER holds the pre-heading block - name, contact details,
        # often the summary. It belongs at the top by definition, so including
        # it would report every other section as needing to move up.
        present = [
            s
            for s in (self._as_section(section) for section, _ in sections)
            if s is not Section.OTHER
        ]
        ideal = [s for s in _IDEAL_ORDER if s in present]
        for index, section in enumerate(ideal):
            if present.index(section) > index:
                move_up.append(_SECTION_LABELS.get(section, str(section)))

        for section, body in sections:
            resolved = self._as_section(section)
            # Only the narrative sections have an order worth arguing about.
            # Reordering a skills line is handled by the skills suggestion, and
            # the pre-heading block is already at the top by definition.
            if resolved not in (Section.EXPERIENCE, Section.PROJECTS, Section.ACHIEVEMENTS):
                continue
            label = _SECTION_LABELS.get(resolved, str(section).title())
            for line in split_bullets(body):
                lowered = line.lower()
                hits = set(_clean(find_skills(line))) & keywords
                if len(hits) >= 2:
                    move_up.append(f"{label} > {self._shorten(line)}")
                elif any(marker in lowered for marker in _DOWNPLAY_MARKERS):
                    move_down.append(f"{label} > {self._shorten(line)}")

        return {
            "move_up": self._dedupe(move_up)[:6],
            "move_down": self._dedupe(move_down)[:6],
        }

    # -- Supporting internals ------------------------------------------------ #
    def _sections(self, text: str) -> List[Tuple[Any, str]]:
        if not text:
            return []
        try:
            return split_into_sections(text)
        except Exception:  # noqa: BLE001 - parsing must not sink the advice
            logger.debug("Section split failed", exc_info=True)
            return [(Section.OTHER, text)]

    @staticmethod
    def _as_section(value: Any) -> Any:
        if isinstance(value, Section):
            return value
        try:
            return Section(str(value).lower())
        except ValueError:
            return Section.OTHER

    def _resume_skills(
        self,
        resume_data: Dict[str, Any],
        text: str,
        match_data: Optional[Dict[str, Any]],
    ) -> Set[str]:
        """Everything the resume can actually back up.

        The match report's `found` lists are included because they survived
        alias-aware matching, so a resume saying "Postgres" still counts as
        evidence for PostgreSQL.
        """
        skills = set(_clean(resume_data.get("skills")))
        if text:
            skills.update(_clean(find_skills(text)))

        breakdown = (match_data or {}).get("match_breakdown") or {}
        for name in ("skills", "tech_stack"):
            found = (breakdown.get(name) or {}).get("found")
            if isinstance(found, (list, tuple, set)):
                skills.update(_clean(list(found)))
        return skills

    def _blocked_skills(
        self, gaps: Optional[Dict[str, Any]], match_data: Optional[Dict[str, Any]]
    ) -> Set[str]:
        """Skills the candidate must not claim, from whichever source says so."""
        blocked: Set[str] = set()

        for bucket in ("critical_gaps", "nice_to_have_gaps"):
            for gap in (gaps or {}).get(bucket) or []:
                name = gap.get("skill_id") or gap.get("skill")
                if name:
                    blocked.update(_clean([name]))

        breakdown = (match_data or {}).get("match_breakdown") or {}
        for name in ("skills", "tech_stack"):
            missing = (breakdown.get(name) or {}).get("missing")
            if isinstance(missing, (list, tuple, set)):
                blocked.update(_clean(list(missing)))
        return blocked

    def _upgrade_verb(self, text: str) -> Optional[Dict[str, str]]:
        """Swap a leading weak verb for one that claims ownership."""
        lowered = text.lower()
        # Longest first, so "helped with" beats "helped".
        for weak in sorted(WEAK_VERBS, key=len, reverse=True):
            if lowered.startswith(weak):
                strong = WEAK_VERBS[weak]
                return {"from": weak, "to": strong, "text": strong + text[len(weak):]}
        first = lowered.split(" ", 1)[0].strip(".,:")
        if first in _STRONG_VERBS:
            return None
        return None

    def _weave_keywords(
        self, text: str, jd_keywords: Sequence[str], allowed: Set[str]
    ) -> Optional[Dict[str, Any]]:
        """Name the advert's tools explicitly where the line already implies them.

        Only skills the resume evidences are eligible, and only when the line is
        already about that area - this rewrites emphasis, it does not invent
        experience.
        """
        lowered = text.lower()
        line_skills = set(_clean(find_skills(text)))
        if not line_skills:
            return None

        additions = [
            skill
            for skill in jd_keywords
            if skill in allowed
            and skill not in lowered
            and match_skill(skill, line_skills) is not None
        ][:2]
        if not additions:
            return None

        joined = self._join([_display(s) for s in additions])
        return {"text": f"{text.rstrip('.')} ({joined})", "skills": additions}

    def _add_metric_slot(self, text: str) -> str:
        """Append a slot for a number the candidate must supply themselves."""
        body = text.rstrip(".")
        lowered = body.lower()

        if any(word in lowered for word in ("latency", "speed", "performance", "optimis", "optimiz")):
            return f"{body}, cutting [TIMEFRAME] to [TIMEFRAME]"
        if any(word in lowered for word in ("accuracy", "precision", "recall", "quality")):
            return f"{body}, reaching [PERCENTAGE] accuracy"
        if any(word in lowered for word in ("user", "customer", "request", "traffic", "document", "record")):
            return f"{body}, serving [NUMBER] per [TIMEFRAME]"
        if any(word in lowered for word in ("team", "mentor", "led", "lead")):
            return f"{body}, across a team of [NUMBER]"
        return f"{body}, delivering [RESULT]"

    @staticmethod
    def _has_metric(text: str) -> bool:
        return bool(_METRIC_RE.search(text))

    @staticmethod
    def _wants_metric(text: str) -> bool:
        """Would a number actually improve this line?

        Certifications, course titles and bare headings are not achievements,
        and appending "delivering [RESULT]" to "AI & ML Fundamentals" produces
        something the candidate would have to delete before sending.
        """
        words = text.split()
        if len(words) < 5:
            return False
        lowered = text.lower()
        if any(
            marker in lowered
            for marker in (
                "certification", "certificate", "certified", "fundamentals",
                "coursework", "degree", "bachelor", "master", "diploma",
                "award", "gpa",
            )
        ):
            return False
        return True

    @staticmethod
    def _is_related(skill: str, wanted: Iterable[str]) -> bool:
        """Does `skill` share a family with anything the advert asked for?

        Reuses the gap detector's family table so the two agents cannot drift
        into disagreeing about what counts as adjacent. Imported lazily to keep
        the dependency pointing one way.
        """
        try:
            from agents.gap_detector import SKILL_FAMILIES
        except Exception:  # noqa: BLE001 - relatedness is an refinement
            return False

        families = {
            name for name, members in SKILL_FAMILIES.items() if skill in members
        }
        if not families:
            return False
        for other in wanted:
            if families & {
                name for name, members in SKILL_FAMILIES.items() if other in members
            }:
                return True
        return False

    def _parse_projects(self, sections: Sequence[Tuple[Any, str]]) -> List[Dict[str, Any]]:
        """Break the projects block into individual projects.

        A project starts at a numbered or titled line; everything until the next
        such line belongs to it.
        """
        projects: List[Dict[str, Any]] = []
        for section, body in sections:
            if self._as_section(section) is not Section.PROJECTS:
                continue

            current: Optional[Dict[str, Any]] = None
            for raw in body.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if self._looks_like_project_title(line):
                    if current:
                        projects.append(current)
                    current = {
                        "name": self._clean_title(line),
                        "text": line,
                        "position": len(projects) + 1,
                    }
                elif current:
                    current["text"] += " " + line
            if current:
                projects.append(current)
        return projects

    @staticmethod
    def _looks_like_project_title(line: str) -> bool:
        """Is this a project heading, or a detail line belonging to one?

        Numbered lines are headings. Dash and bullet lines are *details* - the
        distinction matters, because treating "- Built with LangChain + RAG"
        as a project name produces advice about a project that does not exist.
        """
        if re.match(r"^\s*\d+[.)]\s*\S", line):
            return True
        if re.match(r"^\s*[-*\u2022\u2013]", line):
            return False
        return len(line) <= 70 and line[:1].isupper() and not line.endswith(".")

    @staticmethod
    def _clean_title(line: str) -> str:
        title = re.sub(r"^\s*(?:\d+[.)]|[-*\u2022])\s*", "", line).strip()
        # "Document Q&A System - Built with LangChain" -> the name only.
        for separator in (" - ", " \u2013 ", ": ", " | "):
            if separator in title:
                title = title.split(separator, 1)[0]
                break
        return title.strip() or line.strip()

    def _project_why(
        self, required: Sequence[str], stack: Sequence[str], preferred: Sequence[str]
    ) -> str:
        bits: List[str] = []
        if required:
            bits.append(
                "demonstrates " + self._join([_display(s) for s in required]) + ", "
                "which the advert requires"
            )
        if stack:
            bits.append("uses their core stack (" + self._join([_display(s) for s in stack]) + ")")
        if preferred:
            bits.append("covers preferred " + self._join([_display(s) for s in preferred]))
        return self._capitalise(self._join(bits))

    @staticmethod
    def _project_suggestion(score: int, position: int) -> str:
        if score >= 70:
            return (
                "Move to the top of your projects section"
                if position > 1
                else "Keep first - it is your strongest argument for this role"
            )
        if score >= 40:
            return "Keep, but tighten it to two lines so the stronger project leads"
        return "Drop for this application unless space allows"

    def _resume_title(
        self,
        job_analysis: Dict[str, Any],
        resume_skills: Set[str],
        jd_keywords: Sequence[Tuple[str, int]],
    ) -> str:
        """A headline matching the advert's title, backed by real skills."""
        role = self._role_noun(job_analysis)
        stack = set(_clean(job_analysis.get("tech_stack")))
        candidates = [
            s
            for s, _ in jd_keywords
            if s in resume_skills and s not in _COMMODITY_SKILLS
        ]
        # Raw mention count alone promotes whatever the advert happens to
        # repeat, which is how "Docker" ends up headlining an AI/ML resume.
        # The employer's own core stack is the better tie-breaker.
        headline = sorted(
            candidates, key=lambda s: (s not in stack, candidates.index(s))
        )[:2]
        if not headline:
            return role
        return f"{role} with {self._join([_display(s) for s in headline], final=' & ')} Expertise"

    @staticmethod
    def _role_noun(job_analysis: Dict[str, Any]) -> str:
        title = str(job_analysis.get("title") or "").strip()
        if title:
            # "AI/ML Engineer - Bangalore" -> "AI/ML Engineer"
            for separator in (" - ", " \u2013 ", " | ", ","):
                if separator in title:
                    title = title.split(separator, 1)[0]
                    break
            return title.strip()
        role_type = str(job_analysis.get("role_type") or "").strip()
        if role_type and role_type != "unknown":
            return f"{role_type.upper()} Engineer" if len(role_type) <= 5 else f"{role_type.title()} Engineer"
        return "Engineer"

    @staticmethod
    def _years(resume: Dict[str, Any], text: str) -> str:
        value = resume.get("experience_years")
        if not value:
            match = re.search(r"(\d+(?:\.\d+)?)\+?\s*years?", text, re.IGNORECASE)
            value = match.group(1) if match else None
        if not value:
            return ""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        rendered = str(int(number)) if number.is_integer() else str(number)
        return f"{rendered}+ years"

    def _confidence(
        self,
        text: str,
        sections: Sequence[Tuple[Any, str]],
        job_analysis: Dict[str, Any],
        match_data: Optional[Dict[str, Any]],
    ) -> float:
        """How much the advice should be trusted, given the evidence available.

        Advice from a parsed, sectioned resume plus a scored match is worth more
        than advice from a bare skills list, and the caller deserves to know
        which they are looking at.
        """
        score = 0.3
        if text:
            score += 0.2
        else:
            # Nothing was read, so every downstream signal is about the advert
            # rather than the candidate. Saying anything confident here would
            # be confidence about a document we never saw.
            return 0.2
        if len(sections) >= 3:
            score += 0.2
        if job_analysis.get("required_skills"):
            score += 0.15
        if match_data:
            score += 0.1
        if str(job_analysis.get("job_description") or ""):
            score += 0.05
        return round(min(0.95, score), 2)

    def _rank(self, improvements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Highest impact first, stable within a band."""
        return sorted(
            improvements,
            key=lambda item: (
                _IMPACT_RANK.get(item.get("impact"), 9),
                item.get("section", ""),
                item.get("position", 0),
            ),
        )

    # -- Small text helpers -------------------------------------------------- #
    @staticmethod
    def _join(values: Sequence[str], final: str = " and ") -> str:
        items = [v for v in values if v]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + final + items[-1]

    @staticmethod
    def _capitalise(text: str) -> str:
        clean = text.strip()
        return clean[:1].upper() + clean[1:] if clean else clean

    @staticmethod
    def _shorten(text: str, limit: int = 46) -> str:
        flat = " ".join(text.split())
        return flat if len(flat) <= limit else flat[: limit - 1].rstrip(" ,;:-") + "\u2026"

    @staticmethod
    def _dedupe(values: Sequence[str]) -> List[str]:
        seen: List[str] = []
        for value in values:
            if value not in seen:
                seen.append(value)
        return seen


#: Module-level singleton, matching the other agents.
resume_optimizer = ResumeOptimizerAgent()
