"""The conversational front end: answer questions about one person's resume.

Everything else in this package runs once and returns a report. This module
holds a conversation, which introduces the one failure mode the rest of the
codebase does not have: a chat box *looks* intelligent whether or not anything
intelligent is behind it. An empty text field invites the user to ask anything,
and a keyword matcher will happily answer the 5% it recognises and bluff the
rest.

So the contract here is explicit. Every reply carries a ``source``:

* ``"llm"``      - a model wrote it.
* ``"fallback"`` - no model is configured; a rule matched the question and
  answered it from facts already extracted from the resume.

and when no rule matches, the fallback says so plainly instead of
improvising. The UI is expected to surface ``source`` rather than hide it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents import AgentConfig
from agents.ollama_handler import (
    LLMClient,
    LLMError,
    LLMUnavailableError,
    render_prompt,
)
from utils.logger import get_logger

logger = get_logger(__name__)

#: Turns of conversation replayed into the prompt. Enough for the model to
#: follow a thread, short enough that a long session does not crowd the resume
#: out of the context window.
MAX_HISTORY_TURNS = 8

#: Longest question accepted. Anything larger is a pasted document, and there
#: is a separate endpoint for those.
MAX_MESSAGE_CHARS = 2000

MAX_CONTEXT_CHARS = 8000

#: The advert gets a much smaller share of the prompt than the resume. The
#: resume is the thing the assistant must not get wrong about the user; the
#: advert only needs to be recognisable, and adverts pad heavily with company
#: boilerplate that would otherwise crowd out the resume.
MAX_JOB_CONTEXT_CHARS = 3000

#: Shown whenever a rule wrote the answer, so the user is never left thinking
#: a model did.
FALLBACK_NOTE = (
    "No language model is configured, so this answer was assembled from your "
    "resume by fixed rules rather than written by an AI."
)

_NO_RESUME = (
    "I have not got your resume yet, so there is nothing for me to read. "
    "Upload it on the Settings page and ask me again."
)

#: ``(intent, trigger words)``. Order matters: the first intent whose trigger
#: appears in the question wins, so the specific ones come before the general.
_INTENTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("interview", (
        "interview", "prepare", "preparation", "question they", "asked",
    )),
    ("improve", (
        "improve", "better", "weak", "weakness", "missing", "lacking",
        "should i learn", "what to learn", "gap",
    )),
    ("roles", (
        "role", "job", "apply", "position", "vacancy", "opening", "hiring",
        "which company", "what can i do",
    )),
    ("skills", ("skill", "technology", "tech stack", "know", "good at")),
    ("experience", ("experience", "years", "seniority", "senior", "level")),
    ("summary", (
        "summar", "about me", "tell me about", "who am i", "describe",
        "overview", "profile", "my cv", "my resume",
    )),
    ("greeting", ("hello", "hi ", "hey", "good morning", "good evening")),
)

#: Offered under the reply as one-tap follow-ups. Deliberately questions the
#: fallback can actually answer, so the suggestions do not lead somewhere the
#: rules cannot go.
DEFAULT_SUGGESTIONS = (
    "Summarise my resume",
    "What roles should I apply for?",
    "What is weak in my CV?",
    "How should I prepare for an interview?",
)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _listed(items: Sequence[str], limit: int = 12) -> str:
    """Render a list the way a person would say it out loud."""
    chosen = [str(i) for i in items[:limit]]
    if not chosen:
        return ""
    if len(chosen) == 1:
        return chosen[0]
    return "%s and %s" % (", ".join(chosen[:-1]), chosen[-1])


def format_history(history: Sequence[Dict[str, Any]]) -> str:
    """Flatten prior turns into the transcript the prompt template expects."""
    recent = list(history)[-MAX_HISTORY_TURNS * 2:]
    lines: List[str] = []
    for turn in recent:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        content = _clip(str(turn.get("content") or ""), MAX_MESSAGE_CHARS)
        if not content:
            continue
        speaker = "Candidate" if role == "user" else "CareerPilot"
        lines.append("%s: %s" % (speaker, content))
    return "\n".join(lines) or "(this is the first message)"


def classify(message: str) -> str:
    """Name the intent behind a question, or ``"unknown"``.

    Substring matching, not tokenising: the triggers are phrases as often as
    words, and the fallback's job is to recognise the common questions well
    rather than every question badly.
    """
    lowered = " %s " % (message or "").strip().lower()
    for intent, triggers in _INTENTS:
        if any(trigger in lowered for trigger in triggers):
            return intent
    return "unknown"


class CareerChatAgent:
    """Answer questions about a resume, with or without a model behind it."""

    name = "career_chat"

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self.config = config or AgentConfig.from_settings()
        # Injectable so tests can pass a fake and stay offline.
        self._llm = llm

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.config)
        return self._llm

    def reply(
        self,
        message: str,
        resume_context: str = "",
        history: Optional[Sequence[Dict[str, Any]]] = None,
        profile: Optional[Dict[str, Any]] = None,
        job_context: str = "",
    ) -> Dict[str, Any]:
        """Answer one question. Never raises for a model that is simply absent.

        ``job_context`` is the advert the user currently has open, if any. It
        is what turns "how do I answer this?" into an answer about the role in
        front of them rather than a general one, and it is optional because
        the assistant has to keep working before a job has been picked.
        """
        message = _clip(message, MAX_MESSAGE_CHARS)
        history = history or []

        if not message:
            return {
                "reply": "Ask me anything about your resume.",
                "source": "fallback",
                "backend": None,
                "warning": None,
                "suggestions": list(DEFAULT_SUGGESTIONS),
            }

        warning: Optional[str] = None
        try:
            prompt = render_prompt(
                "career_chat",
                resume_context=_clip(resume_context, MAX_CONTEXT_CHARS)
                or "(no resume has been uploaded yet)",
                job_context=_clip(job_context, MAX_JOB_CONTEXT_CHARS)
                or "(they have not picked a job yet)",
                history=format_history(history),
                message=message,
            )
            answer = (self.llm.generate(prompt) or "").strip()
            if answer:
                return {
                    "reply": answer,
                    "source": "llm",
                    "backend": self.llm.last_backend,
                    "warning": None,
                    "suggestions": list(DEFAULT_SUGGESTIONS),
                }
            warning = "the model returned an empty answer, used fallback"
        except LLMUnavailableError as exc:
            warning = "no LLM available, used fallback (%s)" % exc
            logger.info("Chat: %s", warning)
        except LLMError as exc:
            warning = "LLM call failed, used fallback (%s)" % exc
            logger.warning("Chat: %s", warning)
        except Exception as exc:  # defensive: chat must not 500 on a bad reply
            warning = "unexpected LLM error, used fallback (%s)" % exc
            logger.warning("Chat: %s", warning, exc_info=True)

        return {
            "reply": self._scripted(message, resume_context, profile or {}),
            "source": "fallback",
            "backend": None,
            "warning": warning,
            "suggestions": list(DEFAULT_SUGGESTIONS),
        }

    # -- the no-model path -------------------------------------------------

    def _scripted(
        self,
        message: str,
        resume_context: str,
        profile: Dict[str, Any],
    ) -> str:
        """Answer from facts already extracted, or admit the question is out of range."""
        if not resume_context.strip() and not profile:
            return _NO_RESUME

        intent = classify(message)
        body = self._answer_for(intent, profile)
        return "%s\n\n(%s)" % (body, FALLBACK_NOTE)

    def _answer_for(self, intent: str, profile: Dict[str, Any]) -> str:
        skills = [str(s) for s in profile.get("skills") or []]
        role = str(profile.get("primary_role") or "unknown")
        seniority = str(profile.get("seniority") or "unknown")
        years = profile.get("experience_years")
        roles = [str(r) for r in profile.get("suggested_roles") or []]
        improvements = [str(i) for i in profile.get("improvements") or []]

        if intent == "greeting":
            return (
                "Hello. I can read what is on your resume and tell you what it "
                "says. Try one of the suggestions below."
            )

        if intent == "summary":
            headline = str(profile.get("headline") or "").strip()
            return headline or (
                "I could not find enough on your resume to summarise it yet."
            )

        if intent == "skills":
            if not skills:
                return (
                    "Your resume does not name any technology I recognise. "
                    "Add a skills section listing the languages, frameworks "
                    "and databases you have used."
                )
            return "Your resume evidences %d skills: %s." % (
                len(skills), _listed(skills, 20),
            )

        if intent == "experience":
            if years is None:
                return (
                    "Your resume never states a number of years, so I cannot "
                    "tell you one - I am not going to estimate it. It reads "
                    "as a %s role. Adding a line like \"4 years of "
                    "experience\" would fix this, and would also get you past "
                    "the filters that search for exactly that phrase." % role
                )
            return (
                "Your resume states %g years of experience, which puts it in "
                "the %s band for a %s." % (years, seniority, role)
            )

        if intent == "roles":
            if not roles:
                return (
                    "Your resume does not cluster into a job family I "
                    "recognise yet, so I cannot suggest titles honestly. Name "
                    "more of the tools you have used and ask me again."
                )
            return (
                "On this evidence, look for: %s. The Discover Jobs page will "
                "search those for you and link straight to each posting."
                % _listed(roles)
            )

        if intent == "improve":
            if not improvements:
                return (
                    "I did not find anything obviously missing from the "
                    "document itself."
                )
            return "Fix these first:\n- %s" % "\n- ".join(improvements)

        if intent == "interview":
            return (
                "Open the Interview Prep page. It builds questions from your "
                "own resume, weighted towards the areas an interviewer is "
                "most likely to push on, and it will use a job advert too if "
                "you paste one in."
            )

        return (
            "I cannot answer that one. Without a language model configured I "
            "can only report what was extracted from your resume: your "
            "skills, your stated experience, the roles it points at, and what "
            "is missing from the document. Ask me one of those, or add an "
            "ANTHROPIC_API_KEY to backend/.env and restart to get real "
            "conversation."
        )


#: Shared instance. Holds no per-request state; the transcript arrives with
#: each call rather than being kept on the server.
career_chat = CareerChatAgent()
