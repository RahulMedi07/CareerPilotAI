"""Talking to a language model, with a safety net.

CareerPilot prefers a **local** model through Ollama: it is free, private and
works offline. But a laptop may not have the Ollama daemon running, so this
module is built around graceful degradation:

1. Try Ollama at ``config.LLM_BASE_URL``.
2. If it is unreachable, fall back to the Claude API (when a key is set).
3. If neither is available, raise :class:`LLMUnavailableError` so the caller can
   drop back to its deterministic keyword logic instead of crashing.

Nothing here opens a socket at import time. Availability is probed lazily and
the answer is cached, so a dead daemon costs one short timeout per process
rather than one per prompt.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from agents import AgentConfig, LLMProvider
from utils.error_handling import LLMError
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMUnavailableError(LLMError):
    """No backend could be reached.

    Callers are expected to catch this and degrade, not to propagate it.
    """


class LLMResponseError(LLMError):
    """A backend answered, but the answer could not be used."""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

JOB_ANALYSIS_SYSTEM = (
    "You are a careful technical recruiter. You read job descriptions and "
    "return structured facts about them. You never invent requirements that "
    "are not in the text. You answer with JSON only, no prose, no markdown "
    "fences."
)

JOB_ANALYSIS_TEMPLATE = """Analyze this job description and extract:
1. List of required hard skills
2. Tech stack required
3. Years of experience needed
4. Required soft skills
5. Education requirements
6. Role classification

Format as JSON with these keys:
  "required_skills":  array of lowercase strings, the hard skills demanded
  "tech_stack":       array of lowercase strings, concrete tools and languages
  "experience_years": integer, 0 if the posting does not say
  "soft_skills":      array of lowercase strings
  "education":        string, e.g. "bachelors", "masters", "not specified"
  "role_type":        one of "backend", "frontend", "fullstack", "ai/ml",
                      "data", "devops", "mobile", "security", "qa", "general"
  "seniority":        one of "intern", "junior", "mid", "senior", "staff",
                      "lead", "unknown"
  "preferred_skills": array of lowercase strings, the nice-to-haves
  "title":            string, the role title

Only list skills that appear in the text. Do not invent requirements.

JOB DESCRIPTION:
{job_description}

JSON:"""

SKILL_EXTRACTION_SYSTEM = (
    "You extract technical skills from resumes. You list only skills that are "
    "evidenced in the text. You answer with JSON only."
)

SKILL_EXTRACTION_TEMPLATE = """List the technical skills demonstrated in this resume.

Return a JSON object with one key:
  "skills": array of lowercase strings

Include languages, frameworks, databases, cloud platforms and tools. Exclude
soft skills and job titles.

RESUME:
{resume_text}

JSON:"""

GAP_ANALYSIS_SYSTEM = (
    "You compare a candidate against a job's requirements and explain the "
    "difference honestly and concisely. You answer with JSON only."
)

GAP_ANALYSIS_TEMPLATE = """Compare the candidate's skills with the job's requirements.

Return a JSON object with exactly these keys:
  "gaps":        array of strings, required skills the candidate lacks
  "strengths":   array of strings, required skills the candidate clearly has
  "explanation": string, at most three sentences

CANDIDATE SKILLS: {candidate_skills}
REQUIRED SKILLS:  {required_skills}
PREFERRED SKILLS: {preferred_skills}

JSON:"""

RESUME_REVIEW_SYSTEM = (
    "You are an experienced technical hiring manager reading a candidate's "
    "resume on its own, with no job advert to compare it against. You "
    "describe what is actually on the page. You never credit the candidate "
    "with a skill, an employer or a duration the resume does not evidence. "
    "You answer with JSON only, no prose, no markdown fences."
)

RESUME_REVIEW_TEMPLATE = """Read this resume and describe the candidate it belongs to.

