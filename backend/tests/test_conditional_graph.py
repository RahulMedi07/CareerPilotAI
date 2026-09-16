"""Tests for the branching decisions in ``agents.conditional_graph``.

Most of these exist because the specification this module was written from
contained routing rules that read plausibly and misbehave on real inputs. The
tests below pin the corrected behaviour so it cannot quietly regress back to
the version that looked right on paper.
"""

from __future__ import annotations

import pytest

from agents.conditional_graph import (
    APPLY_AFTER_LEARNING,
    APPLY_NOW,
    CHECK_LEARNABLE,
    CREATE_PLAN,
    FLOOR_MATCH,
    NODE_ORDER,
    OPTIMIZE_BELOW,
    PREPARE_INTERVIEW,
    RECALCULATE_MATCH,
    SKIP,
    STRONG_MATCH,
    blocking_days,
    build_conditional_graph,
    critical_count,
    describe_graph,
    executed_path,
    explain_optimize,
    explain_plan,
    final_recommendation,
    should_create_plan,
    should_optimize,
)
from agents.workflow_state import create_initial_state


def state(score=80.0, gaps=None, projected=None, plan=None):
    """A workflow state carrying only what the routers actually read."""
    built = {"match_score": score}
    if projected is not None:
        built["projected_match_score"] = projected
    if plan is not None:
        built["learning_plan"] = plan
    listed = list(gaps or [])
    built["gaps"] = {
        "gap_report": {
            "critical_gaps": listed,
            "critical_count": len(listed),
        }
    }
    return built


def gap(skill, days, importance="CRITICAL"):
    return {"skill": skill, "learning_time_days": days, "importance": importance}


class TestShouldOptimize:
    def test_a_weak_match_goes_for_a_second_pass(self):
        assert should_optimize(state(score=55.0)) == RECALCULATE_MATCH

    def test_a_strong_match_skips_the_second_pass(self):
        assert should_optimize(state(score=88.0)) == CHECK_LEARNABLE

    def test_the_threshold_itself_counts_as_strong(self):
        assert should_optimize(state(score=OPTIMIZE_BELOW)) == CHECK_LEARNABLE

    def test_a_missing_score_is_treated_as_weak_not_as_an_error(self):
        assert should_optimize({}) == RECALCULATE_MATCH

    def test_it_explains_itself_in_words_that_name_the_number(self):
        record = explain_optimize(state(score=55.0))
        assert record["branch"] == RECALCULATE_MATCH
        assert "55" in record["reason"]


class TestShouldCreatePlan:
    """The brief routed on ``if learning_time <= 14`` alone.

    That is degenerate at both ends: a candidate with no gaps sums to zero
    days, and zero is also <= 14, so the strongest applicants were told to
    wait a fortnight and study nothing.
    """

    def test_no_gaps_means_no_plan_rather_than_a_plan_for_nothing(self):
        assert should_create_plan(state(score=60.0, gaps=[])) == PREPARE_INTERVIEW

    def test_zero_days_of_study_does_not_become_a_two_week_wait(self):
        empty = state(score=60.0, gaps=[gap("Docker", 0)])
        assert should_create_plan(empty) == PREPARE_INTERVIEW

    def test_a_strong_match_applies_now_even_with_a_closeable_gap(self):
        """88% with a three-day gap should not be told to wait. Adverts close."""
        strong = state(score=88.0, gaps=[gap("Docker", 3)])
        assert should_create_plan(strong) == PREPARE_INTERVIEW

    def test_the_strong_threshold_itself_applies_now(self):
        edge = state(score=STRONG_MATCH, gaps=[gap("Docker", 3)])
        assert should_create_plan(edge) == PREPARE_INTERVIEW

    def test_a_middling_match_with_a_short_gap_gets_a_plan(self):
        mid = state(score=64.0, gaps=[gap("Docker", 9)])
        assert should_create_plan(mid) == CREATE_PLAN

    def test_a_gap_longer_than_the_window_is_not_worth_waiting_for(self):
        far = state(score=64.0, gaps=[gap("Kubernetes", 60)])
        assert should_create_plan(far) == PREPARE_INTERVIEW

    def test_the_window_is_configurable(self):
        mid = state(score=64.0, gaps=[gap("Docker", 20)])
        assert should_create_plan(mid, window_days=14) == PREPARE_INTERVIEW
        assert should_create_plan(mid, window_days=30) == CREATE_PLAN

    def test_the_reason_names_the_window_it_compared_against(self):
        mid = state(score=64.0, gaps=[gap("Docker", 9)])
        record = explain_plan(mid, 14)
        assert record["branch"] == CREATE_PLAN
        assert record["blocking_days"] == 9
        assert "14" in record["reason"]


