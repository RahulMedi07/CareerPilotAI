"""Tests for the gap detector.

The behaviour worth protecting here is the *intelligence*, not the plumbing:
that learning estimates shrink when the candidate already knows something
adjacent, that required gaps outrank optional ones, and that a plan is never
returned without a way to act on it.
"""

from __future__ import annotations

import json

import pytest

from agents.gap_detector import (
    BASE_LEARNING_DAYS,
    CRITICAL,
    DEFAULT_LEARNING_DAYS,
    IMPORTANT,
    NICE_TO_HAVE,
    GapDetectorAgent,
    gap_detector,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
RESUME = {
    "skills": [
        "python", "langchain", "rag", "docker", "git", "fastapi",
        "embeddings", "chromadb",
    ]
}

JOB = {
    "required_skills": ["python", "langgraph", "kubernetes", "sql", "pinecone"],
    "preferred_skills": ["terraform", "react"],
    "tech_stack": ["python", "langgraph", "kubernetes", "pinecone"],
}

ADVERT = (
    "We need LangGraph. LangGraph orchestration is core to the role. "
    "You will use LangGraph daily, alongside Kubernetes and SQL. "
    "Pinecone backs our vector search."
)


def detect(resume=None, job=None, match=None, advert=ADVERT):
    return gap_detector.detect_gaps(
        resume if resume is not None else RESUME,
        job if job is not None else JOB,
        match,
        job_text=advert,
    )


@pytest.fixture
def report():
    return detect()


def by_skill(gaps):
    return {gap["skill_id"]: gap for gap in gaps}


# --------------------------------------------------------------------------- #
# Output structure
# --------------------------------------------------------------------------- #
class TestOutputStructure:
    def test_has_the_documented_top_level_keys(self, report):
        for key in (
            "critical_gaps",
            "nice_to_have_gaps",
            "priority_order",
            "total_learning_time_weeks",
            "quick_wins",
        ):
            assert key in report, key

    def test_report_is_json_serialisable(self, report):
        assert json.dumps(report)

    def test_every_critical_gap_has_the_documented_fields(self, report):
        for gap in report["critical_gaps"]:
            for key in (
                "skill",
                "required",
                "user_has",
                "importance",
                "why",
                "learning_time_days",
                "learning_resources",
                "similar_skills_user_has",
                "recommendation",
            ):
                assert key in gap, f"{gap['skill_id']} missing {key}"

    def test_gaps_are_never_marked_as_held(self, report):
        assert all(gap["user_has"] is False for gap in report["critical_gaps"])

    def test_required_flag_matches_the_bucket(self, report):
        assert all(g["required"] is True for g in report["critical_gaps"])
        assert all(g["required"] is False for g in report["nice_to_have_gaps"])

    def test_skill_is_a_display_name_and_skill_id_is_canonical(self, report):
        gap = by_skill(report["critical_gaps"])["langgraph"]
        assert gap["skill"] == "LangGraph"
        assert gap["skill_id"] == "langgraph"

    def test_priority_order_covers_every_gap(self, report):
        total = len(report["critical_gaps"]) + len(report["nice_to_have_gaps"])
        assert len(report["priority_order"]) == total

    def test_counts_agree_with_the_lists(self, report):
        assert report["critical_count"] == len(report["critical_gaps"])
        assert report["nice_to_have_count"] == len(report["nice_to_have_gaps"])


# --------------------------------------------------------------------------- #
# Categorisation
# --------------------------------------------------------------------------- #
class TestCategorisation:
    def test_skills_the_candidate_has_are_not_gaps(self, report):
        found = {g["skill_id"] for g in report["critical_gaps"]}
        assert "python" not in found
        assert "langchain" not in found

    def test_missing_required_skills_become_critical(self, report):
        found = {g["skill_id"] for g in report["critical_gaps"]}
        assert {"langgraph", "kubernetes", "pinecone"} <= found

    def test_missing_preferred_skills_become_nice_to_have(self, report):
        found = {g["skill_id"] for g in report["nice_to_have_gaps"]}
        assert {"terraform", "react"} <= found

    def test_a_skill_is_never_in_both_buckets(self, report):
        critical = {g["skill_id"] for g in report["critical_gaps"]}
        optional = {g["skill_id"] for g in report["nice_to_have_gaps"]}
        assert not (critical & optional)

    def test_aliases_are_not_reported_as_gaps(self):
        report = detect(
            resume={"skills": ["k8s"]},
            job={"required_skills": ["kubernetes"], "tech_stack": []},
        )
        assert report["critical_gaps"] == []

    def test_skills_are_read_from_resume_text_when_no_list_is_given(self):
        report = detect(
            resume={"resume_text": "I build APIs with Python and FastAPI."},
            job={"required_skills": ["python", "kubernetes"], "tech_stack": []},
        )
        assert {g["skill_id"] for g in report["critical_gaps"]} == {"kubernetes"}

    def test_no_gaps_when_the_candidate_has_everything(self):
        report = detect(
            resume={"skills": ["python", "docker"]},
            job={"required_skills": ["python", "docker"], "tech_stack": []},
        )
        assert report["critical_gaps"] == []
        assert report["total_learning_time_weeks"] == 0
        assert "No skill gaps" in report["summary"]


class TestMatchDataIsTrusted:
    """The match calculator has already done alias-aware matching."""

    def test_missing_list_from_the_match_report_is_used(self):
        match = {"match_breakdown": {"skills": {"missing": ["kubernetes"]}}}
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["python", "kubernetes"], "tech_stack": []},
            match=match,
        )
        # Python is absent from the resume but the match report did not call it
        # missing, so we defer rather than second-guess it.
        assert {g["skill_id"] for g in report["critical_gaps"]} == {"kubernetes"}

    def test_prose_components_never_become_gaps(self):
        # experience/education store strings like "1 more years", not skills.
        match = {
            "match_breakdown": {
                "skills": {"missing": ["sql"]},
                "experience": {"missing": "1 more years"},
                "education": {"missing": "masters"},
            }
        }
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["sql"], "tech_stack": []},
            match=match,
        )
        ids = {g["skill_id"] for g in report["critical_gaps"]}
        assert ids == {"sql"}

    def test_falls_back_to_top_level_missing_skills(self):
        match = {"missing_skills": ["docker"]}
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["docker", "python"], "tech_stack": []},
            match=match,
        )
        assert {g["skill_id"] for g in report["critical_gaps"]} == {"docker"}

    def test_unusable_match_data_falls_back_to_computing_the_difference(self):
        report = detect(
            resume={"skills": ["python"]},
            job={"required_skills": ["python", "docker"], "tech_stack": []},
            match={"nonsense": True},
        )
        assert {g["skill_id"] for g in report["critical_gaps"]} == {"docker"}


