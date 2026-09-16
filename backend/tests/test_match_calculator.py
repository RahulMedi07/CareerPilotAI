"""Tests for agents.match_calculator."""

import json

import pytest

from agents.match_calculator import (
    APPLY_THRESHOLD,
    COMPONENT_WEIGHTS,
    MAYBE_THRESHOLD,
    MatchCalculator,
    _as_years,
    _education_key,
    _renormalise,
    extract_resume_education,
    extract_resume_years,
    match_calculator,
)
from models.career_models import JobAnalysis, Skill

RESUME = """Jane Developer

Summary
Backend engineer with 7 years of experience building Python services.

Skills
Python, FastAPI, Docker, Kubernetes, PostgreSQL, LangChain

Experience
Senior Engineer at Acme Corp. Designed microservices handling 2M requests a day.
Mentored three junior engineers and led the migration to Kubernetes.
Strong written and verbal communication.

Education
BSc Computer Science, State University
"""

JOB = {
    "title": "Senior Backend Engineer",
    "required_skills": ["python", "docker", "kubernetes", "aws"],
    "tech_stack": ["python", "docker", "kubernetes", "aws"],
    "experience_years": 5,
    "soft_skills": ["communication", "mentoring"],
    "education": "bachelors",
    "confidence": 0.9,
}


