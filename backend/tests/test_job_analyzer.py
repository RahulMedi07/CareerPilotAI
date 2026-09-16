"""Tests for agents.job_analyzer."""

import json

import pytest

from agents.job_analyzer import (
    EmptyJobDescriptionError,
    JobAnalyzer,
    JobAnalyzerAgent,
    MalformedJobDescriptionError,
    _coerce_years,
    _clean_role,
    _detect_seniority,
    _extract_responsibilities,
    _find_skills,
    _split_sections,
    detect_company_size,
    detect_role_type,
    experience_level,
    extract_education,
    extract_experience_years,
    job_analyzer,
    score_confidence,
    validate_description,
)
from models.career_models import JobDescription
from tests.conftest import StubLLM


class TestFindSkills:
    def test_finds_known_skills_case_insensitively(self):
        assert _find_skills("We use PYTHON and Docker") == ["docker", "python"]

    def test_returns_sorted_unique_results(self):
        found = _find_skills("aws aws python docker python")
        assert found == sorted(found)
        assert len(found) == len(set(found))

    def test_no_skills_returns_empty_list(self):
        assert _find_skills("We are looking for a friendly teammate.") == []

    def test_empty_text(self):
        assert _find_skills("") == []


class TestDetectSeniority:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Senior Backend Engineer", "senior"),
            ("Software Engineering Intern", "intern"),
            ("Junior Developer", "junior"),
            ("Entry-level analyst", "junior"),
            ("Staff Engineer", "staff"),
            ("Engineering Manager", "lead"),
            ("Mid-level Engineer", "mid"),
        ],
    )
    def test_detects_levels(self, text, expected):
        assert _detect_seniority(text) == expected

    def test_returns_none_when_unknown(self):
        assert _detect_seniority("Software Engineer") is None


class TestSplitSections:
    def test_splits_on_preferred_marker(self):
        required, preferred = _split_sections("Required: Python\nPreferred: AWS")
        assert "Python" in required
        assert "AWS" in preferred

    @pytest.mark.parametrize("marker", ["Preferred", "Nice to have", "Bonus", "Plus:"])
    def test_recognises_each_marker(self, marker):
        required, preferred = _split_sections(f"Required: Python\n{marker} Docker")
        assert "Docker" in preferred
        assert "Docker" not in required

    def test_no_marker_puts_everything_in_required(self):
        required, preferred = _split_sections("Required: Python and Docker")
        assert "Docker" in required
        assert preferred == ""


class TestExtractResponsibilities:
    def test_strips_bullet_characters(self):
        text = "- Build and maintain data pipelines\n* Own the deployment process"
        lines = _extract_responsibilities(text)
        assert lines[0].startswith("Build")
        assert lines[1].startswith("Own")

    def test_drops_short_lines(self):
        assert _extract_responsibilities("Hi\nBye\n") == []

    def test_caps_at_fifteen_entries(self):
        text = "\n".join(f"Responsibility number {i} for this particular role" for i in range(40))
        assert len(_extract_responsibilities(text)) == 15


class TestJobAnalyzerAnalyze:
    def test_separates_required_and_preferred(self, sample_job):
        analysis = job_analyzer.analyze(sample_job)
        required = {s.name for s in analysis.required_skills}
        preferred = {s.name for s in analysis.preferred_skills}

        assert {"python", "fastapi", "langchain", "docker"} <= required
        assert {"aws", "kubernetes"} <= preferred

    def test_preferred_never_duplicates_required(self):
        job = JobDescription(
            title="Engineer",
            description="Required: Python and Docker.\nPreferred: Python, Docker and AWS.",
        )
        analysis = JobAnalyzer().analyze(job)
        required = {s.name for s in analysis.required_skills}
        preferred = {s.name for s in analysis.preferred_skills}
        assert required.isdisjoint(preferred)

    def test_keywords_are_sorted_and_deduplicated(self, sample_job):
        analysis = job_analyzer.analyze(sample_job)
        assert analysis.keywords == sorted(set(analysis.keywords))

    def test_carries_over_title_and_company(self, sample_job):
        analysis = job_analyzer.analyze(sample_job)
        assert analysis.title == "Senior AI Engineer"
        assert analysis.company == "Acme"
        assert analysis.seniority == "senior"

    def test_description_without_skills(self):
        job = JobDescription(title="Barista", description="Make excellent coffee for our guests.")
        analysis = JobAnalyzer().analyze(job)
        assert analysis.required_skills == []
        assert analysis.preferred_skills == []
        assert analysis.keywords == []

    def test_empty_description_is_rejected(self):
        with pytest.raises(ValueError):
            JobDescription(title="Engineer", description="")


