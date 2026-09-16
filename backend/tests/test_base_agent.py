"""Tests for BaseAgent and the four concrete agents.

Every test here is offline: the agents are handed a ``StubLLM`` that either
serves scripted JSON or reports itself unavailable.
"""

import json

import pytest

from agents.base_agent import (
    AgentError,
    AgentResult,
    BaseAgent,
    GapAnalysisAgent,
    MatchScoringAgent,
    SkillExtractionAgent,
    _clean_seniority,
    _clean_skill_list,
    _clean_str_list,
    _guess_title,
    build_tools,
)
from agents.ollama_handler import LLMError
from tests.conftest import SAMPLE_RESUME, StubLLM


class EchoAgent(BaseAgent):
    """Tiny agent used to exercise the base class on its own."""

    name = "echo"
    prompt_name = "skill_extraction"
    required_inputs = ("resume_text",)

    def parse(self, payload, **inputs):
        return {"parsed": payload}

    def fallback(self, **inputs):
        return {"parsed": "fallback"}


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------


class TestBaseAgentContract:
    def test_cannot_instantiate_without_a_fallback(self):
        class Incomplete(BaseAgent):
            name = "incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_missing_required_input_is_rejected(self):
        agent = EchoAgent(llm=StubLLM(available=False))
        with pytest.raises(AgentError, match="missing required input"):
            agent.run()

    def test_blank_string_counts_as_missing(self):
        agent = EchoAgent(llm=StubLLM(available=False))
        with pytest.raises(AgentError, match="resume_text"):
            agent.run(resume_text="   ")

    def test_uses_the_llm_when_one_answers(self):
        llm = StubLLM(responses=['{"skills": ["python"]}'])
        result = EchoAgent(llm=llm).run(resume_text="hi")
        assert result.source == "llm"
        assert result.backend == "stub"
        assert result.output == {"parsed": {"skills": ["python"]}}

    def test_falls_back_when_no_llm_is_available(self):
        result = EchoAgent(llm=StubLLM(available=False)).run(resume_text="hi")
        assert result.source == "fallback"
        assert result.warning and "no LLM available" in result.warning

    def test_falls_back_when_the_llm_errors(self):
        llm = StubLLM(error=LLMError("model crashed"))
        result = EchoAgent(llm=llm).run(resume_text="hi")
        assert result.source == "fallback"
        assert "LLM call failed" in result.warning

    def test_falls_back_when_the_reply_is_not_json(self):
        llm = StubLLM(responses=["I'd rather not."])
        result = EchoAgent(llm=llm).run(resume_text="hi")
        assert result.source == "fallback"
        assert "failed" in result.warning

    def test_use_llm_false_skips_the_model_entirely(self):
        llm = StubLLM(responses=['{"skills": ["python"]}'])
        result = EchoAgent(llm=llm, use_llm=False).run(resume_text="hi")
        assert result.source == "fallback"
        assert llm.prompts == []

    def test_a_broken_fallback_raises_agent_error(self):
        class Broken(BaseAgent):
            name = "broken"
            required_inputs = ("x",)

            def fallback(self, **inputs):
                raise ValueError("nope")

        with pytest.raises(AgentError, match="fallback failed"):
            Broken(llm=StubLLM(available=False)).run(x="1")

    def test_prompt_is_rendered_with_the_input(self):
        llm = StubLLM(responses=['{"skills": []}'])
        EchoAgent(llm=llm).run(resume_text="UNIQUE-MARKER")
        assert "UNIQUE-MARKER" in llm.prompts[0]

    def test_result_timing_is_recorded(self):
        result = EchoAgent(llm=StubLLM(available=False)).run(resume_text="hi")
        assert result.duration_ms >= 0.0

    def test_result_serialises(self):
        payload = AgentResult(agent="x", output={"a": 1}).as_dict()
        assert payload["agent"] == "x"
        assert payload["output"] == {"a": 1}
        assert json.dumps(payload)  # must be JSON-safe for the API layer

    def test_agent_without_a_prompt_cannot_build_one(self):
        agent = MatchScoringAgent(llm=StubLLM(available=False))
        with pytest.raises(AgentError, match="no prompt template"):
            agent.build_prompt(resume_text="hi")

    def test_as_tool_exposes_name_and_description(self):
        tool = SkillExtractionAgent(llm=StubLLM(available=False)).as_tool()
        assert tool.name == "extract_skills"
        assert "skills" in tool.description.lower()

    def test_build_tools_returns_one_per_agent(self):
        tools = build_tools(llm=StubLLM(available=False))
        assert [t.name for t in tools] == [
            "analyze_job",
            "extract_skills",
            "detect_gaps",
            "calculate_match",
        ]


