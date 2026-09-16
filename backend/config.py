"""Application configuration for CareerPilot AI.

Every value here can be overridden by an environment variable of the same name,
or by a line in ``backend/.env``. See ``.env.example`` for the full list.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LLM_PROVIDERS = ("ollama", "claude", "gemini", "auto")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class Settings(BaseSettings):
    """Settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- API configuration -------------------------------------------------
    APP_NAME: str = "CareerPilot AI"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    # 3100 is here because 3000 is often already taken by another project, and
    # `next dev -p 3100` then fails on CORS rather than on the port.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3100",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3100",
        "http://127.0.0.1:5173",
    ]

    # --- Storage paths -----------------------------------------------------
    # Relative values are resolved against BASE_DIR, not the working directory,
    # so `./data/chroma` in .env means the same folder however the app is launched.
    UPLOAD_DIR: Path = DATA_DIR / "uploads"
    CHROMA_DB_PATH: Path = DATA_DIR / "chroma"
    LOG_DIR: Path = DATA_DIR / "logs"

    # --- Upload limits -----------------------------------------------------
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt", ".md"}

    # --- RAG settings ------------------------------------------------------
    #: Short form of `sentence-transformers/all-MiniLM-L6-v2`; the library
    #: expands it. 384 dimensions, runs on CPU, no API key needed.
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    CHUNK_SIZE: int = 250
    CHUNK_OVERLAP: int = 50
    TOP_K_RESULTS: int = 5

    # --- Database (Chroma vector store) ------------------------------------
    #: The path itself lives under "Storage paths" above, with the other
    #: directories, so that ensure_directories() has them all in one place.
    CHROMA_COLLECTION_NAME: str = "resumes"
    CHROMA_DISTANCE: str = "cosine"

    # --- LLM settings ------------------------------------------------------
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "mistral"
    #: Accepts the older name LLM_BASE_URL too, so existing .env files keep working.
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "LLM_BASE_URL"),
    )
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT_SECONDS: int = 120
    #: Seconds to wait when probing whether Ollama is up. Kept short so a dead
    #: daemon degrades the workflow quickly instead of stalling every request.
    LLM_HEALTHCHECK_TIMEOUT: float = 2.0
    LLM_MAX_RETRIES: int = 2

    # --- Claude fallback ---------------------------------------------------
    LLM_FALLBACK_ENABLED: bool = True
    ANTHROPIC_API_KEY: Optional[str] = None
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"

    # --- Gemini ------------------------------------------------------------
    #: Flash-lite rather than Pro. Every prompt in this app asks for a short
    #: structured answer, none of them need deep reasoning, and the free tier
    #: is what makes running this without a bill possible.
    #:
    #: The free tier is small and counted per model per day: measured against a
    #: real key, "gemini-2.5-flash" allows twenty requests a day, and one full
    #: analysis spends roughly six. Check what a name actually supports with
    #: ListModels before setting it -- "gemini-2.0-flash" was the first choice
    #: here and is retired, which surfaces only as a 404.
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"

    # --- Logging -----------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    #: Turn off to keep logs on the console only -- useful in containers, where
    #: writing to a rotating file inside the image is wasted work.
    LOG_TO_FILE: bool = True
    LOG_FILE_NAME: str = "app.log"
    LOG_MAX_BYTES: int = 5 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 3

    # --- Job discovery -----------------------------------------------------
    #: Where saved jobs live. SQLite because the data is small, relational and
    #: single-writer; a server would be ceremony for a few hundred rows.
    JOBS_DB_PATH: Path = BASE_DIR / "data/jobs.db"

    # --- Accounts ----------------------------------------------------------
    #: Credentials live in their own file rather than beside the job data, so
    #: the database holding password hashes can be permissioned, backed up and
    #: deleted separately from the one holding adverts.
    AUTH_DB_PATH: Path = BASE_DIR / "data/users.db"

    #: How long a login lasts before the token stops being accepted. Sessions
    #: are revocable server-side, so this is a backstop rather than the only
    #: way out -- logging out deletes the row immediately.
    SESSION_TTL_HOURS: int = 24 * 14

    #: Identifies us to every job board we call. A real contact address is the
    #: minimum courtesy when fetching someone else's data: it lets an operator
    #: who dislikes the traffic ask us to stop rather than silently ban us.
    #: Override this before running anything at volume.
    JOB_SCRAPER_USER_AGENT: str = (
        "CareerPilotAI/0.1 (+https://github.com/example/career-pilot-ai)"
    )

    #: Outbound fetches are short-lived by design. A job board that has not
    #: answered in ten seconds is not going to, and the caller is waiting.
    JOB_FETCH_TIMEOUT_SECONDS: float = 10.0

    #: Hard ceiling on any single response we will read into memory. Without
    #: it a hostile or broken feed can exhaust the process.
    #:
    #: Raised from 2 MB after Arbeitnow began failing on every single search.
    #: Its API returns the whole job board as one document rather than a page
    #: at a time -- measured at 2.21 MB, and it only grows -- so a source that
    #: was working silently dropped out and the app ran on three sources
    #: instead of four. The cap is still a cap: the body is streamed and
    #: counted chunk by chunk, and Content-Length is still not trusted. This
    #: only buys headroom for a legitimate feed that outgrew the old number.
    JOB_FETCH_MAX_BYTES: int = 8 * 1024 * 1024

    #: Attempts per fetch, including the first. Only connection failures,
    #: timeouts, 429 and 5xx are retried: a 404 is not going to change, and
    #: retrying it only makes the caller wait longer for the same answer.
    JOB_FETCH_MAX_ATTEMPTS: int = 3

    #: Base of the exponential wait between fetch attempts, in seconds. With
    #: three attempts the waits are roughly 1s then 2s, plus jitter.
    JOB_FETCH_BACKOFF_FACTOR: float = 2.0

    #: Minimum gap between two requests to the same host. Politeness, and it
    #: also stops a loop in our own code hammering someone else's server.
    JOB_FETCH_MIN_INTERVAL_SECONDS: float = 1.0

    #: How long a fetched source stays reusable. Remotive's own API response
    #: asks callers not to poll more than about four times a day; six hours
    #: honours that, and job adverts do not change faster than that anyway.
    JOB_CACHE_TTL_SECONDS: int = 6 * 60 * 60

    #: Adzuna credentials, from https://developer.adzuna.com. Empty by
    #: default, and the source simply does not run without them -- no error,
    #: no warning, because an unconfigured optional source is not a fault.
    #:
    #: Adzuna licenses its listings from the boards and employers themselves
    #: and publishes an API for exactly this use. That is the difference
    #: between this and the boards named in ``CLOSED_JOB_BOARDS``: here the
    #: publisher is offering the data, rather than forbidding its collection.
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""

    #: Obey robots.txt. Settable only so tests can run without a network.
    JOB_RESPECT_ROBOTS: bool = True

    #: Whether the discovery endpoints may reach the network at all. Off means
    #: the API still works and returns nothing, which is what CI wants.
    JOB_DISCOVERY_ENABLED: bool = True

    # --- Validation --------------------------------------------------------
    @field_validator("UPLOAD_DIR", "CHROMA_DB_PATH", "LOG_DIR", "JOBS_DB_PATH", "AUTH_DB_PATH")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BASE_DIR / value).resolve()

    @field_validator("LLM_PROVIDER")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in LLM_PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER must be one of {LLM_PROVIDERS}, got {value!r}"
            )
        return provider

    @field_validator("LOG_LEVEL")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {LOG_LEVELS}, got {value!r}")
        return level

    @field_validator("ALLOWED_EXTENSIONS")
    @classmethod
    def _normalise_extensions(cls, value: set) -> set:
        return {
            item if item.startswith(".") else f".{item}"
            for item in (str(raw).strip().lower() for raw in value)
            if item
        }

    # --- Derived values ----------------------------------------------------
    @property
    def LLM_BASE_URL(self) -> str:  # noqa: N802 - kept for backwards compatibility
        """Deprecated alias for :attr:`OLLAMA_BASE_URL`."""
        return self.OLLAMA_BASE_URL

    @property
    def max_upload_size_bytes(self) -> int:
        """The upload limit in bytes, so callers need not repeat the arithmetic."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def log_file(self) -> Path:
        """Full path to the log file, derived so the directory stays configurable."""
        return self.LOG_DIR / self.LOG_FILE_NAME

    def ensure_directories(self) -> None:
        """Create the directories the app writes to."""
        for path in (self.UPLOAD_DIR, self.CHROMA_DB_PATH, self.LOG_DIR):
            path.mkdir(parents=True, exist_ok=True)
        # The jobs database is a file, not a directory; it is its parent that
        # has to exist before SQLite will open it.
        self.JOBS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    def summary(self) -> dict:
        """Startup-log view of the configuration.

        Secrets are reported as present or absent, never echoed.
        """
        return {
            "app": f"{self.APP_NAME} v{self.APP_VERSION}",
            "debug": self.DEBUG,
            "llm_provider": self.LLM_PROVIDER,
            "llm_model": self.LLM_MODEL,
            "ollama_base_url": self.OLLAMA_BASE_URL,
            "claude_key_set": bool(self.ANTHROPIC_API_KEY),
            "gemini_key_set": bool(self.GEMINI_API_KEY),
            "embedding_model": self.EMBEDDING_MODEL,
            "chroma_db_path": str(self.CHROMA_DB_PATH),
            "upload_dir": str(self.UPLOAD_DIR),
            "log_level": self.LOG_LEVEL,
        }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide ``Settings``, reading the environment once.

    Cached deliberately. Every caller gets the *same* object, which is what
    makes the module-level ``settings`` singleton below safe to monkeypatch in
    tests: patch an attribute there and every reader sees it. Were this to
    build a fresh instance per call, a patched setting would silently apply to
    one caller and not the next.
    """
    return Settings()


settings = get_settings()


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    import json

    settings.ensure_directories()
    print(json.dumps(settings.summary(), indent=2))
