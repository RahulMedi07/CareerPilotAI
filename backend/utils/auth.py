"""Accounts, passwords and sessions.

Three deliberate choices, each of which has a cheaper alternative that would
have been worse:

**Passwords are hashed with PBKDF2-HMAC-SHA256, not stored and not encrypted.**
Encryption is reversible, which is the whole problem -- a key that can decrypt
a password file is a key that can be stolen. ``scrypt`` and ``argon2`` are both
better algorithms, but ``hashlib.scrypt`` is unavailable on this machine's
LibreSSL build and ``argon2`` means a new dependency. PBKDF2 at
:data:`PBKDF2_ITERATIONS` is what OWASP recommends when those are out of reach,
and it costs about 0.18s per attempt here -- slow enough to make guessing
expensive, fast enough that nobody notices logging in.

**Session tokens are opaque random strings, not JWTs.** A JWT cannot be
revoked without keeping a server-side list of the ones you have revoked, at
which point you have a session table anyway and a signature you still have to
verify. Logging out here deletes a row, and the token stops working the
instant it does.

**Only the hash of a token is stored.** The token is shown to the browser once
and never persisted in readable form, so a copy of this database does not let
anyone resume a live session.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "AuthError",
    "DuplicateUserError",
    "InvalidCredentialsError",
    "WeakPasswordError",
    "PBKDF2_ITERATIONS",
    "MIN_PASSWORD_LENGTH",
    "TOKEN_BYTES",
    "UserStore",
    "user_store",
]

#: OWASP's floor for PBKDF2-HMAC-SHA256. Measured at 0.18s on this machine,
#: which is the point of it: every guess an attacker makes costs that too.
PBKDF2_ITERATIONS = 600_000

#: 16 bytes, per NIST SP 800-132. The salt is per-user and stored in the clear
#: beside the hash -- it exists to stop one rainbow table covering every
#: account at once, not to be a secret.
SALT_BYTES = 16

#: 256 bits of session token. Long enough that guessing one is not a strategy.
TOKEN_BYTES = 32

#: Short passwords are the single most common way an account is lost. Eight is
#: NIST SP 800-63B's minimum; no composition rules beyond it, because forcing
#: a digit and a symbol reliably produces "Password1!" and nothing safer.
MIN_PASSWORD_LENGTH = 8

#: Anchored, and length-capped before the regex ever runs.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MAX_EMAIL_LENGTH = 254  # RFC 5321
_MAX_PASSWORD_LENGTH = 1024  # Refuse megabyte passwords; each costs 0.18s.
_MAX_NAME_LENGTH = 120

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    password_hash BLOB NOT NULL,
    salt          BLOB NOT NULL,
    iterations    INTEGER NOT NULL,
    created_date  TEXT NOT NULL,
    last_login    TEXT
);

-- Case-insensitive, so nobody registers Rahul@x.com over rahul@x.com and then
-- cannot work out which of the two they typed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(LOWER(email));

CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_date TEXT NOT NULL,
    expires_date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_date);
"""


class AuthError(Exception):
    """Base class, so callers can catch every failure from this module."""


class DuplicateUserError(AuthError):
    """That email already has an account."""


class InvalidCredentialsError(AuthError):
    """Wrong email, wrong password, or an account that does not exist.

    One exception covers all three on purpose. Telling someone "no such
    account" confirms which addresses are registered, which is how a list of
    emails becomes a list of *this app's users* before any password is tried.
    """


class WeakPasswordError(AuthError):
    """The password is too short, too long, or blank."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def hash_password(
    password: str, salt: Optional[bytes] = None, iterations: Optional[int] = None
) -> Dict[str, Any]:
    """Derive a verifier for ``password``.

    ``iterations`` is stored per row rather than read from a constant at
    verification time. When the recommended count rises, existing rows keep
    verifying against the number they were created with instead of every
    account locking out at once.

    It defaults to ``None`` rather than to ``PBKDF2_ITERATIONS`` directly
    because a default argument is bound once at import: writing the constant
    here would freeze the cost at whatever it was when the module loaded, and
    changing it afterwards would silently do nothing.
    """
    if iterations is None:
        iterations = PBKDF2_ITERATIONS
    if salt is None:
        salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return {"password_hash": derived, "salt": salt, "iterations": iterations}


def verify_password(
    password: str, password_hash: bytes, salt: bytes, iterations: int
) -> bool:
    """Constant-time check.

    ``compare_digest`` and not ``==``: a plain comparison returns as soon as
    two bytes differ, and the time it took is a measurement of how much of the
    hash was guessed correctly.
    """
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, password_hash)


def hash_token(token: str) -> str:
    """SHA-256 of a session token.

    Plain SHA-256 rather than PBKDF2 because a token is 256 random bits, not a
    human-chosen word. There is no dictionary to slow an attacker down
    against, so stretching would only slow down every legitimate request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_email(email: str) -> str:
    return str(email or "").strip().lower()


