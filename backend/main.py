"""CareerPilot AI - FastAPI application entrypoint.

Run with:  uvicorn main:app --reload
"""

import re
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from models.career_models import (
    AnalyticsResponse,
    ApplicationHistoryResponse,
    ApplicationsResponse,
    ChatRequest,
    ChatResponse,
    ClearIndexResponse,
    CreateApplicationRequest,
    CreateApplicationResponse,
    FullAnalysisResponse,
    FullAnalysisSections,
    HealthResponse,
    IndexStatusResponse,
    InterviewPrepRequest,
    InterviewPrepResponse,
    PracticeAnswerRequest,
    PracticeAnswerResponse,
    JobAnalysisResponse,
    JobDiscoveryRequest,
    JobDiscoveryResponse,
    JobDescriptionRequest,
    ResumeIndexResponse,
    ResumeInsightsResponse,
    SavedJobsResponse,
    SaveJobRequest,
    SaveJobResponse,
    TraceNode,
    TraceResponse,
    UpdateApplicationStatusRequest,
    UpdateApplicationStatusResponse,
)
from models.auth_models import (
    AccountResponse,
    LoginRequest,
    LogoutResponse,
    SignupRequest,
)
from utils.cache import all_stats as cache_stats
from utils.cache import clear_all as clear_all_caches
from utils.error_handling import CareerPilotException
from utils.logger import get_logger

logger = get_logger(__name__)

CHUNK_BYTES = 1024 * 1024
CAREER_PREFIX = "/api/career"

#: Upper bound on an advert, mirroring ``JobDescriptionRequest``. Multipart
#: fields bypass that model, so the same guard is applied by hand.
MAX_JOB_DESCRIPTION_CHARS = 50_000

#: How many past analyses stay available to the trace endpoint.
ANALYSIS_HISTORY_LIMIT = 50

#: How many accounts keep a warm resume index and pipeline in memory. Anyone
#: past this is evicted least-recently-used and rebuilt on their next request.
ACTIVE_ACCOUNT_LIMIT = 20

#: How many discovered adverts stay saveable. Same bounded, oldest-first
#: policy as the analysis history: a server left running for a week must not
#: accumulate every advert it has ever seen.
DISCOVERED_JOBS_LIMIT = 200

#: How many resume-derived phrases a single auto-discovery call will search.
#: Each one is a full round of requests to every board, so this is a rate-limit
#: on the user's behalf as much as a relevance cut-off.
MAX_AUTO_QUERIES = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    logger.info("%s v%s starting up", settings.APP_NAME, settings.APP_VERSION)

    # Expired tokens are already refused at resolve time, so this is tidying
    # rather than security: a session nobody ever returns to would otherwise
    # sit in the table forever. Startup is the honest moment for it -- a
    # desktop app is restarted often enough, and a failure here must not stop
    # the API from serving.
    try:
        from utils.auth import user_store

        swept = user_store.delete_expired_sessions()
        if swept:
            logger.info("cleared %d expired session(s)", swept)
    except Exception as error:  # pragma: no cover - housekeeping, never fatal
        logger.warning("could not clear expired sessions: %s", error)

    yield
    logger.info("%s shutting down", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI career copilot: resume indexing, job analysis and match scoring.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One log line per request, with a correlation id echoed to the caller.

    Only the method, path and outcome are recorded. Bodies are not logged:
    they carry resumes, which are personal data.
    """
    request_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        logger.exception(
            "[%s] %s %s failed after %.1fms",
            request_id,
            request.method,
            request.url.path,
            elapsed,
        )
        raise

    elapsed = (time.perf_counter() - started) * 1000
    log = logger.warning if response.status_code >= 400 else logger.info
    log(
        "[%s] %s %s -> %d in %.1fms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(CareerPilotException)
async def careerpilot_exception_handler(
    request: Request, exc: CareerPilotException
) -> JSONResponse:
    """Turn a deliberate failure into a 500 that can be traced.

    These are the errors this project raises on purpose, so the message is
    written for a human and is safe to return. What made them unreachable
    before was that nothing caught them at the app level: an agent error that
    escaped a route produced Starlette's default 500, an empty body, and no way
    to tie the client's complaint to a log line.
    """
    error_id = uuid.uuid4().hex[:8]
    logger.error("[%s] %s at %s: %s", error_id, type(exc).__name__, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": str(exc),
            "error_type": type(exc).__name__,
            "error_id": error_id,
        },
        headers={"X-Request-ID": error_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything unplanned: log it in full, tell the caller almost nothing.

    An unexpected exception's text is not written for anyone outside this
    process. It carries absolute paths, SQL, and occasionally the value that
    broke - which for this application means resume text. The caller gets an
    id; the log gets the traceback.
    """
    error_id = uuid.uuid4().hex[:8]
    # The class name is safe to record and to reason about; the message is not,
    # and never leaves this process. logger.exception attaches the traceback.
    logger.exception(
        "[%s] unhandled %s at %s", error_id, type(exc).__name__, request.url.path
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error.",
            "error_id": error_id,
        },
        headers={"X-Request-ID": error_id},
    )


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
#: Name of the cookie carrying the session token.
SESSION_COOKIE = "careerpilot_session"

#: One resume index per account, built on demand. Chroma collections are cheap
#: to hold open; re-creating one per request would reopen the store on every
#: call.
_user_indexers: "OrderedDict[str, Any]" = OrderedDict()

#: One pipeline per account, for the same reason and with a sharper edge: the
#: workflow holds a *retriever*, and its first node will read the resume out of
#: it in preference to the text it was handed. A single shared instance would
#: therefore analyse the first caller's CV on everybody's behalf.
_user_workflows: "OrderedDict[str, Any]" = OrderedDict()

_indexer_lock = threading.Lock()


def _remember(cache: "OrderedDict[str, Any]", user_id: str, value: Any) -> Any:
    """Cache one account's object, dropping the least recently used.

    Both caches are keyed by account, so without a bound they grow once per
    person who ever signs in and never shrink. Eviction is safe rather than
    merely tolerable: everything cached here is a handle onto durable
    storage, so a dropped entry is rebuilt on the next request against the
    same Chroma collection and nothing is lost but the rebuild.

    Caller holds ``_indexer_lock``.
    """
    cache[user_id] = value
    cache.move_to_end(user_id)
    while len(cache) > ACTIVE_ACCOUNT_LIMIT:
        cache.popitem(last=False)
    return value


def current_user(request: Request) -> Dict[str, Any]:
    """The signed-in account, or a 401.

    Every route that touches stored data depends on this, and reads the id
    from *here* rather than from a query parameter or a request body. That is
    the whole point of the change: ``user_id`` used to be whatever the caller
    typed, so ``?user_id=someone_else`` returned someone else's saved jobs and
    applications. The field still exists on some request models, and is now
    ignored in favour of this.
    """
    from utils.auth import user_store

    token = request.cookies.get(SESSION_COOKIE) or ""
    if not token:
        # Bearer is accepted so the API stays usable from curl and from the
        # /docs page, neither of which carries cookies by default.
        header = request.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()

    account = user_store.resolve_session(token) if token else None
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account


