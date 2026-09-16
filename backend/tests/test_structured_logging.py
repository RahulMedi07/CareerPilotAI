"""Tests for structured logging.

Three of these exist because the obvious implementation of ``StructuredLogger``
fails them: it replaces the standard logger rather than wrapping it, it attaches
handlers per instance, and it serialises with a bare ``json.dumps``. Each
failure shows up only on an error path, which is the worst place to find one.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

from utils.error_handling import LLMError
from utils.logger import StructuredLogger, get_logger, observed


@pytest.fixture
def entries(caplog):
    caplog.set_level(logging.DEBUG)

    def read():
        return [
            json.loads(record.getMessage())
            for record in caplog.records
            if record.getMessage().startswith("{")
        ]

    return read


class TestItIsStillALogger:
    """The wrapper must not take away what 24 modules already use."""

    @pytest.mark.parametrize(
        "level", ["debug", "info", "warning", "error", "critical", "exception"]
    )
    def test_the_ordinary_methods_still_exist(self, level):
        assert callable(getattr(StructuredLogger(__name__), level))

    def test_percent_style_arguments_still_work(self, caplog):
        caplog.set_level(logging.INFO)
        StructuredLogger("demo").info("scored %d/%d", 74, 100)
        assert "scored 74/100" in caplog.text

    def test_it_wraps_the_same_underlying_logger(self):
        assert StructuredLogger("demo").logger is get_logger("demo")


class TestHandlersAreNotDuplicated:
    """``getLogger(name)`` returns one object; adding handlers to it accumulates."""

    def test_constructing_twice_does_not_double_the_handlers(self):
        name = "duplicate.check"
        before = len(logging.getLogger(name).handlers)
        StructuredLogger(name)
        StructuredLogger(name)
        StructuredLogger(name)
        assert len(logging.getLogger(name).handlers) == before

    def test_a_message_is_recorded_once(self, caplog):
        caplog.set_level(logging.INFO)
        name = "single.emission"
        StructuredLogger(name)
        StructuredLogger(name).info("only once")
        assert caplog.text.count("only once") == 1


class TestLogOperation:
    def test_it_emits_parseable_json(self, entries):
        StructuredLogger("demo").log_operation(
            "analyze_job", "started", {"jd_length": 593}
        )
        entry = entries()[-1]
        assert entry["operation"] == "analyze_job"
        assert entry["status"] == "started"
        assert entry["details"] == {"jd_length": 593}

    def test_details_are_optional(self, entries):
        StructuredLogger("demo").log_operation("analyze_job", "completed")
        assert entries()[-1]["details"] == {}

    def test_the_timestamp_is_timezone_aware(self, entries):
        StructuredLogger("demo").log_operation("x", "y")
        assert entries()[-1]["timestamp"].endswith("+00:00")


class TestLogError:
    def test_the_type_and_message_are_separate_fields(self, entries):
        StructuredLogger("demo").log_error(
            "index_resume", ValueError("bad page"), {"pages": 3}
        )
        entry = entries()[-1]
        assert entry["error_type"] == "ValueError"
        assert entry["error_message"] == "bad page"
        assert entry["context"] == {"pages": 3}


class TestSerialisingCannotRaise:
    """Logging inside ``except`` must never replace the error it is reporting."""

    @pytest.mark.parametrize(
        "value",
        [
            datetime(2026, 8, 31),
            Path("/tmp/resume.pdf"),
            {"a", "b"},
            object(),
            {1, 2},
        ],
    )
    def test_values_json_cannot_encode_are_stringified(self, value, entries):
        StructuredLogger("demo").log_operation("x", "y", {"value": value})
        assert isinstance(entries()[-1]["details"]["value"], str)

    def test_an_unserialisable_context_does_not_hide_the_real_error(self, entries):
        original = ValueError("the actual problem")
        StructuredLogger("demo").log_error("x", original, {"obj": object()})
        assert entries()[-1]["error_message"] == "the actual problem"


class TestObserved:
    """The decorator must be invisible to callers: that is the whole design."""

    def test_the_return_value_is_untouched(self):
        @observed("demo")
        def f():
            return {"match_score": 73.6, "confidence": 0.82}

        assert f() == {"match_score": 73.6, "confidence": 0.82}

    def test_it_does_not_wrap_the_result_in_an_envelope(self):
        @observed("demo")
        def f():
            return {"match_score": 73.6}

        assert "data" not in f() and "status" not in f()

    def test_the_agents_real_confidence_survives(self):
        """A hard-coded 0.95 would be wrong exactly when a fallback was used."""

        @observed("demo")
        def f():
            return {"confidence": 0.31}

        assert f()["confidence"] == 0.31

    def test_the_exception_is_re_raised_not_swallowed(self):
        @observed("demo")
        def f():
            raise LLMError("no backend")

        with pytest.raises(LLMError, match="no backend"):
            f()

    def test_a_failure_is_logged_before_it_propagates(self, entries):
        @observed("index_resume")
        def f():
            raise LLMError("no backend")

        with pytest.raises(LLMError):
            f()
        entry = entries()[-1]
        assert entry["operation"] == "index_resume"
        assert entry["error_type"] == "LLMError"

    def test_arguments_are_passed_through(self):
        @observed("demo")
        def f(a, b, *, c=0):
            return a + b + c

        assert f(1, 2, c=3) == 6

    def test_the_wrapped_function_keeps_its_identity(self):
        @observed("demo")
        def analyze(job_description):
            """Docstring preserved."""
            return {}

        assert analyze.__name__ == "analyze"
        assert analyze.__doc__ == "Docstring preserved."

    @pytest.mark.parametrize(
        "module,attr,operation",
        [
            ("agents.job_analyzer", "analyze", "analyze_job"),
            ("agents.match_calculator", "calculate_match", "calculate_match"),
            ("agents.gap_detector", "detect_gaps", "detect_gaps"),
            ("agents.resume_optimizer", "optimize_resume", "optimize_resume"),
            ("agents.interview_prep", "prepare_interview", "prepare_interview"),
            ("agents.job_scraper", "search", "search_jobs"),
            ("agents.application_tracker", "create_application", "create_application"),
        ],
    )
    def test_every_agent_entry_point_is_instrumented(self, module, attr, operation):
        import importlib

        mod = sys.modules.get(module) or importlib.import_module(module)
        classes = [
            obj
            for obj in vars(mod).values()
            if isinstance(obj, type) and hasattr(obj, attr) and obj.__module__ == module
        ]
        assert any(
            getattr(getattr(cls, attr), "__wrapped__", None) is not None
            for cls in classes
        ), "{0}.{1} is not observed".format(module, attr)
