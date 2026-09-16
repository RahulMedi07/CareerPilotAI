"""Tests for the workflow state helpers and the LangGraph workflow itself."""

import json

import pytest

from agents.graph_builder import NODE_SEQUENCE, WorkflowError, WorkflowGraph, build_workflow
from agents.workflow_state import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    StateDict,
    StepTimer,
    WorkflowState,
    _append,
    create_initial_state,
    executed_nodes,
    has_errors,
    make_trace_entry,
    merge_analysis,
    total_duration_ms,
    trace_summary,
)
from tests.conftest import SAMPLE_JOB_TEXT, SAMPLE_RESUME, StubLLM


@pytest.fixture
def graph():
    """A workflow whose agents can never reach a model, so fallbacks run."""
    return WorkflowGraph(llm=StubLLM(available=False))


@pytest.fixture
def final_state(graph):
    return graph.execute(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JOB_TEXT)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


class TestStateHelpers:
    def test_state_dict_is_an_alias(self):
        assert StateDict is WorkflowState

    def test_initial_state_has_every_key(self):
        # Derived from the TypedDict rather than hardcoded, so adding a field
        # to WorkflowState without initialising it fails here instead of
        # surfacing as a KeyError inside whichever node reads it first.
        state = create_initial_state()
        assert set(state) == set(WorkflowState.__annotations__)

    def test_initial_state_defaults_are_empty(self):
        state = create_initial_state()
        assert state["skills_found"] == []
        assert state["gaps_identified"] == []
        assert state["match_score"] == 0.0
        assert state["all_analysis"] == {}
        assert state["execution_trace"] == []

    def test_initial_state_accepts_values(self):
        state = create_initial_state(resume_text="cv", job_description="jd")
        assert state["resume_text"] == "cv"
        assert state["job_description"] == "jd"

    def test_initial_state_accepts_extra_keys(self):
        assert create_initial_state(resume_id="abc")["resume_id"] == "abc"

    def test_none_inputs_become_empty_strings(self):
        state = create_initial_state(resume_text=None, job_description=None)
        assert state["resume_text"] == ""

    def test_append_reducer_concatenates(self):
        assert _append([{"a": 1}], [{"b": 2}]) == [{"a": 1}, {"b": 2}]

    @pytest.mark.parametrize(
        "existing,new,expected",
        [(None, [{"a": 1}], [{"a": 1}]), ([{"a": 1}], None, [{"a": 1}]), (None, None, [])],
    )
    def test_append_reducer_tolerates_none(self, existing, new, expected):
        assert _append(existing, new) == expected

    def test_append_reducer_does_not_mutate_its_input(self):
        original = [{"a": 1}]
        _append(original, [{"b": 2}])
        assert original == [{"a": 1}]

    def test_trace_entry_shape(self):
        entry = make_trace_entry("node_a", step=2, duration_ms=1.234)
        assert entry["node"] == "node_a"
        assert entry["step"] == 2
        assert entry["status"] == STATUS_OK
        assert entry["duration_ms"] == 1.23
        assert "timestamp" in entry

    def test_trace_entry_omits_empty_detail(self):
        assert "detail" not in make_trace_entry("n")

    def test_trace_entry_is_json_safe(self):
        assert json.dumps(make_trace_entry("n", detail="ok"))

    def test_merge_analysis_keeps_earlier_nodes(self):
        state = create_initial_state()
        state["all_analysis"] = {"first": {"x": 1}}
        merged = merge_analysis(state, "second", {"y": 2})
        assert merged == {"first": {"x": 1}, "second": {"y": 2}}

    def test_merge_analysis_does_not_mutate_the_state(self):
        state = create_initial_state()
        merge_analysis(state, "a", {"x": 1})
        assert state["all_analysis"] == {}

    def test_executed_nodes_and_summary(self):
        state = create_initial_state()
        state["execution_trace"] = [
            make_trace_entry("a", duration_ms=1.0),
            make_trace_entry("b", duration_ms=2.0),
        ]
        assert executed_nodes(state) == ["a", "b"]
        assert trace_summary(state) == ["a (completed, 1.0ms)", "b (completed, 2.0ms)"]
        assert total_duration_ms(state) == 3.0
        assert has_errors(state) is False

    def test_has_errors_spots_a_failed_node(self):
        state = create_initial_state()
        state["execution_trace"] = [make_trace_entry("a", status=STATUS_ERROR)]
        assert has_errors(state) is True

    def test_helpers_handle_a_missing_trace(self):
        assert executed_nodes({}) == []
        assert total_duration_ms({}) == 0.0
        assert has_errors({}) is False


