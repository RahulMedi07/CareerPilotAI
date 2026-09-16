"""Week 2 behaviour: richer output, and agents that refuse to crash.

These sit apart from the per-agent suites because they test promises that span
all four agents - most importantly that a wrong-shaped argument produces a
thin report rather than a stack trace.
"""

from __future__ import annotations

import pytest

from agents.gap_detector import _DOC_URLS, _PRACTICE_PROJECTS, GapDetectorAgent
from agents.interview_prep import GAP_BASED, TECHNICAL, InterviewPrepAgent
from agents.match_calculator import MatchCalculator
from agents.resume_optimizer import ResumeOptimizerAgent

RESUME = {
    "resume_text": """
John Smith
Summary
Junior AI Developer with 2 years building retrieval systems.

Experience
Junior AI Developer - TechCorp (2023-Present)
- Built a RAG pipeline with LangChain over internal documentation
- Deployed services with Docker and wrote the FastAPI layer

Skills
Python, LangChain, FastAPI, Docker, ChromaDB
""",
    "skills": ["python", "langchain", "fastapi", "docker", "chromadb"],
}

JOB = {
    "required_skills": ["python", "langchain", "langgraph", "kubernetes"],
    "preferred_skills": ["pinecone"],
    "tech_stack": ["python", "langgraph"],
    "job_description": (
        "We need LangGraph. LangGraph experience is essential, and LangGraph "
        "agents are the core of the product. Python and Kubernetes required."
    ),
}

#: Every shape a caller could plausibly get wrong.
JUNK = [None, "a string", 123, 4.5, [], {}, True, ["a"], {"skills": None}]


class TestNoAgentCrashesOnBadInput:
    """A shape mistake must cost a thin report, never the run.

    Before week two each of these raised `AttributeError: 'NoneType' object has
    no attribute 'get'` partway through, discarding the stages that had already
    succeeded.
    """

    @pytest.mark.parametrize("first", JUNK)
    @pytest.mark.parametrize("second", JUNK)
    def test_gap_detector(self, first, second):
        assert isinstance(GapDetectorAgent().detect_gaps(first, second), dict)

    @pytest.mark.parametrize("first", JUNK)
    @pytest.mark.parametrize("second", JUNK)
    def test_resume_optimizer(self, first, second):
        assert isinstance(ResumeOptimizerAgent().optimize_resume(first, second), dict)

    @pytest.mark.parametrize("first", JUNK)
    @pytest.mark.parametrize("second", JUNK)
    def test_interview_prep(self, first, second):
        assert isinstance(InterviewPrepAgent().prepare_interview(first, second), dict)

    @pytest.mark.parametrize("first", JUNK)
    @pytest.mark.parametrize("second", JUNK)
    def test_match_calculator(self, first, second):
        assert isinstance(MatchCalculator().calculate_match(first, second), dict)

    def test_a_junk_run_still_answers_the_questions_it_can(self):
        """Degrading is only useful if the keys the UI reads are still there."""
        report = GapDetectorAgent().detect_gaps("nonsense", 42)
        for key in ("critical_gaps", "nice_to_have_gaps", "quick_wins", "summary"):
            assert key in report

    def test_a_caller_cannot_mutate_its_own_argument_through_an_agent(self):
        resume = dict(RESUME)
        before = dict(resume)
        GapDetectorAgent().detect_gaps(resume, JOB)
        assert resume == before


class TestLearningResources:
    """Gaps now carry somewhere to start and something to build."""

    def _gap(self, skill):
        report = GapDetectorAgent().detect_gaps(RESUME, JOB)
        every = report["critical_gaps"] + report["nice_to_have_gaps"]
        for gap in every:
            if gap["skill_id"] == skill:
                return gap
        pytest.fail("expected a %s gap, got %s" % (skill, [g["skill_id"] for g in every]))

    def test_a_known_gap_links_to_official_documentation(self):
        assert self._gap("langgraph")["documentation"] == _DOC_URLS["langgraph"]

    def test_a_known_gap_suggests_something_to_build(self):
        project = self._gap("langgraph")["practice_project"]
        assert project and len(project.split()) > 5

    def test_an_unknown_skill_gets_none_rather_than_a_guessed_link(self):
        """A missing link is honest; an invented one is not.

        `None` lets the caller tell "we have nothing" apart from "here is
        something plausible", which is the whole reason URLs are curated.
        """
        report = GapDetectorAgent().detect_gaps(
            {"skills": ["python"]},
            {"required_skills": ["python", "obscure in-house framework"]},
        )
        every = report["critical_gaps"] + report["nice_to_have_gaps"]
        invented = [g for g in every if g["skill_id"] not in _DOC_URLS]
        assert invented, "expected at least one skill with no curated link"
        assert all(g["documentation"] is None for g in invented)

    def test_every_curated_link_is_https(self):
        assert all(url.startswith("https://") for url in _DOC_URLS.values())

    def test_every_curated_link_belongs_to_a_skill_the_agent_knows(self):
        """A link nobody can reach is dead weight in the table."""
        from agents.gap_detector import BASE_LEARNING_DAYS, SKILL_FAMILIES

        known = set(BASE_LEARNING_DAYS)
        for members in SKILL_FAMILIES.values():
            known |= members
        for skill in list(_DOC_URLS) + list(_PRACTICE_PROJECTS):
            assert skill in known, "%s is linked but unknown to the agent" % skill


