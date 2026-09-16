#!/usr/bin/env python3
"""Week 1 smoke check: prove every part of the backend imports and runs.

This is deliberately *not* a unit test. The suite in ``tests/`` swaps the real
embedder, LLM and vector store for stand-ins so it can run offline in seconds.
This script does the opposite: it wires up the real objects and the real config
to catch the failures that mocking hides -- a missing dependency, a bad import,
a renamed setting, a route that no longer exists.

Run it from the backend folder::

    python test_week1.py            # just the report
    python test_week1.py --verbose  # plus the application's own log output

Exit code is 0 when everything is ready and 1 when anything failed, so it can be
dropped into CI as-is.
"""

import logging
import sys
import time
import traceback
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"

# Allow `python backend/test_week1.py` from the repo root, not just from inside
# backend/. Without this the local packages are not importable.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
_WIDTH = 74


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * _WIDTH)


def ok(message: str) -> None:
    print(f"  [ OK ]  {message}")


def info(message: str) -> None:
    print(f"          {message}")


def warn(message: str) -> None:
    print(f"  [WARN]  {message}")


def fail(message: str) -> None:
    print(f"  [FAIL]  {message}")


def configure_output(verbose: bool) -> None:
    """Keep the report readable.

    The checks below are the signal; the application's own INFO logging is
    noise here and interleaves badly with the report. Failures still surface,
    because they come back as exceptions rather than log lines.
    """
    from utils.logger import setup_logging

    setup_logging()  # let the app install its handlers first, then turn them down

    # chromadb 0.4.x logs a telemetry ERROR on every client start -- a bug in
    # its posthog wrapper, not a problem with the index. Silenced always: it
    # looks like a failure and is not one.
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

    if not verbose:
        warnings.filterwarnings("ignore")
        logging.getLogger().setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Sample data
# --------------------------------------------------------------------------- #
def load_sample(name: str) -> str:
    """Read one of the sample files, with a clear message if it is missing."""
    path = SAMPLES_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Sample file not found: {path}\n"
            f"          Expected it next to this script, in {SAMPLES_DIR.name}/."
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Sample file is empty: {path}")
    return text


SAMPLE_JOB_DESCRIPTION = "sample_job_description.txt"
SAMPLE_RESUME = "sample_resume.txt"

#: Filled in by test_job_analyzer_initialization so the match calculator check
#: can reuse it instead of analysing the same advert twice.
_job_analysis = None


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def test_config_loads() -> None:
    """Settings import, validate and resolve to absolute paths."""
    from config import BASE_DIR as CONFIG_BASE_DIR
    from config import LLM_PROVIDERS, settings

    assert settings.APP_NAME, "APP_NAME is empty"
    # Read the permitted set from config rather than repeating it. A copy here
    # silently goes stale the moment a provider is added -- which is exactly
    # what happened when Gemini arrived and this line still listed three names.
    assert settings.LLM_PROVIDER in LLM_PROVIDERS, (
        "LLM_PROVIDER %r is not one of %s" % (settings.LLM_PROVIDER, LLM_PROVIDERS)
    )
    assert settings.CHROMA_DB_PATH.is_absolute(), "CHROMA_DB_PATH is not absolute"
    assert settings.UPLOAD_DIR.is_absolute(), "UPLOAD_DIR is not absolute"
    assert CONFIG_BASE_DIR == BASE_DIR, "config.BASE_DIR does not match this file"

    ok("Config loaded")
    for key, value in settings.summary().items():
        info(f"{key:<16} {value}")

    settings.ensure_directories()
    ok("Storage directories exist")
    info(f"uploads          {settings.UPLOAD_DIR}")
    info(f"vector store     {settings.CHROMA_DB_PATH}")
    info(f"logs             {settings.LOG_DIR}")

    env_file = BASE_DIR / ".env"
    if env_file.exists():
        info(".env             found, values above include it")
    else:
        info(".env             not present, using defaults (this is fine)")


