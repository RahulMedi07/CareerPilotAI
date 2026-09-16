"""Tests for the resume profiler.

The theme running through these is the one rule the rest of the codebase is
built on: a fact the resume does not state must come back absent, not zero and
not guessed. A CV that never says how long someone has worked is not a CV
belonging to someone with no experience.
"""

from __future__ import annotations

import json

import pytest

from agents.resume_profiler import (
    ResumeProfilerAgent,
    _has_phone,
    group_skills,
    infer_role,
    seniority_from,
)
from tests.conftest import StubLLM

BACKEND_CV = """Rahul Medi
rahul@example.com | +91 98765 43210

SUMMARY
Backend engineer with 4 years of experience.

SKILLS
Python, FastAPI, PostgreSQL, Docker, REST, Git

PROJECTS
Built an order service; cut p99 latency by 40%.

EDUCATION
B.Tech Computer Science
"""

THIN_CV = "Rahul Medi. I am a hard worker and a good team player."


@pytest.fixture
def agent():
    """Offline by default, which is the state the fallback path exists for."""
    return ResumeProfilerAgent(llm=StubLLM(available=False))


class TestRoleInference:
    def test_a_backend_skill_set_is_called_backend(self):
        role, _titles, queries = infer_role(
            ["python", "fastapi", "postgresql", "rest"]
        )
        assert role == "backend developer"
        assert queries

    def test_an_ml_skill_set_is_called_ml(self):
        role, _titles, _queries = infer_role(
            ["pytorch", "langchain", "rag", "embeddings"]
        )
        assert role == "ai/ml engineer"

    def test_both_halves_of_the_stack_is_fullstack_not_whichever_list_is_longer(self):
        """The backend signal list is more than twice the frontend one.

        Picking the highest raw count would therefore call every React
        developer who has touched Python a backend engineer.
        """
        role, _titles, _queries = infer_role(
            ["python", "fastapi", "react", "typescript"]
        )
        assert role == "fullstack developer"

    def test_one_shared_keyword_is_not_a_career(self):
        assert infer_role(["python"])[0] == "unknown"

    def test_no_skills_means_no_role(self):
        role, titles, queries = infer_role([])
        assert role == "unknown"
        assert titles == []
        assert queries == []


class TestSeniority:
    @pytest.mark.parametrize(
        "years,expected",
        [(0.5, "junior"), (3, "mid"), (6, "senior"), (9, "staff"), (12, "lead")],
    )
    def test_a_stated_number_sets_the_band(self, years, expected):
        assert seniority_from(years, "") == expected

    def test_a_stated_word_is_used_when_there_is_no_number(self):
        assert seniority_from(None, "Senior Software Engineer") == "senior"

    def test_neither_is_unknown_rather_than_a_guess(self):
        assert seniority_from(None, "Software Engineer at Acme") == "unknown"

    def test_a_number_beats_a_word(self):
        """The word is often a past job title; the number is a claim about now."""
        assert seniority_from(1.0, "Senior Engineer") == "junior"


class TestSkillGroups:
    def test_skills_are_bucketed(self):
        grouped = group_skills(["python", "docker", "react"])
        assert grouped["Languages"] == ["python"]
        assert grouped["Infrastructure"] == ["docker"]

    def test_empty_groups_are_dropped_rather_than_rendered_blank(self):
        grouped = group_skills(["python"])
        assert list(grouped) == ["Languages"]

    def test_nothing_in_nothing_out(self):
        assert group_skills([]) == {}


class TestPhoneDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "+91 98765 43210",  # India writes mobiles as 5+5
            "+1 (555) 123-4567",
            "020 7946 0018",
            "9876543210",
        ],
    )
    def test_real_numbers_are_found(self, text):
        assert _has_phone(text) is True

    @pytest.mark.parametrize("text", ["2021-2024", "B.Tech 2019", "no number"])
    def test_dates_are_not_phone_numbers(self, text):
        assert _has_phone(text) is False


