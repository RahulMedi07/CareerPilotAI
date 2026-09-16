"""Liveness and readiness probes for the API.

Three decisions here differ from the obvious implementation, and each was made
against a measurement rather than a preference.

**The RAG probe counts; it does not search.** A health check that runs a real
semantic query loads the sentence-transformer model on first use. Measured on
this machine, cold: ``count()`` 0.54s, and a ``search()`` immediately after it a
further 8.19s. Both prove the same thing - Chroma is reachable and the
collection is readable - but one of them is fifteen times the cost, on an
endpoint that is unauthenticated and designed to be called every few seconds.
That combination is a denial-of-service amplifier: a cheap request that buys
expensive work. It is also self-defeating, because a load balancer with the
customary 5s probe timeout would mark a perfectly healthy instance as dead,
restart it, and meet the same 8s model load on the next probe. A restart loop
caused by the thing meant to detect restarts.

**The LLM probe asks whether a backend answers; it does not send a prompt.** A
real prompt on this path would run against ``LLM_TIMEOUT_SECONDS``, which is
120. An unauthenticated GET that can occupy a worker for two minutes, and on a
hosted model costs money per call, is not a health check. The cached
availability probe uses ``LLM_HEALTHCHECK_TIMEOUT`` (2.0s) and answers the
question that matters.

For the hosted backends that question is answered without a network call at
all: Gemini and Claude report availability from a configured key. That is the
right trade for a probe, but it means ``healthy`` there promises a key and not
a reply -- a throttled free tier refuses every request and still has its key.
So the probe names the backend and says which of the two it checked, rather
than showing a green chip that a rate-limited account has not earned.

**A missing LLM is degraded, not unhealthy.** This application is built to work
with no model at all - that is the point of the deterministic fallback path,
and every one of its tests runs that way. Reporting the whole service unhealthy
because Ollama is not running would take a correct, serving instance out of the
load balancer. Only checks marked ``required`` affect the status code.

On error text
-------------
Exception messages are logged, never returned. ``str(exc)`` on a database or
filesystem failure routinely contains absolute paths, and on a connection
failure the internal host and port - the sort of detail that is free
reconnaissance on an endpoint with no authentication in front of it (OWASP
A01/A05). The caller gets the failing service, a stable ``error_id``, and the
class of error; the operator matches that id in the log and gets everything.
"""

from __future__ import annotations

import asyncio
import importlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "HealthCheck",
    "health_check",
    "HEALTHY",
    "DEGRADED",
    "UNHEALTHY",
]

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"

#: Backends whose ``is_available`` reads a configured key rather than calling
#: anything. Ollama is absent because its probe really does hit the daemon.
#: Public because ``test_week1.py`` needs the same distinction, and two copies
#: of this set would drift the moment a provider is added.
KEY_ONLY_BACKENDS = frozenset({"gemini", "claude"})

#: No single probe may hold the endpoint longer than this.
PROBE_TIMEOUT_SECONDS = 5.0

#: How long to let a contended import settle before trying it a second time.
IMPORT_RETRY_SECONDS = 0.25


def _lazy_import(module: str, attr: str) -> Any:
    """Import on demand, retrying once if the import lock is contended.

    The probes import inside their own bodies rather than at module scope, so
    that a health check does not drag every agent -- and the credentials they
    hold -- into the process merely by being imported.

    The cost of that is a race. The probes run on worker threads, and a thread
    reaching a module that another thread is still importing does not wait:
    CPython detects the cycle and raises ``_DeadlockError``. It is a
    ``RuntimeError``, not an ``ImportError``, which is easy to guess wrong.

    A contended import is a timing accident, not a broken dependency, but the
    probe could not tell the two apart and reported the database as unhealthy
    while SQLite was answering queries perfectly well -- alarming, and about
    the worst thing for a status page to be wrong about. The other thread
    finishes in milliseconds, so a single short retry settles it. A second
    failure is allowed to propagate and be reported, because by then it is
    unlikely to be the race.
    """
    try:
        return getattr(importlib.import_module(module), attr)
    except RuntimeError as exc:
        if type(exc).__name__ != "_DeadlockError":
            raise
    time.sleep(IMPORT_RETRY_SECONDS)
    return getattr(importlib.import_module(module), attr)


