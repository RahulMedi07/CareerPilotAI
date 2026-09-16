"""Pydantic models shared across the CareerPilot AI API."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Skill(BaseModel):
    name: str
    level: Optional[SkillLevel] = None
    years_experience: Optional[float] = None


class JobDescription(BaseModel):
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    description: str = Field(min_length=1)


class JobAnalysis(BaseModel):
    title: str
    company: Optional[str] = None
    required_skills: list[Skill] = Field(default_factory=list)
    preferred_skills: list[Skill] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)


class MatchRequest(BaseModel):
    resume_id: str
    job: JobDescription


class MatchResult(BaseModel):
    resume_id: str
    job_title: str
    #: ``None`` when the advert specified nothing that could be assessed. A
    #: real 0.0 means measured and unmatched; the two must stay distinguishable.
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ResumeProfile(BaseModel):
    """Structured facts pulled out of an indexed resume."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    experience_years: Optional[float] = None
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    """A single chunk returned by a semantic search, with its similarity score."""

    chunk_id: str
    text: str
    score: float = Field(ge=0.0, le=1.0)
    content_type: str = "resume"
    section: str = "other"
    source: str = ""
    metadata: dict = Field(default_factory=dict)

    def as_context(self) -> str:
        label = self.section if self.section != "other" else self.content_type
        return f"[{label} | relevance {self.score:.2f}] {self.text}"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    resume_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# /api/career request and response bodies
# --------------------------------------------------------------------------- #
class JobDescriptionRequest(BaseModel):
    """Body for the endpoints that take a raw advert.

    ``max_length`` is a guard, not a business rule: the text is embedded and
    handed to an LLM, so an unbounded body is a cheap way to exhaust the box.
    """

    job_description: str = Field(min_length=1, max_length=50_000)


class ResumeIndexResponse(BaseModel):
    status: str = "success"
    message: str = "Resume indexed"
    file_size: int = Field(ge=0)


class JobAnalysisResponse(BaseModel):
    """The job analyzer's own dict, passed through unchanged.

    Deliberately open: `JobAnalyzerAgent.analyze()` owns this contract and
    re-declaring its fifteen keys here would leave two copies to keep in step.
    """

    model_config = {"extra": "allow"}

    title: str = ""
    required_skills: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class FullAnalysisSections(BaseModel):
    """The five reports, each passed through as its agent produced it."""

    job_analysis: dict = Field(default_factory=dict)
    match_breakdown: dict = Field(default_factory=dict)
    gaps: dict = Field(default_factory=dict)
    resume_optimizations: dict = Field(default_factory=dict)
    interview_prep: dict = Field(default_factory=dict)


class FullAnalysisResponse(BaseModel):
    """Everything the pipeline produced, in one response.

    ``confidence`` is deliberately absent at this level. The two available
    numbers are on different scales -- the match calculator reports 0-100 and
    the pipeline reports 0-1 -- and putting either here under a bare name would
    invite exactly the mix-up that had to be fixed inside the pipeline. Each
    stays inside its own section, where its scale is unambiguous.
    """

    analysis_id: str
    #: ``None`` when nothing could be assessed. See :class:`MatchResponse`.
    overall_match: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    recommendation: str
    user_recommendation: str = ""
    analysis: FullAnalysisSections = Field(default_factory=FullAnalysisSections)
    execution_trace: list = Field(default_factory=list)
    total_analysis_time_ms: int = Field(default=0, ge=0)
    status: str = "completed"
    nodes_failed: list[str] = Field(default_factory=list)


class TraceNode(BaseModel):
    name: str
    status: str
    duration_ms: int = Field(default=0, ge=0)
    output_summary: str = ""


class TraceResponse(BaseModel):
    analysis_id: str
    nodes: list[TraceNode] = Field(default_factory=list)
    total_duration_ms: int = Field(default=0, ge=0)
    status: str = "completed"


