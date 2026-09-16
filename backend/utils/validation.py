"""Boundary coercion for agent inputs.

Every agent in this project takes dictionaries produced by an earlier stage:
the resume parser, the job analyser, the match calculator. In the happy path
those are always dictionaries, and the agents are written on that assumption -
``resume_data.get("skills")`` appears everywhere.

The assumption is not safe at the edges. An upstream agent that falls back may
return ``None``. A JSON payload can put a string where an object belongs. A
test double can pass a list. In every one of those cases the agents used to
raise ``AttributeError: 'NoneType' object has no attribute 'get'`` halfway
through a run, losing the work of the stages that had already succeeded.

The rule adopted here is that a *shape* problem is not an error worth failing a
run over. A caller who hands in a string instead of a resume gets an empty
resume - and therefore a report that honestly says it found nothing - rather
than a stack trace. A caller who hands in genuinely bad *data* inside a
correctly-shaped dictionary still gets the normal handling for that, because
that is a content problem and the agents already reason about it.

Coercion is deliberately confined to this one module so the behaviour is
described once. It is not a validation framework and should not become one:
anything that needs to reject input rather than degrade past it belongs in the
API layer, where there is a user to tell.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = ["as_dict", "as_list", "as_float", "as_int"]


def as_dict(value: Any, name: str = "input") -> Dict[str, Any]:
    """Return a dictionary, whatever was passed in.

    A mapping is copied so the caller cannot mutate its argument by accident.
    Anything else becomes ``{}`` and is logged at debug level: the run
    continues, but the reason the output looks empty is recorded rather than
    silently swallowed.
    """
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    # Mapping-like objects that are not dicts still deserve a chance.
    if hasattr(value, "keys") and hasattr(value, "__getitem__"):
        try:
            return {str(k): value[k] for k in value.keys()}
        except Exception:  # noqa: BLE001 - a hostile mapping is still just empty
            logger.debug("Could not read %s as a mapping; using {}", name)
            return {}
    logger.debug("Expected a dict for %s, got %s; using {}", name, type(value).__name__)
    return {}


def as_list(value: Any, name: str = "input") -> List[Any]:
    """Return a list, whatever was passed in.

    A bare string becomes a single-item list rather than a list of characters,
    because ``skills="python"`` means one skill and splitting it into ``["p",
    "y", ...]`` would be worse than useless.
    """
    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    logger.debug("Expected a list for %s, got %s; using []", name, type(value).__name__)
    return []


def as_float(value: Any, default: float = 0.0) -> float:
    """Return a float, falling back rather than raising."""
    if isinstance(value, bool):
        # bool is an int subclass; treating True as 1.0 is almost never meant.
        return default
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    # NaN compares false against itself; it must not reach a score calculation.
    if result != result:
        return default
    return result


def as_int(value: Any, default: int = 0) -> int:
    """Return an int, falling back rather than raising."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def first_dict(*values: Any) -> Optional[Dict[str, Any]]:
    """The first argument that is genuinely a non-empty dictionary."""
    for value in values:
        if isinstance(value, dict) and value:
            return dict(value)
    return None