def current_user_id(account: Dict[str, Any] = Depends(current_user)) -> str:
    """Just the id, for the many routes that need nothing else."""
    return str(account["user_id"])


def _collection_for(user_id: str) -> str:
    """A Chroma collection name for one account.

    Chroma restricts collection names, and a user id reaching this is already
    server-generated -- but it is concatenated into a name here, so it is
    filtered rather than trusted.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(user_id))[:48] or "anon"
    return "%s_%s" % (settings.CHROMA_COLLECTION_NAME, safe)


def get_indexer(user_id: str = Depends(current_user_id)):
    """The signed-in account's resume index.

    Each account gets its own Chroma collection, and that is the isolation
    boundary rather than a filter applied at query time. The difference
    matters: a metadata filter has to be remembered at every one of the
    indexer's read paths, and forgetting it once returns another user's CV. A
    separate collection fails the other way -- look in the wrong place and you
    get nothing.

    Imported lazily so that starting the app -- and collecting the test suite --
    never pulls in the ML stack.
    """
    from rag.resume_indexer import ResumeIndexer, shared_embedder

    with _indexer_lock:
        existing = _user_indexers.get(user_id)
        if existing is None:
            existing = ResumeIndexer(
                collection_name=_collection_for(user_id),
                embedder=shared_embedder,
            )
        return _remember(_user_indexers, user_id, existing)


def get_complete_workflow(
    user_id: str = Depends(current_user_id), indexer=Depends(get_indexer)
):
    """The seven-node pipeline for this account, built once and reused.

    The indexer is handed in as the retriever so the scorer can quote evidence
    straight from the vector index rather than re-scanning the raw text. This
    replaced a separate ``WorkflowGraph`` dependency: the pipeline builds one
    internally, and keeping a second would have meant two objects to configure
    identically and one to forget.

    Cached **per account**. It used to be one module-level instance, built with
    whichever indexer happened to arrive first and then handed to everyone --
    and because ``node_extract_resume`` prefers the retriever's text over the
    text it is given, that meant every later account's full analysis ran
    against the first account's resume.
    """
    with _indexer_lock:
        existing = _user_workflows.get(user_id)
        if existing is None:
            from agents.complete_workflow import CompleteWorkflow

            existing = CompleteWorkflow(retriever=indexer)
        return _remember(_user_workflows, user_id, existing)


# --------------------------------------------------------------------------- #
# Analysis history
# --------------------------------------------------------------------------- #
#: Recent runs, newest last, so the trace endpoint has something to read.
#
# Two deliberate constraints. It is **bounded**, because the ids are minted per
# request and an unbounded dict would let anyone with a loop exhaust the
# process. And it holds **only the trace** -- never the resume, never the
# advert, never the generated advice. A resume is personal data, and this is
# an in-memory cache; the trace is metadata about which node ran for how
# long, which is all the endpoint needs. Each entry also records the account
# that ran it, so one user cannot replay another's.
#
# Per-process, so it does not survive a restart and is not shared across
# workers. Fine for a trace viewer; a real audit trail belongs in a database.
_ANALYSIS_HISTORY: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

#: Adverts handed out by /discover-jobs, so /save-job can resolve an id.
_DISCOVERED_JOBS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


def _remember_analysis(
    analysis_id: str, result: Dict[str, Any], owner: str
) -> None:
    """Keep the trace for later retrieval, evicting the oldest run.

    ``owner`` is recorded so the trace endpoint can refuse to replay one
    account's run to another. Ids are random, but guessable-in-principle is
    not a security boundary.
    """
    summary = result.get("trace") or {}
    _ANALYSIS_HISTORY[analysis_id] = {
        "analysis_id": analysis_id,
        "owner": owner,
        "nodes": [
            {
                "name": row.get("node", ""),
                "status": row.get("status", "completed"),
                "duration_ms": int(row.get("duration_ms") or 0),
                "output_summary": detail,
            }
            for row, detail in zip(
                summary.get("trace") or [],
                [
                    str(entry.get("detail") or "")
                    for entry in (result.get("execution_trace") or [])
                ],
            )
        ],
        "total_duration_ms": int(summary.get("total_duration_ms") or 0),
        "status": result.get("status", "completed"),
    }
    while len(_ANALYSIS_HISTORY) > ANALYSIS_HISTORY_LIMIT:
        evicted, _ = _ANALYSIS_HISTORY.popitem(last=False)
        logger.debug("Evicted analysis %s from the trace cache", evicted)


def _validate_job_description(text: Optional[str]) -> str:
    """Structural checks here; whether the text is a real advert is the job
    analyzer's call, asked rather than reimplemented.

    Returns 422 for the structural limits to match ``JobDescriptionRequest``,
    whose ``min_length`` and ``max_length`` guard the other endpoints.
    Supporting multipart meant reading the body by hand instead of through that
    model, so its status codes have to be reproduced deliberately -- otherwise
    the same mistake would return 400 here and 422 one endpoint over.

    The analyzer's own verdict is asked for separately and returned as 400,
    because that is what ``/analyze-job`` returns for the identical input. It
    has to be asked *here*: the pipeline catches the error further in and
    scores whatever it managed to extract regardless, so "Python developer" --
    sixteen characters, which ``/analyze-job`` refuses outright -- came back
    from ``/full-analysis`` as "Apply. 100/100, nothing major standing in the
    way." Two words are not an advert, and a hundred percent match against two
    words is a number with nothing behind it.
    """
    from agents.job_analyzer import JobAnalysisError, validate_description

    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="job_description must not be empty.",
        )
    if len(cleaned) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"job_description is longer than "
                f"{MAX_JOB_DESCRIPTION_CHARS} characters."
            ),
        )
    try:
        validate_description(cleaned)
    except JobAnalysisError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return cleaned


async def _read_analysis_request(
    request: Request,
) -> Tuple[str, str, Optional[UploadFile]]:
    """Pull the advert, optional resume text and optional file off the request.

    Accepts JSON *and* multipart. A file can only arrive as multipart, but
    requiring multipart from callers whose resume is already indexed would mean
    building a form to send one string, so both are supported.
    """
    content_type = (request.headers.get("content-type") or "").split(";")[0]

    if content_type.strip().lower() == "application/json":
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001 - any parse failure is a 400
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request body is not valid JSON.",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request body must be a JSON object.",
            )
        return (
            str(payload.get("job_description") or ""),
            str(payload.get("resume_text") or ""),
            None,
        )

    form = await request.form()
    upload = form.get("resume_file")
    if not hasattr(upload, "filename"):
        upload = None
    return (
        str(form.get("job_description") or ""),
        str(form.get("resume_text") or ""),
        upload,
    )


async def _resolve_resume(
    resume_text: str,
    upload: Optional[UploadFile],
    indexer: Any,
) -> Tuple[str, str]:
    """Work out which resume to analyse, and say where it came from.

    Order of preference: an uploaded file, then text in the body, then whatever
    is already indexed. A caller who bothered to attach a file meant that one.
    """
    if upload is not None:
        text = await _index_upload(upload, indexer)
        return text, "upload"

    if resume_text.strip():
        return resume_text.strip(), "request"

    indexed = await run_in_threadpool(indexer.get_full_context)
    if not indexed.strip() or indexed.startswith("No resume data"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No resume available. Attach resume_file, send resume_text, or "
                "index one via POST /api/career/upload-resume."
            ),
        )
    return indexed, "index"


async def _index_upload(upload: UploadFile, indexer: Any) -> str:
    """Store and index an attached resume, returning its text."""
    from rag.resume_indexer import (
        DocumentParseError,
        FileValidationError,
        IndexerError,
    )

    destination, original_name, _size = await _store_upload(upload)
    try:
        summary = await run_in_threadpool(indexer.index_resume, destination)
    except FileValidationError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc).replace(destination.name, original_name),
        ) from exc
    except DocumentParseError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not read '{original_name}': {exc}",
        ) from exc
    except IndexerError as exc:
        logger.exception("Indexing failed for %s", original_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not index the resume.",
        ) from exc

    if summary.get("status") != "indexed" or not summary.get("chunks_indexed"):
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No text could be extracted from '{original_name}'. "
                "If it is a scanned PDF, it needs OCR first."
            ),
        )

    text = await run_in_threadpool(indexer.get_full_context)
    return text


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Name, version and where to find the docs - the usual front door."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def _issue_session(response: Response, user_id: str) -> None:
    """Put a fresh session token in an httpOnly cookie.

    ``httponly`` keeps the token out of ``document.cookie``, so a script
    injected into the page cannot read it. ``samesite="lax"`` is what stops
    another site silently POSTing to these endpoints with the cookie attached.

    ``secure`` follows ``DEBUG`` because this runs on plain http at localhost,
    and a cookie marked secure is simply never sent there -- the login would
    appear to succeed and every following request would be a 401.
    """
    from utils.auth import user_store

    session = user_store.create_session(user_id)
    response.set_cookie(
        SESSION_COOKIE,
        session["token"],
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
        max_age=settings.SESSION_TTL_HOURS * 3600,
        path="/",
    )


@app.post(
    "/api/auth/signup",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
async def signup(payload: SignupRequest, response: Response) -> AccountResponse:
    """Register an account and sign it in.

    Signing in immediately is deliberate: a signup that returns to the login
    page makes the user type the password they just chose, and the most common
    thing to do at that prompt is get it wrong.
    """
    from utils.auth import AuthError, DuplicateUserError, WeakPasswordError, user_store

    try:
        account = await run_in_threadpool(
            user_store.create_user, payload.email, payload.password, payload.name
        )
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await run_in_threadpool(_issue_session, response, account["user_id"])
    return AccountResponse(**account)


@app.post("/api/auth/login", response_model=AccountResponse, tags=["auth"])
async def login(payload: LoginRequest, response: Response) -> AccountResponse:
    """Exchange email and password for a session cookie.

    Every failure is one 401 with one message. Distinguishing "no such
    account" from "wrong password" would turn this endpoint into a way to test
    whether an address is registered.
    """
    from utils.auth import AuthError, InvalidCredentialsError, user_store

    try:
        account = await run_in_threadpool(
            user_store.authenticate, payload.email, payload.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is wrong.",
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    await run_in_threadpool(_issue_session, response, account["user_id"])
    return AccountResponse(**account)


@app.post("/api/auth/logout", response_model=LogoutResponse, tags=["auth"])
async def logout(request: Request, response: Response) -> LogoutResponse:
    """Delete the session server-side and clear the cookie.

    The row goes first. Clearing only the cookie would leave a token that
    still works for anyone who copied it before it left the browser.
    """
    from utils.auth import user_store

    token = request.cookies.get(SESSION_COOKIE) or ""
    if token:
        await run_in_threadpool(user_store.delete_session, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return LogoutResponse()


@app.get("/api/auth/me", response_model=AccountResponse, tags=["auth"])
async def whoami(account: Dict[str, Any] = Depends(current_user)) -> AccountResponse:
    """Who the cookie belongs to. The frontend uses this to decide what to show."""
    from utils.auth import user_store

    full = await run_in_threadpool(user_store.get_user, account["user_id"])
    return AccountResponse(**(full or account))


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness only: is the process up and serving?

    Deliberately does no dependency work, so an orchestrator's liveness probe
    cannot be made to time out by a slow database. ``/api/health/full`` is the
    one that probes dependencies.
    """
    return HealthResponse(app=settings.APP_NAME, version=settings.APP_VERSION)


