"""Tests for the conversational agent.

A chat box is the one place in this app where dishonesty is effortless: the
interface looks equally intelligent whether a model or a regex wrote the
reply. Most of these tests are therefore about labelling rather than content --
that the fallback admits what it is, and that it declines questions it cannot
answer instead of improvising.
"""

from __future__ import annotations

import pytest

from agents.career_chat import (
    FALLBACK_NOTE,
    CareerChatAgent,
    classify,
    format_history,
)
from agents.ollama_handler import LLMError
from tests.conftest import StubLLM

PROFILE = {
    "headline": "This CV reads as a mid backend developer.",
    "primary_role": "backend developer",
    "seniority": "mid",
    "experience_years": 4.0,
    "skills": ["python", "fastapi", "docker"],
    "suggested_roles": ["backend developer", "backend engineer"],
    "improvements": ["No phone number is on the CV."],
}

CONTEXT = "Rahul Medi. Python, FastAPI, Docker. 4 years of experience."


@pytest.fixture
def offline():
    return CareerChatAgent(llm=StubLLM(available=False))


class TestClassify:
    @pytest.mark.parametrize(
        "message,intent",
        [
            ("What skills do I have?", "skills"),
            ("How many years of experience?", "experience"),
            ("What roles should I apply for?", "roles"),
            ("How do I prepare for an interview?", "interview"),
            ("What is weak in my CV?", "improve"),
            ("Summarise my resume", "summary"),
            ("hello", "greeting"),
            ("What is the capital of France?", "unknown"),
        ],
    )
    def test_common_questions_are_recognised(self, message, intent):
        assert classify(message) == intent


class TestHistory:
    def test_an_empty_transcript_says_so(self):
        assert "first message" in format_history([])

    def test_turns_are_labelled_by_speaker(self):
        rendered = format_history([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])
        assert "Candidate: hi" in rendered
        assert "CareerPilot: hello" in rendered

    def test_a_long_conversation_is_trimmed(self):
        turns = [{"role": "user", "content": "q%d" % i} for i in range(40)]
        rendered = format_history(turns)
        assert "q39" in rendered
        assert "q0" not in rendered

    def test_junk_turns_are_skipped_rather_than_crashing(self):
        assert format_history(["not a dict", {"role": "user", "content": ""}])


class TestFallbackLabelling:
    def test_every_scripted_reply_admits_it_is_scripted(self, offline):
        result = offline.reply("what skills do I have?", CONTEXT, [], PROFILE)
        assert result["source"] == "fallback"
        assert FALLBACK_NOTE in result["reply"]

    def test_the_warning_names_the_missing_model(self, offline):
        result = offline.reply("hello", CONTEXT, [], PROFILE)
        assert "no LLM available" in (result["warning"] or "")

    def test_a_question_it_cannot_answer_is_declined_not_improvised(self, offline):
        result = offline.reply(
            "What is the capital of France?", CONTEXT, [], PROFILE
        )
        assert "cannot answer that" in result["reply"]
        assert "ANTHROPIC_API_KEY" in result["reply"]

    def test_with_no_resume_it_asks_for_one(self, offline):
        result = offline.reply("what skills do I have?", "", [], {})
        assert "not got your resume" in result["reply"]
        assert result["source"] == "fallback"


class TestScriptedAnswers:
    def test_skills_are_listed_from_the_profile(self, offline):
        reply = offline.reply("what skills?", CONTEXT, [], PROFILE)["reply"]
        assert "python" in reply and "fastapi" in reply

    def test_no_skills_is_reported_as_a_gap_in_the_document(self, offline):
        profile = dict(PROFILE, skills=[])
        reply = offline.reply("what skills?", CONTEXT, [], profile)["reply"]
        assert "does not name any technology" in reply

    def test_unstated_years_are_refused_not_estimated(self, offline):
        """"None" must never be spoken as "0 years"."""
        profile = dict(PROFILE, experience_years=None)
        reply = offline.reply("how many years?", CONTEXT, [], profile)["reply"]
        assert "never states a number of years" in reply
        assert "0 years" not in reply

    def test_stated_years_are_quoted_back(self, offline):
        reply = offline.reply("how many years?", CONTEXT, [], PROFILE)["reply"]
        assert "4 years" in reply

    def test_roles_point_at_the_discovery_page(self, offline):
        reply = offline.reply("what jobs should I apply for?", CONTEXT, [], PROFILE)
        assert "Discover Jobs" in reply["reply"]

    def test_no_recognisable_role_is_admitted(self, offline):
        profile = dict(PROFILE, suggested_roles=[])
        reply = offline.reply("what jobs?", CONTEXT, [], profile)["reply"]
        assert "cannot suggest titles honestly" in reply

    def test_interview_questions_point_at_the_prep_page(self, offline):
        reply = offline.reply("help me prepare for an interview", CONTEXT, [], PROFILE)
        assert "Interview Prep" in reply["reply"]

    def test_an_empty_message_is_handled(self, offline):
        result = offline.reply("", CONTEXT, [], PROFILE)
        assert result["reply"]
        assert result["suggestions"]


