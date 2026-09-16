"""Saved jobs, on disk, in SQLite.

The data is small, relational and written by one process, which is the exact
shape SQLite is for. A server would be ceremony for a few hundred rows.

**On ``user_id``.** This is now a real owner. The API derives it from a signed
session cookie and never from anything the caller sends, so a request cannot
name a user id it has not authenticated as. This module still treats the value
as opaque: it validates it and parameterises every query, because a storage
layer should not depend on its caller having got the authorisation right. What
changed is only that the value arriving here can now be trusted to identify
someone; enforcing *that* is the API layer's job, not this file's.

Every query is parameterised. There is no string interpolation of user data
into SQL anywhere in this file, including the ``status`` filter, which is
additionally checked against a fixed set.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from config import settings
from utils.logger import get_logger
from utils.validation import as_dict, as_int

logger = get_logger(__name__)

__all__ = [
    "JobStorage",
    "job_storage",
    "JobStorageError",
    "UnknownStatusError",
    "STATUSES",
    "DEFAULT_USER_ID",
]


class JobStorageError(RuntimeError):
    """Something could not be stored or read."""


class UnknownStatusError(JobStorageError, ValueError):
    """A status outside the known set was supplied."""


#: The lifecycle of an application, in order.
STATUSES = ("saved", "analyzed", "applied", "rejected", "interview", "offer")

#: Used when the caller names no user. See the module docstring.
DEFAULT_USER_ID = "local"

#: Conservative: identifiers end up in log lines and file paths elsewhere.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    title        TEXT NOT NULL,
    company      TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    requirements TEXT NOT NULL DEFAULT '{}',
    analysis     TEXT NOT NULL DEFAULT '{}',
    source       TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    posted_date  TEXT NOT NULL DEFAULT '',
    saved_date   TEXT NOT NULL,
    updated_date TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'saved',
    match_score  REAL,
    notes        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_user   ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(user_id, status);
-- The same advert saved twice by the same person is one row, not two. A
-- partial index so that adverts with no URL (Hacker News comments) are not
-- all collapsed into a single row by an empty string.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_user_url
    ON jobs(user_id, url) WHERE url <> '';
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_user_id(user_id: Any) -> str:
    """Constrain the namespace key. Not authentication - see the module docstring."""
    text = str(user_id or "").strip() or DEFAULT_USER_ID
    if not _USER_ID_RE.match(text):
        raise JobStorageError(
            "user_id must be 1-64 characters of letters, digits, dot, dash, "
            "underscore or @"
        )
    return text


def _validate_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text not in STATUSES:
        raise UnknownStatusError(
            "unknown status %r; expected one of %s" % (status, ", ".join(STATUSES))
        )
    return text


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value or {}, default=str)
    except (TypeError, ValueError):
        return "{}"


def _loads(value: Any) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


class JobStorage:
    """A tiny SQLite-backed store of jobs a user has kept.

    Args:
        db_path: Where the database lives. Defaults to ``settings.JOBS_DB_PATH``.
            Tests pass a temp path so they never touch real data.
    """

    label = "Job Storage"

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(settings.JOBS_DB_PATH)
        self._lock = threading.Lock()
        self._ready = False

    # -- Connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """A fresh connection per operation.

        SQLite connections are not safe to share across threads, and this
        store is called from a thread pool and from FastAPI's worker threads.
        Opening per call costs microseconds against a local file and removes
        the entire question.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        # Write-ahead logging lets a reader and a writer coexist instead of
        # one blocking the other.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            try:
                with self._connect() as connection:
                    connection.executescript(_SCHEMA)
            except sqlite3.Error as exc:
                raise JobStorageError("could not create the jobs database: %s" % exc) from exc
            self._ready = True

    # -- Writes ----------------------------------------------------------

    def save_job(
        self, job_dict: Dict[str, Any], user_id: str = DEFAULT_USER_ID
    ) -> str:
        """Store one job and return its id.

        Saving the same advert twice updates the existing row rather than
        creating a duplicate, keeping the original ``saved_date`` and the
        status the user has already moved it to. Someone who saves a job,
        marks it applied, then saves it again from a fresh search would
        otherwise silently lose that they had applied.
        """
        self._ensure_schema()
        job = as_dict(job_dict, "job_dict")
        user = _validate_user_id(user_id)

        if not str(job.get("title") or "").strip():
            raise JobStorageError("a job needs a title to be saved")

        analysis = as_dict(job.get("analysis"))
        job_id = str(job.get("job_id") or job.get("id") or "").strip() or _new_id()
        url = str(job.get("url") or "").strip()
        now = _now()

        match = as_dict(job.get("match_to_user"))
        score = match.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None

        row = (
            job_id, user,
            str(job.get("title") or "").strip(),
            str(job.get("company") or "").strip(),
            str(job.get("description") or ""),
            _dumps(analysis.get("skill_breakdown") or analysis.get("required_skills") or {}),
            _dumps(analysis),
            str(job.get("source") or ""),
            url,
            str(job.get("posted_date") or ""),
            now, now,
            _validate_status(job.get("status") or "saved"),
            score,
            str(job.get("notes") or ""),
        )

        try:
            with self._connect() as connection:
                existing = None
                if url:
                    existing = connection.execute(
                        "SELECT job_id FROM jobs WHERE user_id = ? AND url = ?",
                        (user, url),
                    ).fetchone()
                if existing is None:
                    existing = connection.execute(
                        "SELECT job_id FROM jobs WHERE user_id = ? AND job_id = ?",
                        (user, job_id),
                    ).fetchone()

                if existing is not None:
                    job_id = existing["job_id"]
                    connection.execute(
                        """UPDATE jobs SET title=?, company=?, description=?,
                               requirements=?, analysis=?, source=?, posted_date=?,
                               updated_date=?, match_score=?
                           WHERE job_id = ?""",
                        # title..source is row[2:8]; skip url (it is the match
                        # key and cannot have changed) and take posted_date.
                        row[2:8] + (row[9], now, score, job_id),
                    )
                else:
                    # ``job_id`` is the table's primary key but every read is
                    # scoped by ``user_id``, so an id taken by *another* user
                    # is invisible to the lookups above and the insert below
                    # would fail with a UNIQUE violation. Two people saving the
                    # same advert is not an edge case - popular adverts are
                    # exactly the ones several users save - so this mints a
                    # fresh id for this user's own copy of the row.
                    taken = connection.execute(
                        "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
                    ).fetchone()
                    if taken is not None:
                        job_id = _new_id()
                        row = (job_id,) + row[1:]
                    connection.execute(
                        """INSERT INTO jobs (
                               job_id, user_id, title, company, description,
                               requirements, analysis, source, url, posted_date,
                               saved_date, updated_date, status, match_score, notes
                           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        row,
                    )
        except sqlite3.Error as exc:
            raise JobStorageError("could not save the job: %s" % exc) from exc

        logger.info("Saved job %s for %s (%s)", job_id, user, job.get("title"))
        return job_id

    def update_job_status(
        self, job_id: str, status: str, user_id: Optional[str] = None
    ) -> bool:
        """Move a job along its lifecycle. Returns False if there was no such job."""
        self._ensure_schema()
        checked = _validate_status(status)
        job_id = str(job_id or "").strip()
        if not job_id:
            raise JobStorageError("job_id is required")

        sql = "UPDATE jobs SET status = ?, updated_date = ? WHERE job_id = ?"
        params: List[Any] = [checked, _now(), job_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(_validate_user_id(user_id))

        try:
            with self._connect() as connection:
                changed = connection.execute(sql, params).rowcount
        except sqlite3.Error as exc:
            raise JobStorageError("could not update the job: %s" % exc) from exc

        if changed:
            logger.info("Job %s -> %s", job_id, checked)
        return bool(changed)

    def delete_job(self, job_id: str, user_id: Optional[str] = None) -> bool:
        """Remove one job. Returns False if it was not there."""
        self._ensure_schema()
        sql = "DELETE FROM jobs WHERE job_id = ?"
        params: List[Any] = [str(job_id or "").strip()]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(_validate_user_id(user_id))
        try:
            with self._connect() as connection:
                return bool(connection.execute(sql, params).rowcount)
        except sqlite3.Error as exc:
            raise JobStorageError("could not delete the job: %s" % exc) from exc

    # -- Reads -----------------------------------------------------------

    def get_user_saved_jobs(
        self, user_id: str = DEFAULT_USER_ID, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Everything this user has kept, newest first."""
        return self._select(_validate_user_id(user_id), None, limit)

    def get_jobs_by_status(
        self, user_id: str, status: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """This user's jobs in one state - everything applied to, say."""
        return self._select(_validate_user_id(user_id), _validate_status(status), limit)

    def get_job(self, job_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch one stored advert, optionally scoped to a user.

        Pass ``user_id`` whenever the caller is acting for a person: without
        it this reads across everyone's rows. ``job_id`` identifies *one
        user's copy* of an advert, not the advert itself - two people saving
        the same posting get two rows with two ids.
        """
        self._ensure_schema()
        sql = "SELECT * FROM jobs WHERE job_id = ?"
        params: List[Any] = [str(job_id or "").strip()]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(_validate_user_id(user_id))
        try:
            with self._connect() as connection:
                row = connection.execute(sql, params).fetchone()
        except sqlite3.Error as exc:
            raise JobStorageError("could not read the job: %s" % exc) from exc
        return _row_to_dict(row) if row else None

    def _select(
        self, user: str, status: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        self._ensure_schema()
        capped = max(1, min(as_int(limit, 200), 1000))

        sql = "SELECT * FROM jobs WHERE user_id = ?"
        params: List[Any] = [user]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        # LIMIT is bound, not interpolated, and clamped besides.
        sql += " ORDER BY datetime(saved_date) DESC, job_id DESC LIMIT ?"
        params.append(capped)

        try:
            with self._connect() as connection:
                rows = connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise JobStorageError("could not read saved jobs: %s" % exc) from exc
        return [_row_to_dict(row) for row in rows]

    def count_user_jobs(self, user_id: str = DEFAULT_USER_ID) -> int:
        """How many adverts this user has saved."""
        self._ensure_schema()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ?",
                    (_validate_user_id(user_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise JobStorageError("could not count saved jobs: %s" % exc) from exc
        return int(row["n"]) if row else 0

    def status_counts(self, user_id: str = DEFAULT_USER_ID) -> Dict[str, int]:
        """How many jobs sit in each state. Every status appears, including zeros.

        Reporting only the non-empty ones would make a pipeline look emptier
        than it is and force every caller to fill the gaps themselves.
        """
        self._ensure_schema()
        counts = {status: 0 for status in STATUSES}
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT status, COUNT(*) AS n FROM jobs WHERE user_id = ? GROUP BY status",
                    (_validate_user_id(user_id),),
                ).fetchall()
        except sqlite3.Error as exc:
            raise JobStorageError("could not count by status: %s" % exc) from exc
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = int(row["n"])
        return counts

    def clear_user(self, user_id: str = DEFAULT_USER_ID) -> int:
        """Delete everything this user saved. Returns how many rows went."""
        self._ensure_schema()
        try:
            with self._connect() as connection:
                return int(
                    connection.execute(
                        "DELETE FROM jobs WHERE user_id = ?",
                        (_validate_user_id(user_id),),
                    ).rowcount
                )
        except sqlite3.Error as exc:
            raise JobStorageError("could not clear saved jobs: %s" % exc) from exc


def _new_id() -> str:
    return "job_%s" % uuid.uuid4().hex[:12]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    record = dict(row)
    record["analysis"] = _loads(record.get("analysis"))
    record["requirements"] = _loads(record.get("requirements"))
    return record


#: Shared instance pointing at the configured database.
job_storage = JobStorage()
