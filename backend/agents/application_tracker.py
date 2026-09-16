"""Applications, their events, and the timeline they add up to.

An application is not a job. A job is an advert that exists in the world; an
application is *this person's attempt at it*, and it has a life of its own -
sent, interviewed, rejected, offered. Keeping them in separate tables means
you can apply to the same advert twice (people do, after a year) without
either attempt overwriting the other.

The events table is append-only on purpose. ``status`` on the application row
tells you where things stand now; the event log tells you how they got there,
and that history is what the analytics module needs to say anything useful
about *rates* rather than *totals*. A status field alone can tell you that two
applications reached interview. Only the log can tell you it took eleven days.

**On ``user_id``.** As everywhere else in this project it now identifies a real
owner: the API reads it from a signed session cookie and never from the request
body or query string. This module still validates it and parameterises every
query, because a storage layer should not rely on its caller having got the
authorisation right.
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
from utils.error_handling import DatabaseError
from utils.logger import get_logger, observed
from utils.validation import as_dict, as_float, as_int

logger = get_logger(__name__)

__all__ = [
    "ApplicationTracker",
    "application_tracker",
    "ApplicationError",
    "UnknownApplicationError",
    "UnknownEventError",
    "UnknownStatusError",
    "APPLICATION_STATUSES",
    "EVENTS",
    "STATUS_ALIASES",
    "DEFAULT_USER_ID",
]


class ApplicationError(DatabaseError):
    """Something could not be stored or read."""


class UnknownApplicationError(ApplicationError, KeyError):
    """No application with that id (for this user)."""


class UnknownEventError(ApplicationError, ValueError):
    """An event outside the known set was supplied."""


class UnknownStatusError(ApplicationError, ValueError):
    """A status outside the known set was supplied."""


#: The lifecycle, in order. ``rejected`` and ``offer`` are terminal.
APPLICATION_STATUSES = ("draft", "sent", "interview", "rejected", "offer")

#: Statuses that end the story. Used to work out what is still in flight.
TERMINAL_STATUSES = ("rejected", "offer")

#: Events worth recording. The first seven are the ones a user causes; the
#: last two this module writes for itself, so that every row's history starts
#: at its beginning rather than at the first thing anyone happened to log.
EVENTS = (
    "analysis_completed",
    "resume_tailored",
    "application_sent",
    "interview_scheduled",
    "interview_completed",
    "rejected",
    "offer_received",
    "created",
    "status_changed",
)

#: Event names that people naturally pass where a *status* is wanted - the
#: brief's own example calls ``update_application_status(..., "interview_
#: scheduled")``, which is an event, not one of the five states. Rejecting
#: that would be pedantry: the intent is unambiguous. Translating it is not
#: guessing, it is accepting a synonym, and the event log records the word
#: the caller actually used.
STATUS_ALIASES = {
    "interview_scheduled": "interview",
    "interview_completed": "interview",
    "offer_received": "offer",
    "offer": "offer",
    "applied": "sent",
    "application_sent": "sent",
    "sent": "sent",
    "rejected": "rejected",
    "draft": "draft",
    "interview": "interview",
}

#: The event each status change implies, when the caller does not say.
_STATUS_EVENT = {
    "sent": "application_sent",
    "interview": "interview_scheduled",
    "rejected": "rejected",
    "offer": "offer_received",
}

DEFAULT_USER_ID = "local"

_USER_ID_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    app_id               TEXT PRIMARY KEY,
    user_id              TEXT NOT NULL,
    job_id               TEXT NOT NULL DEFAULT '',
    job_title            TEXT NOT NULL DEFAULT '',
    company              TEXT NOT NULL DEFAULT '',
    match_score          REAL,
    gaps_identified      TEXT NOT NULL DEFAULT '[]',
    resume_version       TEXT NOT NULL DEFAULT '',
    interview_prep_score REAL,
    status               TEXT NOT NULL DEFAULT 'draft',
    created_date         TEXT NOT NULL,
    updated_date         TEXT NOT NULL,
    notes                TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_apps_user   ON applications(user_id);
CREATE INDEX IF NOT EXISTS idx_apps_status ON applications(user_id, status);

CREATE TABLE IF NOT EXISTS application_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL
        REFERENCES applications(app_id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,
    details        TEXT NOT NULL DEFAULT '{}',
    status_after   TEXT NOT NULL DEFAULT '',
    created_date   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_app ON application_events(application_id);

-- Optional per the brief, but interviews are where applications are actually
-- won and lost, and "how did the last one go" is unanswerable without it.
CREATE TABLE IF NOT EXISTS interviews (
    interview_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id     TEXT NOT NULL
        REFERENCES applications(app_id) ON DELETE CASCADE,
    interview_date     TEXT NOT NULL DEFAULT '',
    interviewer        TEXT NOT NULL DEFAULT '',
    performance_rating TEXT NOT NULL DEFAULT '',
    notes              TEXT NOT NULL DEFAULT '',
    next_round         INTEGER NOT NULL DEFAULT 0,
    created_date       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interviews_app ON interviews(application_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return "app_%s" % uuid.uuid4().hex[:12]


def _validate_user_id(user_id: Any) -> str:
    """Constrain the namespace key. Not authentication - see the module docstring."""
    text = str(user_id or "").strip() or DEFAULT_USER_ID
    if not _USER_ID_RE.match(text):
        raise ApplicationError(
            "user_id must be 1-64 characters of letters, digits, dot, dash, "
            "underscore or @"
        )
    return text


def _validate_status(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    resolved = STATUS_ALIASES.get(text)
    if resolved is None:
        raise UnknownStatusError(
            "unknown status %r; expected one of %s"
            % (value, ", ".join(APPLICATION_STATUSES))
        )
    return resolved


def _validate_event(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if text not in EVENTS:
        raise UnknownEventError(
            "unknown event %r; expected one of %s" % (value, ", ".join(EVENTS))
        )
    return text


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, default=str)
    except (TypeError, ValueError):
        return "{}"


def _loads(value: Any, fallback: Any = None) -> Any:
    if not value:
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {} if fallback is None else fallback


def _score_or_none(value: Any) -> Optional[float]:
    """A score, or ``None`` - never a silent zero.

    Zero and "not measured" are different facts, and averaging the second as
    though it were the first drags every average down.
    """
    if value is None or value == "":
        return None
    number = as_float(value, -1.0)
    return None if number < 0 else number


def _day(timestamp: str) -> str:
    """The date part, which is what a timeline shows."""
    return (timestamp or "")[:10]


class ApplicationTracker:
    """Applications, their event log, and the timeline that results.

    Args:
        db_path: Where the database lives. Defaults to ``settings.JOBS_DB_PATH``
            so applications sit beside the jobs they refer to and can be read
            in one query. Tests pass a temp path.
    """

    label = "Application Tracker"

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(settings.JOBS_DB_PATH)
        self._lock = threading.Lock()
        self._ready = False

    # -- Connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """A fresh connection per operation; see JobStorage for the reasoning."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
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
                raise ApplicationError(
                    "could not create the applications tables: %s" % exc
                ) from exc
            self._ready = True

    # -- Writes ----------------------------------------------------------

    @observed("create_application")
    def create_application(
        self,
        user_id: str,
        job_id: str,
        analysis_data: Optional[Dict[str, Any]] = None,
        status: str = "draft",
    ) -> str:
        """Start tracking an attempt at one job. Returns the new ``app_id``.

        ``analysis_data`` is whatever the analysis pipeline produced. Nothing
        in it is required: an application can be created before any analysis
        has run, and the fields simply stay empty rather than being filled
        with zeros that would later be averaged as though they were measured.
        """
        self._ensure_schema()
        user = _validate_user_id(user_id)
        job = str(job_id or "").strip()
        if not job:
            raise ApplicationError("job_id is required to create an application")

        data = as_dict(analysis_data, "analysis_data")
        checked = _validate_status(status)
        app_id = _new_id()
        now = _now()

        row = (
            app_id,
            user,
            job,
            str(data.get("job_title") or data.get("title") or "").strip(),
            str(data.get("company") or "").strip(),
            _score_or_none(data.get("match_score")),
            _dumps(self._gaps(data)),
            str(data.get("resume_version") or data.get("resume_version_used") or "").strip(),
            _score_or_none(data.get("interview_prep_score")),
            checked,
            now,
            now,
            str(data.get("notes") or ""),
        )

        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO applications (
                           app_id, user_id, job_id, job_title, company,
                           match_score, gaps_identified, resume_version,
                           interview_prep_score, status, created_date,
                           updated_date, notes
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    row,
                )
                self._insert_event(
                    connection, app_id, "created", {"job_id": job}, checked, now
                )
        except sqlite3.Error as exc:
            raise ApplicationError("could not create the application: %s" % exc) from exc

        logger.info("Created application %s for %s (job %s)", app_id, user, job)
        return app_id

    @staticmethod
    def _gaps(data: Dict[str, Any]) -> List[str]:
        """Gap names, however the analysis pipeline happened to spell them.

        Different stages of this project return gaps as bare strings, as
        ``{"skill": ...}`` and as ``{"name": ...}``. Normalising here means
        the analytics module counts one vocabulary rather than three.
        """
        raw = data.get("gaps_identified")
        if raw is None:
            raw = data.get("gaps") or data.get("missing_skills") or []
        if isinstance(raw, dict):
            raw = raw.get("critical") or raw.get("all") or list(raw.keys())
        if isinstance(raw, str):
            raw = [raw]
        names: List[str] = []
        for item in raw or []:
            if isinstance(item, dict):
                name = item.get("skill") or item.get("name") or item.get("gap")
            else:
                name = item
            text = str(name or "").strip()
            if text and text not in names:
                names.append(text)
        return names

    def log_application_event(
        self,
        app_id: str,
        event: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append one event to an application's history. Returns the event id.

        The log is append-only: nothing here edits or deletes an earlier
        event. A history that can be quietly rewritten is not a history.
        """
        self._ensure_schema()
        checked = _validate_event(event)
        payload = as_dict(details, "details")
        app_id = str(app_id or "").strip()

        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT status FROM applications WHERE app_id = ?", (app_id,)
                ).fetchone()
                if row is None:
                    raise UnknownApplicationError("no application %r" % app_id)
                event_id = self._insert_event(
                    connection, app_id, checked, payload, row["status"], _now()
                )
                if checked == "interview_completed":
                    self._insert_interview(connection, app_id, payload)
        except sqlite3.Error as exc:
            raise ApplicationError("could not log the event: %s" % exc) from exc

        logger.info("Application %s: %s", app_id, checked)
        return event_id

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        app_id: str,
        event: str,
        details: Dict[str, Any],
        status_after: str,
        when: str,
    ) -> int:
        cursor = connection.execute(
            """INSERT INTO application_events (
                   application_id, event_type, details, status_after, created_date
               ) VALUES (?,?,?,?,?)""",
            (app_id, event, _dumps(details), status_after, when),
        )
        return int(cursor.lastrowid or 0)

    @staticmethod
    def _insert_interview(
        connection: sqlite3.Connection, app_id: str, details: Dict[str, Any]
    ) -> None:
        """Record the interview detail carried on an ``interview_completed`` event."""
        next_round = details.get("next_round")
        if isinstance(next_round, str):
            # The brief's own example passes the *string* "True".
            next_round = next_round.strip().lower() in ("true", "yes", "1")
        connection.execute(
            """INSERT INTO interviews (
                   application_id, interview_date, interviewer,
                   performance_rating, notes, next_round, created_date
               ) VALUES (?,?,?,?,?,?,?)""",
            (
                app_id,
                str(details.get("interview_date") or _day(_now())),
                str(details.get("interviewer") or ""),
                str(details.get("performance") or details.get("performance_rating") or ""),
                str(details.get("notes") or ""),
                1 if next_round else 0,
                _now(),
            ),
        )

    def update_application_status(
        self,
        app_id: str,
        new_status: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Move an application along and log the move in one transaction.

        Both halves happen or neither does. A status that changed without an
        event would leave a timeline with a hole in it, and the analytics
        module reads the timeline.
        """
        self._ensure_schema()
        checked = _validate_status(new_status)
        payload = as_dict(details, "details")
        app_id = str(app_id or "").strip()
        now = _now()

        # The word the caller used, when it is a recognised event, beats the
        # generic one the status implies: "interview_completed" and
        # "interview_scheduled" both mean status=interview but are very
        # different facts, and only one of them has happened.
        spelled = str(new_status or "").strip().lower().replace(" ", "_")
        event = spelled if spelled in EVENTS else _STATUS_EVENT.get(checked, "status_changed")

        try:
            with self._connect() as connection:
                sql = "SELECT status FROM applications WHERE app_id = ?"
                params: List[Any] = [app_id]
                if user_id is not None:
                    sql += " AND user_id = ?"
                    params.append(_validate_user_id(user_id))
                row = connection.execute(sql, params).fetchone()
                if row is None:
                    return False

                connection.execute(
                    "UPDATE applications SET status = ?, updated_date = ? WHERE app_id = ?",
                    (checked, now, app_id),
                )
                payload = dict(payload)
                payload.setdefault("from", row["status"])
                payload.setdefault("to", checked)
                self._insert_event(connection, app_id, event, payload, checked, now)
                if event == "interview_completed":
                    self._insert_interview(connection, app_id, payload)
        except sqlite3.Error as exc:
            raise ApplicationError("could not update the application: %s" % exc) from exc

        logger.info("Application %s: %s -> %s", app_id, row["status"], checked)
        return True

    def add_note(self, app_id: str, note: str) -> bool:
        """Attach a note. Returns False if there is no such application."""
        self._ensure_schema()
        try:
            with self._connect() as connection:
                return bool(
                    connection.execute(
                        "UPDATE applications SET notes = ?, updated_date = ? WHERE app_id = ?",
                        (str(note or ""), _now(), str(app_id or "").strip()),
                    ).rowcount
                )
        except sqlite3.Error as exc:
            raise ApplicationError("could not add the note: %s" % exc) from exc

    def delete_application(self, app_id: str, user_id: Optional[str] = None) -> bool:
        """Remove an application and, by cascade, its events and interviews."""
        self._ensure_schema()
        sql = "DELETE FROM applications WHERE app_id = ?"
        params: List[Any] = [str(app_id or "").strip()]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(_validate_user_id(user_id))
        try:
            with self._connect() as connection:
                return bool(connection.execute(sql, params).rowcount)
        except sqlite3.Error as exc:
            raise ApplicationError("could not delete the application: %s" % exc) from exc

    # -- Reads -----------------------------------------------------------

    def get_application_history(
        self, user_id: str = DEFAULT_USER_ID, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Every application this user has, each with its timeline.

        One query for the applications and one for all their events, rather
        than one query per application. With fifty applications the naive
        version issues fifty-one round trips to say the same thing.
        """
        self._ensure_schema()
        user = _validate_user_id(user_id)
        capped = max(1, min(as_int(limit, 200), 1000))

        try:
            with self._connect() as connection:
                rows = connection.execute(
                    # rowid breaks ties, not app_id. Timestamps are stored to
                    # the second, and several applications created in one
                    # sitting share one - ordering those by a random uuid
                    # meant the dashboard shuffled them on every refresh.
                    """SELECT * FROM applications WHERE user_id = ?
                       ORDER BY datetime(created_date) DESC, rowid DESC LIMIT ?""",
                    (user, capped),
                ).fetchall()
                if not rows:
                    return []
                ids = [row["app_id"] for row in rows]
                placeholders = ",".join("?" * len(ids))
                events = connection.execute(
                    "SELECT * FROM application_events WHERE application_id IN (%s) "
                    "ORDER BY datetime(created_date) ASC, event_id ASC" % placeholders,
                    ids,
                ).fetchall()
        except sqlite3.Error as exc:
            raise ApplicationError("could not read applications: %s" % exc) from exc

        timelines: Dict[str, List[Dict[str, Any]]] = {}
        for event in events:
            timelines.setdefault(event["application_id"], []).append(
                {
                    "date": _day(event["created_date"]),
                    "timestamp": event["created_date"],
                    "event": event["event_type"],
                    "status": event["status_after"],
                    "details": _loads(event["details"]),
                }
            )

        return [self._to_record(row, timelines.get(row["app_id"], [])) for row in rows]

    def get_application(
        self, app_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """One application with its full timeline, or ``None``."""
        self._ensure_schema()
        sql = "SELECT * FROM applications WHERE app_id = ?"
        params: List[Any] = [str(app_id or "").strip()]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(_validate_user_id(user_id))
        try:
            with self._connect() as connection:
                row = connection.execute(sql, params).fetchone()
                if row is None:
                    return None
                events = connection.execute(
                    """SELECT * FROM application_events WHERE application_id = ?
                       ORDER BY datetime(created_date) ASC, event_id ASC""",
                    (row["app_id"],),
                ).fetchall()
                interviews = connection.execute(
                    """SELECT * FROM interviews WHERE application_id = ?
                       ORDER BY interview_date ASC, interview_id ASC""",
                    (row["app_id"],),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ApplicationError("could not read the application: %s" % exc) from exc

        timeline = [
            {
                "date": _day(event["created_date"]),
                "timestamp": event["created_date"],
                "event": event["event_type"],
                "status": event["status_after"],
                "details": _loads(event["details"]),
            }
            for event in events
        ]
        record = self._to_record(row, timeline)
        record["interviews"] = [
            {
                "interview_date": item["interview_date"],
                "interviewer": item["interviewer"],
                "performance_rating": item["performance_rating"],
                "notes": item["notes"],
                "next_round": bool(item["next_round"]),
            }
            for item in interviews
        ]
        return record

    def get_applications_by_status(
        self, user_id: str, status: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Everything sitting in one state - all the interviews, say."""
        checked = _validate_status(status)
        return [
            record
            for record in self.get_application_history(user_id, limit)
            if record["current_status"] == checked
        ]

    @staticmethod
    def _to_record(row: sqlite3.Row, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "app_id": row["app_id"],
            "user_id": row["user_id"],
            "job_id": row["job_id"],
            "job_title": row["job_title"],
            "company": row["company"],
            "match_score": row["match_score"],
            "gaps_identified": _loads(row["gaps_identified"], []),
            "resume_version_used": row["resume_version"],
            "interview_prep_score": row["interview_prep_score"],
            "current_status": row["status"],
            "created_date": row["created_date"],
            "updated_date": row["updated_date"],
            "notes": row["notes"],
            "timeline": timeline,
        }

    def count_applications(self, user_id: str = DEFAULT_USER_ID) -> int:
        """Every application this user has, drafts included.

        Drafts are counted here because this answers "how many rows exist".
        The analytics layer is the one that excludes them from rate
        denominators, where counting an unsent draft would read as a failure.
        """
        self._ensure_schema()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM applications WHERE user_id = ?",
                    (_validate_user_id(user_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ApplicationError("could not count applications: %s" % exc) from exc
        return int(row["n"]) if row else 0

    def status_counts(self, user_id: str = DEFAULT_USER_ID) -> Dict[str, int]:
        """How many applications sit in each state, zeros included."""
        self._ensure_schema()
        counts = {status: 0 for status in APPLICATION_STATUSES}
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT status, COUNT(*) AS n FROM applications
                       WHERE user_id = ? GROUP BY status""",
                    (_validate_user_id(user_id),),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ApplicationError("could not count by status: %s" % exc) from exc
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = int(row["n"])
        return counts

    def clear_user(self, user_id: str = DEFAULT_USER_ID) -> int:
        """Delete this user's applications, and their events by cascade."""
        self._ensure_schema()
        try:
            with self._connect() as connection:
                return int(
                    connection.execute(
                        "DELETE FROM applications WHERE user_id = ?",
                        (_validate_user_id(user_id),),
                    ).rowcount
                )
        except sqlite3.Error as exc:
            raise ApplicationError("could not clear applications: %s" % exc) from exc


#: Shared instance pointing at the configured database.
application_tracker = ApplicationTracker()
