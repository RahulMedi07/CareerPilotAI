"""Logging setup for CareerPilot AI.

Every knob lives in :mod:`config`; this module only wires it up.

Two shapes of log are produced, on purpose:

* **Prose**, via :func:`get_logger`, for the running commentary a person reads
  when something looks wrong. This is what the other 24 modules use.
* **JSON**, via :class:`StructuredLogger`, for operations a machine aggregates -
  one object per event, with the fields in known places.

:class:`StructuredLogger` *wraps* a standard logger rather than replacing it.
That is not decoration. The obvious implementation gives the class only
``log_operation`` and ``log_error``; swapping it in for ``get_logger`` then
breaks all 108 existing ``logger.info(...)`` calls with ``AttributeError`` -
and does so at the moment something has already gone wrong, since that is when
the error paths run. Delegating means both styles work on one object and can be
adopted where each earns its place.
"""

import functools
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, Optional, TypeVar

from config import settings

F = TypeVar("F", bound=Callable[..., Any])

_configured = False


def setup_logging() -> None:
    """Configure the root logger once, with console and rotating file output."""
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(settings.LOG_FORMAT, datefmt=settings.LOG_DATE_FORMAT)

    handlers = [logging.StreamHandler(sys.stdout)]
    if settings.LOG_TO_FILE:
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                settings.log_file,
                maxBytes=settings.LOG_MAX_BYTES,
                backupCount=settings.LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    root.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name."""
    setup_logging()
    return logging.getLogger(name)


def _stringify(value: Any) -> Any:
    """Last-resort coercion so that serialising a log entry cannot raise.

    ``json.dumps`` refuses ``datetime``, ``Path``, ``set`` and every ordinary
    domain object, and those are exactly what ends up in a details dictionary.
    A logging call that raises inside an ``except`` block replaces the error
    being reported with a ``TypeError`` about the report - the original cause
    is gone, and the failure appears to come from the logging line.
    """
    return str(value)


class StructuredLogger:
    """Emits one JSON object per operation, alongside the usual prose logs.

    Attribute lookups fall through to the wrapped :class:`logging.Logger`, so
    ``.info()``, ``.warning()``, ``.exception()`` and the rest behave exactly
    as they always have.

    Handlers are **not** attached here. ``logging.getLogger(name)`` returns the
    same object every time, so a class that adds handlers in ``__init__``
    doubles them on the second construction with the same name - and since
    every module does ``StructuredLogger(__name__)`` at import, a reimport
    duplicates every subsequent line. Configuration belongs to
    :func:`setup_logging`, which is idempotent and reads the validated
    settings, including the log directory. Hard-coding ``data/logs/app.log``
    would also make the path depend on the working directory the server was
    started from, a bug this project has already fixed once elsewhere.
    """

    def __init__(self, name: str) -> None:
        self.logger = get_logger(name)
        self.name = name

    def __getattr__(self, item: str) -> Any:
        # Only reached for attributes not found on the instance, so the
        # explicit methods below take precedence.
        return getattr(self.logger, item)

    def _emit(self, level: int, entry: Dict[str, Any]) -> None:
        self.logger.log(level, json.dumps(entry, default=_stringify, sort_keys=True))

    def log_operation(
        self,
        operation: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        level: int = logging.INFO,
    ) -> None:
        """Record that an operation reached a state, with its measurements."""
        self._emit(
            level,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation": operation,
                "status": status,
                "details": details or {},
            },
        )

    def log_error(
        self,
        operation: str,
        error: BaseException,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a failure with the context needed to understand it.

        The context is the caller's responsibility and must not contain resume
        text or advert bodies: logs are retained far longer than the request
        that produced them, and this project treats both as personal data.
        """
        self._emit(
            logging.ERROR,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {},
            },
        )


def observed(operation: str) -> Callable[[F], F]:
    """Log an agent entry point's outcome as structured JSON, then get out of the way.

    The method's return value and its exceptions are untouched: a failure is
    recorded and re-raised. That restraint is the point. The pattern this
    replaces converted every agent's return into a
    ``{'status', 'data', 'confidence'}`` envelope, which reads well in isolation
    and is a breaking change to every caller in the pipeline and to the tests
    that pin them - and it would have overwritten the confidence figures the
    agents actually compute with a hard-coded 0.95, so the number would have
    been most wrong exactly when the agent had fallen back.

    Callers that do want an envelope have :func:`utils.error_handling.safe_call`,
    which reads the real confidence out of the result instead of inventing one.
    """

    def decorator(func: F) -> F:
        structured = StructuredLogger(func.__module__)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                structured.log_error(
                    operation,
                    exc,
                    {"duration_ms": round((time.perf_counter() - started) * 1000, 1)},
                )
                raise
            structured.log_operation(
                operation,
                "completed",
                {
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "result_keys": sorted(result)[:12] if isinstance(result, dict) else None,
                    "result_count": len(result) if isinstance(result, (list, tuple)) else None,
                },
                level=logging.DEBUG,
            )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