# ---------------------------------------------------------------------------
# Extractors used by JobAnalyzerAgent
# ---------------------------------------------------------------------------

FULL_JD = """Senior AI Engineer — Series B startup

We need a Senior AI Engineer with 5+ years of experience building production
systems, and at least 2 years working with LLMs.

Required: Python, LangChain, RAG, FastAPI, Docker, PostgreSQL
Preferred: Kubernetes, AWS, Terraform

You will design distributed services and mentor junior engineers. Strong
communication skills and a proactive, detail-oriented approach are essential.
Bachelors degree in Computer Science or equivalent experience.
"""


class TestExtractExperienceYears:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("5+ years of experience", 5),
            ("at least 3 years", 3),
            ("minimum of 7 years in the field", 7),
            ("2 years", 2),
            ("five years of experience", 5),
            ("ten years", 10),
        ],
    )
    def test_reads_a_single_figure(self, text, expected):
        assert extract_experience_years(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [("3-5 years", 3), ("3 to 5 years", 3), ("2–4 years", 2), ("4-6+ years", 4)],
    )
    def test_range_uses_the_lower_bound(self, text, expected):
        assert extract_experience_years(text) == expected

    def test_takes_the_highest_overall_requirement(self):
        # The role's bar is 7; the 2 is a per-technology aside.
        assert extract_experience_years("7+ years overall, 2+ years with Kubernetes") == 7

    def test_range_is_not_double_counted(self):
        # "3-5 years" must not also register as a bare "5 years".
        assert extract_experience_years("3-5 years of Python") == 3

    @pytest.mark.parametrize("text", ["", "no numbers here", "0 years", "99 years"])
    def test_returns_zero_when_absent_or_implausible(self, text):
        assert extract_experience_years(text) == 0


class TestExperienceLevel:
    @pytest.mark.parametrize(
        "years,expected",
        [(1, "junior"), (3, "mid"), (5, "senior"), (7, "senior"), (10, "lead")],
    )
    def test_bands(self, years, expected):
        assert experience_level(years) == expected

    def test_falls_back_to_seniority_when_no_years_given(self):
        assert experience_level(0, "staff") == "staff"

    def test_reports_not_specified_with_nothing_to_go_on(self):
        assert experience_level(0) == "not specified"


class TestExtractEducation:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("PhD in Machine Learning", "phd"),
            ("Master's degree required", "masters"),
            ("MSc preferred", "masters"),
            ("Bachelors in CS", "bachelors"),
            ("BSc required", "bachelors"),
            ("Completed a bootcamp", "bootcamp"),
        ],
    )
    def test_recognises_qualifications(self, text, expected):
        assert extract_education(text) == expected

    def test_highest_requirement_wins(self):
        assert extract_education("Bachelors required, Masters a plus") == "masters"

    def test_notes_the_equivalent_experience_escape_hatch(self):
        result = extract_education("Bachelors degree or equivalent experience")
        assert result == "bachelors (or equivalent experience)"

    def test_degree_explicitly_not_required(self):
        assert extract_education("A degree not required for this role") == "not required"

    @pytest.mark.parametrize("text", ["", "Build great software"])
    def test_absent(self, text):
        assert extract_education(text) == "not specified"


class TestDetectRoleType:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Backend Engineer building microservices", "backend"),
            ("Frontend Engineer working in React and CSS", "frontend"),
            ("Full-stack developer", "fullstack"),
            ("Machine learning engineer working on LLM and RAG systems", "ai/ml"),
            ("Data Engineer building ETL and a data warehouse", "data"),
            ("DevOps / SRE for our platform", "devops"),
            ("iOS developer using react native", "mobile"),
            ("Security engineer doing penetration testing", "security"),
            ("QA engineer owning test automation", "qa"),
        ],
    )
    def test_classifies(self, text, expected):
        assert detect_role_type(text) == expected

    def test_scored_not_first_match(self):
        text = "React is used somewhere. Backend, back-end, microservices, distributed systems, api engineer."
        assert detect_role_type(text) == "backend"

    def test_balanced_front_and_back_reads_as_fullstack(self):
        assert detect_role_type("Frontend and backend work") == "fullstack"

    @pytest.mark.parametrize("text", ["", "We sell excellent coffee"])
    def test_unclassifiable(self, text):
        assert detect_role_type(text) == "general"


