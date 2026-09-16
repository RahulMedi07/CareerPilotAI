"""Interview preparation: likely questions, honest answers, and a study plan.

The agent reads the advert, the resume, the gaps and the score, then works out
what the candidate is actually going to be asked and how they should prepare.

Two rules shape everything here, and both cost the output some polish.

**An answer is a scaffold, not a script.** It would be easy to emit fluent
first-person prose - "I built a RAG pipeline processing 10,000 documents at 95%
accuracy" - and a candidate would happily memorise it. But an interview answer
is not a resume line. It is spoken aloud, to someone whose job is to probe it,
and the very next question is "how did you measure that?" A memorised
fabrication fails there, in the room, irrecoverably. So answers are built
strictly from lines that appear in the resume, and everything the resume does
not know becomes a labelled blank: `[RESULT]`, `[WHY THIS CHOICE]`,
`[WHAT YOU'D CHANGE]`. The candidate fills them in and rehearses their own
material.

**A gap answer must never coach a lie.** The obvious advice for a missing skill
is "say you have studied the basics" - which, if they have not, is a lie told
under questioning to someone who can immediately ask what they covered. Gap
advice here is conditional and explicit about it: claim study only if study
happened. What the candidate *can* always do honestly is name the nearest thing
they have really built, which is what `similar_skills_user_has` is for.

Everything is deterministic. No LLM, no network.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from rag.resume_indexer import Section, split_bullets, split_into_sections
from utils.logger import get_logger, observed
from utils.skills import find_skills, match_skill, normalise_skill
from utils.validation import as_dict

logger = get_logger(__name__)

__all__ = [
    "InterviewPrepAgent",
    "interview_prep_agent",
    "ANSWER_PLACEHOLDERS",
    "QUESTION_BANK",
    "BEHAVIOURAL_BANK",
    "HR_BANK",
    "EASY",
    "MEDIUM",
    "HARD",
    "HIGH",
    "LOW",
]

# -- Vocabulary -------------------------------------------------------------

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

EASY = "EASY"
HARD = "HARD"

_CONFIDENCE_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: Categories used in the `category` field of a question.
TECHNICAL = "Technical"
GAP_BASED = "Gap-Based"
EXPERIENCE = "Experience"
SYSTEM_DESIGN = "System Design"
PROJECT_BASED = "Project-Based"

#: Caps on the resume-derived sets. Both exist to keep the page readable: a
#: candidate who is given thirty questions prepares for none of them.
MAX_PROJECT_QUESTIONS = 6
MAX_IMPROVEMENT_AREAS = 5

#: Longest quoted resume line in a project question, before an ellipsis. Long
#: enough to be recognisable as their own writing, short enough to read as a
#: question rather than as a paragraph.
MAX_QUOTE_CHARS = 160

#: A resume line this long, dashed this often, is a PDF that lost its line
#: breaks rather than one long sentence. See ``_achievement_lines``.
_RUNON_CHARS = 180
_RUNON_RE = re.compile(r"\s+[-\u2013\u2014\u2022]\s+")

#: Openers that mark a line as a thing the candidate *did*.
#:
#: A resume bullet is written verb-first by convention, and that convention is
#: the cheapest available signal that a line is an achievement rather than a
#: heading, a job title, a profile summary or a comma-separated skills list.
#: Without it the page quoted "RAHUL SHARMA PROFESSIONAL SUMMARY: AI/ML
#: Developer with 2+ years experience..." back at its own author and asked
#: what the hard part was.
#:
#: Deliberately a whitelist. Guessing that anything past-tense-looking is an
#: achievement over-reaches; missing a bullet only costs one question, and
#: there are more candidates than the six that get used.
_ACHIEVEMENT_VERBS = frozenset(
    """
    architected authored automated built collaborated conducted configured
    contributed converted created cut debugged decreased delivered deployed
    designed developed drove engineered established evaluated executed
    experimented fine-tuned fixed handled implemented improved increased
    integrated introduced launched led maintained managed migrated mentored
    modelled modeled optimised optimized orchestrated owned performed
    presented prototyped rebuilt reduced refactored researched resolved
    scaled shipped spearheaded streamlined supported tested trained
    troubleshot wrote
    """.split()
)

#: Blanks the candidate must fill from their own memory. The agent will not
#: guess a number, a motive or an outcome on their behalf.
ANSWER_PLACEHOLDERS = (
    "[PROBLEM IT SOLVED]",
    "[WHY THIS CHOICE]",
    "[RESULT]",
    "[NUMBER]",
    "[WHAT YOU'D CHANGE]",
    "[HOW FAR YOU GOT]",
)

_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z '\u2019/]*\]")

#: Roughly how long one topic takes to prepare properly, in hours.
HOURS_PER_TECHNICAL_TOPIC = 0.75
HOURS_PER_GAP = 1.5
HOURS_BEHAVIOURAL = 1.5
HOURS_COMPANY_RESEARCH = 1.0
HOURS_MOCK_PRACTICE = 2.0

#: A day of preparation that someone with a job can actually sustain.
REALISTIC_HOURS_PER_DAY = 2.5
MAX_PREP_DAYS = 7

#: Ceiling on questions returned, so the output stays studiable.
#:
#: Raised from 8/4 in week two. These are ceilings, not targets: a question is
#: only emitted where the resume or the advert supports one, so a thin resume
#: against a short advert still returns a short list rather than padding to
#: the limit with questions nobody asked.
MAX_TECHNICAL_QUESTIONS = 10
MAX_GAP_QUESTIONS = 5


# -- Question banks ---------------------------------------------------------
#
# Keyed by canonical skill id. Each entry supplies the question an interviewer
# would actually open with, plus the follow-ups that reliably come next. The
# follow-ups matter more than the question: candidates prepare the headline
# answer and get caught two questions deeper.

QUESTION_BANK: Dict[str, Dict[str, Any]] = {
    "rag": {
        "question": (
            "Walk us through your RAG implementation. How did you handle "
            "chunking and embeddings?"
        ),
        "follow_ups": [
            "How did you choose your chunk size, and what did you try first?",
            "What did you do when retrieval returned nothing relevant?",
            "How did you measure whether retrieval was actually any good?",
            "Where did latency go, and what did you do about it?",
        ],
        "category": TECHNICAL,
    },
    "langchain": {
        "question": "Why LangChain rather than calling the model API directly?",
        "follow_ups": [
            "What did LangChain make harder rather than easier?",
            "How did you handle prompt versioning?",
            "Which abstractions did you end up bypassing?",
        ],
        "category": TECHNICAL,
    },
    "langgraph": {
        "question": "How would you model a multi-step agent workflow as a graph?",
        "follow_ups": [
            "How do you handle a node that fails halfway through?",
            "How does state pass between nodes without being overwritten?",
            "When is a graph the wrong abstraction?",
        ],
        "category": TECHNICAL,
    },
    "embeddings": {
        "question": "Which embedding model did you use, and why that one?",
        "follow_ups": [
            "What are the trade-offs between model size and retrieval quality?",
            "How did you handle documents longer than the context window?",
            "Cosine or dot product, and does the choice matter here?",
        ],
        "category": TECHNICAL,
    },
    "python": {
        "question": "Talk us through a piece of Python you are proud of.",
        "follow_ups": [
            "How did you test it?",
            "What would you refactor now?",
            "How did you handle errors and edge cases?",
        ],
        "category": TECHNICAL,
    },
    "fastapi": {
        "question": "How did you structure your FastAPI service?",
        "follow_ups": [
            "How did you keep slow CPU work off the event loop?",
            "How did you validate and reject bad input?",
            "How would you version the API?",
        ],
        "category": TECHNICAL,
    },
    "docker": {
        "question": "How do you containerise a Python service for production?",
        "follow_ups": [
            "How do you keep the image small?",
            "How do you handle secrets at runtime?",
        ],
        "category": TECHNICAL,
    },
    "sql": {
        "question": "How do you approach a query that has become slow?",
        "follow_ups": [
            "How do you read a query plan?",
            "When would you denormalise?",
        ],
        "category": TECHNICAL,
    },
    "postgresql": {
        "question": "What PostgreSQL features have you leaned on beyond basic CRUD?",
        "follow_ups": [
            "How do you handle migrations safely?",
            "When would you reach for a JSONB column?",
        ],
        "category": TECHNICAL,
    },
    "react": {
        "question": "How do you decide where state should live in a React app?",
        "follow_ups": [
            "How do you avoid unnecessary re-renders?",
            "How do you handle data fetching and loading states?",
        ],
        "category": TECHNICAL,
    },
    "pinecone": {
        "question": "How would you choose between a hosted vector store and a local one?",
        "follow_ups": [
            "How does metadata filtering change your index design?",
            "What happens as the index grows past memory?",
        ],
        "category": TECHNICAL,
    },
    "chroma": {
        "question": "How did you use Chroma, and where did it stop being enough?",
        "follow_ups": [
            "How did you persist and reload the collection?",
            "How did you handle re-indexing when a document changed?",
        ],
        "category": TECHNICAL,
    },
    "aws": {
        "question": "Which AWS services have you actually deployed to, and how?",
        "follow_ups": [
            "How did you manage configuration across environments?",
            "How did you keep costs visible?",
        ],
        "category": TECHNICAL,
    },
    "ci/cd": {
        "question": "What does a good deployment pipeline look like to you?",
        "follow_ups": [
            "What runs before a merge, and what runs after?",
            "How do you roll back?",
        ],
        "category": TECHNICAL,
    },
    "machine learning": {
        "question": "How do you know a model is good enough to ship?",
        "follow_ups": [
            "Which metric, and why that one for this problem?",
            "How would you detect the model degrading in production?",
        ],
        "category": TECHNICAL,
    },
    "llm": {
        "question": "How do you evaluate the output of a language model?",
        "follow_ups": [
            "How do you deal with hallucination in a user-facing product?",
            "How do you keep prompt changes from silently regressing quality?",
        ],
        "category": TECHNICAL,
    },
}

#: Asked of almost everyone. The `context` explains why the panel bothers,
#: which is what tells a candidate what the answer is meant to demonstrate.
BEHAVIOURAL_BANK: Tuple[Dict[str, str], ...] = (
    {
        "question": "Tell us about a time something you built failed. What did you do?",
        "context": (
            "Tests whether you diagnose problems or assign blame. Every panel "
            "asks a version of this."
        ),
        "suggested_approach": (
            "Pick a real failure from your own work, say what broke and how you "
            "found out, then spend most of the answer on the fix and what you "
            "changed afterwards. Do not pick a failure that was someone else's."
        ),
    },
    {
        "question": "Describe a technical decision you had to defend.",
        "context": "Tests whether you can justify a choice rather than repeat a preference.",
        "suggested_approach": (
            "Name the alternatives you rejected and why. An answer with no "
            "rejected alternative sounds like you never considered any."
        ),
    },
    {
        "question": "Tell us about a time you had to learn something quickly.",
        "context": (
            "Especially likely when the advert lists skills you do not yet have "
            "- they are testing whether the gap is closeable."
        ),
        "suggested_approach": (
            "Use a real example with a real timescale. This is your chance to "
            "make the panel comfortable about your gaps without being asked."
        ),
    },
    {
        "question": "Tell us about a disagreement with a colleague.",
        "context": "Tests whether you can disagree without it becoming personal.",
        "suggested_approach": (
            "Show that you changed your mind, or that you were persuasive "
            "without needing to win. Avoid a story where you were simply right."
        ),
    },
    {
        "question": "What are you most proud of building?",
        "context": "An open goal. The panel is checking whether you can explain your own work.",
        "suggested_approach": (
            "Pick the project closest to this advert, not the one that was "
            "hardest. Lead with what it did for someone, not how it worked."
        ),
    },
)

#: Role-flavoured additions to the behavioural set.
_ROLE_BEHAVIOURAL: Dict[str, Dict[str, str]] = {
    "ai/ml": {
        "question": "How do you explain a model's behaviour to someone non-technical?",
        "context": "AI teams sit next to product and legal; this comes up constantly.",
        "suggested_approach": (
            "Avoid jargon entirely for one full sentence, then add detail only "
            "if invited."
        ),
    },
    "backend": {
        "question": "Tell us about an outage or production incident you handled.",
        "context": "Backend panels want to know how you behave when it is broken and live.",
        "suggested_approach": (
            "Walk the timeline: detection, mitigation, root cause, prevention. "
            "Mitigation before root cause - that ordering is the point."
        ),
    },
    "frontend": {
        "question": "How do you handle a design that is difficult to implement?",
        "context": "Tests collaboration with design rather than pure coding skill.",
        "suggested_approach": "Show you proposed an alternative rather than simply refusing.",
    },
    "data": {
        "question": "Tell us about a time the data was wrong.",
        "context": "Data roles are judged on scepticism as much as on tooling.",
        "suggested_approach": "Explain how you noticed, which is the hard part.",
    },
}

#: What HR asks, which is not what the engineers ask. These are kept apart
#: from the behavioural set on purpose: the behavioural questions probe how
#: you work, while these decide whether you are hireable on terms both sides
#: can live with. Candidates lose offers at this stage having sailed through
#: the technical rounds, usually by answering the money question badly.
HR_BANK: Tuple[Dict[str, str], ...] = (
    {
        "question": "Tell me about yourself.",
        "context": (
            "Almost always the opening question, and the one most often "
            "wasted. They are asking for a ninety-second trailer, not a "
            "chronological history."
        ),
        "suggested_approach": (
            "Three beats: what you do now, one thing you have built that is "
            "relevant to this advert, and why this role is the next step. "
            "Practise it out loud until it fits in ninety seconds."
        ),
    },
    {
        "question": "Why are you leaving your current role?",
        "context": "Tests whether you criticise former employers.",
        "suggested_approach": (
            "Answer forwards, not backwards - what this role offers that "
            "yours does not. Never criticise a manager or a colleague, even "
            "when the criticism is fair. The panel cannot verify it and will "
            "assume you would talk about them the same way."
        ),
    },
    {
        "question": "What are your salary expectations?",
        "context": (
            "Asked early to filter, not to negotiate. Most Indian adverts do "
            "not publish a band, so you are being asked to name one first."
        ),
        "suggested_approach": (
            "Give a researched range rather than a single number, and say "
            "what it is based on. If you genuinely do not know the market "
            "rate yet, say you would like to understand the scope first - "
            "that is a real answer, not a dodge. Do not invent a competing "
            "offer you do not have; it is checkable and it ends interviews."
        ),
    },
    {
        "question": "What is your notice period, and when could you start?",
        "context": (
            "A logistics question with a real answer. In India a 60 or 90 day "
            "notice period is common and is not held against you."
        ),
        "suggested_approach": (
            "State the real number. If it can be negotiated or bought out, "
            "say so. Guessing low and then failing to deliver on it is the "
            "one way to turn this into a problem."
        ),
    },
    {
        "question": "Where do you see yourself in a few years?",
        "context": "Tests whether this job is a step in a direction or just a job.",
        "suggested_approach": (
            "Name a direction, not a title. Tie it to something this role "
            "would actually let you do - which means you need to have read "
            "the advert properly."
        ),
    },
    {
        "question": "Do you have any questions for us?",
        "context": (
            "Not a formality. Having no question reads as having no interest, "
            "and it is the last impression you leave."
        ),
        "suggested_approach": (
            "Bring three, because two may get answered during the interview. "
            "See the questions suggested for you further down."
        ),
    },
)

#: Situational questions, keyed by the kind of role. A scenario question asks
#: what you *would* do, so unlike the behavioural set it can be answered
#: without the experience already being on your resume - which is what makes
#: it the place a gap is most survivable.
_SCENARIO_BANK: Dict[str, Tuple[Dict[str, str], ...]] = {
    "backend": (
        {
            "question": (
                "An endpoint that normally answers in 100ms is taking 8 "
                "seconds in production. Nothing was deployed. Walk me through "
                "what you do."
            ),
            "context": "Tests method under pressure, not memorised trivia.",
            "suggested_approach": (
                "Say what you would look at and in what order, and why that "
                "order. Measure before changing anything. Naming what you "
                "would rule out first is worth more than guessing the cause."
            ),
        },
        {
            "question": (
                "You are asked to ship a feature by Friday that you believe "
                "needs two weeks to do safely. What do you do?"
            ),
            "context": "Tests whether you negotiate scope or quietly cut corners.",
            "suggested_approach": (
                "Offer a smaller version that is genuinely finished rather "
                "than a full version that is half-tested, and name the "
                "specific risk you are avoiding."
            ),
        },
    ),
    "frontend": (
        {
            "question": (
                "A page works on your machine and is unusable on a mid-range "
                "Android phone on 4G. How do you approach it?"
            ),
            "context": "Tests whether you have ever profiled rather than guessed.",
            "suggested_approach": (
                "Reach for a measurement first. Bundle size, images and "
                "render-blocking requests are the usual culprits, but say how "
                "you would confirm which one before fixing it."
            ),
        },
    ),
    "ai/ml": (
        {
            "question": (
                "Your model scores well in testing and users say the answers "
                "are wrong. What do you do?"
            ),
            "context": "Tests whether you trust a metric more than a user.",
            "suggested_approach": (
                "Go and look at the failing cases individually. Then question "
                "whether the metric measures what users care about - usually "
                "it does not, and saying so is the answer they want."
            ),
        },
    ),
    "data": (
        {
            "question": (
                "A dashboard the business relies on shows numbers that look "
                "wrong. How do you find out?"
            ),
            "context": "Tests whether you trace a number back to its source.",
            "suggested_approach": (
                "Work backwards one hop at a time from the number to the "
                "query to the table to the ingest, and say how you would "
                "confirm each hop rather than assuming."
            ),
        },
    ),
}

#: Asked of everyone, whatever the stack.
_SCENARIO_GENERAL: Tuple[Dict[str, str], ...] = (
    {
        "question": (
            "You pick up a piece of code you have never seen, with no tests "
            "and no documentation, and you have to change it. How do you "
            "start?"
        ),
        "context": (
            "Most real work looks like this, so the answer says more about "
            "your day-to-day than any algorithm question."
        ),
        "suggested_approach": (
            "Describe getting it running and putting a test around the "
            "current behaviour before changing anything, so you can tell the "
            "difference between a bug and a feature you did not understand."
        ),
    },
    {
        "question": (
            "Halfway through a task you realise the approach you agreed on "
            "will not work. What do you do?"
        ),
        "context": "Tests whether you escalate early or hide it until the deadline.",
        "suggested_approach": (
            "Raise it as soon as you know, with an alternative already "
            "thought through. The failure mode they are checking for is "
            "silence."
        ),
    },
)

#: What to research about a company, in the order it pays off.
_RESEARCH_TOPICS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "Why do you want to join this company?",
        (
            "What the company actually sells, in one sentence",
            "Their most recent product launch or announcement",
            "How the team you would join fits the wider business",
        ),
    ),
    (
        "What do you know about how we work?",
        (
            "Engineering blog posts, if they have one",
            "Their public repositories and the stack they reveal",
            "Team size and how the role was described in the advert",
        ),
    ),
)


# -- Small helpers ----------------------------------------------------------


#: A figure that means something on a resume. Bare years are excluded: "2023"
#: is a date, not a result, and counting it would let a resume with nothing
#: but employment dates pass the "has numbers" check.
_MEANINGFUL_NUMBER = re.compile(
    r"(?<!\w)(?:\d+(?:\.\d+)?\s*(?:%|x|k|m|bn|ms|s|gb|mb|tb|\+)|\d{1,3}(?:,\d{3})+)"
    r"|(?<!\w)\d+(?:\.\d+)?(?=\s+(?:users|requests|customers|hours|days|weeks|"
    r"months|times|queries|records|rows|tests|services|people|engineers))",
    re.IGNORECASE,
)


def _shorten(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """Quote a resume line without letting it run to a paragraph."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    # Cut on a word boundary; a quote ending mid-word looks like a bug.
    return clean[:limit].rsplit(" ", 1)[0] + "..."