# ---------------------------------------------------------------------------
# SkillExtractionAgent
# ---------------------------------------------------------------------------


class TestSkillExtractionAgent:
    def test_fallback_finds_skills_in_the_resume(self):
        agent = SkillExtractionAgent(llm=StubLLM(available=False))
        skills = agent.run(resume_text=SAMPLE_RESUME).output["skills"]
        assert {"python", "fastapi", "docker"} <= set(skills)

    def test_llm_skills_are_lowercased_and_deduplicated(self):
        llm = StubLLM(responses=[json.dumps({"skills": ["Python", "python", "Go"]})])
        skills = SkillExtractionAgent(llm=llm).run(resume_text="x").output["skills"]
        assert skills == ["python", "go"]

    def test_an_empty_llm_list_triggers_the_fallback(self):
        llm = StubLLM(responses=[json.dumps({"skills": []})])
        result = SkillExtractionAgent(llm=llm).run(resume_text=SAMPLE_RESUME)
        assert result.source == "fallback"
        assert "python" in result.output["skills"]


# ---------------------------------------------------------------------------
# GapAnalysisAgent
# ---------------------------------------------------------------------------


class TestGapAnalysisAgent:
    def test_fallback_subtracts_candidate_skills_from_required(self):
        agent = GapAnalysisAgent(llm=StubLLM(available=False))
        output = agent.run(
            candidate_skills=["python", "docker"],
            required_skills=["python", "kubernetes", "aws"],
            preferred_skills=["terraform"],
        ).output
        assert output["gaps"] == ["kubernetes", "aws"]
        assert output["strengths"] == ["python"]
        assert output["preferred_gaps"] == ["terraform"]

    def test_no_gaps_gives_a_positive_explanation(self):
        agent = GapAnalysisAgent(llm=StubLLM(available=False))
        output = agent.run(
            candidate_skills=["python"], required_skills=["python"]
        ).output
        assert output["gaps"] == []
        assert "Every required skill" in output["explanation"]

    def test_a_job_with_no_requirements_is_explained(self):
        agent = GapAnalysisAgent(llm=StubLLM(available=False))
        output = agent.run(candidate_skills=["python"], required_skills=[]).output
        assert "did not name any required skills" in output["explanation"]

    def test_llm_cannot_invent_a_gap_the_candidate_has(self):
        llm = StubLLM(
            responses=[json.dumps({"gaps": ["python", "aws"], "strengths": []})]
        )
        output = GapAnalysisAgent(llm=llm).run(
            candidate_skills=["python"], required_skills=["python", "aws"]
        ).output
        assert output["gaps"] == ["aws"]

    def test_prompt_lists_the_skills(self):
        llm = StubLLM(responses=[json.dumps({"gaps": []})])
        GapAnalysisAgent(llm=llm).run(
            candidate_skills=["python"], required_skills=["kubernetes"]
        )
        assert "python" in llm.prompts[0]
        assert "kubernetes" in llm.prompts[0]

    def test_empty_skill_lists_render_as_none_listed(self):
        agent = GapAnalysisAgent(llm=StubLLM(available=False))
        values = agent.prompt_values(candidate_skills=[], required_skills=[])
        assert values["candidate_skills"] == "none listed"


# ---------------------------------------------------------------------------
# MatchScoringAgent
# ---------------------------------------------------------------------------