class TestDetectCompanySize:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Join our early stage startup", "startup"),
            ("Series A rocket ship", "startup"),
            ("We are a fast scale-up", "scaleup"),
            ("Series C and growing", "scaleup"),
            ("A Fortune 500 enterprise", "enterprise"),
            ("A multinational organisation", "enterprise"),
            ("", "unknown"),
            ("We build software", "unknown"),
        ],
    )
    def test_indicators(self, text, expected):
        assert detect_company_size(text) == expected


class TestValidateDescription:
    def test_accepts_normal_prose(self):
        assert validate_description("  " + FULL_JD + "  ").startswith("Senior")

    @pytest.mark.parametrize("value", ["", "   ", "\n\t", None, 42, []])
    def test_empty_input_rejected(self, value):
        with pytest.raises(EmptyJobDescriptionError):
            validate_description(value)

    def test_too_short_rejected(self):
        with pytest.raises(MalformedJobDescriptionError, match="too short"):
            validate_description("Python dev")

    def test_binary_junk_rejected(self):
        with pytest.raises(MalformedJobDescriptionError, match="readable text"):
            validate_description("\x00\x01\x02 %%%% ###### @@@@@ ^^^^^ &&&&& ***** !!!!!")

    def test_punctuation_heavy_but_real_text_accepted(self):
        text = "Required: Python, Docker, K8s. Preferred: AWS (a plus!), Go."
        assert validate_description(text) == text


class TestScoreConfidence:
    def test_rich_analysis_scores_high(self):
        analysis = {
            "required_skills": ["python", "docker", "aws", "go", "sql"],
            "tech_stack": ["python"],
            "experience_years": 5,
            "seniority": "senior",
            "role_type": "backend",
            "education": "bachelors",
            "soft_skills": ["communication"],
        }
        assert score_confidence(analysis, source="llm") == 1.0

    def test_empty_analysis_scores_zero(self):
        assert score_confidence({}, source="llm") == 0.0

    def test_keyword_path_is_discounted(self):
        analysis = {"required_skills": ["python", "docker", "aws", "go", "sql"]}
        assert score_confidence(analysis, "fallback") < score_confidence(analysis, "llm")

    def test_more_skills_scores_higher(self):
        few = {"required_skills": ["python"]}
        many = {"required_skills": ["python", "go", "sql", "aws", "docker"]}
        assert score_confidence(many) > score_confidence(few)

    def test_unknown_seniority_earns_nothing(self):
        assert score_confidence({"seniority": "unknown"}) == 0.0

    def test_general_role_type_earns_nothing(self):
        assert score_confidence({"role_type": "general"}) == 0.0

    def test_always_within_bounds(self):
        assert 0.0 <= score_confidence({"required_skills": ["x"] * 50}) <= 1.0


# ---------------------------------------------------------------------------
# JobAnalyzerAgent
# ---------------------------------------------------------------------------


@pytest.fixture
def agent():
    """The agent with no model available, so the keyword path runs."""
    return JobAnalyzerAgent(llm=StubLLM(available=False))