def _section_text(sections: Sequence[Tuple[Any, str]]) -> str:
    """The resume back as one block, for helpers that want plain text."""
    return "\n".join(str(body or "") for _section, body in sections)


def _achievement_lines(body: str) -> List[str]:
    """One entry per achievement, even when the line breaks were lost.

    ``split_bullets`` splits on newlines, which is right for a resume that
    still has them. Text pulled out of a PDF often does not: the observed
    output quoted a whole role back at the candidate as a single "line" --

        Junior AI Developer - TechCorp (2023-Present) - Built RAG system with
        LangChain - Implemented embeddings pipeline - Created REST AP...

    which is four separate things plus a job title, truncated mid-word. Asking
    someone to "walk me through that" is only a useful rehearsal when *that*
    is one piece of work.

    Splitting on " - " is only safe as a repair, not as a rule: a single
    bullet may legitimately use a dash as punctuation, and splitting it would
    throw the achievement away. So it only applies to a line long enough and
    dashed often enough to be a run-on rather than a sentence. Hyphenated
    words and date ranges are untouched, having no spaces around the dash.
    """
    out: List[str] = []
    for line in split_bullets(body):
        if len(line) > _RUNON_CHARS and len(_RUNON_RE.findall(line)) >= 2:
            out.extend(part.strip() for part in _RUNON_RE.split(line))
        else:
            out.append(line)
    return [part for part in out if part]