Return a JSON object with exactly these keys:
  "headline":        string, two sentences at most, describing who this
                     candidate is in plain words
  "primary_role":    string, the job family this resume points at, e.g.
                     "backend developer", "data engineer", "ai/ml engineer"
  "seniority":       one of "intern", "junior", "mid", "senior", "staff",
                     "lead", "unknown"
  "experience_years": number or null. Use null if the resume never states a
                     duration -- do not estimate one.
  "skills":          array of lowercase strings actually evidenced in the text
  "strengths":       array of strings, at most five, each naming something
                     concrete in the resume
  "improvements":    array of strings, at most five, each a specific fixable
                     weakness in the resume itself
  "suggested_roles": array of strings, at most five job titles worth applying
                     for on this evidence
  "search_queries":  array of 2-4 short job-board search phrases that would
                     surface those roles, e.g. ["python backend developer"]

If the resume is too thin to judge a field, use null or an empty array. An
empty array means "the resume does not say", which is different from "no".

RESUME:
{resume_text}

JSON:"""

CAREER_CHAT_SYSTEM = (
    "You are CareerPilot, a career assistant talking to one candidate about "
    "their own resume. You have their resume below, and sometimes the advert "
    "they are currently looking at. Ground every claim about them in the "
    "resume, and every claim about the role in the advert; say plainly when "
    "neither tells you something rather than guessing. Be direct and "
    "concise: a few short paragraphs or a short list, never an essay. Reply "
    "in plain prose, not JSON, not markdown headings."
)

CAREER_CHAT_TEMPLATE = """THE CANDIDATE'S RESUME:
{resume_context}

THE JOB THEY ARE LOOKING AT:
{job_context}

CONVERSATION SO FAR:
{history}

THE CANDIDATE ASKS:
{message}

Answer them directly. If the answer depends on something the resume does not
say, ask them for it instead of assuming. Only mention the job above if it is
relevant to what they asked - they may be asking about something else
entirely.

ANSWER:"""

ANSWER_COACH_SYSTEM = (
    "You are an interviewer debriefing a candidate on an answer they just "
    "gave in a practice run. Judge only what is in front of you. Do not "
    "praise an answer for something it did not say, and do not invent a "
    "weakness it does not have. Return JSON only, no prose around it."
)

ANSWER_COACH_TEMPLATE = """THE QUESTION THEY WERE ASKED:
{question}

WHAT THE QUESTION IS PROBING FOR:
{expected}

THEIR ANSWER:
{answer}

Score the answer out of 10 and justify the score. Return exactly this JSON:

{{
  "score": 7,
  "verdict": "one short sentence: is this answer ready, or not yet",
  "strengths": ["specific things the answer actually did well"],
  "gaps": ["specific things it left out that the question was asking for"],
  "improved_opening": "one or two sentences showing a stronger way to start"
}}

Rules. "score" must be an integer from 1 to 10. Every item in "strengths" must
quote or paraphrase something genuinely present in their answer; if the answer
is empty or evasive, return an empty array rather than inventing praise. Every
item in "gaps" must be something the question asked for. Keep each item to one
line.

