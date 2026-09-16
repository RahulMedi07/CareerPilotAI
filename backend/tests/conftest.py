"""Shared pytest fixtures."""

import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest
from fastapi.testclient import TestClient

from config import Settings, settings
from models.career_models import JobDescription

VECTOR_DIMENSIONS = 64


def _days_ago_iso(days: int) -> str:
    """An ISO date that many days in the past, as the scrapers emit."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


class HashingEmbedder:
    """Deterministic, offline stand-in for sentence-transformers.

    Hashes each token into a fixed-width bag-of-words vector and L2-normalises
    it. Documents that share vocabulary end up close together, which is all the
    retrieval tests need — and it never touches the network.
    """

    def __init__(self, dimensions: int = VECTOR_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: List[List[str]] = []

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        for token in "".join(c.lower() if c.isalnum() else " " for c in text).split():
            digest = hashlib.md5(token.encode()).digest()
            vector[digest[0] % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


SAMPLE_RESUME = """Jane Developer
jane.developer@example.com | +1 (555) 123-4567

Summary
Backend engineer with 7 years of experience building Python services.

Skills
Python, FastAPI, Docker, Kubernetes, PostgreSQL, LangChain

Experience
Senior Engineer at Acme Corp. Designed microservices handling 2M requests a day.
Built a retrieval augmented generation assistant on top of ChromaDB.

Education
BSc Computer Science, State University
"""

#: A job advert the sample resume partly matches: it names Python, FastAPI,
#: Docker and LangChain (all on the resume) plus Kubernetes and Terraform
#: (neither), so it exercises both the matched and the gap paths.
SAMPLE_JD = (
    "Senior AI Engineer at Acme.\n"
    "Required: Python, FastAPI, LangChain, Docker, Kubernetes.\n"
    "Preferred: AWS, Terraform, machine learning experience.\n"
    "You will build RAG pipelines end to end and lead a small team.\n"
    "5+ years of experience required.\n"
)

#: Two adverts for tests that need a job source: one the sample resume matches
#: well, one it does not. Shared so the shortlist threshold means the same
#: thing everywhere it is asserted.
#:
#: Both are dated, and dated relative to now. Discovery shows only adverts it
#: can prove were posted in the last seven days, so an undated pair here would
#: be filtered out before any test could look at them, and a fixed date would
#: quietly age out of the window and take the journey tests with it.
FAKE_JOBS: List[Dict[str, Any]] = [
    {
        "job_id": "fake-1",
        "title": "AI Engineer",
        "company": "Acme",
        "description": (
            "Required: Python, FastAPI, Docker, LangChain, RAG. "
            "Preferred: Kubernetes."
        ),
        "source": "test",
        "url": "https://example.invalid/1",
        "posted_date": _days_ago_iso(1),
        "days_old": 1,
    },
    {
        "job_id": "fake-2",
        "title": "Go Developer",
        "company": "Beta",
        "description": "Required: Golang, Kubernetes, Terraform, Rust.",
        "source": "test",
        "url": "https://example.invalid/2",
        "posted_date": _days_ago_iso(2),
        "days_old": 2,
    },
]


def fake_source(query: str = "", location: str = "remote", limit: int = 10):
    """Stand-in for the live scraper.

    Returns copies, so a caller that enriches or mutates the adverts cannot
    corrupt ``FAKE_JOBS`` for the next test.
    """
    return [dict(job) for job in FAKE_JOBS][:limit]


#: The real credentials, read once at import before anything patches them.
#: Used to recognise - and refuse - the user's own key wherever it surfaces.
_REAL_KEYS = frozenset(
    key
    for key in (
        settings.GEMINI_API_KEY,
        settings.ANTHROPIC_API_KEY,
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
        os.environ.get("ANTHROPIC_API_KEY"),
    )
    if key
)


def _blank_agent_credentials(monkeypatch):
    """Make the real API keys unusable for the whole test session.

    Patching ``settings`` alone is not enough. Around twenty agents are built
    at module scope, and each calls ``AgentConfig.from_settings()`` in
    ``__init__`` - which runs at import, long before any fixture. Those objects
    hold a copy of whatever key was in ``.env`` at import and keep using it no
    matter what ``settings`` says afterwards. This is the same trap the
    database singletons fall into, for the same reason.

    Walking the object graph to blank each one was tried first and is not
    reliable: composite agents such as ``CompleteWorkflow`` build sub-agents
    that hold configs several references deep, and the ones the walk missed
    kept calling the real API - 234 requests in a single run, enough for
    Google to answer 429.

    Guarding the credential *properties* on the class needs no walk and cannot
    be evaded, because every handler asks the same two questions before it
    calls out. Only the real keys are rejected, so a test is still free to
    build a config with a fake one and exercise the handler.

    This has to run at session scope. ``test_complete_workflow`` computes a
    workflow result in a *module*-scoped fixture, and pytest builds broader
    scopes first, so a function-scoped guard was applied too late: the fixture
    ran against a live model while the comparison inside the test ran against
    the fallback, and two tests asserting the two graphs agree failed with
    71.8 against 60.8.
    """
    from agents import AgentConfig

    def usable(value: Optional[str]) -> bool:
        # Mirrors the real property, which treats a whitespace-only key as
        # absent, and then additionally refuses the machine's own key.
        return bool(value and value.strip()) and value not in _REAL_KEYS

    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        AgentConfig,
        "has_gemini_credentials",
        property(lambda self: usable(self.gemini_api_key)),
    )
    monkeypatch.setattr(
        AgentConfig,
        "has_claude_credentials",
        property(lambda self: usable(self.claude_api_key)),
    )


@pytest.fixture(autouse=True, scope="session")
def no_real_credentials():
    """Session-wide guard so no test can spend the user's API quota."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        _blank_agent_credentials(monkeypatch)
        yield