class IndexStatusResponse(BaseModel):
    resume_indexed: bool
    status: str = "ready"
    chunks: int = Field(default=0, ge=0)


class ClearIndexResponse(BaseModel):
    status: str = "success"
    message: str = "Index cleared"
    chunks_removed: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
# Job discovery
# --------------------------------------------------------------------------- #
class JobDiscoveryRequest(BaseModel):
    """What to look for.

    There is deliberately no field for a feed URL. Letting a caller name the
    address to fetch would turn this endpoint into an open proxy against the
    server's own network, which is the exact hole the scraper's allow-list
    exists to close. Sources are chosen in code, not over the wire.
    """

    query: str = Field(default="python developer", min_length=1, max_length=200)
    #: Defaults to India, because that is where this app's user is looking for
    #: work. "remote" was the old default and means "no location constraint",
    #: which quietly returned adverts nobody here can take.
    location: str = Field(default="india", max_length=100)
    limit: int = Field(default=10, ge=1, le=50)
    #: Ignore ``query`` and search for what the indexed resume actually points
    #: at instead. Answers 409 when no resume is indexed rather than quietly
    #: falling back to the default query, which would return adverts for
    #: somebody else's career and look like a working search.
    auto_from_resume: bool = False
    #: Only adverts posted within this many days. ``None`` means any age.
    #: The server widens this on its own when the window returns almost
    #: nothing, and says so in ``freshness_note`` - a filter that silently
    #: returns an empty page looks identical to a broken search.
    max_age_days: Optional[int] = Field(default=None, ge=0, le=365)


class JobDiscoveryResponse(BaseModel):
    #: Left as a bare list rather than a typed model. There was a
    #: ``DiscoveredJob`` model here; it was removed because nothing used it and
    #: it advertised a ``match_score`` field that is never populated - the
    #: score lives at ``job["match_to_user"]["score"]``. A schema that
    #: describes a shape the code does not produce is worse than none, because
    #: a client believes it.
    jobs: list = Field(default_factory=list)
    categorized: dict = Field(default_factory=dict)
    total_found: int = Field(default=0, ge=0)
    #: Named so the reader can see which feeds actually answered. A source
    #: that failed is absent rather than silently counted as empty.
    sources_used: list[str] = Field(default_factory=list)
    #: Several sources require attribution as a condition of use. Passing it
    #: through means a caller can honour that without reading their terms.
    attribution: list[str] = Field(default_factory=list)
    #: True when a resume was indexed and the adverts were scored against it.
    #: False means the list is unranked - not that every advert scored zero.
    scored_against_resume: bool = False
    #: Every phrase actually searched. With ``auto_from_resume`` this is how
    #: the caller finds out what the server decided they do for a living, and
    #: it is shown in the UI so a wrong guess is visible rather than silent.
    queries_used: list[str] = Field(default_factory=list)
    #: True when those phrases came from the resume rather than the caller.
    derived_from_resume: bool = False
    #: The window actually applied, which is not always the one asked for.
    #: ``None`` means no age filter survived and the list spans every age.
    max_age_days_used: Optional[int] = None
    #: Set only when the requested window was widened or dropped, and it says
    #: which and why. The UI shows it verbatim so "nothing posted in the last
    #: two days" never masquerades as "nothing matches you".
    freshness_note: Optional[str] = None
    #: How many adverts carried no posting date at all. These survive the age
    #: filter only when no window is in force, because "unknown" is not
    #: "recent".
    undated_count: int = Field(default=0, ge=0)


class SaveJobRequest(BaseModel):
    """``job_id`` refers to a job returned by a recent discovery call.

    Only ids the server has already seen are accepted, so a caller cannot
    inject arbitrary content into the store through this route.

    There is deliberately no ``user_id`` here. The owner comes from the session
    cookie; accepting one in the body would put a field in the public schema
    that looks like it chooses the owner and does not.
    """

    job_id: str = Field(min_length=1, max_length=64)
    status: str = Field(default="saved", max_length=20)
    notes: str = Field(default="", max_length=2000)


