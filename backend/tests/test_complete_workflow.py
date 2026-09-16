"""Tests for the complete seven-node pipeline.

Grouped by the promise being kept, not by method name. The first four classes
are the ones that matter: a pipeline that silently swallows a broken node, or
quietly disagrees with its own scorer, is worse than one that crashes.
"""

from __future__ import annotations

import pytest

from agents.complete_workflow import (
    APPLY,
    MAYBE,
    NODE_LABELS,
    NODE_SEQUENCE,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    SKIP,
    CompleteWorkflow,
    _as_fraction,
    build_complete_workflow,
    complete_workflow,
    summarise_trace,
)
from agents.workflow_state import (
    STATUS_ERROR,
    STATUS_SKIPPED,
    create_initial_state,
)

RESUME = """
Priya Raman
AI/ML Developer with 2+ years experience

EXPERIENCE
Senior Developer, DataCorp (2022-2024)
- Built RAG system with LangChain and Chroma serving 400 users
- Deployed FastAPI services on AWS with Docker
- Python development across three teams

PROJECTS
1. Document Q&A bot
- LangChain, Chroma, embeddings, OpenAI

SKILLS
Python, LangChain, FastAPI, Docker, PostgreSQL, AWS, Git
"""

JOB = """
AI/ML Engineer - Bangalore
We need someone with strong Python, LangChain and RAG experience.
Required: Python, LangChain, RAG, FastAPI, Docker, Pinecone, LangGraph
Preferred: AWS, Kubernetes
"""


@pytest.fixture(scope="module")
def result():
    return CompleteWorkflow().run_complete_analysis(RESUME, JOB)


@pytest.fixture(scope="module")
def linear_result():
    """A run of the original straight-line pipeline.

    ``run_complete_analysis`` now branches by default, so a fixed node count
    and a fixed node order are no longer the right assertions for it - a
    branch the graph deliberately routed around is not a missing step. The
    linear pipeline still exists and still runs all seven nodes in order, and
    the tests that describe *that* shape use this fixture.
    """
    return CompleteWorkflow().run_complete_analysis(RESUME, JOB, advanced=False)


@pytest.fixture
def flow():
    return CompleteWorkflow()


# ---------------------------------------------------------------------------
# A broken node must not take the run down with it.
# ---------------------------------------------------------------------------


class TestOneBadNodeDoesNotSinkTheRun:
    def test_a_raising_node_is_recorded_not_propagated(self, flow):
        def explode(state):
            raise RuntimeError("detector on fire")

        flow.node_detect_gaps = explode
        flow._compiled = None
        result = flow.run_complete_analysis(RESUME, JOB)

        assert "detect_gaps" in result["nodes_failed"]
        assert result["status"] == RUN_PARTIAL

    def test_later_nodes_still_run_after_a_failure(self, flow):
        flow.node_detect_gaps = lambda state: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        flow._compiled = None
        result = flow.run_complete_analysis(RESUME, JOB, advanced=False)

        ran = result["nodes_run"]
        assert "optimize_resume" in ran
        assert "prepare_interview" in ran
        assert "generate_recommendation" in ran

    def test_a_failure_still_produces_a_recommendation(self, flow):
        flow.node_optimize_resume = lambda state: (_ for _ in ()).throw(
            ValueError("nope")
        )
        flow._compiled = None
        result = flow.run_complete_analysis(RESUME, JOB)

        assert result["user_recommendation"]
        assert result["recommendation"]["decision"] in (APPLY, MAYBE, SKIP)

    def test_the_failure_reason_is_kept(self, flow):
        flow.node_detect_gaps = lambda state: (_ for _ in ()).throw(
            RuntimeError("detector on fire")
        )
        flow._compiled = None
        result = flow.run_complete_analysis(RESUME, JOB)

        entry = next(
            e for e in result["execution_trace"] if e["node"] == "detect_gaps"
        )
        assert entry["status"] == STATUS_ERROR
        assert "detector on fire" in entry["error"]

    def test_every_node_can_fail_without_crashing(self, flow):
        for name in NODE_SEQUENCE:
            worker = CompleteWorkflow()
            setattr(
                worker,
                f"node_{name}",
                lambda state: (_ for _ in ()).throw(RuntimeError("x")),
            )
            worker._compiled = None
            result = worker.run_complete_analysis(RESUME, JOB, advanced=False)
            assert result["status"] in (RUN_PARTIAL, RUN_COMPLETED)
            assert len(result["execution_trace"]) == len(NODE_SEQUENCE)

    def test_every_node_can_fail_without_crashing_the_branching_run(self, flow):
        for name in NODE_SEQUENCE:
            worker = CompleteWorkflow()
            setattr(
                worker,
                f"node_{name}",
                lambda state: (_ for _ in ()).throw(RuntimeError("x")),
            )
            worker._compiled = None
            result = worker.run_complete_analysis(RESUME, JOB)
            assert result["status"] in (RUN_PARTIAL, RUN_COMPLETED)
            assert result["execution_trace"]

    def test_empty_input_is_a_result_not_an_exception(self, flow):
        result = flow.run_complete_analysis("", "")
        assert result["status"] == RUN_FAILED
        assert "Nothing to analyse" in result["user_recommendation"]

    def test_resume_only_still_runs(self, flow):
        result = flow.run_complete_analysis(RESUME, "")
        assert result["status"] in (RUN_PARTIAL, RUN_COMPLETED)
        assert result["execution_trace"]

    def test_job_only_still_runs(self, flow):
        result = flow.run_complete_analysis("", JOB)
        assert result["status"] in (RUN_PARTIAL, RUN_COMPLETED)
        assert result["analysis"]


