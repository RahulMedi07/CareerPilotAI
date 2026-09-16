"""Feedback on a practice interview answer.

The behaviour under test is mostly about restraint: what the coach refuses to
say when nothing has read the answer. A score is the most persuasive thing this
app can print and the cheapest thing to fabricate, so the tests below spend
more effort proving it stays absent than proving it appears.
"""

from __future__ import annotations

import pytest

from agents.answer_coach import (
    MODEL_FAILED_NOTE,
    NO_MODEL_NOTE,
    AnswerCoachAgent,
    coverage,
    expected_terms,
    observations,
)
from agents.ollama_handler import LLMError
from tests.conftest import StubLLM

STRONG = (
    "I built a RAG pipeline in Python with FastAPI and ChromaDB. I cut p95 "
    "latency by 40% by batching the embedding calls, and it now serves about "
    "12k requests a day without falling over."
)

WEAK = "We sort of did some AI stuff, I guess. It was good."


class TestExpectedTerms:
    def test_the_named_skill_is_always_expected(self):
        terms = expected_terms("Tell me about your work.", "kubernetes")
        assert "kubernetes" in terms

    def test_technologies_named_in_the_question_are_expected(self):
        terms = expected_terms("How did you use Docker and PostgreSQL?", "")
        assert "docker" in terms
        assert "postgresql" in terms

    def test_it_does_not_invent_terms_the_question_never_mentioned(self):
        # A gap the question never asked about is not a gap. Widening the
        # expected set would manufacture criticism out of nothing.
        terms = expected_terms("Tell me about a difficult week.", "")
        assert terms == []

    def test_duplicates_are_collapsed(self):
        terms = expected_terms("Talk to me about python.", "python")
        assert terms.count("python") == 1


class TestCoverage:
    def test_a_mentioned_term_counts_as_covered(self):
        split = coverage(STRONG, ["fastapi", "rag"])
        assert set(split["covered"]) == {"fastapi", "rag"}
        assert split["missing"] == []

    def test_an_unmentioned_term_is_missing(self):
        split = coverage(WEAK, ["rag"])
        assert split["missing"] == ["rag"]
        assert split["covered"] == []

    def test_it_matches_whole_words_only(self):
        # "go" must not match "going", or every answer would appear to cover Go.
        split = coverage("I am going to the shops.", ["go"])
        assert split["missing"] == ["go"]


class TestObservations:
    def test_a_short_answer_is_called_short(self):
        notes = " ".join(observations("Yes I did that.", []))
        assert "words" in notes
        assert "nothing to say" in notes

    def test_a_concrete_number_is_noticed(self):
        notes = " ".join(observations(STRONG, []))
        assert "concrete number" in notes

    def test_its_absence_is_also_noticed(self):
        notes = " ".join(observations(WEAK, []))
        assert "no measurable result" in notes

    def test_hedging_is_quoted_back(self):
        notes = " ".join(observations(WEAK, []))
        assert "sort of" in notes

    def test_an_answer_written_only_as_we_is_flagged(self):
        notes = " ".join(observations("We shipped the service and we scaled it.", []))
        assert "'we'" in notes

    def test_every_observation_is_checkable_against_the_text(self):
        # None of these may be an opinion. The wording is the contract: each
        # one describes something the candidate can verify by re-reading.
        for note in observations(STRONG, ["rag"]):
            assert not note.startswith("Good")
            assert "excellent" not in note.lower()
            assert "/10" not in note


class TestNoModel:
    @pytest.fixture()
    def agent(self):
        agent = AnswerCoachAgent()
        agent._client = StubLLM(available=False)
        return agent

    def test_it_refuses_to_score_when_nothing_read_the_answer(self, agent):
        result = agent.evaluate("Walk me through your RAG project.", STRONG, "rag")

        assert result["score"] is None
        assert result["source"] == "fallback"
        assert result["note"] == NO_MODEL_NOTE

    def test_it_invents_no_praise_for_a_weak_answer(self, agent):
        result = agent.evaluate("Walk me through your RAG project.", WEAK, "rag")

        assert result["strengths"] == []
        assert result["score"] is None
        assert "rag" in result["missing"]

    def test_an_empty_answer_asks_for_one_rather_than_judging_it(self, agent):
        result = agent.evaluate("Anything at all?", "   ", "python")
        assert result["score"] is None
        assert result["observations"] == []
        assert "Write an answer first" in result["note"]


