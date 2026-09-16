"""Tests for ``agents.advanced_workflow``.

The load-bearing test in this file is
``test_the_rescore_never_claims_a_blocked_skill``. Measured on the sample
resume and advert, the entire ~20-point uplift that a naive "re-score after
optimisation" step appears to deliver comes from adding CI/CD, LangGraph and
Pinecone - the three skills the optimiser explicitly refuses to let the
candidate claim. An honest re-score moves the score by nothing at all. That is
the finding, and this file exists to keep it true.
"""

from __future__ import annotations

import pytest

from agents.advanced_workflow import (
    APPLY_AFTER_LEARNING,
    APPLY_NOW,
    SKIP,
    AdvancedWorkflow,
)
from agents.workflow_state import create_initial_state


@pytest.fixture
def flow():
    return AdvancedWorkflow()


def gap(skill, days):
    return {
        "skill": skill,
        "learning_time_days": days,
        "importance": "CRITICAL",
    }


def rescore(flow, keywords, blocked):
    """Run the re-score node and hand back the detail it recorded."""
    state = create_initial_state(resume_text="r", job_description="j")
    state["skills_found"] = ["python"]
    state["match_score"] = 40.0
    state["all_analysis"] = {
        "optimize_resume": {
            "keywords_to_add": list(keywords),
            "keywords_blocked_by_gaps": list(blocked),
        }
    }
    updated = flow.node_re_calculate_match(state)
    return updated, updated["all_analysis"]["re_calculate_match"]


class TestRescoreHonesty:
    def test_the_rescore_never_claims_a_blocked_skill(self, flow):
        """The projected score may only use keywords the resume can support.

        Adding the blocked ones is what makes the number jump. It is also a
        lie about the candidate.
        """
        _, explained = rescore(
            flow, ["Docker", "CI/CD", "LangGraph"], ["CI/CD", "LangGraph"]
        )
        assert "CI/CD" not in explained["truthful_additions"]
        assert "LangGraph" not in explained["truthful_additions"]
        assert "Docker" in explained["truthful_additions"]

    def test_the_blocked_skills_are_named_not_silently_dropped(self, flow):
        _, explained = rescore(flow, ["Docker", "CI/CD"], ["CI/CD"])
        assert "ci/cd" in explained["refused_additions"]

    def test_the_rescore_does_not_overwrite_the_real_score(self, flow):
        """``match_score`` is what the resume actually scores. It is not a
        draft to be improved by a later node."""
        updated, _ = rescore(flow, ["Docker"], [])
        assert "match_score" not in updated
        assert "projected_match_score" in updated

    def test_a_zero_delta_is_explained_rather_than_left_looking_broken(self, flow):
        _, explained = rescore(flow, ["CI/CD"], ["CI/CD"])
        assert explained["note"]
        assert explained["delta"] == 0.0


class TestVerdict:
    # "Python role." is 12 characters, which the job analyzer rejects as too
    # short to read. These three tests were therefore never reaching the
    # verdict logic they claim to cover -- they were exercising the
    # nothing-to-measure path while asserting a normal outcome. A real advert
    # restores their intent; the unmeasurable case gets its own test below.
    ADVERT = (
        "Backend Python developer. Required: Python, SQL, Git and Docker. "
        "3+ years building web services."
    )
    RESUME = "Python developer with SQL and Git."

    def test_the_verdict_is_one_of_the_three_documented_outcomes(self, flow):
        result = flow.run(self.RESUME, self.ADVERT)
        assert result["recommendation"] in (APPLY_NOW, APPLY_AFTER_LEARNING, SKIP)

    def test_the_headline_does_not_contradict_the_reasoning(self, flow):
        """A headline saying nothing needs closing, above reasoning listing
        three critical gaps, is the advice arguing with itself."""
        result = flow.run(self.RESUME, self.ADVERT)
        final = result["final"]
        if final["blocking_learning_days"] > 0:
            assert "nothing needs closing" not in final["headline"]

    def test_it_says_how_its_verdict_relates_to_the_score(self, flow):
        result = flow.run(self.RESUME, self.ADVERT)
        assert "scored_verdict" in result["final"]

    def test_an_advert_with_no_requirements_gets_no_timing_verdict(self, flow):
        """Timing advice presupposes a fit score. Without one there is none.

        This node used to append "Skip this one - 0/100..." to a summary that
        had just said the job could not be scored, because the missing score
        was coerced to 0.0 on the way in.
        """
        result = flow.run(self.RESUME, "Python role.")
        assert result["recommendation"] == "NOT_SCORED"
        assert result["final"]["match_score"] is None
        assert "0/100" not in result["user_recommendation"]
        # The node still fills its own slot; callers read `final` regardless.
        assert "blocking_learning_days" in result["final"]


