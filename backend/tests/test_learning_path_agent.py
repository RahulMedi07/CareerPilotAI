"""Tests for ``agents.learning_path_agent``.

The agent's value is as much in what it refuses to do as in what it produces:
it will not invent a tutorial URL, and it will not hand back a schedule that
nobody could keep. Both refusals are pinned here.
"""

from __future__ import annotations

from agents.learning_path_agent import (
    COMFORTABLE_HOURS,
    MAX_SUSTAINABLE_HOURS,
    PART_TIME_HOURS_PER_DAY,
    LearningPathAgent,
    learning_path_agent,
)


def gap(skill, days, importance="CRITICAL"):
    return {"skill": skill, "learning_time_days": days, "importance": importance}


class TestFindBestResources:
    def test_a_known_skill_gets_its_official_documentation(self):
        found = learning_path_agent.find_best_resources("Docker")
        assert found["official_docs"].startswith("http")

    def test_it_invents_nothing_for_a_skill_it_does_not_know(self):
        """The failure mode to avoid is a confident, fabricated URL."""
        found = learning_path_agent.find_best_resources("Fortran")
        assert not found["official_docs"]
        assert "official_docs" in found["missing"]

    def test_an_unknown_skill_is_given_a_search_to_run_instead(self):
        found = learning_path_agent.find_best_resources("Fortran")
        assert "Fortran" in found["search_for"]

    def test_video_and_blog_links_are_never_produced(self):
        """No verified table backs these, so no URL is offered for them."""
        found = learning_path_agent.find_best_resources("Docker")
        assert "youtube" in found["unverified_categories"]
        assert "articles" in found["unverified_categories"]

    def test_nothing_it_returns_is_an_unchecked_link(self):
        for skill in ("Docker", "FastAPI", "Pinecone", "LangChain", "Fortran"):
            found = learning_path_agent.find_best_resources(skill)
            for value in found.values():
                if isinstance(value, str) and value.startswith("http"):
                    assert "youtube.com" not in value
                    assert "medium.com" not in value


class TestEstimateEffort:
    def test_a_comfortable_window_is_accepted(self):
        effort = learning_path_agent.estimate_effort("Docker", 14, learning_days=10)
        assert effort["fits"] is True
        assert effort["hours_per_day"] <= COMFORTABLE_HOURS

    def test_an_impossible_window_is_refused_rather_than_rounded_down(self):
        effort = learning_path_agent.estimate_effort("Docker", 2, learning_days=10)
        assert effort["fits"] is False

    def test_the_refusal_says_how_many_hours_it_would_have_taken(self):
        effort = learning_path_agent.estimate_effort("Docker", 2, learning_days=10)
        # There is no workable daily figure, so hours_per_day is left empty
        # rather than quoting a number nobody could keep to.
        assert effort["hours_per_day"] is None
        assert effort["required_hours_per_day"] > MAX_SUSTAINABLE_HOURS
        assert "10" in effort["reason"]

    def test_a_demanding_but_possible_window_warns_without_refusing(self):
        effort = learning_path_agent.estimate_effort("Docker", 4, learning_days=10)
        assert effort["fits"] is True
        assert effort.get("warning")

    def test_a_bare_skill_name_works_as_well_as_a_gap_dict(self):
        from_name = learning_path_agent.estimate_effort("Docker", 14, learning_days=10)
        from_dict = learning_path_agent.estimate_effort(gap("Docker", 10), 14)
        assert from_name["hours_per_day"] == from_dict["hours_per_day"]

    def test_an_uncosted_skill_is_not_assumed_to_take_one_day(self):
        """Assuming a day made this agree to almost any window.

        CI/CD in two days came back as a comfortable two hours, when the gap
        detector's own table puts it at ten days.
        """
        effort = learning_path_agent.estimate_effort("CI/CD", 2)
        assert effort["fits"] is False
        assert effort["days_needed"] == 10

    def test_an_unknown_skill_falls_back_to_the_documented_default(self):
        effort = learning_path_agent.estimate_effort("Fortran", 60)
        assert effort["days_needed"] == 30

    def test_no_days_available_is_refused_not_divided_by_zero(self):
        effort = learning_path_agent.estimate_effort("Docker", 0, learning_days=10)
        assert effort["fits"] is False


