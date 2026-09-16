"""Tests for the exception vocabulary and the result envelope.

The value of a base exception class is entirely in whether the things that
actually get raised inherit from it. A hierarchy nobody raises is worse than no
hierarchy, because ``except CareerPilotException`` then looks like a safety net
and catches nothing. Most of this file is therefore about the retrofit rather
than about the new classes.
"""

from __future__ import annotations

import pytest

from agents.application_tracker import (
    ApplicationError,
    UnknownApplicationError,
    UnknownEventError,
    UnknownStatusError,
)
from agents.base_agent import AgentError
from agents.job_analyzer import (
    EmptyJobDescriptionError,
    JobAnalysisError,
    MalformedJobDescriptionError,
)
from agents.job_scraper import ScraperError, UnsafeURLError
from agents.ollama_handler import LLMResponseError, LLMUnavailableError
from agents.ollama_handler import LLMError as HandlerLLMError
from rag.resume_indexer import DocumentParseError, FileValidationError, IndexerError
from utils.error_handling import (
    STATUS_LLM_ERROR,
    STATUS_SUCCESS,
    STATUS_UNEXPECTED_ERROR,
    STATUS_VALIDATION_ERROR,
    AnalysisError,
    CareerPilotException,
    DatabaseError,
    JobScrapingError,
    LLMError,
    RAGIndexingError,
    ValidationError,
    classify,
    envelope,
    guarded,
    safe_call,
)

#: Every exception the project raises on purpose.
EVERY_DELIBERATE_ERROR = [
    IndexerError,
    FileValidationError,
    DocumentParseError,
    AgentError,
    JobAnalysisError,
    EmptyJobDescriptionError,
    MalformedJobDescriptionError,
    ScraperError,
    UnsafeURLError,
    ApplicationError,
    UnknownApplicationError,
    UnknownEventError,
    UnknownStatusError,
    HandlerLLMError,
    LLMUnavailableError,
    LLMResponseError,
]


class TestTheRetrofitIsReal:
    """The base class has to catch what the project actually raises."""

    @pytest.mark.parametrize("error_type", EVERY_DELIBERATE_ERROR)
    def test_every_deliberate_error_is_a_careerpilot_exception(self, error_type):
        assert issubclass(error_type, CareerPilotException)

    def test_catching_the_base_class_catches_a_real_raise(self):
        with pytest.raises(CareerPilotException):
            raise UnsafeURLError("http://169.254.169.254/ is not on the allow-list")

    @pytest.mark.parametrize(
        "error_type, family",
        [
            (IndexerError, RAGIndexingError),
            (FileValidationError, RAGIndexingError),
            (AgentError, AnalysisError),
            (JobAnalysisError, AnalysisError),
            (ScraperError, JobScrapingError),
            (UnsafeURLError, JobScrapingError),
            (ApplicationError, DatabaseError),
            (HandlerLLMError, LLMError),
        ],
    )
    def test_each_error_lands_in_the_right_family(self, error_type, family):
        assert issubclass(error_type, family)


class TestTheRetrofitBrokeNothing:
    """Adding a base must widen what can be caught, never narrow it."""

    @pytest.mark.parametrize(
        "error_type, original_base",
        [
            (IndexerError, RuntimeError),
            (AgentError, RuntimeError),
            (ScraperError, RuntimeError),
            (ApplicationError, RuntimeError),
            (HandlerLLMError, RuntimeError),
            (UnknownApplicationError, KeyError),
            (UnknownEventError, ValueError),
            (UnknownStatusError, ValueError),
        ],
    )
    def test_the_original_base_still_catches_it(self, error_type, original_base):
        assert issubclass(error_type, original_base)

    def test_the_llm_error_name_means_one_class_on_both_import_paths(self):
        """Two classes with this name would make ``except`` depend on the import."""
        assert HandlerLLMError is LLMError

    def test_a_genuine_bug_is_not_swallowed_by_the_base_class(self):
        """AttributeError is a defect, not a refusal. It must stay distinct."""
        assert not issubclass(AttributeError, CareerPilotException)
        with pytest.raises(AttributeError):
            try:
                raise AttributeError("typo")
            except CareerPilotException:  # pragma: no cover - must not catch
                pytest.fail("a bug was caught as a deliberate error")


