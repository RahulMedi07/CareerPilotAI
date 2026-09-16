"""The full CareerPilot pipeline: advert in, decision out.

Seven nodes, in a straight line::

    analyze_job -> extract_resume -> calculate_match -> detect_gaps
                -> optimize_resume -> prepare_interview
                -> generate_recommendation -> END

Two decisions in here are worth explaining, because both look like they could
have gone the other way.

**The graph is a line, not a fan-out.** The brief draws ``extract_resume``
branching into five parallel children. It cannot be: ``optimize_resume`` and
``prepare_interview`` both read the gap report *and* the match score, so a
genuine fan-out would have them racing the nodes that produce their inputs. It
would also race on the state itself -- ``all_analysis`` is a plain dict that
overwrites, so two branches finishing together would silently drop one of the
two results. Sequential is not a simplification here; it is the only ordering
that produces a correct answer.

**The nodes are borrowed, not rewritten.** :class:`WorkflowGraph` already
implements six of these seven steps. Re-implementing them here would create two
places that answer "how well does this resume fit", and the day they drift is
the day the same candidate gets two different scores from one product. So this
module owns the *pipeline* -- the order, the extra RAG-backed extraction step,
the final recommendation, the tracing -- and delegates every scoring step to
:meth:`WorkflowGraph.node_impl`.

Failure is contained per node. A node that raises is logged, marked ``error``
in the trace, and the run carries on with defaults; a node with nothing to work
on is marked ``skipped``. If the compiled graph itself cannot run, the pipeline
falls back to executing the same nodes in a plain Python loop. The caller
always gets a result object and a trace, never a stack trace.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from agents.graph_builder import WorkflowGraph, WorkflowError
from agents.workflow_state import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    StepTimer,
    WorkflowState,
    create_initial_state,
    merge_analysis,
)
from utils.logger import get_logger

logger = get_logger(__name__)

#: Node order. Also the order they appear in the trace, and the step numbers.
NODE_SEQUENCE = (
    "analyze_job",
    "extract_resume",
    "calculate_match",
    "detect_gaps",
    "optimize_resume",
    "prepare_interview",
    "generate_recommendation",
)

#: Human-readable name per node, used in the summary trace.
NODE_LABELS = {
    "analyze_job": "Job Analyzer",
    "extract_resume": "Resume Extraction",
    "calculate_match": "Match Calculator",
    "detect_gaps": "Gap Detector",
    "optimize_resume": "Resume Optimizer",
    "prepare_interview": "Interview Prep",
    "generate_recommendation": "Recommendation",
}

#: Where each node parks its full output in the returned dict, on top of the
#: node-keyed ``all_analysis``. Stable names survive the graph being rewired.
STATE_SLOTS = {
    "analyze_job": "analysis",
    "calculate_match": "match_result",
    "detect_gaps": "gaps",
    "optimize_resume": "resume_optimizations",
    "prepare_interview": "interview_prep",
}

APPLY = "APPLY"
MAYBE = "MAYBE"
SKIP = "SKIP"
_VERDICTS = (SKIP, MAYBE, APPLY)

#: Not a verdict. Emitted when the advert specified nothing measurable, so the
#: match calculator returned no score at all. Kept out of ``_VERDICTS`` on
#: purpose: it must never be reachable by the score bands.
UNSCORED = "NOT_SCORED"

#: Run-level outcomes.
RUN_COMPLETED = "completed"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"

#: A SKIP is worth reconsidering only if the shortfall is genuinely small and
#: genuinely quick. Both conditions, not either.
_RESCUE_MIN_SCORE = 50.0
_RESCUE_MAX_CRITICAL = 2
_RESCUE_MAX_WEEKS = 2

#: Enough critical gaps and an APPLY stops being honest, however good the score.
_DOWNGRADE_CRITICAL = 3


def _as_fraction(value: Any) -> float:
    """Coerce a confidence onto 0-1, whichever scale it arrived on.

    Agents in this codebase report confidence both ways (``0.95`` and
    ``93.0``). Anything above 1 is read as a percentage.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(number, 1.0))


