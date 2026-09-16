"""Tests for boundary coercion of agent inputs.

The point of `utils.validation` is that a *shape* mistake never ends a run.
These tests are written from that promise rather than from the implementation:
each one names a wrong shape a caller could plausibly pass and asserts the
result is usable, not that a particular branch was taken.
"""

from __future__ import annotations

import math

import pytest

from utils.validation import as_dict, as_float, as_int, as_list, first_dict


class TestAsDict:
    """Anything at all becomes a dictionary."""

    @pytest.mark.parametrize(
        "value",
        [None, "a string", 123, 4.5, [], ["a", "b"], set(), True, (1, 2), object()],
    )
    def test_anything_that_is_not_a_mapping_becomes_empty(self, value):
        assert as_dict(value) == {}

    def test_a_dict_survives_unchanged(self):
        assert as_dict({"skills": ["python"]}) == {"skills": ["python"]}

    def test_the_original_is_not_aliased(self):
        """A caller must not be able to mutate its own argument through us."""
        original = {"skills": ["python"]}
        copy = as_dict(original)
        copy["skills"] = ["java"]
        assert original["skills"] == ["python"]

    def test_a_mapping_that_is_not_a_dict_is_still_read(self):
        from collections import OrderedDict

        assert as_dict(OrderedDict([("a", 1)])) == {"a": 1}

    def test_a_hostile_mapping_degrades_rather_than_raises(self):
        class Hostile:
            def keys(self):
                raise RuntimeError("no")

            def __getitem__(self, key):
                raise RuntimeError("no")

        assert as_dict(Hostile()) == {}


class TestAsList:
    """Wrong-shaped sequences become lists without losing meaning."""

    @pytest.mark.parametrize("value", [None, "", "   ", 123, 4.5, {}, True])
    def test_nothing_useful_becomes_empty(self, value):
        assert as_list(value) == []

    def test_a_bare_string_is_one_item_not_many_characters(self):
        """`skills="python"` means one skill, not seven letters."""
        assert as_list("python") == ["python"]

    def test_a_list_survives(self):
        assert as_list(["python", "sql"]) == ["python", "sql"]

    def test_a_tuple_becomes_a_list(self):
        assert as_list(("python", "sql")) == ["python", "sql"]

    def test_a_set_becomes_a_list(self):
        assert sorted(as_list({"python", "sql"})) == ["python", "sql"]


class TestAsFloat:
    """Numbers that arrive as text must not raise inside a score calculation."""

    @pytest.mark.parametrize(
        "value,expected",
        [("78", 78.0), ("78.5", 78.5), (78, 78.0), (78.5, 78.5), (" 78 ", 78.0)],
    )
    def test_readable_numbers_are_read(self, value, expected):
        assert as_float(value) == expected

    @pytest.mark.parametrize("value", [None, "abc", "", [], {}, object()])
    def test_unreadable_values_fall_back(self, value):
        assert as_float(value, default=-1.0) == -1.0

    def test_nan_never_escapes(self):
        """NaN poisons every comparison downstream, so it is not a valid score."""
        assert as_float(float("nan"), default=0.0) == 0.0
        assert not math.isnan(as_float(float("nan")))

    def test_a_boolean_is_not_a_number(self):
        """`True` is an int in Python, but nobody ever means 1.0 by it."""
        assert as_float(True, default=9.0) == 9.0


class TestAsInt:
    @pytest.mark.parametrize("value,expected", [("7", 7), (7, 7), (7.9, 7)])
    def test_readable_numbers_are_read(self, value, expected):
        assert as_int(value) == expected

    @pytest.mark.parametrize("value", [None, "abc", [], {}, True])
    def test_unreadable_values_fall_back(self, value):
        assert as_int(value, default=-1) == -1


class TestFirstDict:
    def test_picks_the_first_non_empty_dict(self):
        assert first_dict(None, {}, "x", {"a": 1}, {"b": 2}) == {"a": 1}

    def test_returns_none_when_nothing_qualifies(self):
        assert first_dict(None, {}, "x", 5, []) is None
