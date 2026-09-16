"""Tests for retry with exponential backoff.

Written around the question the module exists to answer: *which* failures is
retrying worth anything for. A retry loop that fires on everything is not more
robust than one that fires on transient faults only - it is slower at
delivering the same failure, and it does that while a user waits.

No test here really sleeps; the sleep function is injected and recorded.
"""

from __future__ import annotations

import pytest

from utils.retry_handler import MAX_BACKOFF_SECONDS, retry_with_backoff


class Recorder:
    """Stands in for ``time.sleep`` and remembers what it was asked to wait."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


class Flaky:
    """Fails ``failures`` times, then succeeds."""

    def __init__(self, failures, error=ConnectionError):
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("attempt %d" % self.calls)
        return "ok"


class TestItRetriesWhatIsWorthRetrying:
    def test_a_transient_failure_is_retried_and_succeeds(self):
        flaky = Flaky(failures=2)
        sleeper = Recorder()
        wrapped = retry_with_backoff(max_attempts=3, sleep=sleeper)(flaky)
        assert wrapped() == "ok"
        assert flaky.calls == 3

    def test_a_call_that_works_first_time_never_sleeps(self):
        sleeper = Recorder()
        wrapped = retry_with_backoff(sleep=sleeper)(lambda: "ok")
        assert wrapped() == "ok"
        assert sleeper.waits == []

    def test_the_last_failure_is_raised_not_swallowed(self):
        flaky = Flaky(failures=99)
        wrapped = retry_with_backoff(max_attempts=3, sleep=Recorder())(flaky)
        with pytest.raises(ConnectionError):
            wrapped()
        assert flaky.calls == 3


class TestItDoesNotRetryWhatCannotChange:
    """The point of the module."""

    def test_an_unlisted_exception_leaves_on_the_first_attempt(self):
        flaky = Flaky(failures=99, error=ValueError)
        sleeper = Recorder()
        wrapped = retry_with_backoff(max_attempts=5, sleep=sleeper)(flaky)
        with pytest.raises(ValueError):
            wrapped()
        assert flaky.calls == 1, "a deterministic failure was retried"
        assert sleeper.waits == [], "the caller was made to wait for nothing"

    def test_give_up_on_beats_retry_on(self):
        class Refused(ConnectionError):
            pass

        flaky = Flaky(failures=99, error=Refused)
        wrapped = retry_with_backoff(
            max_attempts=5, give_up_on=(Refused,), sleep=Recorder()
        )(flaky)
        with pytest.raises(Refused):
            wrapped()
        assert flaky.calls == 1


class TestBackoff:
    def test_the_wait_grows_exponentially(self):
        sleeper = Recorder()
        wrapped = retry_with_backoff(
            max_attempts=4, backoff_factor=2.0, jitter=0.0, sleep=sleeper
        )(Flaky(failures=99))
        with pytest.raises(ConnectionError):
            wrapped()
        assert sleeper.waits == [1.0, 2.0, 4.0]

    def test_there_is_one_fewer_wait_than_attempts(self):
        """Sleeping after the final failure delays the exception for nothing."""
        sleeper = Recorder()
        wrapped = retry_with_backoff(max_attempts=3, jitter=0.0, sleep=sleeper)(
            Flaky(failures=99)
        )
        with pytest.raises(ConnectionError):
            wrapped()
        assert len(sleeper.waits) == 2

    def test_jitter_spreads_callers_that_failed_together(self):
        runs = []
        for _ in range(20):
            sleeper = Recorder()
            wrapped = retry_with_backoff(
                max_attempts=2, backoff_factor=2.0, jitter=0.5, sleep=sleeper
            )(Flaky(failures=99))
            with pytest.raises(ConnectionError):
                wrapped()
            runs.append(sleeper.waits[0])
        assert len(set(runs)) > 1, "every client would retry at the same instant"
        assert all(1.0 <= w <= 1.5 for w in runs)

    def test_a_long_backoff_is_capped(self):
        sleeper = Recorder()
        wrapped = retry_with_backoff(
            max_attempts=12, backoff_factor=3.0, jitter=0.0, sleep=sleeper
        )(Flaky(failures=99))
        with pytest.raises(ConnectionError):
            wrapped()
        assert max(sleeper.waits) == MAX_BACKOFF_SECONDS


class TestTheSilentNoneBug:
    """``for attempt in range(1, 1)`` never runs, and returns None as success."""

    @pytest.mark.parametrize("attempts", [0, -1])
    def test_a_loop_that_could_never_run_is_refused_at_decoration(self, attempts):
        with pytest.raises(ValueError, match="at least 1"):
            retry_with_backoff(max_attempts=attempts)

    def test_one_attempt_is_allowed_and_means_no_retry(self):
        flaky = Flaky(failures=99)
        wrapped = retry_with_backoff(max_attempts=1, sleep=Recorder())(flaky)
        with pytest.raises(ConnectionError):
            wrapped()
        assert flaky.calls == 1


class TestItStaysAFunction:
    def test_the_wrapper_keeps_the_name_and_docstring(self):
        @retry_with_backoff()
        def fetch_jobs():
            """Fetch some jobs."""
            return []

        assert fetch_jobs.__name__ == "fetch_jobs"
        assert fetch_jobs.__doc__ == "Fetch some jobs."

    def test_arguments_are_passed_through_unchanged(self):
        @retry_with_backoff(sleep=Recorder())
        def add(a, b, c=0):
            return a + b + c

        assert add(1, 2, c=3) == 6