class TestClassify:
    def test_a_validation_error_is_a_validation_error(self):
        assert classify(ValidationError("too short")) == STATUS_VALIDATION_ERROR

    def test_an_llm_failure_is_an_llm_error(self):
        assert classify(LLMUnavailableError("nothing listening")) == STATUS_LLM_ERROR

    def test_other_deliberate_errors_are_unexpected(self):
        assert classify(ScraperError("feed down")) == STATUS_UNEXPECTED_ERROR

    def test_an_unrelated_exception_still_classifies(self):
        assert classify(ZeroDivisionError()) == STATUS_UNEXPECTED_ERROR


class TestEnvelope:
    def test_success_is_not_degraded(self):
        result = envelope(STATUS_SUCCESS, data={"score": 74}, confidence=0.9)
        assert result["degraded"] is False
        assert result["data"] == {"score": 74}

    def test_any_non_success_is_degraded(self):
        assert envelope(STATUS_LLM_ERROR)["degraded"] is True

    def test_the_timestamp_is_timezone_aware(self):
        """A naive timestamp in a log aggregator is a timestamp in no timezone."""
        assert envelope(STATUS_SUCCESS)["timestamp"].endswith("+00:00")

    def test_absent_fields_are_omitted_rather_than_null(self):
        result = envelope(STATUS_SUCCESS)
        assert "error" not in result
        assert "note" not in result


class TestSafeCall:
    """The answer must always be in one place."""

    def test_a_working_call_reports_success(self):
        result = safe_call("demo", lambda: {"ok": True})
        assert result["status"] == STATUS_SUCCESS
        assert result["data"] == {"ok": True}

    def test_a_real_confidence_is_carried_through_not_replaced(self):
        """Agents earn a confidence figure; a constant would discard it."""
        result = safe_call("demo", lambda: {"confidence": 0.42})
        assert result["confidence"] == 0.42

    def test_a_percentage_confidence_is_normalised(self):
        result = safe_call("demo", lambda: {"confidence": 74})
        assert result["confidence"] == 0.74

    def test_a_boolean_is_not_mistaken_for_a_confidence(self):
        result = safe_call("demo", lambda: {"confidence": True})
        assert result["confidence"] == 1.0

    def test_the_fallback_result_lands_in_data_not_a_second_key(self):
        def boom():
            raise LLMUnavailableError("no backend")

        result = safe_call("demo", boom, fallback=lambda: {"keyword": "path"})
        assert result["status"] == STATUS_LLM_ERROR
        assert result["data"] == {"keyword": "path"}
        assert "fallback" not in result
        assert result["degraded"] is True

    def test_a_fallback_that_also_fails_does_not_mask_the_original(self):
        def boom():
            raise LLMUnavailableError("no backend")

        def worse():
            raise RuntimeError("the fallback is broken too")

        result = safe_call("demo", boom, fallback=worse)
        assert result["status"] == STATUS_LLM_ERROR
        assert "no backend" in result["error"]
        assert result["data"] is None

    def test_an_unexpected_error_is_caught_but_labelled_differently(self):
        def boom():
            raise ZeroDivisionError("nope")

        result = safe_call("demo", boom)
        assert result["status"] == STATUS_UNEXPECTED_ERROR
        assert result["confidence"] == 0.0

    def test_nothing_escapes(self):
        for raiser in (ValidationError, LLMError, ScraperError, KeyError, TypeError):
            def boom(exc=raiser):
                raise exc("x")

            assert safe_call("demo", boom)["status"] != STATUS_SUCCESS


class TestGuarded:
    def test_the_decorator_finds_the_named_fallback(self):
        class Agent:
            def _fallback(self):
                return {"source": "keywords"}

            @guarded("analyse", fallback_attr="_fallback")
            def analyse(self):
                raise LLMUnavailableError("down")

        result = Agent().analyse()
        assert result["data"] == {"source": "keywords"}
        assert result["status"] == STATUS_LLM_ERROR

    def test_a_missing_fallback_attribute_is_not_itself_an_error(self):
        class Agent:
            @guarded("analyse", fallback_attr="_nope")
            def analyse(self):
                raise LLMUnavailableError("down")

        assert Agent().analyse()["data"] is None
