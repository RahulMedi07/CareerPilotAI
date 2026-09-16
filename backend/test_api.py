#!/usr/bin/env python3
"""Exercise every HTTP endpoint against a real, running server.

This is the outermost test in the project. The others stop short of the wire:

    tests/          FastAPI TestClient - no socket, no server process
    test_week1.py   proves each component imports and constructs
    run_test.py     drives real data through the pipeline, in-process
    test_api.py     starts uvicorn and talks to it over HTTP  <- you are here

Because it goes over the network it is the only test that can catch problems
that live *between* the pieces: a route registered at the wrong path, a
response model that will not serialise, middleware that mangles a header,
multipart upload handling, or a status code that only appears once Starlette
has finished with the response.

Storage is isolated. The script starts its own server with UPLOAD_DIR,
CHROMA_DB_PATH and LOG_DIR pointed at a temporary directory, so the sample
resume never lands in the vector store you actually use. The directory is
removed on exit. Point it at a server you started yourself with --url, and
that protection is gone - it will write to whatever that server is using.

Usage:
    python test_api.py                 # start a server, test it, shut it down
    python test_api.py --verbose       # ...and show the server's own log
    python test_api.py --keep          # leave the temp storage for inspection
    python test_api.py --url http://localhost:8000
                                       # test a server that is already running
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# macOS ships LibreSSL, and urllib3 v2 warns about it on import. It is noise
# here: we only ever talk to 127.0.0.1 over plain HTTP.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

try:
    import requests
except ImportError:  # pragma: no cover - dependency guard
    print("The 'requests' library is required:  pip install requests")
    raise SystemExit(1)

WIDTH = 74
RULE = "=" * WIDTH

SAMPLE_RESUME = BASE_DIR / "data" / "sample_resume.txt"
SAMPLE_JOB = BASE_DIR / "data" / "sample_jd.txt"

# The first upload loads the sentence-transformers model and embeds the resume,
# and the first match runs the whole workflow. Neither is quick.
SLOW_TIMEOUT = 180
FAST_TIMEOUT = 30
BOOT_TIMEOUT = 60


class CheckFailed(Exception):
    """A check's expectation was not met."""


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def banner(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def expect(condition: bool, message: str) -> None:
    """Assert, but raising something we catch and report rather than a crash."""
    if not condition:
        raise CheckFailed(message)


def expect_field(payload: Dict[str, Any], field: str, kinds: Tuple[type, ...]) -> Any:
    """Check a response field exists and has the right type; return it."""
    expect(field in payload, f"response is missing '{field}' (got keys: {sorted(payload)})")
    value = payload[field]
    expect(
        isinstance(value, kinds),
        f"'{field}' should be {' or '.join(k.__name__ for k in kinds)}, "
        f"got {type(value).__name__} ({value!r})",
    )
    return value


def shorten(value: Any, limit: int = 60) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


# --------------------------------------------------------------------------- #
# Server lifecycle
# --------------------------------------------------------------------------- #
def free_port() -> int:
    """Ask the OS for a port nobody is using.

    Binding to port 0 and reading back the assignment avoids the race of
    picking a number and hoping, and avoids colliding with a dev server the
    developer already has on 8000.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(sandbox: Path, verbose: bool) -> Tuple[subprocess.Popen, str, Path]:
    """Launch uvicorn against throwaway storage and wait until it answers.

    Deliberately no --reload. The reloader forks a supervisor that owns the
    real worker, so terminating the process we hold a handle to can leave the
    worker running and the port bound. It is also slower to boot and watches
    files we are about to leave alone.
    """
    port = free_port()
    url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.update(
        {
            "UPLOAD_DIR": str(sandbox / "uploads"),
            "CHROMA_DB_PATH": str(sandbox / "chroma"),
            "LOG_DIR": str(sandbox / "logs"),
            "LOG_TO_FILE": "false",
            "PYTHONUNBUFFERED": "1",
        }
    )

    log_path = sandbox / "server.log"
    log_handle = log_path.open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info" if verbose else "warning",
        ],
        cwd=str(BASE_DIR),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )

    print(f"Starting uvicorn on port {port} (isolated storage)...")
    deadline = time.time() + BOOT_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            log_handle.close()
            print("\nThe server exited before it was ready. Its output:\n")
            print(log_path.read_text() or "(no output)")
            raise RuntimeError(f"uvicorn exited with code {process.returncode}")
        try:
            if requests.get(f"{url}/health", timeout=2).status_code == 200:
                print(f"Server is up at {url}\n")
                return process, url, log_path
        except requests.RequestException:
            time.sleep(0.3)

    stop_server(process)
    log_handle.close()
    raise RuntimeError(f"Server did not respond within {BOOT_TIMEOUT}s")


def stop_server(process: Optional[subprocess.Popen]) -> None:
    """Ask the server to stop, then insist."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_health(url: str) -> List[str]:
    """GET /health - is the server alive and reporting itself correctly?"""
    response = requests.get(f"{url}/health", timeout=FAST_TIMEOUT)
    expect(response.status_code == 200, f"expected 200, got {response.status_code}")

    payload = response.json()
    status_value = expect_field(payload, "status", (str,))
    app_name = expect_field(payload, "app", (str,))
    version = expect_field(payload, "version", (str,))
    expect_field(payload, "timestamp", (str,))
    expect(status_value == "ok", f"status should be 'ok', got {status_value!r}")

    # The spec asked for POST /health. It is a GET, and proving the POST is
    # refused is worth more than pretending otherwise: a route that answers
    # every verb usually means someone reached for @app.api_route().
    refused = requests.post(f"{url}/health", timeout=FAST_TIMEOUT)
    expect(
        refused.status_code == 405,
        f"POST /health should be 405 Method Not Allowed, got {refused.status_code}",
    )

    return [f"{app_name} v{version}, status '{status_value}'", "POST correctly refused (405)"]


def check_status_empty(url: str) -> List[str]:
    """GET /api/career/status - a fresh index should admit it is empty."""
    response = requests.get(f"{url}/api/career/status", timeout=FAST_TIMEOUT)
    expect(response.status_code == 200, f"expected 200, got {response.status_code}")

    payload = response.json()
    indexed = expect_field(payload, "resume_indexed", (bool,))
    chunks = expect_field(payload, "chunks", (int,))
    expect_field(payload, "status", (str,))
    expect(indexed is False, "a fresh index should report resume_indexed=false")
    expect(chunks == 0, f"a fresh index should hold 0 chunks, got {chunks}")

    return ["empty index reported honestly (resume_indexed=false, chunks=0)"]


def check_match_without_resume(url: str) -> List[str]:
    """POST /api/career/calculate-match - must refuse before anything is indexed.

    Scoring an empty index would return a meaningless 0% rather than an error,
    which is the kind of answer a caller believes.
    """
    response = requests.post(
        f"{url}/api/career/calculate-match",
        json={"job_description": SAMPLE_JOB.read_text(encoding="utf-8")},
        timeout=SLOW_TIMEOUT,
    )
    expect(
        response.status_code == 409,
        f"expected 409 Conflict with no resume indexed, got {response.status_code}",
    )
    detail = expect_field(response.json(), "detail", (str,))
    expect("upload-resume" in detail, f"the error should say what to do next, got {detail!r}")

    return [f"refused with 409: {shorten(detail)}"]


def check_upload_resume(url: str) -> List[str]:
    """POST /api/career/upload-resume - the multipart upload and index path."""
    with SAMPLE_RESUME.open("rb") as handle:
        response = requests.post(
            f"{url}/api/career/upload-resume",
            files={"file": (SAMPLE_RESUME.name, handle, "text/plain")},
            timeout=SLOW_TIMEOUT,
        )
    expect(response.status_code == 201, f"expected 201 Created, got {response.status_code}: {shorten(response.text)}")

    payload = response.json()
    status_value = expect_field(payload, "status", (str,))
    expect_field(payload, "message", (str,))
    file_size = expect_field(payload, "file_size", (int,))
    expect(status_value == "success", f"status should be 'success', got {status_value!r}")

    on_disk = SAMPLE_RESUME.stat().st_size
    expect(
        file_size == on_disk,
        f"file_size {file_size} should match the bytes sent ({on_disk})",
    )

    return [f"indexed, {file_size} bytes received intact"]


def check_reject_bad_extension(url: str) -> List[str]:
    """POST /api/career/upload-resume - the extension allow-list still bites."""
    response = requests.post(
        f"{url}/api/career/upload-resume",
        files={"file": ("payload.exe", b"MZ not a resume", "application/octet-stream")},
        timeout=FAST_TIMEOUT,
    )
    expect(
        response.status_code == 400,
        f"an unsupported extension should be 400, got {response.status_code}",
    )
    return ["'.exe' upload rejected with 400"]


def check_status_after_upload(url: str) -> List[str]:
    """GET /api/career/status - the index should now report content."""
    response = requests.get(f"{url}/api/career/status", timeout=FAST_TIMEOUT)
    expect(response.status_code == 200, f"expected 200, got {response.status_code}")

    payload = response.json()
    indexed = expect_field(payload, "resume_indexed", (bool,))
    chunks = expect_field(payload, "chunks", (int,))
    expect(indexed is True, "resume_indexed should be true after an upload")
    expect(chunks > 0, f"chunks should be greater than 0 after an upload, got {chunks}")

    return [f"resume_indexed=true, {chunks} documents held"]


def check_analyze_job(url: str) -> List[str]:
    """POST /api/career/analyze-job - structured requirements out of prose."""
    response = requests.post(
        f"{url}/api/career/analyze-job",
        json={"job_description": SAMPLE_JOB.read_text(encoding="utf-8")},
        timeout=SLOW_TIMEOUT,
    )
    expect(response.status_code == 200, f"expected 200, got {response.status_code}: {shorten(response.text)}")

    payload = response.json()
    title = expect_field(payload, "title", (str,))
    skills = expect_field(payload, "required_skills", (list,))
    confidence = expect_field(payload, "confidence", (int, float))
    expect(bool(title.strip()), "the advert has a title line; it should not come back empty")
    expect(len(skills) > 0, "the advert lists skills; none were extracted")
    expect(all(isinstance(s, str) for s in skills), "required_skills should be all strings")
    expect(0.0 <= confidence <= 1.0, f"confidence should be a 0-1 fraction, got {confidence}")

    return [
        f"title '{shorten(title, 44)}'",
        f"{len(skills)} required skills, confidence {confidence:.2f}",
    ]


def check_calculate_match(url: str) -> List[str]:
    """POST /api/career/calculate-match - the full pipeline over the wire."""
    response = requests.post(
        f"{url}/api/career/calculate-match",
        json={"job_description": SAMPLE_JOB.read_text(encoding="utf-8")},
        timeout=SLOW_TIMEOUT,
    )
    expect(response.status_code == 200, f"expected 200, got {response.status_code}: {shorten(response.text)}")

    payload = response.json()
    overall = expect_field(payload, "overall_match", (int, float))
    breakdown = expect_field(payload, "match_breakdown", (dict,))
    recommendation = expect_field(payload, "recommendation", (str,))
    trace = expect_field(payload, "execution_trace", (list,))
    confidence = expect_field(payload, "confidence", (int, float))

    expect(0.0 <= overall <= 100.0, f"overall_match should be 0-100, got {overall}")
    expect(0.0 <= confidence <= 100.0, f"confidence should be 0-100, got {confidence}")
    expect(
        recommendation in {"APPLY", "MAYBE", "SKIP"},
        f"recommendation should be APPLY/MAYBE/SKIP, got {recommendation!r}",
    )
    expect(len(breakdown) > 0, "match_breakdown came back empty")
    expect(len(trace) > 0, "execution_trace came back empty; the workflow left no record")

    for name, component in breakdown.items():
        expect(isinstance(component, dict), f"breakdown['{name}'] should be an object")
        expect("score" in component, f"breakdown['{name}'] has no 'score'")

    return [
        f"overall {overall:.1f}% -> {recommendation} (confidence {confidence:.1f}%)",
        f"{len(breakdown)} components: {', '.join(sorted(breakdown))}",
        f"{len(trace)} workflow steps traced",
    ]


def check_validation_rejected(url: str) -> List[str]:
    """POST /api/career/analyze-job - an empty body must not reach the agent."""
    empty = requests.post(
        f"{url}/api/career/analyze-job", json={"job_description": ""}, timeout=FAST_TIMEOUT
    )
    expect(empty.status_code == 422, f"an empty advert should be 422, got {empty.status_code}")

    missing = requests.post(f"{url}/api/career/analyze-job", json={}, timeout=FAST_TIMEOUT)
    expect(
        missing.status_code == 422,
        f"a missing job_description should be 422, got {missing.status_code}",
    )

    return ["empty and missing job_description both rejected with 422"]


def check_request_id_header(url: str) -> List[str]:
    """Every response should carry the correlation header the middleware adds."""
    response = requests.get(f"{url}/health", timeout=FAST_TIMEOUT)
    request_id = response.headers.get("X-Request-ID")
    expect(bool(request_id), "X-Request-ID header is missing from the response")
    return [f"X-Request-ID present ({request_id[:8]}...)"]


def check_clear_index(url: str) -> List[str]:
    """POST /api/career/clear - tidy up, and prove the teardown works."""
    response = requests.post(f"{url}/api/career/clear", timeout=SLOW_TIMEOUT)
    expect(response.status_code == 200, f"expected 200, got {response.status_code}")

    payload = response.json()
    removed = expect_field(payload, "chunks_removed", (int,))
    expect_field(payload, "status", (str,))
    expect(removed > 0, f"should have removed the chunks we added, got {removed}")

    after = requests.get(f"{url}/api/career/status", timeout=FAST_TIMEOUT).json()
    expect(after["chunks"] == 0, f"index should be empty after clear, holds {after['chunks']}")

    return [f"{removed} documents removed, index confirmed empty"]


# Order matters: the empty-index checks have to run before anything is indexed.
CHECKS: Tuple[Tuple[str, str, Callable[[str], List[str]]], ...] = (
    ("GET  /health", "Server is running", check_health),
    ("GET  /api/career/status", "Empty index", check_status_empty),
    ("POST /api/career/calculate-match", "Refused with no resume", check_match_without_resume),
    ("POST /api/career/upload-resume", "Sample resume", check_upload_resume),
    ("POST /api/career/upload-resume", "Bad extension", check_reject_bad_extension),
    ("GET  /api/career/status", "After upload", check_status_after_upload),
    ("POST /api/career/analyze-job", "Sample advert", check_analyze_job),
    ("POST /api/career/calculate-match", "Full pipeline", check_calculate_match),
    ("POST /api/career/analyze-job", "Input validation", check_validation_rejected),
    ("GET  /health", "Middleware headers", check_request_id_header),
    ("POST /api/career/clear", "Teardown", check_clear_index),
)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_checks(url: str) -> int:
    """Run every check in order. Returns the number that failed."""
    failures = 0

    for endpoint, label, function in CHECKS:
        print(f"{endpoint}")
        print(f"  {label}")
        started = time.time()
        try:
            details = function(url)
        except CheckFailed as exc:
            failures += 1
            print(f"  [FAIL] {exc}\n")
        except requests.RequestException as exc:
            failures += 1
            print(f"  [FAIL] the request itself failed: {exc}\n")
        except Exception as exc:  # noqa: BLE001 - one bad check must not stop the rest
            failures += 1
            print(f"  [ERROR] {type(exc).__name__}: {exc}\n")
        else:
            elapsed = time.time() - started
            for line in details:
                print(f"  \u2713 {line}")
            print(f"  ({elapsed:.2f}s)\n")

    return failures


def preflight() -> None:
    """Fail early and clearly if the fixtures are missing."""
    for path in (SAMPLE_RESUME, SAMPLE_JOB):
        if not path.is_file():
            raise FileNotFoundError(f"Sample file not found: {path}")


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test every CareerPilot API endpoint.")
    parser.add_argument("--url", help="Test a server already running at this URL.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show the server's log.")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary storage.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    banner("CAREERPILOT AI - API ENDPOINT TESTS")

    try:
        preflight()
    except FileNotFoundError as exc:
        print(f"\u2717 {exc}")
        return 1

    process: Optional[subprocess.Popen] = None
    sandbox: Optional[Path] = None
    log_path: Optional[Path] = None

    try:
        if args.url:
            url = args.url.rstrip("/")
            print(f"Testing the server already running at {url}.")
            print("Warning: this writes to that server's real vector store.\n")
        else:
            sandbox = Path(tempfile.mkdtemp(prefix="careerpilot-api-"))
            process, url, log_path = start_server(sandbox, args.verbose)

        failures = run_checks(url)

        banner("SUMMARY")
        total = len(CHECKS)
        print(f"{total - failures}/{total} checks passed")

        if failures:
            print(f"\n{failures} check(s) failed.")
            if log_path and log_path.is_file():
                print(f"Server log: {log_path}")
                if not args.keep:
                    print("Re-run with --keep to stop it being deleted.")
            return 1

        print("\nEvery endpoint responded correctly.")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001 - reported below
        print(f"\n\u2717 {type(exc).__name__}: {exc}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        else:
            print("Re-run with --verbose for the full traceback.")
        return 1
    finally:
        stop_server(process)
        if sandbox and sandbox.is_dir():
            if args.keep:
                print(f"\nTemporary storage kept at: {sandbox}")
            else:
                shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