@app.get("/api/health/full", tags=["meta"])
async def full_health_check(response: Response) -> dict:
    """Probe every dependency and report per-service status.

    The status code carries the verdict, because that is what a load balancer
    or orchestrator reads - a body saying "unhealthy" under a 200 keeps traffic
    coming to a broken instance. 503 means a *required* dependency is down.
    A missing language model is reported as ``degraded`` under a 200, because
    this service answers correctly without one by design.
    """
    from utils.health_check import UNHEALTHY, health_check

    report = await health_check.full_health_check()
    if report["overall_status"] == UNHEALTHY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@app.get("/api/health/performance", tags=["meta"])
async def performance_report() -> dict:
    """Recent latency percentiles and cache effectiveness.

    Reports a *window* of recent calls rather than an all-time average: an
    average over the life of the process is dominated by start-up outliers and
    keeps reporting yesterday's behaviour long after something has regressed.

    The cache hit rate is here because a speedup figure alone cannot show a
    broken cache - a cache serving nothing looks exactly like a fast
    application from outside, right up until the load that was supposed to be
    absorbed arrives.

    No inputs, keys or results are exposed: cache keys are sha256 digests and
    only counts are returned.
    """
    from utils.performance_monitor import performance_registry

    return {
        "operations": performance_registry.report(),
        "caches": cache_stats(),
    }