class TestJobAnalyzerAgentFallback:
    def test_returns_every_documented_key(self, agent):
        output = agent.analyze(FULL_JD)
        for key in (
            "required_skills", "tech_stack", "experience_years", "soft_skills",
            "education", "role_type", "seniority", "confidence",
        ):
            assert key in output, key

    def test_extracts_the_hard_skills(self, agent):
        skills = agent.analyze(FULL_JD)["required_skills"]
        assert {"python", "langchain", "rag", "fastapi", "docker"} <= set(skills)

    def test_tech_stack_excludes_concepts(self, agent):
        output = agent.analyze(FULL_JD)
        assert "rag" in output["required_skills"]
        assert "rag" not in output["tech_stack"]
        assert "python" in output["tech_stack"]

    def test_reads_years_of_experience(self, agent):
        assert agent.analyze(FULL_JD)["experience_years"] == 5

    def test_seniority_is_not_confused_by_mentoring_juniors(self, agent):
        # "mentor junior engineers" must not turn a senior role junior.
        assert agent.analyze(FULL_JD)["seniority"] == "senior"

    def test_extracts_soft_skills(self, agent):
        soft = agent.analyze(FULL_JD)["soft_skills"]
        assert {"communication", "mentoring"} <= set(soft)

    def test_extracts_education(self, agent):
        assert agent.analyze(FULL_JD)["education"] == "bachelors (or equivalent experience)"

    def test_classifies_the_role(self, agent):
        assert agent.analyze(FULL_JD)["role_type"] == "ai/ml"

    def test_detects_company_size(self, agent):
        assert agent.analyze(FULL_JD)["company_size"] == "startup"

    def test_separates_preferred_skills(self, agent):
        output = agent.analyze(FULL_JD)
        assert {"kubernetes", "aws", "terraform"} <= set(output["preferred_skills"])
        assert set(output["required_skills"]).isdisjoint(output["preferred_skills"])

    def test_confidence_is_a_fraction(self, agent):
        assert 0.0 <= agent.analyze(FULL_JD)["confidence"] <= 1.0

    def test_reports_which_path_ran(self, agent):
        assert agent.analyze(FULL_JD)["source"] == "fallback"

    def test_a_terse_advert_scores_lower_confidence(self, agent):
        rich = agent.analyze(FULL_JD)["confidence"]
        terse = agent.analyze("We need somebody who knows Python quite well.")["confidence"]
        assert terse < rich

    def test_output_is_json_serialisable(self, agent):
        assert json.dumps(agent.analyze(FULL_JD))


class TestJobAnalyzerAgentErrors:
    def test_empty_description_raises(self, agent):
        with pytest.raises(EmptyJobDescriptionError):
            agent.analyze("")

    def test_whitespace_only_raises(self, agent):
        with pytest.raises(EmptyJobDescriptionError):
            agent.analyze("   \n\t  ")

    def test_malformed_text_raises(self, agent):
        with pytest.raises(MalformedJobDescriptionError):
            agent.analyze("\x00\x01 %%%%% ###### @@@@@@ ^^^^^^ &&&&&& ****** !!!!!!")

    def test_an_llm_timeout_degrades_instead_of_raising(self):
        from agents.ollama_handler import LLMError

        agent = JobAnalyzerAgent(llm=StubLLM(error=LLMError("timed out after 120s")))
        output = agent.analyze(FULL_JD)
        assert output["source"] == "fallback"
        assert "timed out" in output["warning"]
        assert output["required_skills"]