# ---------------------------------------------------------------------------
# The pipeline must not contradict the agent that produced the number.
# ---------------------------------------------------------------------------


class TestTheVerdictIsAccountable:
    def test_the_scorers_verdict_is_always_reported(self, result):
        assert result["recommendation"]["scored_decision"] in (
            APPLY,
            MAYBE,
            SKIP,
        )

    def test_an_unchanged_verdict_matches_the_scorer(self, result):
        rec = result["recommendation"]
        if not rec["adjusted"]:
            assert rec["decision"] == rec["scored_decision"]

    def test_every_adjustment_carries_a_reason(self, flow):
        for scored, score, critical, weeks in [
            (SKIP, 55.0, 1, 1.0),
            (APPLY, 85.0, 4, 6.0),
            (SKIP, 20.0, 9, 30.0),
            (APPLY, 90.0, 0, 0.0),
            (MAYBE, 60.0, 2, 3.0),
        ]:
            decision, reason = flow._adjust(scored, score, critical, weeks)
            if decision != scored:
                assert reason, f"{scored}->{decision} gave no reason"
                assert scored in reason and decision in reason

    def test_an_unchanged_verdict_has_no_reason(self, flow):
        decision, reason = flow._adjust(APPLY, 90.0, 0, 0.0)
        assert decision == APPLY
        assert reason is None

    def test_a_near_miss_skip_is_rescued(self, flow):
        decision, reason = flow._adjust(SKIP, 55.0, 1, 1.0)
        assert decision == MAYBE
        assert "raised" in reason

    def test_a_distant_skip_is_not_rescued(self, flow):
        assert flow._adjust(SKIP, 20.0, 9, 30.0)[0] == SKIP
        assert flow._adjust(SKIP, 55.0, 1, 20.0)[0] == SKIP
        assert flow._adjust(SKIP, 55.0, 8, 1.0)[0] == SKIP
        assert flow._adjust(SKIP, 30.0, 1, 1.0)[0] == SKIP

    def test_a_gap_heavy_apply_is_downgraded(self, flow):
        decision, reason = flow._adjust(APPLY, 85.0, 4, 6.0)
        assert decision == MAYBE
        assert "lowered" in reason

    def test_a_skip_is_never_promoted_straight_to_apply(self, flow):
        for critical in range(0, 6):
            for weeks in (0.0, 1.0, 2.0, 8.0):
                assert flow._adjust(SKIP, 99.0, critical, weeks)[0] != APPLY

    def test_an_unknown_verdict_falls_back_to_skip(self, flow):
        state = create_initial_state(resume_text=RESUME)
        # A score has to be present, or the node short-circuits to the unscored
        # branch and never reaches the verdict sanitising this test is about.
        state["all_analysis"] = {
            "calculate_match": {"overall_match": 40.0, "recommendation": "???"}
        }
        update = flow.node_generate_recommendation(state)
        payload = update["all_analysis"]["generate_recommendation"]
        assert payload["scored_decision"] == SKIP


# ---------------------------------------------------------------------------
# Confidence arrives on two different scales. Regression test for a real bug.
# ---------------------------------------------------------------------------