class SaveJobResponse(BaseModel):
    saved: bool = True
    job_id: str = ""
    user_jobs_count: int = Field(default=0, ge=0)


class SavedJobsResponse(BaseModel):
    jobs: list = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    status_counts: dict = Field(default_factory=dict)
    #: Echoed back so the caller can see which account the server decided it
    #: was talking to. It is read from the session, never from the request.
    user_id: str = "local"


class CreateApplicationRequest(BaseModel):
    """``analysis_data`` is whatever the analysis pipeline produced.

    Nothing in it is required. An application can be tracked before any
    analysis has run, and the fields simply stay empty rather than being
    filled with zeros that would later be averaged as if they were measured.
    """

    job_id: str = Field(min_length=1, max_length=64)
    analysis_data: dict = Field(default_factory=dict)
    status: str = Field(default="draft", max_length=32)


class CreateApplicationResponse(BaseModel):
    application_id: str
    status: str = "draft"


class UpdateApplicationStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    details: dict = Field(default_factory=dict)


class UpdateApplicationStatusResponse(BaseModel):
    updated: bool = True
    app_id: str = ""
    status: str = ""


class ApplicationsResponse(BaseModel):
    applications: list = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    status_counts: dict = Field(default_factory=dict)
    user_id: str = "local"


class ApplicationHistoryResponse(BaseModel):
    app_id: str
    job_title: str = ""
    company: str = ""
    match_score: Optional[float] = None
    current_status: str = ""
    timeline: list = Field(default_factory=list)
    interviews: list = Field(default_factory=list)
    gaps_identified: list = Field(default_factory=list)


class AnalyticsResponse(BaseModel):
    """Rates, strategy and forecast.

    Several fields are deliberately nullable. An interview rate computed from
    no applications is not 0%, it is *absent*, and a forecast built on no
    offers is not 0%, it is unavailable. Sending a zero would be read as a
    measurement.
    """

    metrics: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    prediction: dict = Field(default_factory=dict)
    user_id: str = "local"


# --------------------------------------------------------------------------- #
# Resume insights, chat and interview prep
# --------------------------------------------------------------------------- #
class ResumeInsightsResponse(BaseModel):
    """What one resume says about its owner, with no job advert involved.

    Note which fields are nullable and why. ``experience_years`` is ``None``
    when the resume never states a duration - that is a different fact from
    "no experience", and rendering it as 0 would be a lie the candidate then
    has to argue with. ``primary_role`` falls back to the string ``"unknown"``
    rather than guessing at a job family from one or two shared keywords.
    """

    headline: str = ""
    primary_role: str = "unknown"
    seniority: str = "unknown"
    #: ``None`` means the resume does not say. Never coerce this to zero.
    experience_years: Optional[float] = Field(default=None, ge=0.0, le=70.0)
    #: Highest qualification named, e.g. ``"bachelors"``. ``None`` when the
    #: resume names none, which is not the same as having no education.
    education: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    #: Skills bucketed for display, e.g. ``{"Languages": ["python"]}``. Empty
    #: groups are dropped rather than rendered as blank rows.
    skill_groups: dict = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    suggested_roles: list[str] = Field(default_factory=list)
    #: Ready-made job-board phrases, so the user never has to invent a search.
    search_queries: list[str] = Field(default_factory=list)
    #: ``"llm"`` or ``"fallback"``. Surfaced so the UI can say which wrote this.
    source: str = "fallback"
    #: Set when a model was tried and could not answer. The result still stands.
    warning: Optional[str] = None
    #: Where the analysed text came from: ``upload``, ``request`` or ``index``.
    resume_source: str = "index"


