"""The decision graph: conditional edges, and the reasoning behind each one.

The linear pipeline in :mod:`agents.complete_workflow` runs seven nodes in a
row. This one branches::

    analyze_job -> extract_resume -> calculate_match -> detect_gaps
                -> optimize_resume
                       |
              match < 70? -- yes --> re_calculate_match --.
                       |                                   |
                       '------------ no ------------------>'
                                                           |
                                              check_gaps_learnable
                                                           |
                     worth learning first? -- yes --> create_learning_plan --.
                                                           |                 |
                                                           '---- no ---------'
                                                           |
                                                  interview_prep
                                                           |
                                              final_recommendation -> END

Three places where this deliberately departs from the graph in the brief, each
because the brief's version cannot run correctly.

**Gaps are detected before the branch, not inside it.** The brief reaches
``detect_gaps`` only through the ``optimize_resume`` arm, then routes both arms
into ``check_gaps_learnable`` - which reads gaps. A candidate scoring 70 or
above therefore arrives at a node that inspects a list nobody produced. The
same hole is in the Task 1 pseudocode, where ``gaps`` is assigned inside
``if match.score < 70:`` and read unconditionally afterwards; on the sample
resume, which scores 73.6, that is an ``UnboundLocalError`` on every run.

**The optimiser runs after the gap detector, not before it.** The brief orders
``optimize_resume -> re_calculate_match -> detect_gaps``. But the optimiser
takes the gap report as an input and uses it to build
``keywords_blocked_by_gaps`` - the list of skills the candidate must *not*
claim. Run it before the gaps exist and that guard is empty, and the module's
entire reason for existing (it will not tell you to claim a skill you do not
have) quietly stops working. Ordering here is not a stylistic choice.

**The optimiser runs on both arms; only the re-score is conditional.** Making
the optimiser itself conditional would mean a candidate scoring 71 gets no
resume advice at all, which is a regression against the linear pipeline that
gives everyone suggestions. What is genuinely worth conditioning is the second
scoring pass, because that is the expensive step and it can only change the
outcome when the first score was short.

Every branch writes a row into ``state["decisions"]`` recording which way it
went and on what number, so the choice is visible in the result rather than
implied by which nodes happen to appear in the trace.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from agents.workflow_state import WorkflowState
from utils.logger import get_logger

logger = get_logger(__name__)

#: Below this the resume is worth a second look after rewording.
OPTIMIZE_BELOW = 70.0

#: At or above this, applying now beats waiting. See `should_create_plan`.
STRONG_MATCH = 75.0

#: Below this, learning first will not rescue the application either.
FLOOR_MATCH = 50.0

#: The window the brief specifies for "learnable soon".
DEFAULT_LEARNING_WINDOW_DAYS = 14

#: Node names. Constants because the conditional functions return them, and a
#: typo in a returned string is a runtime error a long way from its cause.
ANALYZE_JOB = "analyze_job"
EXTRACT_RESUME = "extract_resume"
CALCULATE_MATCH = "calculate_match"
DETECT_GAPS = "detect_gaps"
OPTIMIZE_RESUME = "optimize_resume"
RECALCULATE_MATCH = "re_calculate_match"
CHECK_LEARNABLE = "check_gaps_learnable"
CREATE_PLAN = "create_learning_plan"
# Verb phrase, like every other node, and deliberately *not* "interview_prep":
# LangGraph refuses to compile a graph whose node name collides with a state
# channel, and ``interview_prep`` is a key on WorkflowState. The linear
# pipeline already used this name (complete_workflow.NODE_TO_SLOT); the graph
# disagreeing with it is what made every advanced run fall back to running the
# nodes by hand.
PREPARE_INTERVIEW = "prepare_interview"
FINAL = "final_recommendation"

#: Order used for step numbering and for the sequential fallback. It is the
#: longest path through the graph; nodes skipped by a branch simply do not run.
NODE_ORDER = (
    ANALYZE_JOB,
    EXTRACT_RESUME,
    CALCULATE_MATCH,
    DETECT_GAPS,
    OPTIMIZE_RESUME,
    RECALCULATE_MATCH,
    CHECK_LEARNABLE,
    CREATE_PLAN,
    PREPARE_INTERVIEW,
    FINAL,
)

NODE_LABELS = {
    ANALYZE_JOB: "Job Analyzer",
    EXTRACT_RESUME: "Resume Extraction",
    CALCULATE_MATCH: "Match Calculator",
    DETECT_GAPS: "Gap Detector",
    OPTIMIZE_RESUME: "Resume Optimizer",
    RECALCULATE_MATCH: "Match Calculator (re-run)",
    CHECK_LEARNABLE: "Learnability Check",
    CREATE_PLAN: "Learning Path",
    PREPARE_INTERVIEW: "Interview Prep",
    FINAL: "Final Recommendation",
}

#: The three outcomes.
APPLY_NOW = "APPLY_NOW"
APPLY_AFTER_LEARNING = "APPLY_AFTER_LEARNING"
SKIP = "SKIP"


def _score(state: WorkflowState) -> float:
    """The match score, whichever pass produced it."""
    try:
        return float(state.get("match_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _gap_report(state: WorkflowState) -> Dict[str, Any]:
    """The detector's costed report, wherever the node parked it."""
    gaps = state.get("gaps") or {}
    report = gaps.get("gap_report") if isinstance(gaps, dict) else None
    if isinstance(report, dict):
        return report
    analysis = (state.get("all_analysis") or {}).get(DETECT_GAPS) or {}
    report = analysis.get("gap_report")
    return report if isinstance(report, dict) else (gaps if isinstance(gaps, dict) else {})