# --------------------------------------------------------------------------- #
# Upload helpers
# --------------------------------------------------------------------------- #
async def _store_upload(file: UploadFile) -> Tuple[Path, str, int]:
    """Stream an upload to disk, enforcing the extension and size limits.

    Returns ``(destination, original_name, size_bytes)``. Shared by both upload
    routes so the path-traversal and size checks cannot drift apart.
    """
    from rag.resume_indexer import new_resume_id

    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()
    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{extension}'. Allowed: {sorted(settings.ALLOWED_EXTENSIONS)}",
        )

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = settings.UPLOAD_DIR / f"{new_resume_id()}{extension}"

    size = 0
    try:
        with destination.open("wb") as buffer:
            while chunk := await file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
                    )
                buffer.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        logger.exception("Failed to store upload %s", original_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not store the uploaded file.",
        ) from exc
    finally:
        await file.close()

    return destination, original_name, size


# --------------------------------------------------------------------------- #
# Career API
# --------------------------------------------------------------------------- #
@app.post(
    f"{CAREER_PREFIX}/upload-resume",
    response_model=ResumeIndexResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["career"],
)
async def upload_and_index_resume(
    file: UploadFile = File(...),
    indexer=Depends(get_indexer),
) -> ResumeIndexResponse:
    """Store a resume and index it into the vector database."""
    from rag.resume_indexer import DocumentParseError, FileValidationError, IndexerError

    destination, original_name, size = await _store_upload(file)

    try:
        # Parsing and embedding are blocking CPU work; keep the event loop free.
        summary = await run_in_threadpool(indexer.index_resume, destination)
    except FileValidationError as exc:
        destination.unlink(missing_ok=True)
        # The message names the generated file; the caller only knows theirs.
        detail = str(exc).replace(destination.name, original_name)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    except DocumentParseError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not read '{original_name}': {exc}",
        ) from exc
    except IndexerError as exc:
        logger.exception("Indexing failed for %s", original_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not index the resume.",
        ) from exc

    if summary.get("status") != "indexed" or not summary.get("chunks_indexed"):
        # A scanned PDF parses fine and yields no text. Reporting success here
        # would leave the user with an empty index and no idea why.
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No text could be extracted from '{original_name}'. "
                "If it is a scanned PDF, it needs OCR first."
            ),
        )

    logger.info(
        "Indexed %s (%d bytes, %d chunks)",
        original_name,
        size,
        summary["chunks_indexed"],
    )
    return ResumeIndexResponse(status="success", message="Resume indexed", file_size=size)


@app.post(
    f"{CAREER_PREFIX}/analyze-job",
    response_model=JobAnalysisResponse,
    dependencies=[Depends(current_user)],
    tags=["career"],
)
async def analyze_job(payload: JobDescriptionRequest) -> Any:
    """Pull structured requirements out of a job advert.

    Signed-in only -- declared on the decorator because the route needs the
    check, not the account. Nothing personal is stored, but every call spends
    a model request, and an open endpoint that costs money is one someone
    else can spend for you.
    """
    from agents.job_analyzer import JobAnalysisError, job_analyzer_agent

    try:
        analysis = await run_in_threadpool(
            job_analyzer_agent.analyze, payload.job_description
        )
    except JobAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    logger.info(
        "Analysed advert '%s': %d required skill(s), confidence %.2f",
        analysis.get("title", "?"),
        len(analysis.get("required_skills") or []),
        analysis.get("confidence", 0.0),
    )
    return analysis


@app.post(
    f"{CAREER_PREFIX}/full-analysis",
    response_model=FullAnalysisResponse,
    tags=["career"],
)
async def full_analysis(
    request: Request,
    indexer=Depends(get_indexer),
    pipeline=Depends(get_complete_workflow),
    user_id: str = Depends(current_user_id),
) -> FullAnalysisResponse:
    """Run every agent over one resume and one advert.

    Accepts either JSON (``job_description``, optional ``resume_text``) or
    multipart form data with the same fields plus an optional ``resume_file``.
    A file can only be sent as multipart; callers whose resume is already
    indexed can stay on JSON.

    An attached file is indexed before the run, and the text analysed is that
    file's alone, so the resume scored is always the one the caller just sent.
    Note that indexing *adds* to the collection rather than replacing it: the
    upload does not evict an earlier resume, it only takes precedence for this
    request. Call ``POST /api/career/clear`` first to actually swap.
    """
    job_description, resume_text, upload = await _read_analysis_request(request)
    job_description = _validate_job_description(job_description)
    resume, resume_source = await _resolve_resume(resume_text, upload, indexer)

    result = await _run_pipeline(
        pipeline, resume, job_description, resume_source, user_id
    )
    report = result.get("match_result") or {}
    recommendation = result.get("recommendation") or {}

    return FullAnalysisResponse(
        analysis_id=result["analysis_id"],
        overall_match=report.get("overall_match", result.get("match_score", 0.0)),
        recommendation=recommendation.get("decision")
        or report.get("recommendation", "SKIP"),
        user_recommendation=result.get("user_recommendation", ""),
        analysis=_sections(result),
        execution_trace=result.get("execution_trace") or [],
        total_analysis_time_ms=round(result.get("total_duration_ms") or 0),
        status=result.get("status", "completed"),
        nodes_failed=result.get("nodes_failed") or [],
    )


@app.get(
    f"{CAREER_PREFIX}/analysis/{{analysis_id}}/trace",
    response_model=TraceResponse,
    tags=["career"],
)
async def analysis_trace(
    analysis_id: str, user_id: str = Depends(current_user_id)
) -> TraceResponse:
    """Replay which nodes ran for a past analysis, and for how long.

    Only the trace is kept -- no resume, no advert, no advice -- and only for
    the account that ran it. Held in memory, so an id stops resolving after
    a restart or once it falls out of the most recent
    ``ANALYSIS_HISTORY_LIMIT`` runs.

    Someone else's id gives the same 404 as an unknown one, so the endpoint
    cannot be used to discover which ids exist.
    """
    record = _ANALYSIS_HISTORY.get(analysis_id)
    if record is None or record.get("owner") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No trace for analysis '{analysis_id}'. Traces are kept in "
                f"memory for the last {ANALYSIS_HISTORY_LIMIT} runs."
            ),
        )

    return TraceResponse(
        analysis_id=record["analysis_id"],
        nodes=[TraceNode(**node) for node in record["nodes"]],
        total_duration_ms=record["total_duration_ms"],
        status=record["status"],
    )


def _sections(result: Dict[str, Any]) -> FullAnalysisSections:
    """Fold the pipeline's output into the documented five sections."""
    return FullAnalysisSections(
        job_analysis=result.get("analysis") or {},
        match_breakdown=(result.get("match_result") or {}).get(
            "match_breakdown", {}
        ),
        gaps=result.get("gaps") or {},
        resume_optimizations=result.get("resume_optimizations") or {},
        interview_prep=result.get("interview_prep") or {},
    )