def score(resume=None, job=None, **kwargs):
    return match_calculator.calculate_match(
        resume if resume is not None else {"resume_text": RESUME},
        job if job is not None else JOB,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputStructure:
    def test_has_the_documented_top_level_keys(self):
        report = score()
        for key in ("overall_match", "match_breakdown", "recommendation", "confidence"):
            assert key in report, key

    def test_breakdown_has_all_five_components(self):
        assert set(score()["match_breakdown"]) == {
            "skills", "tech_stack", "experience", "soft_skills", "education",
        }

    def test_every_component_reports_a_score(self):
        for name, component in score()["match_breakdown"].items():
            assert 0.0 <= component["score"] <= 100.0, name

    def test_skill_components_report_found_and_missing(self):
        breakdown = score()["match_breakdown"]
        for name in ("skills", "tech_stack", "soft_skills"):
            assert isinstance(breakdown[name]["found"], list), name
            assert isinstance(breakdown[name]["missing"], list), name

    def test_experience_reports_found_and_required_as_text(self):
        experience = score()["match_breakdown"]["experience"]
        assert experience["found"] == "7 years"
        assert experience["required"] == "5 years"

    def test_overall_is_a_percentage(self):
        assert 0.0 <= score()["overall_match"] <= 100.0

    def test_confidence_is_a_percentage_not_a_fraction(self):
        # The job analyzer reports 0-1; this report reports 0-100.
        assert 1.0 < score()["confidence"] <= 100.0

    def test_report_is_json_serialisable(self):
        assert json.dumps(score())

    def test_weights_sum_to_one(self):
        assert sum(COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Skills and tech stack
# ---------------------------------------------------------------------------


class TestSkillMatching:
    def test_finds_the_skills_present(self):
        found = score()["match_breakdown"]["skills"]["found"]
        assert {"python", "docker", "kubernetes"} <= set(found)

    def test_reports_the_skill_that_is_absent(self):
        assert score()["match_breakdown"]["skills"]["missing"] == ["aws"]

    def test_all_skills_present_scores_100(self):
        report = score(job={"required_skills": ["python", "docker"]})
        assert report["match_breakdown"]["skills"]["score"] == 100.0

    def test_no_skills_present_scores_zero(self):
        report = score({"resume_text": "I write poetry."},
                       {"required_skills": ["python", "docker"]})
        assert report["match_breakdown"]["skills"]["score"] == 0.0

    def test_half_the_skills_scores_half(self):
        report = score({"skills": ["python"]},
                       {"required_skills": ["python", "rust"]})
        assert report["match_breakdown"]["skills"]["score"] == 50.0

    def test_explicit_skill_list_beats_text_scanning(self):
        report = score({"resume_text": "nothing here", "skills": ["python"]},
                       {"required_skills": ["python"]})
        assert report["match_breakdown"]["skills"]["score"] == 100.0

    def test_skills_are_read_from_text_when_not_supplied(self):
        report = score({"resume_text": "I use Python daily."},
                       {"required_skills": ["python"]})
        assert report["match_breakdown"]["skills"]["score"] == 100.0

    def test_matching_is_case_insensitive(self):
        report = score({"skills": ["PYTHON"]}, {"required_skills": ["python"]})
        assert report["match_breakdown"]["skills"]["score"] == 100.0

    def test_tech_stack_drops_concepts(self):
        report = score(
            {"skills": ["python", "rag"]},
            {"required_skills": ["python", "rag"], "tech_stack": ["python"]},
        )
        assert report["match_breakdown"]["tech_stack"]["found"] == ["python"]

    def test_tech_stack_is_derived_when_the_job_omits_it(self):
        report = score({"skills": ["python"]}, {"required_skills": ["python"]})
        assert report["match_breakdown"]["tech_stack"]["applicable"] is True


class TestFuzzyMatching:
    @pytest.mark.parametrize(
        "resume_skill,required",
        [
            ("K8s", "kubernetes"),
            ("ReactJS", "react"),
            ("Postgres", "postgresql"),
            ("NodeJS", "node.js"),
            ("golang", "go"),
            ("ML", "machine learning"),
            ("scikit learn", "scikit-learn"),
        ],
    )
    def test_recognises_the_same_technology_under_another_name(
        self, resume_skill, required
    ):
        report = score({"skills": [resume_skill]}, {"required_skills": [required]})
        assert report["match_breakdown"]["skills"]["missing"] == []

    @pytest.mark.parametrize(
        "resume_skill,required",
        [
            ("JavaScript", "java"),
            ("C++", "c#"),
            ("Azure", "aws"),
            ("Angular", "react"),
            ("NoSQL", "sql"),
            ("PyTorch", "tensorflow"),
        ],
    )
    def test_does_not_credit_a_merely_similar_technology(self, resume_skill, required):
        report = score({"skills": [resume_skill]}, {"required_skills": [required]})
        assert report["match_breakdown"]["skills"]["missing"] == [required]

    def test_a_typo_still_matches_but_scores_below_exact(self):
        typo = score({"skills": ["kubernets"]}, {"required_skills": ["kubernetes"]})
        exact = score({"skills": ["kubernetes"]}, {"required_skills": ["kubernetes"]})
        assert typo["match_breakdown"]["skills"]["missing"] == []
        assert typo["match_breakdown"]["skills"]["score"] < exact["match_breakdown"]["skills"]["score"]

    def test_records_why_a_skill_matched(self):
        report = score({"skills": ["K8s"]}, {"required_skills": ["kubernetes"]})
        match = report["match_breakdown"]["skills"]["matches"][0]
        assert match["required"] == "kubernetes"
        assert match["matched"] == "K8s"
        assert match["reason"]


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------


class TestExperienceMatching:
    def test_meeting_the_requirement_scores_100(self):
        assert MatchCalculator()._calculate_experience_match(5, 5)["score"] == 100.0

    def test_exceeding_the_requirement_is_not_a_bonus(self):
        calc = MatchCalculator()
        assert calc._calculate_experience_match(20, 5)["score"] == 100.0

    def test_falling_short_scores_proportionally(self):
        component = MatchCalculator()._calculate_experience_match(4, 5)
        assert 20.0 < component["score"] < 100.0

    def test_a_large_shortfall_keeps_a_floor(self):
        assert MatchCalculator()._calculate_experience_match(1, 20)["score"] == 20.0

    def test_no_experience_stated_in_the_resume_scores_zero(self):
        component = MatchCalculator()._calculate_experience_match(0, 5)
        assert component["score"] == 0.0
        assert component["found"] == "not stated"

    def test_a_job_asking_for_no_years_is_not_assessed(self):
        component = MatchCalculator()._calculate_experience_match(3, 0)
        assert component["applicable"] is False

    def test_reads_years_out_of_the_resume_text(self):
        report = score({"resume_text": RESUME}, {"experience_years": 5})
        assert report["match_breakdown"]["experience"]["years_found"] == 7

    def test_flags_whether_the_requirement_is_met(self):
        assert MatchCalculator()._calculate_experience_match(7, 5)["meets_requirement"]
        assert not MatchCalculator()._calculate_experience_match(2, 5)["meets_requirement"]


class TestExtractResumeYears:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("7 years of experience", 7),
            ("10+ years experience", 10),
            ("Backend engineer with 3 years of experience", 3),
            ("5 yrs experience", 5),
            ("", 0),
            ("no numbers", 0),
            ("99 years of experience", 0),
        ],
    )
    def test_reads_a_career_length(self, text, expected):
        assert extract_resume_years(text) == expected

    def test_takes_the_longest_span(self):
        text = "3 years of experience in Go. 8 years of experience in Python."
        assert extract_resume_years(text) == 8


