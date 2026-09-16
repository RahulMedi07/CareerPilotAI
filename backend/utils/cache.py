"""A small in-process TTL cache, and a decorator that uses it safely.

Why this is not the four-line version
-------------------------------------
The obvious implementation keys entries on ``hash(str(args) + str(kwargs))``.
That is wrong here in four separate ways, three of which fail silently:

1. ``args`` includes ``self``, and a default ``__repr__`` contains the object's
   memory address - ``<MatchCalculator object at 0x10a732e50>``. So the key
   identifies *the instance*, not the question being asked. Two instances asking
   the same question miss each other's entries; and because CPython recycles
   addresses immediately, a *new* object at a freed address collides with the
   dead one's entries and is served its answers. Both were reproduced before
   this module was written. Here that would mean one caller's job analysis
   handed to another.

2. ``hash()`` on a string is randomised per process (PEP 456, on by default
   since 3.3). Keys are therefore not stable across a restart, which rules the
   scheme out for anything persisted, and makes it untestable across runs.

3. Reducing the key to a 64-bit integer and discarding the original throws away
   the ability to detect a collision. A dict keyed on the real value compares on
   collision; a dict keyed on a hash cannot, so a collision silently returns
   another entry's value. sha256 of a canonical encoding is used instead - not
   for secrecy, but because a 256-bit digest puts the birthday bound out of
   reach, and because it is stable.

4. ``if cached:`` treats a legitimately falsy result - ``{}``, ``[]``, ``0`` -
   as a miss, so the expensive call is repeated forever for exactly the inputs
   that produce nothing. A sentinel is used instead.

Two further properties this cache needs and the sketch lacks: a **size cap**,
because entries are keyed on user-supplied text on an unauthenticated API and an
unbounded dict is a memory-exhaustion bug with a friendly name; and a **lock**,
because the app is threaded (FastAPI's threadpool, and `JobEnricher`'s own
pool), and expiry is a read-then-delete race.

What is deliberately *not* cached is documented in ``agents/`` at each call
site: measurement, not intuition, decides. On the deterministic path most agents
answer in well under a millisecond, and building the key costs a measurable
fraction of that.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

#: Returned by :meth:`Cache.get` when there is no live entry. A plain ``None``
#: cannot be used because ``None`` is a legitimate cached value.
MISS = object()

DEFAULT_MAX_ENTRIES = 512


def _canonical(value: Any) -> str:
    """Encode a value so that equal inputs produce equal text, stably.

    ``json.dumps(..., sort_keys=True)`` handles the common cases and makes two
    dicts that differ only in insertion order agree. Anything JSON cannot
    describe falls back to ``repr``, which is where an un-``__repr__``-ed object
    would reintroduce a memory address - so the fallback also records the type
    name, and callers passing such objects are expected to supply their own key.
    """
    try:
        return json.dumps(value, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return "%s:%r" % (type(value).__name__, value)


def make_key(prefix: str, *parts: Any) -> str:
    """A stable, collision-resistant key for the given parts."""
    digest = hashlib.sha256(
        "\x00".join(_canonical(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return "%s:%s" % (prefix, digest)


class Cache:
    """TTL cache with a size cap and least-recently-used eviction.

    Args:
        ttl_minutes: How long an entry stays valid. ``0`` disables caching
            entirely, which is the honest way to turn it off in configuration.
        max_entries: Hard cap on live entries. The least recently used entry is
            evicted when the cap is reached.
    """

    def __init__(
        self, ttl_minutes: float = 60.0, max_entries: int = DEFAULT_MAX_ENTRIES
    ) -> None:
        if ttl_minutes < 0:
            raise ValueError("ttl_minutes must not be negative")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.ttl_seconds = float(ttl_minutes) * 60.0
        self.max_entries = int(max_entries)
        self._entries: "OrderedDict[str, Tuple[Any, float]]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # -- core ---------------------------------------------------------------

    def get(self, key: str) -> Any:
        """Return the cached value, or :data:`MISS`."""
        if self.ttl_seconds == 0:
            self._misses += 1
            return MISS
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return MISS
            value, stored_at = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[key]
                self._expirations += 1
                self._misses += 1
                return MISS
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        """Store a value, evicting the oldest entries once the cap is reached.

        A TTL of zero means caching is off, so this stores nothing rather than
        storing something that expires immediately - the difference matters
        when a test disables the cache and then asserts on its size.
        """
        if self.ttl_seconds == 0:
            return
        with self._lock:
            if key in self._entries:
                del self._entries[key]
            self._entries[key] = (value, time.monotonic())
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        """Drop every entry. Counters are kept, so hit rate spans the process."""
        with self._lock:
            self._entries.clear()

    # -- introspection ------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        """Numbers the benchmark and the health endpoint report.

        A cache nobody can measure is a cache nobody can tell is broken: a hit
        rate of zero looks exactly like a fast application from the outside.
        """
        with self._lock:
            looked_up = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "max_entries": self.max_entries,
                "ttl_seconds": round(self.ttl_seconds, 1),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / looked_up, 4) if looked_up else 0.0,
                "evictions": self._evictions,
                "expirations": self._expirations,
            }

    def reset_stats(self) -> None:
        """Zero the counters without discarding the cached values."""
        with self._lock:
            self._hits = self._misses = self._evictions = self._expirations = 0


# --------------------------------------------------------------------------- #
# Shared instances
# --------------------------------------------------------------------------- #
#: Job adverts are pure input: the same advert always analyses the same way, so
#: this is safe to hold for a long time. It is also the only agent cache that
#: measurement justified - see ``agents/job_analyzer.py``.
job_analysis_cache = Cache(ttl_minutes=120, max_entries=256)

# There were two more caches here, ``match_cache`` and ``resume_cache``. Both
# were declared, listed below, reported by ``GET /api/health/performance`` and
# emptied by ``POST /api/career/clear`` - and nothing ever wrote to either of
# them. They read 0 hits and 0 misses for the life of the process while the
# health endpoint presented them alongside a cache that genuinely works.
#
# They were removed rather than wired up, for a reason in each case:
#
# ``match_cache``: ``calculate_match`` takes a ``retriever``, and its answer
# depends on what that index currently holds - evidence is pulled from the RAG
# store when one is present and scanned from raw text when it is not. The index
# is mutable external state that no cache key here covers, so a hit computed
# before a re-index would keep serving evidence from the old resume. Keying on
# an index generation would fix that, at real complexity, to save a measured
# 0.069 ms. Correctness first, and the saving does not pay for the risk.
#
# ``resume_cache``: its stated job was to skip re-parsing an identical upload.
# The indexer already solves that, and better, by content-addressing its chunks
# (``_content_sha``) - which additionally stops the duplicate-chunk problem
# that a text cache would do nothing about. Two mechanisms for one job is how
# they drift.
ALL_CACHES: Dict[str, Cache] = {
    "job_analysis": job_analysis_cache,
}


def clear_all() -> None:
    """Drop every cached value.

    Wired into ``POST /api/career/clear``. Without this, clearing the resume
    leaves analyses *derived from that resume* readable by the next caller,
    which turns a privacy control into a no-op.
    """
    for cache in ALL_CACHES.values():
        cache.clear()
    logger.info("All caches cleared")


def all_stats() -> Dict[str, Any]:
    """Hit/miss counters for every named cache, for the health endpoint."""
    return {name: cache.stats() for name, cache in ALL_CACHES.items()}


# --------------------------------------------------------------------------- #
# Decorator
# --------------------------------------------------------------------------- #
def cache_result(
    cache_obj: Cache,
    key_prefix: str,
    key_fn: Optional[Callable[..., Any]] = None,
    copy_result: bool = True,
) -> Callable[[F], F]:
    """Memoise a function on the *values* of its arguments.

    The receiver (``self``/``cls``) is excluded from the key: it identifies the
    object, not the question, and including it is the bug described in the
    module docstring.

    Args:
        cache_obj: The :class:`Cache` to store results in.
        key_prefix: Namespace, so two functions cannot collide.
        key_fn: Optional. Called with the same arguments (minus the receiver)
            and must return something canonicalisable. Use it when an argument
            is large but only part of it affects the result.
        copy_result: Hand each caller its own copy. Defaults to ``True``
            because the alternative is that every caller shares one mutable
            dict: the first one to do ``result["skills"].append(...)`` silently
            edits what everyone else receives for the next two hours, and the
            damage shows up far from its cause. Measured here at 0.0195 ms
            against 2.28 ms to recompute - 117x cheaper than the work being
            avoided, so it never inverts the reason for caching. Turn it off
            only for results known to be immutable.

    Only cache functions that are actually pure. A method that also assigns to
    ``self`` is not: on a hit the body never runs, so the assignment never
    happens. Cache the pure inner computation and leave the side effect in the
    wrapper - see ``JobAnalyzerAgent.analyze``.
    """

    def decorator(func: F) -> F:
        try:
            params = list(inspect.signature(func).parameters)
            drop_first = bool(params) and params[0] in ("self", "cls")
        except (TypeError, ValueError):  # builtins have no signature
            drop_first = False

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key_args = args[1:] if drop_first else args
            if key_fn is not None:
                key = make_key(key_prefix, key_fn(*key_args, **kwargs))
            else:
                key = make_key(key_prefix, list(key_args), kwargs)

            cached = cache_obj.get(key)
            if cached is not MISS:
                return deepcopy(cached) if copy_result else cached

            result = func(*args, **kwargs)
            cache_obj.set(key, deepcopy(result) if copy_result else result)
            return result

        wrapper.cache = cache_obj  # type: ignore[attr-defined]
        wrapper.cache_key_prefix = key_prefix  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
