"""Tests for the interview prep agent.

The honesty classes here matter more than anywhere else in the project. A
resume suggestion is read once, in private, and can be edited before it goes
anywhere. An interview answer is *spoken*, under questioning, by someone who
has rehearsed it - and the panel's whole job is to probe it. A fabricated
detail in a suggested answer does not get caught by the candidate; it gets
caught by the interviewer, one follow-up question later, in the room.

So two properties are pinned down below:

- :class:`TestAnswersAreScaffoldsNotScripts` - every suggested answer is built
  from lines that genuinely appear in the resume, and everything else is a
  labelled blank.
- :class:`TestGapCoachingIsHonest` - advice about a missing skill never tells
  the candidate to claim experience or study they do not have, and never tells
  them to *disown* experience they do have either. Skill matching is
  imperfect, and both directions do damage.
"""

from __future__ import annotations

import json

import pytest

from agents.interview_prep import (
    ANSWER_PLACEHOLDERS,
    BEHAVIOURAL_BANK,
    EASY,
    GAP_BASED,
    HARD,
    HIGH,
    HR_BANK,
    LOW,
    MEDIUM,
    TECHNICAL,
    InterviewPrepAgent,
    interview_prep_agent,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

RESUME = """
RAHUL SHARMA
AI/ML Developer with 2 years experience building AI applications.

SKILLS
Python, FastAPI, REST APIs
LangChain, RAG, Embeddings
Docker, Git, PostgreSQL

EXPERIENCE
AI Developer - TechCorp (2023-present)
- Built RAG system with LangChain
- Created REST APIs with FastAPI
- Implemented embeddings pipeline for search

Intern - AI Startup (2022-2023)
- Learned LLM basics

PROJECTS
1. Document Q&A System
- Built with LangChain and Chroma vector storage

EDUCATION
B.Tech Computer Science, 2022
"""

JOB = {
    "title": "AI/ML Engineer",
    "required_skills": ["python", "langchain", "rag", "embeddings", "pinecone"],
    "preferred_skills": ["fastapi", "docker"],
    "tech_stack": ["python", "langchain"],
    "experience_years": 3,
    "seniority": "mid",
    "role_type": "ai/ml",
    "job_description": (
        "AI/ML Engineer. You will build RAG pipelines, tune RAG retrieval and "
        "own the RAG stack. Python, LangChain and embeddings essential. "
        "Pinecone required."
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
        },
        {
            "skill": "Kubernetes",
            "skill_id": "kubernetes",
            "importance": "CRITICAL",
            "learning_time_days": 30,
            "similar_skills_user_has": [],
        },
    ],
    "nice_to_have_gaps": [],
}

MATCH = {
    "overall_match": 62.0,
    "recommendation": "MAYBE",
    "matched_skills": ["python", "langchain", "rag", "embeddings"],
    "missing_skills": ["pinecone"],
}


def prep(resume=RESUME, job=None, gaps=GAPS, match=MATCH):
    return interview_prep_agent.prepare_interview(
        dict(JOB if job is None else job),
        {"resume_text": resume},
        gaps,
        match,
    )


@pytest.fixture(scope="module")
def report():
    return prep()


@pytest.fixture
def agent():
    return InterviewPrepAgent()


def answers(report):
    return [q["suggested_answer"] for q in report["questions"]]


# --------------------------------------------------------------------------
# Honesty
# --------------------------------------------------------------------------