JSON:"""

#: Registry so agents can look a template up by name instead of importing each
#: constant. Values are ``(system_prompt, user_template)`` pairs.
PROMPT_TEMPLATES: Dict[str, Any] = {
    "job_analysis": (JOB_ANALYSIS_SYSTEM, JOB_ANALYSIS_TEMPLATE),
    "skill_extraction": (SKILL_EXTRACTION_SYSTEM, SKILL_EXTRACTION_TEMPLATE),
    "gap_analysis": (GAP_ANALYSIS_SYSTEM, GAP_ANALYSIS_TEMPLATE),
    "resume_review": (RESUME_REVIEW_SYSTEM, RESUME_REVIEW_TEMPLATE),
    "career_chat": (CAREER_CHAT_SYSTEM, CAREER_CHAT_TEMPLATE),
    "answer_coach": (ANSWER_COACH_SYSTEM, ANSWER_COACH_TEMPLATE),
}


def get_prompt_template(name: str):
    """Return a LangChain ``ChatPromptTemplate`` for a registered prompt.

    LangChain is imported lazily: importing ``agents`` should stay fast, and
    tests that never touch an LLM should never pay for the import.
    """
    if name not in PROMPT_TEMPLATES:
        raise KeyError(
            f"Unknown prompt template {name!r}. "
            f"Available: {', '.join(sorted(PROMPT_TEMPLATES))}"
        )

    from langchain_core.prompts import ChatPromptTemplate

    system, user = PROMPT_TEMPLATES[name]
    return ChatPromptTemplate.from_messages(
        [("system", system), ("human", user)]
    )


def render_prompt(name: str, **values: Any) -> str:
    """Fill a template in and return it as a single plain string.

    Useful for text-completion backends (Ollama's ``/api/generate``) which take
    one string rather than a list of chat messages.
    """
    if name not in PROMPT_TEMPLATES:
        raise KeyError(
            f"Unknown prompt template {name!r}. "
            f"Available: {', '.join(sorted(PROMPT_TEMPLATES))}"
        )
    system, user = PROMPT_TEMPLATES[name]
    try:
        body = user.format(**values)
    except KeyError as exc:  # missing placeholder
        raise KeyError(
            f"Prompt {name!r} is missing the value for {exc.args[0]!r}"
        ) from exc
    return f"{system}\n\n{body}"


def parse_json_response(text: str) -> Dict[str, Any]:
    """Pull a JSON object out of a model's reply.

    Small models love to wrap JSON in ``` fences or add a sentence of
    commentary, so we take the outermost ``{...}`` span rather than trusting
    the whole string.
    """
    if not text or not text.strip():
        raise LLMResponseError("Model returned an empty response")

    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMResponseError(
            f"No JSON object found in model response: {cleaned[:200]!r}"
        )

    snippet = cleaned[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            f"Model response was not valid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMResponseError(
            f"Expected a JSON object, got {type(parsed).__name__}"
        )
    return parsed


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class OllamaHandler:
    """Thin wrapper over a local Ollama daemon."""

    name = "ollama"

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_settings()
        self._llm = None
        self._available: Optional[bool] = None
        self._lock = threading.Lock()

    # -- availability ----------------------------------------------------

    def is_available(self, refresh: bool = False) -> bool:
        """Is the daemon reachable? Cached after the first successful probe."""
        if self._available is not None and not refresh:
            return self._available

        with self._lock:
            if self._available is not None and not refresh:
                return self._available
            self._available = self._probe()
            return self._available

    def _probe(self) -> bool:
        try:
            import requests

            response = requests.get(
                self.config.ollama_tags_url,
                timeout=self.config.healthcheck_timeout,
            )
            ok = response.status_code == 200
        except Exception as exc:  # network error, DNS, refused connection...
            logger.info(
                "Ollama not reachable at %s (%s)",
                self.config.base_url,
                exc.__class__.__name__,
            )
            return False

        if ok:
            logger.info("Ollama is available at %s", self.config.base_url)
        else:
            logger.info(
                "Ollama at %s replied with HTTP %s",
                self.config.base_url,
                response.status_code,
            )
        return ok

    def list_models(self) -> List[str]:
        """Names of the models the daemon has pulled. Empty when offline."""
        try:
            import requests

            response = requests.get(
                self.config.ollama_tags_url,
                timeout=self.config.healthcheck_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.info("Could not list Ollama models: %s", exc)
            return []

        models = payload.get("models") or []
        return [m.get("name", "") for m in models if m.get("name")]

    # -- generation ------------------------------------------------------

    def _get_llm(self):
        """Build the LangChain ``Ollama`` runnable once, on first use."""
        if self._llm is not None:
            return self._llm

        with self._lock:
            if self._llm is not None:
                return self._llm

            from langchain_community.llms import Ollama

            self._llm = Ollama(
                base_url=self.config.base_url,
                model=self.config.model,
                temperature=self.config.temperature,
                num_predict=self.config.max_tokens,
                timeout=self.config.timeout,
            )
            return self._llm

    def generate(self, prompt: str) -> str:
        """Send one prompt, return the raw text reply."""
        if not self.is_available():
            raise LLMUnavailableError(
                f"Ollama is not reachable at {self.config.base_url}. "
                f"Start it with `ollama serve` and pull a model with "
                f"`ollama pull {self.config.model}`."
            )
        try:
            return self._get_llm().invoke(prompt)
        except Exception as exc:
            # A failure here may mean the daemon died mid-flight, so drop the
            # cached "available" answer and let the next call re-probe.
            self._available = None
            raise LLMError(f"Ollama generation failed: {exc}") from exc


class ClaudeHandler:
    """Fallback backend using Anthropic's hosted API.

    The ``anthropic`` package is an optional dependency. If it is not
    installed, or no API key is configured, this handler simply reports itself
    unavailable and the caller degrades further.
    """

    name = "claude"

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_settings()
        self._llm = None
        self._lock = threading.Lock()

    def is_available(self, refresh: bool = False) -> bool:
        """True only when a key is configured *and* the SDK is importable."""
        if not self.config.has_claude_credentials:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            logger.info(
                "Claude fallback configured but the `anthropic` package is "
                "not installed (pip install anthropic)"
            )
            return False
        return True

    def _get_llm(self):
        if self._llm is not None:
            return self._llm

        with self._lock:
            if self._llm is not None:
                return self._llm

            import anthropic

            self._llm = anthropic.Anthropic(
                api_key=self.config.claude_api_key,
                timeout=float(self.config.timeout),
            )
            return self._llm

    def generate(self, prompt: str) -> str:
        if not self.is_available():
            raise LLMUnavailableError(
                "Claude fallback is not usable: set ANTHROPIC_API_KEY and "
                "install the `anthropic` package."
            )
        try:
            message = self._get_llm().messages.create(
                model=self.config.claude_model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = [
                block.text
                for block in message.content
                if getattr(block, "type", None) == "text"
            ]
            return "".join(parts)
        except Exception as exc:
            raise LLMError(f"Claude generation failed: {exc}") from exc


class GeminiHandler:
    """Hosted backend using Google's Gemini REST API.

    Same contract as :class:`ClaudeHandler`: optional key, reports itself
    unavailable rather than raising when it is missing.

    **Why plain HTTP and not the SDK.** Installing ``google-genai`` upgrades
    ``httpx`` to 2.0-era versions, and Starlette 0.35 -- the version FastAPI
    0.109 pins -- builds its test client on the ``httpx.Client(app=...)``
    argument that those versions removed. The SDK install turned 9 passing
    tests red without touching a line of application code. The SDK also warns
    that it no longer supports Python 3.9, which is the only interpreter this
    project has.

    What is actually needed here is one POST returning one string. ``requests``
    is already a dependency, the endpoint is stable, and nothing in the
    dependency tree moves.
    """

    name = "gemini"
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
    )

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_settings()

    def is_available(self, refresh: bool = False) -> bool:
        """True when a key is configured. No network call is made."""
        return self.config.has_gemini_credentials

    def generate(self, prompt: str) -> str:
        if not self.is_available():
            raise LLMUnavailableError(
                "Gemini is not usable: set GEMINI_API_KEY in backend/.env."
            )

        url = self.endpoint % self.config.gemini_model
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            },
        }

        try:
            # The key travels in a header, not as `?key=`. Query strings end up
            # in proxy logs, browser history and error reports; headers do not.
            response = requests.post(
                url,
                json=payload,
                headers={"x-goog-api-key": str(self.config.gemini_api_key or "")},
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError("Gemini request failed: %s" % exc) from exc

        if response.status_code == 429:
            raise LLMError("Gemini rate limit reached (429); free tier is per-minute")
        if response.status_code in (401, 403):
            # Not retryable: a rejected key stays rejected. Raised as
            # "unavailable" so the router stops rather than trying twice more.
            raise LLMUnavailableError(
                "Gemini rejected the API key (HTTP %d). Check GEMINI_API_KEY "
                "in backend/.env." % response.status_code
            )
        if response.status_code >= 400:
            raise LLMError(
                "Gemini returned HTTP %d: %s"
                % (response.status_code, _first_line(response.text))
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("Gemini returned a non-JSON body") from exc

        text = _gemini_text(body)
        if not text.strip():
            # An empty answer means it stopped for a reason other than
            # finishing -- a safety filter, or the token cap hit mid-word.
            # Treated as an error so the router retries and then falls back,
            # rather than handing an agent an empty string to parse.
            raise LLMError("Gemini returned no text (%s)" % _gemini_stop_reason(body))
        return text


def _gemini_text(body: Dict[str, Any]) -> str:
    """Join the text parts of the first candidate.

    A response can carry several parts, and concatenating them is the
    documented way to rebuild the answer. Taking ``parts[0]`` silently
    truncates any reply that came back split.
    """
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))


def _gemini_stop_reason(body: Dict[str, Any]) -> str:
    """Best-effort description of why a response came back empty."""
    candidates = body.get("candidates") or []
    if candidates and (candidates[0] or {}).get("finishReason"):
        return str(candidates[0]["finishReason"])
    blocked = (body.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        return "prompt blocked: %s" % blocked
    return "no finish reason given"


def _first_line(text: str, limit: int = 300) -> str:
    """Collapse an error body to one loggable line.

    Not ``splitlines()[0]``: Google's error bodies are pretty-printed JSON
    beginning with a lone ``{``, so taking the first line reported literally
    "{" and hid the actual message.
    """
    return " ".join(str(text or "").split())[:limit]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMClient:
    """Picks a backend, retries transient failures, and gives up politely.

    This is the only class the agents talk to. Both handlers are injectable so
    tests can supply fakes and stay offline.
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        ollama: Optional[Any] = None,
        claude: Optional[Any] = None,
        gemini: Optional[Any] = None,
    ) -> None:
        self.config = config or AgentConfig.from_settings()
        self.ollama = ollama if ollama is not None else OllamaHandler(self.config)
        self.claude = claude if claude is not None else ClaudeHandler(self.config)
        self.gemini = gemini if gemini is not None else GeminiHandler(self.config)
        #: Name of the backend that answered the most recent call.
        self.last_backend: Optional[str] = None

    def _hosted(self) -> List[Any]:
        """The hosted APIs, cheapest first.

        Gemini leads because its free tier makes running this without a bill
        possible. Both are listed regardless of whether a key is set: an
        unconfigured handler reports itself unavailable and is skipped, so
        ordering costs nothing.
        """
        return [self.gemini, self.claude]

    def _candidates(self) -> List[Any]:
        """Backends to try, in order, for the configured provider."""
        if self.config.provider is LLMProvider.OLLAMA:
            order = [self.ollama]
            if self.config.fallback_enabled:
                order.extend(self._hosted())
            return order
        if self.config.provider is LLMProvider.CLAUDE:
            return [self.claude]
        if self.config.provider is LLMProvider.GEMINI:
            return [self.gemini]
        return [self.ollama] + self._hosted()  # AUTO

    def available_backend(self) -> Optional[str]:
        """Name of the first usable backend, or ``None`` if there is none."""
        for handler in self._candidates():
            if handler.is_available():
                return handler.name
        return None

    def is_available(self) -> bool:
        return self.available_backend() is not None

    def generate(self, prompt: str) -> str:
        """Run a prompt against the first backend that works.

        Raises :class:`LLMUnavailableError` when every backend is down, which
        agents treat as "use the deterministic path".
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")

        errors: List[str] = []
        for handler in self._candidates():
            if not handler.is_available():
                errors.append(f"{handler.name}: unavailable")
                continue

            attempts = self.config.max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    text = handler.generate(prompt)
                    self.last_backend = handler.name
                    return text
                except LLMUnavailableError as exc:
                    errors.append(f"{handler.name}: {exc}")
                    break  # no point retrying a backend that is down
                except LLMError as exc:
                    errors.append(f"{handler.name} attempt {attempt}: {exc}")
                    if attempt < attempts:
                        # Linear backoff: these are local calls, not a busy API.
                        time.sleep(0.25 * attempt)
                    else:
                        logger.warning(
                            "Backend %s failed %d time(s); moving on",
                            handler.name,
                            attempts,
                        )

        raise LLMUnavailableError(
            "No LLM backend could answer. Tried -> " + "; ".join(errors)
        )

    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """Generate and parse a JSON object in one step."""
        return parse_json_response(self.generate(prompt))

    def describe(self) -> Dict[str, Any]:
        """Log-safe snapshot of the routing decision."""
        info = self.config.describe()
        info["active_backend"] = self.available_backend()
        return info


#: Shared client. Cheap to import; probes nothing until first used.
llm_client = LLMClient()