# ---------------------------------------------------------------------------
# Soft skills and education
# ---------------------------------------------------------------------------


class TestSoftSkillMatching:
    def test_finds_soft_skills_in_the_resume(self):
        found = score()["match_breakdown"]["soft_skills"]["found"]
        assert {"communication", "mentoring"} <= set(found)

    def test_scored_leniently_when_some_are_shown(self):
        calc = MatchCalculator()
        component = calc._calculate_soft_skill_match(
            ["communication"], ["communication", "leadership"]
        )
        # 1 of 2 is 50, plus the leniency bonus.
        assert component["score"] == 75.0

    def test_showing_none_is_unassessed_rather_than_zero(self):
        """A resume naming no soft skills is missing evidence, not failing it.

        This used to score a hard 0.0 at the full 10% weight, which asserted the
        candidate lacks communication because a word was absent. Most
        engineering resumes describe achievements rather than adjectives, so
        that penalised the writing style rather than the candidate.
        """
        calc = MatchCalculator()
        component = calc._calculate_soft_skill_match([], ["leadership"])
        assert component["applicable"] is False
        # Still reported, so the candidate is told what to add.
        assert component["missing"] == ["leadership"]

    def test_an_unassessed_soft_skill_does_not_drag_the_total_down(self):
        calc = MatchCalculator()
        component = calc._calculate_soft_skill_match([], ["leadership"])
        assert component["score"] == 100.0
        assert component["applicable"] is False

    def test_a_job_naming_no_soft_skills_is_not_assessed(self):
        calc = MatchCalculator()
        assert calc._calculate_soft_skill_match(["x"], [])["applicable"] is False


class TestEducationMatching:
    def test_exact_level_is_a_full_match(self):
        calc = MatchCalculator()
        assert calc._calculate_education_match("bachelors", "bachelors")["score"] == 100.0

    def test_a_higher_qualification_satisfies_a_lower_requirement(self):
        calc = MatchCalculator()
        assert calc._calculate_education_match("phd", "bachelors")["score"] == 100.0

    def test_falling_short_scores_partially(self):
        calc = MatchCalculator()
        component = calc._calculate_education_match("bachelors", "masters")
        assert 0.0 < component["score"] < 100.0

    def test_no_qualification_against_a_requirement_scores_zero(self):
        calc = MatchCalculator()
        assert calc._calculate_education_match("not specified", "masters")["score"] == 0.0

    def test_or_equivalent_experience_forgives_a_shortfall(self):
        calc = MatchCalculator()
        component = calc._calculate_education_match(
            "not specified", "bachelors (or equivalent experience)"
        )
        assert component["score"] == 75.0
        assert component["meets_requirement"] is True

    @pytest.mark.parametrize("required", ["not specified", "", None, "not required"])
    def test_no_requirement_is_not_assessed(self, required):
        calc = MatchCalculator()
        assert calc._calculate_education_match("phd", required)["applicable"] is False

    def test_reads_the_qualification_from_the_resume(self):
        assert score()["match_breakdown"]["education"]["found"] == "bachelors"