@pytest.fixture(autouse=True, scope="session")
def no_local_env_file():
    """``Settings()`` must not read whichever ``.env`` is sitting on disk.

    The fixtures above patch the ``settings`` *singleton*, which leaves any
    test that constructs a fresh ``Settings()`` reading the real file. That
    made the result of the suite depend on an untracked file: on a machine
    whose ``.env`` was copied from ``.env.example`` -- which is what the README
    tells a new user to do -- ``OLLAMA_BASE_URL=http://localhost:11434`` beat
    the legacy ``LLM_BASE_URL`` alias a test was setting, and that test failed
    on a clean checkout while passing here.
    """
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point every writable path at a temp dir so tests never touch real data.

    The SQLite database needs more than a settings patch. ``JobStorage`` and
    ``ApplicationTracker`` both read ``settings.JOBS_DB_PATH`` once, in
    ``__init__``, and both are instantiated as module singletons at import
    time - which happens before any fixture runs. Patching the setting alone
    leaves those two objects pointing at ``backend/data/jobs.db``, so tests
    read and write the real database: counts come back polluted by whatever
    previous runs left behind, and a test that creates applications quietly
    appends to the user's own records. Each singleton is therefore repointed
    directly, and ``_ready`` is cleared so the schema is recreated in the new
    file rather than assumed to exist.

    Credentials are blanked for the same reason. Any agent built without an
    explicit config calls ``AgentConfig.from_settings()``, so the moment a real
    key existed in ``.env`` the suite started making live billed API calls: the
    run went from 22 seconds to minutes, and results depended on a third-party
    service being up. Tests that want a working model inject ``StubLLM``; tests
    that want the fallback path need these empty. Both environment variables
    are cleared too, because ``from_settings()`` reads them directly when the
    setting is unset.
    """
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CHROMA_DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(settings, "JOBS_DB_PATH", tmp_path / "jobs.db")

    # API keys are blanked by the session-scoped ``no_real_credentials``
    # fixture instead, which has to run earlier than this one.

    from agents.application_tracker import application_tracker
    from agents.job_storage import job_storage

    for store in (job_storage, application_tracker):
        monkeypatch.setattr(store, "db_path", tmp_path / "jobs.db")
        monkeypatch.setattr(store, "_ready", False)

    settings.ensure_directories()
    return tmp_path


@pytest.fixture
def embedder():
    return HashingEmbedder()


@pytest.fixture
def indexer(embedder):
    """An in-memory ResumeIndexer with a deterministic offline embedder."""
    from rag.resume_indexer import ResumeIndexer

    instance = ResumeIndexer(
        collection_name="test_resumes",
        embedder=embedder,
        persist=False,
    )
    yield instance
    instance.clear_index()


@pytest.fixture
def resume_file(tmp_path):
    path = tmp_path / "jane_developer.txt"
    path.write_text(SAMPLE_RESUME, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def signed_in_by_default():
    """Every endpoint test runs as a signed-in account.

    The API now derives ``user_id`` from a session cookie, so without this
    every existing endpoint test would get a 401 instead of the behaviour it
    was written to check. Overriding the dependency keeps those tests about
    what they were always about.

    ``test_auth.py`` deliberately clears this override, because the one thing
    it must exercise is the real 401 path.
    """
    import main

    account = {
        "user_id": "local",
        "email": "tester@example.com",
        "name": "Tester",
        "created_date": "2026-01-01T00:00:00",
        "last_login": None,
    }
    main.app.dependency_overrides[main.current_user] = lambda: account
    try:
        yield account
    finally:
        main.app.dependency_overrides.pop(main.current_user, None)


@pytest.fixture
def client():
    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def sample_job():
    return JobDescription(
        title="Senior AI Engineer",
        company="Acme",
        description=(
            "We need someone to build RAG pipelines end to end for our platform.\n"
            "Required: Python, FastAPI, LangChain, Docker.\n"
            "Preferred: AWS and Kubernetes experience is a plus."
        ),
    )


SAMPLE_JOB_TEXT = """Senior Backend Engineer

Required: Python, Kubernetes, PostgreSQL, AWS
Preferred: FastAPI, Terraform

Responsibilities:
- Design distributed services
- Mentor junior engineers
"""


class StubLLM:
    """Offline stand-in for ``LLMClient``.

    Hand it a list of replies and it serves them in order. Set ``available`` to
    False to simulate a machine with no Ollama and no API key, which is the
    default state of CI.
    """

    def __init__(self, responses=None, available=True, error=None):
        self.responses = list(responses or [])
        self.available = available
        self.error = error
        self.prompts: List[str] = []
        self.last_backend = "stub" if available else None

    def is_available(self) -> bool:
        return self.available

    def available_backend(self):
        return "stub" if self.available else None

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        if not self.responses:
            from agents.ollama_handler import LLMUnavailableError

            raise LLMUnavailableError("stub ran out of scripted responses")
        return self.responses.pop(0)


@pytest.fixture
def offline_llm():
    """An LLM client that reports itself unavailable, forcing the fallback path."""
    return StubLLM(available=False)


@pytest.fixture
def agent_config():
    from agents import AgentConfig

    return AgentConfig(model="mistral", fallback_enabled=False)