class TestCreateLearningPath:
    def test_it_schedules_every_critical_gap(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Pinecone", 2), gap("FastAPI", 7)], available_days=14
        )
        assert plan["fits"] is True
        assert set(plan["skills"]) == {"Pinecone", "FastAPI"}

    def test_it_does_not_pad_the_plan_out_to_fill_the_window(self):
        """Nine days of study spread over fourteen is four days of filler.

        A plan padded with invented "in more depth" days is one you stop
        believing partway through.
        """
        plan = learning_path_agent.create_learning_path(
            [gap("Pinecone", 2), gap("FastAPI", 7)], available_days=14
        )
        assert plan["total_days"] == 9
        assert plan["days_spare"] == 5
        assert plan["daily_commitment_hours"] == PART_TIME_HOURS_PER_DAY

    def test_the_spare_days_are_named_rather_than_silently_dropped(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Pinecone", 2)], available_days=14
        )
        assert "12" in plan["slack_note"]

    def test_the_days_are_numbered_from_one_without_gaps(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Pinecone", 2), gap("FastAPI", 7)], available_days=14
        )
        numbers = [day["day"] for day in plan["days"]]
        assert numbers == list(range(1, len(numbers) + 1))

    def test_shorter_skills_are_scheduled_first(self):
        """Finishing something in week one is what keeps week two alive."""
        plan = learning_path_agent.create_learning_path(
            [gap("CI/CD", 10), gap("Pinecone", 2)], available_days=20
        )
        assert plan["days"][0]["skill"] == "Pinecone"

    def test_every_day_carries_something_to_do(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Docker", 5)], available_days=10
        )
        for day in plan["days"]:
            assert day["focus"]
            assert day["time_hours"] > 0

    def test_an_impossible_window_is_refused(self):
        plan = learning_path_agent.create_learning_path(
            [gap("CI/CD", 10), gap("LangGraph", 5), gap("Pinecone", 2)],
            available_days=1,
        )
        assert plan["fits"] is False

    def test_a_refusal_still_says_what_would_have_fitted(self):
        """Returning nothing is less useful than returning the reachable part."""
        plan = learning_path_agent.create_learning_path(
            [gap("CI/CD", 10), gap("LangGraph", 5), gap("Pinecone", 2)],
            available_days=2,
        )
        assert plan["fits"] is False
        assert "Pinecone" in plan["skills_that_would_fit"]
        assert "CI/CD" in plan["skills_out_of_reach"]

    def test_no_gaps_produces_no_plan_and_says_why(self):
        plan = learning_path_agent.create_learning_path([], available_days=14)
        assert plan["days"] == []
        assert plan["reason"]

    def test_no_days_produces_no_plan_and_says_why(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Docker", 5)], available_days=0
        )
        assert plan["days"] == []
        assert plan["reason"]

    def test_nice_to_haves_are_left_out_by_default(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Docker", 5), gap("Kafka", 5, "NICE_TO_HAVE")], available_days=20
        )
        assert plan["skills"] == ["Docker"]

    def test_nice_to_haves_can_be_asked_for(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Docker", 5), gap("Kafka", 5, "NICE_TO_HAVE")],
            available_days=20,
            critical_only=False,
        )
        assert set(plan["skills"]) == {"Docker", "Kafka"}

    def test_a_tight_fit_is_labelled_as_having_no_slack(self):
        plan = learning_path_agent.create_learning_path(
            [gap("CI/CD", 10), gap("LangGraph", 5), gap("Pinecone", 2)],
            available_days=14,
        )
        assert plan["fits"] is True
        assert plan["compressed"] is True
        assert plan["note"]

    def test_the_summary_agrees_with_the_number_of_days_scheduled(self):
        plan = learning_path_agent.create_learning_path(
            [gap("Pinecone", 2), gap("FastAPI", 7)], available_days=14
        )
        assert str(plan["total_days"]) in plan["summary"]
        assert plan["total_days"] == len(plan["days"])


class TestSingleton:
    def test_the_module_singleton_is_the_documented_class(self):
        assert isinstance(learning_path_agent, LearningPathAgent)