def _result(
    service: str,
    status: str,
    required: bool,
    started: float,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "service": service,
        "status": status,
        "required": required,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    payload.update(extra)
    return payload


def _failure(service: str, required: bool, started: float, exc: BaseException) -> Dict[str, Any]:
    """Log the detail, return an id for it."""
    error_id = uuid.uuid4().hex[:8]
    logger.error(
        "[%s] health probe %r failed: %s: %s",
        error_id,
        service,
        type(exc).__name__,
        exc,
    )
    return _result(
        service,
        UNHEALTHY,
        required,
        started,
        error_type=type(exc).__name__,
        error_id=error_id,
        detail="Probe failed. Search the logs for this error_id.",
    )


class HealthCheck:
    """Probes each dependency and summarises the result.

    The probe methods are synchronous because the work they do is synchronous -
    SQLite and Chroma have no async API here. :meth:`full_health_check` moves
    them onto threads, which is what makes the ``gather`` below concurrent.
    Declaring them ``async`` while their bodies block would give no concurrency
    at all *and* would stall every other request on the event loop for the
    duration.
    """

    def check_rag_system(self) -> Dict[str, Any]:
        """Is the vector store reachable? Counts rather than searches."""
        started = time.perf_counter()
        try:
            resume_indexer = _lazy_import("rag.resume_indexer", "resume_indexer")

            count = resume_indexer.count()
            return _result(
                "rag",
                HEALTHY,
                True,
                started,
                indexed_chunks=count,
                note=None if count else "Reachable, but nothing is indexed yet.",
            )
        except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
            return _failure("rag", True, started, exc)

    def check_llm(self) -> Dict[str, Any]:
        """Does a model backend answer? Optional by design."""
        started = time.perf_counter()
        try:
            llm_client = _lazy_import("agents.ollama_handler", "llm_client")

            backend = llm_client.available_backend()
            available = backend is not None
            if not available:
                note = "No backend reachable; analysis uses the deterministic path."
            elif backend in KEY_ONLY_BACKENDS:
                # Saying "healthy" off a key alone would be a false all-clear:
                # a throttled free tier fails every request and still has a key.
                note = (
                    "A %s key is configured. This is not a live call, so requests "
                    "can still be refused - free tiers limit them per minute." % backend
                )
            else:
                note = None
            return _result(
                "llm",
                HEALTHY if available else DEGRADED,
                False,
                started,
                provider=settings.LLM_PROVIDER,
                backend=backend,
                note=note,
            )
        except Exception as exc:  # noqa: BLE001
            return _failure("llm", False, started, exc)

    def check_database(self) -> Dict[str, Any]:
        """Is SQLite readable?

        Uses the tracker's own public counting query rather than reaching for a
        private connection: a probe that bypasses the module's API can keep
        passing after that API has broken.
        """
        started = time.perf_counter()
        try:
            application_tracker = _lazy_import(
                "agents.application_tracker", "application_tracker"
            )

            application_tracker.count_applications()
            return _result("database", HEALTHY, True, started)
        except Exception as exc:  # noqa: BLE001
            return _failure("database", True, started, exc)

    async def _run(self, name: str, probe: Any) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, probe),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("health probe %r exceeded %.1fs", name, PROBE_TIMEOUT_SECONDS)
            return _result(
                name,
                UNHEALTHY,
                name != "llm",
                started,
                detail="Probe timed out after %.1fs." % PROBE_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            return _failure(name, name != "llm", started, exc)

    async def full_health_check(self) -> Dict[str, Any]:
        """Run every probe concurrently and summarise."""
        started = time.perf_counter()
        services: List[Dict[str, Any]] = list(
            await asyncio.gather(
                self._run("rag", self.check_rag_system),
                self._run("llm", self.check_llm),
                self._run("database", self.check_database),
            )
        )

        required_failed = [
            s for s in services if s.get("required") and s.get("status") != HEALTHY
        ]
        optional_degraded = [
            s for s in services if not s.get("required") and s.get("status") != HEALTHY
        ]

        if required_failed:
            overall = UNHEALTHY
        elif optional_degraded:
            overall = DEGRADED
        else:
            overall = HEALTHY

        return {
            "overall_status": overall,
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "services": services,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


#: Shared instance. Stateless, so sharing costs nothing and saves a construction
#: on every probe.
health_check = HealthCheck()