async def _run_pipeline(
    pipeline: Any,
    resume: str,
    job_description: str,
    resume_source: str,
    owner: str,
) -> Dict[str, Any]:
    """Run the pipeline off the event loop, log it, and file its trace."""
    analysis_id = uuid.uuid4().hex[:12]
    logger.info(
        "[%s] Analysis requested: %d char advert, resume from %s",
        analysis_id,
        len(job_description),
        resume_source,
    )

    result = await run_in_threadpool(
        pipeline.run_complete_analysis,
        resume_text=resume,
        job_description=job_description,
    )
    result["analysis_id"] = analysis_id

    if result.get("status") == "failed":
        # The pipeline swallows node failures by design, so reaching "failed"
        # means it could not start at all.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("note") or "Analysis could not be run.",
        )

    _log_analysis(analysis_id, result)
    _remember_analysis(analysis_id, result, owner)
    return result


def _log_analysis(analysis_id: str, result: Dict[str, Any]) -> None:
    """Record the outcome and the trace.

    Node names, statuses and timings only. The advert and the resume are left
    out for the same reason request bodies are: they are personal data, and a
    log file is the easiest place to leak it from.
    """
    recommendation = result.get("recommendation") or {}
    decision = recommendation.get("decision", "?")

    logger.info(
        "[%s] Analysis %s: %s at %.1f/100 (scored %s, confidence %.2f) in %.0fms",
        analysis_id,
        result.get("status", "?"),
        decision,
        float(result.get("match_score") or 0.0),
        recommendation.get("scored_decision", "?"),
        float(recommendation.get("confidence") or 0.0),
        float(result.get("total_duration_ms") or 0.0),
    )

    for entry in result.get("execution_trace") or []:
        logger.info(
            "[%s]   %s. %-24s %-10s %7.1fms  %s",
            analysis_id,
            entry.get("step", "?"),
            entry.get("node", "?"),
            entry.get("status", "?"),
            float(entry.get("duration_ms") or 0.0),
            entry.get("detail", ""),
        )

    if recommendation.get("adjusted"):
        logger.info(
            "[%s] Verdict adjusted: %s", analysis_id,
            recommendation.get("adjustment_reason"),
        )

    for node in result.get("nodes_failed") or []:
        logger.warning("[%s] Node '%s' failed; result is partial", analysis_id, node)


@app.get(
    f"{CAREER_PREFIX}/status",
    response_model=IndexStatusResponse,
    tags=["career"],
)
async def career_status(indexer=Depends(get_indexer)) -> IndexStatusResponse:
    """Report whether a resume is indexed and ready to score against."""
    try:
        stats = await run_in_threadpool(indexer.stats)
    except Exception:  # noqa: BLE001 - a status probe must never raise
        logger.exception("Could not read index stats")
        return IndexStatusResponse(resume_indexed=False, status="degraded", chunks=0)

    chunks = int(stats.get("total_chunks", 0))
    return IndexStatusResponse(
        resume_indexed=chunks > 0,
        status="ready",
        chunks=chunks,
    )


@app.post(
    f"{CAREER_PREFIX}/clear",
    response_model=ClearIndexResponse,
    tags=["career"],
)
async def clear_index(indexer=Depends(get_indexer)) -> ClearIndexResponse:
    """Delete every indexed chunk. Uploaded files on disk are left alone."""
    try:
        stats = await run_in_threadpool(indexer.stats)
        removed = int(stats.get("total_chunks", 0))
        await run_in_threadpool(indexer.clear_index)
    except Exception as exc:  # noqa: BLE001 - surfaced as a 500 below
        logger.exception("Could not clear the index")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not clear the index.",
        ) from exc

    # Analyses derived from the cleared resume must go with it. Without this,
    # "clear" empties the index while leaving the conclusions drawn from it
    # readable for up to two hours - a privacy control that quietly does half
    # its job is worse than one that is documented as absent.
    clear_all_caches()

    logger.info("Cleared the index (%d chunks removed)", removed)
    return ClearIndexResponse(
        status="success",
        message="Index cleared",
        chunks_removed=removed,
    )


# --------------------------------------------------------------------------- #
# Job discovery
# --------------------------------------------------------------------------- #
def _remember_jobs(jobs: List[Dict[str, Any]]) -> None:
    """Keep discovered adverts so that ``save-job`` can resolve an id.

    ``save-job`` takes an id, not a job body. That is the point: if the client
    posted the whole advert back, anyone could write arbitrary text into the
    store through it. The cost is that the server has to remember what it just
    handed out, which is what this does -- bounded and oldest-first, exactly
    like the analysis history above, so a long-running server cannot grow
    without limit.
    """
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        _DISCOVERED_JOBS[job_id] = job
        _DISCOVERED_JOBS.move_to_end(job_id)
    while len(_DISCOVERED_JOBS) > DISCOVERED_JOBS_LIMIT:
        _DISCOVERED_JOBS.popitem(last=False)