class TestAnswersAreScaffoldsNotScripts:
    """Nothing in an answer may be a fact the resume does not contain."""

    def test_quoted_evidence_really_appears_in_the_resume(self, report):
        lowered = RESUME.lower()
        for question in report["questions"]:
            for quote in _quotes(question["suggested_answer"]):
                assert quote.lower() in lowered, f"invented quote: {quote!r}"

    def test_answers_never_invent_a_number(self, report):
        for answer in answers(report):
            stripped = answer
            for placeholder in ANSWER_PLACEHOLDERS:
                stripped = stripped.replace(placeholder, "")
            for quote in _quotes(answer):
                stripped = stripped.replace(quote, "")
            assert not any(c.isdigit() for c in stripped), answer

    def test_answers_never_invent_a_technology(self, report):
        lowered = RESUME.lower()
        for answer in answers(report):
            for invented in ("kubernetes", "kafka", "terraform", "spark", "redis"):
                if invented in lowered:
                    continue
                # A gap answer may name the missing skill; a technical one may not.
                assert invented not in answer.lower() or "not used" in answer.lower()

    def test_answers_needing_input_say_so(self, report):
        for question in report["questions"]:
            if question.get("answer_placeholders"):
                assert question["needs_your_input"] is True

    def test_placeholders_are_declared(self, report):
        for question in report["questions"]:
            declared = set(question.get("answer_placeholders") or [])
            for placeholder in ANSWER_PLACEHOLDERS:
                if placeholder in question["suggested_answer"]:
                    assert placeholder in declared

    def test_output_carries_an_honesty_note(self, report):
        assert report["honesty_note"]


class TestGapCoachingIsHonest:
    """Gap advice must not coach a lie in either direction."""

    def gap_questions(self, report):
        return [q for q in report["questions"] if q["category"] == GAP_BASED]

    def test_gaps_produce_questions(self, report):
        assert self.gap_questions(report)

    def test_never_tells_them_to_claim_study_they_have_not_done(self, report):
        for question in self.gap_questions(report):
            text = " ".join(
                [question["suggested_answer"]] + list(question.get("how_to_handle") or [])
            ).lower()
            # The spec's own example said "mention you've studied the basics".
            assert "mention you've studied" not in text
            assert "say you have studied" not in text
            if "studi" in text or "studied" in text:
                assert "only" in text or "if you have" in text or "really" in text

    def test_a_gap_with_no_related_skill_is_stated_plainly(self, report):
        for question in self.gap_questions(report):
            if question["skill"] == "Kubernetes":
                assert "have not used" in question["suggested_answer"].lower()

    def test_a_gap_with_a_related_skill_does_not_coach_denial(self, report):
        """Skill matching is imperfect; do not disown real experience."""
        for question in self.gap_questions(report):
            if question["skill"] == "Pinecone":
                answer = question["suggested_answer"].lower()
                assert "does not name" in answer
                assert "talk yourself out of" in answer

    def test_gap_advice_always_offers_a_next_step(self, report):
        for question in self.gap_questions(report):
            assert question["how_to_handle"]

    def test_gap_questions_are_marked_low_or_medium_confidence(self, report):
        for question in self.gap_questions(report):
            assert question["confidence_level"] in (MEDIUM, LOW)

    def test_a_gap_never_claims_high_strength(self, report):
        for question in self.gap_questions(report):
            assert question["your_strength"].startswith("Low")


class TestPredictionIsNotOversold:
    def test_never_promises_near_certainty(self, agent):
        result = agent._predict_success_rate({"overall_match": 100.0}, None, EASY)
        assert result <= 0.92

    def test_never_reports_zero(self, agent):
        result = agent._predict_success_rate({"overall_match": 0.0}, GAPS, HARD)
        assert result >= 0.05

    def test_tracks_the_match_score(self, agent):
        low = agent._predict_success_rate({"overall_match": 30.0}, None, MEDIUM)
        high = agent._predict_success_rate({"overall_match": 85.0}, None, MEDIUM)
        assert high > low

    def test_critical_gaps_reduce_it(self, agent):
        clean = agent._predict_success_rate({"overall_match": 70.0}, None, MEDIUM)
        gapped = agent._predict_success_rate({"overall_match": 70.0}, GAPS, MEDIUM)
        assert gapped < clean

    def test_a_harder_interview_reduces_it(self, agent):
        easy = agent._predict_success_rate({"overall_match": 70.0}, None, EASY)
        hard = agent._predict_success_rate({"overall_match": 70.0}, None, HARD)
        assert hard < easy

    def test_survives_a_broken_match_score(self, agent):
        assert 0.0 <= agent._predict_success_rate({"overall_match": "n/a"}) <= 1.0