class TestBlockingDays:
    """Only critical gaps block. Nice-to-haves are not a reason to wait."""

    def test_nice_to_haves_do_not_add_to_the_wait(self):
        mixed = {
            "gaps": {
                "gap_report": {
                    "critical_gaps": [gap("Docker", 10)],
                    "nice_to_have_gaps": [gap("Kafka", 40, "NICE_TO_HAVE")],
                }
            }
        }
        assert blocking_days(mixed) == 10

    def test_no_gaps_is_zero_days_not_an_error(self):
        assert blocking_days({}) == 0

    def test_critical_count_counts_only_critical_gaps(self):
        assert critical_count(state(gaps=[gap("A", 1), gap("B", 2)])) == 2
        assert critical_count({}) == 0


class TestFinalRecommendation:
    def test_a_strong_match_says_apply_now(self):
        assert final_recommendation(state(score=90.0), 14) == APPLY_NOW

    def test_a_middling_match_with_a_closeable_gap_says_learn_first(self):
        mid = state(score=60.0, gaps=[gap("Docker", 10)])
        assert final_recommendation(mid, 14) == APPLY_AFTER_LEARNING

    def test_a_hopeless_match_says_skip(self):
        weak = state(score=20.0, gaps=[gap("Docker", 90)])
        assert final_recommendation(weak, 14) == SKIP

    def test_below_the_floor_learning_first_is_not_offered(self):
        """A short gap does not rescue a match that is far too low."""
        low = state(score=FLOOR_MATCH - 10, gaps=[gap("Docker", 3)])
        assert final_recommendation(low, 14) == SKIP

    def test_the_verdict_ignores_the_projected_score(self):
        """The projection is what a rewrite *might* reach, not what is true.

        A verdict that quietly reads it would be advising on a resume the
        candidate has not got.
        """
        honest = state(score=40.0, gaps=[gap("Docker", 90)], projected=95.0)
        assert final_recommendation(honest, 14) == SKIP

    def test_a_projection_cannot_turn_a_skip_into_an_apply(self):
        for projected in (80.0, 90.0, 100.0):
            low = state(score=30.0, gaps=[gap("Docker", 90)], projected=projected)
            assert final_recommendation(low, 14) == SKIP


class TestGraphShape:
    def test_every_node_in_the_order_has_a_place_in_the_description(self):
        described = describe_graph()
        assert list(described["nodes"]) == list(NODE_ORDER)
        for node in NODE_ORDER:
            assert node in described["labels"]

    def test_the_description_marks_both_branch_points(self):
        conditional = describe_graph()["conditional_edges"]
        assert {edge["from"] for edge in conditional} == {
            "optimize_resume",
            CHECK_LEARNABLE,
        }

    def test_building_without_implementations_names_what_is_missing(self):
        with pytest.raises(ValueError) as caught:
            build_conditional_graph({}, 14)
        message = str(caught.value)
        assert "analyze_job" in message

    def test_building_names_only_the_nodes_actually_missing(self):
        supplied = {name: (lambda s: {}) for name in NODE_ORDER}
        supplied.pop(PREPARE_INTERVIEW)
        with pytest.raises(ValueError) as caught:
            build_conditional_graph(supplied, 14)
        message = str(caught.value)
        assert PREPARE_INTERVIEW in message
        assert "analyze_job" not in message

    def test_no_node_is_named_after_a_state_key(self):
        """LangGraph refuses to compile such a graph, and we fall back silently.

        ``interview_prep`` was both a node and a state channel, so every
        advanced run raised at compile time and quietly ran the nodes by hand
        instead. The fallback hid it; only this assertion makes it loud.
        """
        state_keys = set(create_initial_state().keys())
        assert [name for name in NODE_ORDER if name in state_keys] == []


class TestExecutedPath:
    def test_the_path_reports_the_nodes_that_actually_ran(self):
        trace = [
            {"node": "analyze_job", "status": "ok"},
            {"node": "extract_resume", "status": "ok"},
        ]
        assert executed_path(trace) == ["analyze_job", "extract_resume"]

    def test_an_empty_trace_is_an_empty_path(self):
        assert executed_path([]) == []