# --------------------------------------------------------------------------- #
# Learning time - the part that makes this more than a list
# --------------------------------------------------------------------------- #
class TestLearningTime:
    def test_related_experience_halves_the_estimate(self):
        """The brief's worked example: LangChain on the resume means 7 days."""
        agent = GapDetectorAgent()
        assert agent._estimate_learning_time("langgraph") == 14
        assert agent._estimate_learning_time("langgraph", ["langchain"]) == 7

    def test_an_unknown_skill_with_nothing_related_costs_the_default(self):
        agent = GapDetectorAgent()
        assert agent._estimate_learning_time("some-new-framework") == DEFAULT_LEARNING_DAYS
        assert DEFAULT_LEARNING_DAYS == 30

    def test_several_relatives_discount_further_than_one(self):
        agent = GapDetectorAgent()
        one = agent._estimate_learning_time("langgraph", ["langchain"])
        many = agent._estimate_learning_time("langgraph", ["langchain", "rag", "llm"])
        assert many < one

    def test_a_distant_relative_discounts_less_than_a_close_one(self):
        agent = GapDetectorAgent()
        # kubernetes/docker share a tight family; react/python do not.
        close = agent._estimate_learning_time("kubernetes", ["docker"])
        assert close == BASE_LEARNING_DAYS["kubernetes"] // 2

    def test_estimates_never_fall_below_the_floor(self):
        agent = GapDetectorAgent()
        days = agent._estimate_learning_time("markdown", ["html", "css", "react"])
        assert days >= 2

    def test_estimates_are_whole_days(self, report):
        for gap in report["critical_gaps"] + report["nice_to_have_gaps"]:
            assert isinstance(gap["learning_time_days"], int)
            assert gap["learning_time_days"] > 0

    def test_big_concepts_cost_more_than_small_tools(self):
        agent = GapDetectorAgent()
        assert agent._estimate_learning_time("machine learning") > agent._estimate_learning_time("git")