# --------------------------------------------------------------------------
# Output contract
# --------------------------------------------------------------------------


class TestOutputStructure:
    def test_has_every_documented_key(self, report):
        for key in (
            "interview_difficulty",
            "estimated_prep_time_hours",
            "questions",
            "behavioral_questions",
            "company_questions",
            "your_questions_for_them",
            "preparation_plan",
            "success_rate_prediction",
            "confidence",
        ):
            assert key in report

    def test_is_json_serialisable(self, report):
        assert json.loads(json.dumps(report)) == report

    def test_questions_are_numbered_from_one(self, report):
        ids = [q["id"] for q in report["questions"]]
        assert ids == list(range(1, len(ids) + 1))

    def test_every_question_has_the_required_fields(self, report):
        for question in report["questions"]:
            for field in (
                "category",
                "question",
                "why_asked",
                "your_strength",
                "suggested_answer",
                "confidence_level",
            ):
                assert question[field], f"{field} missing from {question['id']}"

    def test_difficulty_is_a_known_band(self, report):
        assert report["interview_difficulty"] in (EASY, MEDIUM, HARD)

    def test_confidence_is_a_probability(self, report):
        assert 0.0 <= report["confidence"] <= 1.0

    def test_success_rate_is_a_probability(self, report):
        assert 0.0 <= report["success_rate_prediction"] <= 1.0

    def test_confidence_levels_are_known(self, report):
        for question in report["questions"]:
            assert question["confidence_level"] in (HIGH, MEDIUM, LOW)

    def test_source_is_declared(self, report):
        assert report["source"]


class TestStudiable:
    """The spec's real requirement: the candidate can revise from this."""

    def test_every_question_explains_why_it_is_asked(self, report):
        for question in report["questions"]:
            assert len(question["why_asked"].split()) >= 4

    def test_technical_questions_have_follow_ups(self, report):
        technical = [q for q in report["questions"] if q["category"] == TECHNICAL]
        assert technical
        for question in technical:
            assert question["follow_ups"]

    def test_answers_are_substantial_enough_to_revise_from(self, report):
        for answer in answers(report):
            assert len(answer.split()) >= 15

    def test_the_plan_is_ordered_by_day(self, report):
        days = [d["day"] for d in report["preparation_plan"]]
        assert days == list(range(1, len(days) + 1))

    def test_every_plan_day_has_concrete_tasks(self, report):
        for day in report["preparation_plan"]:
            assert day["tasks"]
            assert day["focus"]

    def test_the_headline_hours_match_the_plan(self, report):
        """A 17-hour estimate beside a 12-hour plan destroys trust in both."""
        total = sum(d["time_hours"] for d in report["preparation_plan"])
        assert report["estimated_prep_time_hours"] == pytest.approx(total, abs=0.1)

    def test_no_day_demands_more_than_someone_can_sustain(self, report):
        for day in report["preparation_plan"]:
            assert day["time_hours"] <= 2.5

    def test_own_projects_are_revised_first(self, report):
        """Highest return on effort, and the thing candidates skip."""
        assert "your own" in report["preparation_plan"][0]["focus"].lower()


# --------------------------------------------------------------------------
# The individual generators
# --------------------------------------------------------------------------


