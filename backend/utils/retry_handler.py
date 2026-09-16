"""Retry with exponential backoff, for the failures that retrying can fix.

The distinction in that sentence is the whole module. A retry loop is not free
and it is not always harmless:

* **Retrying a deterministic failure wastes the caller's time to reach the
  identical answer.** A refused URL, a malformed advert, a 404, a validation
  error - none of these become true on the third attempt. The naive decorator
  catches bare ``Exception``, so it turns a 2 ms rejection into a 2 ms
  rejection plus three seconds of sleeping, and does it while the user waits.
  This one retries only what is listed in ``retry_on``.

* **Retrying a non-idempotent call can do the work twice.** A ``POST`` that
  times out after the server committed it will be sent again. Nothing here can
  detect that for you, so the decorator is applied only to reads, and saying so
  is part of its contract.

* **Backoff without jitter synchronises callers.** Every client that failed at
  the same moment retries at the same moment, which is how a struggling server
  is kept down. A random fraction is added to each wait.

There is also a defect worth naming because it is easy to write and impossible
to see: a retry loop written as ``for attempt in range(1, max_attempts + 1)``
with the ``return`` inside falls off the end and returns ``None`` when
``max_attempts`` is zero. The function reports success, having never run. This
implementation refuses ``max_attempts < 1`` at decoration time, so the mistake
is a startup error rather than a silent wrong answer in production.
"""

from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable, Optional, Tuple, Type

from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = ["retry_with_backoff", "RETRYABLE_BY_DEFAULT"]

#: Transient failures worth a second attempt. Deliberately narrow: everything
#: here is a network or availability condition that a moment's wait can change.
#: ``OSError`` covers ``ConnectionError``, ``TimeoutError`` and socket errors.
RETRYABLE_BY_DEFAULT: Tuple[Type[BaseException], ...] = (OSError,)

#: Cap on any single wait, so a large ``max_attempts`` cannot schedule a sleep
#: measured in minutes.
MAX_BACKOFF_SECONDS = 30.0


def _name(func: Any) -> str:
    """A name for logging that exists for every callable.

    ``func.__name__`` is absent on callable objects, ``functools.partial`` and
    some builtins - and reaching for it in the failure branch means the retry
    handler raises ``AttributeError`` while reporting somebody else's error,
    replacing the real problem with a bogus one at the worst moment. Found by
    the tests in this module, which retry a callable class.
    """
    return getattr(func, "__name__", None) or type(func).__name__


def retry_with_backoff(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    retry_on: Optional[Tuple[Type[BaseException], ...]] = None,
    give_up_on: Tuple[Type[BaseException], ...] = (),
    jitter: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry ``func`` on transient failures, waiting longer between attempts.

    Args:
        max_attempts: Total attempts including the first. Must be >= 1.
        backoff_factor: Base of the exponential wait, in seconds.
        retry_on: Exception types worth retrying. Defaults to
            :data:`RETRYABLE_BY_DEFAULT`. Anything not listed is re-raised
            immediately, on the first attempt.
        give_up_on: Exception types that are never retried even if they would
            otherwise match ``retry_on``. Checked first.
        jitter: Fraction of each wait to randomise, spreading out callers that
            failed together.
        sleep: Injected for tests, which must not really sleep.

    Only for idempotent operations - reads, fetches, probes.
    """
    if max_attempts < 1:
        raise ValueError(
            "max_attempts must be at least 1; %r would skip the call entirely "
            "and return None as though it had succeeded" % (max_attempts,)
        )
    retryable = RETRYABLE_BY_DEFAULT if retry_on is None else retry_on

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except give_up_on:
                    raise
                except retryable as exc:
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempt(s): %s",
                            _name(func),
                            attempt,
                            exc,
                        )
                        raise
                    wait = min(
                        backoff_factor ** (attempt - 1), MAX_BACKOFF_SECONDS
                    )
                    if jitter:
                        wait += random.uniform(0.0, wait * jitter)
                    logger.warning(
                        "%s attempt %d/%d failed (%s); retrying in %.2fs",
                        _name(func),
                        attempt,
                        max_attempts,
                        exc,
                        wait,
                    )
                    sleep(wait)
            # Unreachable: the loop either returns or raises. Present so that a
            # future edit to the bounds cannot reintroduce the silent-None bug.
            raise AssertionError("retry loop completed without returning")

        return wrapper

    return decorator