class TestExtractResumeEducation:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("PhD in Computer Science", "phd"),
            ("MSc Machine Learning", "masters"),
            ("MBA", "masters"),
            ("BSc Computer Science", "bachelors"),
            ("Bachelor of Engineering", "bachelors"),
            ("Completed a coding bootcamp", "bootcamp"),
            ("", "not specified"),
            ("Self taught", "not specified"),
        ],
    )
    def test_reads_the_highest_qualification(self, text, expected):
        assert extract_resume_education(text) == expected

    def test_highest_wins_when_several_are_listed(self):
        assert extract_resume_education("BSc Physics, then an MSc in AI") == "masters"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("B.E. in Information Science & Engineering", "bachelors"),
            ("B.E in Information Science", "bachelors"),
            ("B.Tech Computer Science", "bachelors"),
            ("BCA from Delhi University", "bachelors"),
            ("B.Com", "bachelors"),
            ("BBA", "bachelors"),
            ("M.Tech in Computer Science", "masters"),
            ("M.E. in Structural Engineering", "masters"),
            ("MCA, Pune University", "masters"),
        ],
    )
    def test_indian_qualifications_are_recognised(self, text, expected):
        """This product only searches India, so these are the common cases.

        A real CV reading "B.E. in Information Science" was reported as
        having no education at all.
        """
        assert extract_resume_education(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Happy to be contacted, please email me",
            "I want to be an engineer. Contact me.",
            "Feel free to be in touch with me anytime",
            "masterful engineer",
        ],
    )
    def test_ordinary_words_are_not_degrees(self, text):
        """"B.E." and "M.E." need their dots. "be" and "me" are just words."""
        assert extract_resume_education(text) == "not specified"


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------