class ChatMessage(BaseModel):
    """One turn. The transcript is held by the client and replayed each call.

    Keeping no server-side session is deliberate: there is no user account to
    hang one off, and a per-process dict would silently diverge between
    workers.
    """

    role: str = Field(default="user", pattern="^(user|assistant)$")
    content: str = Field(default="", max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)
    #: The advert the user currently has open, if any. Sent as text rather
    #: than as an id so the assistant works for a job pasted by hand as well
    #: as one picked from search, and so it needs no server-side notion of a
    #: "current job" - there is none, and inventing one would mean state that
    #: two browser tabs would immediately disagree about.
    job_description: str = Field(default="", max_length=20000)
    #: Only for display, so a reply can name the role. Never used for lookup.
    job_title: str = Field(default="", max_length=200)


class ChatResponse(BaseModel):
    reply: str = ""
    #: ``"llm"`` when a model wrote the reply, ``"fallback"`` when a rule did.
    #: The client is expected to show this, not hide it: a chat box looks
    #: equally intelligent either way, and only this field distinguishes them.
    source: str = "fallback"
    backend: Optional[str] = None
    warning: Optional[str] = None
    suggestions: list[str] = Field(default_factory=list)
    #: False when nothing is indexed, so the client can point at the upload
    #: page instead of letting the user talk to an empty context.
    resume_available: bool = False


class InterviewPrepRequest(BaseModel):
    """``job_description`` is optional on purpose.

    With one, the questions are aimed at that advert. Without one, they are
    built from the resume alone, which is what someone with an interview
    booked and no job text to hand actually needs.
    """

    job_description: str = Field(default="", max_length=20000)
    resume_text: str = Field(default="", max_length=50000)


class InterviewPrepResponse(BaseModel):
    interview_difficulty: str = "unknown"
    estimated_prep_time_hours: Optional[float] = Field(default=None, ge=0.0)
    questions: list = Field(default_factory=list)
    behavioral_questions: list = Field(default_factory=list)
    #: The HR round. Separate from ``behavioral_questions`` because it is a
    #: different conversation with different people, and the notice-period and
    #: salary questions get lost when the two are merged.
    hr_questions: list = Field(default_factory=list)
    #: "What would you do if..." - answerable without the experience already
    #: being on the resume, which makes them the friendliest ground for a
    #: candidate with gaps.
    scenario_questions: list = Field(default_factory=list)
    #: Built by quoting the candidate's own project and experience bullets, so
    #: this is empty when the resume has none to quote rather than being
    #: filled with invented projects.
    project_questions: list = Field(default_factory=list)
    #: What to work on before the interview. Each entry pairs the weakness
    #: with something to do about it; a bare list of weaknesses would be
    #: discouraging and unactionable.
    areas_to_improve: list = Field(default_factory=list)
    company_questions: list = Field(default_factory=list)
    your_questions_for_them: list = Field(default_factory=list)
    preparation_plan: list = Field(default_factory=list)
    question_count: int = Field(default=0, ge=0)
    #: True when an advert was supplied. False means the questions are generic
    #: to the resume, which the UI should say rather than imply a target role.
    tailored_to_job: bool = False
    honesty_note: str = ""
    source: str = "fallback"
    resume_source: str = "index"


class PracticeAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=6000)
    #: The skill the question was aimed at, if the caller knows it. Used to
    #: work out what the question was fishing for.
    skill: str = Field(default="", max_length=120)


class PracticeAnswerResponse(BaseModel):
    #: 1-10, and **only** when a model actually read the answer. ``None``
    #: means nothing scored it. Render that as "not scored", never as zero -
    #: a fabricated score is the most persuasive lie this app could tell.
    score: Optional[int] = Field(default=None, ge=1, le=10)
    verdict: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    #: Checkable statements about the answer: length, whether it names a
    #: number, whether it says "I". True without a model.
    observations: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    improved_opening: str = ""
    source: str = "fallback"
    backend: str = "none"
    note: str = ""


class ErrorResponse(BaseModel):
    detail: str
