"""The shared state that flows through the LangGraph workflow.

LangGraph passes one dictionary from node to node. Each node returns only the
keys it wants to change, and LangGraph merges them in.

Merging matters: by default a returned key *replaces* the old value. That is
what we want for ``match_score``, but wrong for ``execution_trace``, which must
accumulate. The ``Annotated[..., operator.add]`` marker below tells LangGraph
to concatenate instead of overwrite, so every node can simply return its own
one-item trace list.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ``typing_extensions`` rather than ``typing``: on Python 3.9 the stdlib
# TypedDict does not preserve ``Annotated`` metadata, which LangGraph needs in
# order to find the reducer.
from typing_extensions import Annotated, TypedDict

#: Trace status values.
#: ``completed`` is the success state. ``STATUS_OK`` is kept as an alias so the
#: older name still reads naturally in code that predates the rename.
STATUS_COMPLETED = "completed"
STATUS_OK = STATUS_COMPLETED
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


def _append(
    existing: Optional[List[Dict[str, Any]]],
    new: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Reducer for ``execution_trace``: concatenate instead of overwrite.

    Written by hand rather than using ``operator.add`` so that a ``None`` from
    a node that returned nothing cannot blow the whole run up.
    """
    return list(existing or []) + list(new or [])


class WorkflowState(TypedDict, total=False):
    """Everything the workflow reads and writes.

    ``total=False`` means every key is optional, so a caller can start a run
    with just a resume and a job description.
    """

    #: The candidate's resume, as plain text.
    resume_text: str
    #: The raw job posting text.
    job_description: str
    #: Skills evidenced in the resume, lowercase.
    skills_found: List[str]
    #: Required skills the candidate does not have, lowercase.
    gaps_identified: List[str]
    #: Overall fit, 0-100.
    match_score: float
    #: Free-form bucket for each node's full output, keyed by node name.
    all_analysis: Dict[str, Any]

    # -- Named slots used by the complete workflow ------------------------
    #
    # `all_analysis` already holds every node's output keyed by node name, and
    # these duplicate a few of those entries under stable, readable names. The
    # duplication is deliberate: `all_analysis["analyze_job"]` couples callers
    # to a node id, whereas `analysis` survives the graph being rewired.

    #: Job analyser output.
    analysis: Dict[str, Any]
    #: Match calculator output.
    match_result: Dict[str, Any]
    #: Gap detector output.
    gaps: Dict[str, Any]
    #: Resume optimiser output.
    resume_optimizations: Dict[str, Any]
    #: Interview prep output.
    interview_prep: Dict[str, Any]
    #: The final plain-English verdict handed to the user.
    user_recommendation: str

    # -- Advanced workflow ------------------------------------------------
    #
    # The conditional graph revisits the match after the optimiser has spoken,
    # so one score is no longer enough: `initial_match_score` is what the
    # resume as written earns, and `projected_match_score` is what it would
    # earn after truthful rewording. They are kept apart on purpose - see
    # `agents/advanced_workflow.py` for why collapsing them would inflate the
    # headline number.

    #: What the resume as written scores, before any rewording.
    initial_match_score: float
    #: What it would score after the optimiser's truthful suggestions only.
    projected_match_score: float
    #: Day-by-day study plan, when one was asked for and fits.
    learning_plan: Dict[str, Any]
    #: Which way each conditional edge went, and why.
    decisions: Annotated[List[Dict[str, Any]], _append]
    #: Questions agents asked each other, in order.
    collaboration: Annotated[List[Dict[str, Any]], _append]
    #: APPLY_NOW / APPLY_AFTER_LEARNING / SKIP.
    recommendation: str

    #: Append-only log of which nodes ran, in order. See the reducer note above.
    execution_trace: Annotated[List[Dict[str, Any]], _append]


#: Alias matching the name used in the project spec.
StateDict = WorkflowState