@app.post(
    f"{CAREER_PREFIX}/discover-jobs",
    response_model=JobDiscoveryResponse,
    tags=["career"],
)
async def discover_jobs(
    payload: JobDiscoveryRequest,
    indexer=Depends(get_indexer),
) -> JobDiscoveryResponse:
    """Find live adverts, analyse each one, and score them against the resume.

    Scoring is skipped -- not faked -- when no resume is indexed. The adverts
    are still worth returning, so this answers 200 with ``match_score`` null
    and ``scored_against_resume`` false rather than refusing outright.

    With ``auto_from_resume`` the caller supplies no query at all: the resume
    is profiled, and the phrases it points at are searched one after another.
    Each phrase is a separate round of requests to every board, so the limit
    is spread across them rather than applied per phrase -- three queries at
    the full limit would return three pages of adverts for one click.
    """
    if not settings.JOB_DISCOVERY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job discovery is disabled (JOB_DISCOVERY_ENABLED=false).",
        )

    from agents.job_enricher import job_enricher
    from agents.job_scraper import SOURCE_TERMS, job_scraper

    queries = [payload.query]
    derived = False
    if payload.auto_from_resume:
        resume, _source = await _resolve_resume("", None, indexer)
        insights = await _profile_resume(resume)
        queries = list(insights.get("search_queries") or [])[:MAX_AUTO_QUERIES]
        if not queries:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Your resume does not name enough technologies to work out "
                    "which roles to search for. Add a skills section, or type a "
                    "search yourself."
                ),
            )
        derived = True

    # Whole rounds only: a limit of 10 over 3 queries is 4 each, not 3.33.
    per_query = max(1, -(-payload.limit // len(queries)))

    jobs: List[Dict[str, Any]] = []
    seen: set = set()
    failures = 0
    for query in queries:
        try:
            found = await run_in_threadpool(
                job_scraper.search, query, payload.location, per_query
            )
        except Exception:  # noqa: BLE001 - one query failing is survivable
            logger.exception("Job discovery failed for %r", query)
            failures += 1
            continue
        for job in found:
            key = job.get("job_id") or job.get("url")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            jobs.append(job)

    if failures == len(queries):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach any job source right now.",
        )

    jobs, age_used, freshness_note = _apply_freshness(jobs, payload.max_age_days)
    undated = sum(1 for job in jobs if job.get("days_old") is None)
    jobs = jobs[: payload.limit]

    if not jobs:
        return JobDiscoveryResponse(
            jobs=[],
            categorized={},
            total_found=0,
            sources_used=[],
            attribution=[],
            queries_used=queries,
            derived_from_resume=derived,
            max_age_days_used=age_used,
            freshness_note=freshness_note,
        )

    # Score against the resume only if there is one. `get_resume_data` returns
    # None when the index is empty.
    resume_data = None
    try:
        resume_data = await run_in_threadpool(_resume_data_or_none, indexer)
    except Exception:  # noqa: BLE001 - discovery still works without a resume
        logger.exception("Could not read the resume; returning unscored jobs")

    enriched = await run_in_threadpool(
        job_enricher.batch_enrich_jobs, jobs, resume_data
    )
    categorized = job_enricher.categorize_jobs(enriched)
    _remember_jobs(enriched)

    sources = sorted({str(job.get("source") or "") for job in enriched} - {""})
    return JobDiscoveryResponse(
        jobs=enriched,
        categorized=categorized,
        total_found=len(enriched),
        sources_used=sources,
        attribution=[SOURCE_TERMS[name] for name in sources if name in SOURCE_TERMS],
        scored_against_resume=resume_data is not None,
        queries_used=queries,
        derived_from_resume=derived,
        max_age_days_used=age_used,
        freshness_note=freshness_note,
        undated_count=undated,
    )


#: Nothing older than this is ever shown, whatever the caller asks for.
#:
#: This is a product promise rather than a tuning knob: the app offers "jobs
#: from the last 7 days", so a list that quietly reaches back a month to look
#: busier is the one thing it must not do. An advert nobody dated cannot be
#: shown to be inside the window, so it does not appear either -- "we do not
#: know how old this is" is not the same answer as "recent enough".
_MAX_WINDOW_DAYS = 7

#: Below this, a narrower request opens up to the ceiling rather than showing
#: a near-empty page. Three fresh adverts that fit is a good morning's work.
_TOO_FEW = 3


def _apply_freshness(
    jobs: List[Dict[str, Any]], requested: Optional[int]
) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    """Keep adverts posted within the window, never widening past 7 days.

    Returns the adverts, the window actually applied, and a note explaining
    any difference between that and the one asked for.

    A narrower request that finds almost nothing opens up as far as the
    ceiling and says so. Past the ceiling there is no widening left: when a
    week genuinely holds nothing the honest answer is a short list or an empty
    one with an explanation, not a month of older posts under a heading that
    says seven days.
    """
    from agents.job_scraper import fresh_jobs

    window = _MAX_WINDOW_DAYS if requested is None else min(requested, _MAX_WINDOW_DAYS)
    kept = fresh_jobs(jobs, window)

    if len(kept) >= _TOO_FEW:
        if requested is not None and requested > _MAX_WINDOW_DAYS:
            return kept, window, (
                "This list covers the last %d days. Older adverts are not "
                "shown, because they are usually filled by the time you apply."
                % _MAX_WINDOW_DAYS
            )
        return kept, window, None

    # Too few. Open up as far as the ceiling, which is as wide as it ever goes.
    widened = kept if window >= _MAX_WINDOW_DAYS else fresh_jobs(jobs, _MAX_WINDOW_DAYS)
    if len(widened) > len(kept):
        return widened, _MAX_WINDOW_DAYS, (
            "Only %d advert(s) matched you from the last %d days, so this list "
            "covers the last %d days instead."
            % (len(kept), window, _MAX_WINDOW_DAYS)
        )

    # Nothing more to be had. Report the widest window actually examined:
    # "nothing in the last 2 days" would invite a retry that cannot help.
    if not widened:
        return [], _MAX_WINDOW_DAYS, (
            "Nothing matching you was posted in the last %d days. Older "
            "adverts are not shown; try a broader search term."
            % _MAX_WINDOW_DAYS
        )
    return widened, _MAX_WINDOW_DAYS, (
        "Only %d advert(s) matching you were posted in the last %d days."
        % (len(widened), _MAX_WINDOW_DAYS)
    )


def _resume_data_or_none(indexer: Any) -> Optional[Dict[str, Any]]:
    """The indexed resume as the matcher expects it, or None if none is indexed.

    ``{"resume_text": ...}`` is the shape `MatchCalculator.calculate_match`
    documents; handing it the indexer instead would silently score every job
    against nothing.

    The indexer is passed in rather than imported. Reaching for the module-level
    ``resume_indexer`` here would score every signed-in user against whatever is
    in the shared default collection instead of their own resume.
    """
    if indexer.is_empty():
        return None
    text = indexer.get_full_context()
    return {"resume_text": text} if text.strip() else None


# --------------------------------------------------------------------------- #
# Resume insights, chat and interview prep
# --------------------------------------------------------------------------- #
async def _profile_resume(resume_text: str) -> Dict[str, Any]:
    """Describe one resume, and record whether a model or a rule did it.

    ``source`` and ``warning`` are lifted out of the agent result and onto the
    payload deliberately. Both are shown in the UI: an answer written by a
    keyword matcher and one written by a model look identical on screen, and
    this is the only thing that tells them apart.
    """
    from agents.resume_profiler import resume_profiler

    result = await run_in_threadpool(resume_profiler.run, resume_text=resume_text)
    payload = dict(result.output)
    payload["source"] = result.source
    payload["warning"] = result.warning
    return payload


def _role_type_of(primary_role: str) -> str:
    """Reduce "backend developer" to the "backend" that the prep agent keys on.

    Its behavioural question bank is indexed by role *type*, not job title, so
    the trailing noun has to come off or every lookup misses and the candidate
    gets the generic set.
    """
    role = primary_role.strip().lower()
    for suffix in (" developer", " engineer", " specialist"):
        if role.endswith(suffix):
            return role[: -len(suffix)]
    return role


async def _read_resume_request(
    request: Request,
) -> Tuple[str, str, Optional[UploadFile]]:
    """Accept either JSON or multipart, and return ``(resume_text, job, upload)``.

    Mirrors ``_read_analysis_request`` but tolerates a missing body entirely:
    the common call here is "describe whatever I already uploaded", which has
    nothing to send.
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("resume_file")
        return (
            str(form.get("resume_text") or ""),
            str(form.get("job_description") or ""),
            upload if isinstance(upload, UploadFile) else None,
        )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - an empty body is a valid request here
        return "", "", None
    if not isinstance(body, dict):
        return "", "", None
    return (
        str(body.get("resume_text") or ""),
        str(body.get("job_description") or ""),
        None,
    )


@app.post(
    f"{CAREER_PREFIX}/resume-insights",
    response_model=ResumeInsightsResponse,
    tags=["career"],
)
async def resume_insights(
    request: Request,
    indexer=Depends(get_indexer),
) -> ResumeInsightsResponse:
    """Describe a resume on its own, with no job advert involved.

    This is the question a user asks before they have a posting in mind:
    *what does my CV actually say about me?* Every other analysis route needs
    an advert to compare against and cannot answer it.

    Accepts JSON (optional ``resume_text``), multipart with a ``resume_file``,
    or an empty body to use whatever is already indexed. Answers 409 when
    there is no resume anywhere -- there is nothing honest to return.
    """
    resume_text, _job, upload = await _read_resume_request(request)
    resume, resume_source = await _resolve_resume(resume_text, upload, indexer)

    insights = await _profile_resume(resume)
    return ResumeInsightsResponse(resume_source=resume_source, **insights)


@app.post(
    f"{CAREER_PREFIX}/chat",
    response_model=ChatResponse,
    tags=["career"],
)
async def chat(payload: ChatRequest, indexer=Depends(get_indexer)) -> ChatResponse:
    """Answer one question about the indexed resume.

    Stateless: the transcript arrives with every call rather than being kept
    per-connection, so there is no session to expire and no cross-request
    state to leak between users of a shared instance.

    Answers 200 with ``resume_available: false`` when nothing is indexed
    instead of 409. A chat box that refuses to open cannot tell the user *why*
    it refused, and "upload your CV first" is exactly the reply that helps.
    """
    from agents.career_chat import career_chat as chat_agent

    context = await run_in_threadpool(indexer.get_full_context)
    if not context.strip() or context.startswith("No resume data"):
        context = ""

    profile: Dict[str, Any] = {}
    if context:
        try:
            profile = await _profile_resume(context)
        except Exception:  # noqa: BLE001 - chat is still useful without it
            logger.exception("Could not profile the resume for chat")

    result = await run_in_threadpool(
        chat_agent.reply,
        payload.message,
        context,
        [turn.model_dump() for turn in payload.history],
        profile,
        _job_context(payload.job_title, payload.job_description),
    )
    return ChatResponse(resume_available=bool(context), **result)


def _job_context(title: str, description: str) -> str:
    """The advert the caller has open, as one block of text for the prompt.

    Empty when they have not picked one, which the agent treats as "no job
    yet" rather than as an empty advert.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    if not description:
        return ""
    if title:
        return "%s\n\n%s" % (title, description)
    return description


@app.post(
    f"{CAREER_PREFIX}/interview-prep",
    response_model=InterviewPrepResponse,
    tags=["career"],
)
async def interview_prep(
    payload: InterviewPrepRequest,
    indexer=Depends(get_indexer),
) -> InterviewPrepResponse:
    """Build interview questions from a resume, and from an advert if there is one.

    The advert is optional, which is the whole point of this route existing
    separately from ``/full-analysis``: someone with an interview on Thursday
    and no job text saved still needs questions, and running the seven-node
    pipeline to get them would require an advert it does not have.
    """
    from agents.interview_prep import InterviewPrepAgent

    resume, resume_source = await _resolve_resume(payload.resume_text, None, indexer)

    job_analysis: Optional[Dict[str, Any]] = None
    advert = payload.job_description.strip()
    if advert:
        # `job_analyzer_agent`, not `job_analyzer`: the former is the BaseAgent
        # wrapper returning a plain dict, which is the shape `prepare_interview`
        # reads. The latter takes a `JobDescription` model and returns another.
        from agents.job_analyzer import JobAnalysisError, job_analyzer_agent

        try:
            job_analysis = await run_in_threadpool(job_analyzer_agent.analyze, advert)
        except JobAnalysisError as exc:
            # An unreadable advert is the caller's typo, not a server fault, and
            # a 500 here reads as "the app broke" when the box is optional and
            # leaving it *empty* works fine. Typing a little must not be worse
            # than typing nothing.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{exc} Paste the full advert, or clear the box to get "
                    f"questions from your resume alone."
                ),
            ) from exc
    else:
        # `prepare_interview` builds its technical questions from the overlap
        # between what an advert demands and what the resume evidences. With no
        # advert that overlap is empty and it returns nothing at all -- which
        # would make this route answer 200 with zero questions, the most
        # useless possible response to "help me prepare".
        #
        # So the resume stands in for the advert: you get asked about what your
        # own CV claims. That is a fair approximation of an unseen first-round
        # screen, and `tailored_to_job` stays false so the UI never implies a
        # target role that was never supplied.
        insights = await _profile_resume(resume)
        skills = list(insights.get("skills") or [])
        job_analysis = {
            "required_skills": skills,
            "preferred_skills": [],
            "tech_stack": skills,
            "role_type": _role_type_of(str(insights.get("primary_role") or "")),
            "job_description": "",
        }

    agent = InterviewPrepAgent()
    report = await run_in_threadpool(
        agent.prepare_interview,
        job_analysis,
        {"resume_text": resume},
        None,
        None,
    )

    return InterviewPrepResponse(
        interview_difficulty=str(report.get("interview_difficulty") or "unknown"),
        estimated_prep_time_hours=report.get("estimated_prep_time_hours"),
        questions=report.get("questions") or [],
        behavioral_questions=report.get("behavioral_questions") or [],
        hr_questions=report.get("hr_questions") or [],
        scenario_questions=report.get("scenario_questions") or [],
        project_questions=report.get("project_questions") or [],
        areas_to_improve=report.get("areas_to_improve") or [],
        company_questions=report.get("company_questions") or [],
        your_questions_for_them=report.get("your_questions_for_them") or [],
        preparation_plan=report.get("preparation_plan") or [],
        question_count=int(report.get("question_count") or 0),
        tailored_to_job=bool(advert),
        honesty_note=str(report.get("honesty_note") or ""),
        source=str(report.get("source") or "fallback"),
        resume_source=resume_source,
    )