class TestRunShape:
    def test_a_run_returns_the_documented_keys(self, flow):
        result = flow.run("Python developer.", "Python role.")
        for key in (
            "initial_match",
            "optimized_match",
            "recommendation",
            "gaps",
            "optimizations",
            "learning_plan",
            "interview_prep",
        ):
            assert key in result

    def test_the_path_records_which_way_the_graph_went(self, flow):
        result = flow.run("Python developer.", "Python role.")
        assert result["path"][0] == "analyze_job"
        assert result["path"][-1] == "final_recommendation"

    def test_every_branch_taken_is_explained(self, flow):
        result = flow.run("Python developer.", "Python role.")
        for decision in result["decisions"]:
            assert decision["reason"]
            assert decision["branch"]

    def test_the_collaboration_transcript_is_returned(self, flow):
        result = flow.run("Python developer.", "Python role.")
        assert result["collaboration"]

    def test_an_empty_resume_does_not_raise(self, flow):
        result = flow.run("", "")
        assert result["recommendation"] in (APPLY_NOW, APPLY_AFTER_LEARNING, SKIP)

    def test_a_failing_node_is_reported_not_swallowed(self, flow):
        def explode(state):
            raise RuntimeError("gap detection is down")

        flow.node_detect_gaps = explode
        flow._compiled = None
        result = flow.run("Python developer.", "Python role.")
        assert "detect_gaps" in result["nodes_failed"]

    def test_a_failing_node_still_produces_a_verdict(self, flow):
        def explode(state):
            raise RuntimeError("gap detection is down")

        flow.node_detect_gaps = explode
        flow._compiled = None
        result = flow.run("Python developer.", "Python role.")
        assert result["recommendation"]


class TestFallbackAgrees:
    def test_the_fallback_takes_the_same_branches_as_the_graph(self, flow):
        """If the two engines disagree, one of them is giving wrong advice."""
        resume = "Python developer with SQL, Git and REST experience."
        job = "Backend engineer. Python, SQL, Git, REST, Docker."
        graph = flow.run(resume, job)

        other = AdvancedWorkflow()
        state = create_initial_state(resume_text=resume, job_description=job)
        fallback = other._result(other._run_sequentially(state))

        assert graph["path"] == fallback["path"]
        assert graph["recommendation"] == fallback["recommendation"]

    def test_the_fallback_reaches_the_same_score(self, flow):
        resume = "Python developer with SQL, Git and REST experience."
        job = "Backend engineer. Python, SQL, Git, REST, Docker."
        graph = flow.run(resume, job)

        other = AdvancedWorkflow()
        state = create_initial_state(resume_text=resume, job_description=job)
        fallback = other._result(other._run_sequentially(state))

        assert graph["initial_match"] == fallback["initial_match"]


class TestGapsAlwaysAvailable:
    def test_gaps_are_present_whichever_branch_the_score_takes(self):
        """The brief assigned ``gaps`` only inside ``if match < 70`` and then
        read it unconditionally. On the sample data, which scores above 70,
        that is an UnboundLocalError."""
        strong = AdvancedWorkflow().run(
            "Senior Python engineer with SQL, Git, REST, Docker and FastAPI.",
            "Python role. SQL and Git required.",
        )
        weak = AdvancedWorkflow().run("Trainee.", "Senior Kubernetes architect.")
        for result in (strong, weak):
            assert result["gaps"] is not None
            assert "detect_gaps" in result["path"]


class TestDescribe:
    def test_it_can_describe_its_own_shape(self, flow):
        described = flow.describe()
        assert described["nodes"]
        assert described["conditional_edges"]