class TestStepTimer:
    def test_records_a_successful_step(self):
        with StepTimer("node_a", step=1) as timer:
            pass
        entry = timer.entry()
        assert entry["status"] == STATUS_OK
        assert entry["duration_ms"] >= 0.0

    def test_marks_a_failed_step_and_reraises(self):
        timer = StepTimer("node_a")
        with pytest.raises(ValueError):
            with timer:
                raise ValueError("boom")
        assert timer.entry()["status"] == STATUS_ERROR

    def test_extra_fields_reach_the_entry(self):
        with StepTimer("n") as timer:
            pass
        assert timer.entry(detail="hi")["detail"] == "hi"


# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------


class TestGraphStructure:
    def test_node_names_match_the_spec(self, graph):
        assert graph.node_names() == [
            "analyze_job",
            "extract_skills",
            "detect_gaps",
            "calculate_match",
            "optimize_resume",
            "prepare_interview",
        ]

    def test_graph_compiles(self, graph):
        assert graph.graph is not None

    def test_graph_is_compiled_only_once(self, graph):
        assert graph.graph is graph.graph

    def test_describe_lists_edges_ending_at_end(self, graph):
        described = graph.describe()
        assert described["entry_point"] == "analyze_job"
        assert described["edges"][-1] == {"from": "prepare_interview", "to": "END"}
        assert len(described["edges"]) == len(NODE_SEQUENCE)

    def test_describe_is_json_safe_and_hides_secrets(self, graph):
        graph.config.claude_api_key = "sk-secret"
        assert "sk-secret" not in json.dumps(graph.describe())

    def test_factory_builds_a_workflow(self):
        assert isinstance(build_workflow(), WorkflowGraph)

    def test_all_agents_share_one_llm_client(self, graph):
        assert graph.job_agent._llm is graph.skill_agent._llm


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestGraphExecution:
    def test_every_node_runs_in_order(self, final_state):
        assert executed_nodes(final_state) == list(NODE_SEQUENCE)

    def test_trace_steps_are_numbered_sequentially(self, final_state):
        assert [e["step"] for e in final_state["execution_trace"]] == list(
            range(1, len(NODE_SEQUENCE) + 1)
        )

    def test_every_step_records_a_duration(self, final_state):
        assert all(e["duration_ms"] >= 0.0 for e in final_state["execution_trace"])

    def test_every_step_has_a_readable_detail(self, final_state):
        assert all(e.get("detail") for e in final_state["execution_trace"])

    def test_no_node_failed(self, final_state):
        assert has_errors(final_state) is False

    def test_skills_are_extracted_from_the_resume(self, final_state):
        assert {"python", "fastapi", "docker"} <= set(final_state["skills_found"])

    def test_gaps_are_the_requirements_the_resume_lacks(self, final_state):
        # The sample resume lists Python, Kubernetes and PostgreSQL but not AWS.
        assert set(final_state["gaps_identified"]) == {"aws"}
        assert "kubernetes" not in final_state["gaps_identified"]

    def test_score_is_a_percentage(self, final_state):
        assert 0.0 <= final_state["match_score"] <= 100.0

    def test_all_analysis_holds_one_entry_per_node(self, final_state):
        assert set(final_state["all_analysis"]) == set(NODE_SEQUENCE)

    def test_final_state_is_json_serialisable(self, final_state):
        assert json.dumps(final_state)

    def test_trace_records_that_the_fallback_was_used(self, final_state):
        assert final_state["all_analysis"]["extract_skills"]["source"] == "fallback"

    def test_job_analyzer_reports_its_findings_in_the_trace(self, final_state):
        entry = next(
            e for e in final_state["execution_trace"] if e["node"] == "analyze_job"
        )
        assert entry["label"] == "Job Analyzer"
        assert entry["status"] == "completed"
        assert entry["skills_extracted"] > 0
        assert 0.0 <= entry["confidence"] <= 1.0

    def test_other_nodes_do_not_carry_analyzer_columns(self, final_state):
        entry = next(
            e for e in final_state["execution_trace"] if e["node"] == "extract_skills"
        )
        assert "skills_extracted" not in entry

    def test_match_calculator_reports_its_verdict_in_the_trace(self, final_state):
        entry = next(
            e for e in final_state["execution_trace"] if e["node"] == "calculate_match"
        )
        assert entry["label"] == "Match Calculator"
        assert entry["status"] == "completed"
        assert 0.0 <= entry["overall_score"] <= 100.0
        assert entry["recommendation"] in {"APPLY", "MAYBE", "SKIP"}

    def test_the_scored_breakdown_reaches_the_final_state(self, final_state):
        match = final_state["all_analysis"]["calculate_match"]
        assert set(match["match_breakdown"]) == {
            "skills", "tech_stack", "experience", "soft_skills", "education",
        }
        assert match["overall_match"] == final_state["match_score"]

    def test_execute_accepts_a_prepared_state(self, graph):
        state = create_initial_state(
            resume_text=SAMPLE_RESUME, job_description=SAMPLE_JOB_TEXT
        )
        assert executed_nodes(graph.execute(state)) == list(NODE_SEQUENCE)

    def test_execute_fills_in_missing_keys_of_a_partial_state(self, graph):
        final = graph.execute({"resume_text": SAMPLE_RESUME, "job_description": "Python role"})
        assert final["match_score"] >= 0.0

    def test_run_alias_behaves_like_execute(self, graph):
        final = graph.run(SAMPLE_RESUME, SAMPLE_JOB_TEXT)
        assert executed_nodes(final) == list(NODE_SEQUENCE)

    def test_empty_input_is_rejected(self, graph):
        with pytest.raises(WorkflowError, match="Nothing to analyse"):
            graph.execute(resume_text="", job_description="   ")

    def test_two_runs_do_not_share_a_trace(self, graph):
        first = graph.execute(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JOB_TEXT)
        second = graph.execute(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JOB_TEXT)
        assert len(first["execution_trace"]) == len(second["execution_trace"]) == len(
            NODE_SEQUENCE
        )