class TestTechnicalQuestions:
    def technical(self, report):
        return [q for q in report["questions"] if q["category"] == TECHNICAL]

    def test_only_asks_about_skills_the_resume_claims(self, report):
        for question in self.technical(report):
            assert question["skill"].lower() not in ("pinecone", "kubernetes")

    def test_the_most_stressed_skill_is_asked_early(self, report):
        """The advert repeats RAG; the panel will open there."""
        skills = [q["skill"].lower() for q in self.technical(report)]
        assert "rag" in skills[:3]

    def test_does_not_waste_a_question_on_a_commodity_tool(self, report):
        """Nobody is interviewed on Git."""
        skills = [q["skill"].lower() for q in report["questions"]]
        assert "git" not in skills

    def test_strength_reflects_the_evidence_count(self, report):
        for question in self.technical(report):
            if question["skill"].lower() == "langchain":
                # Two narrative lines mention it, so it is a strong topic.
                assert question["your_strength"].startswith("High")
            if question["skill"].lower() == "rag":
                assert question["your_strength"].startswith(("High", "Medium"))

    def test_is_capped(self, report):
        assert len(self.technical(report)) <= interview_prep_agent.max_technical

    def test_a_core_stack_skill_says_so(self, report):
        reasons = " ".join(q["why_asked"] for q in self.technical(report)).lower()
        assert "core stack" in reasons


class TestAnswerConstruction:
    def test_anchors_on_real_work_not_the_summary(self, agent):
        """A summary asserts; an experience bullet demonstrates."""
        answer = agent._create_suggested_answer(
            {"skill": "langchain"}, {"resume_text": RESUME}
        )
        assert "Built RAG system with LangChain" in answer

    def test_offers_a_second_example_when_one_exists(self, agent):
        answer = agent._create_suggested_answer(
            {"skill": "langchain"}, {"resume_text": RESUME}
        )
        assert "second example" in answer

    def test_handles_a_skill_with_no_evidence(self, agent):
        answer = agent._create_suggested_answer(
            {"skill": "docker"}, {"resume_text": RESUME}
        )
        assert "never shows where you used it" in answer

    def test_empty_resume_does_not_crash(self, agent):
        assert agent._create_suggested_answer({"skill": "python"}, {})


class TestFollowUps:
    def test_uses_the_bank_when_the_skill_is_known(self, agent):
        follow_ups = agent._generate_follow_ups({"skill": "rag"})
        assert any("chunk" in f.lower() for f in follow_ups)

    def test_falls_back_for_an_unknown_skill(self, agent):
        assert agent._generate_follow_ups({"skill": "cobol"})

    def test_accepts_a_bare_string(self, agent):
        assert agent._generate_follow_ups("rag")

    def test_gap_follow_ups_are_about_learning(self, agent):
        follow_ups = agent._generate_follow_ups({"category": GAP_BASED})
        assert "learn" in " ".join(follow_ups).lower()

    def test_is_capped(self, agent):
        assert len(agent._generate_follow_ups({"skill": "rag"})) <= 4


class TestBehaviouralQuestions:
    def test_returns_the_standard_set(self, report):
        assert len(report["behavioral_questions"]) >= len(BEHAVIOURAL_BANK)

    def test_each_explains_what_is_being_tested(self, report):
        for question in report["behavioral_questions"]:
            assert question["context"]
            assert question["suggested_approach"]

    def test_role_adds_a_relevant_question(self, agent):
        ai = " ".join(q["question"] for q in agent._generate_behavioral_questions("ai/ml"))
        backend = " ".join(
            q["question"] for q in agent._generate_behavioral_questions("backend")
        )
        assert ai != backend

    def test_an_unknown_role_still_works(self, agent):
        assert agent._generate_behavioral_questions("astrology")

    def test_does_not_mutate_the_shared_bank(self, agent):
        agent._generate_behavioral_questions("ai/ml")[0]["question"] = "changed"
        assert BEHAVIOURAL_BANK[0]["question"] != "changed"