def test_resume_indexer_initialization() -> None:
    """The RAG stack imports and Chroma will open a collection."""
    from rag.resume_indexer import (
        ResumeIndexer,
        SentenceTransformerEmbedder,
        resume_indexer,
    )

    ok("RAG module imported")

    embedder = SentenceTransformerEmbedder()
    info(f"embedding model  {embedder.model_name} (loads on first index)")

    # An ephemeral index proves chromadb works without writing to the real
    # store, and without pulling the ~90 MB embedding model.
    scratch = ResumeIndexer(collection_name="week1_smoke", persist=False)
    assert scratch.count() == 0, "a fresh in-memory index should be empty"
    ok("Chroma opened an in-memory collection")

    info(f"live collection  {resume_indexer.collection_name}")
    try:
        indexed = resume_indexer.count()
    except Exception as exc:  # a corrupt or locked store should not be fatal here
        warn(f"live store could not be read: {exc.__class__.__name__}: {exc}")
    else:
        info(f"chunks on disk   {indexed}")
        ok("RAG system ready")


def test_job_analyzer_initialization() -> None:
    """The job analyzer builds and returns a full analysis of a real advert."""
    global _job_analysis
    from agents.job_analyzer import JobAnalyzerAgent, job_analyzer_agent

    assert isinstance(job_analyzer_agent, JobAnalyzerAgent)
    assert job_analyzer_agent.name == "analyze_job"
    ok(f"Agent initialized: {job_analyzer_agent.label}")

    job_text = load_sample(SAMPLE_JOB_DESCRIPTION)
    info(f"sample advert    {len(job_text)} characters")

    started = time.perf_counter()
    analysis = job_analyzer_agent.analyze(job_text)
    elapsed = (time.perf_counter() - started) * 1000

    assert analysis.get("required_skills"), "no required skills were extracted"
    _job_analysis = analysis

    ok(f"Advert analysed in {elapsed:.0f} ms via '{analysis.get('source')}'")
    info(f"title            {analysis.get('title')}")
    info(f"seniority        {analysis.get('seniority')}")
    info(f"experience       {analysis.get('experience_years')} years")
    info(f"education        {analysis.get('education')}")
    info(f"required skills  {', '.join(analysis.get('required_skills', []))}")
    info(f"tech stack       {', '.join(analysis.get('tech_stack', []))}")
    info(f"soft skills      {', '.join(analysis.get('soft_skills', []))}")
    info(f"confidence       {analysis.get('confidence')}")


def test_match_calculator_initialization() -> None:
    """The scorer builds and produces a verdict for the sample pair."""
    from agents.match_calculator import MatchCalculator, match_calculator

    assert isinstance(match_calculator, MatchCalculator)
    ok("Agent initialized: Match Calculator")

    if _job_analysis is None:
        raise RuntimeError("job analysis unavailable - the previous check failed")

    resume_text = load_sample(SAMPLE_RESUME)
    info(f"sample resume    {len(resume_text)} characters")

    started = time.perf_counter()
    result = match_calculator.calculate_match(
        {"resume_text": resume_text}, _job_analysis
    )
    elapsed = (time.perf_counter() - started) * 1000

    score = result["overall_match"]
    assert 0.0 <= score <= 100.0, f"score out of range: {score}"

    ok(
        f"Scored in {elapsed:.0f} ms: "
        f"{score}/100 -> {result['recommendation']} "
        f"(confidence {result['confidence']})"
    )
    for name, component in result["match_breakdown"].items():
        info(f"{name:<16} {component.get('score')}")

    missing = result.get("missing_skills") or []
    if missing:
        info(f"gaps found       {', '.join(str(item) for item in missing)}")
    else:
        info("gaps found       none")


def test_fastapi_app_starts() -> None:
    """The app object builds and answers on its real routes."""
    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:  # httpx lives in requirements-dev.txt
        raise RuntimeError(
            "TestClient needs httpx: pip install -r requirements-dev.txt"
        ) from exc

    from main import app

    paths = sorted({route.path for route in app.routes})
    ok(f"FastAPI app built with {len(paths)} routes")
    for path in paths:
        if path.startswith("/api/career"):
            info(path)

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200, f"/health returned {health.status_code}"
        ok(f"GET /health -> {health.status_code} {health.json()}")

        status = client.get("/api/career/status")
        # 401 is the right answer here, not a failure. This client carries no
        # session cookie, and every /api/career route sits behind an account so
        # one person's resume can never be served to another. The check was
        # written before accounts existed and asserted 200; asserting 401
        # instead now proves the route is actually guarded.
        assert status.status_code == 401, (
            "/api/career/status returned %d to an anonymous client; it should be "
            "401, or the route has lost its authentication guard"
            % status.status_code
        )
        ok("GET /api/career/status -> 401 for an anonymous client (route guarded)")