def validate_password(password: str) -> str:
    # These strings are shown to the user verbatim by /api/auth/signup.
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            "Password must be at least %d characters." % MIN_PASSWORD_LENGTH
        )
    if len(text) > _MAX_PASSWORD_LENGTH:
        raise WeakPasswordError("That password is too long.")
    return text


def validate_email(email: str) -> str:
    text = normalise_email(email)
    if not text or len(text) > _MAX_EMAIL_LENGTH or not _EMAIL_RE.match(text):
        raise AuthError("That does not look like an email address.")
    return text


class UserStore:
    """Accounts and sessions in SQLite.

    Mirrors :class:`~agents.job_storage.JobStorage`: one connection per
    operation, WAL, foreign keys on. Shared connections are not thread-safe
    and this is called from FastAPI's worker threads.
    """

    label = "Accounts"

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(settings.AUTH_DB_PATH)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
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
                raise AuthError("could not create the accounts database: %s" % exc) from exc
            self._ready = True

    # -- Accounts --------------------------------------------------------

    def create_user(self, email: str, password: str, name: str = "") -> Dict[str, Any]:
        """Register an account and return it without the hash."""
        self._ensure_schema()
        address = validate_email(email)
        secret = validate_password(password)
        label = str(name or "").strip()[:_MAX_NAME_LENGTH]

        derived = hash_password(secret)
        user_id = "usr_%s" % secrets.token_hex(8)
        created = _iso(_now())

        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (user_id, email, name, password_hash, salt,"
                    " iterations, created_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        address,
                        label,
                        derived["password_hash"],
                        derived["salt"],
                        derived["iterations"],
                        created,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateUserError("An account already uses that email.") from exc
        except sqlite3.Error as exc:
            raise AuthError("could not create the account: %s" % exc) from exc

        logger.info("Registered account %s", user_id)
        return {"user_id": user_id, "email": address, "name": label, "created_date": created}

    def authenticate(self, email: str, password: str) -> Dict[str, Any]:
        """Check credentials and return the account.

        A missing account still pays for one password hash. Returning early
        would make "no such user" measurably faster than "wrong password",
        which is the same disclosure :class:`InvalidCredentialsError` exists to
        avoid, leaked through the clock instead of the message.
        """
        self._ensure_schema()
        address = normalise_email(email)
        secret = str(password or "")

        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM users WHERE LOWER(email) = ?", (address,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise AuthError("could not read the account: %s" % exc) from exc

        if row is None:
            hash_password(secret, salt=b"\x00" * SALT_BYTES)
            raise InvalidCredentialsError("email or password is wrong")

        if not verify_password(
            secret, row["password_hash"], row["salt"], int(row["iterations"])
        ):
            raise InvalidCredentialsError("email or password is wrong")

        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET last_login = ? WHERE user_id = ?",
                (_iso(_now()), row["user_id"]),
            )

        return {"user_id": row["user_id"], "email": row["email"], "name": row["name"]}

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, email, name, created_date, last_login FROM users"
                " WHERE user_id = ?",
                (str(user_id or ""),),
            ).fetchone()
        return dict(row) if row is not None else None

    def count_users(self) -> int:
        self._ensure_schema()
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    # -- Sessions --------------------------------------------------------

    def create_session(self, user_id: str, ttl_hours: Optional[int] = None) -> Dict[str, Any]:
        """Issue a token. The plain value is returned once and never stored."""
        self._ensure_schema()
        hours = int(ttl_hours if ttl_hours is not None else settings.SESSION_TTL_HOURS)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = _now()
        expires = now + timedelta(hours=hours)

        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, created_date, expires_date)"
                " VALUES (?, ?, ?, ?)",
                (hash_token(token), str(user_id), _iso(now), _iso(expires)),
            )
        return {"token": token, "expires_date": _iso(expires), "user_id": str(user_id)}

    def resolve_session(self, token: str) -> Optional[Dict[str, Any]]:
        """The account behind a token, or ``None``.

        Expiry is enforced here rather than only by the sweep, so a token
        outlives its welcome by exactly zero requests even if nothing has
        cleaned up yet.
        """
        if not token:
            return None
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT s.user_id, s.expires_date, u.email, u.name FROM sessions s"
                " JOIN users u ON u.user_id = s.user_id WHERE s.token_hash = ?",
                (hash_token(token),),
            ).fetchone()

        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_date"])
        except (TypeError, ValueError):
            return None
        if expires <= _now():
            self.delete_session(token)
            return None
        return {"user_id": row["user_id"], "email": row["email"], "name": row["name"]}

    def delete_session(self, token: str) -> bool:
        if not token:
            return False
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),)
            )
        return cursor.rowcount > 0

    def delete_expired_sessions(self) -> int:
        self._ensure_schema()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE expires_date <= ?", (_iso(_now()),)
            )
        return cursor.rowcount


#: Shared instance. Constructed lazily against the configured path, the same
#: way the job and application stores are.
user_store = UserStore()
