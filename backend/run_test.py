#!/usr/bin/env python3
"""Week 1 end-to-end pipeline test.

Runs a resume and a job advert through every stage the real API uses:

    config -> ResumeIndexer -> JobAnalyzerAgent -> MatchCalculator -> verdict

Unlike ``test_week1.py``, which only proves each part starts, this one moves
real data through the whole chain and prints what came out. It embeds text with
the real sentence-transformers model, so the vectors and the RAG evidence
lookups are genuine.

The index is **in-memory**. Writing to the live store would mix this sample
resume into whatever you have already indexed, and there is only one shared
collection -- see the "one resume at a time" limitation in README_DEV.md.

Usage::

    python run_test.py                    # uses data/sample_*.txt
    python run_test.py cv.txt advert.txt  # your own files
    python run_test.py --verbose          # plus the application's own logs
"""

import logging
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DEFAULT_RESUME = BASE_DIR / "data" / "sample_resume.txt"
DEFAULT_JOB = BASE_DIR / "data" / "sample_jd.txt"

WIDTH = 58
RULE = "=" * WIDTH


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def banner(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def tick(message: str) -> None:
    print(f"\u2713 {message}")


def cross(message: str) -> None:
    print(f"\u2717 {message}")


def step(number: int, title: str) -> None:
    print(f"\nStep {number}: {title}")


def branch(message: str) -> None:
    print(f"  \u251c\u2500 {message}")


def leaf(message: str) -> None:
    print(f"  \u2514\u2500 {message}")


def bullet(message: str) -> None:
    print(f"  - {message}")


def listing(values: Sequence[Any], empty: str = "none") -> str:
    """Comma-separated list that wraps rather than running off the terminal."""
    items = [str(value) for value in values]
    if not items:
        return empty

    indent = " " * 18
    limit = WIDTH - 18
    lines: List[str] = []
    current = ""
    for item in items:
        candidate = f"{current}, {item}" if current else item
        if current and len(candidate) > limit:
            lines.append(current + ",")
            current = item
        else:
            current = candidate
    if current:
        lines.append(current)
    return ("\n" + indent).join(lines)


def as_items(value: Any) -> List[str]:
    """Normalise a ComponentScore ``found``/``missing`` field to a list.

    These fields are polymorphic: the skill-based components store lists, while
    experience and education store a single descriptive string such as
    ``"2 years"``. Treating a string as a sequence would iterate its characters.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def is_countable(component: Dict[str, Any]) -> bool:
    """Can this component be summarised as "n of m found"?

    Only the skill-style components hold comparable collections. Experience and
    education hold prose, where "1/2 found" would be meaningless.
    """
    return isinstance(component.get("found"), (list, tuple, set)) and isinstance(
        component.get("missing"), (list, tuple, set)
    )


def bar(percentage: float, size: int = 20) -> str:
    filled = int(round(percentage / 100 * size))
    return "[" + "#" * filled + "." * (size - filled) + "]"


def shorten(text: str, limit: int = 88) -> str:
    """Collapse whitespace and clip to one readable line."""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip(" ,;:-") + "\u2026"


def configure_output(verbose: bool) -> None:
    """Silence incidental logging so the report is readable."""
    from utils.logger import setup_logging

    setup_logging()
    # chromadb 0.4.x logs a telemetry ERROR on every client start. It is a bug
    # in its posthog wrapper, not an indexing problem, and it looks alarming.
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    if not verbose:
        warnings.filterwarnings("ignore")
        logging.getLogger().setLevel(logging.WARNING)


def read_text_file(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{label} is empty: {path}")
    return text


# --------------------------------------------------------------------------- #
# Pipeline stages
# --------------------------------------------------------------------------- #
def load_config() -> Any:
    from config import settings

    settings.ensure_directories()
    tick("Config loaded")
    return settings


def build_indexer(collection: str = "run_test_pipeline") -> Any:
    from rag.resume_indexer import ResumeIndexer

    indexer = ResumeIndexer(collection_name=collection, persist=False)
    indexer.count()  # force the Chroma client open now, not mid-report
    tick("RAG initialized")
    return indexer


def build_agents() -> tuple:
    from agents.job_analyzer import job_analyzer_agent
    from agents.match_calculator import match_calculator

    tick("Job analyzer initialized")
    tick("Match calculator initialized")
    return job_analyzer_agent, match_calculator


def index_resume(indexer: Any, resume_path: Path) -> Dict[str, Any]:
    resume_text = read_text_file(resume_path, "Resume")
    branch(f"Read {resume_path.name} ({len(resume_text):,} characters)")
    branch("Embedding with all-MiniLM-L6-v2 (first run downloads ~90 MB)")

    started = time.perf_counter()
    summary = indexer.index_resume(resume_path)
    elapsed = time.perf_counter() - started

    if summary.get("status") == "empty":
        raise RuntimeError(
            f"No text could be extracted from {resume_path.name}. "
            "If it is a scanned PDF it needs OCR first."
        )

    sections = summary.get("sections") or {}
    indexed = summary.get("chunks_indexed", 0)
    branch(f"Indexed {indexed} content chunks across {len(sections)} sections in {elapsed:.1f}s")
    if sections:
        branch(f"Sections: {listing(sorted(sections))}")
    # count() is higher than chunks_indexed because the indexer also stores a
    # synthetic profile record (name, email, years, skills) as its own
    # retrievable document. chunks_indexed counts resume content only.
    leaf(f"Collection holds {indexer.count()} documents (content + profile record)")
    return summary


def analyze_job(agent: Any, job_path: Path) -> Dict[str, Any]:
    job_text = read_text_file(job_path, "Job description")
    branch(f"Read {job_path.name} ({len(job_text):,} characters)")

    started = time.perf_counter()
    analysis = agent.analyze(job_text)
    elapsed = (time.perf_counter() - started) * 1000

    branch(f"Called JobAnalyzerAgent ({elapsed:.0f} ms, source '{analysis.get('source')}')")
    leaf(f"Extracted {len(analysis.get('required_skills') or [])} required skills")
    return analysis


def calculate_match(
    calculator: Any, indexer: Any, analysis: Dict[str, Any]
) -> Dict[str, Any]:
    context = indexer.get_full_context()
    branch(f"Retrieved {len(context):,} characters from the RAG index")

    started = time.perf_counter()
    result = calculator.calculate_match(
        {"resume_text": context}, analysis, retriever=indexer
    )
    elapsed = (time.perf_counter() - started) * 1000

    branch(f"Called MatchCalculator with the index as its retriever ({elapsed:.0f} ms)")
    leaf(f"Overall match {result['overall_match']}/100")
    return result


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def report_job_analysis(analysis: Dict[str, Any]) -> None:
    banner("JOB ANALYSIS")
    rows = [
        ("Title", analysis.get("title") or "unknown"),
        ("Role type", analysis.get("role_type") or "unknown"),
        ("Seniority", analysis.get("seniority") or "unknown"),
        ("Experience", f"{analysis.get('experience_years', 0)} years"),
        ("Education", analysis.get("education") or "not specified"),
        ("Required Skills", listing(analysis.get("required_skills") or [])),
        ("Tech Stack", listing(analysis.get("tech_stack") or [])),
        ("Nice to have", listing(analysis.get("preferred_skills") or [])),
        ("Soft Skills", listing(analysis.get("soft_skills") or [])),
        ("Confidence", f"{analysis.get('confidence', 0)}"),
    ]
    for label, value in rows:
        print(f"{label + ':':<17} {value}")


def report_match(result: Dict[str, Any]) -> None:
    banner("MATCH RESULTS")

    score = result["overall_match"]
    print(f"Overall Match:    {score}%  {bar(score)}")
    print(f"Confidence:       {result.get('confidence')}%")
    print()

    for name, component in result.get("match_breakdown", {}).items():
        found = as_items(component.get("found"))
        missing = as_items(component.get("missing"))

        label = name.replace("_", " ").title()
        if not component.get("applicable", True):
            detail = f"(not assessed: {component.get('reason', 'not specified')})"
        elif is_countable(component):
            detail = f"({len(found)}/{len(found) + len(missing)} found)"
        else:
            detail = ""

        print(f"{label + ':':<17} {component.get('score')}%  {detail}".rstrip())
        if found:
            print(f"{'':<17} have: {listing(found)}")
        if missing:
            print(f"{'':<17} lack: {listing(missing)}")

    evidence = collect_evidence(result)
    if evidence:
        print("\nEvidence pulled from your resume:")
        for skill, quote in list(evidence.items())[:5]:
            bullet(f"{skill}: \"{shorten(quote)}\"")

    gaps = result.get("missing_skills") or []
    print("\nGaps:")
    if gaps:
        for gap in gaps:
            bullet(str(gap))
    else:
        bullet("none - every stated requirement was matched")

    print(f"\nRecommendation:   {result.get('recommendation')}")
    advice = result.get("advice") or result.get("summary")
    if advice:
        print(f"\n{advice}")
    print(RULE)


def collect_evidence(result: Dict[str, Any]) -> Dict[str, str]:
    """Flatten the per-component evidence quotes into one mapping."""
    evidence: Dict[str, str] = {}
    for component in result.get("match_breakdown", {}).values():
        for skill, quote in (component.get("evidence") or {}).items():
            evidence.setdefault(skill, quote)
    return evidence


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def parse_args(argv: List[str]) -> tuple:
    positional = [item for item in argv[1:] if not item.startswith("-")]
    verbose = "--verbose" in argv or "-v" in argv
    resume = Path(positional[0]).resolve() if len(positional) > 0 else DEFAULT_RESUME
    job = Path(positional[1]).resolve() if len(positional) > 1 else DEFAULT_JOB
    return resume, job, verbose


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    resume_path, job_path, verbose = parse_args(argv)

    configure_output(verbose)

    print(RULE)
    print("CAREERPILOT AI - WEEK 1 TEST")
    print(RULE)
    print()

    stage = "startup"
    started = time.perf_counter()
    try:
        stage = "loading config"
        load_config()

        stage = "initializing the RAG index"
        indexer = build_indexer()

        stage = "initializing the agents"
        analyzer, calculator = build_agents()

        stage = "indexing the resume"
        step(1, "Load Resume")
        index_resume(indexer, resume_path)

        stage = "analyzing the job description"
        step(2, "Analyze Job")
        analysis = analyze_job(analyzer, job_path)

        stage = "calculating the match"
        step(3, "Calculate Match")
        result = calculate_match(calculator, indexer, analysis)

        stage = "reporting"
        step(4, "Show Results")
        leaf("Formatting the report")
        report_job_analysis(analysis)
        report_match(result)

    except FileNotFoundError as exc:
        cross(f"Missing input while {stage}: {exc}")
        print("\nExpected sample files:")
        bullet(str(DEFAULT_RESUME))
        bullet(str(DEFAULT_JOB))
        print("\nOr pass your own:  python run_test.py <resume> <job_description>")
        return 1
    except KeyboardInterrupt:
        cross("Interrupted")
        return 130
    except Exception as exc:
        cross(f"Pipeline failed while {stage}")
        print(f"  {exc.__class__.__name__}: {exc}\n")
        traceback.print_exc()
        if not verbose:
            print("\nRun with --verbose for the application's own log output.")
        return 1

    elapsed = time.perf_counter() - started
    print(f"\nPipeline completed in {elapsed:.1f}s. All four stages ran.")
    if not verbose:
        print("Run with --verbose to see the application's own log output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