class TestFallback:
    def test_it_describes_a_real_resume(self, agent):
        out = agent.run(resume_text=BACKEND_CV).output
        assert out["primary_role"] == "backend developer"
        assert out["experience_years"] == 4.0
        assert "python" in out["skills"]
        assert out["search_queries"]

    def test_unstated_years_come_back_as_none_not_zero(self, agent):
        """The whole point. Zero would be a claim; None is the truth."""
        cv = BACKEND_CV.replace("with 4 years of experience", "who ships")
        out = agent.run(resume_text=cv).output
        assert out["experience_years"] is None
        assert out["experience_years"] != 0

    def test_a_thin_resume_is_reported_as_thin(self, agent):
        out = agent.run(resume_text=THIN_CV).output
        assert out["skills"] == []
        assert out["primary_role"] == "unknown"
        assert out["suggested_roles"] == []
        assert "does not name a single technology" in out["headline"]

    def test_it_never_invents_a_headline_number(self, agent):
        out = agent.run(resume_text=THIN_CV).output
        assert "0 years" not in out["headline"]

    def test_missing_contact_details_are_reported(self, agent):
        out = agent.run(resume_text="Python FastAPI Docker REST PostgreSQL").output
        assert any("email" in note.lower() for note in out["improvements"])

    def test_a_complete_resume_has_nothing_to_complain_about(self, agent):
        out = agent.run(resume_text=BACKEND_CV).output
        assert out["improvements"] == []

    def test_a_resume_without_numbers_is_told_to_add_some(self, agent):
        cv = BACKEND_CV.replace("cut p99 latency by 40%", "improved performance")
        out = agent.run(resume_text=cv).output
        assert any("number" in note.lower() for note in out["improvements"])

    def test_the_source_says_a_rule_wrote_it(self, agent):
        assert agent.run(resume_text=BACKEND_CV).source == "fallback"

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("B.Tech in Computer Science, 2021", "bachelors"),
            ("Master of Science in Data Science", "masters"),
            ("PhD in Machine Learning", "phd"),
        ],
    )
    def test_education_is_reported(self, agent, line, expected):
        """The brief asks for education, so it has to leave the profiler."""
        out = agent.run(resume_text="%s\n%s" % (BACKEND_CV, line)).output
        assert out["education"] == expected

    def test_an_unstated_qualification_is_none_not_a_guess(self, agent):
        """Same rule as years: absent is not the same as none held."""
        out = agent.run(resume_text=THIN_CV).output
        assert out["education"] is None


class TestLLMPath:
    def _agent(self, payload):
        return ResumeProfilerAgent(llm=StubLLM([json.dumps(payload)]))

    def test_a_model_answer_is_used(self):
        agent = self._agent({
            "headline": "A backend engineer who ships.",
            "primary_role": "backend developer",
            "seniority": "mid",
            "experience_years": 4,
            "skills": ["python", "fastapi"],
            "strengths": ["Ships things"],
            "improvements": ["Add metrics"],
            "suggested_roles": ["backend developer"],
            "search_queries": ["python backend developer"],
        })
        result = agent.run(resume_text=BACKEND_CV)
        assert result.source == "llm"
        assert result.output["headline"] == "A backend engineer who ships."

    def test_a_skill_the_resume_does_not_evidence_is_dropped(self):
        """A fabricated skill is worse than a missing one.

        The candidate is the person who has to answer for it in the room.
        """
        agent = self._agent({
            "headline": "h",
            "primary_role": "backend developer",
            "seniority": "mid",
            "experience_years": 4,
            "skills": ["python", "kubernetes"],  # kubernetes is not in the CV
            "strengths": [],
            "improvements": [],
            "suggested_roles": [],
            "search_queries": [],
        })
        out = agent.run(resume_text=BACKEND_CV).output
        assert "python" in out["skills"]
        assert "kubernetes" not in out["skills"]

    def test_a_null_year_from_the_model_stays_null(self):
        agent = self._agent({
            "headline": "h",
            "primary_role": "backend developer",
            "seniority": "unknown",
            "experience_years": None,
            "skills": ["python"],
            "strengths": [],
            "improvements": [],
            "suggested_roles": [],
            "search_queries": [],
        })
        assert agent.run(resume_text=BACKEND_CV).output["experience_years"] is None

    def test_an_unusable_year_is_dropped_rather_than_defaulted(self):
        agent = self._agent({
            "headline": "h",
            "primary_role": "backend developer",
            "seniority": "mid",
            "experience_years": "about four",
            "skills": ["python"],
            "strengths": [],
            "improvements": [],
            "suggested_roles": [],
            "search_queries": [],
        })
        assert agent.run(resume_text=BACKEND_CV).output["experience_years"] is None

    def test_a_nonsense_seniority_is_recomputed(self):
        agent = self._agent({
            "headline": "h",
            "primary_role": "backend developer",
            "seniority": "rockstar",
            "experience_years": 4,
            "skills": ["python"],
            "strengths": [],
            "improvements": [],
            "suggested_roles": [],
            "search_queries": [],
        })
        assert agent.run(resume_text=BACKEND_CV).output["seniority"] == "mid"

    def test_missing_queries_fall_back_to_derived_ones(self):
        agent = self._agent({
            "headline": "h",
            "primary_role": "backend developer",
            "seniority": "mid",
            "experience_years": 4,
            "skills": ["python", "fastapi", "rest", "postgresql"],
            "strengths": [],
            "improvements": [],
            "suggested_roles": [],
            "search_queries": [],
        })
        out = agent.run(resume_text=BACKEND_CV).output
        assert out["search_queries"]

    def test_a_broken_model_reply_falls_back(self):
        agent = ResumeProfilerAgent(llm=StubLLM(["not json at all"]))
        result = agent.run(resume_text=BACKEND_CV)
        assert result.source == "fallback"
        assert result.output["primary_role"] == "backend developer"