def blocking_days(state: WorkflowState) -> int:
    """Days of study standing between this candidate and the requirements.

    Critical gaps only. The brief's conditional graph sums ``g['days']`` over
    *every* gap, which counts nice-to-haves the employer listed as optional -
    enough to push almost any real advert past a fortnight and route everyone
    down the same arm. Its own Task 1 pseudocode uses critical gaps only, and
    that is the one that describes a real decision.
    """
    report = _gap_report(state)
    days = report.get("blocking_learning_days")
    if days is not None:
        try:
            return int(days)
        except (TypeError, ValueError):
            pass
    total = 0
    for gap in report.get("critical_gaps") or []:
        try:
            total += int(gap.get("learning_time_days") or 0)
        except (TypeError, ValueError):
            continue
    return total


def critical_count(state: WorkflowState) -> int:
    """How many critical gaps the detector found.

    Falls back to counting the listed gaps when the report has no explicit
    count, so a branch decision is never taken on a silently missing key.
    """
    report = _gap_report(state)
    try:
        return int(report.get("critical_count") or 0)
    except (TypeError, ValueError):
        return len(report.get("critical_gaps") or [])


# -- Conditional edges ----------------------------------------------------


def should_optimize(state: WorkflowState) -> str:
    """Is a second scoring pass worth running?

    Only when the first score fell short. Above the threshold the resume is
    already carrying the application, and re-scoring it cannot change the
    advice.
    """
    score = _score(state)
    if score < OPTIMIZE_BELOW:
        return RECALCULATE_MATCH
    return CHECK_LEARNABLE


def should_create_plan(
    state: WorkflowState,
    window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
) -> str:
    """Should the candidate learn something before applying?

    The brief's rule is ``if learning_time <= 14: APPLY_AFTER_LEARNING``. Taken
    literally it gives bad advice at both ends.

    A candidate with **no** critical gaps sums to zero days, and zero is less
    than fourteen - so the strongest applicants are told to wait two weeks and
    study nothing. That is the degenerate case, and it is the common one.

    A candidate matching at 88% with a single three-day gap is told to delay a
    live application by three days. Adverts close. Someone already over the
    bar should send it and learn in parallel, which is what the plan is then
    offered as.

    So: learn first only when the gaps are real, the window is enough, and the
    match is not already strong enough to carry the application.
    """
    days = blocking_days(state)
    if days <= 0:
        return PREPARE_INTERVIEW
    if _score(state) >= STRONG_MATCH:
        return PREPARE_INTERVIEW
    if days <= window_days:
        return CREATE_PLAN
    return PREPARE_INTERVIEW


def explain_optimize(state: WorkflowState) -> Dict[str, Any]:
    """The row written into ``state["decisions"]`` for the first branch."""
    score = _score(state)
    took = should_optimize(state)
    return {
        "decision": "should_optimize",
        "branch": took,
        "match_score": round(score, 1),
        "threshold": OPTIMIZE_BELOW,
        "reason": (
            "Match %.1f is below %.0f, so the resume is re-scored after the "
            "optimiser's truthful suggestions." % (score, OPTIMIZE_BELOW)
            if took == RECALCULATE_MATCH
            else "Match %.1f is at or above %.0f; rewording cannot change the "
            "advice, so the second pass is skipped." % (score, OPTIMIZE_BELOW)
        ),
    }


def explain_plan(
    state: WorkflowState,
    window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
) -> Dict[str, Any]:
    """The row written into ``state["decisions"]`` for the second branch."""
    days = blocking_days(state)
    score = _score(state)
    took = should_create_plan(state, window_days)

    if days <= 0:
        reason = (
            "No critical requirement is unevidenced, so there is nothing to "
            "learn first."
        )
    elif score >= STRONG_MATCH:
        reason = (
            "Match %.1f already clears %.0f. Apply now and close the %d day(s) "
            "of gaps in parallel - the advert will not wait."
            % (score, STRONG_MATCH, days)
        )
    elif days <= window_days:
        reason = (
            "%d day(s) of study closes the critical gaps, inside the %d-day "
            "window." % (days, window_days)
        )
    else:
        reason = (
            "%d day(s) of study is more than the %d-day window, so learning "
            "first is not the shortcut here." % (days, window_days)
        )

    return {
        "decision": "should_create_plan",
        "branch": took,
        "blocking_days": days,
        "window_days": window_days,
        "match_score": round(score, 1),
        "reason": reason,
    }