class TestHrQuestions:
    """The round people prepare least and get caught by most."""

    def test_the_hr_round_is_kept_separate_from_the_behavioural_one(self, report):
        """Different people ask these, looking for different things.

        "Tell me about a conflict" is scored by the hiring manager on how you
        work. "What is your notice period" is scored by a recruiter against a
        start date. Merging them into one list would bury the second set.
        """
        assert report["hr_questions"]
        hr = {q["question"] for q in report["hr_questions"]}
        behavioural = {q["question"] for q in report["behavioral_questions"]}
        assert not hr & behavioural

    def test_it_covers_the_questions_nobody_rehearses(self, report):
        joined = " ".join(q["question"] for q in report["hr_questions"]).lower()
        assert "notice period" in joined
        assert "salary" in joined or "compensation" in joined

    def test_every_one_says_how_to_approach_it(self, report):
        for question in report["hr_questions"]:
            assert question["suggested_approach"]

    def test_does_not_mutate_the_shared_bank(self, agent):
        agent._generate_hr_questions()[0]["question"] = "changed"
        assert HR_BANK[0]["question"] != "changed"


class TestScenarioQuestions:
    def test_the_role_changes_the_scenarios(self, agent):
        ai = " ".join(q["question"] for q in agent._generate_scenario_questions("ai/ml"))
        backend = " ".join(
            q["question"] for q in agent._generate_scenario_questions("backend")
        )
        assert ai != backend

    def test_an_unknown_role_still_gets_the_general_ones(self, agent):
        # Every role is asked something situational. Returning nothing for an
        # unrecognised role_type would silently empty the section.
        assert agent._generate_scenario_questions("astrology")

    def test_each_explains_what_is_being_tested(self, report):
        for question in report["scenario_questions"]:
            assert question["context"]
            assert question["suggested_approach"]


class TestProjectQuestions:
    """Questions built from the user's own resume, quoted verbatim."""

    def test_it_quotes_the_resume_rather_than_paraphrasing_it(self, report):
        """Paraphrasing would mean generating work this code cannot verify.

        Quoting is checkable: the line is either on the CV or it is not.
        """
        joined = " ".join(q["question"] for q in report["project_questions"])
        assert "RAG system with LangChain" in joined or "embeddings pipeline" in joined

    def test_it_only_quotes_lines_that_are_actually_on_the_resume(self, report):
        for question in report["project_questions"]:
            quoted = question["question"]
            # Every quoted fragment has to trace back to the source document.
            fragment = quoted.split('"')[1] if '"' in quoted else ""
            if fragment:
                assert fragment.rstrip(".…").strip() in RESUME.replace("\n", " ") or (
                    fragment.split("…")[0].strip() in RESUME
                )

    def test_the_ones_the_advert_cares_about_are_marked(self, report):
        # LangChain and RAG are both named in the advert, so at least one
        # quoted line should be flagged as worth leading with.
        assert any(q.get("matches_advert") for q in report["project_questions"])

    def test_a_resume_with_no_projects_or_experience_produces_none(self):
        result = prep(resume="SKILLS\nPython, Docker\n")
        assert result["project_questions"] == []

    def test_each_one_names_what_it_is_about(self, report):
        for question in report["project_questions"]:
            assert question["category"]

    def test_a_role_that_lost_its_line_breaks_is_split_back_up(self):
        """A PDF that flattens a role into one line, as they routinely do.

        Observed live: the whole of a job -- title, employer, dates and four
        bullets -- arrived as a single line and was quoted back truncated
        mid-word, so "walk me through that" pointed at nothing in particular.
        """
        result = prep(
            resume=(
                "SKILLS\nPython\n\nEXPERIENCE\n"
                "Junior AI Developer - TechCorp (2023-Present) - Built a RAG "
                "system with LangChain for internal search - Implemented an "
                "embeddings pipeline over the document store - Created REST "
                "APIs with FastAPI for the search front end\n"
            )
        )
        quoted = [q["question"].split('"')[1] for q in result["project_questions"]]
        assert quoted, "expected at least one project question"
        # Each quote is one achievement, not the whole role glued together.
        assert any(q.startswith("Built a RAG system") for q in quoted)
        assert not any("Junior AI Developer" in q for q in quoted)
        assert not any(q.endswith("...") for q in quoted)

    def test_a_dash_used_as_punctuation_does_not_lose_the_achievement(self):
        """The split is a repair for run-ons, not a rule about dashes.

        One bullet with one dash in it must survive intact, or a normal
        resume would quietly lose questions.
        """
        result = prep(
            resume=(
                "SKILLS\nPython\n\nEXPERIENCE\n"
                "- Rebuilt the ingestion job in Python - it now finishes "
                "before the morning reports run\n"
            )
        )
        quoted = " ".join(q["question"] for q in result["project_questions"])
        assert "Rebuilt the ingestion job in Python - it now finishes" in quoted

    def test_a_profile_summary_is_not_treated_as_a_project(self):
        """Seen live on a real PDF.

        The section split handed the preamble to Experience, and the page
        quoted "RAHUL SHARMA PROFESSIONAL SUMMARY: AI/ML Developer with 2+
        years experience in building AI systems using Python..." back at its
        own author and asked what the hard part was. A summary is a claim
        about the candidate, not a piece of work to defend.
        """
        result = prep(
            resume=(
                "SKILLS\nPython\n\nEXPERIENCE\n"
                "RAHUL SHARMA PROFESSIONAL SUMMARY: AI/ML Developer with 2+ "
                "years experience building systems in Python and LangChain\n"
                "Built a document search service in Python that the support "
                "team now uses daily\n"
            )
        )
        quoted = [q["question"].split('"')[1] for q in result["project_questions"]]
        assert not any("PROFESSIONAL SUMMARY" in q for q in quoted)
        assert any(q.startswith("Built a document search service") for q in quoted)

    def test_a_skills_list_is_not_treated_as_a_project(self):
        # "Python development - API integration - Learned LLM basics" is a
        # list of claims, and none of them can carry a five-minute answer.
        result = prep(
            resume=(
                "SKILLS\nPython\n\nPROJECTS\n"
                "Python development - API integration - Learned LLM basics\n"
            )
        )
        assert result["project_questions"] == []