class TestSimilarSkills:
    def test_finds_a_relative_in_the_same_family(self):
        similar = gap_detector._find_similar_skills("langgraph", {"langchain", "java"})
        assert "langchain" in similar
        assert "java" not in similar

    def test_finds_relatives_across_the_database_family(self):
        similar = gap_detector._find_similar_skills("sql", {"postgresql"})
        assert "postgresql" in similar

    def test_returns_nothing_when_there_is_no_overlap(self):
        assert gap_detector._find_similar_skills("kubernetes", {"react", "vue"}) == []

    def test_a_skill_is_not_its_own_relative(self):
        assert "docker" not in gap_detector._find_similar_skills("docker", {"docker"})

    def test_similar_skills_appear_in_the_gap(self, report):
        gap = by_skill(report["critical_gaps"])["langgraph"]
        assert "LangChain" in gap["similar_skills_user_has"]

    def test_similar_skills_are_display_names(self, report):
        gap = by_skill(report["critical_gaps"])["pinecone"]
        assert "ChromaDB" in gap["similar_skills_user_has"]


# --------------------------------------------------------------------------- #
# Importance and priority
# --------------------------------------------------------------------------- #
class TestImportance:
    def test_a_core_stack_skill_is_critical(self, report):
        assert by_skill(report["critical_gaps"])["langgraph"]["importance"] == CRITICAL

    def test_a_repeatedly_mentioned_skill_is_critical(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["rust"], "tech_stack": []},
            advert="We use Rust. Rust everywhere. Rust.",
        )
        assert report["critical_gaps"][0]["importance"] == CRITICAL

    def test_a_barely_mentioned_requirement_is_only_important(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["rust"], "tech_stack": []},
            advert="Some Rust would help.",
        )
        assert report["critical_gaps"][0]["importance"] == IMPORTANT

    def test_preferred_skills_are_nice_to_have(self, report):
        for gap in report["nice_to_have_gaps"]:
            assert gap["importance"] == NICE_TO_HAVE

    def test_why_explains_the_grade(self, report):
        gap = by_skill(report["critical_gaps"])["langgraph"]
        assert "3 times" in gap["why"]
        assert "core tech stack" in gap["why"]

    def test_mentions_count_is_reported(self, report):
        assert by_skill(report["critical_gaps"])["langgraph"]["mentions_in_job"] == 3

    def test_mentions_are_zero_without_the_advert_text(self):
        report = detect(advert="")
        assert all(g["mentions_in_job"] == 0 for g in report["critical_gaps"])


class TestPrioritisation:
    def test_critical_gaps_come_before_nice_to_have(self, report):
        order = report["priority_order"]
        critical = {g["skill"] for g in report["critical_gaps"]}
        optional = {g["skill"] for g in report["nice_to_have_gaps"]}
        last_critical = max(order.index(s) for s in critical)
        first_optional = min(order.index(s) for s in optional)
        assert last_critical < first_optional

    def test_the_most_mentioned_skill_leads(self, report):
        assert report["priority_order"][0] in {"LangGraph", "Pinecone"}
        assert by_skill(report["critical_gaps"])["langgraph"]["mentions_in_job"] == 3

    def test_ties_break_towards_the_cheaper_gap(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["kubernetes", "git"], "tech_stack": ["kubernetes", "git"]},
            advert="",
        )
        assert report["priority_order"] == ["Git", "Kubernetes"]

    def test_ordering_is_stable_for_identical_input(self):
        assert detect()["priority_order"] == detect()["priority_order"]


