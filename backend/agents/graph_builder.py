"""The LangGraph workflow that drives a full resume-vs-job analysis.

The graph is a straight line, because each step genuinely needs the one before
it::

    analyze_job -> extract_skills -> detect_gaps -> calculate_match -> END

* ``analyze_job``     reads the posting and pulls out required/preferred skills
* ``extract_skills``  reads the resume and pulls out what the candidate has
* ``detect_gaps``     subtracts one from the other
* ``calculate_match`` turns the comparison into a 0-100 score

Every node is wrapped by :meth:`WorkflowGraph._node`, which times it, catches
its exceptions and appends a line to ``execution_trace``. A node that fails is
recorded and the run continues with safe defaults, so a partial answer is still
returned rather than a stack trace.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from agents import AgentConfig
from agents.base_agent import (
    AgentError,
    GapAnalysisAgent,
    MatchScoringAgent,
    SkillExtractionAgent,
)
from agents.job_analyzer import JobAnalyzerAgent
from agents.gap_detector import gap_detector
from agents.resume_optimizer import resume_optimizer
from agents.interview_prep import interview_prep_agent
from agents.ollama_handler import LLMClient
from agents.workflow_state import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    StepTimer,
    WorkflowState,
    create_initial_state,
    executed_nodes,
    make_trace_entry,
    merge_analysis,
    total_duration_ms,
)
from utils.logger import get_logger

logger = get_logger(__name__)

#: The order nodes are wired in. Also the order they appear in the trace.
NODE_SEQUENCE = (
    "analyze_job",
    "extract_skills",
    "detect_gaps",
    "calculate_match",
    "optimize_resume",
    "prepare_interview",
)


class WorkflowError(RuntimeError):
    """Raised when the graph itself cannot run, as opposed to a node failing."""


class WorkflowGraph:
    """Builds, compiles and runs the CareerPilot analysis graph.

    The four agents are injectable so tests can hand in fakes and never touch
    a network. Compilation is lazy: constructing a ``WorkflowGraph`` is cheap,
    and the LangGraph import only happens on the first :meth:`execute`.
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        llm: Optional[LLMClient] = None,
        job_agent: Optional[Any] = None,
        skill_agent: Optional[Any] = None,
        gap_agent: Optional[Any] = None,
        match_agent: Optional[Any] = None,
        retriever: Optional[Any] = None,
    ) -> None:
        self.config = config or AgentConfig.from_settings()

        # One client shared by all four agents. Availability is cached on the
        # client, so a missing Ollama daemon costs a single probe per run
        # rather than one per node.
        self.llm = llm if llm is not None else LLMClient(self.config)

        # Optional ``ResumeIndexer``. When present the scorer quotes evidence
        # from the RAG index; when absent it scans the raw resume text. Left
        # unset by default so constructing a graph never loads the ML stack.
        self.retriever = retriever

        self.job_agent = job_agent or JobAnalyzerAgent(
            config=self.config, llm=self.llm
        )
        self.skill_agent = skill_agent or SkillExtractionAgent(
            config=self.config, llm=self.llm
        )
        self.gap_agent = gap_agent or GapAnalysisAgent(
            config=self.config, llm=self.llm
        )
        self.match_agent = match_agent or MatchScoringAgent(
            config=self.config, llm=self.llm
        )

        self._graph = None

    # -- Construction -----------------------------------------------------

    def build(self):
        """Wire the nodes and edges together and compile to a runnable graph."""
        from langgraph.graph import END, StateGraph

        builder = StateGraph(WorkflowState)

        builder.add_node("analyze_job", self._node("analyze_job", self._analyze_job))
        builder.add_node(
            "extract_skills", self._node("extract_skills", self._extract_skills)
        )
        builder.add_node("detect_gaps", self._node("detect_gaps", self._detect_gaps))
        builder.add_node(
            "calculate_match", self._node("calculate_match", self._calculate_match)
        )
        builder.add_node(
            "optimize_resume", self._node("optimize_resume", self._optimize_resume)
        )
        builder.add_node(
            "prepare_interview",
            self._node("prepare_interview", self._prepare_interview),
        )

        builder.set_entry_point("analyze_job")
        builder.add_edge("analyze_job", "extract_skills")
        builder.add_edge("extract_skills", "detect_gaps")
        builder.add_edge("detect_gaps", "calculate_match")
        # Runs last because it needs both the gaps and the score: the advice
        # depends on knowing which skills are missing (so it never suggests
        # claiming them) and which are evidenced (so it can lead with them).
        builder.add_edge("calculate_match", "optimize_resume")
        # Interview prep reads the same two results, plus nothing the optimiser
        # produces, but sits last because it is the final step chronologically:
        # you fix the resume, then you prepare for the conversation.
        builder.add_edge("optimize_resume", "prepare_interview")
        builder.add_edge("prepare_interview", END)

        return builder.compile()

    @property
    def graph(self):
        """The compiled graph, built once and reused."""
        if self._graph is None:
            self._graph = self.build()
        return self._graph

    # -- Tracing wrapper --------------------------------------------------

    def _node(
        self,
        name: str,
        fn: Callable[[WorkflowState], Dict[str, Any]],
    ) -> Callable[[WorkflowState], Dict[str, Any]]:
        """Wrap a node so it is timed, guarded and traced.

        Returning the trace entry as a one-item list works because
        ``execution_trace`` has an append reducer on the state.
        """
        step = NODE_SEQUENCE.index(name) + 1 if name in NODE_SEQUENCE else 0

        def _wrapped(state: WorkflowState) -> Dict[str, Any]:
            timer = StepTimer(name, step=step)
            try:
                with timer:
                    update = fn(state) or {}
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
                        )
                    ],
                }

            detail = update.pop("_detail", None)
            status = update.pop("_status", timer.status)
            extra = update.pop("_trace", None) or {}
            timer.status = status
            update["execution_trace"] = [timer.entry(detail=detail, **extra)]
            logger.info("Node '%s' finished in %.1fms", name, timer.duration_ms)
            return update

        _wrapped.__name__ = f"node_{name}"
        return _wrapped

    # -- Nodes ------------------------------------------------------------

    def _analyze_job(self, state: WorkflowState) -> Dict[str, Any]:
        description = (state.get("job_description") or "").strip()
        if not description:
            return {
                "all_analysis": merge_analysis(
                    state, "analyze_job", {"skipped": "no job description supplied"}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": "no job description supplied",
                "_trace": {"label": self.job_agent.label, "skills_extracted": 0,
                           "confidence": 0.0},
            }

        result = self.job_agent.run(job_description=description)
        payload = dict(result.output)
        payload["source"] = result.source
        if result.warning:
            payload["warning"] = result.warning

        return {
            "all_analysis": merge_analysis(state, "analyze_job", payload),
            "_trace": self.job_agent.trace_fields(payload),
            "_detail": (
                f"{payload.get('title', 'role')} "
                f"[{payload.get('role_type', 'general')}, "
                f"{payload.get('experience_level', 'unspecified')}]: "
                f"{len(payload.get('required_skills') or [])} required skill(s) "
                f"via {result.source}"
            ),
        }

    def _extract_skills(self, state: WorkflowState) -> Dict[str, Any]:
        resume = (state.get("resume_text") or "").strip()
        if not resume:
            return {
                "skills_found": [],
                "all_analysis": merge_analysis(
                    state, "extract_skills", {"skipped": "no resume text supplied"}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": "no resume text supplied",
            }

        result = self.skill_agent.run(resume_text=resume)
        skills = list(result.output.get("skills") or [])
        payload = {"skills": skills, "source": result.source}
        if result.warning:
            payload["warning"] = result.warning

        return {
            "skills_found": skills,
            "all_analysis": merge_analysis(state, "extract_skills", payload),
            "_detail": f"found {len(skills)} skill(s) [{result.source}]",
        }

    def _detect_gaps(self, state: WorkflowState) -> Dict[str, Any]:
        job = (state.get("all_analysis") or {}).get("analyze_job") or {}
        required = list(job.get("required_skills") or [])
        preferred = list(job.get("preferred_skills") or [])
        candidate = list(state.get("skills_found") or [])

        if not required and not preferred:
            return {
                "gaps_identified": [],
                "all_analysis": merge_analysis(
                    state, "detect_gaps", {"skipped": "job listed no skills"}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": "job listed no skills to compare against",
            }

        result = self.gap_agent.run(
            candidate_skills=candidate or ["none listed"],
            required_skills=required,
            preferred_skills=preferred,
        )
        gaps = list(result.output.get("gaps") or [])
        payload = dict(result.output)
        payload["source"] = result.source
        if result.warning:
            payload["warning"] = result.warning

        # The agent above answers "what is missing". The detector answers
        # "which of those cost you the job, and how long to fix". It is kept
        # separate and additive so the plain gaps list stays the contract the
        # rest of the workflow depends on.
        report = self._gap_report(state, job, candidate)
        if report:
            payload["gap_report"] = report

        detail = f"{len(gaps)} gap(s) against {len(required)} requirement(s)"
        trace: Dict[str, Any] = {"label": gap_detector.label}
        if report:
            trace["critical_gaps"] = report["critical_count"]
            trace["total_learning_weeks"] = report["total_learning_time_weeks"]
            detail += (
                f"; {report['critical_count']} critical, "
                f"~{report['total_learning_time_weeks']} week(s) to close"
            )

        return {
            "gaps_identified": gaps,
            "all_analysis": merge_analysis(state, "detect_gaps", payload),
            "_detail": detail,
            "_trace": trace,
        }

    def _gap_report(
        self,
        state: WorkflowState,
        job: Dict[str, Any],
        candidate: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Cost and prioritise the gaps, or return None if that fails.

        Wrapped because the learning plan is an enrichment: if it breaks, the
        workflow should still report the gaps rather than fall over.

        No ``match_data`` is passed - this node runs before the match is
        scored, so the detector computes the difference itself.
        """
        try:
            return gap_detector.detect_gaps(
                {
                    "skills": candidate,
                    "resume_text": state.get("resume_text") or "",
                },
                job,
                None,
                job_text=state.get("job_description") or "",
            )
        except Exception:  # noqa: BLE001 - enrichment must not break the run
            logger.exception("Gap detector failed; reporting plain gaps only")
            return None

    def _calculate_match(self, state: WorkflowState) -> Dict[str, Any]:
        analysis = state.get("all_analysis") or {}
        job = analysis.get("analyze_job") or {}
        resume = (state.get("resume_text") or "").strip()

        if not resume:
            return {
                "match_score": 0.0,
                "all_analysis": merge_analysis(
                    state, "calculate_match", {"skipped": "no resume text supplied"}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": "no resume text supplied",
                "_trace": {
                    "label": self.match_agent.label,
                    "overall_score": 0.0,
                    "recommendation": "SKIP",
                },
            }

        result = self.match_agent.run(
            resume_text=resume,
            # The skills node has already done this work; reusing it keeps the
            # score consistent with the gaps reported one step earlier.
            skills_found=state.get("skills_found") or [],
            job_analysis=job,
            retriever=self.retriever,
        )
        payload = dict(result.output)
        payload["source"] = result.source
        # `overall_match` is None when the advert specified nothing to assess.
        # `match_score` stays a float because the branch conditions downstream
        # compare it numerically, but the trace line must not read "0.0/100"
        # next to a verdict of NOT_SCORED.
        measured = payload.get("overall_match")
        score = float(measured or 0.0)
        verdict = payload.get("recommendation", "SKIP")

        return {
            "match_score": score,
            "all_analysis": merge_analysis(state, "calculate_match", payload),
            "_trace": self.match_agent.trace_fields(payload),
            "_detail": (
                f"score {score:.1f}/100 -> {verdict}"
                if measured is not None
                else f"nothing to score against -> {verdict}"
            ),
        }

    def _optimize_resume(self, state: WorkflowState) -> Dict[str, Any]:
        analysis = state.get("all_analysis") or {}
        job = analysis.get("analyze_job") or {}
        resume = (state.get("resume_text") or "").strip()

        if not resume or not job:
            reason = "no resume text supplied" if not resume else "no job analysis to tailor to"
            return {
                "all_analysis": merge_analysis(state, "optimize_resume", {"skipped": reason}),
                "_status": STATUS_SKIPPED,
                "_detail": reason,
                "_trace": {"label": resume_optimizer.label, "improvements": 0},
            }

        report = resume_optimizer.optimize_resume(
            {
                "resume_text": resume,
                "skills": state.get("skills_found") or [],
            },
            # The advert text lets the optimiser weight keywords by how often
            # the employer repeats them, which is its strongest signal.
            dict(job, job_description=job.get("job_description") or state.get("job_description") or ""),
            (analysis.get("detect_gaps") or {}).get("gap_report"),
            analysis.get("calculate_match"),
        )

        count = len(report.get("improvements") or [])
        high = report.get("high_impact_count", 0)
        return {
            "all_analysis": merge_analysis(state, "optimize_resume", report),
            "_detail": f"{count} suggestion(s), {high} high impact",
            "_trace": {
                "label": resume_optimizer.label,
                "improvements": count,
                "high_impact": high,
                "confidence": report.get("confidence", 0.0),
            },
        }

    def _prepare_interview(self, state: WorkflowState) -> Dict[str, Any]:
        analysis = state.get("all_analysis") or {}
        job = analysis.get("analyze_job") or {}
        resume = (state.get("resume_text") or "").strip()

        if not resume or not job:
            reason = (
                "no resume text supplied" if not resume else "no job analysis to prepare for"
            )
            return {
                "all_analysis": merge_analysis(
                    state, "prepare_interview", {"skipped": reason}
                ),
                "_status": STATUS_SKIPPED,
                "_detail": reason,
                "_trace": {"label": interview_prep_agent.label, "questions_generated": 0},
            }

        report = interview_prep_agent.prepare_interview(
            dict(
                job,
                job_description=job.get("job_description")
                or state.get("job_description")
                or "",
            ),
            {"resume_text": resume, "skills": state.get("skills_found") or []},
            (analysis.get("detect_gaps") or {}).get("gap_report"),
            analysis.get("calculate_match"),
        )

        count = report.get("question_count", 0)
        days = report.get("prep_days", 0)
        success = report.get("success_rate_prediction", 0.0)
        return {
            "all_analysis": merge_analysis(state, "prepare_interview", report),
            "_detail": (
                f"{count} question(s), {days} day(s) of prep, "
                f"{round(success * 100)}% predicted"
            ),
            "_trace": {
                "label": interview_prep_agent.label,
                "questions_generated": count,
                "prep_days": days,
                "success_prediction": success,
                "difficulty": report.get("interview_difficulty"),
            },
        }

    # -- Execution --------------------------------------------------------

    def execute(self, state: Optional[WorkflowState] = None, **kwargs: Any) -> WorkflowState:
        """Run the whole workflow and return the final state.

        Accepts either a prepared state or keyword arguments::

            graph.execute(resume_text=..., job_description=...)

        Missing keys are filled in with defaults, so callers cannot accidentally
        hand a node a state that is half-built.
        """
        if state is None:
            state = create_initial_state(**kwargs)
        else:
            merged = create_initial_state()
            merged.update(state)  # type: ignore[typeddict-item]
            merged.update(kwargs)  # type: ignore[typeddict-item]
            state = merged

        if not (state.get("resume_text") or "").strip() and not (
            state.get("job_description") or ""
        ).strip():
            raise WorkflowError(
                "Nothing to analyse: provide resume_text, job_description, or both."
            )

        logger.info("Starting workflow with nodes: %s", ", ".join(NODE_SEQUENCE))
        try:
            final = self.graph.invoke(state)
        except Exception as exc:
            raise WorkflowError(f"Workflow execution failed: {exc}") from exc

        logger.info(
            "Workflow finished: %s in %.1fms",
            " -> ".join(executed_nodes(final)),
            total_duration_ms(final),
        )
        return final

    def run(self, resume_text: str = "", job_description: str = "", **kwargs: Any) -> WorkflowState:
        """Convenience alias for the common two-argument call."""
        return self.execute(
            resume_text=resume_text, job_description=job_description, **kwargs
        )

    # -- Introspection ----------------------------------------------------

    @staticmethod
    def node_names() -> List[str]:
        return list(NODE_SEQUENCE)

    def node_impl(self, name: str) -> Callable[[WorkflowState], Dict[str, Any]]:
        """The *untraced* body of a node, so another graph can reuse it.

        :class:`~agents.complete_workflow.CompleteWorkflow` wires a longer
        pipeline over the same steps. Handing it the real node bodies is
        deliberate: two orchestrators that each re-implemented "how do we score
        this resume" would eventually disagree, and the first anyone would know
        of it is two different numbers for the same candidate. There is one
        implementation of each step, and both graphs call it.

        Returns the raw callable; the caller supplies its own timing, tracing
        and error handling, since step numbers differ between the two graphs.
        """
        try:
            return getattr(self, f"_{name}")  # type: ignore[no-any-return]
        except AttributeError:
            raise KeyError(f"No such node: {name!r}") from None

    def describe(self) -> Dict[str, Any]:
        """Log-safe description of the graph and its LLM configuration."""
        return {
            "nodes": list(NODE_SEQUENCE),
            "edges": [
                {"from": a, "to": b}
                for a, b in zip(NODE_SEQUENCE, NODE_SEQUENCE[1:])
            ]
            + [{"from": NODE_SEQUENCE[-1], "to": "END"}],
            "entry_point": NODE_SEQUENCE[0],
            "llm": self.config.describe(),
        }


def build_workflow(config: Optional[AgentConfig] = None) -> WorkflowGraph:
    """Factory kept for readability at call sites."""
    return WorkflowGraph(config=config)


__all__ = [
    "WorkflowGraph",
    "WorkflowError",
    "NODE_SEQUENCE",
    "build_workflow",
    "make_trace_entry",
    "STATUS_OK",
    "STATUS_ERROR",
    "AgentError",
]