class TestAreasToImprove:
    def test_a_missing_required_skill_is_named(self, report):
        joined = " ".join(item["area"] for item in report["areas_to_improve"]).lower()
        assert "pinecone" in joined or "kubernetes" in joined

    def test_every_area_says_why_and_what_to_do(self, report):
        """A weakness with no remedy attached is just discouragement."""
        for item in report["areas_to_improve"]:
            assert item["why"]
            assert item["what_to_do"]

    def test_a_resume_without_projects_is_told_so(self):
        result = prep(resume="SKILLS\nPython\n\nEXPERIENCE\nDid things at a company.\n")
        joined = " ".join(item["area"] for item in result["areas_to_improve"]).lower()
        assert "project" in joined

    def test_a_resume_with_numbers_is_not_told_it_has_none(self, report):
        # The fixture says "12000 requests" nowhere, but it does describe
        # concrete work; the check must not fire on a CV that quantifies.
        result = prep(
            resume=(
                "SKILLS\nPython\n\nEXPERIENCE\n"
                "- Cut p95 latency by 40% and served 12000 requests per day\n"
            )
        )
        joined = " ".join(item["area"] for item in result["areas_to_improve"]).lower()
        assert "no numbers" not in joined

    def test_a_bare_year_does_not_count_as_a_result(self):
        """2023 is a date, not an achievement.

        Treating any digit as evidence of impact would let a CV whose only
        numbers are employment dates pass a check meant to find quantified
        outcomes.
        """
        result = prep(
            resume="SKILLS\nPython\n\nEXPERIENCE\nEngineer at TechCorp (2022-2023)\n"
        )
        joined = " ".join(item["area"] for item in result["areas_to_improve"]).lower()
        assert "number" in joined

    def test_a_role_description_is_not_offered_as_a_skill_to_learn(self):
        """Caught live, not imagined.

        Asked to read "Backend Engineer. Python, FastAPI, Kubernetes and
        PostgreSQL required", the model returned one required skill:
        "backend engineering". The page then advised "Build one small thing
        with Backend before the interview", which is not an action anyone can
        take. Only things the skills vocabulary recognises as a technology
        are proposed.
        """
        result = prep(
            job={
                "title": "Backend Engineer",
                "required_skills": ["backend engineering", "communication"],
                "preferred_skills": [],
                "tech_stack": ["kubernetes"],
                "experience_years": 3,
                "seniority": "mid",
                "role_type": "backend",
                "job_description": "Backend Engineer.",
            },
            gaps=None,
            match=None,
        )
        areas = [item["area"].lower() for item in result["areas_to_improve"]]
        assert not any("backend" in area for area in areas)
        assert not any("communication" in area for area in areas)
        # ...and the real gap is still found, from tech_stack.
        assert any("kubernetes" in area for area in areas)