class TestConfidenceIsComparable:
    def test_percentages_are_normalised(self):
        assert _as_fraction(93.0) == 0.93
        assert _as_fraction(0.93) == 0.93

    def test_junk_is_zero_not_an_exception(self):
        assert _as_fraction(None) == 0.0
        assert _as_fraction("nonsense") == 0.0

    def test_confidence_is_clamped(self):
        assert _as_fraction(500) == 1.0
        assert _as_fraction(-4) == 0.0

    def test_mixed_scales_do_not_produce_nonsense(self, flow):
        value = flow._confidence(
            {"confidence": 93.0}, {"confidence": 0.4}, {"confidence": 0.95}
        )
        assert 0.0 <= value <= 1.0

    def test_never_more_confident_than_the_weakest_input(self, flow):
        value = flow._confidence(
            {"confidence": 99.0}, {"confidence": 0.2}, {"confidence": 0.95}
        )
        assert value <= 0.2

    def test_no_inputs_means_no_confidence(self, flow):
        assert flow._confidence({}, {}, {}) == 0.0

    def test_reported_confidence_is_a_fraction(self, result):
        assert 0.0 <= result["recommendation"]["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Advice must not argue with itself.
# ---------------------------------------------------------------------------


class TestAdviceIsCoherent:
    def test_a_skip_does_not_open_by_polishing_this_resume(self, flow):
        steps = flow._next_steps(
            SKIP,
            {"priority_order": ["Pinecone"], "critical_gaps": [
                {"skill": "Pinecone", "learning_time_days": 2}
            ]},
            {"high_impact_count": 5},
            {"estimated_prep_time_hours": 9.0, "prep_days": 5},
        )
        assert steps
        assert "resume edit" not in steps[0]["action"]

    def test_a_skip_still_offers_the_edits_last(self, flow):
        steps = flow._next_steps(
            SKIP,
            {"priority_order": ["Pinecone"], "critical_gaps": [
                {"skill": "Pinecone", "learning_time_days": 2}
            ]},
            {"high_impact_count": 5},
            {},
        )
        assert "resume edit" in steps[-1]["action"]
        assert "anyway" in steps[-1]["action"]

    def test_an_apply_leads_with_the_resume_edits(self, flow):
        steps = flow._next_steps(
            APPLY,
            {"priority_order": [], "critical_gaps": []},
            {"high_impact_count": 5},
            {"estimated_prep_time_hours": 9.0, "prep_days": 5},
        )
        assert "resume edit" in steps[0]["action"]

    def test_avoid_advice_names_the_expensive_gap_not_the_cheap_one(self, flow):
        gaps = {
            "priority_order": ["Pinecone", "LangGraph", "CI/CD"],
            "critical_gaps": [
                {"skill": "Pinecone", "learning_time_days": 2},
                {"skill": "LangGraph", "learning_time_days": 5},
                {"skill": "CI/CD", "learning_time_days": 10},
            ],
        }
        steps = flow._next_steps(SKIP, gaps, {}, {})
        avoid = next(s for s in steps if "does not require" in s["action"])
        assert "CI/CD" in avoid["action"]
        assert "Pinecone" not in avoid["action"]

    def test_a_truncated_gap_list_says_so(self, flow):
        gaps = {
            "priority_order": ["A", "B", "C", "D", "E"],
            "critical_gaps": [{"skill": "A", "learning_time_days": 1}],
        }
        steps = flow._next_steps(SKIP, gaps, {}, {})
        assert "and 2 more" in steps[0]["action"]

    def test_a_short_gap_list_does_not_claim_more(self, flow):
        gaps = {
            "priority_order": ["A", "B"],
            "critical_gaps": [{"skill": "A", "learning_time_days": 1}],
        }
        steps = flow._next_steps(SKIP, gaps, {}, {})
        assert "more)" not in steps[0]["action"]

    def test_no_gaps_produces_no_gap_step(self, flow):
        steps = flow._next_steps(
            APPLY, {}, {"high_impact_count": 2}, {"estimated_prep_time_hours": 4}
        )
        assert not any("critical gaps" in s["action"] for s in steps)

    def test_every_step_says_where_and_how_long(self, result):
        for step in result["recommendation"]["next_steps"]:
            assert step["action"] and step["where"] and step["effort"]

    def test_the_summary_leads_with_the_first_step(self, result):
        steps = result["recommendation"]["next_steps"]
        if steps:
            assert steps[0]["action"] in result["user_recommendation"]

    def test_reasoning_quotes_the_real_score(self, result):
        score = result["recommendation"]["overall_match"]
        assert f"{score:.1f}/100" in result["recommendation"]["reasoning"][0]

    def test_gap_names_come_from_the_gap_report(self, result):
        report = (result["gaps"] or {}).get("gap_report") or {}
        names = {str(n) for n in (report.get("priority_order") or [])}
        for step in result["recommendation"]["next_steps"]:
            if step["action"].startswith("Close the critical gaps"):
                listed = step["action"].split(":", 1)[1]
                assert any(name in listed for name in names)


# ---------------------------------------------------------------------------
# Structure and wiring.
# ---------------------------------------------------------------------------


class TestPipelineShape:
    def test_seven_nodes_in_the_documented_order(self):
        assert NODE_SEQUENCE == (
            "analyze_job",
            "extract_resume",
            "calculate_match",
            "detect_gaps",
            "optimize_resume",
            "prepare_interview",
            "generate_recommendation",
        )

    def test_every_node_has_a_label(self):
        assert set(NODE_LABELS) == set(NODE_SEQUENCE)

    def test_every_node_has_an_implementation(self, flow):
        for name in NODE_SEQUENCE:
            assert callable(getattr(flow, f"node_{name}"))

    def test_edges_form_a_single_line_to_end(self):
        edges = CompleteWorkflow.describe()["edges"]
        assert len(edges) == len(NODE_SEQUENCE)
        assert edges[0]["from"] == NODE_SEQUENCE[0]
        assert edges[-1]["to"] == "END"
        for edge, expected in zip(edges, NODE_SEQUENCE[1:]):
            assert edge["to"] == expected

    def test_node_names_are_exposed(self):
        assert CompleteWorkflow.node_names() == list(NODE_SEQUENCE)

    def test_the_graph_compiles(self, flow):
        assert flow.compiled is not None

    def test_the_graph_is_compiled_once(self, flow):
        assert flow.compiled is flow.compiled

    def test_builder_returns_a_workflow(self):
        assert isinstance(build_complete_workflow(), CompleteWorkflow)

    def test_a_shared_instance_exists(self):
        assert isinstance(complete_workflow, CompleteWorkflow)


class TestResultStructure:
    @pytest.mark.parametrize(
        "key",
        [
            "analysis",
            "match_result",
            "gaps",
            "resume_optimizations",
            "interview_prep",
            "user_recommendation",
            "execution_trace",
            "trace",
            "total_duration_ms",
            "status",
        ],
    )
    def test_documented_keys_are_present(self, result, key):
        assert key in result

    def test_every_node_produced_a_named_slot(self, result):
        assert result["analysis"]
        assert result["match_result"]
        assert result["gaps"]
        assert result["resume_optimizations"]
        assert result["interview_prep"]

    def test_named_slots_mirror_all_analysis(self, result):
        assert result["match_result"] == result["all_analysis"]["calculate_match"]
        assert result["gaps"] == result["all_analysis"]["detect_gaps"]

    def test_a_clean_run_is_completed(self, result):
        assert result["status"] == RUN_COMPLETED
        assert result["nodes_failed"] == []

    def test_score_is_carried_up(self, result):
        assert 0 <= result["match_score"] <= 100

    def test_skills_are_carried_up(self, result):
        assert result["skills_found"]


class TestTrace:
    def test_one_entry_per_node(self, linear_result):
        assert len(linear_result["execution_trace"]) == len(NODE_SEQUENCE)

    def test_nodes_appear_in_order(self, linear_result):
        assert linear_result["nodes_run"] == list(NODE_SEQUENCE)

    def test_steps_are_numbered_from_one(self, linear_result):
        steps = [e["step"] for e in linear_result["execution_trace"]]
        assert steps == list(range(1, len(NODE_SEQUENCE) + 1))

    def test_the_branching_run_is_also_numbered_from_one(self, result):
        steps = [e["step"] for e in result["execution_trace"]]
        assert steps == list(range(1, len(steps) + 1))

    def test_every_entry_is_timed(self, result):
        for entry in result["execution_trace"]:
            assert entry["duration_ms"] >= 0

    def test_total_is_the_sum_of_the_parts(self, result):
        parts = sum(e["duration_ms"] for e in result["execution_trace"])
        assert result["total_duration_ms"] == pytest.approx(parts, abs=0.1)

    def test_summary_uses_human_labels(self, linear_result):
        names = [row["node"] for row in linear_result["trace"]["trace"]]
        assert names == [NODE_LABELS[n] for n in NODE_SEQUENCE]

    def test_the_branching_summary_also_uses_human_labels(self, result):
        for row in result["trace"]["trace"]:
            assert row["node"] and "_" not in row["node"]

    def test_summary_prefers_the_pipeline_label_over_the_agents(self, linear_result):
        names = [row["node"] for row in linear_result["trace"]["trace"]]
        assert "Interview Prep" in names
        assert "Interview Prep Agent" not in names

    def test_summary_has_the_documented_shape(self, result):
        summary = result["trace"]
        assert set(summary) == {"trace", "total_duration_ms", "status"}
        for row in summary["trace"]:
            assert set(row) == {"node", "status", "duration_ms"}
            assert isinstance(row["duration_ms"], int)

    def test_summary_of_nothing_is_failed(self):
        assert summarise_trace([])["status"] == RUN_FAILED

    def test_summary_flags_an_error(self):
        summary = summarise_trace(
            [{"node": "analyze_job", "status": STATUS_ERROR, "duration_ms": 3}]
        )
        assert summary["status"] == RUN_PARTIAL

    def test_summary_flags_a_skip(self):
        summary = summarise_trace(
            [{"node": "detect_gaps", "status": STATUS_SKIPPED, "duration_ms": 1}]
        )
        assert summary["status"] == RUN_PARTIAL

    def test_two_runs_do_not_share_a_trace(self, flow):
        first = flow.run_complete_analysis(RESUME, JOB, advanced=False)
        second = flow.run_complete_analysis(RESUME, JOB, advanced=False)
        assert len(first["execution_trace"]) == len(NODE_SEQUENCE)
        assert len(second["execution_trace"]) == len(NODE_SEQUENCE)


# ---------------------------------------------------------------------------
# The LangGraph-free fallback must give the same answer.
# ---------------------------------------------------------------------------


class TestFallbackPath:
    @pytest.fixture
    def broken(self, monkeypatch):
        flow = CompleteWorkflow()
        monkeypatch.setattr(
            CompleteWorkflow,
            "build",
            lambda self: (_ for _ in ()).throw(ImportError("no langgraph")),
        )
        return flow

    def test_a_broken_graph_still_returns_a_result(self, broken):
        result = broken.run_complete_analysis(RESUME, JOB)
        assert result["execution_trace"]

    def test_the_fallback_runs_every_node(self, broken):
        result = broken.run_complete_analysis(RESUME, JOB, advanced=False)
        assert result["nodes_run"] == list(NODE_SEQUENCE)

    def test_the_fallback_explains_itself(self, broken):
        note = broken.run_complete_analysis(RESUME, JOB, advanced=False)["note"]
        assert "without LangGraph" in note

    def test_the_fallback_reaches_the_same_verdict(self, broken, result):
        fallback = broken.run_complete_analysis(RESUME, JOB)
        assert (
            fallback["recommendation"]["decision"]
            == result["recommendation"]["decision"]
        )
        assert fallback["match_score"] == result["match_score"]

    def test_the_fallback_does_not_duplicate_trace_entries(self, broken):
        result = broken.run_complete_analysis(RESUME, JOB, advanced=False)
        assert len(result["execution_trace"]) == len(NODE_SEQUENCE)

    def test_the_branching_fallback_does_not_duplicate_trace_entries(self, broken):
        result = broken.run_complete_analysis(RESUME, JOB)
        ran = result["nodes_run"]
        assert len(ran) == len(set(ran))


# ---------------------------------------------------------------------------
# Nodes are borrowed from WorkflowGraph, not reimplemented.
# ---------------------------------------------------------------------------


class TestScoringIsNotDuplicated:
    def test_the_same_resume_scores_the_same_in_both_graphs(self, result):
        from agents.graph_builder import build_workflow

        other = build_workflow().execute(
            resume_text=RESUME, job_description=JOB
        )
        assert result["match_score"] == other["match_score"]

    def test_gaps_agree_between_the_two_graphs(self, result):
        from agents.graph_builder import build_workflow

        other = build_workflow().execute(
            resume_text=RESUME, job_description=JOB
        )
        assert set(result["gaps_identified"]) == set(other["gaps_identified"])

    def test_node_impl_rejects_an_unknown_node(self):
        from agents.graph_builder import build_workflow

        with pytest.raises(KeyError):
            build_workflow().node_impl("not_a_node")


class TestResumeExtraction:
    def test_it_reports_how_the_resume_was_loaded(self, result):
        payload = result["all_analysis"]["extract_resume"]
        assert payload["resume_source"] == "text"

    def test_it_counts_the_characters(self, result):
        payload = result["all_analysis"]["extract_resume"]
        assert payload["characters"] == len(RESUME.strip())

    def test_no_resume_is_skipped_not_failed(self, flow):
        state = create_initial_state(job_description=JOB)
        update = flow.node_extract_resume(state)
        assert update["_status"] == STATUS_SKIPPED

    def test_a_broken_retriever_falls_back_to_text(self, flow):
        class Broken:
            def get_full_context(self):
                raise RuntimeError("index gone")

            def get_profile(self):
                raise RuntimeError("index gone")

        flow.graph.retriever = Broken()
        state = create_initial_state(resume_text=RESUME, job_description=JOB)
        update = flow.node_extract_resume(state)
        payload = update["all_analysis"]["extract_resume"]
        assert payload["resume_source"] == "text"
        assert update["skills_found"]

    def test_the_index_supplies_the_resume_when_none_is_passed(self, flow):
        class Stub:
            def get_full_context(self):
                return RESUME

            def get_profile(self):
                return {"name": "Priya Raman"}

        flow.graph.retriever = Stub()
        state = create_initial_state(job_description=JOB)
        update = flow.node_extract_resume(state)
        payload = update["all_analysis"]["extract_resume"]
        assert payload["resume_source"] == "rag"
        assert payload["profile"]["name"] == "Priya Raman"

    def test_a_supplied_resume_beats_the_indexed_one(self, flow):
        class Stub:
            def get_full_context(self):
                return "SOMEBODY ELSE ENTIRELY"

            def get_profile(self):
                return {}

        flow.graph.retriever = Stub()
        state = create_initial_state(resume_text=RESUME, job_description=JOB)
        update = flow.node_extract_resume(state)
        assert update["resume_text"] == RESUME.strip()


class TestRecommendationEdgeCases:
    def test_no_match_result_is_skipped(self, flow):
        state = create_initial_state(resume_text=RESUME)
        update = flow.node_generate_recommendation(state)
        assert update["_status"] == STATUS_SKIPPED
        assert update["user_recommendation"]

    def test_a_skipped_match_is_skipped(self, flow):
        state = create_initial_state(resume_text=RESUME)
        state["all_analysis"] = {"calculate_match": {"skipped": "no resume"}}
        update = flow.node_generate_recommendation(state)
        assert update["_status"] == STATUS_SKIPPED

    def test_it_survives_an_empty_gap_report(self, flow):
        state = create_initial_state(resume_text=RESUME)
        state["all_analysis"] = {
            "calculate_match": {"overall_match": 80.0, "recommendation": APPLY}
        }
        payload = flow.node_generate_recommendation(state)["all_analysis"][
            "generate_recommendation"
        ]
        assert payload["decision"] == APPLY
        assert payload["critical_gaps"] == 0

    def test_a_perfect_match_has_no_gap_sentence(self, flow):
        state = create_initial_state(resume_text=RESUME)
        state["all_analysis"] = {
            "calculate_match": {"overall_match": 95.0, "recommendation": APPLY}
        }
        payload = flow.node_generate_recommendation(state)["all_analysis"][
            "generate_recommendation"
        ]
        assert any("No critical" in r for r in payload["reasoning"])

    def test_the_headline_matches_the_decision(self, flow):
        for decision, word in [(APPLY, "Apply"), (MAYBE, "shot"), (SKIP, "skip")]:
            assert word.lower() in flow._headline(decision, 70.0, 1, 1.0).lower()

    def test_a_missing_score_is_reported_as_unscored_not_as_zero(self, flow):
        state = create_initial_state(resume_text=RESUME)
        state["all_analysis"] = {"calculate_match": {"recommendation": SKIP}}
        update = flow.node_generate_recommendation(state)
        payload = update["all_analysis"]["generate_recommendation"]
        assert payload["overall_match"] is None
        assert payload["decision"] == "NOT_SCORED"
        # The prose has to agree with the number, or the reader believes the
        # prose. "0/100" and "the fit is not there" were both untrue here.
        assert "0/100" not in update["user_recommendation"]
        assert "Not scored" in update["user_recommendation"]

    def test_an_unscored_run_is_not_marked_as_a_skipped_node(self, flow):
        # The calculator ran and succeeded; it found nothing to measure. Marking
        # the node skipped would drop the whole run to "partial".
        state = create_initial_state(resume_text=RESUME)
        state["all_analysis"] = {"calculate_match": {"recommendation": SKIP}}
        assert "_status" not in flow.node_generate_recommendation(state)
