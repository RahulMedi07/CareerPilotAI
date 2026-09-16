"""The exception vocabulary for CareerPilot AI, and the envelope helper.

Before this module the project had eleven exception classes spread across six
files, rooted at ``RuntimeError``, ``KeyError`` and ``ValueError``. Each
hierarchy was sensible on its own. Together they had a hole: there was no way
to write ``except <anything this project raises>``. A caller had to import from
six modules and list eleven names, and would silently miss the twelfth the day
somebody added one.

That hole is what this module closes. The classes below are **not a parallel
set of new exceptions** - if they were, nothing would ever raise them and
``except CareerPilotException`` would catch nothing at all, which is the most
expensive kind of nothing: a safety net that looks fitted and is not. Instead
each existing hierarchy has been re-rooted onto the matching class here:

    ================================  ==============================
    Existing class                    now also inherits
    ================================  ==============================
    ``IndexerError``                  ``RAGIndexingError``
    ``AgentError`` (and so every      ``AnalysisError``
    ``JobAnalysisError``)
    ``LLMError``                      defined here, re-exported by
                                      ``agents.ollama_handler``
    ``ScraperError``                  ``JobScrapingError``
    ``ApplicationError``              ``DatabaseError``
    ================================  ==============================

Every one of them keeps its original base as well, so ``except RuntimeError``
and ``except KeyError`` at existing call sites still behave exactly as before.
The retrofit is additive: it widens what can be caught, never narrows it.

A note on ``ValidationError``
-----------------------------
Pydantic exports a class of the same name and this project uses pydantic
heavily. Importing both into one module is a genuine trap, so this one is
deliberately **not** imported bare anywhere that touches request models. When
both are needed, import the module and qualify it.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple, Type

from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "CareerPilotException",
    "RAGIndexingError",
    "AnalysisError",
    "LLMError",
    "JobScrapingError",
    "ValidationError",
    "DatabaseError",
    "STATUS_SUCCESS",
    "STATUS_VALIDATION_ERROR",
    "STATUS_LLM_ERROR",
    "STATUS_UNEXPECTED_ERROR",
    "classify",
    "envelope",
    "guarded",
    "safe_call",
]


# --------------------------------------------------------------------------- #
# The hierarchy
# --------------------------------------------------------------------------- #
class CareerPilotException(Exception):
    """Base class for every error this project raises on purpose.

    Catching this catches deliberate failures and lets genuine defects -
    ``AttributeError``, ``KeyError`` from a typo, anything unplanned - keep
    travelling. That distinction is the whole point of having a base class:
    a bare ``except Exception`` cannot tell a refused input from a bug, so it
    hides bugs.
    """


class RAGIndexingError(CareerPilotException, RuntimeError):
    """Resume indexing failed: reading, parsing, embedding or storing."""


class AnalysisError(CareerPilotException, RuntimeError):
    """An agent could not produce a result for a job or resume."""


class LLMError(CareerPilotException, RuntimeError):
    """A language-model backend could not be reached or could not be used.

    Canonical home for the name. ``agents.ollama_handler`` re-exports this
    class along with its two subclasses, so both import paths give the same
    object and ``except LLMError`` works whichever one a module reached for.
    """


class JobScrapingError(CareerPilotException, RuntimeError):
    """A job source could not be read. Never fatal - that source is dropped."""


class ValidationError(CareerPilotException, ValueError):
    """Input was rejected at a boundary.

    Reserved for boundaries with a *user* on the other side who can be told.
    Inside the pipeline the project's rule is the opposite one: a badly shaped
    argument is coerced by :mod:`utils.validation` and the run continues with a
    thinner answer, because losing six completed stages over a stray ``None``
    from the seventh serves nobody. See that module's docstring.
    """


class DatabaseError(CareerPilotException, RuntimeError):
    """A stored record could not be written or read."""


# --------------------------------------------------------------------------- #
# Result envelopes
# --------------------------------------------------------------------------- #
STATUS_SUCCESS = "success"
STATUS_VALIDATION_ERROR = "validation_error"
STATUS_LLM_ERROR = "llm_error"
STATUS_UNEXPECTED_ERROR = "unexpected_error"

#: Exception type -> the status string an envelope reports for it. Ordered
#: most specific first; :func:`classify` walks it in order.
_STATUS_BY_TYPE: Tuple[Tuple[Type[BaseException], str], ...] = (
    (ValidationError, STATUS_VALIDATION_ERROR),
    (LLMError, STATUS_LLM_ERROR),
    (CareerPilotException, STATUS_UNEXPECTED_ERROR),
)


def classify(error: BaseException) -> str:
    """Return the envelope status string for an exception."""
    for exc_type, status in _STATUS_BY_TYPE:
        if isinstance(error, exc_type):
            return status
    return STATUS_UNEXPECTED_ERROR


def envelope(
    status: str,
    data: Any = None,
    confidence: float = 0.0,
    error: Optional[str] = None,
    note: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build the standard result envelope.

    One rule, applied without exception: **the usable answer is always in
    ``data``.** If a fallback was used, the fallback is what ``data`` holds and
    ``degraded`` is true. There is never a second place to look.

    That is a deliberate departure from the pattern this was specified from,
    which put the answer in ``data`` on success, in ``fallback`` on a
    validation error, and in ``data`` again - but meaning something different -
    on an LLM error. Three places to look for one value guarantees that every
    consumer eventually reads the wrong one, and the bug it produces is a
    missing section rather than a crash, so it survives to production.
    """
    payload: Dict[str, Any] = {
        "status": status,
        "data": data,
        "confidence": round(float(confidence), 4),
        "degraded": status != STATUS_SUCCESS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if error is not None:
        payload["error"] = error
    if note is not None:
        payload["note"] = note
    payload.update(extra)
    return payload


def safe_call(
    operation: str,
    func: Callable[..., Any],
    *args: Any,
    fallback: Optional[Callable[[], Any]] = None,
    confidence: Optional[float] = None,
    confidence_key: str = "confidence",
    fallback_confidence: float = 0.5,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run ``func`` and wrap the outcome in an envelope.

    ``confidence`` is read from the result when the result is a mapping that
    carries one, because the agents in this project already compute a real,
    earned confidence figure. Overwriting that with a constant - the
    ``'confidence': 0.95`` of the original specification - would replace
    measured information with decoration, and the number would then be wrong
    precisely when it mattered: a fallback answer would still claim 0.95.
    """
    try:
        result = func(*args, **kwargs)
    except CareerPilotException as exc:
        status = classify(exc)
        recovered = None
        note = None
        if fallback is not None:
            try:
                recovered = fallback()
                note = "Primary path failed; this is the fallback result."
            except Exception:  # noqa: BLE001 - a broken fallback must not mask the original
                logger.exception("%s: fallback also failed", operation)
                recovered = None
        logger.warning("%s failed (%s): %s", operation, status, exc)
        return envelope(
            status,
            data=recovered,
            confidence=fallback_confidence if recovered is not None else 0.0,
            error=str(exc),
            note=note,
        )
    except Exception as exc:  # noqa: BLE001 - boundary: nothing may escape
        logger.exception("%s: unexpected error", operation)
        return envelope(STATUS_UNEXPECTED_ERROR, error=str(exc))

    earned = confidence
    if earned is None:
        earned = 1.0
        if isinstance(result, dict):
            raw = result.get(confidence_key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                # Agents report confidence as either 0-1 or 0-100.
                earned = float(raw) / 100.0 if float(raw) > 1.0 else float(raw)
    return envelope(STATUS_SUCCESS, data=result, confidence=earned)


def guarded(
    operation: str,
    fallback_attr: Optional[str] = None,
    **outer: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Dict[str, Any]]]:
    """Decorator form of :func:`safe_call` for methods on an agent.

    ``fallback_attr`` names a zero-argument method on ``self`` to call when the
    primary path raises.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Dict[str, Any]]:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            fallback = None
            if fallback_attr:
                candidate = getattr(self, fallback_attr, None)
                if callable(candidate):
                    fallback = candidate
            return safe_call(
                operation,
                func,
                self,
                *args,
                fallback=fallback,
                **dict(outer, **kwargs),
            )

        return wrapper

    return decorator
