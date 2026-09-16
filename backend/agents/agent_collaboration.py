"""One agent asking another a question, with the exchange written down.

The brief describes this as "agents can now ask each other questions". It is
worth being exact about what that means here, because the phrase suggests
something this is not.

These are **structured delegations with a recorded transcript**, not a
negotiation between autonomous parties. ``ask_gap_detector`` does not send
prose to a language model and hope for a useful reply; it calls the gap
detector with the right inputs and records the question that prompted it, the
inputs it was given and the shape of what came back. Describing that as a
conversation would be dressing a function call in costume.

What the layer genuinely buys, and why it is worth having:

* **The question is recorded, so the reasoning is auditable.** The trace stops
  reading "detect_gaps ran, 3 gaps" and starts reading "match came back at
  65%, so the gap detector was asked what the biggest gaps were; it named 3,
  17 days of study between them". When an answer looks wrong, that is the
  difference between seeing *what* ran and seeing *why*.
* **The wiring lives in one place.** Every caller previously had to know that
  the gap detector wants ``resume_data`` shaped one way and the optimiser
  another. Getting that wrong is silent - the optimiser without gap data will
  cheerfully suggest claiming skills the candidate does not have.
* **Failures are contained and visible.** An agent that raises produces an
  exchange marked ``failed`` with the reason, and the caller gets an empty
  result rather than an exception.

Every exchange is appended to :attr:`AgentCollaboration.transcript` and is
rendered into the workflow's execution trace.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from agents.gap_detector import CRITICAL, gap_detector
from agents.interview_prep import interview_prep_agent
from agents.learning_path_agent import learning_path_agent
from agents.resume_optimizer import resume_optimizer
from utils.logger import get_logger

logger = get_logger(__name__)

ASKED_OK = "answered"
ASKED_FAILED = "failed"

#: Who is on each end of an exchange. The asker is the orchestrator in every
#: case; naming it explicitly keeps the transcript readable when it is printed
#: on its own, away from the workflow that produced it.
ORCHESTRATOR = "Workflow"


class AgentCollaboration:
    """Routes questions to agents and keeps the transcript.

    Agents are injectable so tests can substitute stubs without constructing
    the real ones.
    """

    def __init__(
        self,
        gaps_agent: Any = None,
        optimizer: Any = None,
        interview: Any = None,
        learning: Any = None,
    ) -> None:
        self.gaps_agent = gaps_agent if gaps_agent is not None else gap_detector
        self.optimizer = optimizer if optimizer is not None else resume_optimizer
        self.interview = (
            interview if interview is not None else interview_prep_agent
        )
        self.learning = learning if learning is not None else learning_path_agent
        self.transcript: List[Dict[str, Any]] = []

    # -- Transcript -------------------------------------------------------

    def _record(
        self,
        agent: str,
        question: str,
        answer: str,
        status: str = ASKED_OK,
        duration_ms: float = 0.0,
        **extra: Any,
    ) -> Dict[str, Any]:
        exchange = {
            "step": len(self.transcript) + 1,
            "from": ORCHESTRATOR,
            "to": agent,
            "question": question,
            "answer": answer,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        }
        exchange.update(extra)
        self.transcript.append(exchange)
        logger.info("%s -> %s: %s", ORCHESTRATOR, agent, question)
        return exchange

    def clear(self) -> None:
        """Forget the transcript. Used between runs of a reused instance."""
        self.transcript = []

    def _failed(
        self, agent: str, question: str, exc: Exception, started: float
    ) -> None:
        logger.warning("%s could not answer: %s", agent, exc, exc_info=True)
        self._record(
            agent,
            question,
            "Could not answer: %s: %s" % (exc.__class__.__name__, exc),
            status=ASKED_FAILED,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            error=str(exc),
        )

    # -- Questions --------------------------------------------------------

    def ask_gap_detector(
        self,
        match_result: Optional[Dict[str, Any]],
        resume_data: Optional[Dict[str, Any]],
        job_analysis: Optional[Dict[str, Any]],
        job_text: str = "",
    ) -> Dict[str, Any]:
        """"The match came back at 65%. What are the biggest gaps?"

        Returns the detector's full report, or ``{}`` if it could not answer.
        """
        score = float((match_result or {}).get("overall_match") or 0.0)
        question = (
            "Match is %.0f%%. What are the biggest gaps, and how long would "
            "each take to close?" % score
        )
        started = time.perf_counter()
        try:
            report = self.gaps_agent.detect_gaps(
                resume_data or {},
                job_analysis or {},
                match_result,
                job_text=job_text,
            )
        except Exception as exc:  # noqa: BLE001 - one agent must not sink the run
            self._failed("Gap Detector", question, exc, started)
            return {}

        report = report or {}
        critical = int(report.get("critical_count") or 0)
        days = int(report.get("blocking_learning_days") or 0)
        self._record(
            "Gap Detector",
            question,
            (
                "%d critical gap(s): %s. About %d day(s) of study to close "
                "them." % (critical, self._list(report), days)
                if critical
                else "No critical gap: nothing required is completely "
                "unevidenced."
            ),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            critical_gaps=critical,
            blocking_learning_days=days,
        )
        return report

    def ask_resume_optimizer(
        self,
        gaps: Optional[Dict[str, Any]],
        job_analysis: Optional[Dict[str, Any]],
        resume_data: Optional[Dict[str, Any]],
        match_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """"Given these gaps, how do I improve my resume for THIS job?"

        The gaps go in deliberately. Without them the optimiser has no list of
        skills the candidate cannot claim, and its suggestions stop being
        safe to follow.
        """
        critical = int((gaps or {}).get("critical_count") or 0)
        question = (
            "Given %d critical gap(s), how should this resume change for this "
            "advert - without claiming anything untrue?" % critical
        )
        started = time.perf_counter()
        try:
            report = self.optimizer.optimize_resume(
                resume_data or {},
                job_analysis or {},
                gaps,
                match_result,
            )
        except Exception as exc:  # noqa: BLE001
            self._failed("Resume Optimizer", question, exc, started)
            return {}

        report = report or {}
        improvements = len(report.get("improvements") or [])
        blocked = list(report.get("keywords_blocked_by_gaps") or [])
        self._record(
            "Resume Optimizer",
            question,
            "%d suggestion(s), %d high impact.%s"
            % (
                improvements,
                int(report.get("high_impact_count") or 0),
                (
                    " Refused to add %s - those are gaps, not phrasing."
                    % ", ".join(blocked)
                    if blocked
                    else ""
                ),
            ),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            improvements=improvements,
            blocked_keywords=blocked,
        )
        return report

    def ask_interview_prep(
        self,
        gaps: Optional[Dict[str, Any]],
        match_result: Optional[Dict[str, Any]],
        job_analysis: Optional[Dict[str, Any]] = None,
        resume_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """"Given this match and these gaps, prepare me for the interview." """
        score = float((match_result or {}).get("overall_match") or 0.0)
        critical = int((gaps or {}).get("critical_count") or 0)
        question = (
            "Match %.0f%% with %d critical gap(s). What will they ask, and "
            "what should I do about the gaps?" % (score, critical)
        )
        started = time.perf_counter()
        try:
            prep = self.interview.prepare_interview(
                job_analysis or {},
                resume_data or {},
                gaps,
                match_result,
            )
        except Exception as exc:  # noqa: BLE001
            self._failed("Interview Prep", question, exc, started)
            return {}

        prep = prep or {}
        self._record(
            "Interview Prep",
            question,
            "%d question(s), %d of them about the gaps. Difficulty looks %s."
            % (
                int(prep.get("question_count") or 0),
                int(prep.get("gap_question_count") or 0),
                str(prep.get("interview_difficulty") or "unknown").lower(),
            ),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            question_count=int(prep.get("question_count") or 0),
            gap_questions=int(prep.get("gap_question_count") or 0),
        )
        return prep

    def ask_learning_path_agent(
        self,
        gaps: Any,
        available_time_days: int = 14,
    ) -> Dict[str, Any]:
        """"I have 14 days. What should I learn from these gaps?"

        ``gaps`` may be the detector's whole report or a bare list of gap
        dicts; both turn up in practice and neither is worth making the caller
        unpack.
        """
        items = self._gap_list(gaps)
        question = (
            "I have %d day(s). What can I realistically learn from these %d "
            "gap(s)?" % (available_time_days, len(items))
        )
        started = time.perf_counter()
        try:
            plan = self.learning.create_learning_path(items, available_time_days)
        except Exception as exc:  # noqa: BLE001
            self._failed("Learning Path", question, exc, started)
            return {}

        plan = plan or {}
        self._record(
            "Learning Path",
            question,
            (
                plan.get("summary")
                or "No plan: %s" % plan.get("reason", "unknown")
            ),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            fits=bool(plan.get("fits")),
            planned_days=int(plan.get("total_days") or 0),
        )
        return plan

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _gap_list(gaps: Any) -> List[Dict[str, Any]]:
        """Accept a report or a list; return the gap dicts worth planning."""
        if isinstance(gaps, dict):
            items = list(gaps.get("critical_gaps") or [])
            if not items:
                items = [
                    gap
                    for gap in (gaps.get("nice_to_have_gaps") or [])
                    if str(gap.get("importance", "")).upper() == CRITICAL
                ]
            return items
        if isinstance(gaps, Sequence) and not isinstance(gaps, (str, bytes)):
            return [gap for gap in gaps if isinstance(gap, dict)]
        return []

    @staticmethod
    def _list(report: Dict[str, Any]) -> str:
        names = [
            str(gap.get("skill"))
            for gap in (report.get("critical_gaps") or [])
            if gap.get("skill")
        ]
        return ", ".join(names) if names else "none named"


#: Shared instance for callers that do not need their own transcript.
agent_collaboration = AgentCollaboration()