def _numbers_in_sections(sections: Sequence[Tuple[Any, str]]) -> bool:
    """True when the resume quantifies anything in its narrative sections.

    Skills and education are skipped. A graduation year and a version number
    are digits, but neither is evidence that the candidate measured their own
    work, which is the thing being checked.
    """
    for section, body in sections:
        if section in (Section.SKILLS, Section.EDUCATION):
            continue
        if _MEANINGFUL_NUMBER.search(str(body or "")):
            return True
    return False


def _clean(values: Any) -> List[str]:
    """Normalise a possibly-messy list of skills into canonical ids."""
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    out: List[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("skill") or value.get("name") or ""
        text = normalise_skill(str(value))
        if text and text not in out:
            out.append(text)
    return out


def _display(skill: str) -> str:
    """Human-facing spelling of a canonical skill id."""
    from agents.resume_optimizer import _display as _shared_display

    return _shared_display(skill)


def _placeholders_in(text: str) -> List[str]:
    return sorted(set(_PLACEHOLDER_RE.findall(text)))


class InterviewPrepAgent:
    """Turns an advert plus a resume into something a candidate can study."""

    #: Shown in the workflow execution trace.
    label = "Interview Prep Agent"

    def __init__(self) -> None:
        self.max_technical = MAX_TECHNICAL_QUESTIONS
        self.max_gap = MAX_GAP_QUESTIONS

    # -- Entry point ----------------------------------------------------

    @observed("prepare_interview")
    def prepare_interview(
        self,
        job_analysis: Optional[Dict[str, Any]] = None,
        resume_data: Optional[Dict[str, Any]] = None,
        gaps: Optional[Dict[str, Any]] = None,
        match_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the full preparation pack.

        Every argument is optional because the callers upstream degrade rather
        than fail: a run with no gap analysis should still produce technical
        questions, just without the gap-specific coaching.
        """
        job_analysis = as_dict(job_analysis, "job_analysis")
        resume_data = as_dict(resume_data, "resume_data")
        gaps = as_dict(gaps, "gaps") or None
        match_data = as_dict(match_data, "match_data") or None

        text = str(resume_data.get("resume_text") or "").strip()
        sections = self._sections(text)

        questions = self._generate_technical_questions(job_analysis, resume_data)
        gap_questions = self._generate_gap_questions(gaps)

        # Gap questions are the ones candidates lose offers on, so they are not
        # buried at the bottom of a long technical list.
        combined = self._number(questions + gap_questions)

        role_type = str(job_analysis.get("role_type") or "").lower()
        behavioural = self._generate_behavioral_questions(role_type)
        hr = self._generate_hr_questions()
        scenarios = self._generate_scenario_questions(role_type)
        projects = self._generate_project_questions(sections, job_analysis)
        improve = self._areas_to_improve(job_analysis, gaps, sections)
        company = self._company_questions(job_analysis, match_data)
        theirs = self._questions_for_them(job_analysis, gaps)

        difficulty = self._difficulty(job_analysis, gaps, match_data)
        hours = self._prep_hours(combined, gap_questions, difficulty)
        plan = self._create_prep_schedule(hours, len(gap_questions), gaps)
        # The headline figure has to be the plan's own total. Advertising 17
        # hours next to a five-day plan that adds up to twelve is the kind of
        # small dishonesty that makes someone distrust the rest of the output.
        if plan:
            hours = round(sum(day["time_hours"] for day in plan), 1)
        success = self._predict_success_rate(match_data, gaps, difficulty)

        report: Dict[str, Any] = {
            "interview_difficulty": difficulty,
            "estimated_prep_time_hours": hours,
            "questions": combined,
            # The same questions, split by what they test. `questions` stays
            # the canonical numbered list -- these are views onto it, not
            # copies with separate numbering, so a candidate discussing
            # "question 7" means the same thing in both.
            "strength_questions": [
                q for q in combined if q.get("category") == TECHNICAL
            ],
            "weakness_questions": [
                q for q in combined if q.get("category") == GAP_BASED
            ],
            "behavioral_questions": behavioural,
            # Kept apart from the behavioural set rather than merged into it.
            # They are asked by different people, in a different round, and
            # merging them would bury the money and notice-period questions
            # that candidates most often answer badly.
            "hr_questions": hr,
            "scenario_questions": scenarios,
            # Quoted from the candidate's own resume, so this is empty when the
            # resume has no project or experience bullets to quote.
            "project_questions": projects,
            "areas_to_improve": improve,
            "company_questions": company,
            "your_questions_for_them": theirs,
            "preparation_plan": plan,
            "success_rate_prediction": success,
            "success_rate_reasoning": self._explain_success_rate(
                success, match_data, gaps, difficulty
            ),
            "confidence": self._confidence(text, sections, job_analysis, match_data),
            # Extras the trace and the UI use.
            "question_count": len(combined),
            "gap_question_count": len(gap_questions),
            "prep_days": len(plan),
            "honesty_note": (
                "Answers are scaffolds built from your own resume. Fill in every "
                "bracketed blank from memory, and never claim study or experience "
                "you do not have - the follow-up question will find it."
            ),
            "source": "deterministic",
        }

        logger.info(
            "Interview prep: %d question(s), %d gap question(s), %.1fh over %d day(s)",
            len(combined),
            len(gap_questions),
            hours,
            len(plan),
        )
        return report

    # -- Question generation --------------------------------------------

    def _generate_technical_questions(
        self,
        job_analysis: Dict[str, Any],
        resume: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Questions about the skills the advert wants and the resume claims.

        Ordered by how heavily the advert leans on the skill, because that is
        the order the panel will work through them in.
        """
        required = _clean(job_analysis.get("required_skills"))
        preferred = _clean(job_analysis.get("preferred_skills"))
        stack = set(_clean(job_analysis.get("tech_stack")))

        text = str(resume.get("resume_text") or "")
        sections = self._sections(text)
        evidence = self._evidence_index(sections)
        resume_skills = self._resume_skills(resume, text)

        advert = str(job_analysis.get("job_description") or "").lower()

        # A skill the candidate cannot speak to at all is a gap, and gap
        # questions are generated separately with different coaching.
        # Commodity tools are dropped too: nobody is interviewed on Git, and
        # spending a question on it displaces one that matters.
        from agents.resume_optimizer import _COMMODITY_SKILLS

        askable = [
            s
            for s in required + preferred
            if s in resume_skills and s not in _COMMODITY_SKILLS
        ]

        def weight(skill: str) -> Tuple[int, int]:
            mentions = advert.count(skill) if advert else 0
            return (-(mentions + (3 if skill in stack else 0)), required.index(skill) if skill in required else 99)

        out: List[Dict[str, Any]] = []
        for skill in sorted(dict.fromkeys(askable), key=weight):
            entry = self._question_for_skill(skill)
            if entry is None:
                continue
            lines = evidence.get(skill, [])
            strength, level = self._strength(skill, lines)
            question = {
                "category": entry.get("category", TECHNICAL),
                "skill": _display(skill),
                "question": entry["question"],
                "why_asked": self._why_asked(skill, job_analysis, advert),
                "your_strength": strength,
                "suggested_answer": self._create_suggested_answer(
                    {"skill": skill, "category": entry.get("category", TECHNICAL)},
                    resume,
                    lines,
                ),
                "follow_ups": self._generate_follow_ups(entry),
                "confidence_level": level,
            }
            question["answer_placeholders"] = _placeholders_in(question["suggested_answer"])
            question["needs_your_input"] = bool(question["answer_placeholders"])
            out.append(question)
            if len(out) >= self.max_technical:
                break
        return out

    def _generate_gap_questions(
        self, gaps: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Questions about skills the candidate does not have.

        These need different handling from technical questions: there is no
        experience to draw on, so the answer is a structure for being honest
        without sounding defeated.
        """
        if not gaps:
            return []

        entries = list(gaps.get("critical_gaps") or [])
        entries += list(gaps.get("nice_to_have_gaps") or [])

        out: List[Dict[str, Any]] = []
        for gap in entries[: self.max_gap]:
            if not isinstance(gap, dict):
                continue
            skill_id = normalise_skill(str(gap.get("skill_id") or gap.get("skill") or ""))
            if not skill_id:
                continue
            name = str(gap.get("skill") or _display(skill_id))
            related = [str(s) for s in (gap.get("similar_skills_user_has") or []) if s]
            bank = QUESTION_BANK.get(skill_id, {})
            answer = self._gap_answer(name, related)

            out.append(
                {
                    "category": GAP_BASED,
                    "skill": name,
                    "question": bank.get(
                        "question",
                        f"What is your experience with {name}?",
                    ),
                    "why_asked": (
                        f"{name} is listed as "
                        f"{str(gap.get('importance') or 'required').lower()} and it is "
                        "not evidenced anywhere on your resume."
                    ),
                    "your_strength": self._gap_strength(name, related),
                    "suggested_answer": answer,
                    "how_to_handle": self._how_to_handle(name, related, gap),
                    "follow_ups": [
                        f"What would you read or build first to pick up {name}?",
                        "How long do you think it would take you to be useful with it?",
                    ],
                    "confidence_level": MEDIUM if related else LOW,
                    # Read back out of the text rather than assumed, so the two
                    # can never drift apart.
                    "answer_placeholders": _placeholders_in(answer),
                    "needs_your_input": True,
                }
            )
        return out

    def _generate_behavioral_questions(self, role_type: str) -> List[Dict[str, str]]:
        """The soft-skill set, with one question flavoured by the role."""
        out = [dict(q) for q in BEHAVIOURAL_BANK]
        extra = _ROLE_BEHAVIOURAL.get((role_type or "").lower())
        if extra:
            out.insert(2, dict(extra))
        return out

    def _generate_hr_questions(self) -> List[Dict[str, str]]:
        """The HR round, which is a different conversation from the technical one."""
        return [dict(q) for q in HR_BANK]

    def _generate_scenario_questions(self, role_type: str) -> List[Dict[str, str]]:
        """Situational questions: what you *would* do, not what you did.

        The general pair comes last. The role-specific ones are the more
        useful preparation, and a candidate who reads only the top of a list
        should be reading those.
        """
        specific = _SCENARIO_BANK.get((role_type or "").lower(), ())
        return [dict(q) for q in specific] + [dict(q) for q in _SCENARIO_GENERAL]

    def _generate_project_questions(
        self, sections: Sequence[Tuple[Any, str]], job_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Questions about the candidate's own projects, quoting their own words.

        Built from the Projects and Experience sections only. A skill listed in
        a comma-separated skills block is a claim with nothing behind it; a
        line in a project bullet is a thing they did, and only the second kind
        can carry a five-minute answer.

        The line is quoted back verbatim rather than paraphrased. Paraphrasing
        would mean generating a description of work this code cannot verify,
        and the candidate would then be preparing for a question about a
        project that does not quite exist.
        """
        wanted = set(_clean(job_analysis.get("required_skills")) or []) | set(
            _clean(job_analysis.get("tech_stack")) or []
        )

        candidates: List[Tuple[int, str, List[str]]] = []
        for section, body in sections:
            if section not in (Section.PROJECTS, Section.EXPERIENCE):
                continue
            for line in _achievement_lines(body):
                clean = line.strip(" -*\u2022\t").strip()
                # Too short to be a description of anything; usually a job
                # title, a date range or a heading.
                if len(clean.split()) < 5:
                    continue
                # Verb-first or it is not an achievement. See
                # ``_ACHIEVEMENT_VERBS``.
                if clean.split()[0].strip(":,.").lower() not in _ACHIEVEMENT_VERBS:
                    continue
                skills = _clean(find_skills(clean))
                if not skills:
                    continue
                # Lines using something the advert asks for are worth more
                # preparation time than lines that do not.
                overlap = len([s for s in skills if s in wanted])
                candidates.append((overlap, clean, skills))

        # Highest overlap first, and stable within that so the order does not
        # change between two runs on the same resume.
        candidates.sort(key=lambda item: -item[0])

        out: List[Dict[str, Any]] = []
        seen: set = set()
        for overlap, line, skills in candidates[:MAX_PROJECT_QUESTIONS]:
            named = ", ".join(_display(s) for s in skills[:3])
            key = named.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "question": (
                        "Your resume says: \"%s\". Walk me through that - what "
                        "was the hard part?" % _shorten(line)
                    ),
                    "category": PROJECT_BASED,
                    "context": (
                        "They will pick a line off your resume and ask you to "
                        "defend it. This one mentions %s%s."
                        % (
                            named,
                            ", which this advert asks for" if overlap else "",
                        )
                    ),
                    "suggested_approach": (
                        "Say what the thing was for before saying how it "
                        "worked, name one decision you would make differently "
                        "now, and be ready for \"why did you choose %s?\". If "
                        "you cannot remember the detail of this line, that is "
                        "a reason to reword it on your resume, not to bluff."
                        % _display(skills[0])
                    ),
                    "skills": [_display(s) for s in skills[:5]],
                    "matches_advert": bool(overlap),
                }
            )
        return out

    def _areas_to_improve(
        self,
        job_analysis: Dict[str, Any],
        gaps: Optional[Dict[str, Any]],
        sections: Sequence[Tuple[Any, str]],
    ) -> List[Dict[str, str]]:
        """What to work on before the interview, worst first.

        Only things that are actually missing, each with what to do about it.
        A list of weaknesses with no suggested action is demoralising and
        useless; the point is the second half of each entry.
        """
        out: List[Dict[str, str]] = []

        have = self._resume_skills({}, _section_text(sections))
        # `tech_stack` as well as `required_skills`: which of the two an
        # advert's technologies land in depends on how the analyzer read it,
        # and a terse advert routinely puts them in only one.
        candidates = _clean((gaps or {}).get("missing_skills")) or _clean(
            list(job_analysis.get("required_skills") or [])
            + list(job_analysis.get("tech_stack") or [])
        )

        missing = []
        for skill in candidates:
            if skill in have or skill in missing:
                continue
            # Only propose things that are actually a named technology.
            #
            # Asked to read "Backend Engineer. Python, FastAPI, Kubernetes and
            # PostgreSQL required", the model returned a single required skill:
            # "backend engineering". Passed through unchecked that produced
            # the advice "Build one small thing with Backend before the
            # interview", which is not a thing anyone can do. A role
            # description is not a gap you can close in an evening, and the
            # vocabulary this app already uses to read resumes is the honest
            # test of the difference.
            if not find_skills(skill):
                continue
            missing.append(skill)

        for skill in missing[:MAX_IMPROVEMENT_AREAS]:
            name = _display(skill)
            out.append(
                {
                    "area": name,
                    "why": (
                        "The advert asks for %s and your resume does not "
                        "mention it." % name
                    ),
                    "what_to_do": (
                        "Build one small thing with %s before the interview so "
                        "you can answer from experience rather than from "
                        "reading. One working example beats a paragraph of "
                        "theory, and it gives you something to talk about "
                        "when they ask." % name
                    ),
                }
            )

        if not self._has_section(sections, Section.PROJECTS):
            out.append(
                {
                    "area": "Nothing on your resume is described as a project",
                    "why": (
                        "Interviewers pick a project off the page and ask "
                        "about it. With no projects section they have to pick "
                        "from your job duties instead, which are harder to "
                        "tell a story about."
                    ),
                    "what_to_do": (
                        "Add two or three projects with what each one did and "
                        "what you personally built."
                    ),
                }
            )

        if not _numbers_in_sections(sections):
            out.append(
                {
                    "area": "No numbers anywhere on your resume",
                    "why": (
                        "\"Improved performance\" and \"improved performance "
                        "by 40%\" are the same claim, but only the second one "
                        "invites the follow-up question you want."
                    ),
                    "what_to_do": (
                        "Put a figure on two or three bullets - users, "
                        "requests, latency, time saved. Estimates are fine if "
                        "you can explain how you arrived at them."
                    ),
                }
            )

        return out

    @staticmethod
    def _has_section(
        sections: Sequence[Tuple[Any, str]], wanted: Any
    ) -> bool:
        return any(section == wanted for section, _body in sections)

    def _generate_follow_ups(self, question: Any) -> List[str]:
        """The questions that come *after* the one they opened with.

        Candidates over-prepare the headline answer and get caught two levels
        down, so these are treated as first-class rather than decoration.
        """
        if isinstance(question, dict):
            listed = question.get("follow_ups")
            if listed:
                return [str(f) for f in listed][:4]
            skill = normalise_skill(str(question.get("skill") or ""))
            if skill in QUESTION_BANK:
                return [str(f) for f in QUESTION_BANK[skill]["follow_ups"]][:4]
            category = question.get("category")
        else:
            skill = normalise_skill(str(question))
            if skill in QUESTION_BANK:
                return [str(f) for f in QUESTION_BANK[skill]["follow_ups"]][:4]
            category = None

        if category == GAP_BASED:
            return ["How would you go about learning it?"]
        return [
            "What would you do differently now?",
            "How did you test that?",
            "What was the hardest part?",
        ]

    def _create_suggested_answer(
        self,
        question: Dict[str, Any],
        resume_data: Dict[str, Any],
        lines: Optional[Sequence[str]] = None,
    ) -> str:
        """A first-person scaffold built only from what the resume says.

        The candidate's own wording is quoted back at them so the answer sounds
        like theirs, and every fact the resume does not contain - the reason for
        a choice, the outcome, any number - is left as a blank. That is the
        whole design: fluent invented detail is exactly what collapses under a
        follow-up question.
        """
        skill = normalise_skill(str(question.get("skill") or ""))
        name = _display(skill) if skill else "this"

        if lines is None:
            text = str(resume_data.get("resume_text") or "")
            lines = self._evidence_index(self._sections(text)).get(skill, [])

        if not lines:
            return (
                f"Your resume lists {name} but never shows where you used it, so "
                f"expect to be asked for a concrete example. Have one ready: what "
                f"you built with it, [WHY THIS CHOICE], and [RESULT]. If the honest "
                f"answer is that you have only read about it, say so plainly."
            )

        anchor = lines[0].rstrip(". ")
        parts = [
            f'Start from your own work: "{anchor}".',
            "Say what the system had to do - [PROBLEM IT SOLVED].",
            f"Explain why you reached for {name} rather than the alternative - "
            "[WHY THIS CHOICE].",
            "Give the outcome - [RESULT].",
            "Close with [WHAT YOU'D CHANGE] if you built it again, which is the "
            "part that makes you sound senior.",
        ]
        if len(lines) > 1:
            parts.insert(
                1,
                f'You have a second example if they push: "{lines[1].rstrip(". ")}".',
            )
        return " ".join(parts)

    # -- Gap coaching ---------------------------------------------------

    @staticmethod
    def _gap_strength(name: str, related: Sequence[str]) -> str:
        if related:
            joined = ", ".join(_display(normalise_skill(r)) for r in related[:2])
            return f"Low - no {name} experience, but {joined} is adjacent"
        return f"Low - no {name} experience and nothing closely related"

    @staticmethod
    def _gap_answer(name: str, related: Sequence[str]) -> str:
        """An honest answer, structured so honesty does not sound like defeat.

        When something adjacent is on the resume the opening is deliberately
        *not* "I have not used it". Skill matching is imperfect - a candidate
        using PostgreSQL every day can be reported as missing SQL - and an
        agent that coaches someone into disowning a skill they have is doing
        the same damage as one that invents a skill they lack, just in the
        other direction. So the answer defers to what the candidate knows.
        """
        if related:
            joined = " and ".join(_display(normalise_skill(r)) for r in related[:2])
            return (
                f"Your resume does not name {name} directly, but it does show "
                f"{joined}. If that work genuinely involved {name}, say so plainly "
                f"and give the example - do not talk yourself out of experience you "
                f"actually have. If it did not, say you have not used {name}, "
                f"explain what carries over from {joined}, and say what you would do "
                f"in your first week. Only claim study you have really done - if you "
                f"have started, say [HOW FAR YOU GOT] precisely."
            )
        return (
            f"Say plainly that you have not used {name}. Do not pad it. Follow it "
            f"with the nearest thing you have genuinely built and why you think it "
            f"transfers, then what you would do to get up to speed. An honest no "
            f"with a plan beats a vague yes that unravels on the next question."
        )

    @staticmethod
    def _how_to_handle(
        name: str, related: Sequence[str], gap: Dict[str, Any]
    ) -> List[str]:
        if related:
            joined = " / ".join(_display(normalise_skill(r)) for r in related[:2])
            steps = [
                f"First check whether this is really a gap. Your {joined} work may "
                f"already involve {name} - if it does, this is a normal experience "
                "question, not an awkward one.",
                f"If it is a genuine gap, say so, then bridge to {joined} and name "
                "the concept the two share, not just the tool.",
            ]
        else:
            steps = [
                f"Be honest that you have not used {name} - they will ask a second "
                "question, and a bluff fails there rather than here.",
            ]
        days = gap.get("learning_time_days")
        if isinstance(days, int) and days > 0:
            steps.append(
                f"You are roughly {days} day(s) from being useful with it - saying "
                "that shows you have assessed it rather than hand-waved."
            )
        steps.append(
            "Only mention studying it if you actually have. If you do, say exactly "
            "what you covered."
        )
        steps.append("Ask what they use it for. It turns your gap into a conversation.")
        return steps

    # -- Company and reverse questions -----------------------------------

    def _company_questions(
        self,
        job_analysis: Dict[str, Any],
        match_data: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        matched = _clean((match_data or {}).get("matched_skills"))
        stack = _clean(job_analysis.get("tech_stack"))
        angle_skills = [s for s in matched if s in stack] or matched[:2]

        if angle_skills:
            angle = (
                "Lead with "
                + " and ".join(_display(s) for s in angle_skills[:2])
                + " - it is where your experience and their advert actually overlap."
            )
        else:
            angle = (
                "Focus on the problem the team is solving rather than the stack, "
                "since your overlap with their listed tools is thin."
            )

        out: List[Dict[str, Any]] = []
        for topic, research in _RESEARCH_TOPICS:
            out.append(
                {
                    "topic": topic,
                    "suggested_research": list(research),
                    "your_angle": angle,
                }
            )
        return out

    def _questions_for_them(
        self,
        job_analysis: Dict[str, Any],
        gaps: Optional[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Questions the candidate asks, chosen to do work for them."""
        out: List[Dict[str, str]] = []

        critical = list((gaps or {}).get("critical_gaps") or [])
        if critical and isinstance(critical[0], dict):
            skill = str(critical[0].get("skill") or "")
            if skill:
                out.append(
                    {
                        "question": f"How does the team use {skill} day to day?",
                        "why_ask": (
                            f"Turns your weakest area into a normal conversation, and "
                            f"their answer tells you how much {skill} you would really "
                            "need on day one."
                        ),
                    }
                )

        stack = _clean(job_analysis.get("tech_stack"))
        if stack:
            out.append(
                {
                    "question": (
                        f"What does the {_display(stack[0])} side of the codebase look "
                        "like now, and what would you change about it?"
                    ),
                    "why_ask": "Gets an honest answer about technical debt before you join.",
                }
            )

        out.extend(
            [
                {
                    "question": "What would a successful first three months look like?",
                    "why_ask": (
                        "If they cannot answer it, the role is not well defined - that "
                        "is worth knowing before you accept."
                    ),
                },
                {
                    "question": "How does work get from an idea to production here?",
                    "why_ask": "Reveals review culture, testing and release discipline in one answer.",
                },
                {
                    "question": "What is the thing about working here that people find hardest?",
                    "why_ask": "Harder to answer with a platitude than 'what is the culture like?'.",
                },
            ]
        )
        return out

    # -- Planning --------------------------------------------------------

    def _create_prep_schedule(
        self,
        total_hours: float,
        gap_count: int,
        gaps: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """A day-by-day plan someone with a job could actually follow.

        Ordered by return on effort. Your own projects come first: they are the
        largest share of the interview and the cheapest thing to prepare, and a
        candidate who spends the whole week cramming a missing skill still gets
        caught out explaining their own work.
        """
        if total_hours <= 0:
            return []

        blocks: List[Tuple[str, float, List[str]]] = [
            (
                "Re-read your own projects until you can explain them cold",
                min(2.0, total_hours),
                [
                    "Write one paragraph per project: problem, choice, outcome",
                    "Fill in every bracketed blank in the suggested answers",
                    "Re-read the code you wrote - you will have forgotten the details",
                ],
            )
        ]

        if gap_count:
            names = []
            for gap in list((gaps or {}).get("critical_gaps") or [])[:2]:
                if isinstance(gap, dict) and gap.get("skill"):
                    names.append(str(gap["skill"]))
            focus = (
                f"Get hands-on with {' and '.join(names)}"
                if names
                else "Close the biggest skill gap"
            )
            blocks.append(
                (
                    focus,
                    min(3.0, HOURS_PER_GAP * gap_count),
                    [
                        "Read the official quickstart, not a blog post",
                        "Build the smallest thing that runs end to end",
                        "Write down exactly how far you got, so you can say it honestly",
                    ],
                )
            )

        blocks.append(
            (
                "Prepare behavioural answers",
                HOURS_BEHAVIOURAL,
                [
                    "Pick one real story per behavioural question",
                    "Check each story has a result, not just a situation",
                ],
            )
        )
        blocks.append(
            (
                "Practise out loud",
                HOURS_MOCK_PRACTICE,
                [
                    "Answer each technical question aloud, timed to two minutes",
                    "Record one and listen back - it is unpleasant and it works",
                    "Practise the gap answers most; those are the ones that wobble",
                ],
            )
        )
        blocks.append(
            (
                "Research the company",
                HOURS_COMPANY_RESEARCH,
                [
                    "Learn what they sell and who pays for it",
                    "Prepare your own questions for them",
                ],
            )
        )

        plan: List[Dict[str, Any]] = []
        for index, (focus, hours, tasks) in enumerate(blocks[:MAX_PREP_DAYS], start=1):
            plan.append(
                {
                    "day": index,
                    "focus": focus,
                    "time_hours": round(min(hours, REALISTIC_HOURS_PER_DAY), 1),
                    "tasks": tasks,
                }
            )
        return plan

    def _predict_success_rate(
        self,
        match_data: Optional[Dict[str, Any]],
        gaps: Optional[Dict[str, Any]] = None,
        difficulty: str = MEDIUM,
    ) -> float:
        """A rough, transparent estimate - not a real probability.

        Derived from the match score, penalised for critical gaps and for a
        harder interview. It is deliberately capped below certainty: no amount
        of resume analysis can know how someone performs in a room, and a
        confident-looking 0.97 would be a lie dressed as arithmetic.
        """
        score = 0.0
        if match_data:
            try:
                score = float(match_data.get("overall_match") or 0.0)
            except (TypeError, ValueError):
                score = 0.0

        base = max(0.0, min(1.0, score / 100.0))

        critical = len((gaps or {}).get("critical_gaps") or [])
        base -= 0.05 * min(critical, 4)

        if difficulty == HARD:
            base -= 0.10
        elif difficulty == EASY:
            base += 0.05

        return round(max(0.05, min(0.92, base)), 2)

    def _explain_success_rate(
        self,
        predicted: float,
        match_data: Optional[Dict[str, Any]],
        gaps: Optional[Dict[str, Any]] = None,
        difficulty: str = MEDIUM,
    ) -> Dict[str, Any]:
        """Show the arithmetic behind the prediction, term by term.

        A bare number invites either blind trust or blind dismissal. Listing
        what moved it, and by how much, lets the candidate argue with it -
        which is the correct response to an estimate this crude.

        Note what is deliberately *not* a term here: how much preparation the
        candidate has done. This agent hands out a study plan, it does not
        watch anyone follow it, so treating prep as a multiplier would inflate
        the number using a fact nobody has measured.
        """
        score = 0.0
        if match_data:
            try:
                score = float(match_data.get("overall_match") or 0.0)
            except (TypeError, ValueError):
                score = 0.0

        critical = len((gaps or {}).get("critical_gaps") or [])
        counted = min(critical, 4)

        factors: List[Dict[str, Any]] = [
            {
                "factor": "Resume match",
                "effect": f"+{round(max(0.0, min(1.0, score / 100.0)) * 100)}%",
                "why": f"Your resume scored {round(score, 1)}% against this advert.",
            }
        ]

        if counted:
            plural = "s" if counted > 1 else ""
            extra = (
                f" ({critical} found, only the first four are counted)"
                if critical > counted
                else ""
            )
            factors.append(
                {
                    "factor": "Critical gaps",
                    "effect": f"-{counted * 5}%",
                    "why": (
                        f"{counted} required skill{plural} missing{extra}; each one "
                        "is a question you cannot answer from experience."
                    ),
                }
            )

        if difficulty == HARD:
            factors.append(
                {
                    "factor": "Interview difficulty",
                    "effect": "-10%",
                    "why": "A senior or heavily-specified advert screens harder.",
                }
            )
        elif difficulty == EASY:
            factors.append(
                {
                    "factor": "Interview difficulty",
                    "effect": "+5%",
                    "why": "The advert's bar looks reachable from where you are.",
                }
            )

        capped = predicted >= 0.92
        return {
            "predicted": predicted,
            "as_percentage": round(predicted * 100),
            "factors": factors,
            "ceiling": 0.92,
            "capped": capped,
            "caveat": (
                "This is arithmetic on a resume, not a forecast. It cannot see "
                "how you speak, how you think aloud, or who else applied. "
                + (
                    "It is capped at 92% because nothing on paper justifies "
                    "more confidence than that."
                    if capped
                    else "Preparation is not a term in it, because nothing here "
                    "can verify you did any - doing the plan raises your real "
                    "chances without moving this number."
                )
            ),
        }

    def _prep_hours(
        self,
        questions: Sequence[Dict[str, Any]],
        gap_questions: Sequence[Dict[str, Any]],
        difficulty: str,
    ) -> float:
        technical = len(questions) - len(gap_questions)
        hours = (
            technical * HOURS_PER_TECHNICAL_TOPIC
            + len(gap_questions) * HOURS_PER_GAP
            + HOURS_BEHAVIOURAL
            + HOURS_COMPANY_RESEARCH
            + HOURS_MOCK_PRACTICE
        )
        if difficulty == HARD:
            hours *= 1.25
        elif difficulty == EASY:
            hours *= 0.8
        return round(min(hours, MAX_PREP_DAYS * REALISTIC_HOURS_PER_DAY), 1)

    def _difficulty(
        self,
        job_analysis: Dict[str, Any],
        gaps: Optional[Dict[str, Any]],
        match_data: Optional[Dict[str, Any]],
    ) -> str:
        """How hard this specific interview is likely to be for this candidate."""
        points = 0

        seniority = str(job_analysis.get("seniority") or job_analysis.get("experience_level") or "").lower()
        if any(word in seniority for word in ("senior", "lead", "staff", "principal")):
            points += 2
        elif "junior" in seniority or "entry" in seniority:
            points -= 1

        required = _clean(job_analysis.get("required_skills"))
        if len(required) >= 8:
            points += 1

        critical = len((gaps or {}).get("critical_gaps") or [])
        if critical >= 3:
            points += 2
        elif critical:
            points += 1

        if match_data:
            try:
                score = float(match_data.get("overall_match") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score >= 80:
                points -= 2
            elif score < 55:
                points += 1

        if points >= 3:
            return HARD
        if points <= 0:
            return EASY
        return MEDIUM

    # -- Resume reading --------------------------------------------------

    def _sections(self, text: str) -> List[Tuple[Any, str]]:
        if not text.strip():
            return []
        try:
            return list(split_into_sections(text))
        except Exception:  # noqa: BLE001 - a parse failure must not lose the run
            logger.exception("Could not split resume into sections")
            return []

    def _evidence_index(
        self, sections: Sequence[Tuple[Any, str]]
    ) -> Dict[str, List[str]]:
        """Map each skill to the resume lines that actually demonstrate it.

        Only narrative sections count. A skill appearing in a comma-separated
        skills list is a claim; a skill appearing in a project bullet is
        evidence, and only the second kind can support an interview answer.
        """
        strong: Dict[str, List[str]] = {}
        weak: Dict[str, List[str]] = {}

        for section, body in sections:
            if section in (Section.SKILLS, Section.EDUCATION):
                continue
            # A line from Experience or Projects is something they did. The
            # summary block merely asserts it, so it is kept as a last resort
            # but never used as the anchor when real work is available.
            bucket = (
                weak if section in (Section.SUMMARY, Section.OTHER) else strong
            )
            for line in split_bullets(body):
                clean = line.strip(" -*\u2022\t")
                if len(clean.split()) < 3:
                    continue
                for skill in _clean(find_skills(clean)):
                    lines = bucket.setdefault(skill, [])
                    if clean not in lines:
                        lines.append(clean)

        index: Dict[str, List[str]] = {}
        for skill in set(strong) | set(weak):
            merged = list(strong.get(skill, []))
            for line in weak.get(skill, []):
                if line not in merged:
                    merged.append(line)
            index[skill] = merged
        return index

    def _resume_skills(self, resume: Dict[str, Any], text: str) -> Set[str]:
        skills = set(_clean(resume.get("skills")))
        if text:
            skills |= set(_clean(find_skills(text)))
        return skills

    # -- Presentation helpers --------------------------------------------

    @staticmethod
    def _question_for_skill(skill: str) -> Optional[Dict[str, Any]]:
        entry = QUESTION_BANK.get(skill)
        if entry:
            return entry
        matched = match_skill(skill, set(QUESTION_BANK))
        if matched:
            return QUESTION_BANK[matched[0]]
        return {
            "question": f"Tell us how you have used {_display(skill)}.",
            "follow_ups": [
                "What was the hardest part?",
                "What would you do differently now?",
            ],
            "category": TECHNICAL,
        }

    @staticmethod
    def _strength(
        skill: str,
        lines: Sequence[str],
    ) -> Tuple[str, str]:
        name = _display(skill)
        count = len(lines)
        if count >= 2:
            return f"High - {count} places on your resume evidence {name}", HIGH
        if count == 1:
            return f"Medium - one line on your resume evidences {name}", MEDIUM
        return f"Low - {name} is claimed but not demonstrated anywhere", LOW

    @staticmethod
    def _why_asked(skill: str, job_analysis: Dict[str, Any], advert: str) -> str:
        name = _display(skill)
        required = _clean(job_analysis.get("required_skills"))
        stack = _clean(job_analysis.get("tech_stack"))
        mentions = advert.count(skill) if advert else 0

        if skill in stack:
            return f"{name} is part of their core stack, so expect depth rather than trivia."
        if mentions >= 3:
            return f"The advert mentions {name} {mentions} times - it is the thing they care about most."
        if skill in required:
            return f"{name} is a stated requirement."
        return f"{name} is listed as preferred, so this is likely a lighter question."

    @staticmethod
    def _number(questions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for index, question in enumerate(questions, start=1):
            item = {"id": index}
            item.update(question)
            out.append(item)
        return out

    @staticmethod
    def _confidence(
        text: str,
        sections: Sequence[Tuple[Any, str]],
        job_analysis: Dict[str, Any],
        match_data: Optional[Dict[str, Any]],
    ) -> float:
        """How much the pack should be trusted, given the evidence available."""
        if not text:
            # Without a resume the questions come from the advert alone, which
            # makes the "your strength" and answer sections guesswork.
            return 0.2
        score = 0.4
        if len(sections) >= 3:
            score += 0.2
        if job_analysis.get("required_skills"):
            score += 0.2
        if match_data:
            score += 0.1
        if job_analysis.get("job_description"):
            score += 0.05
        return round(min(score, 0.95), 2)


#: Shared instance, mirroring the other agents.
interview_prep_agent = InterviewPrepAgent()
