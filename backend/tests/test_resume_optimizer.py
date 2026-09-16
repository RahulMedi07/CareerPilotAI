"""Tests for the resume optimiser.

Most of this file guards one property: **the optimiser must never write a claim
the candidate cannot defend in an interview.**

That sounds obvious until you look at what a resume tool is naturally pulled
towards doing. The most impressive-sounding rewrite of "Built RAG system with
LangChain" is something like "processed 10K+ documents at 95% retrieval
accuracy" - and a tool that emits that string has just invented two numbers.
The candidate pastes it in, an interviewer asks "how did you measure the 95%?",
and the answer is that a program made it up. Similarly, the fastest way to
raise a keyword-match score is to add the missing keywords - which means
advising someone to list a skill they do not have.

Both failures are silent. The output looks *better* in every case, which is
exactly why they need tests rather than good intentions. So the honesty
classes below (:class:`TestNeverInventsFacts`, :class:`TestNeverSuggestsALie`)
are the ones worth keeping if the rest of this file is ever thrown away.
"""

from __future__ import annotations

import json

import pytest

from agents.resume_optimizer import (
    HIGH,
    LOW,
    MEDIUM,
    PLACEHOLDERS,
    ResumeOptimizerAgent,
    resume_optimizer,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

RESUME = """
RAHUL SHARMA
AI/ML Developer with 2 years experience building web and AI applications.

SKILLS
Python, FastAPI, REST APIs
LangChain, RAG, Embeddings
React, Next.js, Tailwind CSS
Docker, Git, PostgreSQL

EXPERIENCE
AI Developer - TechCorp (2023-present)
- Built RAG system with LangChain
- Created REST APIs with FastAPI
- Worked with Chroma vector database

Intern - AI Startup (2022-2023)
- Assisted with Python development
- Learned LLM basics

PROJECTS
1. Document Q&A System
- Built with LangChain + RAG
- Used Chroma for vector storage

2. Job Matching Algorithm
- Python implementation
- Embeddings-based matching

EDUCATION
B.Tech Computer Science, 2022

ACHIEVEMENTS
- AI & ML Fundamentals certification
"""

JOB = {
    "title": "AI/ML Engineer",
    "required_skills": ["python", "langchain", "rag", "embeddings", "pinecone"],
    "preferred_skills": ["fastapi", "react"],
    "tech_stack": ["python", "langchain"],
    "experience_years": 2,
    "role_type": "ai/ml",
    "job_description": (
        "We need an AI/ML Engineer strong in LangChain and RAG. You will build "
        "RAG pipelines, tune RAG retrieval, and own our RAG stack end to end. "
        "Python and embeddings essential. Pinecone experience required."
    ),
}

GAPS = {
    "critical_gaps": [
        {
            "skill": "Pinecone",
            "skill_id": "pinecone",
            "importance": "CRITICAL",
            "learning_time_days": 7,
            "similar_skills_user_has": ["chroma"],
        }
    ],
    "nice_to_have_gaps": [],
}

MATCH = {
    "overall_match": 60.0,
    "recommendation": "MAYBE",
    "matched_skills": ["python", "langchain", "rag", "embeddings"],
    "missing_skills": ["pinecone"],
}


def optimise(resume=RESUME, job=None, gaps=GAPS, match=MATCH):
    """Run the optimiser, defaulting to the realistic fixture above."""
    return resume_optimizer.optimize_resume(
        {"resume_text": resume},
        dict(JOB if job is None else job),
        gaps,
        match,
    )


@pytest.fixture(scope="module")
def report():
    return optimise()


@pytest.fixture
def agent():
    return ResumeOptimizerAgent()


def all_text(report) -> str:
    """Every string the optimiser would show a user, flattened."""
    return json.dumps(report).lower()


# --------------------------------------------------------------------------
# Honesty: the two properties that matter most
# --------------------------------------------------------------------------


class TestNeverInventsFacts:
    """No rewrite may contain a number the candidate did not supply."""

    def test_rewrites_use_placeholders_not_invented_numbers(self, report):
        for item in report["improvements"]:
            text = item.get("suggested_description") or item.get("suggested") or ""
            stripped = text
            for placeholder in PLACEHOLDERS:
                stripped = stripped.replace(placeholder, "")
            digits = [c for c in stripped if c.isdigit()]
            # Any digit left must have come from the candidate's own line.
            original = (item.get("current_description") or item.get("current") or "")
            for digit in digits:
                assert digit in original, (
                    f"invented the digit {digit!r} in: {text!r}"
                )

    def test_anything_with_a_placeholder_asks_the_user_to_fill_it_in(self, report):
        for item in report["improvements"]:
            if item.get("placeholders"):
                assert item["needs_your_input"] is True

    def test_placeholders_are_declared_not_hidden(self, report):
        for item in report["improvements"]:
            text = item.get("suggested_description") or item.get("suggested") or ""
            for placeholder in PLACEHOLDERS:
                if placeholder in text:
                    assert placeholder in item["placeholders"]

    def test_summary_never_states_an_achievement_it_cannot_know(self, report):
        summary = report["tailored_summary"]
        # Any figure in the summary must be a slot, or the years from the CV.
        assert "[RESULT]" in summary or "[NUMBER]" in summary or not any(
            c.isdigit() for c in summary.replace("2+", "")
        )

    def test_output_carries_an_honesty_note(self, report):
        assert report["honesty_note"]

    def test_no_rewrite_invents_a_technology(self, report):
        """A rewrite may re-word, but not add a tool that appears nowhere."""
        for item in report["improvements"]:
            text = (
                item.get("suggested_description") or item.get("suggested") or ""
            ).lower()
            if not text:
                continue
            for invented in ("kubernetes", "kafka", "terraform", "spark"):
                assert invented not in text


class TestNeverSuggestsALie:
    """No advice may push the candidate to claim a skill they lack."""

    def test_gap_skills_are_not_offered_as_keywords_to_add(self, report):
        added = {k.lower() for k in report["keywords_to_add"]}
        assert "pinecone" not in added

    def test_gap_skills_are_reported_separately_and_honestly(self, report):
        assert "Pinecone" in report["keywords_blocked_by_gaps"]

    def test_blocked_and_suggested_lists_never_overlap(self, report):
        added = {k.lower() for k in report["keywords_to_add"]}
        blocked = {k.lower() for k in report["keywords_blocked_by_gaps"]}
        assert not (added & blocked)

    def test_the_tailored_summary_does_not_name_a_missing_skill(self, report):
        assert "pinecone" not in report["tailored_summary"].lower()

    def test_the_headline_title_does_not_name_a_missing_skill(self, report):
        assert "pinecone" not in report["resume_title"].lower()

    def test_no_rewrite_weaves_in_a_missing_skill(self, report):
        for item in report["improvements"]:
            text = (item.get("suggested_description") or "").lower()
            assert "pinecone" not in text

    def test_a_skill_the_candidate_has_is_still_suggested(self, report):
        """The guard must not be so blunt that it blocks honest advice."""
        assert report["keywords_to_add"] or report["improvements"]


# --------------------------------------------------------------------------
# Output contract
# --------------------------------------------------------------------------


class TestOutputStructure:
    def test_has_every_documented_key(self, report):
        for key in (
            "resume_title",
            "improvements",
            "projects_to_highlight",
            "keywords_to_add",
            "keywords_to_remove",
            "reordering",
            "tailored_summary",
            "confidence",
        ):
            assert key in report

    def test_is_json_serialisable(self, report):
        assert json.loads(json.dumps(report)) == report

    def test_reordering_has_both_directions(self, report):
        assert set(report["reordering"]) == {"move_up", "move_down"}

    def test_confidence_is_a_probability(self, report):
        assert 0.0 <= report["confidence"] <= 1.0

    def test_improvements_declare_a_known_impact(self, report):
        for item in report["improvements"]:
            assert item["impact"] in (HIGH, MEDIUM, LOW)

    def test_every_improvement_explains_itself(self, report):
        for item in report["improvements"]:
            assert item["why"].strip()

    def test_every_improvement_names_its_section(self, report):
        for item in report["improvements"]:
            assert item["section"].strip()

    def test_high_impact_count_matches_the_list(self, report):
        counted = sum(1 for i in report["improvements"] if i["impact"] == HIGH)
        assert report["high_impact_count"] == counted

    def test_suggestions_are_capped(self, report):
        assert len(report["improvements"]) <= resume_optimizer.max_improvements

    def test_source_is_declared(self, report):
        assert report["source"]


class TestCopyPasteable:
    """The spec's real requirement: the user can paste this straight in."""

    def test_rewrites_differ_from_the_original(self, report):
        for item in report["improvements"]:
            if "current_description" in item:
                assert item["suggested_description"] != item["current_description"]

    def test_rewrites_are_complete_sentences(self, report):
        for item in report["improvements"]:
            text = item.get("suggested_description")
            if text:
                assert text[0].isupper() or text[0] == "["
                assert text.rstrip().endswith((".", "]"))

    def test_the_summary_is_a_usable_paragraph(self, report):
        assert len(report["tailored_summary"].split()) >= 12

    def test_the_title_reads_like_a_headline(self, report):
        assert 0 < len(report["resume_title"]) <= 90


# --------------------------------------------------------------------------
# The advice itself
# --------------------------------------------------------------------------


class TestWording:
    def test_weak_verbs_are_upgraded(self, agent):
        result = agent._suggest_wording("Built RAG system with LangChain", [("rag", 3)])
        assert result["changed"]
        assert not result["suggested"].lower().startswith("built")

    def test_strong_verbs_are_left_alone(self, agent):
        original = "Architected a distributed retrieval service"
        result = agent._suggest_wording(original, [])
        assert not result["suggested"].lower().startswith("built")

    def test_a_line_that_already_has_numbers_gets_no_slot(self, agent):
        result = agent._suggest_wording("Cut latency by 40% across 3 services", [])
        assert not result["placeholders"]

    def test_a_reason_is_always_given_when_something_changed(self, agent):
        result = agent._suggest_wording("Used Chroma for vector storage", [("rag", 2)])
        if result["changed"]:
            assert result["reasons"]

    def test_empty_input_is_handled(self, agent):
        assert agent._suggest_wording("", [])["changed"] is False


class TestMetrics:
    def test_counts_quantified_and_unquantified_lines(self, agent):
        result = agent._extract_metrics(
            ["Cut costs by 30%", "Built a thing", "Served 1000 users"]
        )
        assert len(result["quantified"]) == 2
        assert len(result["unquantified"]) == 1
        assert result["total"] == 3

    def test_returns_the_lines_themselves_so_advice_can_quote_them(self, agent):
        result = agent._extract_metrics(["Built a thing"])
        assert result["unquantified"] == ["Built a thing"]

    def test_ratio_is_a_fraction(self, agent):
        result = agent._extract_metrics(["Cut costs by 30%", "Built a thing"])
        assert result["ratio"] == pytest.approx(0.5)

    def test_no_descriptions_does_not_divide_by_zero(self, agent):
        assert agent._extract_metrics([])["ratio"] == 0.0

    def test_percentages_count_as_metrics(self, agent):
        assert agent._extract_metrics(["Improved accuracy by 12%"])["quantified"] == [
            "Improved accuracy by 12%"
        ]

    def test_a_year_alone_is_not_an_achievement_metric(self, agent):
        """"(2022-2023)" is when the job happened, not what it achieved."""
        result = agent._extract_metrics(["Intern - AI Startup (2022-2023)"])
        assert result["quantified"] == []


class TestProjects:
    def test_finds_the_real_project_titles(self, report):
        names = [p["project"] for p in report["projects_to_highlight"]]
        assert "Document Q&A System" in names

    def test_does_not_mistake_a_bullet_for_a_project(self, report):
        """Regression: "- Built with LangChain + RAG" is a detail, not a project."""
        names = [p["project"] for p in report["projects_to_highlight"]]
        assert "Built with LangChain + RAG" not in names
        for name in names:
            assert not name.startswith("-")

    def test_the_most_relevant_project_leads(self, report):
        scores = [p["relevance_score"] for p in report["projects_to_highlight"]]
        assert scores == sorted(scores, reverse=True)

    def test_a_directly_relevant_project_scores_well(self, report):
        """Regression: scoring against every requirement capped everything low."""
        top = report["projects_to_highlight"][0]
        assert top["relevance_score"] >= 50

    def test_scores_stay_in_range(self, report):
        for project in report["projects_to_highlight"]:
            assert 0 <= project["relevance_score"] <= 100

    def test_every_project_says_why_and_what_to_do(self, report):
        for project in report["projects_to_highlight"]:
            assert project["why"].strip()
            assert project["suggestion"].strip()

    def test_a_resume_with_no_projects_is_fine(self):
        result = optimise(resume="SKILLS\nPython\n\nEXPERIENCE\n- Wrote Python")
        assert result["projects_to_highlight"] == []


class TestKeywords:
    def test_a_heavily_repeated_requirement_is_surfaced(self, agent):
        """The JD says RAG four times; that emphasis should be detected."""
        suggestions = agent._generate_keyword_suggestions(JOB)
        counts = dict(suggestions)
        assert counts.get("rag", 0) > 1

    def test_suggestions_are_ordered_by_employer_emphasis(self, agent):
        suggestions = agent._generate_keyword_suggestions(JOB)
        counts = [c for _, c in suggestions]
        assert counts == sorted(counts, reverse=True)

    def test_removal_advice_never_targets_a_required_skill(self, report):
        targets = {k["keyword"].lower() for k in report["keywords_to_remove"]}
        assert not (targets & set(JOB["required_skills"]))

    def test_removal_advice_spares_related_skills(self):
        """Regression: PostgreSQL was suggested for removal by a job wanting SQL."""
        job = dict(JOB, required_skills=["python", "sql"], tech_stack=["python"])
        result = optimise(job=job, gaps=None, match=None)
        targets = {k["keyword"].lower() for k in result["keywords_to_remove"]}
        assert "postgresql" not in targets

    def test_removal_is_framed_as_downplaying_not_deleting(self, report):
        for item in report["keywords_to_remove"]:
            assert "delete" not in item["why"].lower()
            assert item["action"]

    def test_irrelevant_skills_are_flagged_for_a_focused_role(self):
        resume = RESUME + "\nAlso skilled in Excel and WordPress.\n"
        result = optimise(resume=resume)
        targets = {k["keyword"].lower() for k in result["keywords_to_remove"]}
        assert targets  # something clearly off-topic was noticed


class TestReordering:
    def test_weak_material_moves_down(self, report):
        joined = " ".join(report["reordering"]["move_down"]).lower()
        assert "intern" in joined

    def test_does_not_ask_to_move_every_section_up(self, report):
        """Regression: naming four whole sections as "move up" is just noise."""
        sections = {"Skills", "Experience", "Projects", "Achievements", "Education"}
        named = [m for m in report["reordering"]["move_up"] if m in sections]
        assert len(named) <= 2

    def test_does_not_reorder_the_skills_list(self, report):
        assert not any(
            m.startswith("Skills >") for m in report["reordering"]["move_up"]
        )

    def test_entries_are_readable(self, report):
        for entry in report["reordering"]["move_up"] + report["reordering"]["move_down"]:
            assert entry.strip()
            assert len(entry) <= 100


class TestImpactGrading:
    def test_not_everything_is_high_impact(self, report):
        """A grade that is always HIGH carries no information."""
        impacts = {i["impact"] for i in report["improvements"]}
        assert len(impacts) > 1

    def test_the_strongest_suggestions_come_first(self, report):
        order = [i["impact"] for i in report["improvements"]]
        rank = {HIGH: 0, MEDIUM: 1, LOW: 2}
        assert [rank[i] for i in order] == sorted(rank[i] for i in order)

    def test_a_certification_line_is_not_given_a_metric_slot(self, agent):
        """Regression: "AI & ML Fundamentals, delivering [RESULT]." is nonsense."""
        assert agent._wants_metric("AI & ML Fundamentals certification") is False

    def test_a_real_achievement_line_does_want_a_metric(self, agent):
        assert agent._wants_metric("Built a RAG system with LangChain and Chroma")

    def test_a_two_word_line_is_left_alone(self, agent):
        assert agent._wants_metric("Python developer") is False


class TestSummary:
    def test_leads_with_the_advertised_role(self, report):
        assert "engineer" in report["tailored_summary"].lower()

    def test_names_skills_the_candidate_actually_has(self, report):
        assert "langchain" in report["tailored_summary"].lower()

    def test_does_not_repeat_a_skill(self, report):
        """Regression: "Hands-on with FastAPI, FastAPI, Git and LangChain"."""
        words = [
            w.strip(" .,")
            for w in report["tailored_summary"].replace(" and ", ", ").split(",")
        ]
        named = [w.lower() for w in words if w and " " not in w]
        assert len(named) == len(set(named))

    def test_reflects_the_candidates_experience(self, report):
        assert "2" in report["tailored_summary"]


class TestTitle:
    def test_uses_the_advertised_job_title(self, report):
        assert "engineer" in report["resume_title"].lower()

    def test_names_a_skill_the_candidate_has(self, report):
        title = report["resume_title"].lower()
        assert any(skill in title for skill in ("langchain", "rag", "python"))


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_resume_does_not_crash(self):
        result = optimise(resume="")
        assert result["improvements"] == []
        assert result["confidence"] < 0.5

    def test_empty_job_analysis_does_not_crash(self):
        result = resume_optimizer.optimize_resume({"resume_text": RESUME}, {}, None, None)
        assert isinstance(result["improvements"], list)

    def test_works_without_gaps_or_match_data(self):
        result = optimise(gaps=None, match=None)
        assert result["resume_title"]

    def test_missing_gap_data_blocks_nothing_incorrectly(self):
        result = optimise(gaps=None, match=None)
        assert result["keywords_blocked_by_gaps"] == []

    def test_none_inputs_are_tolerated(self):
        result = resume_optimizer.optimize_resume({}, {}, None, None)
        assert result["confidence"] == pytest.approx(0.0, abs=0.5)

    def test_a_resume_with_no_headings_still_produces_advice(self):
        result = optimise(resume="I built RAG systems with LangChain and Python.")
        assert isinstance(result["improvements"], list)

    def test_unicode_survives(self):
        result = optimise(resume=RESUME.replace("Rahul", "Rahül") + "\n— naïve café")
        assert json.dumps(result)

    def test_the_agent_is_stateless_across_runs(self):
        first = optimise()
        second = optimise()
        assert first["improvements"] == second["improvements"]


class TestWorkflowIntegration:
    def test_exposes_a_trace_label(self):
        assert resume_optimizer.label == "Resume Optimizer"

    def test_reports_the_numbers_the_trace_needs(self, report):
        assert isinstance(report["high_impact_count"], int)
        assert isinstance(len(report["improvements"]), int)

    def test_consumes_gap_detector_output_shape(self, report):
        """Guards the contract between the two agents."""
        assert report["keywords_blocked_by_gaps"] == ["Pinecone"]

    def test_consumes_match_calculator_output_shape(self):
        result = optimise(match=MATCH)
        assert result["confidence"] > 0