def check_llm_connection() -> None:
    """Report which LLM backend is actually usable.

    Deliberately not a pass/fail check. The app is designed to work with no LLM
    at all -- it falls back to deterministic keyword matching -- so treating a
    stopped Ollama as a failure would contradict the design.

    It asks the router rather than probing Ollama directly. Probing Ollama was
    what this did before Gemini existed, and it reported "falls back to keyword
    matching" while the agents were quietly answering through Gemini -- a
    reassuring message that happened to be false.
    """
    from agents import AgentConfig
    from agents.ollama_handler import LLMClient
    from utils.health_check import KEY_ONLY_BACKENDS

    config = AgentConfig.from_settings()
    provider = str(getattr(config.provider, "value", config.provider))
    models = {"gemini": config.gemini_model, "claude": config.claude_model}
    info(f"provider         {provider}")
    info(f"model            {models.get(provider, config.model)}")

    started = time.perf_counter()
    backend = LLMClient(config).available_backend()
    elapsed = (time.perf_counter() - started) * 1000

    if backend and backend in KEY_ONLY_BACKENDS:
        # The giveaway is the timing: a hosted backend reports itself ready off
        # a configured key without sending anything, so "answered" would be a
        # claim about a request that was never made.
        ok(f"LLM tier configured: '{backend}' key present (checked in "
           f"{elapsed:.0f} ms, no request sent)")
        info("A key is not a reply. Free tiers refuse per-minute; agents fall "
             "back to keyword matching when that happens.")
    elif backend:
        ok(f"LLM tier ready: '{backend}' answered in {elapsed:.0f} ms")
    else:
        warn(f"No LLM backend reachable for provider '{provider}' "
             f"(probed in {elapsed:.0f} ms)")
        info("The app still works: agents fall back to keyword matching.")
        if provider in ("gemini", "auto"):
            info("To enable Gemini:  set GEMINI_API_KEY in backend/.env")
        if provider in ("ollama", "auto"):
            info("To enable Ollama:  ollama serve && ollama pull " + config.model)

    info("gemini key       " + ("set" if config.has_gemini_credentials else "not set"))
    info("claude key       " + ("set" if config.has_claude_credentials else "not set"))


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
CHECKS = (
    ("1. Configuration", test_config_loads),
    ("2. RAG / resume indexer", test_resume_indexer_initialization),
    ("3. Job analyzer agent", test_job_analyzer_initialization),
    ("4. Match calculator agent", test_match_calculator_initialization),
    ("5. FastAPI application", test_fastapi_app_starts),
    ("6. LLM connection", check_llm_connection),
)


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    configure_output(verbose)

    print("=" * _WIDTH)
    print("CareerPilot AI - Week 1 verification")
    print(f"python {sys.version.split()[0]}  |  {BASE_DIR}")
    print("=" * _WIDTH)

    failures = []
    started = time.perf_counter()

    for title, check in CHECKS:
        section(title)
        try:
            check()
        except Exception as exc:
            fail(f"{exc.__class__.__name__}: {exc}")
            traceback.print_exc()
            failures.append(title)

    elapsed = time.perf_counter() - started

    print()
    print("=" * _WIDTH)
    passed = len(CHECKS) - len(failures)
    if failures:
        print(f"{passed}/{len(CHECKS)} checks passed in {elapsed:.1f}s")
        for title in failures:
            print(f"  FAILED: {title}")
        print("=" * _WIDTH)
        return 1

    print(f"ALL SYSTEMS READY - {passed}/{len(CHECKS)} checks passed in {elapsed:.1f}s")
    print("=" * _WIDTH)
    if not verbose:
        print("Run with --verbose to see the application's own log output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