class TestRenormalisation:
    def test_unspecified_components_do_not_cap_the_score(self):
        # A job stating only skills, fully met, must still reach 100.
        report = score({"skills": ["python"]}, {"required_skills": ["python"]})
        assert report["overall_match"] == 100.0

    def test_unspecified_components_are_marked_inapplicable(self):
        report = score({"skills": ["python"]}, {"required_skills": ["python"]})
        breakdown = report["match_breakdown"]
        assert breakdown["experience"]["applicable"] is False
        assert breakdown["education"]["applicable"] is False
        assert breakdown["soft_skills"]["applicable"] is False

    def test_weights_are_shared_out_among_the_assessed_components(self):
        breakdown = {
            "skills": {"score": 100.0, "weight": 0.40, "applicable": True},
            "tech_stack": {"score": 0.0, "weight": 0.25, "applicable": True},
            "experience": {"score": 100.0, "weight": 0.15, "applicable": False},
            "soft_skills": {"score": 100.0, "weight": 0.10, "applicable": False},
            "education": {"score": 100.0, "weight": 0.10, "applicable": False},
        }
        # 100*0.4 + 0*0.25, over a total weight of 0.65.
        assert _renormalise(breakdown) == pytest.approx(61.5, abs=0.1)

    def test_a_job_with_nothing_to_score_returns_no_number(self):
        # Not 0.0. An average over no terms is undefined, and a caller that
        # cannot tell it apart from a real zero will print "0%".
        assert _renormalise({}) is None

    def test_assessed_components_carrying_no_weight_also_return_no_number(self):
        breakdown = {
            "skills": {"score": 80.0, "weight": 0.0, "applicable": True},
        }
        assert _renormalise(breakdown) is None

    def test_matching_on_years_alone_is_not_a_match(self):
        # Taken from a live search: a "Freelance Copywriter" advert named no
        # skills and no stack, but did ask for 2 years -- which the CV has. The
        # only applicable component scored 100, so the reader was shown
        # "100% - APPLY" for copywriting work, above every genuine engineering
        # role. Two years of anything satisfies a request for two years, so
        # this measured nothing about the job.
        breakdown = {
            "skills": {"score": 0.0, "weight": 0.40, "applicable": False},
            "tech_stack": {"score": 0.0, "weight": 0.25, "applicable": False},
            "experience": {"score": 100.0, "weight": 0.15, "applicable": True},
            "soft_skills": {"score": 0.0, "weight": 0.10, "applicable": False},
            "education": {"score": 0.0, "weight": 0.10, "applicable": False},
        }
        assert _renormalise(breakdown) is None

    def test_a_degree_and_soft_skills_together_are_still_not_a_match(self):
        # Two generic components instead of one changes nothing: neither says
        # anything about which job this is.
        breakdown = {
            "skills": {"score": 0.0, "weight": 0.40, "applicable": False},
            "tech_stack": {"score": 0.0, "weight": 0.25, "applicable": False},
            "experience": {"score": 0.0, "weight": 0.15, "applicable": False},
            "soft_skills": {"score": 90.0, "weight": 0.10, "applicable": True},
            "education": {"score": 100.0, "weight": 0.10, "applicable": True},
        }
        assert _renormalise(breakdown) is None

    def test_one_role_specific_component_is_enough_to_report_a_score(self):
        # The rule is about *what* was measured, not how much. An advert that
        # named its stack but nothing else is genuinely scoreable.
        breakdown = {
            "skills": {"score": 0.0, "weight": 0.40, "applicable": False},
            "tech_stack": {"score": 60.0, "weight": 0.25, "applicable": True},
            "experience": {"score": 100.0, "weight": 0.15, "applicable": True},
            "soft_skills": {"score": 0.0, "weight": 0.10, "applicable": False},
            "education": {"score": 0.0, "weight": 0.10, "applicable": False},
        }
        # 60*0.25 + 100*0.15, over a total weight of 0.40.
        assert _renormalise(breakdown) == pytest.approx(75.0, abs=0.1)

    def test_a_non_technical_advert_is_not_recommended_to_a_developer(self):
        # The end-to-end form of the bug above, through the public entry point.
        report = score(
            {"resume_text": RESUME},
            {
                "title": "Freelance Copywriter",
                "required_skills": [],
                "tech_stack": [],
                "soft_skills": [],
                "experience_years": 2,
                "education": "not specified",
            },
        )
        assert report["overall_match"] is None
        assert report["recommendation"] == "NOT_SCORED"

    def test_an_unparseable_job_is_reported_as_unscored_not_as_zero(self):
        # Nothing could be assessed, so the honest answer is "we cannot tell".
        # It used to come back as 0.0/SKIP, which reads to the user as "you are
        # a 0% match" -- a claim the app never measured.
        report = score({"resume_text": RESUME}, {})
        assert report["overall_match"] is None
        assert report["recommendation"] == "NOT_SCORED"
        assert report["confidence"] < 50.0
        assert all(
            component["applicable"] is False
            for component in report["match_breakdown"].values()
        )

    def test_the_advice_for_an_unscored_job_explains_why_rather_than_ranking_gaps(self):
        tips = score({"resume_text": RESUME}, {})["recommendations"]
        assert len(tips) == 1
        assert "nothing to check" in tips[0]

    def test_a_measured_zero_is_still_a_zero(self):
        # The counterpart to the test above: the advert asked for something,
        # the resume has none of it. That is a real 0 and must stay a number.
        report = score(
            {"skills": ["cobol"]}, {"required_skills": ["rust"], "tech_stack": ["rust"]}
        )
        assert report["overall_match"] == 0.0
        assert report["recommendation"] == "SKIP"

    def test_skills_outweigh_soft_skills(self):
        job = {"required_skills": ["python"], "soft_skills": ["leadership"]}
        skills_only = score({"skills": ["python"]}, job)["overall_match"]
        soft_only = score({"soft_skills": ["leadership"]}, job)["overall_match"]
        assert skills_only > soft_only


# ---------------------------------------------------------------------------
# Recommendation and confidence
# ---------------------------------------------------------------------------