class TestKeywordDensity:
    """Counting, shown as counts, so the reader can disagree with it."""

    def _rows(self, with_gaps=False):
        gaps = GapDetectorAgent().detect_gaps(RESUME, JOB) if with_gaps else None
        report = ResumeOptimizerAgent().optimize_resume(RESUME, JOB, gaps)
        return {row["keyword"].lower(): row for row in report["keyword_density"]}

    def test_it_reports_both_numbers(self):
        rows = self._rows()
        assert rows
        for row in rows.values():
            assert isinstance(row["in_resume"], int)
            assert isinstance(row["in_job_advert"], int)

    def test_a_skill_the_advert_stresses_but_the_resume_lacks_is_flagged(self):
        row = self._rows()["langgraph"]
        assert row["in_resume"] == 0
        assert row["in_job_advert"] >= 3

    def test_a_gap_is_shown_but_never_recommended(self):
        """The count proves it matters; the action still refuses to fabricate."""
        row = self._rows(with_gaps=True)["langgraph"]
        assert row["verdict"] == "gap"
        assert "learn" in row["action"].lower()

    def test_without_a_gap_analysis_it_still_refuses_to_invent(self):
        """No gap data means we cannot prove it is a gap - but not that it is safe."""
        row = self._rows()["langgraph"]
        assert row["verdict"] == "absent"
        assert "only add" in row["action"].lower()

    def test_counting_does_not_match_inside_longer_words(self):
        """"Go" must not be found inside "Django"."""
        from agents.resume_optimizer import _count_word

        assert _count_word("i used django daily", "go") == 0
        assert _count_word("i wrote go daily", "go") == 1

    def test_counting_survives_punctuation_in_skill_names(self):
        from agents.resume_optimizer import _count_word

        assert _count_word("built ci/cd pipelines", "ci/cd") == 1
        assert _count_word("wrote c++ and node.js", "c++") == 1
        assert _count_word("wrote c++ and node.js", "node.js") == 1


class TestQuestionSplit:
    """The same questions, grouped by what they actually test."""

    def _report(self):
        gaps = GapDetectorAgent().detect_gaps(RESUME, JOB)
        return InterviewPrepAgent().prepare_interview(JOB, RESUME, gaps)

    def test_strengths_and_weaknesses_are_separated(self):
        report = self._report()
        assert all(q["category"] == TECHNICAL for q in report["strength_questions"])
        assert all(q["category"] == GAP_BASED for q in report["weakness_questions"])

    def test_the_split_is_a_view_and_loses_nothing(self):
        report = self._report()
        assert len(report["strength_questions"]) + len(
            report["weakness_questions"]
        ) == len(report["questions"])

    def test_numbering_is_shared_so_question_seven_means_one_thing(self):
        report = self._report()
        by_id = {q["id"]: q for q in report["questions"]}
        for group in ("strength_questions", "weakness_questions"):
            for question in report[group]:
                assert by_id[question["id"]] is question


class TestSuccessRateReasoning:
    """The prediction now shows its arithmetic."""

    def _reasoning(self, match=None, gaps=None):
        return InterviewPrepAgent().prepare_interview(
            JOB, RESUME, gaps, match or {"overall_match": 78.0}
        )["success_rate_reasoning"]

    def test_it_lists_the_match_as_a_factor(self):
        factors = self._reasoning()["factors"]
        assert any("match" in f["factor"].lower() for f in factors)

    def test_every_factor_says_what_it_did_and_why(self):
        for factor in self._reasoning()["factors"]:
            assert factor["effect"]
            assert len(factor["why"].split()) > 3

    def test_critical_gaps_appear_as_a_penalty(self):
        gaps = GapDetectorAgent().detect_gaps(RESUME, JOB)
        factors = self._reasoning(gaps=gaps)["factors"]
        penalties = [f for f in factors if f["effect"].startswith("-")]
        assert penalties

    def test_preparation_is_deliberately_not_a_factor(self):
        """We hand out a plan; we never watch anyone follow it.

        Multiplying the estimate by "prep completeness" would raise the number
        using a fact nobody measured, which is the most flattering way to lie.
        """
        reasoning = self._reasoning()
        assert not any("prep" in f["factor"].lower() for f in reasoning["factors"])
        assert "preparation" in reasoning["caveat"].lower()

    def test_the_headline_number_matches_the_prediction(self):
        report = InterviewPrepAgent().prepare_interview(
            JOB, RESUME, None, {"overall_match": 78.0}
        )
        assert (
            report["success_rate_reasoning"]["predicted"]
            == report["success_rate_prediction"]
        )

    def test_a_perfect_resume_is_still_capped_below_certainty(self):
        reasoning = self._reasoning(match={"overall_match": 100.0})
        assert reasoning["predicted"] <= 0.92
        assert reasoning["capped"] is True
        assert "92" in reasoning["caveat"]

    def test_an_unreadable_match_score_does_not_raise(self):
        assert self._reasoning(match={"overall_match": "not a number"})["predicted"] > 0