def create_initial_state(
    resume_text: str = "",
    job_description: str = "",
    **extra: Any,
) -> WorkflowState:
    """Build a fully populated starting state.

    Every key is given a value so nodes never have to guard against a missing
    one, and so the shape of the state is obvious from a single place.
    """
    state: WorkflowState = {
        "resume_text": resume_text or "",
        "job_description": job_description or "",
        "skills_found": [],
        "gaps_identified": [],
        "match_score": 0.0,
        "all_analysis": {},
        "analysis": {},
        "match_result": {},
        "gaps": {},
        "resume_optimizations": {},
        "interview_prep": {},
        "user_recommendation": "",
        "initial_match_score": 0.0,
        "projected_match_score": 0.0,
        "learning_plan": {},
        "decisions": [],
        "collaboration": [],
        "recommendation": "",
        "execution_trace": [],
    }
    state.update(extra)  # type: ignore[typeddict-item]
    return state


def make_trace_entry(
    node: str,
    status: str = STATUS_OK,
    step: int = 0,
    duration_ms: float = 0.0,
    detail: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """One line in the execution trace."""
    entry: Dict[str, Any] = {
        "step": step,
        "node": node,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        entry["detail"] = detail
    entry.update(extra)
    return entry


def merge_analysis(
    state: WorkflowState,
    node: str,
    payload: Any,
) -> Dict[str, Any]:
    """Add one node's output to ``all_analysis`` without dropping the others.

    ``all_analysis`` has no reducer, so a node returning it replaces the whole
    dict. Copying the existing contents first keeps earlier nodes' results.
    """
    merged = dict(state.get("all_analysis") or {})
    merged[node] = payload
    return merged


def trace_summary(state: WorkflowState) -> List[str]:
    """The node order as a readable list, e.g. ``['analyze_job (ok, 3.1ms)']``."""
    return [
        f"{entry.get('node')} ({entry.get('status')}, {entry.get('duration_ms')}ms)"
        for entry in state.get("execution_trace") or []
    ]


def executed_nodes(state: WorkflowState) -> List[str]:
    """Just the node names, in the order they ran."""
    return [str(entry.get("node")) for entry in state.get("execution_trace") or []]


def has_errors(state: WorkflowState) -> bool:
    """True if any node recorded a failure."""
    return any(
        entry.get("status") == STATUS_ERROR
        for entry in state.get("execution_trace") or []
    )


def total_duration_ms(state: WorkflowState) -> float:
    """Sum of every node's runtime."""
    return round(
        sum(
            float(entry.get("duration_ms") or 0.0)
            for entry in state.get("execution_trace") or []
        ),
        2,
    )


class StepTimer:
    """Context manager that measures a node and builds its trace entry.

    Usage::

        with StepTimer("extract_skills", step=2) as timer:
            ...
        return {"execution_trace": [timer.entry(detail="found 7 skills")]}
    """

    def __init__(self, node: str, step: int = 0) -> None:
        self.node = node
        self.step = step
        self.status = STATUS_OK
        self._started = 0.0
        self.duration_ms = 0.0

    def __enter__(self) -> "StepTimer":
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.duration_ms = (time.perf_counter() - self._started) * 1000
        if exc_type is not None:
            self.status = STATUS_ERROR
        return False  # never swallow the exception

    def entry(self, **extra: Any) -> Dict[str, Any]:
        """Render this step as a trace row, with any extra columns merged in."""
        return make_trace_entry(
            self.node,
            status=self.status,
            step=self.step,
            duration_ms=self.duration_ms,
            **extra,
        )


__all__ = [
    "WorkflowState",
    "StateDict",
    "StepTimer",
    "STATUS_COMPLETED",
    "STATUS_OK",
    "STATUS_ERROR",
    "STATUS_SKIPPED",
    "create_initial_state",
    "make_trace_entry",
    "merge_analysis",
    "trace_summary",
    "executed_nodes",
    "has_errors",
    "total_duration_ms",
]