class TestRecommendation:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (100.0, "APPLY"), (90.0, "APPLY"), (85.0, "APPLY"),
            (84.9, "MAYBE"), (70.0, "MAYBE"), (65.0, "MAYBE"),
            (64.9, "SKIP"), (20.0, "SKIP"), (0.0, "SKIP"),
        ],
    )
    def test_bands(self, value, expected):
        assert MatchCalculator._generate_recommendation(value) == expected

    def test_boundaries_match_the_documented_thresholds(self):
        assert MatchCalculator._generate_recommendation(APPLY_THRESHOLD) == "APPLY"
        assert MatchCalculator._generate_recommendation(MAYBE_THRESHOLD) == "MAYBE"

    def test_no_score_is_not_folded_into_skip(self):
        # SKIP is a judgement. "We did not measure this" is not.
        assert MatchCalculator._generate_recommendation(None) == "NOT_SCORED"

    def test_a_perfect_match_says_apply(self):
        report = score({"skills": ["python"]}, {"required_skills": ["python"]})
        assert report["recommendation"] == "APPLY"

    def test_a_hopeless_match_says_skip(self):
        report = score({"skills": ["cobol"]}, {"required_skills": ["python", "rust"]})
        assert report["recommendation"] == "SKIP"


class TestAdvice:
    def test_names_the_missing_skills(self):
        advice = " ".join(score()["recommendations"])
        assert "aws" in advice

    def test_lists_at_most_five_gaps(self):
        job = {"required_skills": [f"skill{i}" for i in range(10)]}
        advice = " ".join(score({"skills": []}, job)["recommendations"])
        assert "skill4" in advice
        assert "skill5" not in advice

    def test_mentions_an_experience_shortfall(self):
        report = score({"resume_text": "Python developer, 1 year of experience."},
                       {"required_skills": ["python"], "experience_years": 8})
        assert any("8 years" in tip for tip in report["recommendations"])

    def test_mentions_an_education_shortfall(self):
        report = score({"resume_text": "Python developer"},
                       {"required_skills": ["python"], "education": "phd"})
        assert any("phd" in tip.lower() for tip in report["recommendations"])

    def test_a_strong_match_is_told_to_apply(self):
        report = score({"skills": ["python"]}, {"required_skills": ["python"]})
        assert any("apply" in tip.lower() for tip in report["recommendations"])

    def test_a_weak_match_is_told_to_reconsider(self):
        report = score({"skills": []}, {"required_skills": ["python", "rust"]})
        assert any("weak match" in tip.lower() for tip in report["recommendations"])