class TestJobAnalyzerAgentWithLLM:
    def _reply(self, **overrides):
        payload = {
            "title": "Staff AI Engineer",
            "required_skills": ["Python", "LangChain"],
            "preferred_skills": ["Terraform"],
            "tech_stack": ["Python"],
            "experience_years": 8,
            "soft_skills": ["Communication"],
            "education": "masters",
            "role_type": "ai/ml",
            "seniority": "staff",
        }
        payload.update(overrides)
        return StubLLM(responses=[json.dumps(payload)])

    def test_uses_the_model_when_available(self):
        output = JobAnalyzerAgent(llm=self._reply()).analyze(FULL_JD)
        assert output["source"] == "llm"
        assert output["title"] == "Staff AI Engineer"

    def test_normalises_case(self):
        output = JobAnalyzerAgent(llm=self._reply()).analyze(FULL_JD)
        assert output["required_skills"] == ["python", "langchain"]
        assert output["soft_skills"] == ["communication"]

    def test_maps_years_to_a_level(self):
        output = JobAnalyzerAgent(llm=self._reply()).analyze(FULL_JD)
        assert output["experience_years"] == 8
        assert output["experience_level"] == "lead"

    def test_a_skill_is_never_both_required_and_preferred(self):
        llm = self._reply(required_skills=["python"], preferred_skills=["python", "go"])
        assert JobAnalyzerAgent(llm=llm).analyze(FULL_JD)["preferred_skills"] == ["go"]

    def test_missing_fields_are_recovered_from_the_text(self):
        llm = self._reply(experience_years=None, education="", role_type="nonsense",
                          seniority="wizard", tech_stack=[], soft_skills=[])
        output = JobAnalyzerAgent(llm=llm).analyze(FULL_JD)
        assert output["experience_years"] == 5           # read from the advert
        assert output["education"].startswith("bachelors")
        assert output["role_type"] == "ai/ml"
        assert output["seniority"] == "senior"
        assert output["tech_stack"]
        assert output["soft_skills"]

    def test_a_reply_with_no_skills_falls_back(self):
        llm = self._reply(required_skills=[])
        output = JobAnalyzerAgent(llm=llm).analyze(FULL_JD)
        assert output["source"] == "fallback"
        assert output["required_skills"]

    def test_a_reply_naming_only_a_role_falls_back(self):
        """Observed live, against a real advert.

        Asked to read "Backend Engineer. Python, FastAPI, Kubernetes and
        PostgreSQL required", the model replied with one required skill:
        "backend engineering". That is not empty, so the emptiness check let
        it through, and everything downstream works by intersecting the
        advert's skills with the resume's -- so the interview-prep page
        offered zero technical questions for an advert naming four
        technologies the candidate had three of.

        A reply containing no recognisable technology is a mis-read, not a
        job with no requirements.
        """
        llm = self._reply(required_skills=["backend engineering", "communication"])
        output = JobAnalyzerAgent(llm=llm).analyze(FULL_JD)
        assert output["source"] == "fallback"
        # The rules-based extractor reads this advert perfectly well.
        assert "python" in output["required_skills"]

    def test_one_real_technology_among_the_noise_is_enough_to_keep_the_reply(self):
        # The guard is against a reply that found nothing usable, not against
        # a reply that also mentions soft skills.
        llm = self._reply(required_skills=["communication", "python"])
        output = JobAnalyzerAgent(llm=llm).analyze(FULL_JD)
        assert output["source"] == "llm"

    def test_llm_path_is_more_confident_than_keywords(self):
        # Same findings either way, so only the source discount differs.
        keywords = JobAnalyzerAgent(llm=StubLLM(available=False)).analyze(FULL_JD)
        llm = self._reply(
            required_skills=keywords["required_skills"],
            tech_stack=keywords["tech_stack"],
            soft_skills=keywords["soft_skills"],
        )
        assert JobAnalyzerAgent(llm=llm).analyze(FULL_JD)["confidence"] > keywords["confidence"]

    def test_a_thin_llm_reply_does_not_outrank_thorough_keywords(self):
        # Confidence tracks how much was found, not which path found it.
        thin = JobAnalyzerAgent(llm=self._reply()).analyze(FULL_JD)["confidence"]
        thorough = JobAnalyzerAgent(llm=StubLLM(available=False)).analyze(FULL_JD)["confidence"]
        assert thin < thorough


class TestExtractRequirements:
    def test_returns_the_six_documented_keys(self, agent):
        result = agent.extract_requirements(FULL_JD)
        assert set(result) == {
            "required_skills", "tech_stack", "experience_level",
            "soft_skills", "education", "role_type",
        }

    def test_reuses_the_last_analysed_description(self, agent):
        agent.analyze(FULL_JD)
        assert agent.extract_requirements()["role_type"] == "ai/ml"

    def test_raises_when_nothing_has_been_analysed(self, agent):
        with pytest.raises(EmptyJobDescriptionError, match="Call analyze"):
            agent.extract_requirements()

    def test_experience_level_is_a_band_not_a_number(self, agent):
        assert agent.extract_requirements(FULL_JD)["experience_level"] == "senior"


class TestTraceFields:
    def test_supplies_the_requested_columns(self, agent):
        fields = agent.trace_fields(agent.analyze(FULL_JD))
        assert fields["label"] == "Job Analyzer"
        assert fields["skills_extracted"] == 6
        assert 0.0 <= fields["confidence"] <= 1.0

    def test_handles_an_empty_analysis(self, agent):
        assert agent.trace_fields({}) == {
            "label": "Job Analyzer", "skills_extracted": 0, "confidence": 0.0
        }


class TestNormalisationHelpers:
    @pytest.mark.parametrize(
        "value,expected",
        [(5, 5), ("5", 5), ("5+ years", 5), (5.9, 5), (None, 0), (True, 0),
         ("lots", 0), (0, 0), (99, 0), ([], 0)],
    )
    def test_coerce_years(self, value, expected):
        assert _coerce_years(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [("backend", "backend"), ("Full-Stack", "fullstack"), ("full stack", "fullstack"),
         ("ml/ai", "ai/ml"), ("ai/ml", "ai/ml"), ("wizard", None), (None, None)],
    )
    def test_clean_role(self, value, expected):
        assert _clean_role(value) == expected