# --------------------------------------------------------------------------- #
# Learning paths
# --------------------------------------------------------------------------- #
class TestLearningPath:
    def test_every_gap_gets_at_least_one_resource(self, report):
        for gap in report["critical_gaps"] + report["nice_to_have_gaps"]:
            assert gap["learning_resources"]

    def test_known_skills_get_curated_resources(self, report):
        resources = by_skill(report["critical_gaps"])["langgraph"]["learning_resources"]
        assert any("LangGraph" in r for r in resources)

    def test_unknown_skills_still_get_a_sensible_default(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["obscure-tool"], "tech_stack": []},
        )
        resources = report["critical_gaps"][0]["learning_resources"]
        assert any("documentation" in r.lower() for r in resources)

    def test_resources_mention_related_experience_when_there_is_some(self, report):
        resources = by_skill(report["critical_gaps"])["langgraph"]["learning_resources"]
        assert any("skim" in r.lower() for r in resources)

    def test_the_timeline_covers_the_whole_estimate(self, report):
        for gap in report["critical_gaps"]:
            last = gap["learning_path"][-1]["days"]
            assert int(last.split("-")[-1]) == gap["learning_time_days"]

    def test_the_timeline_starts_on_day_one(self, report):
        for gap in report["critical_gaps"]:
            assert gap["learning_path"][0]["days"].startswith("1-")

    def test_short_gaps_get_fewer_phases_than_long_ones(self):
        agent = GapDetectorAgent()
        short = agent._generate_learning_path(
            {"skill_id": "git", "learning_time_days": 5, "similar_skills_user_has": []}
        )
        long = agent._generate_learning_path(
            {"skill_id": "kubernetes", "learning_time_days": 30, "similar_skills_user_has": []}
        )
        assert len(short["timeline"]) < len(long["timeline"])

    def test_every_phase_has_a_goal(self, report):
        for gap in report["critical_gaps"]:
            for phase in gap["learning_path"]:
                assert phase["goal"].strip()

    def test_no_resource_invents_a_url(self, report):
        for gap in report["critical_gaps"] + report["nice_to_have_gaps"]:
            for resource in gap["learning_resources"]:
                assert "http://" not in resource
                assert "https://" not in resource


class TestRecommendations:
    def test_every_gap_gets_a_recommendation(self, report):
        for gap in report["critical_gaps"] + report["nice_to_have_gaps"]:
            assert gap["recommendation"].strip()

    def test_a_recommendation_names_the_transferable_skill(self, report):
        gap = by_skill(report["critical_gaps"])["langgraph"]
        assert "LangChain" in gap["recommendation"]

    def test_nice_to_have_recommendations_say_so(self, report):
        text = " ".join(g["recommendation"] for g in report["nice_to_have_gaps"])
        assert "priority" in text.lower()

    def test_a_long_road_is_named_honestly(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["machine learning"], "tech_stack": []},
        )
        assert "honest" in report["critical_gaps"][0]["recommendation"].lower()


# --------------------------------------------------------------------------- #
# Quick wins and totals
# --------------------------------------------------------------------------- #
class TestQuickWins:
    def test_quick_wins_are_cheap(self, report):
        for win in report["quick_wins"]:
            assert win["learning_time_days"] <= gap_detector.quick_win_days

    def test_quick_wins_explain_why_they_are_quick(self, report):
        for win in report["quick_wins"]:
            assert win["why"].strip()

    def test_a_gap_made_cheap_by_experience_becomes_a_quick_win(self, report):
        names = {win["skill"] for win in report["quick_wins"]}
        assert "LangGraph" in names

    def test_expensive_gaps_are_not_quick_wins(self, report):
        names = {win["skill"] for win in report["quick_wins"]}
        assert "Kubernetes" not in names

    def test_quick_wins_are_ordered_cheapest_first(self, report):
        days = [w["learning_time_days"] for w in report["quick_wins"]]
        assert days == sorted(days)