@app.post(
    f"{CAREER_PREFIX}/practice-answer",
    response_model=PracticeAnswerResponse,
    dependencies=[Depends(current_user)],
    tags=["career"],
)
async def practice_answer(
    payload: PracticeAnswerRequest,
) -> PracticeAnswerResponse:
    """Give feedback on one practice interview answer.

    Takes no resume, on purpose. The thing being judged is the answer the
    candidate just typed, and pulling their CV in would let the feedback
    credit them for something they wrote months ago rather than something they
    said just now.

    ``score`` comes back as ``None`` whenever no model read the answer, and the
    caller must render that as "not scored". A number out of ten is the most
    persuasive thing this app can put on a screen and the cheapest to fake; a
    fabricated 8/10 is worse than no feedback at all, because it is the one
    that stops someone preparing.
    """
    from agents.answer_coach import answer_coach

    result = await run_in_threadpool(
        answer_coach.evaluate,
        payload.question,
        payload.answer,
        payload.skill,
    )
    return PracticeAnswerResponse(**result)


@app.post(
    f"{CAREER_PREFIX}/save-job",
    response_model=SaveJobResponse,
    tags=["career"],
)
async def save_job(
    payload: SaveJobRequest, user_id: str = Depends(current_user_id)
) -> SaveJobResponse:
    """Keep a discovered job for later.

    The row is namespaced by the *signed-in* account. A ``user_id`` sent in the
    body is ignored -- it used to choose the owner, which made every saved job
    readable by anyone willing to guess an id.
    """
    from agents.job_storage import JobStorageError, job_storage

    job = _DISCOVERED_JOBS.get(payload.job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Unknown job_id. Run /discover-jobs first; only jobs from a "
                "recent search can be saved."
            ),
        )

    record = dict(job)
    record["status"] = payload.status
    record["notes"] = payload.notes

    try:
        job_id = await run_in_threadpool(job_storage.save_job, record, user_id)
        count = await run_in_threadpool(job_storage.count_user_jobs, user_id)
    except JobStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaveJobResponse(saved=True, job_id=job_id, user_jobs_count=count)


