"""The branching pipeline: agents collaborate, the graph decides, twice.

This is the brief's advanced workflow. It reuses every node from
:class:`~agents.complete_workflow.CompleteWorkflow` rather than reimplementing
them - two modules that both answer "how well does this resume fit" is two
answers to one question, and the day they drift is the day one candidate gets
two different scores from one product.

What is new here is the branching (:mod:`agents.conditional_graph`), the
recorded agent-to-agent questions (:mod:`agents.agent_collaboration`), the
study plan (:mod:`agents.learning_path_agent`), and the second scoring pass.

The second scoring pass needs explaining, because it is the one place where
this module returns a smaller number than the brief advertises.

The brief asks for ``initial_match`` and ``optimized_match`` - score the
resume, apply the optimiser's suggestions, score it again, and report the
improvement. Measured on the sample pair, that is::

    baseline                      73.6  MAYBE
    + the optimiser's truthful suggestions
      (Docker, Next.js, Machine Learning)      73.6  MAYBE
    + the skills the optimiser refuses to add
      (CI/CD, LangGraph, Pinecone)             93.7  APPLY

The uplift the brief is reaching for is the second line: twenty points and a
changed verdict. Every one of those points comes from claiming three skills the
candidate does not have. The optimiser already refuses to suggest them - they
arrive in ``keywords_blocked_by_gaps`` precisely so nobody adds them - and
re-scoring as though they had been added would launder that refusal into a
headline number.

So the re-score here uses **only** what the optimiser was willing to suggest,
and on this resume that moves the score by nothing at all. That is the honest
answer, and it carries information: it says the distance to this job is missing
capability, not bad phrasing, and no amount of rewriting closes it.

When the re-score *does* move, it moves for a real reason. The matcher works
from named skills, so a candidate whose resume says PostgreSQL but never SQL is
being under-credited for something they can genuinely do. Surfacing that is a
correction, not an inflation - and the projected score is still reported
separately from the real one, and never allowed to change the verdict. Advising
someone to apply on the strength of a resume they have not written yet would be
the same mistake in a different place.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from agents.agent_collaboration import AgentCollaboration
from agents.complete_workflow import UNSCORED, CompleteWorkflow
from agents.conditional_graph import (
    ANALYZE_JOB,
    APPLY_AFTER_LEARNING,
    APPLY_NOW,
    CALCULATE_MATCH,
    CHECK_LEARNABLE,
    CREATE_PLAN,
    DEFAULT_LEARNING_WINDOW_DAYS,
    DETECT_GAPS,
    EXTRACT_RESUME,
    FINAL,
    PREPARE_INTERVIEW,
    NODE_LABELS,
    NODE_ORDER,
    OPTIMIZE_RESUME,
    RECALCULATE_MATCH,
    SKIP,
    blocking_days,
    build_conditional_graph,
    critical_count,
    describe_graph,
    explain_optimize,
    explain_plan,
    final_recommendation,
    should_create_plan,
    should_optimize,
)
from agents.workflow_state import (
    STATUS_ERROR,
    STATUS_SKIPPED,
    StepTimer,
    WorkflowState,
    create_initial_state,
    merge_analysis,
)
from utils.logger import get_logger

logger = get_logger(__name__)

RUN_COMPLETED = "completed"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"

#: Where each node parks its output for stable access.
STATE_SLOTS = {
    ANALYZE_JOB: "analysis",
    CALCULATE_MATCH: "match_result",
    DETECT_GAPS: "gaps",
    OPTIMIZE_RESUME: "resume_optimizations",
    PREPARE_INTERVIEW: "interview_prep",
}


class AdvancedWorkflow:
    """The conditional pipeline.

    ``pipeline`` and ``collaboration`` are injectable so tests can supply
    stubs and never build the real agents.
    """

    def __init__(
        self,
        pipeline: Optional[CompleteWorkflow] = None,
        collaboration: Optional[AgentCollaboration] = None,
        retriever: Optional[Any] = None,
        learning_window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
        **kwargs: Any,
    ) -> None:
        self.pipeline = pipeline or CompleteWorkflow(retriever=retriever, **kwargs)
        self.collaboration = collaboration or AgentCollaboration()
        self.learning_window_days = int(learning_window_days)
        self._compiled = None

    @property
    def retriever(self) -> Optional[Any]:
        """The linear pipeline's retriever, or ``None`` if nothing is indexed."""
        return getattr(self.pipeline, "retriever", None)

    # -- Compilation ------------------------------------------------------

    def build(self) -> Any:
        """Compile the branching graph, wrapping each node in tracing."""
        return build_conditional_graph(
            {name: self._traced(name) for name in NODE_ORDER},
            window_days=self.learning_window_days,
        )

    @property
    def compiled(self) -> Any:
        """The compiled graph, built once and reused."""
        if self._compiled is None:
            self._compiled = self.build()
        return self._compiled

    # -- Nodes borrowed from the linear pipeline --------------------------

    def node_analyze_job(self, state: WorkflowState) -> Dict[str, Any]:
        """Delegate to the linear pipeline: the work is identical here."""
        return self.pipeline.node_analyze_job(state)

    def node_extract_resume(self, state: WorkflowState) -> Dict[str, Any]:
        """Delegate to the linear pipeline: the work is identical here."""
        return self.pipeline.node_extract_resume(state)

    def node_calculate_match(self, state: WorkflowState) -> Dict[str, Any]:
        """First scoring pass - what the resume as written earns."""
        update = dict(self.pipeline.node_calculate_match(state) or {})
        update["initial_match_score"] = float(update.get("match_score") or 0.0)
        return update

    def node_detect_gaps(self, state: WorkflowState) -> Dict[str, Any]:
        """Ask the gap detector, through the collaboration layer."""
        update = dict(self.pipeline.node_detect_gaps(state) or {})
        report = (
            (update.get("all_analysis") or {}).get(DETECT_GAPS) or {}
        ).get("gap_report") or {}
        exchange = self.collaboration._record(
            "Gap Detector",
            "Match is %.0f%%. What are the biggest gaps, and how long would "
            "each take to close?" % float(state.get("match_score") or 0.0),
            (
                "%d critical gap(s): %s. About %d day(s) to close them."
                % (
                    int(report.get("critical_count") or 0),
                    ", ".join(
                        str(gap.get("skill"))
                        for gap in (report.get("critical_gaps") or [])
                    )
                    or "none named",
                    int(report.get("blocking_learning_days") or 0),
                )
                if report.get("critical_count")
                else "No critical gap: nothing required is completely unevidenced."
            ),
        )
        update["collaboration"] = [exchange]
        return update

    def node_optimize_resume(self, state: WorkflowState) -> Dict[str, Any]:
        """Rewrite suggestions - with the gap list, so nothing untrue is added."""
        update = dict(self.pipeline.node_optimize_resume(state) or {})
        report = (update.get("all_analysis") or {}).get(OPTIMIZE_RESUME) or {}
        blocked = list(report.get("keywords_blocked_by_gaps") or [])
        exchange = self.collaboration._record(
            "Resume Optimizer",
            "Given %d critical gap(s), how should this resume change for this "
            "advert - without claiming anything untrue?"
            % critical_count(state),
            "%d suggestion(s), %d high impact.%s"
            % (
                len(report.get("improvements") or []),
                int(report.get("high_impact_count") or 0),
                (
                    " Refused to add %s - those are gaps, not phrasing."
                    % ", ".join(blocked)
                    if blocked
                    else ""
                ),
            ),
            blocked_keywords=blocked,
        )
        update["collaboration"] = [exchange]
        update["decisions"] = [explain_optimize({**state, **update})]
        return update

    # -- The second scoring pass ------------------------------------------

    def node_re_calculate_match(self, state: WorkflowState) -> Dict[str, Any]:
        """Score again, counting only what the optimiser would actually suggest.

        See the module docstring. The additions here are the optimiser's
        ``keywords_to_add`` with ``keywords_blocked_by_gaps`` removed - which
        the optimiser has already done, but doing it again costs nothing and
        means a change there can never silently inflate this number.
        """
        analysis = state.get("all_analysis") or {}
        report = analysis.get(OPTIMIZE_RESUME) or {}
        before = float(state.get("match_score") or 0.0)

        blocked = {
            str(name).strip().lower()
            for name in (report.get("keywords_blocked_by_gaps") or [])
        }
        additions = [
            str(name)
            for name in (report.get("keywords_to_add") or [])
            if str(name).strip().lower() not in blocked
        ]

        if not additions:
            payload = {
                "projected_match": round(before, 1),
                "initial_match": round(before, 1),
                "delta": 0.0,
                "truthful_additions": [],
                "refused_additions": sorted(blocked),
                "note": (
                    "Nothing could be added truthfully, so the score is "
                    "unchanged. The distance here is missing capability, not "
                    "phrasing."
                ),
            }
            return {
                "projected_match_score": round(before, 1),
                "all_analysis": merge_analysis(state, RECALCULATE_MATCH, payload),
                "_detail": "no truthful additions; score unchanged at %.1f" % before,
                "_trace": {
                    "label": NODE_LABELS[RECALCULATE_MATCH],
                    "delta": 0.0,
                    "refused": sorted(blocked),
                },
            }

        # Score a state whose skill list carries the truthful additions. The
        # real state is untouched: this is a projection, not a promotion.
        probe = dict(state)
        probe["skills_found"] = list(state.get("skills_found") or []) + additions
        rescored = dict(self.pipeline.node_calculate_match(probe) or {})
        after = float(rescored.get("match_score") or before)
        delta = after - before

        payload = {
            "projected_match": round(after, 1),
            "initial_match": round(before, 1),
            "delta": round(delta, 1),
            "truthful_additions": additions,
            "refused_additions": sorted(blocked),
            "note": (
                "This is what the resume would score after the suggested "
                "rewording, counting only skills already evidenced. It is a "
                "projection of edits not yet made, so the verdict below still "
                "uses %.1f." % before
            )
            if delta > 0
            else (
                "Rewording does not move this score: the requirements it "
                "misses are ones the resume cannot honestly claim."
            ),
        }
        return {
            # match_score is deliberately NOT updated - the verdict must rest
            # on the resume that exists.
            "projected_match_score": round(after, 1),
            "all_analysis": merge_analysis(state, RECALCULATE_MATCH, payload),
            "_detail": "%.1f -> %.1f after truthful rewording (%+.1f)"
            % (before, after, delta),
            "_trace": {
                "label": NODE_LABELS[RECALCULATE_MATCH],
                "initial_match": round(before, 1),
                "projected_match": round(after, 1),
                "delta": round(delta, 1),
            },
        }

    # -- Decision nodes ---------------------------------------------------

    def node_check_gaps_learnable(self, state: WorkflowState) -> Dict[str, Any]:
        """Decide whether learning first is the better move, and record why."""
        decision = explain_plan(state, self.learning_window_days)
        days = blocking_days(state)
        payload = {
            "blocking_learning_days": days,
            "critical_gaps": critical_count(state),
            "window_days": self.learning_window_days,
            "learnable_in_window": 0 < days <= self.learning_window_days,
            "branch": decision["branch"],
            "reason": decision["reason"],
        }
        return {
            "all_analysis": merge_analysis(state, CHECK_LEARNABLE, payload),
            "decisions": [decision],
            "_detail": decision["reason"],
            "_trace": {
                "label": NODE_LABELS[CHECK_LEARNABLE],
                "blocking_days": days,
                "branch": decision["branch"],
            },
        }

    def node_create_learning_plan(self, state: WorkflowState) -> Dict[str, Any]:
        """Ask the learning path agent for a plan over the window."""
        report = (
            (state.get("all_analysis") or {}).get(DETECT_GAPS) or {}
        ).get("gap_report") or {}
        plan = self.collaboration.ask_learning_path_agent(
            report, self.learning_window_days
        )
        exchange = self.collaboration.transcript[-1] if self.collaboration.transcript else {}

        if not plan or not plan.get("days"):
            reason = plan.get("reason") or "no plan could be built"
            return {
                "learning_plan": plan or {},
                "all_analysis": merge_analysis(state, CREATE_PLAN, plan or {}),
                "collaboration": [exchange] if exchange else [],
                "_status": STATUS_SKIPPED,
                "_detail": reason,
                "_trace": {"label": NODE_LABELS[CREATE_PLAN]},
            }

        return {
            "learning_plan": plan,
            "all_analysis": merge_analysis(state, CREATE_PLAN, plan),
            "collaboration": [exchange] if exchange else [],
            "_detail": plan.get("summary") or "",
            "_trace": {
                "label": NODE_LABELS[CREATE_PLAN],
                "days": plan.get("total_days"),
                "hours_per_day": plan.get("daily_commitment_hours"),
            },
        }

    def node_prepare_interview(self, state: WorkflowState) -> Dict[str, Any]:
        """Draft the interview questions, framed around the gaps.

        Dispatched by name from :meth:`_traced`, so the method has to keep
        matching the node it implements.
        """
        update = dict(self.pipeline.node_prepare_interview(state) or {})
        prep = (update.get("all_analysis") or {}).get("prepare_interview") or {}
        exchange = self.collaboration._record(
            "Interview Prep",
            "Match %.0f%% with %d critical gap(s). What will they ask, and "
            "what should I do about the gaps?"
            % (float(state.get("match_score") or 0.0), critical_count(state)),
            "%d question(s), %d of them about the gaps. Difficulty looks %s."
            % (
                int(prep.get("question_count") or 0),
                int(prep.get("gap_question_count") or 0),
                str(prep.get("interview_difficulty") or "unknown").lower(),
            ),
        )
        update["collaboration"] = [exchange]
        return update

    def node_final_recommendation(self, state: WorkflowState) -> Dict[str, Any]:
        """APPLY_NOW, APPLY_AFTER_LEARNING or SKIP, with the reasoning.

        This layers a *timing* verdict on top of the linear pipeline's
        recommendation rather than replacing it. The two answer different
        questions - the pipeline's ``decision`` says how strong the
        application is (APPLY/MAYBE/SKIP), this says when to send it - and the
        older one carries the accountability keys (``scored_decision``,
        ``adjusted``, ``next_steps``, ``confidence``) that the API and its
        callers already report. Dropping them to substitute a thinner payload
        would be a regression wearing the badge of a new feature.
        """
        # The accountable base: verdict, confidence, next steps, and the
        # record of whether the scorer's decision was adjusted.
        base_update = dict(self.pipeline.node_generate_recommendation(state) or {})
        base_payload = dict(
            (base_update.get("all_analysis") or {}).get("generate_recommendation")
            or {}
        )
        base_summary = str(base_update.get("user_recommendation") or "")

        # "When should you send this?" presupposes an answer to "how well do
        # you fit?". When the advert stated nothing measurable there is no fit
        # score, and `float(None or 0.0)` below would silently become 0.0 --
        # which is how "Not scored" ended up followed by "Skip this one -
        # 0/100" in the same paragraph. Keep the base verdict's wording and
        # still fill this node's slot, because callers read `final`
        # unconditionally.
        if base_payload.get("decision") == UNSCORED:
            payload = dict(base_payload)
            payload.update(
                {
                    "recommendation": UNSCORED,
                    "timing_verdict": UNSCORED,
                    "timing_headline": "",
                    "timing_reasoning": [],
                    "scored_verdict": UNSCORED,
                    "verdicts_reconciled": "",
                    "match_score": None,
                    "projected_match_score": None,
                    "blocking_learning_days": blocking_days(state),
                    "has_learning_plan": False,
                }
            )
            return {
                "recommendation": UNSCORED,
                "user_recommendation": base_summary,
                "all_analysis": merge_analysis(state, FINAL, payload),
                "_detail": "not scored: the advert stated no requirements",
                "_trace": {
                    "label": NODE_LABELS[FINAL],
                    "recommendation": UNSCORED,
                },
            }

        verdict = final_recommendation(state, self.learning_window_days)
        score = float(state.get("match_score") or 0.0)
        projected = float(state.get("projected_match_score") or 0.0)
        days = blocking_days(state)
        critical = critical_count(state)
        plan = state.get("learning_plan") or {}
        scored = str(base_payload.get("scored_decision") or "").upper()

        reasoning = ["Match is %.1f/100 on the resume as written." % score]
        if projected and abs(projected - score) >= 0.1:
            reasoning.append(
                "After the suggested rewording it would be %.1f - a projection "
                "of edits you have not made yet, so it does not change the "
                "verdict." % projected
            )
        if critical:
            reasoning.append(
                "%d critical requirement(s) unevidenced, about %d day(s) of "
                "study." % (critical, days)
            )
        else:
            reasoning.append("No critical requirement is completely unevidenced.")

        if verdict == APPLY_AFTER_LEARNING and plan.get("days"):
            reasoning.append(
                "%d day(s) at about %.1f hours a day closes the gap that is "
                "costing you this application."
                % (plan.get("total_days") or 0, plan.get("daily_commitment_hours") or 0.0)
            )
        elif verdict == APPLY_NOW and days:
            reasoning.append(
                "Apply now and close the remaining gaps in parallel; the "
                "advert will not wait for the study to finish."
            )
        elif verdict == SKIP:
            reasoning.append(
                "The distance is real and not quick to close. Better spent on "
                "a nearer role."
            )

        reconciled = self._reconcile(verdict, scored)
        if reconciled:
            reasoning.append(reconciled)

        timing_headline = self._headline(verdict, score, days)

        # Start from the accountable payload and add to it. Base keys win on
        # collision: the caller reading "headline" today should keep getting
        # the same kind of sentence.
        payload = dict(base_payload)
        payload.update(
            {
                "recommendation": verdict,
                "timing_verdict": verdict,
                "timing_headline": timing_headline,
                "timing_reasoning": reasoning,
                "scored_verdict": scored,
                "verdicts_reconciled": reconciled,
                "match_score": round(score, 1),
                "projected_match_score": round(projected, 1) if projected else None,
                "blocking_learning_days": days,
                "has_learning_plan": bool(plan.get("days")),
            }
        )
        payload["critical_gaps"] = base_payload.get("critical_gaps", critical)
        payload["headline"] = base_payload.get("headline") or timing_headline
        payload["reasoning"] = list(base_payload.get("reasoning") or []) + reasoning

        # What the user reads: the pipeline's summary (which leads with the
        # first concrete step) followed by the timing advice this workflow
        # exists to give.
        user = " ".join(part for part in (base_summary, timing_headline) if part)

        return {
            "recommendation": verdict,
            "user_recommendation": user or timing_headline,
            "all_analysis": merge_analysis(state, FINAL, payload),
            "_detail": "%s at %.1f/100" % (verdict, score),
            "_trace": {"label": NODE_LABELS[FINAL], "recommendation": verdict},
        }

    @staticmethod
    def _reconcile(verdict: str, scored: str) -> str:
        """Explain how this verdict sits beside the match calculator's.

        The two answer different questions and use different words, which
        looks like a disagreement if both are printed and neither is
        explained. The scorer says how *strong* the application is
        (APPLY/MAYBE/SKIP); this workflow says *when* to send it (now, after
        studying, or not at all). "MAYBE" and "APPLY_NOW" together mean
        "borderline, but if you are going to apply, do it now" - which is
        advice, where two bare labels would just be noise.

        Returns "" when there is nothing worth saying.
        """
        if not scored:
            return ""
        if verdict == SKIP and scored in ("APPLY", "MAYBE"):
            return (
                "The scorer rated this %s on fit alone; the timing verdict is "
                "still SKIP because the gaps take too long to close to be "
                "worth the application." % scored
            )
        if verdict == APPLY_NOW and scored == "MAYBE":
            return (
                "The scorer rated this MAYBE - borderline on fit. That is not "
                "a contradiction: it is borderline, and if you are going to "
                "apply, now beats waiting."
            )
        if verdict == APPLY_NOW and scored == "SKIP":
            return (
                "The scorer rated this SKIP on fit alone. Read the gaps below "
                "before sending it."
            )
        if verdict == APPLY_AFTER_LEARNING and scored == "SKIP":
            return (
                "The scorer rated this SKIP as the resume stands, which is "
                "why the study comes first rather than the application."
            )
        return ""

    @staticmethod
    def _headline(verdict: str, score: float, days: int) -> str:
        if verdict == APPLY_NOW:
            if days <= 0:
                return (
                    "Apply now - %.0f/100, and nothing needs closing first."
                    % score
                )
            # Saying "nothing here is worth waiting for" directly above "3
            # critical requirements unevidenced" is the headline arguing with
            # its own reasoning two lines later.
            return (
                "Apply now - %.0f/100. About %d day(s) of study is "
                "outstanding, but it is not worth holding the application "
                "for." % (score, days)
            )
        if verdict == APPLY_AFTER_LEARNING:
            return (
                "Worth applying, but about %d day(s) of study first turns a "
                "defensive interview into a confident one." % days
            )
        return (
            "Skip this one - %.0f/100, and the gaps are not the kind you close "
            "in a fortnight." % score
        )

    # -- Tracing ----------------------------------------------------------

    def _traced(self, name: str) -> Callable[[WorkflowState], Dict[str, Any]]:
        fn = getattr(self, "node_%s" % name)

        def _wrapped(state: WorkflowState) -> Dict[str, Any]:
            # Number by what has actually run, not by position in NODE_ORDER.
            # This graph branches, so a fixed index leaves holes: the sample
            # run traced 1,2,3,4,5,7,9,10 and looked like it had lost two
            # steps, when in truth it simply did not go that way.
            step = len(state.get("execution_trace") or []) + 1
            timer = StepTimer(name, step=step)
            try:
                with timer:
                    update = dict(fn(state) or {})
            except Exception as exc:
                logger.warning("Node '%s' failed: %s", name, exc, exc_info=True)
                return {
                    "all_analysis": merge_analysis(state, name, {"error": str(exc)}),
                    "execution_trace": [
                        timer.entry(
                            detail="%s: %s" % (exc.__class__.__name__, exc),
                            error=str(exc),
                            label=NODE_LABELS[name],
                        )
                    ],
                }

            detail = update.pop("_detail", None)
            timer.status = update.pop("_status", timer.status)
            extra = update.pop("_trace", None) or {}
            extra.setdefault("label", NODE_LABELS[name])

            slot = STATE_SLOTS.get(name)
            if slot:
                produced = (update.get("all_analysis") or {}).get(name)
                if produced is not None:
                    update[slot] = produced

            update["execution_trace"] = [timer.entry(detail=detail, **extra)]
            return update

        _wrapped.__name__ = "node_%s" % name
        return _wrapped

    # -- Execution --------------------------------------------------------

    def run(
        self,
        resume_text: str = "",
        job_description: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run the branching pipeline. Never raises."""
        self.collaboration.clear()
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

        try:
            final = self.compiled.invoke(state)
        except Exception as exc:
            logger.warning(
                "Conditional graph unavailable (%s); running nodes directly.", exc
            )
            final = self._run_sequentially(state)
            return self._result(
                final,
                note="Ran without LangGraph: %s: %s" % (exc.__class__.__name__, exc),
            )
        return self._result(final)

    #: The name the brief uses.
    def advanced_workflow(
        self, resume: str = "", job_description: str = "", **kwargs: Any
    ) -> Dict[str, Any]:
        """Alias for :meth:`run`, matching the brief's function name."""
        return self.run(resume, job_description, **kwargs)

    def _run_sequentially(self, state: WorkflowState) -> WorkflowState:
        """Walk the same branches without LangGraph.

        The fallback keeps a broken graph dependency to a slower run rather
        than an outage - and it takes the *same* conditional decisions, so the
        two paths cannot disagree about what the answer is.
        """
        current: Dict[str, Any] = dict(state)

        def step(name: str) -> None:
            update = self._traced(name)(current)  # type: ignore[arg-type]
            trace = update.pop("execution_trace", [])
            for key in ("decisions", "collaboration"):
                extra = update.pop(key, [])
                current[key] = list(current.get(key) or []) + list(extra)
            current.update(update)
            current["execution_trace"] = list(current.get("execution_trace") or [])
            current["execution_trace"].extend(trace)

        for name in (
            ANALYZE_JOB,
            EXTRACT_RESUME,
            CALCULATE_MATCH,
            DETECT_GAPS,
            OPTIMIZE_RESUME,
        ):
            step(name)

        if should_optimize(current) == RECALCULATE_MATCH:  # type: ignore[arg-type]
            step(RECALCULATE_MATCH)

        step(CHECK_LEARNABLE)
        if should_create_plan(current, self.learning_window_days) == CREATE_PLAN:  # type: ignore[arg-type]
            step(CREATE_PLAN)

        step(PREPARE_INTERVIEW)
        step(FINAL)
        return current  # type: ignore[return-value]

    # -- Result shaping ---------------------------------------------------

    def _result(
        self,
        state: WorkflowState,
        status: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        trace = list(state.get("execution_trace") or [])
        failed = [
            str(e.get("node")) for e in trace if e.get("status") == STATUS_ERROR
        ]
        skipped = [
            str(e.get("node")) for e in trace if e.get("status") == STATUS_SKIPPED
        ]
        if status is None:
            status = RUN_PARTIAL if (failed or skipped) else RUN_COMPLETED

        analysis = state.get("all_analysis") or {}
        initial = float(state.get("initial_match_score") or state.get("match_score") or 0.0)
        projected = float(state.get("projected_match_score") or 0.0)

        result: Dict[str, Any] = {
            # The brief's keys.
            "initial_match": round(initial, 1),
            "optimized_match": round(projected or initial, 1),
            "recommendation": state.get("recommendation") or SKIP,
            "gaps": analysis.get(DETECT_GAPS) or {},
            "optimizations": analysis.get(OPTIMIZE_RESUME) or {},
            "learning_plan": state.get("learning_plan") or None,
            "interview_prep": analysis.get(PREPARE_INTERVIEW) or {},
            # Everything needed to check the above.
            "match_result": analysis.get(CALCULATE_MATCH) or {},
            "analysis": analysis.get(ANALYZE_JOB) or {},
            "final": analysis.get(FINAL) or {},
            "user_recommendation": state.get("user_recommendation") or "",
            "match_score": round(float(state.get("match_score") or 0.0), 1),
            "projected_match_explained": analysis.get(RECALCULATE_MATCH) or {},
            "decisions": list(state.get("decisions") or []),
            "collaboration": list(state.get("collaboration") or []),
            "skills_found": list(state.get("skills_found") or []),
            "gaps_identified": list(state.get("gaps_identified") or []),
            "all_analysis": analysis,
            "execution_trace": trace,
            "path": [str(e.get("node")) for e in trace],
            "nodes_run": [str(e.get("node")) for e in trace],
            "nodes_failed": failed,
            "nodes_skipped": skipped,
            "total_duration_ms": round(
                sum(float(e.get("duration_ms") or 0.0) for e in trace), 2
            ),
            "status": status,
        }
        if note:
            result["note"] = note
            if not result["user_recommendation"]:
                result["user_recommendation"] = note
        return result

    # -- Introspection ----------------------------------------------------

    @staticmethod
    def describe() -> Dict[str, Any]:
        """Log-safe description of the branching graph and its conditions."""
        return describe_graph()


#: Module-level convenience matching the brief's free function.
def advanced_workflow(
    resume: str = "",
    job_description: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run the advanced workflow once."""
    return AdvancedWorkflow(**kwargs).run(resume, job_description)


__all__ = [
    "APPLY_AFTER_LEARNING",
    "APPLY_NOW",
    "SKIP",
    "AdvancedWorkflow",
    "advanced_workflow",
]