def final_recommendation(
    state: WorkflowState,
    window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
) -> str:
    """APPLY_NOW, APPLY_AFTER_LEARNING or SKIP.

    Deliberately reads ``match_score`` - the score the resume *actually* earns
    - and never the projected one. Letting a projection flip a SKIP into an
    APPLY would be advising someone to apply on the strength of a resume they
    have not written yet.
    """
    score = _score(state)
    days = blocking_days(state)

    if score >= STRONG_MATCH:
        return APPLY_NOW
    if 0 < days <= window_days and score >= FLOOR_MATCH:
        return APPLY_AFTER_LEARNING
    if score >= OPTIMIZE_BELOW - 5.0:
        return APPLY_NOW
    return SKIP


def build_conditional_graph(
    nodes: Dict[str, Callable[[WorkflowState], Dict[str, Any]]],
    window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
) -> Any:
    """Compile the branching graph from a mapping of name to callable.

    ``nodes`` is injected rather than constructed here so this module stays
    testable without the agents, and so :class:`AdvancedWorkflow` can wrap each
    node in its own tracing.
    """
    from langgraph.graph import END, StateGraph

    missing = [name for name in NODE_ORDER if name not in nodes]
    if missing:
        raise ValueError("missing node implementations: %s" % ", ".join(missing))

    builder = StateGraph(WorkflowState)
    for name in NODE_ORDER:
        builder.add_node(name, nodes[name])

    builder.set_entry_point(ANALYZE_JOB)
    builder.add_edge(ANALYZE_JOB, EXTRACT_RESUME)
    builder.add_edge(EXTRACT_RESUME, CALCULATE_MATCH)
    # Gaps before the optimiser: it needs them to know what must not be
    # claimed, and before the branch so both arms can read them.
    builder.add_edge(CALCULATE_MATCH, DETECT_GAPS)
    builder.add_edge(DETECT_GAPS, OPTIMIZE_RESUME)

    builder.add_conditional_edges(
        OPTIMIZE_RESUME,
        should_optimize,
        {RECALCULATE_MATCH: RECALCULATE_MATCH, CHECK_LEARNABLE: CHECK_LEARNABLE},
    )
    builder.add_edge(RECALCULATE_MATCH, CHECK_LEARNABLE)

    builder.add_conditional_edges(
        CHECK_LEARNABLE,
        lambda state: should_create_plan(state, window_days),
        {CREATE_PLAN: CREATE_PLAN, PREPARE_INTERVIEW: PREPARE_INTERVIEW},
    )
    builder.add_edge(CREATE_PLAN, PREPARE_INTERVIEW)
    builder.add_edge(PREPARE_INTERVIEW, FINAL)
    builder.add_edge(FINAL, END)

    return builder.compile()


def describe_graph() -> Dict[str, Any]:
    """Log-safe description, including which edges are conditional."""
    return {
        "nodes": list(NODE_ORDER),
        "labels": dict(NODE_LABELS),
        "edges": [
            {"from": ANALYZE_JOB, "to": EXTRACT_RESUME},
            {"from": EXTRACT_RESUME, "to": CALCULATE_MATCH},
            {"from": CALCULATE_MATCH, "to": DETECT_GAPS},
            {"from": DETECT_GAPS, "to": OPTIMIZE_RESUME},
            {"from": RECALCULATE_MATCH, "to": CHECK_LEARNABLE},
            {"from": CREATE_PLAN, "to": PREPARE_INTERVIEW},
            {"from": PREPARE_INTERVIEW, "to": FINAL},
            {"from": FINAL, "to": "END"},
        ],
        "conditional_edges": [
            {
                "from": OPTIMIZE_RESUME,
                "question": "Is the match below %.0f?" % OPTIMIZE_BELOW,
                "targets": [RECALCULATE_MATCH, CHECK_LEARNABLE],
            },
            {
                "from": CHECK_LEARNABLE,
                "question": (
                    "Are the critical gaps worth closing before applying?"
                ),
                "targets": [CREATE_PLAN, PREPARE_INTERVIEW],
            },
        ],
        "outcomes": [APPLY_NOW, APPLY_AFTER_LEARNING, SKIP],
    }


def executed_path(trace: List[Dict[str, Any]]) -> List[str]:
    """The nodes that actually ran, in order - the path through the graph."""
    return [str(entry.get("node")) for entry in trace or []]


__all__ = [
    "APPLY_AFTER_LEARNING",
    "APPLY_NOW",
    "SKIP",
    "ANALYZE_JOB",
    "CALCULATE_MATCH",
    "CHECK_LEARNABLE",
    "CREATE_PLAN",
    "DETECT_GAPS",
    "EXTRACT_RESUME",
    "FINAL",
    "PREPARE_INTERVIEW",
    "NODE_LABELS",
    "NODE_ORDER",
    "OPTIMIZE_RESUME",
    "RECALCULATE_MATCH",
    "DEFAULT_LEARNING_WINDOW_DAYS",
    "FLOOR_MATCH",
    "OPTIMIZE_BELOW",
    "STRONG_MATCH",
    "blocking_days",
    "build_conditional_graph",
    "critical_count",
    "describe_graph",
    "executed_path",
    "explain_optimize",
    "explain_plan",
    "final_recommendation",
    "should_create_plan",
    "should_optimize",
]