class CompleteWorkflow:
    """Runs every agent in order and turns the results into a decision.

    ``graph`` is injectable so tests can hand in a stub and never construct the
    real agents. Compilation is lazy, so building one of these is cheap.
    """

    def __init__(
        self,
        graph: Optional[WorkflowGraph] = None,
        retriever: Optional[Any] = None,
        **graph_kwargs: Any,
    ) -> None:
        if graph is None:
            graph = WorkflowGraph(retriever=retriever, **graph_kwargs)
        elif retriever is not None and getattr(graph, "retriever", None) is None:
            graph.retriever = retriever

        self.graph = graph
        self._compiled = None

    # -- Retriever --------------------------------------------------------

    @property
    def retriever(self) -> Optional[Any]:
        """The optional ``ResumeIndexer`` backing ``extract_resume``."""
        return getattr(self.graph, "retriever", None)

    # -- Compilation ------------------------------------------------------

    def build(self):
        """Compile the LangGraph ``StateGraph``.

        Imported here rather than at module scope so that importing this module
        -- which tests and the API do at startup -- never pulls in LangGraph.
        """
        from langgraph.graph import END, StateGraph

        builder = StateGraph(WorkflowState)

        for name in NODE_SEQUENCE:
            builder.add_node(name, self._traced(name))

        builder.set_entry_point(NODE_SEQUENCE[0])
        for source, target in zip(NODE_SEQUENCE, NODE_SEQUENCE[1:]):
            builder.add_edge(source, target)
        builder.add_edge(NODE_SEQUENCE[-1], END)

        return builder.compile()

    @property
    def compiled(self):
        """The compiled graph, built once and reused."""
        if self._compiled is None:
            self._compiled = self.build()
        return self._compiled

    # -- Node bodies ------------------------------------------------------
    #
    # Public, one per spec node. Each takes the state and returns the state
    # update; timing and error handling live in `_traced`.

    def node_analyze_job(self, state: WorkflowState) -> Dict[str, Any]:
        """Read the advert: title, seniority, required and preferred skills."""
        return self.graph.node_impl("analyze_job")(state)

    def node_extract_resume(self, state: WorkflowState) -> Dict[str, Any]:
        """Load the resume and the skills evidenced in it.

        Prefers the RAG index when one is attached, because the indexer has
        already parsed the document into sections and a profile. Falls back to
        the raw text otherwise, so the pipeline runs with no vector store and
        no model download.
        """
        resume = (state.get("resume_text") or "").strip()
        source = "text"
        profile: Dict[str, Any] = {}

        if self.retriever is not None:
            loaded, profile, source = self._from_rag(resume)
            if loaded:
                resume = loaded
                state = dict(state, resume_text=resume)  # type: ignore[assignment]

        if not resume:
            return {
                "skills_found": [],
                "all_analysis": merge_analysis(
                    state, "extract_resume", {"skipped": "no resume supplied"}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": "no resume supplied",
                "_trace": {"label": NODE_LABELS["extract_resume"]},
            }

        update = dict(self.graph.node_impl("extract_skills")(state) or {})
        skills = list(update.get("skills_found") or [])

        payload = dict(
            ((update.get("all_analysis") or {}).get("extract_skills") or {})
        )
        payload.update(
            {
                "resume_source": source,
                "characters": len(resume),
                "skills": skills,
            }
        )
        if profile:
            payload["profile"] = profile

        update["resume_text"] = resume
        update["all_analysis"] = merge_analysis(state, "extract_resume", payload)
        update["_detail"] = (
            f"{len(resume)} chars from {source}, {len(skills)} skill(s)"
        )
        update["_trace"] = {
            "label": NODE_LABELS["extract_resume"],
            "skills_found": len(skills),
            "resume_source": source,
        }
        return update

    def node_calculate_match(self, state: WorkflowState) -> Dict[str, Any]:
        """Score the resume against the advert, 0-100."""
        return self.graph.node_impl("calculate_match")(state)

    def node_detect_gaps(self, state: WorkflowState) -> Dict[str, Any]:
        """Work out what is missing, how badly, and how long it takes to fix."""
        return self.graph.node_impl("detect_gaps")(state)

    def node_optimize_resume(self, state: WorkflowState) -> Dict[str, Any]:
        """Rewrite suggestions tailored to this one advert."""
        return self.graph.node_impl("optimize_resume")(state)

    def node_prepare_interview(self, state: WorkflowState) -> Dict[str, Any]:
        """Likely questions, answer scaffolds and a day-by-day prep plan."""
        return self.graph.node_impl("prepare_interview")(state)

    def node_generate_recommendation(self, state: WorkflowState) -> Dict[str, Any]:
        """Turn six analyses into one decision the user can act on."""
        analysis = state.get("all_analysis") or {}
        match = analysis.get("calculate_match") or {}
        gaps = (analysis.get("detect_gaps") or {}).get("gap_report") or {}
        interview = analysis.get("prepare_interview") or {}
        optimisation = analysis.get("optimize_resume") or {}

        if not match or match.get("skipped"):
            reason = "nothing was scored, so there is no decision to give"
            summary = (
                "Not enough information to make a call. "
                "Supply both a resume and a job advert and run this again."
            )
            payload = {
                "decision": SKIP,
                "headline": summary,
                "reasoning": [reason],
                "next_steps": [],
                "confidence": 0.0,
                "skipped": reason,
            }
            return {
                "user_recommendation": summary,
                "all_analysis": merge_analysis(
                    state, "generate_recommendation", payload
                ),
                "_status": STATUS_SKIPPED,
                "_detail": reason,
                "_trace": {"label": NODE_LABELS["generate_recommendation"]},
            }

        if match.get("overall_match") is None:
            # The match calculator ran and succeeded; it simply found nothing
            # in the advert to measure against. That is not a skipped node and
            # not a low score, so it keeps a normal status and is reported as
            # what it is. Falling through would have made `float(None or 0.0)`
            # into a 0.0 and printed "0/100 - the fit is not there" underneath
            # a breakdown whose every row read "Not counted".
            reason = (
                "the advert named no skills, technologies, years of experience "
                "or qualifications, so there was nothing to score against"
            )
            summary = (
                "Not scored. This advert states no requirements that could be "
                "checked against your resume, so no match percentage would "
                "mean anything. Paste the full posting if you have it, or "
                "judge this one yourself."
            )
            payload = {
                "decision": UNSCORED,
                "scored_decision": UNSCORED,
                "adjusted": False,
                "adjustment_reason": None,
                "overall_match": None,
                "critical_gaps": int(gaps.get("critical_count") or 0),
                "weeks_to_close_gaps": 0.0,
                "headline": "Not scored - the advert states no requirements.",
                "reasoning": [reason],
                "next_steps": self._next_steps(
                    UNSCORED, gaps, optimisation, interview
                ),
                "confidence": 0.0,
                "summary": summary,
            }
            return {
                "user_recommendation": summary,
                "all_analysis": merge_analysis(
                    state, "generate_recommendation", payload
                ),
                "_detail": reason,
                "_trace": {
                    "label": NODE_LABELS["generate_recommendation"],
                    "decision": UNSCORED,
                    "scored_decision": UNSCORED,
                    "confidence": 0.0,
                },
            }

        score = float(match.get("overall_match") or 0.0)
        scored = str(match.get("recommendation") or SKIP).upper()
        if scored not in _VERDICTS:
            scored = SKIP

        critical = int(gaps.get("critical_count") or 0)
        weeks = float(gaps.get("total_learning_time_weeks") or 0.0)
        decision, adjustment = self._adjust(scored, score, critical, weeks)

        payload = {
            "decision": decision,
            "scored_decision": scored,
            "adjusted": adjustment is not None,
            "adjustment_reason": adjustment,
            "overall_match": round(score, 1),
            "critical_gaps": critical,
            "weeks_to_close_gaps": round(weeks, 1),
            "reasoning": self._reasoning(
                decision, score, critical, weeks, interview, adjustment
            ),
            "next_steps": self._next_steps(
                decision, gaps, optimisation, interview
            ),
            "confidence": self._confidence(match, gaps, interview),
        }
        payload["headline"] = self._headline(decision, score, critical, weeks)
        summary = self._summary(payload)
        payload["summary"] = summary

        return {
            "user_recommendation": summary,
            "all_analysis": merge_analysis(
                state, "generate_recommendation", payload
            ),
            "_detail": (
                f"{decision} at {score:.1f}/100"
                + (" (adjusted)" if adjustment else "")
            ),
            "_trace": {
                "label": NODE_LABELS["generate_recommendation"],
                "decision": decision,
                "scored_decision": scored,
                "confidence": payload["confidence"],
            },
        }

    # -- Recommendation helpers -------------------------------------------

    def _adjust(
        self,
        scored: str,
        score: float,
        critical: int,
        weeks: float,
    ) -> tuple:
        """Optionally move the match calculator's verdict, and say why.

        The scorer has already published a verdict. Quietly overriding it would
        leave the product showing two answers with no account of the
        difference, so this returns the reason alongside the change and the
        caller keeps both values.
        """
        if scored == SKIP and (
            score >= _RESCUE_MIN_SCORE
            and 0 < critical <= _RESCUE_MAX_CRITICAL
            and 0 < weeks <= _RESCUE_MAX_WEEKS
        ):
            return MAYBE, (
                f"Scored {SKIP}, raised to {MAYBE}: only {critical} critical "
                f"gap(s), and about {weeks:.0f} week(s) of study closes them."
            )

        if scored == APPLY and critical >= _DOWNGRADE_CRITICAL:
            return MAYBE, (
                f"Scored {APPLY}, lowered to {MAYBE}: {critical} critical "
                f"requirements are unevidenced, which is a lot to defend in an "
                f"interview."
            )

        return scored, None

    def _reasoning(
        self,
        decision: str,
        score: float,
        critical: int,
        weeks: float,
        interview: Dict[str, Any],
        adjustment: Optional[str],
    ) -> List[str]:
        reasons = [f"Overall match is {score:.1f}/100."]

        if critical:
            reasons.append(
                f"{critical} critical requirement(s) are not evidenced on your "
                f"resume"
                + (f", roughly {weeks:.0f} week(s) of study." if weeks else ".")
            )
        else:
            reasons.append("No critical requirement is completely unevidenced.")

        difficulty = interview.get("interview_difficulty")
        success = interview.get("success_rate_prediction")
        if difficulty and success is not None:
            reasons.append(
                f"Interview looks {str(difficulty).lower()}; on the resume "
                f"alone the odds come out around {round(float(success) * 100)}%."
            )

        if adjustment:
            reasons.append(adjustment)

        if decision == APPLY:
            reasons.append("Apply, and tailor the resume before you send it.")
        elif decision == MAYBE:
            reasons.append(
                "Worth applying if you want it, but go in knowing the gaps."
            )
        else:
            reasons.append(
                "The distance here is real. Better spent on a closer role, or "
                "on closing the gaps first."
            )
        return reasons

    def _next_steps(
        self,
        decision: str,
        gaps: Dict[str, Any],
        optimisation: Dict[str, Any],
        interview: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Concrete actions, ordered by what to do first.

        Order depends on the verdict. Leading a ``SKIP`` with "polish your
        resume for this advert" would contradict the sentence directly above
        it, and advice that argues with itself gets ignored wholesale.
        """
        missing = [str(name) for name in (gaps.get("priority_order") or [])]
        critical = list(gaps.get("critical_gaps") or [])
        if not missing:
            missing = [
                str(gap.get("skill")) for gap in critical if gap.get("skill")
            ]

        # `priority_order` is cheapest-first, which is right for "what to study
        # next" and exactly wrong for "which requirement rules you out". The
        # first pass here advised avoiding roles that need Pinecone -- a two-day
        # gap -- while ignoring the ten-day one.
        costliest = ""
        if critical:
            costliest = str(
                max(
                    critical,
                    key=lambda gap: float(gap.get("learning_time_days") or 0),
                ).get("skill")
                or ""
            )
        if not costliest and missing:
            costliest = missing[-1]

        shown = missing[:3]
        remainder = len(missing) - len(shown)
        gap_names = ", ".join(shown) + (
            f" (and {remainder} more)" if remainder > 0 else ""
        )

        weeks = gaps.get("total_learning_time_weeks") or 0
        high = int(optimisation.get("high_impact_count") or 0)
        hours = interview.get("estimated_prep_time_hours")
        days = interview.get("prep_days")

        close_gaps = {
            "action": "Close the critical gaps: " + gap_names,
            "where": "gaps.critical_gaps",
            "effort": f"~{weeks} week(s)",
        }
        edit_resume = {
            "action": f"Apply the {high} high-impact resume edit(s).",
            "where": "resume_optimizations.improvements",
            "effort": "under an hour",
        }
        prep = {
            "action": f"Work through the {days}-day interview plan.",
            "where": "interview_prep.preparation_plan",
            "effort": f"{hours} hour(s)",
        }

        steps: List[Dict[str, Any]] = []
        if decision == SKIP:
            if missing:
                steps.append(close_gaps)
                steps.append(
                    {
                        "action": (
                            "Look for a role that does not require "
                            f"{costliest} - the same resume scores higher "
                            "against a closer advert."
                        ),
                        "where": "a different advert",
                        "effort": "minutes",
                    }
                )
            if high:
                # Deliberately last, and reworded: these edits were tailored to
                # an advert we have just advised against, but the wording and
                # quantifying work carries over to every other application.
                steps.append(
                    dict(
                        edit_resume,
                        action=(
                            f"Apply the {high} high-impact resume edit(s) "
                            "anyway - stronger wording and real numbers help "
                            "on any application."
                        ),
                    )
                )
            return steps

        if high:
            steps.append(edit_resume)
        if missing:
            steps.append(close_gaps)
        if hours:
            steps.append(prep)
        return steps

    def _headline(
        self,
        decision: str,
        score: float,
        critical: int,
        weeks: float,
    ) -> str:
        """One line the user reads first, and which has to be true.

        The SKIP branch used to assert "the gaps are the expensive kind" without
        consulting ``weeks``, so a low score with a two-day gap was described as
        expensive. It now says which kind of skip it is, because the two call
        for different action: study, or look elsewhere.
        """
        if decision == APPLY:
            return f"Apply. {score:.0f}/100, nothing major standing in the way."
        if decision == MAYBE:
            gap_text = (
                f"{critical} critical gap(s)" if critical else "some soft spots"
            )
            return f"Worth a shot. {score:.0f}/100 with {gap_text}."
        if weeks > _RESCUE_MAX_WEEKS:
            return (
                f"Probably skip. {score:.0f}/100, and roughly {weeks:.0f} week(s) "
                "of study stand in the way."
            )
        return (
            f"Probably skip. {score:.0f}/100 - the gaps are small, but the fit "
            "is not there."
        )

    def _summary(self, payload: Dict[str, Any]) -> str:
        """The paragraph the user actually reads."""
        parts = [payload["headline"]]
        parts.extend(payload["reasoning"][1:])

        steps = payload.get("next_steps") or []
        if steps:
            parts.append("Start with: " + str(steps[0]["action"]))
        return " ".join(str(part) for part in parts)

    def _confidence(
        self,
        match: Dict[str, Any],
        gaps: Dict[str, Any],
        interview: Dict[str, Any],
    ) -> float:
        """How much to trust this verdict.

        The average of whatever the upstream agents reported, and never higher
        than the least confident of them: a chain of inferences is no more
        reliable than its weakest link, and averaging alone would hide that.

        Every input is normalised first, because the agents do not agree on a
        scale -- the match calculator reports ``93.0`` and the interview agent
        reports ``0.95`` for comparable certainty. Averaging them raw produced
        a plausible-looking number that meant nothing at all.
        """
        scores = [
            _as_fraction(source.get("confidence"))
            for source in (match, gaps, interview)
            if isinstance(source, dict) and source.get("confidence") is not None
        ]
        if not scores:
            return 0.0
        return round(min(sum(scores) / len(scores), min(scores)), 2)

    # -- RAG ---------------------------------------------------------------

    def _from_rag(self, fallback: str) -> tuple:
        """Pull the resume out of the vector store. Never fatal."""
        profile: Dict[str, Any] = {}
        text = ""
        try:
            text = (self.retriever.get_full_context() or "").strip()
        except Exception as exc:
            logger.warning("RAG context unavailable, using raw text: %s", exc)
            return fallback, profile, "text"

        try:
            raw = self.retriever.get_profile()
            profile = dict(raw) if isinstance(raw, dict) else vars(raw)
        except Exception as exc:
            logger.debug("No profile in the index: %s", exc)

        if not text:
            return fallback, profile, "text"

        # A resume passed in directly is the one the user meant; the index may
        # hold an older upload.
        if fallback:
            return fallback, profile, "text+rag"
        return text, profile, "rag"

    # -- Tracing -----------------------------------------------------------

    def _traced(self, name: str) -> Callable[[WorkflowState], Dict[str, Any]]:
        """Wrap a node so it is timed, guarded and traced."""
        step = NODE_SEQUENCE.index(name) + 1
        fn = getattr(self, f"node_{name}")

        def _wrapped(state: WorkflowState) -> Dict[str, Any]:
            timer = StepTimer(name, step=step)
            try:
                with timer:
                    update = dict(fn(state) or {})
            except Exception as exc:
                logger.warning("Node '%s' failed: %s", name, exc, exc_info=True)
                return {
                    "all_analysis": merge_analysis(
                        state, name, {"error": str(exc)}
                    ),
                    "execution_trace": [
                        timer.entry(
                            detail=f"{exc.__class__.__name__}: {exc}",
                            error=str(exc),
                            label=NODE_LABELS[name],
                        )
                    ],
                }

            detail = update.pop("_detail", None)
            timer.status = update.pop("_status", timer.status)
            extra = update.pop("_trace", None) or {}
            extra.setdefault("label", NODE_LABELS[name])

            # Mirror the node's output into its stable slot, so callers can read
            # `result["gaps"]` without knowing which node produced it.
            slot = STATE_SLOTS.get(name)
            if slot:
                produced = (update.get("all_analysis") or {}).get(name)
                if produced is not None:
                    update[slot] = produced

            update["execution_trace"] = [timer.entry(detail=detail, **extra)]
            logger.info("Node '%s' finished in %.1fms", name, timer.duration_ms)
            return update

        _wrapped.__name__ = f"node_{name}"
        return _wrapped

    # -- Execution ---------------------------------------------------------

    def run_complete_analysis(
        self,
        resume_text: str = "",
        job_description: str = "",
        advanced: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run every agent and return the complete analysis plus its trace.

        By default this now runs the *branching* workflow from
        :mod:`agents.advanced_workflow`: same agents, but it decides which
        steps are worth running and adds a learning plan when one would
        actually help. Pass ``advanced=False`` for the original straight-line
        run of all seven nodes.

        The return shape is unchanged either way. Every key the linear
        pipeline documented is still present and still means the same thing -
        the branching run only adds to it (``decisions``, ``collaboration``,
        ``learning_plan``, ``path``). ``main.py``, the response models, the
        trace endpoint and the older scripts all read the original keys, so
        changing the engine underneath them must not change the contract.

        Never raises. A run with nothing to analyse, a node that blows up and a
        graph that will not compile all come back as a result object with a
        ``status`` and a trace explaining what happened.
        """
        state = create_initial_state(
            resume_text=resume_text, job_description=job_description, **kwargs
        )

        if not state["resume_text"].strip() and not state["job_description"].strip():
            return self._result(
                state,
                RUN_FAILED,
                note="Nothing to analyse: provide resume_text, job_description, "
                "or both.",
            )

        if advanced:
            try:
                return self._run_advanced(resume_text, job_description, **kwargs)
            except Exception as exc:
                # The branching workflow is the newer of the two. If it cannot
                # run, fall back to the linear pipeline rather than failing
                # the request: a plainer answer beats no answer.
                logger.warning(
                    "Advanced workflow unavailable (%s); running the linear "
                    "pipeline instead.",
                    exc,
                )

        try:
            final = self.compiled.invoke(state)
        except Exception as exc:
            # The graph itself failed -- a bad compile, a LangGraph version
            # change. The agents are fine, so run them directly rather than
            # returning nothing.
            logger.warning(
                "Compiled graph unavailable (%s); running nodes directly.", exc
            )
            final = self._run_sequentially(state)
            return self._result(
                final,
                note=f"Ran without LangGraph: {exc.__class__.__name__}: {exc}",
            )

        return self._result(final)

    def _run_advanced(
        self,
        resume_text: str,
        job_description: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run the branching workflow and return it in this class's shape.

        Imported here rather than at module scope because
        :mod:`agents.advanced_workflow` builds itself on top of this class.
        """
        from agents.advanced_workflow import AdvancedWorkflow

        advanced = AdvancedWorkflow(pipeline=self)
        result = advanced.run(resume_text, job_description, **kwargs)

        analysis = dict(result.get("all_analysis") or {})
        # Both graphs now call the interview node ``prepare_interview`` - the
        # conditional graph used to disagree, which cost it LangGraph entirely
        # (a node may not share a name with a state key). Only the last node
        # still differs. The public keys are the linear pipeline's, because
        # that is what every caller already reads.
        interview = analysis.get("prepare_interview") or {}
        recommendation = analysis.get("final_recommendation") or {}

        shaped: Dict[str, Any] = {
            "resume_text": resume_text or "",
            "job_description": job_description or "",
            "analysis": analysis.get("analyze_job") or {},
            "match_result": analysis.get("calculate_match") or {},
            "gaps": analysis.get("detect_gaps") or {},
            "resume_optimizations": analysis.get("optimize_resume") or {},
            "interview_prep": interview,
            "recommendation": recommendation,
            "user_recommendation": result.get("user_recommendation") or "",
            "skills_found": list(result.get("skills_found") or []),
            "gaps_identified": list(result.get("gaps_identified") or []),
            "match_score": float(result.get("match_score") or 0.0),
            "all_analysis": analysis,
            "execution_trace": list(result.get("execution_trace") or []),
            "trace": summarise_trace(list(result.get("execution_trace") or [])),
            "total_duration_ms": result.get("total_duration_ms") or 0.0,
            "nodes_run": list(result.get("nodes_run") or []),
            "nodes_failed": list(result.get("nodes_failed") or []),
            "nodes_skipped": list(result.get("nodes_skipped") or []),
            "status": result.get("status") or RUN_COMPLETED,
        }

        # What the branching run adds. A node the graph deliberately routed
        # around is absent here, not empty - there is a difference between
        # "no learning plan was needed" and "the planner returned nothing".
        shaped["workflow"] = "advanced"
        shaped["path"] = list(result.get("path") or [])
        shaped["decisions"] = list(result.get("decisions") or [])
        shaped["collaboration"] = list(result.get("collaboration") or [])
        shaped["learning_plan"] = result.get("learning_plan")
        shaped["initial_match"] = result.get("initial_match")
        shaped["optimized_match"] = result.get("optimized_match")
        shaped["projected_match_explained"] = result.get("projected_match_explained")
        shaped["final"] = result.get("final") or {}
        return shaped

    #: The name the brief uses.
    def run(self, resume_text: str = "", job_description: str = "", **kwargs: Any):
        """Alias for :meth:`run_complete_analysis`."""
        return self.run_complete_analysis(resume_text, job_description, **kwargs)

    def _run_sequentially(self, state: WorkflowState) -> WorkflowState:
        """Execute the nodes in order without LangGraph.

        The fallback path, and the reason a broken graph dependency degrades
        into a slower run rather than an outage. Applies updates by hand,
        including the append semantics ``execution_trace`` relies on.
        """
        current: Dict[str, Any] = dict(state)
        for name in NODE_SEQUENCE:
            update = self._traced(name)(current)  # type: ignore[arg-type]
            trace = update.pop("execution_trace", [])
            current.update(update)
            current["execution_trace"] = list(current.get("execution_trace") or [])
            current["execution_trace"].extend(trace)
        return current  # type: ignore[return-value]

    # -- Result shaping ----------------------------------------------------

    def _result(
        self,
        state: WorkflowState,
        status: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assemble the public return value."""
        trace = list(state.get("execution_trace") or [])
        failed = [
            str(entry.get("node"))
            for entry in trace
            if entry.get("status") == STATUS_ERROR
        ]
        skipped = [
            str(entry.get("node"))
            for entry in trace
            if entry.get("status") == STATUS_SKIPPED
        ]

        if status is None:
            if failed or skipped:
                status = RUN_PARTIAL
            elif len(trace) < len(NODE_SEQUENCE):
                status = RUN_PARTIAL
            else:
                status = RUN_COMPLETED

        analysis = state.get("all_analysis") or {}
        result: Dict[str, Any] = {
            "resume_text": state.get("resume_text") or "",
            "job_description": state.get("job_description") or "",
            "analysis": analysis.get("analyze_job") or {},
            "match_result": analysis.get("calculate_match") or {},
            "gaps": analysis.get("detect_gaps") or {},
            "resume_optimizations": analysis.get("optimize_resume") or {},
            "interview_prep": analysis.get("prepare_interview") or {},
            "recommendation": analysis.get("generate_recommendation") or {},
            "user_recommendation": state.get("user_recommendation") or "",
            "skills_found": list(state.get("skills_found") or []),
            "gaps_identified": list(state.get("gaps_identified") or []),
            "match_score": float(state.get("match_score") or 0.0),
            "all_analysis": analysis,
            "execution_trace": trace,
            "trace": summarise_trace(trace),
            "total_duration_ms": round(
                sum(float(entry.get("duration_ms") or 0.0) for entry in trace), 2
            ),
            "nodes_run": [str(entry.get("node")) for entry in trace],
            "nodes_failed": failed,
            "nodes_skipped": skipped,
            "status": status,
        }
        if note:
            result["note"] = note
            if not result["user_recommendation"]:
                result["user_recommendation"] = note
        return result

    # -- Introspection -----------------------------------------------------

    @staticmethod
    def node_names() -> List[str]:
        """The nodes in the order the linear pipeline runs them."""
        return list(NODE_SEQUENCE)

    @staticmethod
    def describe() -> Dict[str, Any]:
        """Log-safe description of the pipeline."""
        return {
            "nodes": list(NODE_SEQUENCE),
            "labels": dict(NODE_LABELS),
            "edges": [
                {"from": a, "to": b}
                for a, b in zip(NODE_SEQUENCE, NODE_SEQUENCE[1:])
            ]
            + [{"from": NODE_SEQUENCE[-1], "to": "END"}],
        }


def summarise_trace(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Condense the detailed trace into the reporting shape.

    ``{"trace": [{"node": "Job Analyzer", "status": ..., "duration_ms": ...}],
    "total_duration_ms": ..., "status": ...}``
    """
    rows = [
        {
            # The pipeline's own label wins over the agent's. An agent may call
            # itself "Interview Prep Agent"; this trace is a report on nodes.
            "node": NODE_LABELS.get(
                str(entry.get("node")),
                entry.get("label") or str(entry.get("node")),
            ),
            "status": entry.get("status", STATUS_OK),
            "duration_ms": round(float(entry.get("duration_ms") or 0.0)),
        }
        for entry in trace
    ]
    statuses = {row["status"] for row in rows}
    if STATUS_ERROR in statuses or STATUS_SKIPPED in statuses:
        overall = RUN_PARTIAL
    elif not rows:
        overall = RUN_FAILED
    else:
        overall = RUN_COMPLETED

    return {
        "trace": rows,
        "total_duration_ms": round(
            sum(float(entry.get("duration_ms") or 0.0) for entry in trace)
        ),
        "status": overall,
    }


def build_complete_workflow(**kwargs: Any) -> CompleteWorkflow:
    """Construct a :class:`CompleteWorkflow`."""
    return CompleteWorkflow(**kwargs)


def run_complete_analysis(
    resume_text: str = "",
    job_description: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """One-shot convenience wrapper around a fresh pipeline."""
    return CompleteWorkflow(**kwargs).run_complete_analysis(
        resume_text, job_description
    )


#: Shared instance for callers that do not need their own configuration.
complete_workflow = CompleteWorkflow()


__all__ = [
    "NODE_SEQUENCE",
    "NODE_LABELS",
    "CompleteWorkflow",
    "WorkflowError",
    "build_complete_workflow",
    "complete_workflow",
    "run_complete_analysis",
    "summarise_trace",
]