class TestGraphDegradedPaths:
    def test_missing_job_description_skips_job_dependent_nodes(self, graph):
        final = graph.execute(resume_text=SAMPLE_RESUME)
        statuses = {e["node"]: e["status"] for e in final["execution_trace"]}
        assert statuses["analyze_job"] == STATUS_SKIPPED
        assert statuses["detect_gaps"] == STATUS_SKIPPED
        assert statuses["extract_skills"] == STATUS_OK
        # Skipped is not failed: the run still completes end to end.
        assert executed_nodes(final) == list(NODE_SEQUENCE)

    def test_missing_resume_still_analyses_the_job(self, graph):
        final = graph.execute(job_description=SAMPLE_JOB_TEXT)
        statuses = {e["node"]: e["status"] for e in final["execution_trace"]}
        assert statuses["analyze_job"] == STATUS_OK
        assert statuses["extract_skills"] == STATUS_SKIPPED
        assert statuses["calculate_match"] == STATUS_SKIPPED
        assert final["match_score"] == 0.0
        assert final["skills_found"] == []

    def test_a_resume_with_no_gaps_reports_none(self, graph):
        final = graph.execute(
            resume_text="Skills: Python, Kubernetes, PostgreSQL, AWS",
            job_description="Engineer\nRequired: Python, Kubernetes, PostgreSQL, AWS",
        )
        assert final["gaps_identified"] == []
        assert final["match_score"] > 50.0

    def test_a_failing_node_is_traced_and_the_run_continues(self, graph):
        class Exploding:
            def run(self, **kwargs):
                raise RuntimeError("agent exploded")

        graph.skill_agent = Exploding()
        graph._graph = None  # force a rebuild with the swapped agent

        final = graph.execute(resume_text=SAMPLE_RESUME, job_description=SAMPLE_JOB_TEXT)
        entry = next(e for e in final["execution_trace"] if e["node"] == "extract_skills")
        assert entry["status"] == STATUS_ERROR
        assert "agent exploded" in entry["error"]
        assert has_errors(final) is True
        # The later nodes still ran.
        assert executed_nodes(final) == list(NODE_SEQUENCE)

    def test_an_llm_backed_run_uses_the_model(self):
        scripted = StubLLM(
            responses=[
                json.dumps(
                    {
                        "title": "Backend Engineer",
                        "seniority": "senior",
                        "required_skills": ["python", "rust"],
                        "preferred_skills": [],
                        "responsibilities": ["ship"],
                        "summary": "A backend role.",
                    }
                ),
                json.dumps({"skills": ["python"]}),
                json.dumps({"gaps": ["rust"], "strengths": ["python"], "explanation": "No Rust."}),
            ]
        )
        final = WorkflowGraph(llm=scripted).execute(
            resume_text="I write Python.", job_description="Backend Engineer"
        )
        assert final["all_analysis"]["analyze_job"]["source"] == "llm"
        assert final["skills_found"] == ["python"]
        assert final["gaps_identified"] == ["rust"]
        # Scoring stays deterministic even when a model is available.
        assert final["all_analysis"]["calculate_match"]["source"] == "fallback"