class TestConfidence:
    def test_a_detailed_advert_and_resume_is_confident(self):
        assert score()["confidence"] > 60.0

    def test_a_thin_advert_is_less_confident(self):
        rich = score()["confidence"]
        thin = score({"skills": ["python"]}, {"required_skills": ["python"]})["confidence"]
        assert thin < rich

    def test_confidence_is_independent_of_the_match(self):
        # Same advert, same amount of evidence, opposite outcomes.
        good = score({"skills": ["python", "docker"]},
                     {"required_skills": ["python", "docker"], "confidence": 0.9})
        bad = score({"skills": ["cobol", "fortran"]},
                    {"required_skills": ["python", "docker"], "confidence": 0.9})
        assert good["overall_match"] > bad["overall_match"]
        assert good["confidence"] == bad["confidence"]

    def test_stays_within_bounds(self):
        assert 0.0 <= score({}, {})["confidence"] <= 100.0


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_quotes_the_resume_line_backing_a_skill(self):
        evidence = score()["match_breakdown"]["skills"]["evidence"]
        assert "python" in evidence
        assert "Python" in evidence["python"]

    def test_no_evidence_for_a_missing_skill(self):
        assert "aws" not in score()["match_breakdown"]["skills"]["evidence"]

    def test_credits_a_skill_the_resume_describes_but_never_names(self):
        report = score(
            {"resume_text": "Built a retrieval augmented generation assistant."},
            {"required_skills": ["rag"]},
        )
        assert report["match_breakdown"]["skills"]["found"] == ["rag"]
        assert (
            "retrieval augmented generation"
            in report["match_breakdown"]["skills"]["evidence"]["rag"]
        )

    def test_uses_the_retriever_when_one_is_supplied(self):
        class FakeResult:
            content = "Built a RAG pipeline in Python on ChromaDB."

        class FakeIndexer:
            def __init__(self):
                self.queries = []

            def search_by_technology(self, tech, top_k=1):
                self.queries.append(tech)
                return [FakeResult()]

        indexer = FakeIndexer()
        report = score({"skills": ["python"]}, {"required_skills": ["python"]},
                       retriever=indexer)
        assert indexer.queries == ["python"]
        assert "RAG pipeline" in report["match_breakdown"]["skills"]["evidence"]["python"]

    def test_a_broken_retriever_does_not_break_the_score(self):
        class ExplodingIndexer:
            def search_by_technology(self, tech, top_k=1):
                raise RuntimeError("index is corrupt")

        report = score({"skills": ["python"]}, {"required_skills": ["python"]},
                       retriever=ExplodingIndexer())
        assert report["overall_match"] == 100.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_inputs_do_not_raise(self):
        report = match_calculator.calculate_match({}, {})
        assert report["overall_match"] is None
        assert report["recommendation"] == "NOT_SCORED"

    def test_none_inputs_do_not_raise(self):
        assert match_calculator.calculate_match(None, None)["overall_match"] is None

    def test_empty_resume_against_a_real_job(self):
        report = score({"resume_text": ""}, JOB)
        assert report["overall_match"] < 20.0

    def test_scoring_is_reproducible(self):
        assert score()["overall_match"] == score()["overall_match"]

    def test_unknown_job_title_is_labelled(self):
        assert score({}, {"required_skills": ["python"]})["job_title"] == "Unknown role"

    @pytest.mark.parametrize(
        "value,expected",
        [(5, 5), ("5", 5), ("5+ years", 5), (5.9, 5), (None, 0), (True, 0),
         ("none", 0), (0, 0), (99, 0), ([], 0)],
    )
    def test_year_coercion(self, value, expected):
        assert _as_years(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [("bachelors", "bachelors"), ("bachelors (or equivalent experience)", "bachelors"),
         ("  MASTERS  ", "masters"), (None, "not specified"), ("", "not specified")],
    )
    def test_education_key(self, value, expected):
        assert _education_key(value) == expected


# ---------------------------------------------------------------------------
# The older Pydantic-flavoured API
# ---------------------------------------------------------------------------


def make_analysis(required=(), preferred=()):
    return JobAnalysis(
        title="Engineer",
        required_skills=[Skill(name=n) for n in required],
        preferred_skills=[Skill(name=n) for n in preferred],
    )


class TestLegacyCalculate:
    def test_returns_a_match_result(self):
        result = match_calculator.calculate("r1", RESUME, make_analysis(["python"]))
        assert result.resume_id == "r1"
        assert result.job_title == "Engineer"
        assert 0.0 <= result.score <= 100.0

    def test_perfect_match_scores_100(self):
        analysis = make_analysis(["python", "docker"])
        assert match_calculator.calculate("r1", "python docker", analysis).score == 100.0

    def test_no_overlap_scores_zero(self):
        analysis = make_analysis(["python", "docker"])
        result = match_calculator.calculate("r1", "I write poetry.", analysis)
        assert result.score == 0.0
        assert set(result.missing_skills) >= {"python", "docker"}

    def test_preferred_skills_appear_in_the_lists(self):
        analysis = make_analysis(["python"], ["docker"])
        result = match_calculator.calculate("r1", "python docker", analysis)
        assert "docker" in result.matched_skills

    def test_missing_preferred_skills_are_reported(self):
        analysis = make_analysis(["python"], ["rust"])
        result = match_calculator.calculate("r1", "python", analysis)
        assert "rust" in result.missing_skills

    def test_recommendations_are_produced(self):
        result = match_calculator.calculate("r1", "python", make_analysis(["python"]))
        assert result.recommendations

    def test_delegates_to_the_one_scoring_engine(self):
        # The legacy wrapper must not have its own arithmetic.
        analysis = make_analysis(["python", "aws"])
        legacy = match_calculator.calculate("r1", RESUME, analysis).score
        modern = match_calculator.calculate_match(
            {"resume_text": RESUME},
            {"title": "Engineer", "required_skills": ["python", "aws"]},
        )["overall_match"]
        assert legacy == modern