class TestAConfiguredModelThatFails:
    """A spent quota must not be reported as a missing key.

    Both paths end in the same unscored fallback, so the only thing telling
    the two apart is the note - and they need opposite actions: add a key, or
    wait for the daily limit to reset.
    """

    def _agent(self, error):
        agent = AnswerCoachAgent()
        agent._client = StubLLM(available=True, error=error)
        return agent

    def test_a_rate_limit_says_unreachable_not_unconfigured(self):
        agent = self._agent(LLMError("Gemini rate limit reached (429)"))
        result = agent.evaluate("Walk me through your RAG project.", STRONG, "rag")

        assert result["score"] is None
        assert result["source"] == "fallback"
        assert result["note"] == MODEL_FAILED_NOTE
        assert result["note"] != NO_MODEL_NOTE

    def test_the_note_points_at_the_quota_rather_than_the_key(self):
        agent = self._agent(LLMError("Gemini rate limit reached (429)"))
        note = agent.evaluate("Q?", STRONG, "rag")["note"]

        assert "429" in note
        assert "not configured" not in note

    def test_observations_still_come_back_when_the_model_fails(self):
        # The deterministic half does not depend on the model, so losing the
        # model must not cost the user the part that still works.
        agent = self._agent(LLMError("boom"))
        result = agent.evaluate("Walk me through your RAG project.", WEAK, "rag")

        assert result["observations"]
        assert "rag" in result["missing"]


class TestModelPath:
    def _agent(self, payload: str) -> AnswerCoachAgent:
        agent = AnswerCoachAgent()
        agent._client = StubLLM([payload])
        return agent

    def test_a_valid_score_survives(self):
        agent = self._agent(
            '{"score": 8, "verdict": "Ready.", "strengths": ["names a metric"],'
            ' "gaps": [], "improved_opening": "Start with the outcome."}'
        )
        result = agent.evaluate("Walk me through your RAG project.", STRONG, "rag")

        assert result["score"] == 8
        assert result["source"] == "llm"
        assert result["strengths"] == ["names a metric"]

    @pytest.mark.parametrize("bad", [0, 11, -3, 99])
    def test_an_out_of_range_score_is_dropped_not_clamped(self, bad):
        # Clamping 99 to 10 would report a perfect answer on the strength of a
        # model's formatting mistake. Dropping it says "not scored", which is
        # true.
        agent = self._agent('{"score": %d, "strengths": [], "gaps": []}' % bad)
        result = agent.evaluate("Q?", STRONG, "rag")
        assert result["score"] is None

    def test_a_non_numeric_score_is_dropped(self):
        agent = self._agent('{"score": "eight", "strengths": [], "gaps": []}')
        assert self._run(agent)["score"] is None

    def test_a_boolean_score_is_dropped(self):
        # `True` is an int in Python and would otherwise round to 1/10.
        agent = self._agent('{"score": true, "strengths": [], "gaps": []}')
        assert self._run(agent)["score"] is None

    def test_unparseable_output_falls_back_rather_than_erroring(self):
        agent = self._agent("I am afraid I cannot do that.")
        result = self._run(agent)
        assert result["source"] == "fallback"
        assert result["score"] is None

    def test_observations_are_present_on_the_model_path_too(self):
        # The checkable facts do not stop being true because a model also had
        # an opinion.
        agent = self._agent('{"score": 6, "strengths": [], "gaps": []}')
        assert self._run(agent)["observations"]

    def _run(self, agent: AnswerCoachAgent):
        return agent.evaluate("Walk me through your RAG project.", STRONG, "rag")