class TestTotals:
    def test_weeks_are_derived_from_the_critical_gaps(self, report):
        assert report["blocking_learning_days"] == sum(
            g["learning_time_days"] for g in report["critical_gaps"]
        )

    def test_weeks_round_up(self):
        assert GapDetectorAgent._to_weeks(8) == 2
        assert GapDetectorAgent._to_weeks(7) == 1
        assert GapDetectorAgent._to_weeks(1) == 1
        assert GapDetectorAgent._to_weeks(0) == 0

    def test_nice_to_have_gaps_do_not_inflate_the_total(self):
        with_optional = detect()
        without = detect(
            job={
                "required_skills": JOB["required_skills"],
                "preferred_skills": [],
                "tech_stack": JOB["tech_stack"],
            }
        )
        assert with_optional["total_learning_time_weeks"] == without["total_learning_time_weeks"]

    def test_summary_names_the_critical_gaps(self, report):
        assert "critical" in report["summary"].lower()


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
class TestEdgeCases:
    def test_empty_job_gives_an_empty_plan(self):
        report = detect(resume=RESUME, job={})
        assert report["critical_gaps"] == []
        assert report["priority_order"] == []
        assert report["total_learning_time_weeks"] == 0

    def test_empty_resume_makes_everything_a_gap(self):
        report = detect(resume={}, job=JOB)
        assert len(report["critical_gaps"]) == len(JOB["required_skills"])

    def test_both_empty_does_not_raise(self):
        assert detect(resume={}, job={})["summary"]

    def test_duplicate_requirements_are_reported_once(self):
        report = detect(
            resume={"skills": []},
            job={"required_skills": ["docker", "Docker", "DOCKER"], "tech_stack": []},
        )
        assert len(report["critical_gaps"]) == 1

    def test_none_values_are_tolerated(self):
        report = detect(
            resume={"skills": None, "resume_text": None},
            job={"required_skills": None, "preferred_skills": None, "tech_stack": None},
        )
        assert report["critical_gaps"] == []

    def test_a_skill_listed_as_both_required_and_preferred_is_critical_only(self):
        report = detect(
            resume={"skills": []},
            job={
                "required_skills": ["docker"],
                "preferred_skills": ["docker"],
                "tech_stack": [],
            },
        )
        assert len(report["critical_gaps"]) == 1
        assert report["nice_to_have_gaps"] == []

    def test_the_advert_can_be_read_from_the_job_analysis(self):
        report = gap_detector.detect_gaps(
            {"skills": []},
            {
                "required_skills": ["rust"],
                "tech_stack": [],
                "job_description": "Rust. Rust. Rust.",
            },
        )
        assert report["critical_gaps"][0]["mentions_in_job"] == 3


# --------------------------------------------------------------------------- #
# Graph integration
# --------------------------------------------------------------------------- #
class TestWorkflowIntegration:
    def test_the_node_reports_the_gap_detector_in_the_trace(self):
        from agents.graph_builder import WorkflowGraph

        final = WorkflowGraph().execute(
            resume_text="Python engineer using FastAPI and Docker.",
            job_description="Need Python, Kubernetes and Terraform.",
        )
        entry = next(e for e in final["execution_trace"] if e["node"] == "detect_gaps")
        assert entry["label"] == "Gap Detector"
        assert entry["status"] == "completed"
        assert "critical_gaps" in entry
        assert "total_learning_weeks" in entry

    def test_the_full_report_is_attached_to_the_analysis(self):
        from agents.graph_builder import WorkflowGraph

        final = WorkflowGraph().execute(
            resume_text="Python engineer using FastAPI and Docker.",
            job_description="Need Python, Kubernetes and Terraform.",
        )
        report = final["all_analysis"]["detect_gaps"]["gap_report"]
        assert report["priority_order"]
        assert report["critical_count"] >= 1

    def test_the_plain_gaps_list_is_unchanged(self):
        from agents.graph_builder import WorkflowGraph

        final = WorkflowGraph().execute(
            resume_text="Python engineer using FastAPI and Docker.",
            job_description="Need Python and Kubernetes.",
        )
        assert all(isinstance(g, str) for g in final["gaps_identified"])
