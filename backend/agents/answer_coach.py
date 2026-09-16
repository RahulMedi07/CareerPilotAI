"""Give a candidate feedback on a practice interview answer.

The obvious way to build this is to return a number out of ten. Resist that
unless a model is actually reading the answer, because a score is the single
most persuasive thing you can put on a screen and the cheapest thing to fake.
A keyword counter dressed up as "7/10" tells the candidate they are nearly
ready, on evidence that amounts to string matching.

So there are two modes and they are not the same shape:

* **A model is configured.** It reads the answer and returns a score out of
  ten with its reasoning. ``source`` is ``"llm"``.
* **No model is configured.** ``score`` is ``None`` and stays ``None``. What
  comes back instead is a set of *checkable observations*: which of the things
  the question was probing for appear in the answer and which do not, whether
  the answer contains a concrete number, whether it is written in the first
  person, and how long it is. Every one of those is a fact the candidate can
  verify by re-reading their own words. None of them is a judgement.

The difference matters most when the answer is bad. A fabricated 4/10 and a
fabricated 8/10 are equally worthless, but the 8 is the one that stops someone
preparing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from agents import AgentConfig
from agents.ollama_handler import (
    LLMClient,
    LLMError,
    LLMUnavailableError,
    parse_json_response,
    render_prompt,
)
from utils.logger import get_logger
from utils.skills import find_skills

logger = get_logger(__name__)

#: Longest practice answer accepted. Past this it is a document, not an answer
#: anyone would give out loud.
MAX_ANSWER_CHARS = 6000

MAX_QUESTION_CHARS = 1000

#: Below this an answer is too short to say anything useful about. Roughly two
#: spoken sentences.
MIN_USEFUL_WORDS = 20

#: An answer this long stops being an answer and becomes a monologue. Chosen
#: from the usual advice that a competency answer should run about two minutes,
#: and people speak around 130 words a minute.
LONG_ANSWER_WORDS = 280

#: Said on every fallback response, and repeated inside ``feedback`` so it
#: survives a UI that only renders one field.
NO_MODEL_NOTE = (
    "No language model is configured, so nobody scored this answer. What "
    "follows is a list of things that are or are not present in what you "
    "wrote - not an opinion on how good it was."
)

#: Said when a model *is* configured but the call did not come back. Kept
#: separate from ``NO_MODEL_NOTE`` because the two need different actions:
#: one is a missing setting, the other is usually the free-tier daily quota,
#: and telling someone their key is missing when it is merely spent sends
#: them to fix the wrong thing.
MODEL_FAILED_NOTE = (
    "The language model could not be reached, so nobody scored this answer. "
    "This is often the free tier's daily limit - the backend log will say "
    "429 if so. What follows is a list of things that are or are not present "
    "in what you wrote, not an opinion on how good it was."
)

#: Digits attached to something measurable. ``2019`` on its own is a year, not
#: a result, so a bare four-digit number is not enough.
_METRIC_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|x\b|ms\b|s\b|k\b|m\b|bn\b|users?\b|"
    r"requests?\b|hours?\b|days?\b|weeks?\b|months?\b)",
    re.IGNORECASE,
)

_FIRST_PERSON_RE = re.compile(r"\b(i|i'?ve|i'?d|i'?m|my|mine)\b", re.IGNORECASE)
_TEAM_VOICE_RE = re.compile(r"\b(we|we'?ve|we'?re|our|ours|us)\b", re.IGNORECASE)

#: Hedges that turn a claim into a non-claim. An interviewer hears these.
_HEDGES = (
    "sort of",
    "kind of",
    "i guess",
    "maybe",
    "probably",
    "i think maybe",
    "or something",
    "stuff like that",
    "and so on",
)


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def expected_terms(question: str, skill: str, extra: Sequence[str] = ()) -> List[str]:
    """Work out what the question was fishing for.

    Deliberately conservative: the named ``skill`` plus any technology the
    question itself mentions. Guessing wider would produce "gaps" the question
    never asked about, which is worse than saying nothing.
    """
    terms: List[str] = []
    for candidate in [skill, *extra]:
        cleaned = (candidate or "").strip().lower()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)

    for found in find_skills(question or ""):
        if found not in terms:
            terms.append(found)

    return terms


def coverage(answer: str, terms: Sequence[str]) -> Dict[str, List[str]]:
    """Split ``terms`` into those the answer mentions and those it does not."""
    lowered = (answer or "").lower()
    covered: List[str] = []
    missing: List[str] = []

    for term in terms:
        if not term:
            continue
        # Word-boundary match so "go" does not match "going" and "r" does not
        # match every word in the answer.
        pattern = r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term)
        (covered if re.search(pattern, lowered) else missing).append(term)

    return {"covered": covered, "missing": missing}


def observations(answer: str, terms: Sequence[str]) -> List[str]:
    """Checkable statements about an answer. No opinions, no score."""
    notes: List[str] = []
    words = _words(answer)
    count = len(words)

    if count < MIN_USEFUL_WORDS:
        notes.append(
            "That is %d words. Spoken aloud it lasts a few seconds, which "
            "usually reads as having nothing to say." % count
        )
    elif count > LONG_ANSWER_WORDS:
        notes.append(
            "That is %d words, roughly %d minutes spoken. Interviewers tend to "
            "stop listening before the end." % (count, max(1, round(count / 130)))
        )
    else:
        notes.append("That is %d words, which is about the right length spoken." % count)

    if _METRIC_RE.search(answer or ""):
        notes.append("It contains a concrete number, which is what makes a claim checkable.")
    else:
        notes.append(
            "It contains no measurable result. Answers that name a number are "
            "harder to wave away than answers that do not."
        )

    has_i = bool(_FIRST_PERSON_RE.search(answer or ""))
    has_we = bool(_TEAM_VOICE_RE.search(answer or ""))
    if has_we and not has_i:
        notes.append(
            "It is written entirely as 'we'. The interviewer is trying to work "
            "out what you personally did."
        )

    found_hedges = [h for h in _HEDGES if h in (answer or "").lower()]
    if found_hedges:
        notes.append(
            "It hedges: %s. Each one weakens the claim it is attached to."
            % ", ".join('"%s"' % h for h in found_hedges)
        )

    split = coverage(answer, terms)
    if split["covered"]:
        notes.append("It mentions %s." % ", ".join(split["covered"]))
    if split["missing"]:
        notes.append(
            "It never mentions %s, which is what the question was asking about."
            % ", ".join(split["missing"])
        )

    return notes


class AnswerCoachAgent:
    """Feedback on one practice answer, scored only when a model reads it."""

    name = "answer_coach"
    prompt_name = "answer_coach"

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        # from_settings(), not AgentConfig(): the bare constructor takes
        # dataclass defaults and never reads .env, so this agent ignored the
        # configured provider and key and fell back on every call.
        self.config = config or AgentConfig.from_settings()
        self._client: Optional[LLMClient] = None

    @property
    def client(self) -> LLMClient:
        if self._client is None:
            self._client = LLMClient(self.config)
        return self._client

    def evaluate(
        self,
        question: str,
        answer: str,
        skill: str = "",
        expected: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Return feedback on ``answer``.

        ``score`` is an integer 1-10 only on the model path. On the fallback
        path it is ``None`` and the caller must render that as "not scored",
        never as zero.
        """
        question = (question or "").strip()[:MAX_QUESTION_CHARS]
        answer = (answer or "").strip()[:MAX_ANSWER_CHARS]
        terms = expected_terms(question, skill, expected or ())

        if not answer:
            return {
                "score": None,
                "verdict": "There is nothing here to look at yet.",
                "strengths": [],
                "gaps": [],
                "observations": [],
                "covered": [],
                "missing": terms,
                "improved_opening": "",
                "source": "fallback",
                "backend": "none",
                "note": "Write an answer first, then ask for feedback on it.",
            }

        try:
            raw = self.client.generate(
                render_prompt(
                    self.prompt_name,
                    question=question or "(not supplied)",
                    expected=", ".join(terms) or "(nothing specific)",
                    answer=answer,
                )
            )
            parsed = parse_json_response(raw)
            if isinstance(parsed, dict):
                return self._from_model(parsed, terms, answer)
            logger.warning("answer_coach: model returned no usable JSON")
        except LLMUnavailableError as exc:
            # This covers two different situations: no key at all, and a key
            # whose every attempt failed. Saying "not configured" for both sent
            # a real quota exhaustion looking like a missing setting, so the
            # reason is logged and carried into the note the user reads.
            if self.client.available_backend() is None:
                logger.info("answer_coach: no model configured, observations only")
            else:
                logger.warning("answer_coach: model unreachable (%s)", exc)
                return self._fallback(terms, answer, reachable=False)
        except LLMError as exc:
            logger.warning("answer_coach: model call failed (%s)", exc)
            return self._fallback(terms, answer, reachable=False)
        except Exception as exc:  # noqa: BLE001 - never fail a practice run
            logger.warning("answer_coach: unexpected failure (%s)", exc)

        return self._fallback(terms, answer)

    def _from_model(
        self, parsed: Dict[str, Any], terms: Sequence[str], answer: str
    ) -> Dict[str, Any]:
        """Normalise the model's reply, clamping the score into 1-10.

        A model that returns 0, 11 or "eight" gets its score dropped rather
        than coerced, because a wrong number here is worse than no number.
        """
        score: Optional[int] = None
        raw_score = parsed.get("score")
        if isinstance(raw_score, bool):
            raw_score = None
        if isinstance(raw_score, (int, float)):
            rounded = int(round(raw_score))
            if 1 <= rounded <= 10:
                score = rounded

        def strings(key: str) -> List[str]:
            value = parsed.get(key)
            if not isinstance(value, list):
                return []
            return [str(v).strip() for v in value if str(v).strip()][:6]

        split = coverage(answer, terms)
        return {
            "score": score,
            "verdict": str(parsed.get("verdict") or "").strip(),
            "strengths": strings("strengths"),
            "gaps": strings("gaps"),
            "observations": observations(answer, terms),
            "covered": split["covered"],
            "missing": split["missing"],
            "improved_opening": str(parsed.get("improved_opening") or "").strip(),
            "source": "llm",
            "backend": self.client.available_backend() or "llm",
            "note": "",
        }

    def _fallback(
        self, terms: Sequence[str], answer: str, reachable: bool = True
    ) -> Dict[str, Any]:
        split = coverage(answer, terms)
        return {
            "score": None,
            "verdict": "",
            "strengths": [],
            "gaps": [],
            "observations": observations(answer, terms),
            "covered": split["covered"],
            "missing": split["missing"],
            "improved_opening": "",
            "source": "fallback",
            "backend": "none",
            "note": NO_MODEL_NOTE if reachable else MODEL_FAILED_NOTE,
        }


#: Module-level singleton, matching the other agents in this package.
answer_coach = AnswerCoachAgent()