class TestMatchScoringAgent:
    def test_never_calls_the_llm(self):
        llm = StubLLM(responses=['{"score": 99}'])
        result = MatchScoringAgent(llm=llm).run(
            resume_text=SAMPLE_RESUME, required_skills=["python"]
        )
        assert llm.prompts == []
        assert result.source == "fallback"

    def test_perfect_match_scores_100(self):
        output = MatchScoringAgent(llm=StubLLM(available=False)).run(
            resume_text="python docker",
            required_skills=["python", "docker"],
        ).output
        assert output["overall_match"] == 100.0
        assert output["recommendation"] == "APPLY"

    def test_missing_everything_scores_zero(self):
        output = MatchScoringAgent(llm=StubLLM(available=False)).run(
            resume_text="I like painting",
            required_skills=["python", "docker"],
        ).output
        assert output["overall_match"] == 0.0
        assert set(output["missing_skills"]) == {"python", "docker"}
        assert output["recommendation"] == "SKIP"

    def test_score_is_reproducible(self):
        agent = MatchScoringAgent(llm=StubLLM(available=False))
        kwargs = {"resume_text": SAMPLE_RESUME, "required_skills": ["python", "aws"]}
        first = agent.run(**kwargs).output["overall_match"]
        assert first == agent.run(**kwargs).output["overall_match"]

    def test_accepts_a_full_job_analysis(self):
        output = MatchScoringAgent(llm=StubLLM(available=False)).run(
            resume_text=SAMPLE_RESUME,
            job_analysis={
                "title": "Backend Engineer",
                "required_skills": ["python", "docker"],
                "experience_years": 3,
            },
        ).output
        assert output["job_title"] == "Backend Engineer"
        assert output["match_breakdown"]["experience"]["applicable"] is True

    def test_reuses_already_extracted_skills(self):
        # The graph passes skills_found so the scorer agrees with the gap node.
        output = MatchScoringAgent(llm=StubLLM(available=False)).run(
            resume_text="unrelated prose",
            skills_found=["python", "docker"],
            required_skills=["python", "docker"],
        ).output
        assert output["overall_match"] == 100.0

    def test_trace_fields(self):
        agent = MatchScoringAgent(llm=StubLLM(available=False))
        output = agent.run(
            resume_text="python", required_skills=["python"]
        ).output
        assert agent.trace_fields(output) == {
            "label": "Match Calculator",
            "overall_score": 100.0,
            "recommendation": "APPLY",
        }

    def test_recommendations_are_produced(self):
        output = MatchScoringAgent(llm=StubLLM(available=False)).run(
            resume_text="python", required_skills=["python", "rust"]
        ).output
        assert output["recommendations"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize("value,expected", [(None, []), ("solo", ["solo"]), (42, [])])
    def test_clean_str_list_coerces_odd_shapes(self, value, expected):
        assert _clean_str_list(value) == expected

    def test_clean_str_list_deduplicates_case_insensitively(self):
        assert _clean_str_list(["Go", "go", " GO "]) == ["Go"]

    def test_clean_str_list_drops_blanks(self):
        assert _clean_str_list(["a", "", "   "]) == ["a"]

    def test_clean_skill_list_lowercases(self):
        assert _clean_skill_list(["Python", "AWS"]) == ["python", "aws"]

    @pytest.mark.parametrize("value", ["senior", "SENIOR", " Mid "])
    def test_valid_seniority_is_normalised(self, value):
        assert _clean_seniority(value) == value.strip().lower()

    @pytest.mark.parametrize("value", [None, "", "principal", 7])
    def test_invalid_seniority_is_dropped(self, value):
        assert _clean_seniority(value) is None

    def test_guess_title_takes_the_first_real_line(self):
        assert _guess_title("\n\n  Backend Engineer  \nRequired: Python") == "Backend Engineer"

    def test_guess_title_on_empty_text(self):
        assert _guess_title("   \n  ") == "Unknown role"

    def test_guess_title_is_truncated(self):
        assert len(_guess_title("x" * 500)) == 120