class TestLLMPath:
    def test_a_model_reply_is_returned_and_labelled(self):
        agent = CareerChatAgent(llm=StubLLM(["You look like a backend engineer."]))
        result = agent.reply("summarise me", CONTEXT, [], PROFILE)
        assert result["source"] == "llm"
        assert result["reply"] == "You look like a backend engineer."
        assert FALLBACK_NOTE not in result["reply"]

    def test_the_resume_is_actually_put_in_the_prompt(self):
        stub = StubLLM(["fine"])
        CareerChatAgent(llm=stub).reply("summarise me", CONTEXT, [], PROFILE)
        assert CONTEXT in stub.prompts[0]

    def test_an_empty_model_reply_falls_back_rather_than_showing_blank(self):
        agent = CareerChatAgent(llm=StubLLM(["   "]))
        result = agent.reply("what skills?", CONTEXT, [], PROFILE)
        assert result["source"] == "fallback"
        assert result["reply"].strip()

    def test_a_failing_model_falls_back(self):
        agent = CareerChatAgent(llm=StubLLM(error=LLMError("boom")))
        result = agent.reply("what skills?", CONTEXT, [], PROFILE)
        assert result["source"] == "fallback"
        assert "boom" in (result["warning"] or "")

    def test_chat_never_raises_for_an_absent_model(self, offline):
        assert offline.reply("anything", CONTEXT, [], PROFILE)["reply"]


class TestJobContext:
    """The assistant can be told which advert the user is looking at."""

    ADVERT = "Backend Engineer at Acme. Kubernetes and Go required."

    def test_the_advert_reaches_the_prompt(self):
        stub = StubLLM(["fine"])
        CareerChatAgent(llm=stub).reply(
            "should I apply?", CONTEXT, [], PROFILE, job_context=self.ADVERT
        )
        assert "Kubernetes and Go required" in stub.prompts[0]

    def test_the_resume_is_still_there_alongside_it(self):
        # The advert supplements the CV; it must never replace it, or the
        # assistant would answer about the job and forget who is asking.
        stub = StubLLM(["fine"])
        CareerChatAgent(llm=stub).reply(
            "should I apply?", CONTEXT, [], PROFILE, job_context=self.ADVERT
        )
        assert CONTEXT in stub.prompts[0]

    def test_no_advert_says_so_rather_than_leaving_a_hole(self):
        """An empty slot in the prompt invites the model to invent a job.

        Saying "they have not picked a job yet" is a fact it can act on.
        """
        stub = StubLLM(["fine"])
        CareerChatAgent(llm=stub).reply("summarise me", CONTEXT, [], PROFILE)
        assert "not picked a job" in stub.prompts[0]

    def test_a_very_long_advert_is_clipped(self):
        # Adverts pad with boilerplate, so they get a smaller share of the
        # window than the resume does.
        stub = StubLLM(["fine"])
        CareerChatAgent(llm=stub).reply(
            "should I apply?", CONTEXT, [], PROFILE, job_context="x" * 20000
        )
        assert len(stub.prompts[0]) < 20000

    def test_the_advert_is_optional_for_every_caller(self):
        # The parameter was added last and defaults to empty, so existing
        # call sites keep working unchanged.
        agent = CareerChatAgent(llm=StubLLM(["fine"]))
        assert agent.reply("hello", CONTEXT, [], PROFILE)["reply"]
