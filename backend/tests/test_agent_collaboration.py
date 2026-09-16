"""Tests for ``agents.agent_collaboration``.

The collaboration layer is a set of structured delegations with a recorded
transcript. These tests pin two things: that the transcript honestly records
what happened, and that one specialist falling over does not take the run
down with it.
"""

from __future__ import annotations

from agents.agent_collaboration import (
    ASKED_FAILED,
    ASKED_OK,
    ORCHESTRATOR,
    AgentCollaboration,
)


class StubGaps:
    def __init__(self, report=None):
        self.report = report if report is not None else {
            "critical_gaps": [
                {"skill": "Docker", "learning_time_days": 10},
                {"skill": "Pinecone", "learning_time_days": 2},
            ],
            "critical_count": 2,
            "blocking_learning_days": 12,
        }
        self.calls = 0

    def detect_gaps(self, *args, **kwargs):
        self.calls += 1
        return self.report


class StubOptimizer:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "improvements": [{"what": "x"}],
            "keywords_to_add": ["Python"],
            "keywords_blocked_by_gaps": ["Docker"],
            "high_impact_count": 1,
        }
        self.seen_gaps = None

    def optimize_resume(self, resume_data, job_analysis, gaps=None, match_data=None):
        self.seen_gaps = gaps
        return self.result


class StubInterview:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "questions": [{"q": "a"}],
            "question_count": 1,
            "gap_question_count": 1,
            "interview_difficulty": "hard",
        }

    def prepare_interview(self, *args, **kwargs):
        return self.result


class StubLearning:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "days": [{"day": 1}],
            "total_days": 1,
            "skills": ["Docker"],
            "fits": True,
            "summary": "one day",
        }
        self.seen_days = None

    def create_learning_path(self, gaps, available_days=14, critical_only=True):
        self.seen_days = available_days
        return self.result


class Exploding:
    """A specialist that fails, to prove the orchestrator survives it."""

    def detect_gaps(self, *args, **kwargs):
        raise RuntimeError("detector is down")

    def optimize_resume(self, *args, **kwargs):
        raise RuntimeError("optimizer is down")

    def prepare_interview(self, *args, **kwargs):
        raise RuntimeError("interview is down")

    def create_learning_path(self, *args, **kwargs):
        raise RuntimeError("planner is down")


def build(**overrides):
    parts = {
        "gaps_agent": StubGaps(),
        "optimizer": StubOptimizer(),
        "interview": StubInterview(),
        "learning": StubLearning(),
    }
    parts.update(overrides)
    return AgentCollaboration(**parts), parts


MATCH = {"overall_match": 74.0, "matched_skills": [], "missing_skills": []}


class TestTranscript:
    def test_each_delegation_is_recorded_once(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        assert len(collab.transcript) == 1

    def test_the_record_names_both_ends_of_the_exchange(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        entry = collab.transcript[0]
        assert entry["from"] == ORCHESTRATOR
        assert entry["to"]

    def test_the_record_carries_a_question_and_an_answer(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        entry = collab.transcript[0]
        assert entry["question"]
        assert entry["answer"]

    def test_the_steps_are_numbered_in_the_order_they_happened(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        collab.ask_interview_prep({}, MATCH)
        assert [entry["step"] for entry in collab.transcript] == [1, 2]

    def test_a_successful_exchange_is_marked_as_answered(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        assert collab.transcript[0]["status"] == ASKED_OK

    def test_every_exchange_is_timed(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        assert collab.transcript[0]["duration_ms"] >= 0

    def test_clearing_empties_the_transcript(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        collab.clear()
        assert collab.transcript == []


class TestAnswersAreHonest:
    def test_the_gap_answer_names_the_gaps_it_found(self):
        collab, _ = build()
        collab.ask_gap_detector(MATCH, {}, {})
        answer = collab.transcript[0]["answer"]
        assert "Docker" in answer and "Pinecone" in answer

    def test_the_optimizer_answer_admits_what_it_refused_to_add(self):
        """The refusal is the interesting half of the answer."""
        collab, _ = build()
        collab.ask_resume_optimizer({"critical_gaps": []}, {}, {})
        answer = collab.transcript[0]["answer"]
        assert "Docker" in answer

    def test_the_question_to_the_optimizer_asks_for_nothing_untrue(self):
        collab, _ = build()
        collab.ask_resume_optimizer({"critical_gaps": []}, {}, {})
        assert "untrue" in collab.transcript[0]["question"]


class TestFailuresAreSurvivable:
    def test_a_failing_detector_does_not_raise(self):
        collab, _ = build(gaps_agent=Exploding())
        assert collab.ask_gap_detector(MATCH, {}, {}) == {}

    def test_a_failing_optimizer_does_not_raise(self):
        collab, _ = build(optimizer=Exploding())
        assert collab.ask_resume_optimizer({}, {}, {}) == {}

    def test_a_failing_interview_agent_does_not_raise(self):
        collab, _ = build(interview=Exploding())
        assert collab.ask_interview_prep({}, MATCH) == {}

    def test_a_failing_planner_does_not_raise(self):
        collab, _ = build(learning=Exploding())
        assert collab.ask_learning_path_agent({}) == {}

    def test_a_failure_is_recorded_rather_than_hidden(self):
        collab, _ = build(gaps_agent=Exploding())
        collab.ask_gap_detector(MATCH, {}, {})
        assert collab.transcript[0]["status"] == ASKED_FAILED

    def test_the_recorded_failure_says_what_went_wrong(self):
        collab, _ = build(gaps_agent=Exploding())
        collab.ask_gap_detector(MATCH, {}, {})
        assert "down" in collab.transcript[0]["answer"]

    def test_one_failure_does_not_stop_the_others(self):
        collab, _ = build(gaps_agent=Exploding())
        collab.ask_gap_detector(MATCH, {}, {})
        assert collab.ask_interview_prep({}, MATCH)
        assert collab.transcript[1]["status"] == ASKED_OK


class TestHandover:
    def test_the_optimizer_receives_the_gaps_the_detector_found(self):
        """Without this the optimizer cannot know what it must not claim."""
        optimizer = StubOptimizer()
        collab, _ = build(optimizer=optimizer)
        report = {"critical_gaps": [{"skill": "Docker"}]}
        collab.ask_resume_optimizer(report, {}, {})
        assert optimizer.seen_gaps is not None

    def test_the_planner_is_given_the_window_it_was_asked_for(self):
        learning = StubLearning()
        collab, _ = build(learning=learning)
        collab.ask_learning_path_agent({"critical_gaps": []}, available_time_days=30)
        assert learning.seen_days == 30

    def test_a_bare_list_of_gaps_is_accepted_as_well_as_a_report(self):
        collab, _ = build()
        as_list = collab.ask_learning_path_agent([{"skill": "Docker"}])
        as_report = collab.ask_learning_path_agent({"critical_gaps": [{"skill": "Docker"}]})
        assert as_list and as_report


class TestDefaults:
    def test_it_wires_itself_to_the_real_agents_when_given_none(self):
        collab = AgentCollaboration()
        assert collab.gaps_agent is not None
        assert collab.optimizer is not None
        assert collab.interview is not None
        assert collab.learning is not None