@app.get(
    f"{CAREER_PREFIX}/my-jobs",
    response_model=SavedJobsResponse,
    tags=["career"],
)
async def my_jobs(
    job_status: Optional[str] = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Depends(current_user_id),
) -> SavedJobsResponse:
    """Every job this user saved, newest first, optionally filtered by status."""
    from agents.job_storage import JobStorageError, job_storage

    try:
        if job_status:
            jobs = await run_in_threadpool(
                job_storage.get_jobs_by_status, user_id, job_status, limit
            )
        else:
            jobs = await run_in_threadpool(
                job_storage.get_user_saved_jobs, user_id, limit
            )
        counts = await run_in_threadpool(job_storage.status_counts, user_id)
    except JobStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SavedJobsResponse(
        jobs=jobs, total=len(jobs), status_counts=counts, user_id=user_id
    )


# ---------------------------------------------------------------------------
# Application tracking
#
# Every route below takes its ``user_id`` from the session cookie. The
# ``user_id`` field on the request models is ignored: it was previously
# whatever the caller sent, which let anyone read anyone's applications by
# guessing an id.
# ---------------------------------------------------------------------------


@app.post(
    f"{CAREER_PREFIX}/create-application",
    response_model=CreateApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
)
async def create_application(
    payload: CreateApplicationRequest,
    user_id: str = Depends(current_user_id),
) -> CreateApplicationResponse:
    """Start tracking an attempt at one job."""
    from agents.application_tracker import ApplicationError, application_tracker

    try:
        app_id = await run_in_threadpool(
            application_tracker.create_application,
            user_id,
            payload.job_id,
            payload.analysis_data,
            payload.status,
        )
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return CreateApplicationResponse(application_id=app_id, status=payload.status)


@app.post(
    f"{CAREER_PREFIX}/application/{{app_id}}/update-status",
    response_model=UpdateApplicationStatusResponse,
    tags=["applications"],
)
async def update_application_status(
    app_id: str,
    payload: UpdateApplicationStatusRequest,
    user_id: str = Depends(current_user_id),
) -> UpdateApplicationStatusResponse:
    """Move an application along and record the move in its timeline."""
    from agents.application_tracker import ApplicationError, application_tracker

    try:
        updated = await run_in_threadpool(
            application_tracker.update_application_status,
            app_id,
            payload.status,
            payload.details,
            user_id,
        )
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application %r for this user." % app_id,
        )

    return UpdateApplicationStatusResponse(
        updated=True, app_id=app_id, status=payload.status
    )


@app.get(
    f"{CAREER_PREFIX}/my-applications",
    response_model=ApplicationsResponse,
    tags=["applications"],
)
async def my_applications(
    application_status: Optional[str] = Query(
        default=None, alias="status", max_length=32
    ),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Depends(current_user_id),
) -> ApplicationsResponse:
    """Every application this user has, newest first, each with its timeline."""
    from agents.application_tracker import ApplicationError, application_tracker

    try:
        if application_status:
            applications = await run_in_threadpool(
                application_tracker.get_applications_by_status,
                user_id,
                application_status,
                limit,
            )
        else:
            applications = await run_in_threadpool(
                application_tracker.get_application_history, user_id, limit
            )
        counts = await run_in_threadpool(application_tracker.status_counts, user_id)
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return ApplicationsResponse(
        applications=applications,
        total=len(applications),
        status_counts=counts,
        user_id=user_id,
    )


@app.get(
    f"{CAREER_PREFIX}/application/{{app_id}}/history",
    response_model=ApplicationHistoryResponse,
    tags=["applications"],
)
async def application_history(
    app_id: str,
    user_id: str = Depends(current_user_id),
) -> ApplicationHistoryResponse:
    """The complete timeline of one application.

    The account is always passed to the lookup. It used to be optional, and
    omitting it returned any application by id regardless of who owned it.
    """
    from agents.application_tracker import ApplicationError, application_tracker

    try:
        record = await run_in_threadpool(
            application_tracker.get_application, app_id, user_id
        )
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application %r." % app_id,
        )

    return ApplicationHistoryResponse(
        app_id=record["app_id"],
        job_title=record["job_title"],
        company=record["company"],
        match_score=record["match_score"],
        current_status=record["current_status"],
        timeline=record["timeline"],
        interviews=record.get("interviews", []),
        gaps_identified=record.get("gaps_identified", []),
    )


@app.get(
    f"{CAREER_PREFIX}/analytics",
    response_model=AnalyticsResponse,
    tags=["applications"],
)
async def analytics(
    user_id: str = Depends(current_user_id),
) -> AnalyticsResponse:
    """Success rates, a strategy, and a forecast where the data supports one.

    Fields come back ``null`` rather than zero when there is not enough
    history to compute them. That is the point: an interview rate of "0%"
    from no applications reads as failure, when the truth is that nothing has
    been measured yet.
    """
    from agents.application_analytics import application_analytics
    from agents.application_tracker import ApplicationError

    def _gather() -> Dict[str, Any]:
        history = application_analytics.tracker.get_application_history(user_id)
        return {
            "metrics": application_analytics.calculate_success_metrics(user_id, history),
            "strategy": application_analytics.recommend_application_strategy(
                user_id, history
            ),
            "prediction": application_analytics.predict_offer_probability(
                user_id, history
            ),
        }

    try:
        result = await run_in_threadpool(_gather)
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return AnalyticsResponse(user_id=user_id, **result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