class TestQuestionsForThem:
    def test_turns_the_top_gap_into_a_question(self, report):
        joined = " ".join(q["question"] for q in report["your_questions_for_them"])
        assert "Pinecone" in joined

    def test_every_question_says_why_to_ask_it(self, report):
        for question in report["your_questions_for_them"]:
            assert question["why_ask"]

    def test_works_without_gaps(self):
        result = prep(gaps=None)
        assert result["your_questions_for_them"]


class TestCompanyQuestions:
    def test_suggests_concrete_research(self, report):
        for question in report["company_questions"]:
            assert question["suggested_research"]

    def test_angle_uses_the_overlap(self, report):
        angle = report["company_questions"][0]["your_angle"]
        assert "LangChain" in angle or "Python" in angle


class TestDifficulty:
    def test_a_strong_match_is_easier(self, agent):
        result = agent._difficulty(
            {"seniority": "junior", "required_skills": ["python"]},
            None,
            {"overall_match": 90.0},
        )
        assert result == EASY

    def test_a_senior_role_with_gaps_is_harder(self, agent):
        result = agent._difficulty(
            {"seniority": "senior", "required_skills": ["a"] * 9},
            GAPS,
            {"overall_match": 40.0},
        )
        assert result == HARD

    def test_the_sample_case_lands_in_between(self, report):
        assert report["interview_difficulty"] in (EASY, MEDIUM, HARD)


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_arguments_at_all(self):
        result = interview_prep_agent.prepare_interview()
        assert result["questions"] == []
        assert result["confidence"] <= 0.3

    def test_empty_resume(self):
        result = prep(resume="")
        assert isinstance(result["questions"], list)

    def test_no_gaps_or_match(self):
        result = prep(gaps=None, match=None)
        assert result["questions"]

    def test_no_job_analysis(self):
        result = interview_prep_agent.prepare_interview({}, {"resume_text": RESUME})
        assert isinstance(result["questions"], list)

    def test_malformed_gap_entries_are_skipped(self):
        result = prep(gaps={"critical_gaps": ["not a dict", {}, None]})
        assert isinstance(result["questions"], list)

    def test_unicode_survives(self):
        assert json.dumps(prep(resume=RESUME + "\n\u2014 caf\u00e9 na\u00efve"))

    def test_is_stateless_across_runs(self):
        assert prep()["questions"] == prep()["questions"]

    def test_a_resume_with_no_headings(self):
        result = prep(resume="I built RAG pipelines with LangChain in Python.")
        assert isinstance(result["questions"], list)


class TestWorkflowIntegration:
    def test_exposes_a_trace_label(self):
        assert interview_prep_agent.label == "Interview Prep Agent"

    def test_reports_the_numbers_the_trace_needs(self, report):
        assert report["question_count"] == len(report["questions"])
        assert report["prep_days"] == len(report["preparation_plan"])

    def test_consumes_gap_detector_output_shape(self, report):
        skills = [q["skill"] for q in report["questions"] if q["category"] == GAP_BASED]
        assert "Pinecone" in skills

    def test_consumes_match_calculator_output_shape(self, report):
        assert report["success_rate_prediction"] > 0


def _quotes(text):
    """Pull the double-quoted resume fragments out of an answer."""
    import re

    return [q for q in re.findall(r'"([^"]+)"', text)]
