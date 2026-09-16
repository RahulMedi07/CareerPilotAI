# CareerPilot AI — Developer Log

Technical record of the project. **This file is updated after every prompt.**

---

## Current state

| Area | Status |
|---|---|
| FastAPI app + CORS | Done |
| `/health`, `/` | Done |
| Resume upload endpoint | **Done** — stores *and* indexes via `/api/career/upload-resume` |
| Config via `pydantic-settings` | **Done** — validated allow-lists, cwd-independent paths, `.env.example`, `python config.py` smoke check |
| Logging (console + rotating file) | **Done** — fully driven by settings, plus per-request access logging with a correlation id |
| RAG indexer (Chroma + embeddings) | **Done** — verified end-to-end against the real model, **now exposed via the API** |
| Job analyzer agent | **Done** — `JobAnalyzerAgent`: LLM-first structured extraction, keyword fallback, confidence score |
| Match calculator | **Done** — `MatchCalculator`: 5 weighted components, fuzzy skill matching, RAG-backed evidence, APPLY/MAYBE/SKIP verdict |
| `AgentConfig` + LLM routing | **Done** — Ollama first, Claude fallback, deterministic last resort |
| LangGraph workflow | **Done** — 4-node graph, plus the 7-node `CompleteWorkflow` **exposed via `/api/career/full-analysis`** |
| Execution trace | **Done** — per-node step, status, duration, detail, plus agent-specific columns; returned to the caller and replayable via `/api/career/analysis/{id}/trace` |
| Unit tests | 2512 passing |
| Week 2 agent upgrades | **Done** — curated documentation links, practice projects, keyword-density table, strength/weakness question split, success-rate reasoning, shared input coercion |
| Job discovery | **Done** — `JobScraper` (Hacker News, WeWorkRemotely, Remotive, Arbeitnow), SSRF allow-list, robots.txt per RFC 9309, entity-bomb refusal; `JobEnricher` (threaded, order-preserving); `JobStorage` (SQLite) — exposed via `/discover-jobs`, `/save-job`, `/my-jobs` |
| Application tracking | **Done** — `ApplicationTracker` (applications + event timeline + interviews, SQLite), `ApplicationAnalytics` (Wilson intervals, gap lift, withheld forecasts), `ApplicationDashboard`; six endpoints from `/create-application` to `/dashboard` |
| Advanced LangGraph | **Done** — `AdvancedWorkflow` (10 nodes, 2 branch points, 4 routes), `conditional_graph` (routers return branch + reason), `AgentCollaboration` (delegation with transcript), `LearningPathAgent` (day-by-day plans); default path of `run_complete_analysis`, legacy keys unchanged |
| Error handling & resilience | **Done** — `CareerPilotException` family retrofitted onto all 16 existing exceptions (nothing narrowed); `retry_with_backoff` with jitter, caps and a transient-only allow-list wired into the scraper's HTTP choke-point; `StructuredLogger` + `@observed` on all 7 agent entry points; `utils/health_check.py` behind `GET /api/health/full`; app-level handlers so nothing escapes as a bare 500 |
| Performance & caching | **Done** — measured first: the pipeline was already 2.79 ms on the keyword path, so the work went where measurement pointed. Found and fixed the vector store holding 27 rows for 9 distinct chunks (top-5 search was returning 2 distinct facts); `utils/cache.py` (TTL + LRU, keyed on inputs and on which backend would answer) wired into job analysis at 28x; `utils/performance_monitor.py` behind `GET /api/health/performance`; `ParallelExecutor` that threads only when a model is reachable; `utils/benchmarks.py` |
| Integration & docs | **Done** — `agents/job_hunt_pipeline.py` (discover → score → analyse → save → metrics → dashboard, seven traced steps, injectable source so tests never hit the network, never raises); `tests/test_job_hunt_pipeline.py` (12), `tests/test_week2_complete.py` (11 cross-component) and `tests/test_week2_api.py` (4 journey/orphan); `docs/USAGE_GUIDE.md`, `docs/DEPLOYMENT.md`, `WEEK2_COMPLETE.md`. Found two real defects on the way: two users could never save the same advert (`UNIQUE constraint failed: jobs.job_id`), and `isolated_storage` was not isolating the SQLite database, so the suite had been reading and writing `data/jobs.db` |
| Frontend | **Done** — Next.js 16 / React 19 / Tailwind v4, 13 build routes, 12 pages (10 dashboard + login + signup) |
| Resume-only reading | **Done** — `ResumeProfilerAgent` describes a CV on its own terms (role, seniority, grouped skills, strengths, fixes, roles to search) with an LLM path and a deterministic fallback; `POST /api/career/resume-insights` |
| Interactive assistant | **Done** — `CareerChatAgent`, `POST /api/career/chat`. Every reply is labelled `llm` or `fallback`, and the fallback declines rather than improvises |
| Interview prep without an advert | **Done** — `POST /api/career/interview-prep`, advert optional; with no advert the questions are synthesised from the CV's own skills and `tailored_to_job` stays false |
| Practising an answer | **Done** — `AnswerCoachAgent`, `POST /api/career/practice-answer`. Scores 1–10 with a model; with none it returns `score: null` and a list of checkable observations rather than an invented mark |
| Job search from the CV | **Done** — `discover-jobs` accepts `auto_from_resume`, infers up to `MAX_AUTO_QUERIES` phrases from the resume and returns `queries_used` so the guess is visible |
| Accounts | **Done** — `utils/auth.py` (PBKDF2 600k, per-row iteration count, opaque tokens stored only as SHA-256), four `/api/auth/*` endpoints, session cookie (`HttpOnly`, `SameSite=Lax`). Every data endpoint derives `user_id` from the session and **ignores** any caller-supplied id; the resume index is one Chroma collection per account, and job scoring reads that same per-account index, so isolation fails closed. Login/signup pages, a route guard on the dashboard group, and sign-out in the header |

Python in use: **3.9.6** — code avoids `X | Y` union syntax (PEP 604 needs 3.10+).

---

## Layout

```
career-pilot-ai/
├── backend/
│   ├── main.py                    # FastAPI app, middleware, /api/career routes
│   ├── config.py                  # Settings: paths, LLM, embeddings, API, logging
│   ├── .env.example               # Annotated template -- cp to .env
│   ├── requirements.txt           # Runtime deps
│   ├── requirements-dev.txt       # pytest, httpx
│   ├── pytest.ini                 # pythonpath=. so tests import local modules
│   ├── test_week1.py              # Standalone smoke check (not collected by pytest)
│   ├── run_test.py                # End-to-end pipeline demo with formatted report
│   ├── test_complete_workflow.py  # Demo script: full 7-node analysis → results.txt
│   ├── conftest.py                # Keeps the root-level scripts out of collection
│   ├── test_api.py                # Starts uvicorn and tests every endpoint over HTTP
│   ├── samples/                   # Sample advert + resume for the smoke check
│   ├── data/sample_jd.txt         # Fixture: AI/ML Engineer advert (tracked)
│   ├── data/sample_resume.txt     # Fixture: 2-year candidate, scores SKIP (tracked)
│   ├── models/career_models.py    # Pydantic request/response schemas
│   ├── rag/resume_indexer.py      # Extract → section → chunk → embed → Chroma → search
│   ├── agents/__init__.py         # AgentConfig, LLMProvider
│   ├── agents/ollama_handler.py   # Ollama client, Claude fallback, prompt templates
│   ├── agents/base_agent.py       # BaseAgent + skills/gaps/match agents + tools
│   ├── agents/workflow_state.py   # WorkflowState TypedDict, trace helpers
│   ├── agents/graph_builder.py    # LangGraph StateGraph wiring and execution
│   ├── agents/job_analyzer.py     # JobAnalyzerAgent + keyword JobAnalyzer + extractors
│   ├── agents/match_calculator.py # 5-component weighted scoring + recommendation
│   ├── agents/gap_detector.py     # Gap grading, learning-time estimates, study plans
│   ├── agents/resume_optimizer.py # Tailored rewrites, keywords, reordering (node 5)
│   ├── agents/interview_prep.py   # Questions, answer scaffolds, prep plan (node 6)
│   ├── agents/complete_workflow.py # The full 7-node pipeline and final verdict
│   ├── agents/advanced_workflow.py # 10-node branching pipeline (default path)
│   ├── agents/conditional_graph.py # Branch routers, thresholds, graph description
│   ├── agents/agent_collaboration.py # Agent-to-agent delegation + transcript
│   ├── agents/learning_path_agent.py # Day-by-day study plans, effort estimates
│   ├── utils/logger.py            # Logging setup + StructuredLogger + @observed
│   ├── utils/error_handling.py    # CareerPilotException family, classify, envelope, safe_call
│   ├── utils/retry_handler.py     # retry_with_backoff: jitter, caps, allow-list
│   ├── utils/health_check.py      # Concurrent probes behind /api/health/full
│   ├── utils/cache.py             # TTL + LRU, SHA-256 keys, deep-copied values
│   ├── utils/performance_monitor.py # Rolling-window percentiles, perf_counter
│   ├── utils/benchmarks.py        # Measures at run time; python -m utils.benchmarks
│   ├── agents/parallel_executor.py # Threads only when a model is reachable
│   ├── agents/job_hunt_pipeline.py # Discover → score → analyse → save → metrics
│   ├── utils/skills.py            # Skill vocabulary, word-boundary matcher, fuzzy matcher
│   └── tests/                     # Unit + integration tests
├── README.md                      # The user-facing guide. No code in it.
└── README_DEV.md                  # This file: decisions, log, deployment
```

> **Documentation was consolidated to two files.** `README_SIMPLE.md`,
> `WEEK2_COMPLETE.md`, `docs/USAGE_GUIDE.md`, `docs/DEPLOYMENT.md` and the
> `frontend/` placeholder were removed. The deployment guide is now the last
> section of this file; the usage walkthrough is covered by `README.md` and the
> interactive `/docs` page. Tables and log entries elsewhere in this file still
> name those files — that is a record of what was true at the time and has been
> left as-is rather than rewritten.

---

## RAG pipeline

```
PDF/TXT/MD ──PyPDF2──> raw text ──heading detector──> sections
     └─> chunk 250 chars / 50 overlap ─> MiniLM embeddings ─> Chroma (cosine)
```

### `ResumeIndexer` API

| Method | Returns | Notes |
|---|---|---|
| `index_resume(file_path)` | `dict` | Validates, parses, splits by section, indexes, extracts a profile record |
| `index_projects(projects_list)` | `dict` | Entries may be strings or dicts (`name`, `description`, `technologies`, `role`, `impact`, `url`) |
| `index_achievements(text)` | `dict` | One document per bullet or line |
| `search_skills(query, top_k=5)` | `List[SearchResult]` | Filtered to `skills`/`projects`/`summary` |
| `search_experience(query, top_k=5)` | `List[SearchResult]` | Filtered to `experience`/`projects`/`achievements`/`summary` |
| `search_by_technology(tech, top_k=5)` | `List[SearchResult]` | Semantic search + literal mention filter |
| `search(query, ...)` | `List[SearchResult]` | Generic; takes `content_types`, `sections`, `technology` |
| `get_full_context()` | `str` | Whole index rendered for an LLM prompt |
| `get_profile()` | `ResumeProfile` | Name, email, phone, years, skills |
| `stats()` / `count()` / `is_empty()` | `dict` / `int` / `bool` | Introspection |
| `clear_index()` | `None` | Drops and recreates the collection |

### Chunk metadata

Every chunk carries `source`, `chunk_id`, `type`, `section`, `chunk_index`,
`document_id`, `indexed_at`, plus `project_name`/`technologies`/`skills`/`name`
where relevant. Chroma rejects `None` and list values, so `_clean_metadata()`
drops nulls and joins lists into comma-separated strings.

- `type` ∈ `resume`, `project`, `achievement`, `profile`
- `section` ∈ `summary`, `skills`, `experience`, `education`, `projects`, `achievements`, `other`

### Scores

The collection is created with `hnsw:space = cosine`. Chroma returns a
*distance*, so `_to_similarity()` converts it to `1 - distance`, clamped to
`[0, 1]`, where 1.0 is a perfect match.

---

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/` | App metadata and links |
| GET | `/health` | Liveness probe → `HealthResponse` |
| POST | `/api/career/upload-resume` | Multipart upload **and** index → `{status, message, file_size}` (201) |
| POST | `/api/career/analyze-job` | `{job_description}` → the full `JobAnalyzerAgent.analyze()` dict |
| POST | `/api/career/full-analysis` | JSON **or** multipart → `FullAnalysisResponse`: verdict, all five analysis sections, trace, timing |
| GET | `/api/career/analysis/{analysis_id}/trace` | Replays one run: `{nodes: [{name, status, duration_ms, output_summary}], total_duration_ms, status}` |
| GET | `/api/career/status` | `{resume_indexed, status, chunks}` |
| POST | `/api/career/clear` | Empties the index → `{status, message, chunks_removed}` |
| POST | `/api/career/resume-insights` | JSON, multipart **or an empty body** → `ResumeInsightsResponse`. No advert involved |
| POST | `/api/career/chat` | `{message, history[]}` → `ChatResponse`. **200 even with no resume**, with `resume_available: false` |
| POST | `/api/career/interview-prep` | `{job_description?, resume_text?}` → `InterviewPrepResponse`. The advert is optional |
| POST | `/api/career/practice-answer` | `{question, answer, skill?}` → `PracticeAnswerResponse`. **Needs no indexed resume.** `score` is `null` when no model is configured |

### The resume-first endpoints

These three exist because the product had no answer to "I have a CV and no
particular job in mind". Everything before them needed an advert.

`POST /api/career/resume-insights` reads the resume alone. `experience_years` is
`Optional[float]` and is **null when the CV does not state a duration** — it is
never estimated and never coerced to zero, because a 0 on screen is a claim the
candidate then has to argue with. On the LLM path the model's claimed skills are
intersected with `find_skills()` over the actual text: a fabricated skill is
worse than a missing one, since the candidate has to answer for it in the room.

`POST /api/career/chat` returns **200 with `resume_available: false`** rather
than a 409 when nothing is indexed. A chat box that refuses to open cannot tell
the user *why* it refused. Every reply carries `source`: `"llm"` means a model
wrote it, `"fallback"` means a rule matched and answered from extracted facts,
and when no rule matches the fallback says so instead of improvising.

`POST /api/career/interview-prep` takes an optional advert. With one, it runs
`job_analyzer_agent.analyze()` as before. **Without one it synthesises a job
analysis from the CV's own skills**, because `prepare_interview` builds technical
questions from the advert ∩ resume overlap and an empty advert makes that
intersection empty — the endpoint returned `question_count: 0`. `tailored_to_job`
stays `false` so the UI can say the questions are generic rather than imply a
target role that was never supplied.

`POST /api/career/discover-jobs` gained `auto_from_resume`. When set, the search
phrases come from `ResumeProfilerAgent`, capped at `MAX_AUTO_QUERIES = 3`, and
the response carries `queries_used` and `derived_from_resume`. The `limit` is
split **across** the queries, not applied to each — asking for 20 returns 20.
A 409 means no resume; a **422** means the resume is indexed but names too few
technologies to infer a role from, which is a different problem with a different
fix.

### The two new endpoints

`POST /api/career/full-analysis` is the whole product in one call. It accepts
**either** `application/json` (`{job_description, resume_text?}`) **or**
`multipart/form-data` (`job_description` field + `resume_file`). Supporting both
is deliberate: a file upload *requires* multipart, but forcing every caller who
already has a resume indexed to build a multipart body just to send one string
is hostile. The resume is resolved in preference order — **uploaded file →
`resume_text` in the body → whatever is already indexed** — and a 409 is returned
only when all three are absent.

`GET /api/career/analysis/{analysis_id}/trace` replays a finished run for the
UI's pipeline diagram. The store behind it (`_ANALYSIS_HISTORY`) has two
constraints written into it:

- **It is bounded** (`ANALYSIS_HISTORY_LIMIT = 50`, oldest evicted first). Ids are
  minted on every request, so an unbounded dict is a memory-exhaustion vector
  that any anonymous caller can pull on.
- **It holds no personal data** — node name, status, duration, one summary line.
  Not the advert, not the resume, not the suggestions. It is an unauthenticated
  in-process cache; anyone who guesses an id can read it, so there must be
  nothing worth reading.

`FullAnalysisResponse` deliberately has **no top-level `confidence`**. Two
numbers could claim that name — the match calculator's 0–100 score and the
pipeline's 0–1 agreement figure — and publishing one under a bare label invites
exactly the units mix-up that had to be fixed *inside* the pipeline last prompt.
Callers who want it can read `analysis.match_breakdown`.

`calculate-match` is **additive**. It now runs the full seven-node pipeline
instead of the four-node graph, but the original five keys keep their names,
their meanings and their scales — `confidence` is still the match calculator's
0–100 figure, not a fraction. Existing callers see no change.

Upload rules: extension allow-list (`.pdf .txt .md`), 10 MB cap enforced while
streaming, stored as `<uuid><ext>` so the client filename never touches the path.
`/api/career/upload-resume` additionally rejects a file with no extractable text
(422) rather than reporting success on an empty index, and deletes the stored
file when indexing fails.

### Status codes

| Code | When |
|---|---|
| 400 | Bad extension, empty file, malformed JSON body, or a pipeline that failed outright |
| 404 | `analysis/{id}/trace` for an id that is unknown or has been evicted |
| 409 | A match/analysis request with no resume uploaded, supplied or indexed |
| 413 | Upload over the size cap |
| 422 | Body failed validation, advert empty or over 50 000 chars, or the document yielded no text |
| 500 | Indexing or workflow failure — logged in full, generic in the response |

The advert checks return **422, not 400 or 413**, because that is what the
`JobDescriptionRequest` model would have returned. `full-analysis` and the new
`calculate-match` read the body by hand to support multipart, which bypasses
FastAPI's automatic validation — so `_validate_job_description` reproduces
pydantic's status codes on purpose. Two endpoints answering the same mistake
with different codes costs an integrator an afternoon.

### Request logging

An HTTP middleware logs one line per request:
`[a1b2c3d4] POST /api/career/analyze-job -> 200 in 12.4ms`, at WARNING for 4xx/5xx.
The same id is returned as the `X-Request-ID` header so a user-reported failure
can be found in the log. **Bodies are never logged** — they carry resumes.

Analysis runs log more: the request (advert length and where the resume came
from, never the text), the verdict and score, every node's duration and summary,
any adjustment the pipeline made to the raw verdict, and any node that failed.

One caveat on the brief's "log user feedback (APPLY/SKIP decisions)": what is
logged is the **system's** recommendation. Real user feedback — whether they
actually applied — would need the user to tell us, and no endpoint collects that
yet. Calling the current line "user feedback" would make the logs lie.

### Blocking work

Parsing, embedding and the graph run are synchronous CPU work. Every endpoint
pushes them through `run_in_threadpool`, so one long request cannot stall the
event loop for everyone else.

### Try it

```bash
uvicorn main:app --reload

curl -X POST localhost:8000/api/career/upload-resume -F 'file=@resume.pdf'
curl -X POST localhost:8000/api/career/analyze-job \
     -H 'Content-Type: application/json' -d '{"job_description":"Senior Python engineer, 5+ years, FastAPI, Docker."}'

# whole pipeline, resume already indexed
curl -X POST localhost:8000/api/career/full-analysis \
     -H 'Content-Type: application/json' -d '{"job_description":"Senior Python engineer, 5+ years, FastAPI, Docker."}'

# whole pipeline, resume attached in the same call
curl -X POST localhost:8000/api/career/full-analysis \
     -F 'job_description=Senior Python engineer, 5+ years, FastAPI, Docker.' \
     -F 'file=@resume.pdf'

curl localhost:8000/api/career/analysis/6faaa41df263/trace
curl localhost:8000/api/career/status
curl -X POST localhost:8000/api/career/clear
```

---

## Agent orchestration

### The graph

```
      resume_text + job_description
                  │
                  ▼
          ┌───────────────┐
          │  analyze_job  │  posting → skills, stack, years, seniority,
          └───────┬───────┘             role type, education, confidence
                  ▼
          ┌───────────────┐
          │extract_skills │  resume → skills the candidate evidences
          └───────┬───────┘
                  ▼
          ┌───────────────┐
          │  detect_gaps  │  required − found
          └───────┬───────┘
                  ▼
          ┌───────────────┐
          │calculate_match│  → 0–100 score + recommendations
          └───────┬───────┘
                  ▼
          ┌───────────────┐
          │optimize_resume│  → tailored rewrites, keywords, reordering
          └───────┬───────┘
                  ▼
          ┌───────────────┐
          │prepare_interview│ → questions, answer scaffolds, prep plan
          └───────┬───────┘
                  ▼
                 END
```

Linear on purpose: every node consumes the previous node's output.

### Four-tier LLM strategy

| Tier | When | Where |
|---|---|---|
| 1. Ollama (local) | Daemon answers `GET /api/tags` | `OllamaHandler` |
| 2. Gemini (REST) | Ollama down, `GEMINI_API_KEY` set | `GeminiHandler` |
| 3. Claude API | `ANTHROPIC_API_KEY` set, `anthropic` installed | `ClaudeHandler` |
| 4. Deterministic | None available, or the reply is unusable | `BaseAgent.fallback()` |

Gemini is tried before Claude because it has a free tier and needs no extra
package. `LLMClient` walks the tiers in order. **The last tier means the
workflow always completes** — no Ollama, no key and no network still produces a
full analysis, which is exactly how the test suite runs.

### Modules

| File | Contents |
|---|---|
| `agents/__init__.py` | `AgentConfig` (validated dataclass), `LLMProvider` enum, `default_agent_config()` |
| `agents/ollama_handler.py` | `OllamaHandler`, `ClaudeHandler`, `LLMClient`, prompt templates, `parse_json_response` |
| `agents/base_agent.py` | `BaseAgent`, `AgentResult`, the skills/gaps/match agents, `build_tools()` |
| `agents/job_analyzer.py` | `JobAnalyzerAgent` (node 1), the standalone extractors, and the older keyword `JobAnalyzer` |
| `agents/match_calculator.py` | `MatchCalculator` (node 4), `ComponentScore`, `_EvidenceFinder`, the resume year/education extractors |
| `agents/gap_detector.py` | `GapDetectorAgent`, `SKILL_FAMILIES`, `BASE_LEARNING_DAYS` — enriches node 3 with costed, prioritised study plans |
| `agents/resume_optimizer.py` | `ResumeOptimizerAgent` (node 5), `WEAK_VERBS`, `PLACEHOLDERS`, `_COMMODITY_SKILLS` — copy-pasteable rewrites that never invent a fact |
| `agents/interview_prep.py` | `InterviewPrepAgent` (node 6), `QUESTION_BANK`, `BEHAVIOURAL_BANK`, `ANSWER_PLACEHOLDERS` — likely questions, answer scaffolds, day-by-day plan |
| `agents/complete_workflow.py` | `CompleteWorkflow`, `NODE_SEQUENCE` (7), `summarise_trace`, `_as_fraction` — runs every agent, adds RAG-backed extraction and the final APPLY/MAYBE/SKIP with reasons |
| `agents/workflow_state.py` | `WorkflowState` / `StateDict`, `StepTimer`, trace helpers |
| `agents/graph_builder.py` | `WorkflowGraph`: build → compile → `execute(state)` |

### State

```python
class WorkflowState(TypedDict, total=False):
    resume_text: str
    job_description: str
    skills_found: List[str]
    gaps_identified: List[str]
    match_score: float
    all_analysis: Dict[str, Any]
    execution_trace: Annotated[List[Dict[str, Any]], _append]   # reducer!
```

`execution_trace` carries an **append reducer**. Without it LangGraph would
overwrite the key each time a node returned it, and only the last node's entry
would survive. Every other key overwrites, which is why `merge_analysis()`
copies `all_analysis` forward by hand.

### Execution trace

One entry per node, appended by the `WorkflowGraph._node` wrapper:

```json
{
  "step": 1,
  "node": "analyze_job",
  "status": "completed",
  "duration_ms": 38.38,
  "timestamp": "2026-08-31T04:51:14.717591+00:00",
  "detail": "Senior Backend Engineer [backend, senior]: 4 required skill(s) via fallback",
  "label": "Job Analyzer",
  "skills_extracted": 4,
  "confidence": 0.57
}
```

`status` is `completed`, `skipped` (input missing — not an error) or `error`. A
node that raises is recorded and the run continues, so a partial answer is
returned instead of a stack trace.

A node may add its own columns by returning a `_trace` dict; `_node` pops it and
merges it into the entry. `analyze_job` uses this for the human-readable
`label`, the `skills_extracted` count and the `confidence` score.
`calculate_match` uses it for its verdict:

```json
{
  "step": 4,
  "node": "calculate_match",
  "status": "completed",
  "duration_ms": 1.79,
  "detail": "score 92.0/100 -> APPLY",
  "label": "Match Calculator",
  "overall_score": 92.0,
  "recommendation": "APPLY"
}
```

Nodes that return no `_trace` keep the plain shape, so the trace stays narrow by
default.

`optimize_resume` runs last because its advice depends on both earlier results —
the gaps tell it which skills it must *not* suggest claiming, and the score
tells it which are worth leading with:

```json
{
  "step": 5,
  "node": "optimize_resume",
  "status": "completed",
  "duration_ms": 8.8,
  "detail": "12 suggestion(s), 5 high impact",
  "label": "Resume Optimizer",
  "improvements": 12,
  "high_impact": 5,
  "confidence": 0.95
}
```

`prepare_interview` closes the run:

```json
{
  "step": 6,
  "node": "prepare_interview",
  "status": "completed",
  "duration_ms": 5.8,
  "detail": "12 question(s), 5 day(s) of prep, 30% predicted",
  "label": "Interview Prep Agent",
  "questions_generated": 12,
  "prep_days": 5,
  "success_prediction": 0.3,
  "difficulty": "HARD"
}
```

### Usage

```python
from agents.graph_builder import WorkflowGraph
from agents.workflow_state import trace_summary

final = WorkflowGraph().execute(resume_text=cv, job_description=jd)

final["match_score"]        # 68.75
final["gaps_identified"]    # ['aws']
trace_summary(final)        # ['analyze_job (completed, 38.4ms)', ...]
```

### Job analysis output

`JobAnalyzerAgent.analyze(job_description)` returns:

| Key | Type | Notes |
|---|---|---|
| `required_skills` | `list[str]` | Hard skills, lowercase, deduplicated |
| `tech_stack` | `list[str]` | `required_skills` minus concepts (RAG, agile, system design…) — the nameable tools only |
| `experience_years` | `int` | `0` when unstated |
| `experience_level` | `str` | `junior`/`mid`/`senior`/`lead`, derived from years, falling back to seniority wording |
| `soft_skills` | `list[str]` | Communication, leadership, mentoring… |
| `education` | `str` | e.g. `bachelors (or equivalent experience)`, `not required`, `not specified` |
| `role_type` | `str` | `backend`, `frontend`, `fullstack`, `ai/ml`, `data`, `devops`, `mobile`, `security`, `qa`, `general` |
| `seniority` | `str` | Wording found in the advert |
| `confidence` | `float` | 0.0–1.0, see below |
| `company_size` | `str` | `startup`/`scaleup`/`enterprise`/`unknown` |
| `preferred_skills`, `responsibilities`, `title`, `source` | | Extras carried through for later nodes |

The first eight keys are the requested contract; the rest are additions the
matching step already needed.

`extract_requirements()` returns the six-key subset and can be called with no
argument — it reuses the last description passed to `analyze()`.

**Confidence** is a weighted count of how much was actually found, multiplied by
a source factor (`llm` 1.0, `fallback` 0.85):

| Signal | Weight |
|---|---|
| required skills (scaled, full marks at 5+) | 0.30 |
| experience years | 0.15 |
| seniority | 0.15 |
| role type (not `general`) | 0.15 |
| tech stack | 0.10 |
| education | 0.10 |
| soft skills | 0.05 |

So it measures evidence, not self-belief: a thorough keyword pass can and does
outscore a thin LLM reply.

**Errors:** `EmptyJobDescriptionError` (blank/non-string) and
`MalformedJobDescriptionError` (under 20 characters, or under 50% letters — a
binary paste). Both subclass `JobAnalysisError` → `AgentError`. An LLM timeout is
*not* an error: it degrades to the keyword path and sets `warning` on the output.

### Match scoring

`MatchCalculator.calculate_match(resume_data, job_analysis, retriever=None)`
returns the score. **No model is ever asked for the number** — the arithmetic is
pure Python, so the same inputs always give the same score and every point is
traceable to a rule.

| Component | Weight | Question it answers |
|---|---|---|
| `skills` | 40% | How many required skills does the resume evidence? |
| `tech_stack` | 25% | How many of the named tools does it evidence? |
| `experience` | 15% | Years held vs years asked for |
| `soft_skills` | 10% | Communication, leadership, mentoring… |
| `education` | 10% | Is the degree requirement met? |

Each component returns the same shape:

```json
{
  "score": 80.0,
  "found": ["docker", "fastapi", "langchain", "python"],
  "missing": ["rag"],
  "weight": 0.4,
  "applicable": true,
  "evidence": {"python": "Skills: Python, FastAPI, Docker, K8s, LangChain"},
  "matches": [{"required": "python", "matched": "Python", "exact": true, "why": "exact"}]
}
```

The overall shape is the requested `overall_match` / `match_breakdown` /
`recommendation` / `confidence`, plus `matched_skills`, `missing_skills`,
`recommendations` and `job_title` which the graph and `MatchResult` already
consumed.

**Renormalisation.** A component the advert never mentions is marked
`applicable: false` and its weight is removed from the denominator rather than
being scored 100. An advert that says nothing about education should not hand
out a free 10%, and it should not penalise the candidate either. If nothing at
all is assessable the score is `0.0` with low `confidence` — see the design
decisions below.

**Recommendation:** `>= 85` APPLY, `65–85` MAYBE, `< 65` SKIP.

**Confidence** is reported separately from the score and answers "how much did
we have to work with?": `coverage * 0.5 + depth * 0.25 + job_factor * 0.25`,
where coverage is the share of weight actually assessed, depth is how much
evidence was retrieved, and `job_factor` is the analyzer's own confidence. A 90%
match computed from a two-line advert is not the same claim as a 90% match from
a detailed one.

**Fuzzy matching** lives in `utils/skills.py` and is deliberately conservative,
because crediting a skill the candidate does not have is worse than missing one:

| Rule | Example | Result |
|---|---|---|
| Curated alias | `K8s` → `kubernetes` | exact, 1.0 |
| Punctuation only | `next.js` ≈ `next js` | 0.97 |
| Prefix | `react` ≈ `reactjs` | 0.9 |
| Typo (SequenceMatcher ≥ 0.88) | `kubernets` ≈ `kubernetes` | 0.95 |
| Names under 5 characters | `go`, `r`, `ml` | never fuzzy — alias table only |
| `_NEVER_MATCH` pairs | `java`/`javascript`, `c`/`c++`, `aws`/`azure` | 0.0 |

`_NEVER_MATCH` exists because the pairs that score highest on string similarity
are exactly the ones that are most damaging to confuse. `match_skill()` scans
the whole candidate list and returns the *strongest* match, not the first.

**Evidence.** Every credited skill is quoted back from the resume. If a
`ResumeIndexer` is passed it is asked first (`search_by_technology`, one vector
query per unique skill, cached); otherwise the resume text is scanned. The
scanner is alias-aware, so "built a retrieval augmented generation assistant"
counts as evidence of `rag` even though the acronym never appears. A retriever
that raises is caught and the text path is used — evidence is a nice-to-have,
not a dependency.

---

## Key design decisions

- **Lazy ML imports.** `chromadb` and `sentence-transformers` are imported inside
  methods, so the API boots and tests run without the heavy stack installed.
  `ResumeIndexer()` construction never loads torch.
- **Injectable embedder.** Anything with `encode(texts) -> vectors` can be passed
  to `ResumeIndexer(embedder=...)`. Tests inject a hashing embedder, so the suite
  is fully offline and runs in ~2.3 s.
- **`persist=False`** swaps `PersistentClient` for `EphemeralClient`, giving tests
  a real Chroma instance with no disk I/O.
- **Section-aware chunking.** Text is split by resume heading *before* chunking,
  so `search_skills` and `search_experience` can filter by section.
- **Filter fallback.** Resumes with no recognisable headings land entirely in
  `other`, which would make a section-filtered search return nothing. `search()`
  retries unfiltered when a filtered query comes back empty (`fallback_to_all`).
- **Chroma telemetry disabled** via `ChromaSettings(anonymized_telemetry=False)`.
  It ships usage data off the machine, and 0.4.24 logs an ERROR on every call
  against modern posthog.
- **Singletons.** `settings`, `resume_indexer`, `job_analyzer`, `match_calculator`
  are module-level instances; tests monkeypatch attributes on them.
- **Scoring weights.** Skills 40%, tech stack 25%, experience 15%, soft skills
  10%, education 10% — set by the prompt. *(Superseded the earlier required
  0.75 / preferred 0.25 split in Prompt 7.)*
- **Upload safety.** `Path(filename).name` strips directory components;
  the stored name is a UUID, so a hostile filename cannot escape `UPLOAD_DIR`.
- **Every agent has a deterministic fallback.** An LLM makes answers richer; it is
  never required. That keeps the whole pipeline runnable offline and keeps the
  test suite honest.
- **Scoring never asks a model.** `MatchScoringAgent` has `prompt_name = None`.
  A score has to be reproducible, and a model would return a different number
  each run for the same inputs.
- **Cached availability probe.** `OllamaHandler.is_available()` caches its answer
  and `WorkflowGraph` shares one `LLMClient` across all four agents, so a dead
  daemon costs one short timeout per run rather than one per node.
- **The model cannot contradict the evidence.** `GapAnalysisAgent.parse()` drops
  any "gap" for a skill the candidate demonstrably has, and `JobAnalyzerAgent`
  never lets a skill be both required and preferred.
- **An empty LLM skill list is treated as a formatting slip**, not as a resume
  with zero skills, so it falls through to the keyword extractor.
- **API keys never reach the logs.** `claude_api_key` is `repr=False` and
  `describe()` reports only a boolean.
- **`JobAnalyzerAgent` lives in `job_analyzer.py`, not `base_agent.py`.** It needs
  the extractors in that module, and `base_agent` used to import from it — a
  cycle. The dependency now runs one way (`job_analyzer` → `base_agent`);
  `build_tools()` imports the agent lazily inside the function to keep it that way.
- **The LLM fills the form; the text fills the blanks.** Any field the model omits
  or fails to validate is recovered from the raw advert rather than left empty, so
  a partially useful reply is still used.
- **Seniority is the earliest level mentioned, not the first pattern matched.**
  A posting names its own level up front and others in passing, so
  "Senior Engineer… you will mentor junior engineers" reads as senior.
- **Role type is scored, not first-match.** Every category accumulates keyword
  hits and the highest total wins; near-equal frontend and backend scores mean
  fullstack. First-match made any advert that said "React" a frontend role.
- **Experience ranges take the lower bound.** "3–5 years" is a request for 3;
  quoting 5 would understate the candidate's fit. Across separate figures the
  maximum wins, since "7 years overall, 2 with Kubernetes" has a bar of 7.
- **`tech_stack` is not a copy of `required_skills`.** Concepts (RAG, agile,
  system design) are filtered out, leaving the named tools a stack list implies.
- **One scoring engine, not two.** The legacy `calculate(resume_id, resume_text,
  analysis) -> MatchResult` signature still exists for the API layer, but it now
  delegates to `calculate_match()`. Two implementations of "how good is this
  match" would drift apart within a week.
- **Components the advert never mentions are renormalised away, not scored 100.**
  Scoring an unmentioned requirement full marks inflates every vague posting;
  scoring it zero punishes the candidate for the employer's omission. Removing
  the weight is the only honest option.
- **A job with nothing assessable scores 0, not 100.** The old code returned a
  perfect score for an empty requirement list. Telling someone to APPLY on the
  basis of no information is the worst possible failure mode; `confidence`
  carries the "we cannot tell" signal instead.
- **Over-qualification is not a bonus.** 10 years against a 5-year bar scores
  100, not 200-capped-to-100. Shortfall is proportional with a 20-point floor,
  since 2 years against 5 is a real candidate, not a zero.
- **Fuzzy matching is conservative by design.** A false positive tells someone
  they are qualified when they are not, which is worse than a missed match they
  can see and correct. Hence the 5-character minimum, the 0.88 threshold and the
  explicit `_NEVER_MATCH` list.
- **Score and confidence are separate numbers.** Collapsing them into one figure
  hides whether a low score means "poor fit" or "thin advert".
- **Known correlation: `skills` and `tech_stack` overlap.** `tech_stack` is
  derived as a subset of `required_skills`, so the two components move together
  and hard skills carry closer to 65% of the weight in practice than the nominal
  40%. This follows the requested weighting faithfully; noting it here rather
  than quietly re-deriving `tech_stack` from a different source.
- **`/api/career/full-analysis` runs the graph, not the agents directly.**
  The graph already calls the analyzer and the scorer in order; calling them
  again alongside it would double the work and allow the two answers to differ.
- **The index is reached through a FastAPI dependency, not an import.**
  `get_indexer()` is overridable, so the API tests run against an in-memory
  Chroma with an offline embedder instead of the real singleton.
- **The graph is built once and cached**, with the live indexer injected as its
  retriever. Constructing it per request would rebuild four agents and re-probe
  Ollama every time.
- **Blocking work is pushed to a threadpool.** Embedding a resume takes seconds;
  doing it on the event loop would freeze every other request.
- **A resume that yields no text is a 422, not a success.** Scanned PDFs parse
  cleanly and produce nothing, and reporting `"status": "success"` would leave
  the user with an empty index and no explanation.
- **The upload path is written once.** `_store_upload()` is shared by both upload
  routes so the extension allow-list, the size cap and the filename sanitising
  cannot drift apart between them.
- **`status` never raises.** If Chroma is unreachable the endpoint reports
  `"degraded"` with a 200. A health probe that 500s tells you nothing that the
  timeout had not already.

---

## Commands

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

uvicorn main:app --reload     # run
pytest                        # test
pytest -v tests/test_main.py  # one file
python test_week1.py          # smoke check: real objects, real config
python test_week1.py -v       # ...plus the app's own log output
python run_test.py            # full pipeline on the sample data
python run_test.py cv.txt jd.txt   # ...on your own files

python test_complete_workflow.py              # the demo: all 7 nodes, saved to results.txt
python test_complete_workflow.py cv.txt jd.txt
python test_complete_workflow.py --no-emoji   # ASCII markers for a plain terminal
python test_complete_workflow.py --verbose    # ...plus the pipeline's own logs
python test_api.py            # start a server, test every endpoint, shut it down
python test_api.py --url http://localhost:8000   # ...against a running server
```

### Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000
npm run dev -- -p 5173        # if 3000 is taken; CORS allows this port too
npm run build                 # production build + TypeScript check
npm run lint                  # eslint
npx shadcn@latest add <name>  # note: shadcn, not shadcn-ui
```

`.env.local` holds one variable, `NEXT_PUBLIC_API_URL`, defaulting to
`http://localhost:8000`. The backend must be running separately; the frontend
is a display for it and holds no data of its own.

Only two origins reach the API: the ports named in `CORS_ORIGINS` in
`config.py`. Serving the frontend from any other port produces a browser CORS
error rather than a silent failure, which is the intended behaviour.

### `test_week1.py` vs `tests/`

They verify different things and neither replaces the other.

| | `tests/` | `test_week1.py` |
|---|---|---|
| Embedder / LLM / store | Stubbed | Real |
| Speed | ~3.6 s, offline | ~1 s |
| Catches | Logic regressions | Bad imports, missing deps, renamed settings, dead routes |
| Collected by bare `pytest` | Yes | No — `testpaths = tests` |

Mocking is what makes the suite fast, and also what lets an import error or a
renamed setting slip through. The smoke script builds the real `Settings`, a real
Chroma collection, the real agents and the real ASGI app, then reports. It exits
`1` on any failure, so it works unchanged in CI.

Its five `test_*` functions are plain and argument-free, so `pytest test_week1.py`
also works if you want it inside a pytest run.

Sample inputs live in [backend/samples/](backend/samples/) — a full AI Engineer
advert and a resume that is a *deliberately imperfect* match. It scores **80.5 →
MAYBE**, missing Kubernetes and a named vector DB. A sample that scored 100 would
pass even if the scoring logic were broken.

Optional — enable the local LLM tier (the app works without it):

```bash
ollama serve                  # start the daemon on :11434
ollama pull mistral           # ~4 GB
```

---

## Configuration

Everything is read by `config.Settings`. Values are resolved in this order, each
beating the one below it: **constructor argument → environment variable →
`backend/.env` → default in `config.py`**. Copy the annotated template to start:

```bash
cp backend/.env.example backend/.env
```

| Variable | Default | Meaning |
|---|---|---|
| `DEBUG` | `true` | Enables uvicorn auto-reload |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address |
| `API_PREFIX` | `/api/v1` | Legacy route prefix |
| `CORS_ORIGINS` | localhost 3000/5173 | JSON array — see below |
| `UPLOAD_DIR` | `./data/uploads` | Saved uploads |
| `CHROMA_DB_PATH` | `./data/chroma` | Vector store |
| `LOG_DIR` | `./data/logs` | Rotating log files |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | 384-dim, CPU, no API key |
| `CHROMA_COLLECTION_NAME` | `resumes` | Collection name |
| `CHROMA_DISTANCE` | `cosine` | Distance metric |
| `LLM_PROVIDER` | `ollama` | `ollama`, `claude`, `gemini` or `auto` |
| `LLM_MODEL` | `mistral` | Ollama model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama daemon |
| `LLM_TEMPERATURE` | `0.2` | 0.0–2.0 |
| `LLM_MAX_TOKENS` | `2048` | Generation cap |
| `LLM_TIMEOUT_SECONDS` | `120` | Per-generation timeout |
| `LLM_HEALTHCHECK_TIMEOUT` | `2.0` | Availability probe — short on purpose |
| `LLM_MAX_RETRIES` | `2` | Retries per backend |
| `LLM_FALLBACK_ENABLED` | `true` | Allow the Claude tier |
| `ANTHROPIC_API_KEY` | unset | Also read from the environment |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Fallback model |
| `GEMINI_API_KEY` | unset | Also read as `GOOGLE_API_KEY` from the environment |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Free tier is per-model, per-day |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `250` / `50` | Resume chunking |
| `TOP_K_RESULTS` | `5` | Search results returned |
| `MAX_UPLOAD_SIZE_MB` | `10` | Upload cap |
| `ALLOWED_EXTENSIONS` | pdf/docx/txt/md | JSON array; dots optional |
| `LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL` |
| `LOG_FORMAT` / `LOG_DATE_FORMAT` | see `config.py` | `logging.Formatter` strings |
| `LOG_TO_FILE` | `true` | `false` = console only |
| `LOG_FILE_NAME` | `app.log` | Inside `LOG_DIR` |
| `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` | `5 MB` / `3` | Rotation |

### Validation happens at import

`LLM_PROVIDER` and `LOG_LEVEL` are checked against an allow-list and normalised
for case. A typo fails the process on boot with a message naming the variable,
rather than surfacing as a confusing error deep inside a request:

```
LLM_PROVIDER
  Value error, LLM_PROVIDER must be one of ('ollama', 'claude', 'gemini', 'auto'), got 'openai'
```

`ALLOWED_EXTENSIONS` is lower-cased and given leading dots, so `PDF` and `.pdf`
both work.

### Paths resolve against `backend/`, not the cwd

`UPLOAD_DIR`, `CHROMA_DB_PATH` and `LOG_DIR` accept relative values and resolve
them against `BASE_DIR`. `CHROMA_DB_PATH=./data/chroma` therefore means the same
directory whether uvicorn is launched from `backend/`, the repo root, or `/`.
Without this, launching from a different folder silently creates a second, empty
vector store.

### `OLLAMA_BASE_URL` and the old name

The setting was previously `LLM_BASE_URL`. The field is now `OLLAMA_BASE_URL`
with `AliasChoices("OLLAMA_BASE_URL", "LLM_BASE_URL")`, so existing `.env` files
keep working; the new name wins if both are set. `settings.LLM_BASE_URL` remains
as a read-only property.

### `CORS_ORIGINS` must be JSON

pydantic-settings parses `list`/`set` fields from the environment as JSON before
any validator runs, so a comma-separated string raises. Use
`CORS_ORIGINS=["http://localhost:3000"]`.

### Secrets

Never commit the API key. `.env` is gitignored; `.env.example` is not and must
never hold a real key. `AgentConfig` marks the key `repr=False` and omits it from
`describe()`, and `Settings.summary()` reports only `claude_key_set: true|false`,
so it cannot reach the logs.

```bash
python config.py    # prints the resolved settings summary, secrets redacted
```

A test asserts `.env.example` documents exactly `Settings.model_fields` — adding
a setting without documenting it fails the suite.

---

## Frontend layout

```
frontend/
├── app/
│   ├── layout.tsx              Server Component: fonts, metadata, ThemeProvider
│   ├── globals.css             Tailwind v4 entry + project utilities
│   └── (dashboard)/
│       ├── layout.tsx          Sidebar + Header + Footer shell
│       ├── page.tsx            "/" — resume-first home; upload box until one
│       │                       is indexed, then a profile card + the 4 steps
│       ├── my-resume/          wired to POST /api/career/resume-insights
│       ├── analyze/            upload-resume + full-analysis + trace
│       ├── discover-jobs/      POST /api/career/discover-jobs; the first
│       │                       search runs itself with auto_from_resume,
│       │                       location=india, max_age_days=2
│       ├── interview-prep/     wired to POST /api/career/interview-prep
│       ├── assistant/          wired to POST /api/career/chat, with an
│       │                       optional pasted advert as job context
│       ├── my-jobs/            wired to GET  /api/career/my-jobs
│       ├── my-applications/    wired to GET  /api/career/my-applications
│       │                       and GET /api/career/analytics for the stat cards
│       ├── my-applications/[id]/  history + update-status
│       └── settings/           wired to /career/status, upload-resume,
│                           clear, and /api/health/full
├── components/
│   ├── ui/                     shadcn: button card input textarea dialog
│   │                           select badge progress
│   ├── layout/                 Header, Sidebar, Footer
│   ├── dashboard/StatCard.tsx  renders null as a caption, 0 as a figure
│   ├── dashboard/JobCard.tsx   backend bucket thresholds; null score ≠ 0%
│   ├── dashboard/JobDetailModal.tsx  runs POST /api/career/full-analysis
│   ├── dashboard/AnalysisResults.tsx  score, breakdown, gaps, rewrites, prep
│   ├── dashboard/AgentTraceViewer.tsx nine-node timeline with per-node detail
│   ├── dashboard/ApplicationTimeline.tsx  status history, from → to
│   ├── providers/ThemeProvider.tsx   the only 'use client' boundary at the root
│   └── shared/LoadingSpinner.tsx, ErrorMessage.tsx, SourceBadge.tsx
├── hooks/useDarkMode.ts        useSyncExternalStore hydration guard
├── lib/api.ts                  axios, baseURL ${API_URL}/api
├── lib/utils.ts                cn()
├── types/index.ts              mirrored from real responses, not the design
├── __tests__/api-errors.test.ts   describeApiError, all five shapes
├── __tests__/health.test.ts       getHealth: 503-with-report vs 503-without
├── vitest.config.mts           node env, no jsdom; @ alias
├── .env.example                committed template (see the `!` in .gitignore)
└── package.json                engines node >=20.9.0; lint via bare eslint
```

20 component files, 5,248 lines across `app/ components/ lib/ hooks/ types/`.
Every module exports named bindings only — the 13 redundant `export default`
lines were removed in prompt 41, so there is exactly one way to import each
component.

Two rules the layer follows:

**Nullable rates stay nullable all the way to the pixel.** `RateText` in
`types/index.ts` is `string | null`, `StatCard` distinguishes missing from zero,
`JobCard` renders `Not scored` when `match_to_user` is null, `AnalysisResults`
renders `Not counted` for a match dimension with `applicable: false` rather than
the 0 or 100 the backend happens to put in `score`, `/my-applications` takes its
interview rate from the API rather than dividing in the browser, and no display
path uses `|| 0` or `?? 0` on a rate or a score. Anything added here must keep
that property; it is the one invariant the frontend can break silently.

**Rates arrive pre-formatted.** `_pct()` in `agents/application_analytics.py`
returns `Optional[str]` — `"100%"`, or `None`. `interview_rate`, `offer_rate`
and the two `*_confidence_95` fields are strings, so they are rendered verbatim.
Numeric methods on them throw, which is exactly what the dashboard used to do.

**The two rates have different denominators.** `interview_rate` is
`_pct(interviews, applied)`; `offer_rate` is `_pct(offers, interviews)`. Every
place either is displayed says which, because the alternative is a single
"success rate" whose meaning changes depending on which card you are looking at.

**Charts are not exempt.** `/analytics` draws nothing at all when
`total_applications` is 0 — an axis with a zero-height bar reads as a measured
zero. Zero-count pie slices are filtered out before they reach recharts, and
applications with a null `match_score` get a labelled `Not scored` bar rather
than being dropped from the distribution or bucketed into the bottom band.

**Types are transcribed from responses, not from the design.** They were
written by calling each endpoint and reading what came back — hence
`current_status` rather than `status`, `sent` rather than `applied`,
`match_to_user.score` rather than a bare number on the job, `match_score` on a
saved job but `match_to_user` on a discovered one, `analysis.gaps` being an
object rather than an array, and `match_breakdown[dim].missing` being a string
array on some dimensions and a plain string on others.

**Classification thresholds are copied from the backend, not invented.**
`JobCard` hard-codes 80 / 60 / 40 with a comment naming `agents/job_enricher.py`
as the source. The filter buttons on `/discover-jobs` use the backend's own
`categorized.counts`, so the UI can never disagree with the data it filters.

---

## Test coverage map

| File | Covers |
|---|---|
| `tests/conftest.py` | Temp-dir isolation, offline `HashingEmbedder`, in-memory `indexer` fixture, sample resume/job |
| `tests/test_config.py` | Defaults, MB→bytes, idempotent dir creation, env override, settings cache, provider/log-level allow-lists, extension normalisation, cwd-independent path resolution, `OLLAMA_BASE_URL` alias, `.env` precedence, `.env.example` completeness, secret redaction |
| `test_week1.py` | Not unit tests — an end-to-end smoke check against the *real* config, Chroma, agents and ASGI app |
| `run_test.py` | Not unit tests — drives real data through index → analyse → score and prints a formatted report |
| `test_complete_workflow.py` | Not unit tests — the demo script; runs all seven nodes and writes `results.txt` |
| `conftest.py` (root) | Not tests — excludes the root-level scripts from collection so `pytest .` does not abort on a duplicate basename |
| `test_api.py` | Not unit tests — the only test that uses a real socket; catches wiring the `TestClient` cannot |
| `tests/test_gap_detector.py` | Learning-time discounts, gap grading, prioritisation, learning paths, quick wins |
| `tests/test_resume_optimizer.py` | Fabrication guards, gap-keyword guards, project parsing, impact grading, reordering |
| `tests/test_interview_prep.py` | Answer-scaffold honesty, gap coaching in both directions, prediction bounds, plan realism |
| `tests/test_complete_workflow.py` | Node-failure containment, verdict accountability, confidence scales, advice coherence, LangGraph-free fallback |
| `tests/test_job_analyzer.py` | Keyword analyzer (skills, seniority, required/preferred split, responsibilities) **and** `JobAnalyzerAgent`: years/education/role/company-size extraction, validation errors, confidence weighting, LLM vs fallback paths, `extract_requirements`, trace fields |
| `tests/test_match_calculator.py` | Output contract, per-component scoring, fuzzy matching, resume year/education extraction, renormalisation, recommendation tiers, confidence, evidence + retriever, edge cases, legacy `calculate()` |
| `tests/test_resume_indexer.py` | Pure helpers: chunking, PDF/text extraction, heading detection, profile parsing, bullets, where-clause building, similarity conversion |
| `tests/test_indexer_store.py` | Full `ResumeIndexer` against real in-memory Chroma: indexing, metadata, search filters, fallback, context rendering, clear, stats |
| `tests/test_skills.py` | Vocabulary, word-boundary matching, aliases, `tech_stack` filtering, soft-skill matching, `normalise_skill` / `skill_similarity` / `match_skill` including the never-match pairs |
| `tests/test_main.py` | Meta routes, CORS, resume upload (success, rejection, size limit, path traversal, case-insensitive extension, empty and text-free files), `analyze-job`, `full-analysis` (JSON and multipart bodies, resume precedence, section content, short and unreadable input, validation parity), `analysis/{id}/trace` (shape, 404, bounded store, eviction order, no personal data, path-traversal id), `status` including the degraded branch, `clear`, request logging, and 404s for the three endpoints removed in the audit |
| `tests/test_agent_config.py` | `AgentConfig` validation and bounds, `from_settings`, env-var key, `copy_with`, secret redaction, `LLMProvider.parse` |
| `tests/test_ollama_handler.py` | Prompt rendering, JSON extraction (fences/prose/malformed), availability probe + caching, Claude fallback, `LLMClient` routing, retries |
| `tests/test_base_agent.py` | LLM path vs fallback path for the skills/gaps/match agents, input validation, tool building, normalisation helpers |
| `tests/test_graph_builder.py` | State helpers and the append reducer, `StepTimer`, graph structure, end-to-end execution, node order, trace contents and per-node columns, skipped/failed nodes |
| `tests/test_job_hunt_pipeline.py` | Stage tracing, a dead job board not losing the run, `run_job_hunt`, shortlisting on score, unscored (`-1.0`) vs genuinely zero, drafts only on request and out of the rate denominators, two users saving the same advert, recorded reasoning |
| `tests/test_week2_complete.py` | **Seams only.** The seven-agent workflow end to end, linear and branching agreeing on the score, an agent exception reaching HTTP as a 422 with no leaked text, a cache hit not breaking the follow-up `extract_requirements()`, clearing the index reaching the caches |
| `tests/test_week2_api.py` | One user walked through discover → save → apply → progress → analytics in order, plus `/api/health/performance` and cache clearing, which nothing else covered |
| `tests/test_resume_profiler.py` | Role inference (both halves of the stack → fullstack, one shared keyword → not a career), seniority bands, skill grouping, phone detection across seven international formats, unstated years staying `None`, and the LLM path having its claimed skills intersected with the real text |
| `tests/test_career_chat.py` | Intent classification, history trimming, every scripted reply admitting it is scripted, a question it cannot answer being declined rather than improvised, unstated years being refused rather than estimated, an empty model reply falling back rather than rendering blank |
| `tests/test_insight_endpoints.py` | The three new endpoints plus auto-discovery, over a `StubIndexer` so no test loads the ML stack: null years serialising as `null`, no-resume chat being a self-explaining 200, auto-discovery with no resume being a 409, and the limit covering all queries together rather than each one |

---

## Prompt log

### Prompt 70 — 2026-09-11

Does it run on someone else's laptop, from a zip. The only way to answer that
is to stop reading the project and actually be that person, so the zip was
unpacked into `/tmp` and installed from nothing on ports 8011 and 3200.

It runs. `pip install` on Python 3.9.6 succeeded, `npm install` added 717
packages with **0 vulnerabilities**, `next build` produced all **13 routes**
with TypeScript clean, and all 11 pages served 200 from the production build.
The fresh copy created its own `data/`, both SQLite databases and the Chroma
store on first boot, and reported `accounts: 0` — proof that no personal data
travelled with it. Signup returned 201 on the empty database, login 200, and
the session held: no cookie 401, forged cookie 401, and after logout 401,
which means sessions are revoked server-side rather than merely forgotten by
the browser.

**The README was wrong three times, and every one of them would have landed on
the recipient.**

*It promised "Python 3.9 or newer".* PyPI disagrees: `numpy==1.26.4` publishes
no 3.13 wheel. Since 3.13 is what a new machine installs today, the most
likely first experience was pip trying to compile numpy from source and dying
in a wall of C errors that look like a broken project rather than a version
mismatch. Now stated as 3.9–3.12, with that failure described so it is
recognisable.

*The zip command leaked four files and a directory.* `*/data/*.db` does not
match `users.db-wal`, so the WAL and SHM sidecars went along, and
`backend/data/logs/` was never excluded at all — 15 MB containing 895 user-id
occurrences and 47 CV filenames. No emails, tokens or API keys were in them,
but that is luck, not design. Fixed with `*/data/*.db-*` and `*/data/logs/*`,
and a verification command so the fix can be checked rather than believed.

*The sizes were stale* — `.next` measured 566 MB against a claimed 333 MB, and
the whole tree 2.2 GB against 1.8 GB.

One thing the clean-room run exposed that no amount of reading would have:
the first health check on a brand-new install reports `unhealthy`, because
`all-MiniLM-L6-v2` is fetched on first use and the probe times out while it
downloads. It is ~90 MB, it needs a network even if you planned to run
entirely offline behind Ollama, and it settles by itself — healthy 25 seconds
after startup once cached. That is now in the README, because an unexplained
`unhealthy` on a first run reads as a broken project.

Gates unchanged: 2517 backend tests, 60/60 e2e with the window still `7` and
ages `[0,1,2,2,3,4,6,7]`, 11 frontend tests, ruff at exactly the 5 intentional
findings. The corrected zip is **953 KB across 203 files**, and an audit for
`.env`, `.db`, `chroma`, `uploads` and `logs` matches only the two
`.env.example` files, which is the point of them.

### Prompt 69 — 2026-09-11

A closing sweep: is everything done, is every changed file in scope, and does
testing throw anything. Two defects found, both by looking rather than by
grepping.

**`test_week1.py` still claimed a reply it never got.** The health probe was
fixed in Prompt 67; the smoke script had the same bug and went unnoticed
because nobody reads a line that says `[ OK ]`:

```
[ OK ]  LLM tier ready: 'gemini' answered in 0 ms
```

`available_backend()` returns `"gemini"` off a configured key without sending
anything, so *answered* was false — and `0 ms` was the tell, sitting in the
output the whole time. `_KEY_ONLY_BACKENDS` became public `KEY_ONLY_BACKENDS`
so both callers share one definition rather than drifting, and the line now
reads `LLM tier configured: 'gemini' key present (checked in 0 ms, no request
sent)` with a note that a key is not a reply.

**The sidebar linked to something that no longer exists.** Its footer read
`Week 3 • Frontend Ready` — an internal milestone meaningless to anyone using
the app — above a link labelled **Backend status** pointing at `/settings`,
where the status card had been *removed in Prompt 67*. Not merely jargon: a
promise the destination no longer keeps. Settings is already in the nav above
it, so the whole block went.

It survived the earlier sweep because that sweep read `main`. This sat in
`aside`, on every dashboard page. Catching it needed a walk of the DOM outside
the content area — the same lesson as the footer, one level further out.

The same walk flagged `node.js`, `LLM frameworks like LangChain` and
`Python Backend Developer` and those were **left alone**: the first two are the
user's own CV read back to them and the third is an employer's advert title.
Rewriting either would be editing someone's data to satisfy a style rule.

**Scope.** Twenty files carry today's timestamp; four (`utils/auth.py`,
`interview-prep/page.tsx`, `(dashboard)/layout.tsx`,
`my-applications/[id]/page.tsx`) were last touched between 00:04 and 11:58,
before this work began, and are untouched by it. Everything after 17:00 is
this session. No `.orig`, `.rej`, `.bak` or scratch files anywhere.

Gates: **2517 passed**, `test_week1.py` **6/6**, ruff **exactly the 5
intentional `ARG` findings**, ruff over tests clean, `tsc` and `eslint` silent,
11 frontend tests, `next build` 13 routes with no warnings, end-to-end
**60 passed, 0 failed**, and 11 routes served 200 with **zero console errors on
any page**. Live window: ages `[0, 1, 2, 2, 3, 4, 6, 7]`, 0 undated. Data:
1 account, 3 sessions, **0 orphans**, 1 job, 2 applications, 2 collections, no
test-shaped accounts.

Two decisions are still open and are the user's to make, not mine: the CV and
applications owned by the retired `local` id, and no rate limiting on
`/api/auth/login`.

### Prompt 68 — 2026-09-11

"Where else can we get jobs from — but first make sure every source actually
provides the posting date, the India location and a direct application URL."

The right order, and it changed the answer. Eleven candidates were probed live.
Six were rejected, and the one rejection that costs something is the one worth
recording.

**SmartRecruiters is refused, and it hurt.** It is keyless, it is well-formed,
and it returns exactly the three fields the filter needs — Swiggy alone had
**73 India vacancies, 30 of them posted inside a week**, with `releasedDate`,
`location.country = "in"` and an `applyUrl` on every one. Then its robots.txt:

```
User-agent: LinkedInBot
Allow: /v1/companies/
User-agent: *
Disallow: /
```

One named crawler admitted and everybody else turned away. That is a decision,
not an oversight. The `CREDENTIALLED_API_HOSTS` exemption does not reach it —
that exemption exists for a host we hold an issued key for, and we hold
nothing here. Taking it anyway would be the "ignore robots.txt when
convenient" behaviour the module's own docstring says it exists to avoid.
It is recorded in `CLOSED_JOB_BOARDS` with the cost stated, so the next person
tempted by it reads the reason rather than rediscovering the temptation.

The other rejections, all on evidence rather than principle:

| Candidate | Why not |
| --- | --- |
| The Muse | Sample advert dated 10 months back, and a `location=Bangalore, India` query returned "Flexible / Remote" and "New York, NY". Fails both the date and the location test. |
| RemoteOK | Permitted, dated, `location: "India"`, apply URL present — and only **2** India roles, aged 25 and 38 days. Contributes nothing to a 7-day search. |
| Jobicy | **0** India roles in 100. |
| Himalayas, WorkingNomads | 0 India roles. |
| Workable, Recruitee | Every Indian slug tried was 404 or empty. |
| Careerjet, Jooble, Jobdataapi | Alive, but key-gated. Careerjet answered `403: "add a Referer header so we know who is calling"`, so it is a real option once an affiliate ID is requested. |

**Added: three boards, on ATS already supported.** HighRadius (59 India roles,
5 inside a week), Airbnb (8, 1 inside a week), Clarisights (2). Verified
through the real code path, not the probe: 251 adverts fetched, 69 surviving
the India filter, and **all 69 carried a posting date, an `http` URL and a
description over 50 characters**.

Two boards that passed the field test were still left out, on cost. Zscaler
publishes **372 vacancies in a 4.7 MB response and exactly one is in India** —
the whole payload is paid for on every cache miss. Airbnb's 2.3 MB for eight
was judged worth it; Zscaler's was not. The reasoning sits above
`INDIA_BOARDS` so the omission does not read as an oversight.

**The probe was wrong before the code was.** A first pass reported Zscaler as
"372 roles" on a naive `"india" in location.lower()`, which matches
`Remote - Indiana, USA`. The application does not have that bug — `_filter_jobs`
uses `(?<!\w)india(?!\w)` and carries a city alias table, so it rejects Indiana
and still finds `Bengaluru Office`, and `TestIndiaAliases` has pinned both for
some time. Worth stating plainly: the throwaway script was less careful than
the thing it was checking, and believing it would have added a 4.7 MB request
for one job.

Two tests added (2515 → **2517**): the closed-board set now includes
SmartRecruiters, a test asserts its reason names robots.txt, LinkedInBot and
the missing credential so the distinction from the merely-unavailable boards
cannot be edited away, and a duplicate-slug guard.

Gates: **2517 passed**, ruff **exactly the 5 intentional `ARG` findings**,
ruff over tests clean, end-to-end **60 passed, 0 failed**. The backend was
restarted, since it runs without `--reload`. Live discovery now returns 20
adverts inside the window where it returned 8, ages
`[0, 0, 1, 2, 2, 3, 4, 4, 5, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7]`, 0 undated.
Files changed: `backend/agents/job_scraper.py`,
`backend/tests/test_job_scraper.py`. Nothing else.

### Prompt 67 — 2026-09-11

A final-cleanup pass with three questions: is every change actually mine and
related, is "jobs from the last 7 days" real, and does the app feel right to
somebody opening it for the first time. **One real defect, in the one file
nobody had run.**

#### The 7-day rule holds, and the ceiling is enforced, not just requested

`grep` found the promise in four places, but a promise in source is not a
promise kept, so it was measured against the live API:

| Request | `max_age_days_used` | Ages returned | Undated |
| --- | --- | --- | --- |
| `max_age_days: 7` | 7 | 0,1,1,1,1,1,2,2,2,3,4,4,4,5,6,6,6,6,6,7 | 0 |
| `max_age_days: 365` | **7** | oldest 7 | 0 |

The second row is the interesting one. `_apply_freshness` clamps with
`window = min(requested, _MAX_WINDOW_DAYS)` and `_MAX_WINDOW_DAYS = 7`, so a
caller asking for a year gets a week and is told why: *"This list covers the
last 7 days. Older adverts are not shown, because they are usually filled by the
time you apply."* `fresh_jobs` drops undated adverts entirely — measured as 0,
not assumed.

`README_DEV` still described the old `_FRESHNESS_LADDER = (7, 30)` in the
present tense, several hundred lines below the entry that removed it. The symbol
no longer exists anywhere in the codebase. Marked **Superseded** rather than
deleted: the paragraph still explains why `freshness_note` exists.

#### The defect: `test_week1.py` had rotted against two features

`backend/test_week1.py` is the only check that wires up the *real* config,
embedder and app rather than the mocks in `tests/`. Nothing in the session had
run it. It exited **1**, on two assertions that were correct when written and
had quietly gone stale:

| Assertion | Why it failed |
| --- | --- |
| `settings.LLM_PROVIDER in ("ollama", "claude", "auto")` | A hand-copied list that never learned about Gemini — the configured provider |
| `/api/career/status == 200` | Written before accounts existed. The route is now behind auth, so **401 is the correct answer** |

The first is now read from `config.LLM_PROVIDERS`, the single source of truth,
so it cannot drift again. The second asserts `401` — a *stronger* check than the
original, because it fails if the route ever loses its auth guard.

A third problem was reporting, not pass/fail: `check_llm_connection` probed
Ollama regardless of the configured provider, so it printed *"Ollama not
reachable… agents fall back to keyword matching"* while check 3 on the same run
was visibly analysing an advert `via 'llm'` through Gemini. A reassuring message
that was false. It now asks `LLMClient.available_backend()` — the router that
respects the provider — and reports `LLM tier ready: 'gemini'`.

Result: **6/6, exit 0**, and the LLM line now matches what the agents do.

#### First-run experience, walked as a new account

Signed up as a brand-new user and visited every page with an empty account. The
409s in the browser console are by design, not breakage: the backend answers
"no resume indexed" with 409, and `page.tsx` separates that from a real outage
(`noResume` vs `brokenBackend`) to pick the friendly empty state.

| Page | What a new user sees |
| --- | --- |
| `/` | "Start with your resume", upload dropzone |
| `/discover-jobs` | States the 7-day rule in plain words before any search |
| `/my-jobs` | "Nothing saved yet." → *Find some adverts* |
| `/my-applications` | Counts read `0` — honestly, they are zero — but **Interview rate reads "Nothing sent yet"**, not `0%` or `NaN` |
| `/interview-prep` | "There is no resume to build questions from yet." → *Upload your CV* |
| `/assistant` | The model declines: *"I cannot summarize your resume because you have not uploaded it yet"*, labelled AI-written |

Every empty state offers a way out, and `/settings` was confirmed to carry a
real upload control, so the link `/interview-prep` sends there is not a dead end.

#### The whole journey, run as a new account

`/tmp/cp_e2e.py` walks signup → upload → discover → save → apply → advance →
history → analyse → prep → assistant → analytics → isolation → cleanup against
the live stack: **59 of 60**.

The first run reported six failures. All six were the harness, not the app, and
the pattern is worth recording because it has now happened three sessions
running: **every field name I guessed was wrong, and every one I read from
`career_models.py` was right.**

| Asserted | Actual |
| --- | --- |
| upload `200` | `201 Created` — correct for something that creates a resource |
| `chunks_created` | No such field; `status` / `message` / `file_size`, and `/status` reports `chunks=8` |
| `events` / `history` | **`timeline`** — `created` → `application_sent` |
| item `.application_id` | Items key off **`app_id`** |
| `questions` | Split across five buckets; 21 questions with `questions` holding 1 |
| top-level `confidence` | Nested under `prediction.current_stats` |

The sixtieth check failed for a different reason: the assistant answered from
the deterministic path, not the model. The log gives the cause —
`Gemini rate limit reached (429); free tier is per-minute` — because the script
fires a burst of LLM calls with no pause. The app retried three times, fell
back, and **labelled the answer `fallback` rather than `llm`**, which is the
designed behaviour working. The same question one run earlier, under quota,
came back `source: llm` naming Python and FastAPI from the CV.

#### The defect: "No questions could be built", above 21 questions

`InterviewPrepResponse.questions` is the technical and gap-based list. The other
four buckets — behavioural, HR, scenario, project — are separate. A short advert
that names no technology yields an empty `questions` while the other four stay
full. The study tab then rendered:

- a card headed **"0 questions"**, and
- the sentence *"No questions could be built. That happens when the CV names no
  technology to ask about."*

directly above 21 questions that had in fact been built and were on screen.
Measured, not hypothesised: `{questions: 0, behavioral: 6, hr: 6, scenario: 4,
project: 1}`.

The same class of defect as the gap count fixed in Prompt 64 — a headline number
contradicting the content beneath it. The count is now labelled
**"N technical questions"**, and the empty notice says which kind could not be
built and points at the rounds that could:

```tsx
const otherRoundsBuilt = Boolean(
  result &&
    (result.behavioral_questions.length > 0 ||
      result.hr_questions.length > 0 ||
      result.scenario_questions.length > 0 ||
      result.project_questions.length > 0),
);
```

`PracticeRoom` was checked at the same time and already handled the empty list
with *"There are no questions to practise yet."* — no dead end there.

#### The `llm healthy` chip was a false all-clear

Raised by the screenshot of Settings → Backend: `llm healthy optional 0ms`.
The zero was the tell. `check_llm` called `llm_client.is_available()`, and for
the two hosted backends that reads a configured key and makes no network call:

| Backend | `is_available` | Real probe? |
| --- | --- | --- |
| `gemini` | `return self.config.has_gemini_credentials` | no |
| `claude` | key set *and* `import anthropic` succeeds | no |
| `ollama` | calls the daemon on `LLM_HEALTHCHECK_TIMEOUT` (2.0s) | yes |

So the chip sat green through this entire session while Gemini answered `429`
— `Gemini rate limit reached (429); free tier is per-minute` — on every single
request, and the assistant quietly served deterministic answers instead. The
one e2e assertion that failed, `the answer is grounded in the CV`, failed for
exactly that reason. A panel whose job is to tell you whether the backend is
answering was reporting that it was, off a string in a `.env` file.

That is the same defect as “Gaps identified: 0” for an application nobody had
analysed, and it contradicts the footer on every page: *blanks mean the data
was not there, not that the value was zero.*

The status stays `healthy` and stays `optional` — the fallback path genuinely
works, and reporting `degraded` for a key that may well be fine would be the
opposite error. What changed is that the probe now names the backend it found
and qualifies the ones it could not actually reach:

```
"llm", "healthy", provider "gemini", backend "gemini",
note: "A gemini key is configured. This is not a live call, so requests can
       still be refused - free tiers limit them per minute."
```

`_KEY_ONLY_BACKENDS = frozenset({"gemini", "claude"})` is the whole mechanism;
Ollama is deliberately absent because its probe is real and needs no caveat.
No frontend change was needed — `settings/page.tsx` already renders
`service.note` under each row, which is how the `rag` probe says *“Reachable,
but nothing is indexed yet.”* `/api/health/full` has no `response_model`, so
the new `backend` field passes through untouched.

One existing test broke, correctly: it stubbed `client.is_available` to prove
the probe never sends a prompt, and the probe now asks `available_backend()`.
The intent was preserved and the hook moved, plus three new tests — key-only
backends carry the note, Ollama does not, and no backend at all is `degraded`
with `required: False`.

Still untouched, and still true: the probe must not send a real prompt. That
would run against `LLM_TIMEOUT_SECONDS` (120) on an unauthenticated `GET`, and
cost money per call on a hosted model.

#### Then: would Amazon show you this?

Renaming the rows was still the wrong answer, and the next question said so:
*“consider if we go amazon website soo will there be an endpoint in UI??”* No.
No shopping site shows you its database latency. A working app does not report
on itself; it just works. The whole card is gone.

What replaces it is nothing at all while everything is fine. Health is still
fetched, and surfaces as one plain sentence only when something is actually
broken:

| Condition | What the person sees |
| --- | --- |
| healthy | nothing |
| unreachable | Cannot reach the server right now. Nothing you have saved is lost. |
| `unhealthy` | Part of the app is not working, so some pages may fail to load. |
| `degraded` | The AI assistant is unavailable, so its answers will be simpler than usual. Everything else works normally. |

`degraded` earns a sentence because the assistant quietly answers from rules
instead of the model, and someone who is not told that will blame the weaker
answer on themselves.

The note added to `check_llm` above is still worth having even though nothing
renders it today — `/api/health/full` is what a person debugging this app
reads, and a green `llm` there meant nothing.

#### The same leak, everywhere else

Removing one panel and leaving the rest would have missed the point, so the
whole app was swept for strings a job-seeker would not understand. Comments
were excluded — only what actually renders.

The worst of it was not in Settings at all: **a book icon in the header, on
every single page, linking to `http://localhost:8000/docs`.** FastAPI's
Swagger UI, one click from someone looking for a job.

| Where | Was | Now |
| --- | --- | --- |
| Header (every page) | book icon → `localhost:8000/docs` | removed |
| Header badge tooltip | Running against a backend on this machine. | Everything runs on this computer. Your resume is not sent anywhere else. |
| Settings | `Indexed` / `Nothing indexed` | `Saved` / `Not uploaded yet` |
| Settings | 24 chunks searchable. Every analysis reads from these. | Your resume is saved. Every job match and interview question is built from it. |
| Settings | Clear index | Remove resume |
| Settings | parsed and embedded by the backend | read on the computer running this app |
| Settings | salted PBKDF2 hash … revokes the session | never stored in a readable form … ends the session everywhere |
| Settings | no change-password endpoint … SQLite file next to the backend | not built yet, said in one sentence |
| Analyse | Index holds 24 chunks. | Your resume is saved and will be used for this analysis. |
| Analyse | the nine-node workflow scores it against your indexed resume | it is scored against your resume, step by step |
| Analyse | Running the workflow… | Analysing… |
| Analyse | a real measurement of an empty index | reflects having no resume saved |
| Analyse | Short adverts give the extractor less to work with | A short advert gives less to work with |
| Assistant / Find jobs | No resume is indexed | You have not uploaded a resume yet |
| Find jobs | scored against the resume you have indexed | matched against your resume |
| Find jobs | Check that one is indexed on the Settings page | Check your resume is uploaded on the Settings page |
| Job card | No resume indexed | No resume uploaded |
| Source badge | Written by a language model. | Written by AI. |
| Source badge | Add an `ANTHROPIC_API_KEY` to `backend/.env` | removed — and stale anyway, the provider is Gemini |
| Analysis / job modal | No language model was reachable | The AI was not available |
| Trace card | Agent execution trace | How this was worked out |
| Trace card | raw node names (`job_analyzer`) under each step | removed; the human label was always there |
| Trace card | 9 nodes · 412ms in agent work · … end to end | 9 steps · 412ms of work · … in total |
| Trace card | Failed: `gap_detector`, `resume_tailor`. | Some steps did not finish… |
| Job modal | Running every agent over this advert… | Working through this advert… |
| Footer (every page) | runs locally against your own backend … come from the API | runs on your own computer … the information was not available |
| Analyse | Nine agents are running. | Working through the advert. |
| Analyse | Results and the full agent trace appear here. | Your result, and how it was reached, appear here. |

The last three were caught only by re-reading the rendered text of all nine
pages in a browser after the edits, not by searching the source. The first
sweep's pattern looked for `/api/` and missed `the API`, and did not look for
`backend` at all. Grep finds what you thought of; reading the page finds what
is there.

Two things were deliberately **not** softened. The `SourceBadge` still
distinguishes AI-written text from rule-built text, and the analysis still says
when it fell back — that distinction is the one thing the app must never blur,
and plain words make it clearer, not weaker. And “Not scored” still refuses to
become 0%.

The execution timeline survived the sweep because it is the substance of the
project, not decoration. It just stopped narrating itself in the vocabulary of
the graph that produced it.

A subagent surveying the codebase reported “21 chunks” rendering on the
discover page and `step.node` as a user-facing label. The first was inside a
`/* */` comment and the second was already falling back to a human `label`.
Both were checked against the file before being touched. Reading beats
believing the report — which is the same lesson as every false alarm in this
log.

`get_errors` also reported a clean file immediately after an edit that had left
a dangling `) : null}` in the JSX. The stale answer was caught by `tsc`, not by
the editor. Gates decide; the inline diagnostics are a hint.

#### Change hygiene

Session edits, by mtime: `frontend/app/globals.css`,
`frontend/app/(dashboard)/layout.tsx`,
`frontend/app/(dashboard)/my-applications/[id]/page.tsx`,
`frontend/app/(dashboard)/interview-prep/page.tsx`,
`backend/utils/auth.py`, `backend/test_week1.py`,
`backend/utils/health_check.py`, `backend/tests/test_health_check.py`,
`frontend/app/(dashboard)/settings/page.tsx`,
`frontend/app/(dashboard)/analyze/page.tsx`,
`frontend/app/(dashboard)/assistant/page.tsx`,
`frontend/app/(dashboard)/discover-jobs/page.tsx`,
`frontend/components/layout/Header.tsx`,
`frontend/components/layout/Footer.tsx`,
`frontend/components/shared/SourceBadge.tsx`,
`frontend/components/dashboard/AgentTraceViewer.tsx`,
`frontend/components/dashboard/AnalysisResults.tsx`,
`frontend/components/dashboard/JobCard.tsx`,
`frontend/components/dashboard/JobDetailModal.tsx`, and the
three markdown files.
Nothing else. `next-env.d.ts` and `tsconfig.tsbuildinfo` are regenerated build
artifacts and are gitignored. No `.orig`, `.rej`, `.bak` or scratch scripts
anywhere in the tree — the throwaway probes live in `/tmp`. The frontend's
deleted `AGENTS.md`, `CLAUDE.md`, `README.md` and `app/page.tsx` are the
`create-next-app` scaffold this app replaced.

Gates after the change: **2515 passed** (2512 plus the three new health
tests), `test_week1.py` **6/6**, ruff prod
**exactly the 5 intentional `ARG` findings**, ruff over `tests/` and
`test_week1.py` clean, `tsc` and `eslint` clean, 11 frontend tests, and
`next build` **13 routes** with no warnings. The dev server was restarted
afterwards, because a production build overwrites `.next` and leaves a running
`next dev` serving 404s for every route. The backend runs without `--reload`,
so it was restarted too — otherwise the old probe keeps answering.

Test data created for this pass was removed afterwards: back to 1 account,
2 collections, 1 job, 2 applications, 0 orphan events.

#### Closing verification

Run after every edit above was in place.

| Check | Result |
| --- | --- |
| `pytest` | 2515 passed |
| `test_week1.py` | 6/6, exit 0 |
| ruff prod | exactly the 5 intentional `ARG` findings |
| ruff `tests/` | clean |
| `tsc` / `eslint` | clean |
| frontend tests | 11 passed |
| `next build` | 13 routes, compiled, no warnings |
| **end-to-end journey** | **60 passed, 0 failed** |
| 9 pages walked in a browser | no crash, no console error |
| `/login`, `/signup` | render, no jargon |
| files touched this session | 14 source files, all intended |
| stray `.orig`/`.rej`/`.bak`/scratch | none |
| orphan sessions | 0 |

The end-to-end run is the one that matters: 60/60, where the previous pass got
59/60. The single failure then was *the answer is grounded in the CV*, caused
by Gemini's free tier returning 429 and the assistant correctly falling back to
rules. This time the model answered and the assertion passed on its own terms.
Nothing was changed to make it pass — which is the point of leaving it in.

It also re-proved the 7-day rule live: 8 adverts, ages `[0, 0, 1, 2, 2, 3, 4,
6]`, `max_age_days_used = 7`, zero undated. And the isolation block still
holds: a second account sees none of the first's jobs, applications or resume,
a signed-out request gets 401, and a wrong password gets the same message as an
unknown email.

### Prompt 66 — 2026-09-11

The end-to-end request again. Since the code was byte-identical to the pass that
had just gone green — checked with `find -mmin`, not assumed — repeating the same
sweep would have proved nothing. So this pass went after ground never covered
before: the signup form, a phone-sized screen, and the messages a user actually
reads when something goes wrong. **Two real defects came out of it.**

**1. Error messages written for a log, shown to a user**

`/api/auth/signup` passes `str(exc)` straight through to the form. The exceptions
in `utils/auth.py` were phrased as log lines, so the signup page rendered:

> an account already uses that email

directly beneath a login page that says *"Email or password is wrong."* Same
product, same screen size apart, two different voices. Four messages were
affected — duplicate email, malformed email, password too short, password too
long — and all four now read as sentences.

The two `InvalidCredentialsError` strings were deliberately left lowercase.
Nothing renders them: `main.py` replaces them with a single fixed message so that
login cannot be used to test whether an address is registered. Rewording them
would have implied they reach a screen, and they must not.

Tests assert on exception *types*, not text, so nothing broke — 2512 still pass.

**2. The assistant page broke on a phone**

At 390px, `/assistant` was the only page of nine that scrolled sideways: 377px of
content in a 312px viewport, with the header pushed off the right edge.

The cause is the flexbox default nobody remembers. In
`app/(dashboard)/layout.tsx` the main column is `flex-1`, and a flex item's
`min-width` is `auto`, meaning it will not shrink below its widest unwrappable
child. The assistant's suggestion buttons are `whitespace-nowrap`, so *"How
should I prepare for an interview?"* set a floor the column could not go under.
Every other page happened to have nothing rigid enough to hit it.

One class fixes it — `min-w-0` on that column — and all nine pages now fit with
no horizontal scroll at all.

**Also checked, all clean:** signup with a short password and a malformed email
are both stopped by native validation with a usable message; a duplicate email
returns 409 and renders in the form; a wrong password says *"Email or password is
wrong."* without revealing whether the account exists; a CV uploaded through the
UI produced *"Experience — 7 years"*, correct for 2019–2026; a pasted advert
scored **89.7% → APPLY** across an eight-node trace. Sweep: **75 / 75**.

**A scare, and why it is worth writing down.** Restarting the dev server I ran
`pkill -f "next dev"`, then saw port 3000 answer nothing and assumed I had killed
the user's other project. I had not. That project is **Vite on 5173**, not Next
on 3000 — a `next` pattern could never have matched it, and all nine of its
processes were still running. The note warning about port 3000 was simply stale.
Checking before announcing damage took one command; announcing first would have
cost trust for nothing. Prefer killing by PID or port regardless.

Separately: running `next build` while `next dev` is live overwrites `.next` and
makes the dev server 404 every route. That, not a routing bug, is what five
"missing" pages were in the previous pass.

**Housekeeping.** Three test accounts signed in, `/clear`ed and deleted; the
vector store is back to two collections. Backups `/tmp/users.db.bak6`,
`/tmp/jobs.db.bak6`.

Both long-standing items remain open and still need the owner's word: the
`local`-owned data is unmigrated, and `/api/auth/login` has no rate limiting.

---

### Prompt 65 — 2026-09-11

The same end-to-end request again, run from cold. **No code changed.** Every gate
and every check passed, and the two things that looked like defects were both my
own instruments being wrong — which is the only reason this entry is worth
keeping.

| Gate | Result |
|---|---|
| `pytest` | 2512 passed in 27.0s |
| `ruff` prod / tests | the 5 intentional `ARG` findings / clean |
| `tsc`, `eslint` | clean |
| Frontend tests | 11 passed |
| `next build` | 13 routes |
| Live sweep | **75 / 75** |

Driven through the browser rather than curl this time: uploaded a CV on `/`,
which produced *"Experience — 7 years"* (correct for 2019–2026) under an
**AI-written** label; pasted an advert on `/analyze` and got **89.7% → APPLY**
with an eight-node trace, per-node timings, and *"Experience — Not counted — the
advert did not ask for a number of years"*. The application detail page showed
the prompt-64 fix holding: **Match score: Not scored · Events: 3 · Gaps
identified: Not analysed**.

**Two false alarms, both mine**

*Five pages 404ed.* They were URLs I invented. The real routes are `/`,
`/my-resume`, `/discover-jobs` and `/assistant` — there is no `/dashboard`,
`/upload`, `/discover`, `/chat` or `/analytics`. The route list now lives in the
notes so the next pass reads it instead of guessing.

*Every element measured about 1.3:1 in both themes* — which cannot be true of a
page whose text I had just read. Two separate bugs in my probe:

- `getComputedStyle` returns `lab(92.03 -0.05 2.67)` and `oklch(...)`, not
  `rgb()`. A digit-grabbing regex reads `oklch(0.145 0 0)` as near-black, so
  everything collapses to a ratio of ~1.
- The one survivor, a `Track application` button at 1.22, had
  `background: oklab(... / 0.042)`. Flattening a 4.2%-alpha background to opaque
  white invents a contrast failure that is not on screen.

Screenshots of both themes settled it in seconds. That is now the first resort,
not the last. Three contrast false alarms across three sessions all came from
trusting a computed-style parser over the rendered pixels.

**Housekeeping.** The sweep's two accounts were signed into, `/clear`ed, then
deleted. The vector store went back to exactly two collections, which confirms
what prompt 64 worked out: `/clear` drops the collection, row deletion alone does
not. Backups: `/tmp/users.db.bak5`, `/tmp/jobs.db.bak5`.

Both items from prompt 64 are still open and still waiting on the owner: the
`local`-owned data is unmigrated, and `/api/auth/login` has no rate limiting.

---

### Prompt 64 — 2026-09-10

**"Just check this project end to end and confirm me all working correct if
anything needs to be corrected do it and finish it off make sure i should not
get any bugs or errors"**.

The third end-to-end pass, and the first one run *after* a large styling change,
so the question was really: did the restyle break anything, and is the app
honest everywhere it claims to be.

**Gates**

| Gate | Result |
|---|---|
| `pytest` | **2512 passed** in 27.10s |
| `ruff` (prod scope) | exactly the 5 intentional `ARG` findings |
| `ruff` (tests scope) | All checks passed |
| `tsc --noEmit` | clean |
| `eslint` | clean |
| Frontend tests | 2 files, 11 tests |
| `next build` | **13 routes**, no CSS warnings |

The backend was restarted first so the running process provably matched the code
on disk, and its startup log came back clean.

**The live sweep**

`/tmp/cp_sweep.py` — 75 assertions against the running server, covering all 26
routes from the OpenAPI schema rather than a remembered list. It creates two
accounts and checks the second cannot see the first's anything.

It failed 3 of 75 on the first run. All three were **my test being wrong**, and
worth writing down because two of them looked exactly like real defects:

1. **`create-application` returned 422.** I had guessed a payload of
   `job_title`/`company`/`job_description`. The real model takes `job_id`,
   `analysis_data` and `status`. Guessing a request shape has now caused more
   false alarms in this project than any actual bug.
2. **"Bob's analysis leaked COBOL."** It did contain the word — because *the
   advert I wrote mentions COBOL*. Re-run with terms unique to the other CV and
   never in the advert (`db2`, `jcl`, `cics`, `vsam`, `z/os`, `whitfield`,
   `settlement`, `tape`) every one came back absent. Better still, the place
   COBOL appears is `keyword_density → verdict: "gap"`, with the action
   *"Marked as a gap - learn Cobol before claiming it"*. The pipeline is
   asserting the candidate does **not** have it. That is isolation working, not
   failing.
3. The third was a cascade of the first.

After correcting the test: **75 / 75**.

**The one real defect, and it was a display one**

On the application detail page:

```
Match score        Events        Gaps identified
Not scored           3                0
```

`match_score` correctly refuses to print a number nobody measured. `gaps` printed
`0` — from an empty list that the API returns **both** when the analysis found no
gaps and when no analysis was ever attached. The footer of every page says
*"blanks mean the data was not there, not that the value was zero"*, and this was
the one place that broke its own rule.

There is no flag to distinguish the two, so the fix uses the evidence that is
there: a score is proof something was measured.

```tsx
{application.gaps_identified.length > 0 ||
 typeof application.match_score === 'number' ? (
  <span className="text-2xl">{application.gaps_identified.length}</span>
) : (
  <span className="text-base text-muted-foreground">Not analysed</span>
)}
```

Both branches were then proved in the browser: an application created with no
analysis reads **Not analysed**, and one created with `match_score: 72` and an
empty gap list still reads **0**, because there a zero is a real measurement.

**A colour scare that turned out to be my own fault**

The MAYBE badge measured **1.14:1** in light mode — invisible. Chasing it down:
`-webkit-text-fill-color` was `rgb(234, 232, 227)`, the *dark* theme's
foreground, on an element whose `--foreground` resolved to light ink, with no
stylesheet rule overriding it and no animation running.

The cause was that earlier in the session I had toggled the theme by hand with
`classList.remove('dark')` while `next-themes` also manages that class. On a
clean load the same markup measures **15.79:1**, and re-running a real analysis
in light mode gave 15.79 on the actual badge. No defect — but worth the chase,
because the alternative was "fixing" a colour that was never wrong.

**Also checked**

- Every page walked signed-in: no console errors, no `NaN`, no `undefined`, no
  `[object Object]`, every title rendering.
- The full pipeline driven through the UI: pasted advert → **79%, MAYBE**, with
  *"Experience — Not counted — the advert did not ask for a number of years"*.
- Backend killed, six pages reloaded: all six show *"Could not reach the backend
  at http://localhost:8000. Is it running?"* with a **Try again** button. No
  crash, no invented zero, and no false bounce to `/login`.
- Analytics off a single application reports `interview_rate: "100%"` — but ships
  it with `interview_rate_confidence_95: "21%-100%"`, a `sample_size_warning`,
  `confidence: "low"`, and a null time-to-offer whose basis reads *"any date
  given here would be a guess dressed as a prediction"*.

**Housekeeping**

Eight test accounts were removed. Signing in as each and calling
`POST /api/career/clear` before deleting the rows turned out to matter: **`clear`
deletes the account's Chroma collection**, which plain row deletion does not.

That explained the 12 leftover `resumes_usr_*` collections from earlier sessions,
whose accounts were deleted the wrong way. With `data/chroma` backed up to
`/tmp/chroma.bak`, those 12 were removed through Chroma's own API and the two
that belong to the real account verified intact afterwards — `resumes` at 50
chunks and `resumes_usr_46f5ec2ca3b34bb7` at 24.

Final state: **1 account, 1 session, 2 collections**, both services returning 200.

Backups from this pass: `/tmp/users.db.bak4`, `/tmp/jobs.db.bak4`,
`/tmp/chroma.bak`.

**Still open, still needs the owner's word**

- The CV, 1 saved job and 2 applications under the retired `local` id are still
  unmigrated, so the real account starts empty.
- `/api/auth/login` has no rate limiting. Hashing is deliberately slow; slow is
  not the same as prevented.

---

### Prompt 63 — 2026-09-10

**"now just change the Ui part because color is not good change it and fonts
looks like AI generated too pls remove and maje sure it should look like normal
human created UI and fonts / dont change any logic or code just CSS"**.

A styling prompt with a hard fence around it: **CSS only**. One file changed —
`frontend/app/globals.css`. No `.tsx` was opened for editing, `layout.tsx`
included, so the rendered markup at the end of this prompt is byte-for-byte the
markup at the start of it.

**What actually reads as "AI-generated"**

Worth naming the tells before fixing them, because the brief was a feeling
rather than a list:

| Tell | Where it was |
|---|---|
| Blue→purple gradient clipped into heading text | `.gradient-text`, on the logo **and all ten page titles** |
| Zero-chroma grayscale (`oklch(L 0 0)`) | every neutral in `:root` and `.dark` |
| Stock Tailwind status colours at full saturation | `text-green-600`, `bg-amber-500`, … across the pages |
| `translateY(-2px)` lift plus a 24px shadow on hover | `.card-hover` |
| Frosted-glass panel | `.glass` |
| `0.625rem` radius — the shadcn default, untouched | `--radius` |

None of these are wrong on their own. Together they are the house style of
every generated dashboard, which is exactly the complaint.

**Fonts**

The type stack now leads with the faces already on the machine:

```css
--font-sans:    ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", …
--font-display: Charter, "Bitstream Charter", "Iowan Old Style", Palatino, Georgia, ui-serif, serif;
```

Geist is left in the stack as a fallback — `layout.tsx` still injects it and I
was not allowed to touch that file, so it stays as a harmless last resort
rather than the first choice. The upside is not only aesthetic: a native face
costs no network request, which matters for an app whose promise is that the CV
never leaves the laptop.

Page titles moved to the serif. That needed a base rule, because the sign-in
and sign-up headings do not carry `.gradient-text`:

```css
h1 { font-family: var(--font-display); letter-spacing: -0.005em; }
```

**Colour**

`:root` became warm paper (`oklch(0.982 0.005 91)`) over warm ink, and `.dark`
warm charcoal rather than the neutral gray. The status colours were the harder
half: they are hardcoded in the TSX as `text-green-600` and friends, and I
could not edit the TSX. Tailwind v4 compiles those utilities down to
`var(--color-green-600)`, so a `@theme { }` block overriding roughly forty
shades re-tints every one of them **with no code change at all**. Verified in
the browser rather than assumed: `text-green-600` computes to
`lab(46.8 -31.0 10.1)`, the muted value, not the stock one.

**The contrast pass, and the one real defect it found**

Every foreground/background pair was measured in the page rather than eyeballed:

| Pair (light) | Before | After |
|---|---|---|
| body on paper | — | 16.03 |
| muted on card | — | 5.51 |
| green-600 on paper | — | 4.73 |
| red-600 on paper | — | 5.16 |
| blue-600 on paper | — | 5.25 |
| **amber-600 on paper** | **3.51** | **5.14** |
| **white on amber-500** (the MAYBE badge) | **2.53** | **4.67** |

Amber is the one hue that cannot be both bright and legible, and stock Tailwind
amber under white text fails WCAG AA badly. So the single status a user most
needs to read carefully — *maybe* — was the one status that was hardest to
read. Both shades were pulled down to an ochre that clears 4.5:1.

**A scoping bug I introduced and caught**

The logo treatment was first written as `header .gradient-text`. Every page
wraps its title block in a `<header>`, so the rule landed on all ten page `h1`s
as well and shrank them to 17px. Scoping to `header a .gradient-text` — the
anchor is unique to the real site header — fixed it. Checked by walking all
nine dashboard pages and asserting each `h1` was the serif at full size.

**Checks**

- All nine dashboard pages walked: serif titles, **zero** elements still
  clipping a gradient into text, no console errors on any of them.
- `type-check` ✓ · `lint` ✓ · 11 frontend tests ✓ · `build` ✓ with no
  `@theme` / `oklch` / `color-mix` warnings · **13 routes**, unchanged.
- Both themes screenshotted; light and dark both re-measured for contrast.

**Housekeeping**

The throwaway account used to review the pages (`uilook@example.com`) and its
rows were deleted; `data/users.db` holds one account again. Backups at
`/tmp/users.db.bak3` and `/tmp/jobs.db.bak3`.

One thing found while cleaning and **left alone deliberately**: `data/chroma`
holds 13 `resumes_usr_*` collections but there is only one account. Deleting a
user removes their database rows and leaves their indexed résumé on disk. It is
test debris here, not a live leak — the app has no delete-account feature to
reach it — but if one is ever added, it has to drop the collection too.

---

### Prompt 62 — 2026-09-10

**"Just check this project end to end and confirm me all working correct if
anything needs to be corrected do it and finish it off make sure i should not
get any bugs or errors"**.

The same request as prompt 61 with one clause added — *make sure I should not
get any bugs or errors*. Prompt 61 had already walked everything a user
touches, and all of it passed. So this pass deliberately went after the
opposite: the code paths that had **never been run live**. That is where the
worst find of the whole project was waiting.

#### The worst bug in the project so far: one CV, analysed for everybody

`get_complete_workflow` cached a single `CompleteWorkflow` at module level:

```python
_complete_workflow = None

def get_complete_workflow(indexer=Depends(get_indexer)):
    global _complete_workflow
    if _complete_workflow is None:
        _complete_workflow = CompleteWorkflow(retriever=indexer)
    return _complete_workflow
```

Read that with prompt 60's per-account indexers in mind. The **first** person
to call `/full-analysis` after a restart had their indexer baked into the
cached pipeline. Everyone after them got that same object.

On its own that might have been survivable — most nodes work from the text
they are handed. But `CompleteWorkflow.node_extract_resume` does this
(`complete_workflow.py`, `_from_rag`):

> if a retriever is attached, read the resume out of *it*, in preference to
> the text passed in.

So the retriever won. Every later account's full analysis — their gaps, their
match score, their interview questions, their rewritten bullet points — was
computed **from the first account's CV**, and the resulting report was handed
back to them as their own. That is not a wrong number on a dashboard. That is
one person's résumé leaking into another person's screen.

The fix mirrors the indexer: one pipeline per account.

```python
_user_workflows: "OrderedDict[str, Any]" = OrderedDict()

def get_complete_workflow(
    user_id: str = Depends(current_user_id), indexer=Depends(get_indexer)
):
    with _indexer_lock:
        existing = _user_workflows.get(user_id)
        if existing is None:
            existing = CompleteWorkflow(retriever=indexer)
        return _remember(_user_workflows, user_id, existing)
```

**Why it survived prompt 61.** `/full-analysis` was the one endpoint the
57-check walk never called, because it is the slowest. Everything cheap was
checked; the expensive thing was skipped; the expensive thing was the one that
was broken. Worth remembering as a habit: *the route you skip because it is
slow is the route nobody has ever tested.*

**Why it survived the audit before that.** Same reason as prompt 61's bug, and
this is now a pattern rather than a coincidence. Both bugs lived in a
**dependency**, not a route. Every route signature read
`workflow = Depends(get_complete_workflow)` and looked perfect. The lesson,
written down properly this time: **auditing route signatures proves nothing
about isolation. Grep for module-level singletons that hold per-user state.**

Proved live, with two accounts and deliberately disjoint CVs — Alice a COBOL
mainframe engineer, Bob a React frontend engineer — both analysed against one
advert that mentions both worlds, Alice going first so that under the bug hers
would be the cached retriever:

| Check | Result |
| --- | --- |
| Alice's report is about her mainframe CV | cobol, db2, jcl, mainframe |
| Bob's report is **not** built from Alice's CV | no mainframe terms at all |
| Bob's report is about his frontend CV | figma, react, svelte, storybook |
| Analysis ids differ | pass |
| Alice can replay her own trace | 200 |
| Bob cannot replay Alice's trace | 404 |

#### Two caches that grew forever

`_user_indexers` and the new `_user_workflows` are keyed by account, so
without a bound they gain an entry per person who ever signs in and never lose
one. The project already bounds `_ANALYSIS_HISTORY` and `_DISCOVERED_JOBS` for
exactly this reason, so the inconsistency was the argument. Both are now
`OrderedDict`s behind a shared `_remember` helper, capped at
`ACTIVE_ACCOUNT_LIMIT = 20`, least-recently-**used** first.

Eviction is safe rather than merely tolerable, and that is worth stating: both
caches hold *handles onto durable storage*, not state. Drop one and the next
request rebuilds it against the same Chroma collection. Nothing is lost but
the rebuild — which is exactly the test that was written for it.

#### Sessions that were cleaned up but never swept

`delete_expired_sessions` existed, was tested, and **was never called by
anything**. Not a security hole — `resolve_session` enforces expiry itself, so
an expired token is refused on the very next request whether or not anything
has tidied up. But a session whose owner never returns is never resolved, so
the resolve-time check never fires and the row sits in `users.db` forever.

Now swept once at startup, inside a `try` that logs and continues. Housekeeping
must never be the reason the API will not start, and there is a test that kills
the sweep with a locked database and asserts `/health` still answers 200.

#### The paths that had never been run

| Never exercised before | Result |
| --- | --- |
| `/full-analysis` with two accounts | found the bug above; now passes |
| `/analysis/{id}/trace` as a non-owner | 404, correct |
| PDF upload (only `.txt` had ever been sent) | 201, parsed |
| `/my-applications/[id]` in a browser | renders; status update writes through |
| Every page with the backend **stopped** | five pages, all honest |

The application detail page was the only page never opened. It renders **"Not
scored"** rather than a fabricated 0%, disables *Update* while the status is
unchanged, and appends to the timeline rather than overwriting: driving it
through the real combobox took the application `sent → interview`, the event
count went 2 → 3, and both entries stayed. No console errors.

Killing the backend and reloading five pages produced *"Could not reach the
backend at http://localhost:8000. Is it running?"* with a **Try again** button
on every one — no crash, no `NaN`, no invented zero, and importantly **no
redirect to `/login`**. A network failure must not be dressed up as being
signed out, and it isn't.

#### One thing that looked like a bug and was not

`update-status` with `"interviewing"` returns 400. That is correct — the five
statuses are `draft, sent, interview, rejected, offer`, with `applied` accepted
as an alias for `sent`. The word was wrong in the probe script, not in the API.
The check that mattered was whether the **UI** can ever send a word the backend
refuses, and it cannot: both application pages render their options from
`APPLICATION_STATUSES` in `types/index.ts`, which is exactly those five.

#### Numbers

| Gate | Result |
| --- | --- |
| Backend tests | **2512 passed** (2506 + 6) |
| Ruff, production scope | 5 findings, all intentional |
| Ruff, tests scope | clean |
| `tsc`, `eslint` | clean |
| Frontend tests | 11 passing, 2 files |
| Build | 13 routes |
| Live services | backend 200, frontend 200 |

Throwaway accounts from the walk were removed afterwards; `users.db` holds one
real account and one session. Backups at `/tmp/users.db.bak2` and
`/tmp/jobs.db.bak2`.

#### Still true, and still worth writing down

`/api/auth/login` has no rate limiting. Password verification is deliberately
slow, which makes online brute force expensive, but expensive is not the same
as prevented. The saved job and two applications under the retired `local` id
are still orphaned — migrating them is a permanent edit to a database with no
git behind it, so it stays offered rather than done.

### Prompt 61 — 2026-09-10

**"rerun this project"**, then **"Just check this project end to end and confirm
me all working correct if anything needs to be corrected do it and finish it
off"**.

Both services were restarted (backend :8000, frontend :3100, leaving the
unrelated project on :3000 alone) and then the whole app was exercised against
the running instance rather than against the test suite. That distinction
mattered: the suite was green when this prompt arrived, and the walk still
found a hole in the work done in prompt 60.

#### The one that mattered: discovery was still scoring against a shared index

Prompt 60 gave every account its own Chroma collection and wired `get_indexer`
into every endpoint that touches a resume. It missed one caller.

```python
def _resume_data_or_none() -> Optional[Dict[str, Any]]:
    from rag.resume_indexer import resume_indexer   # the shared singleton
    if resume_indexer.is_empty():
        return None
```

`/discover-jobs` calls this to decide what to score adverts against. The
endpoint had the caller's indexer in hand — it uses it correctly a few lines
earlier for `auto_from_resume` — and then reached past it for the module-level
one. The effect was quiet and bad: signing in as a brand-new account, searching
for jobs, and getting match scores computed against **whatever resume happened
to be in the default collection**. Not a leak of resume text, but a leak of
what the resume implies, on the number the whole product is built around.

It survived prompt 60's review because the audit was done on route signatures.
Every route took `user_id` or `indexer` from a dependency, so the route list
looked clean. This function is not a route.

The fix passes the indexer in, and the docstring now says why rather than
leaving the next person to rediscover it:

```python
def _resume_data_or_none(indexer: Any) -> Optional[Dict[str, Any]]:
    """...
    The indexer is passed in rather than imported. Reaching for the module-level
    ``resume_indexer`` here would score every signed-in user against whatever is
    in the shared default collection instead of their own resume.
    """
```

Three tests were added. Two are direct — the function returns the text of the
indexer it was handed, and returns `None` rather than empty text for an empty
one. The third is the one that would have caught the original bug: it overrides
`get_indexer` with a sentinel object and asserts the sentinel is what arrives.

The first attempt at that third test was itself wrong, and instructively so:

```python
import rag.resume_indexer as indexer_module
monkeypatch.setattr(indexer_module, "resume_indexer", Poisoned())
# AttributeError: ResumeIndexer object has no attribute 'resume_indexer'
```

`rag/__init__.py` re-exports the instance, so `rag.resume_indexer` as an
*attribute* is the indexer, not the module. `test_health_check.py` already had
a comment about this trap. Reading it first would have been quicker.

#### Dead fields that still described the old contract

`SaveJobRequest`, `CreateApplicationRequest` and `UpdateApplicationStatusRequest`
still declared `user_id: str = Field(default="local", ...)`. Nothing read them —
prompt 60 removed every `payload.user_id` — but they were still in the OpenAPI
schema and still on `/docs`, where they look exactly like a field that chooses
the owner. Removed. Pydantic ignores unknown keys by default, so the tests that
send a forged `user_id` and assert it is ignored keep working, which is the
point of those tests.

One test had to change with them. `test_an_overlong_user_id_is_refused_by_validation`
asserted a 422 from the `max_length=64` rule. With the field gone there is
nothing to refuse, so it now asserts the request succeeds and is owned by the
session account — renamed to `test_an_overlong_user_id_in_the_body_is_ignored`
so the name matches the guarantee.

#### Comments that had become false

Four places still told a reader there was no authentication:

| File | Said | Now |
|---|---|---|
| `agents/job_storage.py` | "a *namespace*, not a credential… it stops nothing at all" | a real owner, derived from the session; the module still validates and parameterises because storage should not trust its caller's authorisation |
| `agents/application_tracker.py` | "There is no authentication. Anyone who can reach the API can pass any user id" | same correction |
| `models/career_models.py` | "Spelled out in the response because the API has no authentication" | echoed back so the caller can see which account the server decided it was talking to |
| `frontend/components/layout/Header.tsx` | "there is no login… every request is made as the fixed user id `local`" | rewritten, and the badge's tooltip with it |
| `frontend/app/(dashboard)/settings/page.tsx` | "Stored in this browser only, because there is no account to store it against" | "Stored in this browser, not on your account" |

`utils/health_check.py` also mentions "an endpoint with no authentication in
front of it" — that one was **left alone**, because it is about the health
routes, which really are open on purpose.

#### Sign-out moved to where people look for it

The header docstring explained that a logout button was refused because
"ending a session that was never started would be the one lie in an interface
whose whole point is that it does not invent things." That reasoning inverts
once a session exists: the button is now the honest thing, and hiding it in
Settings is the surprise. The header shows the signed-in name (or email) and a
sign-out control. It renders nothing while the account is still loading, since
a name that appears and then changes reads as a bug.

Verified by clicking it: redirect to `/login?next=%2Fsettings`, and a direct
`fetch('/api/auth/me')` afterwards returns **401** — the session is revoked at
the server, not just dropped in the browser.

#### What the live walk actually covered

A 57-check script driving two real accounts over HTTP against the running
server. Everything passed. The parts worth naming:

- Signed out, `/api/career/status` and `/api/auth/me` are 401.
- Duplicate email → 409. Password under 8 → 422. Malformed email → 400 with
  *"that does not look like an email address"*. Wrong password and unknown
  email both → 401, and the unknown email still pays for a hash.
- Alice uploads a CV → 201, 6 chunks. Bob signs up and `status` reports **no**
  resume — the isolation holding on the live index, not a stub.
- Bob's `/resume-insights` → 409, not a made-up answer built from Alice's CV.
- Discovery: Alice `scored_against_resume: true`, Bob `false`. That pair is the
  regression check for the bug above, run against the real thing.
- `?user_id=<alice>` on Bob's `/my-jobs` → his own empty list. A body `user_id`
  naming Bob, sent by Alice, still saves to Alice.
- Bob updating or reading Alice's application → **404** both times.
- Alice's history keeps every step (2 entries after one status change).
- Analytics: Alice `interview_rate: "0%"` from one real application; Bob
  `interview_rate: null`. Zero as a measurement, absent as absent.
- All five model-backed routes answer (3.6s, 5.0s, 15.3s, 0.0s, 5.4s) and all
  five return 401 to an anonymous caller.
- Clear, sign out, 401, sign back in — and the application is still there.

Then every page in a browser: all 9 dashboard pages render under a freshly
created account, no console errors, no `NaN`/`undefined`/stray `0%`.

#### Numbers

| Gate | Result |
|---|---|
| Backend tests | **2506 passed** (2503 + 3) |
| ruff `F,ARG` production | 5 intentional findings, unchanged |
| ruff `F` tests | clean |
| `tsc --noEmit` / `eslint` | clean |
| Frontend tests | 11 passed |
| Frontend build | 13 routes (12 pages + `_not-found`) |

The page count in the docs was wrong in two places — "eleven-page app" and
"all thirteen of them load" — and is now twelve, checked against the build's
route table rather than against memory.

#### Left alone deliberately

- The `local` rows in `jobs.db` (1 saved job, 2 applications) and the original
  Chroma collection are still orphaned: no account owns that id. Re-pointing
  them at a real account is a permanent, unversioned edit to someone's data,
  so it wants asking rather than assuming.
- Still no change-password, delete-account or password-reset.
- `hashlib.scrypt` is still unavailable on this machine's LibreSSL, so PBKDF2
  at 600k stays.

### Prompt 60 — 2026-09-10

**"i checked entire project its working fine soo now add a login page for that
project"** — clarified to *real* protection, and *multiple* accounts.

Those two answers decided the shape of the work. A login page that only hides
the UI would have been an afternoon; the request was for data that is actually
private, which meant the id had to stop coming from the caller.

#### The thing that was actually wrong

`user_id` was a caller-supplied string defaulting to `"local"`. Two docstrings
said so plainly — *"it namespaces the rows; it does not protect them"*. So
`GET /api/career/my-applications?user_id=someone_else` returned someone else's
applications, and nothing stopped it.

Every data endpoint now takes `user_id: str = Depends(current_user_id)`, which
reads a session cookie. The `user_id` field still exists on some request models
and is **ignored**. Routes that need the check but not the value use
`dependencies=[Depends(current_user)]` on the decorator instead of an unused
argument — which also keeps the ARG lint gate at its 5 intentional findings.

Coverage was verified by walking the app's dependency graph rather than by
reading the file, because reading the file is how you miss one:

```
AUTH  16 routes    OPEN  /health, /api/health/*, /api/auth/{signup,login,logout}
```

#### The resume index was the real hole

Endpoints were the obvious half. The vector store was the half that would have
leaked the most personal thing here: `resume_indexer` was a **single global
Chroma collection** with no `user_id` anywhere in it — 60 matches for
metadata-ish terms, none for `user_id`. With accounts, user B would have been
scored against user A's CV.

Fixed with **one collection per account** rather than a metadata filter. The
reasoning is failure mode, not elegance: a filter has to be remembered at every
read path, and forgetting it once returns another person's resume. A separate
collection means a lookup in the wrong place returns *nothing*. It fails
closed. `ResumeIndexer.__init__` already accepted `collection_name`, so this
cost a user-aware `get_indexer` and no change inside the indexer.

One consequence worth stating: every per-user indexer shares a single
`shared_embedder`. Letting each build its own would have loaded a ~90 MB model
per signed-in account for no behavioural difference.

Confirmed visibly at the end — a newly created account lands on *"Start with
your resume"* rather than seeing the existing `local` CV.

#### Choices, with reasons

| Choice | Why not the alternative |
| --- | --- |
| PBKDF2-HMAC-SHA256, 600k iterations | `hashlib.scrypt` is **unavailable** here — this Python links LibreSSL 2.8.3. Measured 0.180s, at the OWASP floor |
| Iterations stored per row | Raising the count later must not lock out every existing account at once |
| Opaque random tokens, not JWTs | A JWT cannot be revoked before it expires. Signing out has to mean something |
| Only the token's SHA-256 is stored | Stealing `users.db` must not yield usable sessions. Plain SHA-256 is right *here*: the token is 256 random bits, so there is no dictionary to slow down |
| One 401 for every login failure | Different messages confirm which emails are registered |
| Unknown email still pays for a hash | Otherwise the *clock* leaks what the message refuses to |
| No composition rules, 8 char minimum | NIST SP 800-63B. Length, not "must contain a symbol" |
| `secure=not settings.DEBUG` on the cookie | A `Secure` cookie is never sent over `http://localhost`. Hardcoding it would make login appear to succeed and then 401 forever |
| Login schema has **no** `min_length` | A 422 on a short password tells someone guessing which ones are not worth trying |

`hash_password` had `iterations=PBKDF2_ITERATIONS` as a **default argument** —
bound once at import, so the constant could never be changed afterwards.
Now late-bound.

#### Tests

`TestClient(main.app)` is built in six files against the same `app` object, so
an autouse fixture in `conftest.py` overrides `current_user`. `test_auth.py`
removes that override, because the 401 path is its subject.

Nine existing tests failed, all of them **encoding the old contract** — things
like `test_a_bad_user_id_is_a_400`, which only made sense while the caller
chose the id. They were rewritten to assert the new guarantee (the field is
ignored) rather than deleted, and real cross-account isolation is now tested
with two genuine accounts.

**2503 passing** (2442 + 61). Both ruff scopes clean, tsc and eslint clean,
11 frontend tests, build now **13 routes** (11 + login + signup).

#### Verified live, not just compiled

Signed-out `GET /api/career/my-jobs` → 401. Signup → 201 with
`HttpOnly; Max-Age=1209600; Path=/; SameSite=lax` and no `Secure` on local
http, as designed. Alice's application visible to Alice; Bob passing
`?user_id=` gets `total: 0` and his own id back. In the browser, `/my-jobs`
while signed out redirects to `/login?next=%2Fmy-jobs`.

Test accounts were removed afterwards; session rows cascaded with them.

#### Left alone deliberately

The pre-existing rows under `user_id = 'local'` (1 job, 2 applications, and the
original Chroma collection) are now **unreachable** — no account has that id.
They were not adopted by the first account to sign up, because guessing that
the first person to register owns whatever data was already on disk is wrong
the moment it is wrong, and `backend/` has no git history to undo it with. They
are harmless where they are. Deleting them is a decision for their owner.

Still missing, and honestly labelled as such in Settings: change password,
delete account, password reset. Each needs an endpoint that does not exist, and
a form that silently discarded a new password would be worse than no form.

### Prompt 59 — 2026-09-10

**"check this project is completed end to end? ... make sure it should run on
another laptop also if i share zip file and open there"**

Verified by actually doing it: zip, extract to a clean directory, fresh venv,
fresh `npm install`, run. That found one defect the resident suite could not.

#### A test that only passed on this machine

`test_config.py::TestOllamaBaseUrl::test_the_old_name_still_works_as_an_env_var`
passes here and **fails on a clean copy**.

`conftest.py` patches the `settings` *singleton*, so anything constructing a
fresh `Settings()` still reads `BASE_DIR/.env` off disk. That made the outcome
of the suite depend on an untracked file. This machine's `.env` has no
`OLLAMA_BASE_URL` line, so the legacy `LLM_BASE_URL` alias the test sets wins.
A `.env` copied from `.env.example` *does* have it, at
`http://localhost:11434`, and it beats the alias.

The sting: the same edit that documents `cp .env.example .env` — needed,
because the README said "open `backend/.env`" for a file that does not exist on
a fresh copy — is what would have made this fail for every new user. Writing
the instruction and testing the instruction were the same task, and only the
second one found it.

Fixed with a session fixture that sets `Settings.model_config["env_file"]` to
`None`. Clean copy now `2441 passed, 1 skipped`; the skip is
`no real key configured on this machine`, which is correct on a machine with no
key. Original still `2442 passed`.

#### The zip itself

Zipping the folder as it stands ships **1.8 GB** and, worse, ships
`backend/.env` — Gemini key and both Adzuna keys in plain text. It also ships
`backend/data`, which is the owner's CV, saved jobs and applications.

Excluding `.venv`, `node_modules`, `.next`, `data/chroma`, `data/uploads`,
`*.db`, `.env` and `.env.local` gives **1.2 MB**. Verified by extracting and
grepping for secrets rather than trusting the exclude list: none present, all
required files present, both sample fixtures retained.

Then verified it *runs*: clean venv installs from `requirements.txt` with exit
0, core imports fine, server boots, `status` correctly reports
`resume_indexed: False, chunks: 0` on empty data, sample CV uploads and indexes
to 8 chunks. Frontend: 717 packages, build succeeds.

#### Adzuna is load-bearing and was undocumented

`fetch_jobs_adzuna` returns `[]` when no key is set — deliberate, and the
docstring says so. But nothing in the README ever mentioned Adzuna, so a new
user would never know to get one. Measured on the same search:

| | Adverts |
| --- | --- |
| With keys | 14 |
| Without | **2** |

The degradation is honest — the response says "Only 2 advert(s) matching you
were posted in the last 7 days" and the chat labels itself `fallback` — but two
adverts is not a job hunt. Now documented as its own section, kept separate
from the Gemini key, because they control unrelated things and conflating them
is the likely reason a fresh copy disappoints.

#### Also confirmed

No hardcoded absolute paths anywhere in source. `.env.example` covers every key
`.env` uses. All writable directories self-create. `engines.node >= 20.9` is
declared and the lockfile ships.

### Prompt 58 — 2026-09-08

**"Just check this project end to end and confirm me all working correct if
anything needs to be corrected do it and finish it off"**

Two real defects fixed, one documentation error corrected, and four things
that looked like defects proved not to be.

#### The misleading 100%

The known one. A German-language advert had scored 100% against a junior CV
because exactly one skill was legible in it, and 1 of 1 is 100%.

The calculator was never at fault. It returns `confidence` — how much of the
advert could be read, 0–100 — alongside `overall_match`, and its docstring
says the two are *"reported separately on purpose"*. `job_enricher._match()`
kept the score and dropped the confidence, so the intent died one layer below
the screen. Surfacing it was restoring a decision, not making a new one.

The threshold is measured rather than picked: a one-skill advert scores 100
at confidence 50; a full eight-skill advert scores 79.5 at confidence 67.5.
60 sits between them. Below it the card greys the percentage and replaces the
verdict with "Little of this advert could be read — treat the score loosely".

The number is still shown. Suppressing it would hide a real match behind a
caveat, and the honest complaint was never "this number exists", it was "this
number is dressed up as a certainty".

**The fix was half-done when first verified.** The card was fixed and the page
still read `Perfect match (2)` — the same two adverts, promised again by the
filter chip directly above them. `categorize_jobs` bands on score alone. It
now refuses the top bucket to an advert it could barely read, and the live
page reads `Perfect match (0)` with the buckets still summing to the total.

Worth naming: the card fix alone would have passed a code review and looked
finished. Only rendering the page caught the second half.

#### A health check that cried wolf

Covered under Prompt 57 — a contended import on a worker thread reported the
database as unhealthy while SQLite was answering normally.

#### CORS

`CORS_ORIGINS` allowed 3000 and 5173. Port 3000 is taken on this machine, so
the app had been running on 3100 behind a hand-set environment variable that
died with every restart. 3100 is now in the defaults, verified by restarting
with no override and watching the preflight return
`access-control-allow-origin: http://localhost:3100`.

#### Four things that were not bugs

Each of these looked broken and was measured before being touched.

| Symptom | Reality |
| --- | --- |
| `interview-prep` returned `source: deterministic` while chat used the LLM | Hardcoded. Interview prep is deterministic *by design* — scaffolds quoted from the candidate's own CV, never invented answers |
| Only 2 questions returned | That is the technical subset. The pack holds 23 questions across 7 categories plus a 4-day plan |
| `success_rate_prediction` missing from the API | Deliberately undeclared. `PracticeAnswerResponse` states the rule two classes down: "a fabricated score is the most persuasive lie this app could tell" |
| Trace nodes all had `name: None` | The key is `node`. Checking before reporting also revealed the trace *does* carry `branch` and `projected_match`, which changed the Prompt 57 conclusion |

A fifth was a documentation error rather than a code one. The README claimed
the interview rate stays blank below five applications. It does not — it is
blank only until the first application is sent, after which it shows a real
rate beside a 95% confidence range (`0%–79%` after one). The behaviour is
better than the sentence describing it, so the sentence was corrected.

#### On the learning plan

Prompt 57 recommended surfacing the discarded `learning_plan`. That
recommendation was **withdrawn after measuring it**. The plan is only built
when the gaps close inside `DEFAULT_LEARNING_WINDOW_DAYS`, which is 14, and a
realistic advert produced `blocking_days: 194`. It came back `None` on every
live run. Building a card for it would have added UI that essentially never
renders — the output is rarely produced, not routinely thrown away.

#### End-to-end, measured

| Step | Result |
| --- | --- |
| Resume indexed | `resume_indexed: true`, 26 chunks |
| Insights | junior, 0.75 years, 19 skills, 8.1s |
| Discovery | 15 adverts, every one 1–7 days old, all 15 scored *and* carrying confidence, 45.9s |
| Interview prep | 23 items over 7 categories |
| Practice answer | Scored 7/10 by the model, `source: llm`, with a rewritten opening, 8.1s |
| Assistant | LLM-backed, CV-grounded, 21.1s |
| Save / track | Timeline logged `created` then `application_sent` with `from`/`to` |
| Pages | All 9 return 200 |

One transient worth recording: a burst of 429s mid-run. Gemini's free tier is
**per-minute**, and a 15-advert discovery exhausts it. The app degraded to its
deterministic path and labelled the output as such rather than passing it off
as model work — which is the behaviour the fallback exists for, observed doing
its job under real load rather than in a test.

#### Gates

`2442 passed`, ruff at its 5 intentional findings, `tsc` and `eslint` clean,
11 frontend tests, 11 routes.

### Prompt 57 — 2026-09-08

**"See just go through whole project code once because u created 136 files
and added 54778 lines soo check all are 100% required for my project if not
pls remove unwanted code changes"** — plus a restatement of the four things
the product must do, and a note that the Gemini key is already in `.env`.

A fair challenge. The tree had grown across fifty-six prompts and nobody had
ever gone back to ask which of it was still load-bearing.

#### How "unused" was decided

The first attempt at this was a shell one-liner that grepped for each module
name and called anything with a single hit an orphan. It reported `Sidebar`,
`JobCard` and `lib/api.ts` as dead — three files the application obviously
cannot run without. It was matching import paths in a way that missed most
real references.

That is worth recording as the lesson rather than the bug: **a detection tool
gets checked against a known-good case before its output is believed.** Had
the first list been acted on the application would have been destroyed, and
with no git here that would have been permanent.

The replacement builds a real import graph — Python's `ast` module to read
every `import` and `from … import` statement — and walks it breadth-first
from the two true entry points, `main.py` and `config.py`. Anything the walk
never reaches cannot execute, whatever a grep says about it.

#### What the walk found

Of 38 backend modules, 34 are reachable. Four are not:

| Module | Lines | Reached by |
| --- | --- | --- |
| `agents/job_hunt_pipeline.py` | 437 | nothing |
| `agents/application_dashboard.py` | 228 | only `job_hunt_pipeline`, itself dead |
| `utils/benchmarks.py` | 289 | nothing |
| `agents/parallel_executor.py` | 179 | only `utils/benchmarks.py`, itself dead |

Two of the four are dead only *transitively* — they have a caller, but the
caller is itself unreachable. A single pass would have kept them; the graph
walk is what exposes the whole limb.

Their three test files came out with them (581 lines). Deleting a module and
leaving tests that import it just converts dead code into a broken suite.

Total removed: **1,714 lines across seven files**, with three further test
files edited to drop stale references. Nothing was deleted before the graph
proved it, and everything was archived first —
`/tmp/careerpilot_deadcode_backup_20260908.tgz` — because there is no version
control in this workspace to undo a mistake.

One of those edits needed care. `tests/test_ollama_handler.py` imported
`job_hunt_pipeline` inside the guard that proves no agent holds a live API
key at test time — the check that stops the suite spending real money. The
import was dropped and `complete_workflow`, the larger composite, left to
carry the check; the comment beside it was corrected too, since it spoke of
"agents" plural.

#### What was *not* removed

The eight agents that looked ornamental — `advanced_workflow`,
`agent_collaboration`, `conditional_graph`, `learning_path_agent`,
`gap_detector`, `resume_optimizer` and the rest — are all reachable through
`complete_workflow`, whose `run()` takes `advanced: bool = True`. Advanced is
the **default**, so that path is what runs on every ordinary analysis. A
live trace confirmed it: eight nodes, 15.3 seconds. They stay.

The frontend is clean. All 44 `.ts`/`.tsx` files are reachable from the 12
route entry points; the only file with no importer is `next-env.d.ts`, which
Next.js generates and requires. There were no unused shadcn primitives.

#### A real bug the audit uncovered

Restarting the backend afterwards, `/api/health/full` reported
`overall_status: unhealthy` with the database down. The database was fine —
the very next request said `healthy`.

The log gave it away: `_DeadlockError: deadlock detected by
_ModuleLock('agents.ollama_handler')`. The probes import their dependency
inside the probe body, deliberately, so that importing the health module does
not drag every agent and its credentials into the process. But the probes run
on worker threads, and a thread reaching a module that another thread is
mid-import of does not block and wait — CPython detects the cycle and raises.

The probe's `except Exception` could not tell that timing accident from a
corrupt database, so it announced the user's data was gone.

For a status page, being wrong in that direction is close to the worst
option, so `_lazy_import` now retries once after 250 ms and lets a second
failure through as genuine. One retry, not a loop: a probe must never itself
become the hang it exists to detect.

Guessing the exception's base class would have broken the fix silently —
`_DeadlockError` subclasses `RuntimeError`, **not** `ImportError`, which is
the natural assumption. It was checked in the interpreter, and a test now
pins that fact so nobody narrows the `except` later on a hunch.

Five tests cover it: the base class, the successful retry, a genuine
`RuntimeError` *not* being retried, a permanently locked import still being
reported, and the database probe surviving one contended import.

#### Gates

`2436 passed` (2484 before, minus 53 in the deleted test files, plus the 5
new ones), ruff still at its 5 intentional findings, frontend unchanged at 11
tests and 11 routes, and `/api/health/full` healthy from a cold start with no
deadlock in the log.

The Gemini key was verified live rather than assumed: a real
`generate("Reply with exactly: OK")` returned `OK`.

### Prompt 56 — 2026-09-07

**"not like this i should get automatic link of that job / example if any
jobs posted on linkdin I should get link here for lasy 7 days like that for
all webistes i said u"**

Fair rejection. Prompt 55 handed the user a set of pre-filled search links
and called it done, which moved the work back onto them — the opposite of
what was asked. What was wanted is the advert itself, in the app, with a
link that applies.

The blocker in Prompt 55 was real and has not changed: LinkedIn, Indeed,
Naukri, Foundit and Wellfound each forbid automated reading of their
listings. But "we may not take it from them" is not the same as "it cannot
be had". Those boards license their inventory to aggregators, and Adzuna is
one — it redistributes what it has the right to redistribute and issues API
keys for exactly this purpose. Going through the licensee reaches much of
the same market by the front door.

Adzuna fits the requirements unusually closely:

| Requirement | How Adzuna satisfies it |
| --- | --- |
| India only | `/v1/api/jobs/in/search/1` — the country is in the URL, so it cannot be omitted by accident |
| Last 7 days | `max_days_old=7`, applied at the source, so the window costs one request instead of a page of discards |
| Direct apply link | `redirect_url` points at the advert itself |

Added `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` to `config.py` and `.env.example`,
`api.adzuna.com` to `ALLOWED_HOSTS`, `fetch_jobs_adzuna` plus the
`_fetch_adzuna` adapter, and registered it second in `self.sources` so its
results interleave near the top.

**Unset by default, and silent about it.** `fetch_jobs_adzuna` returns `[]`
when no key is configured. An optional source nobody asked for is not a
fault, and raising or warning there would degrade discovery for every
install that never wanted it. The user needs a free key from
<https://developer.adzuna.com> before this contributes anything — that is a
setup step, not a bug, and it is stated plainly rather than buried.

Five tests added, all offline via the injected `fetcher`: no key returns
nothing; an advert keeps its `redirect_url`, nested `company.display_name`
and `location.display_name`; `max_days_old=7` genuinely reaches the URL; the
India endpoint is asserted; a malformed entry is skipped rather than
crashing the search.

`test_the_example_file_documents_every_setting` caught the new settings
missing from `.env.example` — the test earning its keep on the first
opportunity it had.

**Then the key went in and it returned nothing.** Not a parsing bug: the log
said `robots.txt at api.adzuna.com disallows this path`. Their robots.txt is
`User-agent: * / Disallow: /`.

This needed deciding rather than working around. robots.txt governs
*crawling* — a program discovering content by following links — and RFC 9309
is written throughout in those terms. An API host publishes a blanket
disallow to stop search engines indexing JSON; `api.github.com` says exactly
the same thing. Obeying it against a request we hold an issued key for would
be refusing an invitation because the door has a "no hawkers" sign.

So `CREDENTIALLED_API_HOSTS` exempts that one host, and the shape of it
matters: a hardcoded map, one host at a time, each entry naming the
credential that justifies it. No setting widens it, because "ignore
robots.txt when convenient" is the exact behaviour the rest of the module
exists to prevent. Three tests hold that line — the exemption is reached
without robots.txt being fetched at all, the map contains only that host,
and an ordinary host is still refused when its robots.txt says no.

That last test was initially written so that it would also have passed if
the robots fetch merely failed, which would have proved nothing. It now
supplies the parser directly.

**A second defect surfaced once results were flowing:** the same EPAM
vacancy appeared twice. `_dedupe` keyed on URL when a URL was present, and
Adzuna carried one role under two advert IDs — so two different URLs, one
job. Identity is now matched on employer, title *and* location as well as
URL. Location is in that key deliberately: the same title in Bangalore and
in Pune is two openings, and collapsing those would hide a real job from
someone in the other city, which is a worse failure than the duplicate being
fixed.

**Verified live, end to end.** Before the key: 1 advert, from Paytm alone.
After: 15 adverts from Adzuna, Druva and Paytm, top match 100% — a Full
Stack Developer Intern role, against a CV that reads junior. An apply link
was followed to `adzuna.in` and answered 200 with a page title matching the
advert. (`curl` gets 429 there; that is bot rate-limiting, not a dead link,
which is why this was checked in a real browser.)

Suite 2474 → 2484. Ruff unchanged at the 5 intentional findings.

The Prompt 55 outbound links were kept. They are not the answer, but they
cost nothing and still cover the ground no licensee reaches.

### Prompt 55 — 2026-09-07

**"It's searching and sending me jobs but I need it to search also from
LinkedIn, Indeed, Foundit, Wellfound, Naukri as well — can you do it?"**

No, and the reason is recorded in `CLOSED_JOB_BOARDS` in
`agents/job_scraper.py` precisely so it does not have to be re-argued: all
five forbid automated collection or publish nothing a program may read.
Wellfound was added to that map here, since it had not been asked about
before. The practical objection matters more than the legal one — the person
asking is job-hunting on these sites, and an app that got their IP or account
flagged on Naukri would cost them the thing they came for.

So the request was met sideways rather than refused flatly. **A row of
outbound links now appears under every search**, in
`components/dashboard/SearchElsewhere.tsx`: LinkedIn, Naukri, Indeed, Foundit
and Wellfound, each opening that same search on that site with India and a
seven-day window set through the site's own published query parameters
(`f_TPR=r604800`, `jobAge=7`, `fromage=7`). A hyperlink is not a scraper. Only
the search term crosses, the user arrives signed in as themselves, and no
result comes back into the app. Where a site later renames a parameter the
extra filter is ignored and the link still lands on a search for the right
words, which is a soft failure rather than a dead button. The term is encoded
once with `encodeURIComponent` so an `&` in a search cannot reshape the URL,
and every link carries `rel="noopener noreferrer"`.

**A bug of my own, caught in the browser rather than by a test.** The panel
first read its term from the input box. Typing into the box without pressing
Search then produced links for one search while the results on screen were
for another — the CV-derived one. It now reads `params.query`, which changes
only when a search is actually submitted. Verified by typing "typed but never
submitted" into the box and confirming the links still pointed at
`junior software engineer`.

**Two boards added, and only two.** Thirty-six candidate Indian company slugs
were probed against the Greenhouse, Lever and Ashby APIs; thirty-four were
dead or wrong, because a company's ATS slug rarely matches its name and
guessing is not a method. Sarvam AI (63 jobs, all dated, all in India) and
SpotDraft (13 jobs, 10 in India) were real and were added. They contribute 5
adverts inside the seven-day window, in Bengaluru, aged 0–5 days. They did not
appear in a search for "engineer" — that is the query filter doing its job,
not a broken source, and it was checked directly against the feeds rather
than inferred from the empty result.

A stale `./app/(dashboard)/dashboard/page.tsx` module-not-found error appears
in the dev server console. No such file exists, and `build`, `type-check` and
`lint` are all clean, so it is a `.next` cache artifact and was left alone
rather than chased.

### Prompt 54 — 2026-09-07

**"It has my resume in it so just clean up and it should look like a new
project so that I will test it end to end from now."**

A data reset, not a code change. Nothing in `agents/`, `rag/`, `models/`,
`utils/` or the frontend was touched, and the suite was re-run afterwards to
prove it.

Two things were established before deleting anything, because there is no
version control here and every deletion is final. First, what was actually
stored: a 5.3 MB Chroma index, a 128 KB `jobs.db` holding 4 saved jobs and 9
applications, 16 MB of logs, and 16 uploaded files. Second, and more
importantly, that the five uploaded PDFs were **the only copies of the CV
anywhere in the workspace** — a `find` across `/Users/rmedi/Resume` excluding
the app's own data directory returned nothing. That was put to the user rather
than assumed, with the offer of a backup. The user confirmed they had the
original elsewhere.

Removed: `data/chroma`, `data/jobs.db` and its `-shm`/`-wal` siblings,
`data/uploads`, `data/logs`. Kept: `data/sample_jd.txt` and
`data/sample_resume.txt`, which are non-personal fixtures shipped with the
project. The backend was stopped first so SQLite and Chroma released their
handles, and `uploads/` and `logs/` were recreated empty. `localStorage` was
cleared in the browser too — it held one key, `theme`.

**A measurement bug in the verification, worth recording.** The first check
after the restart reported "saved jobs: 4, applications: 4" and looked like the
delete had failed. It had not. The one-liner was
`len(d.get('jobs') or d)`, and an empty list is falsy, so it fell through to
counting the four top-level keys of the response envelope. Reading the SQLite
tables directly showed `jobs: 0, applications: 0`. The `or` fallback idiom is
wrong for any value that can legitimately be empty; the lesson is the same one
this codebase keeps returning to, which is that a plausible number is not a
measured one.

**What the empty state actually looks like**, checked on all nine pages:

- `/` — "Start with your resume", the upload prompt. Requirement 1, unaided.
- `/my-resume` — "No resume uploaded yet".
- `/my-jobs` — "Nothing saved yet."
- `/my-applications` — Tracked 0, Ever sent 0, and **"Interview rate" with no
  number against it**. Zero applications sent makes the rate undefined, not
  0%, and the card says so by staying blank.
- `/discover-jobs` — "No resume is indexed, so there is nothing to work out
  your roles from", with a link to upload. It does not attempt a search.

`/` and `/discover-jobs` each log a browser console error for a `409 Conflict`
on first load. This is deliberate and was left alone: the backend uses 409 to
mean "no resume indexed", the pages catch it and render their first-run state
from it, and the console line is the browser reporting any 4xx response, not
the application failing. Gates after the reset: 2474 backend tests, ruff at
its five intentional findings, frontend build/type-check/lint/tests clean.

### Prompt 53 — 2026-09-07

**"Just check end to end and confirm me that all my project works 100%."**

Taken as an instruction to verify rather than to assert. Every gate was
re-run, every endpoint exercised against the live backend, and the whole
user journey walked in a real browser. Three defects surfaced that the
previous audit had not reached, because the previous audit checked that the
job pipeline *returned* adverts without checking what was *in* them.

**1. Hacker News adverts could not be applied to.** Requirement 5 asks for a
direct link to the posting. Every Hacker News advert's `url` was the comment
permalink — `news.ycombinator.com/item?id=…` — which is a discussion to read,
not a job to apply for. The real careers link was sitting unused in the same
headline the title and company were already being parsed out of:

```
Supero | Cloud / Platform Engineer | REMOTE (SF Bay Area, CA, US · Bengaluru,
KA, India) | Full-time | https://www.supero.dev/careers/cloud-platform-engineer
```

`_hn_apply_url` now takes it, preferring the headline over the body because a
comment often links its product or blog further down. The permalink is kept
as `discussion_url`. Only `http(s)` is matched, so a `javascript:` payload in
a comment can never reach an `href`.

**2. The same adverts showed no location.** Hacker News has no location
field, so the card rendered a blank where the headline plainly said
"Bengaluru, KA, India". `_hn_location` reads it off the headline, and is
deliberately narrow: it accepts only a segment naming a place the search
vocabulary knows. `_location_haystack` prefers this field over the headline,
so a segment with no place in it would *hide* the place from the country
filter and drop a valid advert. Anything unrecognised stays blank.

**3. Education was never reported, and Indian degrees were unreadable.**
Requirement 2 names education explicitly. `resume-insights` returned no such
field — and `ResumeInsightsResponse` would have stripped it even if the
profiler had produced one. Worse, once wired through it read "Not stated" for
a CV that says **"B.E. in Information Science & Engineering"**. The pattern
table covered `b.tech`, `b.sc` and `b.eng` but not `B.E.` — one of the
commonest degrees on an Indian CV, in a product that searches only India.
Added `B.E.`, `M.E.`, `M.Tech`, `MCA`, `BCA`, `BBA`, `B.Com`, `M.Com`.

`B.E.` also exposed the `\b` trap already documented in `_place_patterns`: a
word boundary after a full stop demands a word character that a following
space does not supply, so `\b(…|b\.e\.)\b` never matched. The group now closes
with `(?!\w)`. Both are matched with their dots only — bare "be" and "me" are
ordinary English words, and "happy to be contacted, please email me" must not
come back as a graduate. Four such phrases are asserted against.

One hypothesis was investigated and **disproved**: the resume index was found
empty at the start, and `chroma.sqlite3` had been written at the exact minute
the previous test run finished, which suggested the suite was destroying real
data. Measured directly — 26 chunks before the suite, 26 after. `conftest`'s
`isolated_storage` is autouse and repoints every writable path. The suite is
not the cause and no change was made.

Gates after: **2474 backend tests** (+28), ruff still exactly 5 intentional
`ARG` findings, frontend type-check/lint/build clean, 11 tests, 11 routes.

Measured limits, unchanged and inherent: discovery takes 35–40s cold, the
7-day rule legitimately returns very few adverts (a CV-derived search returned
one), and interview question generation took 122s.

### Prompt 52 — 2026-09-07

**A full-codebase audit against eight stated goals**, with instructions to
remove only what is confidently unnecessary, to change nothing for the sake of
changing it, and not to assume the current implementation is correct.

The last instruction earned its place. Three of the eight were not met.

#### Requirement 4 — "jobs from the last 7 days" was not what the code did

`MAX_AGE_DAYS` was **2**, and `_apply_freshness` ran a ladder — 2 days, then 7,
then 30, then it dropped the date filter altogether and admitted undated
adverts. It announced each widening, so it was honest, but "last 7 days" is a
promise and a ladder that reaches 30 days is not that promise.

Measured over the India set before changing anything:

| Window | Adverts |
| --- | --- |
| 2 days | 1 |
| 7 days | 13 |
| 14 days | 27 |
| 30 days | 43 |
| undated | 0 shown under the old filter-drop |

`_MAX_WINDOW_DAYS = 7` is now a ceiling rather than a target. `requested=None`
means 7, not unbounded. A request wider than 7 is clamped down to it and says
so. When nothing is found the reported window is the ceiling, because "nothing
in the last 2 days" invites a retry that cannot help. Undated adverts can never
appear.

That last point cost a test. `FAKE_JOBS` in `tests/conftest.py` carried no
`posted_date` and no `days_old`, so under the new rule discovery correctly
returned nothing and the week-2 journey test failed at its first assertion. The
fixture is now dated relative to now — a pinned date would age out of the
window and take the journey tests with it on a quiet Tuesday.

#### Requirement 6 — nothing connected a job to interview prep

Both pages existed and both worked; there was no route between them. The user
had to find the advert again and paste it in by hand.

`lib/interview-handoff.ts` stashes the advert in `sessionStorage`, and
`/interview-prep` reads it once on mount and clears it. Read-once matters: a
stale advert reappearing three navigations later would be worse than no feature
at all. The button fills the box and does **not** submit, so a job opened out
of curiosity does not spend a model call.

The lint rule `react-hooks/set-state-in-effect` objects to the mount effect. It
is suppressed with a block directive and an explanation, because the rule
cannot distinguish "derived state cascading" from "read an external store that
does not exist during server rendering". A lazy `useState` initialiser is the
usual alternative and is wrong here — the page is prerendered, so the server
would render an empty box and the client a full one.

#### The bug the audit was actually for

With the handoff built, both **Run full analysis** and **Prepare for this
interview** were greyed out on live adverts. Not a UI fault: the India company
boards were returning **no description at all**.

```
Cloud / Platform Engineer   Supero       desc=1007  src=HackerNews
Manager, Engineering        Druva        desc=   0  src=Druva careers
AI Agent Engineer           Observe.AI   desc=   0  src=Observe.AI careers
```

`_greenhouse` read `entry.get("content")`, but Greenhouse omits that field
unless asked. Measured directly against the API:

```
WITHOUT content=true -> 41 jobs,  0 carry content
WITH    content=true -> 41 jobs, 41 carry content
```

One query parameter. Every Greenhouse advert — six of the twelve boards — had
been arriving as a title, a company and a link, with nothing to score against
the resume and nothing to build questions from. The adverts still appeared and
the page still looked fine, which is why this survived the feature being built,
reviewed and shipped. The test asserts on the **URL**, not just the parsed
output, so the parameter cannot be dropped again without a failure.

Fixing that exposed a second one. The fixture used entity-encoded HTML
(`&lt;p&gt;`), which is what Greenhouse actually publishes, and the parsed
description came back as `<p>Python and Postgres.</p>`. `_strip_html` ran
`html.unescape` **after** tag removal, so encoded markup passed through
untouched and was then decoded into visible litter — which flows into skill
extraction and the LLM prompt, not just the screen. Unescaping first is also
the safer order: `&lt;script&gt;…&lt;/script&gt;` now becomes a real script
element and is removed with its contents.

Live after both fixes: descriptions of 6,487 and 6,347 characters, no tags,
none missing.

#### Removals

Confirmed unreferenced and removed without asking:

- `backend/results.txt` — regenerated output of `test_complete_workflow.py`
- `frontend/components/forms/` — empty directory
- `recharts` — 0 references; the charts page it served was removed earlier

Removed after asking, because deletion here is permanent:

- `app/(auth)/login` and `app/(auth)/signup` — non-functional by design, and
  nothing anywhere linked to them
- `POST /api/v1/resumes/upload` — stored a resume **without** indexing it, and
  was the source of the orphaned files in `backend/data/uploads/`
- `POST /api/career/calculate-match` — a strict subset of `/full-analysis`
- `GET /api/career/dashboard` — its page and API wrapper were already gone

25 routes → 22. 13 frontend routes → 11.

The deleted endpoints' tests were not simply deleted. `TestCareerUploadResume`
already covered path traversal, size limits and extension rejection on the
surviving endpoint; only the case-insensitivity check was unique, so it was
ported. The "two words are not an advert" and "unreadable input" tests were
ported onto `/full-analysis`, since that invariant was a real bug fix and is
worth more than the route it was written against. Each removed endpoint keeps
one test asserting it now 404s, so a caller written against the old shape gets
a named failure rather than a puzzle.

#### Kept, deliberately

- `my-jobs`, `my-applications`, `settings` — outside the eight goals, but the
  user had previously called them good, and they work. Asked; told to keep.
- `agents/job_hunt_pipeline.py`, `agents/parallel_executor.py` — reachable only
  from their own tests, but documented Week 2 deliverables. Asked; told to keep.
- `backend/run_test.py`, `test_api.py`, `test_week1.py`,
  `test_complete_workflow.py`, `utils/benchmarks.py` — manual scripts, not dead
  code.
- The five ruff ARG findings. Still intentional, still five.

#### What the audit found clean

- No TODO, FIXME, mock, placeholder or "coming soon" markers in any source file
- `.env.example` documents every `config.py` field, with no drift either way
- Every backend dependency justified — `httpx` via `TestClient`, `multipart`
  via FastAPI uploads, `numpy` transitively via Chroma
- All 354 India adverts carried an apply URL

#### Verification

2446 backend tests, 21.6s. Both ruff scopes as expected. Frontend type-check,
lint, 11 tests and build all clean at 11 routes. Live: `max_age_days_used` 7,
every advert inside the window with a URL and an Indian location, apply links
200 (Druva returns 403 to non-browser agents — a WAF, not a broken link), the
assistant answering from indexed resume content. The handoff was walked in a
browser end to end: 2,483 characters prefilled, "Filled in from Senior Staff
Software Engineer at Druva", cleared on reload, no console errors.

#### Limitation found and not fixed

The suite makes no HTTP requests, but it is not offline. `_fetch` calls
`_validate_url` — the SSRF guard, which resolves the hostname — **before** the
injected fetcher runs. When DNS was unavailable mid-audit, 30 tests failed and
the run took 19m31s; with DNS up the same suite passes in 21.6s. The guard's
ordering is correct for production and will not be weakened to make tests
faster, so this is recorded rather than repaired.

#### An honest correction

An earlier probe reported the chat endpoint returning an empty reply. The probe
was reading `response`; the field is `reply`. The assistant was working the
whole time.

---

### Prompt 51 — 2026-09-07

**"Hey I need jobs inside india only not outside india and it should fetch from
available websites like linkdin, indeed, foundit, naukari and many more"**

Two halves, and they pull in opposite directions. The India-only half was
straightforward. The four named boards cannot be done at all, and saying so up
front was the only honest answer.

#### The four named boards

Each was checked rather than assumed, and the reason is now recorded in code as
`CLOSED_JOB_BOARDS` in `agents/job_scraper.py` so it is not re-litigated from
memory the next time it is asked:

| Board | Why not |
|---|---|
| LinkedIn | No public jobs API. User Agreement §8.2 prohibits automated collection. |
| Indeed | Publisher Jobs API withdrawn to existing partners; robots.txt disallows `/jobs`. |
| Naukri | No public API; terms prohibit automated extraction. |
| Foundit | Ex-Monster India; same prohibition. |

Building a scraper for these would break their terms and would break on their
next markup change. The user was told this plainly rather than being handed
something that half-worked.

#### What was probed instead

Everything below was measured against the live service, not guessed from
documentation:

| Candidate | Result |
|---|---|
| RemoteOK | 200, keyless — but **1 of 100** adverts India-related. Rejected. |
| Himalayas | 200, 105,395 adverts — but **ignores every filter parameter**. `country`, `location`, `locationRestrictions` and `search` all return unfiltered results and `totalCount` barely moves. Rejected: an API that accepts a filter and silently ignores it is worse than one that refuses it. |
| Adzuna India | 400 — alive, but needs a registered `app_id`/`app_key`. |
| Jooble | 403 — needs a key. |
| Careerjet | Connection refused. |
| **Company ATS boards** | **Accepted.** |

#### The source that was built

Greenhouse, Lever and Ashby publish a company's own vacancies as JSON so that
company's careers page can render them. No key, no scraping, and nothing that
was not deliberately published. Twelve Indian employers are registered in
`INDIA_BOARDS`: Paytm, Meesho, CRED, Epifi, Sigmoid, Zenoti, Netradyne, Druva,
Observe.AI, Groww, Postman, Atlan. Measured on the day: **513 raw adverts, 354
after the India filter.**

Three readers (`_greenhouse`, `_lever`, `_ashby`) each return the same 5-tuple,
so `fetch_jobs_india_boards` does not care which vendor a company uses. Each
board is wrapped in its own `try`/`except`: a company can rename its board or
change vendor at any time, and one dead board must not take the other eleven
with it.

#### Two bugs found while building it

**Lever dates are epoch milliseconds.** Every other source in this codebase
sends seconds. Passed through unconverted, every Lever advert lands in 1970 —
sorted to the bottom of the list and labelled some thousands of days old.
`_epoch_seconds` converts them, and returns `""` rather than `0` for missing or
unparseable input, so an undated advert stays undated instead of becoming
1970-01-01. That is the same rule as everywhere else here: never render missing
as a number.

**One employer crowded out the rest.** Paytm alone has 173 India adverts; Atlan
has 6. Taken in source order, `limit=10` was ten Paytm adverts and the other
eleven companies might as well not have been fetched. This is the identical bug
the codebase already documented for cross-source results ("ten Hacker News
comments") — so the fix was to group by company and reuse the existing
`_interleave` rather than write a second one. After it, `limit=12` returns
exactly one advert from each of the twelve.

#### The default location changed, and eleven tests caught it

`JobDiscoveryRequest.location` moved from `"remote"` to `"india"`. Eleven tests
in `test_job_endpoints.py` failed immediately — they drive a canned
WeWorkRemotely feed of Remote/Berlin adverts and had been leaning on the old
default. They test endpoint plumbing, not location filtering, so they now name
`"location": "remote"` explicitly. A new test asserts the default really is
India by checking that the same remote feed comes back empty.

Worth noting the failure was useful: it is exactly what a default change should
do to a suite that depends on it.

#### Verified live

`POST /api/career/discover-jobs` with `engineer`/`india` returns ten adverts
from ten distinct employers across Pune, Bengaluru, Bangalore and Hyderabad,
with real posted dates. One result came from Hacker News with a null `location`
field and still passed the India filter — checked, and its headline reads
`Supero | Cloud / Platform Engineer | REMOTE (SF Bay Area, CA, US · Bengaluru,
KA, India)`. Not a leak; `_location_haystack` working as designed.

2,469 backend tests pass, up from 2,460. Both ruff scopes unchanged — the five
intentional `ARG` findings in production, clean tests. Frontend type-check,
lint, 11 tests and a 13-route build all pass.

The **Search anywhere instead** button stays. It is an explicit user action and
never automatic: a page headed "India" must not quietly show Berlin.

### Prompt 50 — 2026-09-05

**"Review the existing project carefully. The project is already working well,
so do not rebuild everything from scratch."** Five features, one flow: upload
resume → analyse → find current jobs → select → prepare → assistant. Plus
"remove unnecessary features", and a closing line pinning three of them down —
"saved jobs, settings, applications are Good".

**Nothing is in version control.** `git status` at the repository root returns
`fatal: not a git repository`. Every deletion below is permanent and was
confirmed with the user before it happened. Only `/dashboard`, `/analytics` and
the four-line `app/page.tsx` redirect were authorised, and nothing else was
touched.

#### Resume first, because everything depends on it

`app/page.tsx` used to be `redirect('/dashboard')`. It is now
`app/(dashboard)/page.tsx` — inside the route group, so it inherits the sidebar
and header shell rather than reimplementing them — and it calls
`getResumeInsights()` on mount. No resume means an upload box and nothing else.
A resume means a summary card and the four numbered steps.

The distinction that matters is between *no resume* and *broken backend*. Both
arrive as a rejected promise. `noResume` is `error.includes('No resume
available')`, which is the backend's own wording; anything else is
`brokenBackend` and gets an `ErrorMessage` with a retry, not an upload box.
Offering someone an upload form when the server is down would have them
uploading a CV into a void.

Validation is client-side as well as server-side: extension and a 10 MB ceiling,
checked before the request is sent, and `event.target.value = ''` afterwards so
that picking the same file twice actually fires twice.

#### DOCX, via the standard library

`ALLOWED_EXTENSIONS` gained `.docx`. `python-docx` was not added for it: a
`.docx` is a zip containing `word/document.xml`, and `zipfile` +
`xml.etree.ElementTree` read it in about forty lines. A dependency that exists
to save forty lines of stdlib is forty lines of stdlib plus a dependency.

`_extract_docx` mirrors the defences already in `agents/job_scraper.py::_parse_xml`:

- **Zip bomb.** `info.file_size` is checked against a 10 MB ceiling *before*
  `read()`, because checking afterwards is checking after the damage.
- **DTD.** Word does not emit one. A `.docx` that declares a DTD is either
  corrupt or hostile, and either way is refused rather than handed to a parser.
- **Runs.** Word splits a single word across `<w:t>` elements at arbitrary
  points — formatting boundaries, spell-check state, revision marks. Runs inside
  one `<w:p>` are joined with *no* separator and paragraphs with `\n`. Verified
  live: a document whose XML holds `Post` and `greSQL` as separate runs comes
  back as `PostgreSQL`. Joining with a space would have produced `Post greSQL`
  and silently cost the user a skill.

Errors are specific enough to act on. A renamed `.doc` is told to re-save it; a
zip that is not a Word document says so; a document with no text is told its
content is probably images and to export a PDF with selectable text.

#### Recency, and the trap of a helpful default

`_date()` returned today's date when an advert had no date on it. That is the
single worst possible default for a feature whose entire purpose is a 2-day
window: every undated advert would have sorted to the top and claimed to be
brand new. It now returns `""`.

`_age_in_days` returns `Optional[int]` — `None` for absent or unparseable, never
`0`. `_by_recency` sorts dated adverts newest-first and appends undated ones
last in their original order rather than interleaving them at an invented
position. `fresh_jobs(jobs, max_age_days)` deliberately **excludes** undated
adverts: an advert that will not say when it was posted cannot be shown under a
heading that says "last 2 days".

> **Superseded.** The ladder below was removed in Requirement 4 of a later
> prompt (see *"jobs from the last 7 days" was not what the code did*, earlier
> in this file). `_FRESHNESS_LADDER` no longer exists: `_MAX_WINDOW_DAYS = 7` is
> now a hard ceiling and the window never widens past a week. The reasoning
> below is kept because it explains why the note exists at all.

The endpoint applies a ladder rather than a filter. `_FRESHNESS_LADDER = (7, 30)`,
`_TOO_FEW = 3`: try what was asked for, then a week, then a month, then no date
filter at all. Whichever rung it lands on, `freshness_note` says so in the
response and the page prints it verbatim — *"Only 0 advert(s) matched you from
the last 2 days, so this list covers the last 30 days instead."* Seen on a live
run. Silently widening would have been the same lie as the old `_date` default,
one layer up.

`undated_count` is computed **before** truncation to `limit`, or it would count
the page rather than the search.

#### India, whole words only

`_LOCATION_ALIASES` maps `"india"` to india, bharat and thirty-odd cities. Cities
only — no states, because "Punjab" and "Bihar" appear in far too many other
strings.

Matching is `re.search` with lookaround word boundaries, not `in`. Three tests
exist because three substrings genuinely collide: **Indiana** contains "india",
**Punengo** contains "pune", and a search for a single city must not drag in the
whole country alias list.

Then the honest part, measured rather than assumed: **of 182 live adverts
fetched, 2 mentioned an Indian place**, and `_filter_jobs(jobs, '', 'india')`
kept exactly those 2. The filter is correct. The feeds are the limitation, and
both READMEs now say so with the number attached. The empty state offers
"Search anywhere instead" as a button rather than doing it automatically —
showing US roles under a heading that says India is the worse of the two
failures.

#### "Why should I apply for this job?"

`_match_reasons(score, matched, missing, analysis)` composes the answer from
values already computed. Nothing is generated, so nothing can be invented, and
every line is checkable against the user's own CV in seconds.

The gaps are in the same list as the overlaps. A panel of reasons to apply with
the reasons against left off is advertising, and the user is the one who would
be sitting in the interview being asked about the missing half.

Two corrections came out of reading the live output rather than the tests:

- **"The advert is pitched at unknown level."** The analyser stores an
  undetermined seniority as the literal string `"unknown"`, which is truthy.
  Same for `role_type` defaulting to `"general"`. Both are now skipped. This is
  the project's oldest rule — a blank is not a value — leaking through a
  sentinel that happened not to be `None`.
- **A card that said "the advert did not list its skills clearly enough to
  compare" and then, four lines down, "on skills alone this is one of the
  closest matches found."** Both cannot be true. The 80+ claim now requires
  `total` to be non-zero; with no skills to compare, a high score is an artefact
  of the scoring, not a finding.

#### Interview prep: four new sections, and two bugs found by using it

HR questions are kept in their own bank rather than folded into behavioural.
Different room, different interviewer, different answers.

Project questions quote the resume **verbatim**. Paraphrasing would mean
generating a description of work this code cannot verify, and the candidate
would then be rehearsing for a question about a project that does not quite
exist.

Two things went wrong there, both only visible by running it against the real
indexed CV:

**The run-on quote.** `split_bullets` splits on newlines. Text pulled out of a
PDF frequently has none, so a whole role arrived as one "line" and was quoted
back as `Junior AI Developer - TechCorp (2023-Present) - Built RAG system with
LangChain - Implemented embeddings pipeline - Created REST AP...`. Truncated
mid-word, and pointing at four things at once. `_achievement_lines` splits on
`" - "`, but **only** when the line is over 180 characters *and* contains at
least two separators — a single bullet may legitimately use a dash as
punctuation, and splitting that would throw the achievement away. Both cases
have a test.

**The summary quoted as a project.** With the run-ons split, the page started
quoting `RAHUL SHARMA PROFESSIONAL SUMMARY: AI/ML Developer with 2+ years...`
back at its own author and asking what the hard part was. A resume bullet is
written verb-first by convention, and that convention is the cheapest signal
available that a line is an achievement rather than a heading, a title, a
summary or a skills list. `_ACHIEVEMENT_VERBS` is a deliberate whitelist —
guessing that anything past-tense-looking qualifies over-reaches, and missing a
bullet costs one question out of a capped six.

#### The analyser bug underneath the improvement areas

`areas_to_improve` advised: *"Build one small thing with Backend before the
interview."* Not an instruction anyone can follow.

Tracing it: the advert was `Backend Engineer. Python, FastAPI, Kubernetes and
PostgreSQL required. 3+ years.` The rules-based `job_analyzer.analyze()` reads
that correctly. The LLM-backed `job_analyzer_agent.analyze()` returned
`required_skills: ['backend engineering']` — it summarised the role instead of
listing the technologies. Everything downstream intersects the advert's skills
with the resume's, so one unusable string starved the whole page: **zero
technical questions** for an advert naming four technologies the candidate has
three of.

`parse()` already raised on an *empty* skill list. It now also raises when none
of the returned skills is a recognisable technology, which hands over to the
rules-based extractor rather than losing the analysis. Verified: the guard
fires, `source` becomes `fallback`, `required_skills` becomes
`['fastapi', 'kubernetes', 'postgresql', 'python']`, three technical questions
appear, and `areas_to_improve` names Kubernetes.

`_areas_to_improve` was hardened independently — it draws from `tech_stack` as
well as `required_skills`, and filters candidates through `find_skills()` — on
the principle that a display layer should not print nonsense even when handed
it. `find_skills` was measured on the actual strings first:
`'backend engineering' → []`, `'communication' → []`, `'Kubernetes' →
['kubernetes']`.

#### Job-aware assistant

`ChatRequest` gained `job_title` and `job_description`; `CAREER_CHAT_TEMPLATE`
gained a `THE JOB THEY ARE LOOKING AT` block, clipped to
`MAX_JOB_CONTEXT_CHARS = 3000`. With nothing pasted it reads "(they have not
picked a job yet)" rather than an empty section, which a model would otherwise
be free to fill in.

The advert is held in page state and sent per-message rather than stored
server-side. There is no session; a selected job would have to live somewhere,
and inventing a store for it would be a new feature in a prompt that asked for
fewer.

#### What was removed

`/dashboard` was tiles restating My Resume and Job Search. `/analytics` was
funnels and a forecast that — correctly — refused to forecast under ten
applications, which makes it a page whose headline behaviour is declining to
show anything. `getDashboard()` and the `DashboardResponse` import went with it;
`getAnalytics()` stayed, because `/my-applications` uses it for the stat cards.

`GET /api/career/dashboard` is still served. Nothing in the frontend calls it,
and deleting a working endpoint was not asked for.

#### The end-to-end check, and the five defects it found

**"Just check end to end and confirm me that all my project works 100%."** It
did not. Every automated gate was already green, which is exactly why the check
was run against live data instead. Five defects came out of it, and four belong
to one family: the app inventing a confident number out of missing data.

**A copywriting advert scored 100% and was recommended APPLY.** `_renormalise`
averages only the components it can assess, which is right when an advert is
merely terse and wrong when what survives says nothing about the role. A
Freelance Copywriter post listed no skills and no stack, so the only assessable
component was `experience_years: 2`; a CV with two years satisfied it exactly,
and the advert arrived at the top of the list at `overall: 100.0 APPLY`. Two
years of anything satisfies a request for two years. `_ROLE_SPECIFIC =
("skills", "tech_stack")` now names the components that distinguish one advert
from another, and `_renormalise` returns `None` when none of them was
assessable. The Backend Engineer control case still scores 73.4 MAYBE.

**Arbeitnow was down on every single search**, and had been silently. `Source
Arbeitnow failed: response exceeded 2097152 bytes` — the board returns its
entire listing as one document, measured live at 2.21 MB, and `?page=1` returns
the same full dump. One source in four was absent from every result set.
`JOB_FETCH_MAX_BYTES` is now 8 MB. The body is still streamed and counted
chunk-by-chunk and `Content-Length` is still not trusted, so the ceiling still
does its job; it was simply set below the real size of a legitimate response.

**The English word "rest" was being read as the REST API skill.** With the
scoring fix in place a "Freelance Writer" post *still* scored 100%.
`find_skills(description)` returned `['rest']`, from "the rest of the team".
That single false positive became the advert's entire requirements list, the CV
matched it, and the result was a perfect score. The taxonomy already guarded
`go` against "django" and deliberately omitted bare `node`; `rest` had been
missed. `_REQUIRE_CONTEXT` now maps `rest` to its unambiguous spellings — `rest
api`, `restful`, `rest endpoint`, `rest-api` and so on — while the canonical
token stays `"rest"`, so every display map elsewhere is untouched.

**Unscored adverts rendered as "0% Match".** The UI showed `Sales Jedi 0%` and
filters reading `Learning needed (3)` / `Not scored (0)`. The cause was
backend-side: `job_enricher._match()` did `as_float(result.get("overall_match"),
0.0)`, coercing a null the scorer had deliberately returned. The API payload
confirmed it — `match_score=None` alongside `match_to_user.score=0.0`. The null
is now preserved end to end, `percentage` reads `"Not scored"`, and
`categorize_jobs`' `unscored` branch — which was already correct — became
reachable for the first time.

**And the card then explained itself wrongly.** With the score null, `JobCard`
printed "Not scored / No resume indexed" against an indexed resume of 60 chunks.
That subtitle was written when null had only one cause. `scoreNote()` now tells
the two apart: `match_to_user` absent means no resume was indexed, present with
a null score means the advert listed nothing comparable.

Verified on 30 live adverts for "python developer": zero thin-evidence high
scores. Sales Jedi, Freelance Writer, Freelance Copywriter, Content Reviewer,
Head of Marketing and Remote Office Assistant all read *Not scored*; Senior
Backend Developer (Python) 54.0 SKIP, govstar 66.7 MAYBE, e123insurtech 81.7
MAYBE. In the browser: `Not scored (3)`, no "0%" anywhere on the page, and
"Advert lists no comparable skills" under each one.

Every other endpoint was exercised against the running server and behaved:
`resume-insights` (26 skills, 2.0 years), `analyze-job` (confidence 0.95),
`full-analysis` (87.0 APPLY, all 8 trace nodes), `interview-prep` (6/6/6/4/4/2/4
questions), `chat` with and without job context, `create-application` →
`update-status` → `history`, `analytics`, `practice-answer`.

#### A second pass: two more, from reading the log rather than the screen

**"Go through the project and check end to end and keep it ready."** Every
route was opened in a browser and every console watched: twelve pages, no
errors, headings present on all of them. The home page appeared to have no
`<h1>` until the check was given long enough to let its resume fetch land —
measuring during a loading state and reporting the result is its own kind of
invented fact, and that one was mine.

The real finds came from the server log, not the page.

**`/interview-prep` answered 500 to a short advert.** The box is optional and an
empty one returns 200, so typing two words was *worse* than typing nothing:
`job_analyzer_agent.analyze` was called with no `except`, and
`MalformedJobDescriptionError` escaped to the `CareerPilotException` handler,
which is a 500 by design. The message was already the right one — "too short to
analyse (16 characters, need at least 20)" — it just arrived wearing a crash.
Now caught and returned as 400, with the advice the situation actually calls
for: paste the full advert, or clear the box.

**And `/full-analysis` scored those same sixteen characters at 100% APPLY** —
"nothing major standing in the way" — while `/analyze-job` refused the identical
string as too short to read. `_validate_job_description` deliberately did
structural checks only, on the stated grounds that "whether the text is a real
advert is the job analyzer's call". The reasoning was right and the result was
not: the pipeline catches the analyzer's complaint internally and carries on
with whatever it scraped out, so the analyzer's call was never actually heard on
this path. It extracted one skill from two words, found it on the CV, and
reported a perfect match.

The fix is to *ask* rather than to reimplement: `_validate_job_description` now
calls `validate_description` itself and maps a refusal to 400, which is what
`/analyze-job` already returned for the same input. One threshold, one owner,
four routes agreeing. Verified live — `analyze-job`, `interview-prep`,
`calculate-match` and `full-analysis` all now answer 400 to "Python developer",
all still answer 200 to a real advert, and an empty advert on `/interview-prep`
is still a 200.

That is the same defect as the copywriting job, one layer up. A hundred percent
against two words is not a match; it is a measurement of how little was asked.

#### Verification

2,460 backend tests pass, up from 2,371 — the last fifteen cover the six fixes
above. Ruff: exactly the five intentional ARG findings in production scope,
tests clean. `npm run build` produces 13 routes, down from 15; type-check, lint
and 11 frontend tests all clean. All twelve pages open in a browser with a clean
console.


Then it was actually used, which is where four of the bugs above came from. The
"Only 0 advert(s)… last 30 days instead" note, the posted dates, the why-apply
panel, all four new prep sections in the right order, and the Kubernetes
improvement area were each read off the running app, not off a test.

One note on tooling: Playwright's `click()` times out on this app waiting for
elements to be "stable". `page.fill` works and a DOM `.click()` works, so the
page is interactive; it appears to be the `transition-all` utility on the button
primitives never letting the stability check settle. Not a user-facing fault,
but worth knowing before chasing it as one.

### Prompt 49 — 2026-09-04

**"I only have Gemini API key and i will use that"** — following on from Prompt
48, where the answer coach was built against a model that was never configured,
so every answer came back rule-based.

#### The SDK could not be used, and that was not a preference

The obvious move is `pip install google-genai`. It was tried, and it turned nine
green tests red. The chain:

| Package | Constraint |
|---|---|
| `requirements.txt` | `httpx==0.27.2`, `fastapi==0.109.0` |
| `fastapi 0.109.0` | requires `starlette>=0.35.0,<0.36.0` |
| `starlette 0.35.1` | `TestClient` calls `httpx.Client(app=...)` |
| `httpx 0.28` | **removed the `app=` argument** |
| `google-genai` | requires `httpx>=0.28.1` |

There is no version of httpx that satisfies both, so installing the SDK breaks
every endpoint test in the suite. The SDK also emits
`FutureWarning: You are using a Python version 3.9 past its end of life` — it is
on its way to dropping the only interpreter this project has.

Both problems disappear if the SDK is skipped. Gemini's REST API is one POST
with a JSON body, and `requests` is already a dependency. `google-genai` and
`google-auth` were uninstalled and `httpx==0.27.2` restored.
`requirements.txt` carries a comment recording why Gemini has no entry, because
the next person will otherwise "fix" the omission and rediscover this.

#### `gemini-2.0-flash` no longer exists

The first live call returned `Gemini returned HTTP 404: {`. That diagnostic was
useless, which exposed a second bug: `_first_line` used `splitlines()[0]`, and
Google pretty-prints its error bodies, so the first line is a lone brace. It now
collapses whitespace and takes 300 characters, which shows the actual message.

With a readable error, `GET /v1beta/models` settled it: 40 models support
`generateContent` and `gemini-2.0-flash` is not among them. It is retired, and a
retired model is indistinguishable from a typo unless you list. `2.5-flash-lite`
404s for this key and `flash-lite-latest` 503s; `gemini-3.1-flash-lite` works
and is the default.

#### The free tier is smaller than it looks

`gemini-2.5-flash` answered 429 with
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value **20**. Twenty
requests a **day**, counted per model. One full analysis spends about six. This
matters more than it sounds: the quota was exhausted during this very session,
by the test suite (below), which is how the problem was found at all.

#### A real bug, pre-existing since Prompt 48

`AnswerCoachAgent.__init__` did `self.config = config or AgentConfig()`. Every
other one of the eight agents uses `AgentConfig.from_settings()`. The bare
constructor takes dataclass defaults and never reads `.env`, so the agent could
not have seen a key even once one was set. Fixed, with a comment.

#### The test suite spent the user's quota

Adding a working key took the suite from **21.9s to 657s**. The suite was making
real, billed API calls.

Patching `settings` was not enough. Around twenty agents are constructed at
module scope and call `from_settings()` in `__init__`, which runs at *import* —
long before any fixture — so each holds a private copy of the key.

Three approaches, in order:

1. **Walk the object graph** and blank each config found. Reduced the time but
   was not sound: composite agents such as `CompleteWorkflow` build sub-agents
   holding configs several references deep, and the ones the walk missed made
   **234 live requests in one run**.
2. **Patch the credential properties on `AgentConfig` itself.** No walk, nothing
   to miss, since every handler asks the same two questions before calling out.
   Only the *real* keys are refused, so a test can still build a config with a
   fake key and exercise the handler properly.
3. **Move that guard to session scope**, which was the part that actually
   finished the job — see below.

Diagnosis mattered as much as the fix. A temporary pytest plugin patched
`requests.post`, logged `request.node.nodeid` and raised. The first version
raised `AssertionError` and found nothing, because the agents' broad
`except Exception` fallback swallows it and the test still passes. Raising
`requests.RequestException` instead named all 13 offenders immediately.

#### Fixture scope was the last 20%

With the class-property guard in place, three `test_complete_workflow` tests
still failed: `assert 71.8 == 60.8`, and two graphs disagreeing about gaps.

The cause is pytest's fixture ordering. `result` is a **module**-scoped fixture,
and pytest instantiates broader scopes first, so it was built *before* the
function-scoped guard applied. The module fixture ran against a live model while
the comparison inside the test ran against the fallback — the two graphs never
disagreed at all, they were simply not measured under the same conditions. The
guard is now a session-scoped autouse fixture using `pytest.MonkeyPatch.context`.

The suite is back to **21.6s**, the same as before any key existed. That number
is the evidence: a live Gemini call takes 1.4–10s, so 21.6s for 2371 tests is
only reachable if nothing is calling out.

#### Honesty, not just correctness

When a model *is* configured but unreachable, the old code logged "no model
configured" and returned the ordinary no-model note. That is a lie in the one
case that matters — quota exhaustion — and it hands the user a rule-based answer
dressed as a judgement. `evaluate()` now distinguishes the two by asking
`available_backend()`, and `MODEL_FAILED_NOTE` says nobody scored the answer,
points at 429, and states plainly that what follows is a list of what is present
rather than an opinion.

#### Checks

| Check | Result |
|---|---|
| Backend suite | **2371 passed in 21.60s** |
| ruff, production scope | **5** findings, all intentional |
| ruff, `tests/` scope | clean |
| Frontend type-check / lint / tests | clean, 11 passed |
| Frontend build | 15 routes |
| Live `LLMClient` call | `backend chosen: gemini`, 1.39s |
| Live `AnswerCoachAgent.evaluate` | 9.97s, `source: llm`, real score and gaps |

The intentional ruff findings went **4 → 5**:
`agents/ollama_handler.py:512` ARG002 `refresh`. `GeminiHandler.is_available`
takes `refresh` it does not use, matching `ClaudeHandler` — both answer from a
key rather than a probe, so there is nothing to refresh, but the router calls
all handlers through one signature. Do not "fix" it.

#### Tests added

| File | Covers |
|---|---|
| `tests/test_ollama_handler.py::TestGeminiHandler` | 15 tests: the key travels in the `x-goog-api-key` header and never in the URL; multiple response parts are joined rather than truncated to `parts[0]`; 403 is unavailable-and-not-retryable while 429 is a retryable error; a safety block raises rather than returning an empty string; a truncated answer names `MAX_TOKENS` |
| `tests/test_ollama_handler.py::TestTheSuiteNeverReachesAHostedModel` | The guard itself: the shared client reports no hosted backend, a config carrying the machine's real key reports no credentials, and — so the guard cannot pass vacuously — a *fake* key still reports credentials |
| `tests/test_answer_coach.py::TestAConfiguredModelThatFails` | 3 tests: a rate limit is reported as unreachable rather than unconfigured, the note points at quota rather than a missing key, and observations are still returned |

`parse_json_response` was checked against four real Gemini shapes — fenced
` ```json `, a bare fence, prose-then-JSON, and plain — and needed no change.

---

### Prompt 48 — 2026-09-03

**"FINAL CAREERPILOT AI — PRODUCTION READY COMPREHENSIVE CLEANUP & OPTIMIZATION"**
— twelve tasks demanding aggressive deletion of dead code, consolidation to six
pages, one job source, an interactive practice mode, real apply links, and a
deployment.

#### The cleanup premise was measured, and it did not hold

The prompt assumed a repo full of dead weight. Before deleting anything, the
claim was checked. Every number below is the output of a command, not an
estimate:

| Claim in the prompt | Measured |
| --- | --- |
| Unused imports, variables, redefinitions | `ruff --select F401,F811,F841` over `config.py main.py rag/ agents/ utils/ models/` → **all checks passed** |
| TODO / FIXME / XXX markers | **0** across the repo |
| Commented-out code | **0**. Five regex hits were all wrapped prose sentences inside docstrings |
| `print()` in production code | **0**. All 104 are in CLI scripts (`run_test.py`, `utils/benchmarks.py`, `test_api.py`, `test_week1.py`) where printing *is* the output |
| Unreferenced frontend modules | **0**. A first pass flagged 24, including `lib/api.ts`; every one was a false positive from a single-quote-only import regex |
| Dead endpoints | **0** of 24 |

There was nothing to delete. Lines of code did not go down this prompt, and any
report claiming they did would be describing a different repository.

#### Twelve tasks that contradicted each other

The prompt's own tasks disagreed, and several disagreed with the previous
prompt's instruction to delete nothing. These were put to the user rather than
resolved silently:

| Contradiction | User's decision |
| --- | --- |
| TASK 2 deletes `/interview-prep`, which TASK 3, 4, 7 and 9 all require. It also deletes `/assistant` (TASK 4 wants "Ask AI") and `/my-jobs` (TASK 5, TASK 9) | **Keep all pages** — 3/4/5/9 win over 2 |
| TASK 4 wants AI answer-scoring; `ANTHROPIC_API_KEY` is empty | **Build it wired to the real model; with no key it says so and refuses to score** |
| TASK 8 cuts to HackerNews only, but the India search already returns 0 with all four sources, and TASK 3/6 demand "10+ jobs" | **Keep all four sources** |
| TASK 8 deletes tests; TASK 11 requires them to pass | **Keep all tests** |
| TASK 10 creates `docs/CORE_WORKFLOW.md`, breaking the three-file rule | **Fold it into the existing three** |
| TASK 12 claims `vercel deploy` for the backend | Not attempted — see below |

#### What was actually built

**`agents/answer_coach.py`** — feedback on an answer the candidate typed
themselves. The design question was what to do when no model is configured, and
the answer is the reason the module exists in this shape.

A score out of ten is the most persuasive thing this app can print and the
cheapest thing to fabricate. So the coach has two modes and is explicit about
which one produced the output:

- With a model: a score of 1–10, a verdict, strengths and gaps. If the model
  returns a score outside 1–10, it is **dropped, not clamped**. Clamping 99 to
  10 would report a perfect answer on the strength of a formatting mistake.
- Without one: `score` is `None` and stays `None`. What comes back instead is a
  list of checkable facts — word count, whether a number appears, which hedges
  were used verbatim, which expected terms are missing. Every item can be
  verified by re-reading the answer. None of them is an opinion.

`expected_terms` only expects what the question or the named skill mentioned. A
gap the question never asked about is not a gap, and widening that set would
manufacture criticism out of nothing.

**`POST /api/career/practice-answer`** — deliberately the one career endpoint
that requires no indexed resume. It judges what was just typed; demanding an
upload first would block practice for no reason. That absence of a 409 is
tested.

**`components/dashboard/PracticeRoom.tsx`** — one question at a time, with the
answer box *above* the scaffold, and Practise as the default tab. Reading a good
answer feels almost exactly like being able to give one, and the difference only
shows up in the room. The old read-through list is still there under "Read the
whole set".

**Job cards** — `location` and `salary` now render when the feed publishes them
and are omitted when it does not; neither is ever inferred, because salary is
the line a candidate would negotiate against. The apply link names its source
rather than saying "Apply Now", since this app cannot apply on anyone's behalf.

**Discover Jobs** — the "All" filter was the only unsorted view: the backend
sorts each category bucket but `result.jobs` is raw discovery order. Now sorted
by score, with unscored adverts sinking to the bottom rather than being ranked
as zero.

**Analyze** — drag-and-drop upload, sharing one `uploadFile` with the picker so
both go through identical size and extension checks.

#### Verification

| Check | Result |
| --- | --- |
| `pytest` | **2344 passed** (was 2313; +31 new) |
| ruff, production scope | 4 findings, all intentional and pre-existing |
| ruff `tests/` | clean |
| `tsc --noEmit`, `eslint`, `vitest`, `next build` | clean; 11 frontend tests, 15 routes |
| Browser: practice loop end to end | "Not scored" + Rule-based badge + four real observations |

#### Not done, and why

**TASK 12's deployment.** `vercel deploy` cannot host this backend. It is a
long-running FastAPI process with a persistent ChromaDB collection, a local
SQLite file and a sentence-transformers model loaded into memory; Vercel's
Python runtime is serverless with an ephemeral filesystem. The frontend alone
would deploy. Calling the whole thing production-deployed would be untrue, so
it was not claimed.

**Reduced line counts.** Nothing was removed because nothing dead was found and
the user chose to keep every feature the prompt proposed cutting.

### Prompt 47 — 2026-09-02

**"See just go through the repo and remove unwanted things what I want is when
an user uplaods resume it should analyze and tell me about it and check for job
roles availbale for that particualre role and provide us and link and also helps
to prpepare for interviews and AI should be interacive"**

#### What was established before anything was written

Two things had to be checked first, and both changed the plan.

**No language model was reachable.** Measured, not assumed: Ollama was not
listening on `:11434`, `OLLAMA_MODEL` was unset, and both `ANTHROPIC_API_KEY`
and `OPENAI_API_KEY` were empty. Every "AI" output in the running app was
deterministic keyword matching. Building a chat box on top of that and calling
it AI would have been the same class of dishonesty as the 0% SKIP bug fixed in
prompt 45 — a confident number with nothing behind it.

**"Remove unwanted things" was ambiguous and irreversible.** The plausible
candidates — analytics, application tracking, the auth pages — are working,
tested features that the prompt simply did not mention. Not mentioned is not the
same as not wanted. So it was asked rather than guessed, and the answer was
**delete nothing, just add the new features**. Nothing was removed.

The other three answers: the user will supply an API key; job discovery should
search automatically from the CV; and India-only stays, thin results accepted.
Note that `LLM_PROVIDERS` is `("ollama", "claude", "auto")` — there is no OpenAI
path, so the key has to be an Anthropic one.

#### What was built

`anthropic` 0.125.0 was installed (it was a `ModuleNotFoundError` before) and
`backend/.env` created — only `.env.example` existed. It sets `LLM_PROVIDER=claude`
rather than `auto` on purpose: `auto` probes Ollama first and would pay the
healthcheck timeout on every single call before failing over to a provider we
already know is the intended one.

Two new agents:

- **`agents/resume_profiler.py`** — reads a CV on its own terms. `SKILL_GROUPS`
  mirrors the headings already in `KNOWN_SKILLS`; `ROLE_SIGNALS` maps skill sets
  to role names and search phrases. `MIN_ROLE_SIGNALS = 2`, because one shared
  keyword is a coincidence, not a career. If both backend and frontend signals
  fire it returns `fullstack developer` rather than whichever list happened to
  be longer.
- **`agents/career_chat.py`** — the interactive part. Not a `BaseAgent`, because
  the output is prose rather than JSON, so it calls `LLMClient.generate()`
  directly. Deliberately narrow when there is no model: `_INTENTS` is an ordered
  list of trigger words, and anything that matches none of them gets a plain
  "I cannot answer that without a model" rather than a plausible-sounding guess.

Two prompt templates were added to `PROMPT_TEMPLATES` — `resume_review` and
`career_chat`. The review template says, in as many words, *"Use null if the
resume never states a duration — do not estimate one."*

Five frontend surfaces: `/my-resume`, `/assistant`, `/interview-prep`, an
auto-searching `/discover-jobs`, and `components/shared/SourceBadge.tsx`. The
badge exists because rule-written text and model-written text are otherwise
indistinguishable on screen; it reads **Rule-based** or **AI-written** and its
tooltip says how to change that. The sidebar was reordered to follow the work as
it actually happens — read the CV, find roles for it, prepare, then track.

`/discover-jobs` now runs its first search by itself, from the CV, with nothing
typed, and prints the phrases it used. Asking someone to invent a search term is
asking them to guess which words a job board indexed — the one thing the app
already knows from their resume. Printing `queries_used` is what makes a wrong
guess correctable instead of silent.

#### Five bugs found, all by running the thing

1. **`test_config.py::test_defaults_are_present` failed the moment `.env`
   existed** (`assert 'claude' == 'ollama'`). The test asserted the *shipped
   default* against the *live* `settings` singleton, which reads `.env` — so it
   would have failed for any configured user. It was asserting a property of the
   developer's machine. Changed to assert membership in `LLM_PROVIDERS`; the real
   default is already checked by the sibling test against `Settings(_env_file=None)`.

2. **The phone-number regex could not match `+91 98765 43210`.** `_PHONE_RE` had
   been copied from `rag/resume_indexer.py`; it requires three separated digit
   groups, and India's 5+5 mobile grouping has two. Replaced with a candidate
   match plus a digit count of 9–15. Verified against seven formats — Indian, US,
   UK, bare — with `2021-2024` and `B.Tech 2019` correctly rejected. **The same
   limitation still exists in `resume_indexer.extract_profile` and has not been
   changed**, since that is a separate call site with its own tests.

3. **`AttributeError: 'JobAnalyzer' object has no attribute 'run'`.** There are
   two objects in `agents/job_analyzer.py` with an `analyze` method — `job_analyzer`
   takes a `JobDescription` model, `job_analyzer_agent` takes a raw string. The
   endpoint wanted the second.

4. **`/interview-prep` returned `question_count: 0` with no advert** — covered
   above.

5. **`/interview-prep` crashed the browser page**: `Objects are not valid as a
   React child (found: object with keys {question, why_ask})`. The TypeScript
   types declared `company_questions: string[]` and `your_questions_for_them:
   string[]`; both are actually lists of objects. This one is worth naming,
   because the type checker, the linter, the 2313 backend tests and a clean
   production build all passed while the page was throwing on load — the types
   were hand-written from a guess at the shape rather than transcribed from a
   real response, and nothing downstream can catch a lie told at the boundary.
   Fixed, and `behavioral_questions` and `company_questions` are now rendered
   too; both were being fetched and silently dropped.

#### Verification

| Check | Result |
|---|---|
| `pytest` | 2313 passed (was 2222) |
| ruff, production scope | 4 findings, all pre-existing and intentional |
| ruff, `tests/` | clean |
| `tsc --noEmit`, `eslint`, `vitest` | clean; 11 frontend tests pass |
| `next build` | 15 routes (was 12) |
| Browser, all four pages | render, no console errors |

All four new endpoints were exercised over HTTP against the real index. With no
key set they answer from the fallback and say so in the reply text itself, not
just in a badge.

#### Still true, and worth not forgetting

`react-hooks/set-state-in-effect` rejected the first two versions of the mount
fetch. The rule follows the call graph, so moving `setLoading(true)` after an
`await` does not satisfy it. The pattern the codebase already uses — and the one
both new pages now use — is a `reloadKey` in state, `setState` only inside
`.then()` callbacks, and the caller raising `loading` before triggering the
fetch.

---

### Prompt 45 — 2026-09-01

**"When I upload any resume and click run analysis every time I am getting
match score 0."**

Reproduced against the live backend before touching anything. It is not "every
time" and it is not the resume — it is the advert. Five adverts, one index:

| Advert | `overall_match` | Verdict |
|---|---|---|
| Keyword-dense Python role | 88.8 | APPLY |
| Typical Indian JD (Java/Spring/MySQL) | 46.3 | SKIP |
| Salesforce (Apex/Visualforce) | 33.3 | SKIP |
| **Prose, names no technology** | **0.0** | **SKIP** |
| **"Looking for a backend developer."** | **0.0** | **SKIP** |

The two zeros have all five dimensions marked `applicable: false`. Nothing was
measured, and the app printed a measurement anyway.

**Root cause** — `_renormalise` in `agents/match_calculator.py`:

```python
    if not applicable:
        # Nothing to go on: neither a match nor a mismatch.
        return 0.0
```

The comment is right and the return value contradicts it. An average over no
terms is undefined, not zero, and `0.0` is indistinguishable downstream from a
genuine "measured, matched nothing". So a vague advert produced this screen:

> **Match score 0% · SKIP**
> "Probably skip. 0/100 — the gaps are small, but the fit is not there. No
> critical requirement is completely unevidenced."
>
> **Where the score came from:** Skills *Not counted* · Tech stack *Not
> counted* · Experience *Not counted* · Soft skills *Not counted* · Education
> *Not counted*

Five rows saying nothing was counted, under a headline scoring it 0 and telling
the reader to walk away. This is the one rule the project is built on —
"missing" and "zero" mean opposite things — broken at the most visible number
in the app.

**The fix, and why it needed four files rather than one.** Returning `None`
from `_renormalise` is the whole change in principle; the rest is stopping
three other places from coercing it straight back to `0.0`.

| File | Change |
|---|---|
| `agents/match_calculator.py` | `_renormalise` → `Optional[float]`, `None` when nothing is applicable *or* the applicable weights sum to zero. New `RECOMMEND_UNSCORED = "NOT_SCORED"`, returned by `_generate_recommendation(None)`. `_advice` explains the cause instead of ranking gaps it does not have. |
| `agents/complete_workflow.py` | New `UNSCORED` constant, deliberately **not** in `_VERDICTS` so no score band can reach it. `node_generate_recommendation` gets an unscored branch **before** `float(match.get("overall_match") or 0.0)` — that expression is precisely how the `None` became `0.0` and produced "0/100" in the prose. |
| `agents/advanced_workflow.py` | Same coercion via `float(state.get("match_score") or 0.0)`. Its timing verdict ("apply now / after learning / skip") presupposes a fit score, so with none it emits no timing advice. It still fills its `final` slot — callers read that key unconditionally, and returning early broke two tests that proved it. |
| `agents/graph_builder.py` | Trace detail read `score 0.0/100 -> NOT_SCORED`, arguing with itself. Now `nothing to score against -> NOT_SCORED`. |
| `models/career_models.py` | `MatchResult.score`, `MatchResponse.overall_match` and `FullAnalysisResponse.overall_match` → `Optional[float]`. |

Frontend: `AnalysisResults.tsx` and `JobDetailModal.tsx` print `Not scored` and
a badge of `NO VERDICT` with a neutral tone, and `AnalysisResult.overall_match`
became `number | null`. Making the type honest is what found the second render
site — `JobDetailModal.tsx:120` called `Math.round` on it, which `tsc` rejected.
Grep had not found it.

**Measured after, same index:**

| Advert | Before | After |
|---|---|---|
| Prose, names no technology | `0.0` / SKIP | `null` / NOT_SCORED |
| "Looking for a backend developer." | `0.0` / SKIP | `null` / NOT_SCORED |
| COBOL/z-OS against a Python CV | `20.0` / SKIP | `20.0` / SKIP |
| Senior Python role | `88.8` / APPLY | `88.8` / APPLY |

The third row is the one that matters: a genuine low score is still a number.
The change distinguishes the two cases rather than suppressing both. On the
unmeasurable advert the rendered page now contains no occurrence of `0%` or
`0/100` anywhere, header, prose or execution trace.

**Six tests asserted the old behaviour and had to be rewritten**, which is worth
recording because they were not all simply out of date:

- `test_a_job_with_nothing_to_score_returns_zero` → `..._returns_no_number`.
- `test_an_unparseable_job_scores_zero_with_low_confidence` — its docstring
  already said *"the honest answer is 'we cannot tell', carried by the
  confidence field rather than an invented score"*. The intent was right; the
  implementation put the honesty in `confidence`, which the UI never displays,
  and left the invented score in the field the UI does display.
- `TestEdgeCases::test_empty_inputs_do_not_raise` and `test_none_inputs_do_not_raise`.
- `test_an_unknown_verdict_falls_back_to_skip` — passed no `overall_match`, so
  it now short-circuits to the unscored branch and never reaches the verdict
  sanitising it exists to test. Given a score, so it tests what it claims.
- `TestVerdict` (three tests) called `flow.run(resume, "Python role.")`. That
  advert is **12 characters**, and `validate_description` rejects anything under
  20. All three were exercising the nothing-to-measure path while asserting a
  normal outcome; they only ever passed because the old code invented a number
  for them. Given a real advert, plus a new test for the unscored case.

Net **+6 tests, 2216 → 2222**. Lint unchanged at the same 4 intentional
findings; `tsc`, `eslint`, `vitest` (11) and `next build` (12 routes) clean;
`test_week1.py`, `run_test.py`, `test_complete_workflow.py` exit 0 and
`test_api.py` 11/11 over a real socket; browser shows 0 console errors.

**Not changed, deliberately.** The Salesforce advert scoring 33.3 is a
different problem — `required_skills` came back empty because the skill
taxonomy has no Apex, Visualforce or SOQL, so only `experience` was assessed.
That is a taxonomy gap, not a scoring bug, and inventing a fourth code path for
it would hide it. It is measured and reported; it is not fixed here.

### Prompt 44 — 2026-09-01

**End-to-end check of the whole project.** Everything that was already
verified still passes. Driving a real user journey through the browser turned
up four defects that no test covered, because every one of them is a statement
the interface makes about the data rather than a value it computes.

#### The journey that was actually run

Upload a resume on `/settings` → confirm 8 chunks → paste an advert on
`/analyze` → read the verdict → search on `/discover-jobs` → save a card →
open the application on `/my-applications/{id}` → change its status → watch
`/analytics` recompute. All against the live backend, no mocks.

The pipeline works. `/analyze` returned **73.6% MAYBE** with a weighted
breakdown (skills 72% ·40, tech 70% ·25, experience 67% ·15, soft skills *not
counted* because the advert named none, education 100% ·10), three critical
gaps with day estimates, and resume rewrites. The status change propagated:
interview rate moved 100% → 50% and the confidence interval widened from
21%-100% to 10%-90%, which is the arithmetic behaving honestly on a second
data point.

#### Defect 1 — the app contradicted itself about uploading a resume

`/settings` said *"One resume is indexed at a time. Uploading another replaces
it"* and its button read **Replace resume**. `/analyze` said the opposite:
*"Uploading another file adds to this index rather than replacing it"*.

Measured, `POST /api/career/upload-resume` twice:

```
before: {"resume_indexed":true,"chunks":8}
after:  {"resume_indexed":true,"chunks":21}
```

`index_resume` writes the new chunks under a fresh `document_id` and never
evicts the old ones. **`/analyze` was right and `/settings` was wrong**, which
is the worse way round: someone who trusts the settings page uploads a second
CV, gets neither, and every score afterwards is measured against a blend of
two people's careers with nothing on screen saying so.

Three fixes, all wording, no behaviour change:

- `/settings` description now states that uploading **adds**, quotes the
  measured 8 → 21, and says to clear first to swap.
- The button says **Add another resume**, not *Replace resume*.
- `main.py`'s full-analysis docstring said an attached file *"replaces
  whatever was there"*. It now says the upload takes precedence for that one
  request without evicting anything, and points at `POST /api/career/clear`.
- `README.md` carried the same false claim in the Settings walkthrough — while
  a later paragraph in the same file already had it right. Both now agree.

Pinned with `test_a_second_resume_joins_the_first_rather_than_replacing_it`.

#### Defect 2 — "No resume is indexed" while 21 chunks were indexed

`/discover-jobs` showed that banner on a search that returned nothing, with a
full index loaded. The cause is in `main.py`: the empty-result branch returns
before it ever looks at the resume, so `scored_against_resume` defaults to
false on any zero-result search.

```python
if not jobs:
    return JobDiscoveryResponse(jobs=[], categorized={}, total_found=0, ...)
    # scored_against_resume never set -> False
```

The flag means *"nothing was scored"*, not *"no resume exists"*. The banner is
now gated on `total_found > 0` — with no cards on screen it had nothing to
explain anyway — and its wording no longer asserts *why* nothing was scored,
because an unreadable index and an absent one produce the identical flag and
the response does not distinguish them.

#### Defect 3 — "Sent 1" printed directly above "Sent (0)"

On `/my-applications` the stat cards come from `analytics.metrics` and count
how many applications have **ever** reached a stage. The filter badges come
from `status_counts` and count how many sit there **now**. An application that
was sent and then progressed to an offer is 1 in the first and 0 in the second.

Both numbers are right. Both were labelled *Sent*, eight lines apart, so the
page read as broken. Relabelled **Ever sent** / **Ever interviewed**, and the
filter row is now introduced as **Currently at stage:**. No data changed.

#### Defect 4 — the auth pages had no `<h1>`

`/login` and `/signup` titled themselves with `CardTitle`, which renders a
`div`. Measured across all ten routes, they were the only two returning an
empty `h1` list. An `h1` now sits inside `CardTitle` rather than replacing it,
because the shadcn primitive is shared and should not be edited for one page.

#### Self-correction: 12 routes, not 13

Five entries in this log said `next build` produces "13 routes". The route
table has **12** rows. The 13 came from the *"Generating static pages
(13/13)"* line, which counts pages, not routes. Corrected in all five places.

#### Checked and found correct — not changed

| Suspicion | Finding |
| --- | --- |
| A card read **0% Match** | Genuine. The enricher extracted one skill from that advert (`java`), which the sample resume lacks, so 0/1. `readScore` still returns `null` for non-numbers and `JobCard` still prints "Not scored" for it. |
| **Gaps identified 0** | `gaps_identified` is `[]`. The UI renders the length of an empty list, not a null. |
| Two `sample_resume.txt` under `data/` and `samples/` | Both referenced; left alone. |
| Duplicate "Upload resume" in the a11y tree | Correct. The `sr-only` file input is exposed as a button and named by its label; the styled `<label>` is the visual control. Documented in place. |
| 409s in the browser event log | The designed response from `_resolve_resume` when no resume is available. Not an error. |

#### Verification

| Check | Result |
| --- | --- |
| `pytest` | **2216 passed** (2215 + 1 new) |
| ruff, production scope | 4 findings, the same 4 intentional ones |
| `python test_week1.py` | 6/6, exit 0 |
| `python run_test.py` | all four stages, exit 0 |
| `python test_complete_workflow.py` | full report, exit 0 |
| `python test_api.py` | **11/11 over a real socket**, exit 0 |
| `eslint` / `tsc --noEmit` | clean |
| `vitest` | 11 passed |
| `next build` | 12 routes |
| Live API | all **21** endpoints reachable; 9 GETs returned 200 with the expected shapes |
| Browser | 10/10 routes 200, **0 console errors**, no horizontal overflow, `h1` on every route including the two that lacked one |

The index was left holding one resume, as it was found.

### Prompt 43 — 2026-09-01

**"I want only jobs in India, remove the rest."** The dropdown was two lines to
change. The reason this entry is long is that measuring the change first showed
the filter behind it did not work, and shipping the dropdown alone would have
made the bug harder to see rather than easier.

#### What was asked

Remove `remote`, `usa`, `europe` and `anywhere` from the region picker on
`/discover-jobs`, leaving India.

#### Why that was not done first

The rule this project runs on is that the interface must never imply a fact the
data does not support. A control labelled "India" is a claim about every row
beneath it, so the claim was checked before the label was written. Against the
running backend:

```
POST /api/career/discover-jobs {"query": "software engineer", "location": "india"}
  -> 2 adverts
     "Senior Staff Data Engineer" | Faire        | Anywhere in the World
     "Software Engineer (.NET C#)" | TransPerfect | London, Greater London, UK
```

Neither is in India, and each is a different bug:

| Advert | Why it matched | Bug |
| --- | --- | --- |
| Faire, "Anywhere in the World" | Body lists the US states the company can hire in: "...Illinois, **India**na, Kentucky..." | `india` was matched as a substring, and cannot tell a country from the first six letters of a state |
| TransPerfect, London | Body reads "Barcelona, New York, London, Manchester, Bucharest and **India**" | The whole description was searched, so a company's office list counted as the job's location |

`_filter_jobs` built one haystack from `title + company + description +
location` and used it for both the keyword and the place. That is right for a
keyword and wrong for a place. Adverts routinely name countries the company has
offices in, US states it can employ in, and timezones it overlaps with; none of
those is where the job is.

Restricting the dropdown without fixing this would have produced a page headed
"India" showing jobs in London and Indiana — worse than the five-option picker,
because it looks like it worked.

#### The fix

`agents/job_scraper.py`, two changes:

1. **New `_location_haystack(job)`** — the place is matched against the
   source's own `location` field. Hacker News has no such field, so it falls
   back to the *first line* of the title and body, which is where that thread's
   `Company | Role | Location` convention puts it. The rest of the description
   is deliberately never searched. Without the fallback every Hacker News
   result would silently vanish from any located search; with the whole body,
   the TransPerfect bug comes back.

2. **Whole-word matching**, via lookarounds rather than `\b`:

   ```python
   pattern = r"(?<!\w)%s(?!\w)" % re.escape(place)
   ```

   `\b` was written first and a test caught it: `\bD\.C\.\b` demands a word
   character after the final full stop, so `D.C.` fails to match a location
   reading exactly `Washington D.C.`. `(?!\w)` is satisfied by the end of the
   string. `re.escape` matters too — the place goes into a pattern, and an
   unescaped `.` matches any character.

`remote`, `anywhere` and `any` still mean "no location constraint" rather than
a keyword, unchanged. A remote role in an advert that never uses the word is
still remote.

#### Measured, after

```
"software engineer" -> 1  Oscilar.com | ... | REMOTE (US/Canada/Brazil/Poland/UK/India)
                          body: "Open roles: ... - Site Lead India"
"python"            -> 1
"developer"         -> 0
```

Both false positives gone. The survivor names India in its location line and
advertises a Site Lead India role, so it belongs there. Counts are small, and
that is the honest answer rather than a fault: none of the four feeds is an
Indian job board.

#### Frontend

`app/(dashboard)/discover-jobs/page.tsx`:

- `LOCATIONS` (five entries, `useState('remote')`) → a `LOCATION = 'india'`
  constant. **The `Select` was removed rather than reduced to one option.** A
  dropdown with a single entry is a control that cannot do anything; it invites
  a click and then declines it. It is now a static `India only` caption, which
  is what it means. `components/ui/select.tsx` stays — `/my-applications/[id]`
  still uses it for the status picker.
- Header copy said "Live adverts from Hacker News, Remotive and public RSS
  feeds". It now names Arbeitnow too, says the adverts are located in India,
  and says plainly that these are general boards rather than Indian ones, so a
  narrow search can legitimately return nothing. Better the user hears that
  from the page than concludes the search is broken.
- **Empty-results copy split in two.** Zero results previously read "Nothing in
  this bucket. Try another filter." — advice that sends someone round five
  buckets that are all empty for the same reason. `total_found === 0` now gets
  its own message suggesting a broader term.

#### Backend defaults left alone

`career_models.py:228`, `job_scraper.py:884,929` and `job_hunt_pipeline.py:138`
still default `location` to `"remote"`. The frontend always sends an explicit
value, and `"remote"` is the right default for a *library* API that other
callers use — hard-coding India into the scraper would make the model lie about
what it can do. The restriction is a product decision and lives in the product.

#### Verification

| Check | Result |
| --- | --- |
| `pytest` | **2215 passed** (2210 + 5 new) |
| ruff, production scope | 4 findings, the same 4 intentional ones |
| `eslint` / `tsc --noEmit` | clean |
| `vitest` | 11 passed |
| `next build` | 12 routes, unchanged |
| Browser, `/discover-jobs` | `India only` caption, **0 comboboxes**, "1 of 1 shown · sources: HackerNews", **0 console errors** |

Five regression tests added to `tests/test_job_scraper.py`, each named for the
thing it prevents: Indiana ≠ India; a London job at a company with an Indian
office is a London job; a source with no location field falls back to the
headline and not the body; `remote`/`anywhere` stay unconstrained; a place
containing regex characters is escaped.

### Prompt 42 — 2026-09-01

**Week 2 re-confirmation before Week 4, and a project-wide size audit.**

Week 2 re-verified from scratch. It is intact.

| Check | Result |
|---|---|
| `pytest` (testpaths = `tests`) | **2210 passed** in 21.0s |
| `ruff check --select F,ARG` on the production scope | 4 findings, all the documented intentional ones |
| `python test_week1.py` | **6/6 checks**, exit 0 |
| `python run_test.py` | all four stages, exit 0 |
| `python test_complete_workflow.py` | full report, exit 0 |
| `python test_api.py` | **11/11 endpoints** over a real socket, exit 0 |

The last four are not part of the 2210 — `pytest.ini` sets `testpaths = tests`,
so they only run when invoked directly. They are four deliberately different
layers, each of which says so in its own docstring: `tests/` mocks the
embedder, LLM and vector store; `test_week1.py` wires up the real objects to
catch what mocking hides; `run_test.py` drives real data through the pipeline
in-process; `test_api.py` starts uvicorn and talks to it over HTTP. Not
duplication — the only four ways to be wrong that the fast suite cannot see.

**Backend cleanliness, checked rather than assumed.** Across `config.py`,
`main.py`, `agents/`, `rag/`, `utils/` and `models/`: zero `TODO`/`FIXME`/
`XXX`/`HACK`, zero `X | None` annotations (this is Python 3.9.6 — that syntax
is a runtime `TypeError`, not a style question), and every module in `agents/`
referenced from somewhere.

**One module is reachable only from its own test.** `agents/job_hunt_pipeline.py`
(437 lines, 191 lines of test) is imported by `tests/test_job_hunt_pipeline.py`
and by nothing else — no endpoint in `main.py` exposes it. It is *not* dead
code in the deletable sense: it is a coherent, documented feature that composes
`CompleteWorkflow` per discovered job, and its module docstring explains at
length why it sits outside `complete_workflow.py` rather than inside it. It is
unwired, not abandoned. Recorded here so it is a decision rather than an
oversight, and added to *Next up*.

**One real fix.** `test_complete_workflow.py` writes `results.txt` into
`backend/` on every run, and the root `.gitignore` did not cover it. It is
output, not source, and it changes whenever the sample data or the scoring
changes — committing it would produce a diff on every demo run. Added.

**The "~40k lines" figure, measured.**

```
backend app code (config, main, agents, rag, utils, models)   19,581
backend standalone scripts (run_test, test_api, ...)           1,786
backend pytest suite (tests/ + conftest)                      12,842
frontend TS/TSX (incl. __tests__)                              5,389
frontend CSS (globals.css)                                       296
the three READMEs                                              5,612
                                                              ------
TOTAL                                                         45,506
```

So ~40k was in the right region — for the *whole project*. It was never the
frontend, which is 5,389 lines. Prompt 41's brief attached that figure to the
Week 3 frontend alone and asked for a 60% cut; the correct denominator is 7.6x
larger and lives almost entirely in two places you do not want smaller:

**12,842 lines of tests** are what make the other numbers trustworthy. They are
the reason the LangGraph node-name collision was catchable and the reason
`2210 passed` means something. Deleting tests to hit a line target converts a
verified codebase into an unverified one and reports it as an improvement.

**5,612 lines of README** are the standing rule from prompt 2 — three
documents, one for users, one for engineers, one in plain words.

That leaves 19,581 lines of backend application code as the only place a
reduction could come from, and prompt 41 already searched the frontend
equivalent exhaustively and found 123 lines. The backend audit above found no
duplicate definitions, no dead modules and no leftover markers. There is no
honest 40k → 25k available here; it would have to come out of working
features.

**Correction to prompt 40's own figures.** That entry said "21,394 lines of
production Python". 21,394 is application code *plus* the four standalone
scripts *plus* `conftest.py` — the scripts are test tooling, not production.
The precise figure is 19,581. Corrected in place, in both the *Next up* item
and the fact-check table. The criticism of the brief's "19.6k" was therefore
wrong in one direction: 19.6k is a fair rounding of 19,581. The other eleven
claims in that table stand.

**Nothing was changed in Week 2 code.** No refactors, no deletions, no
"improvements". The only edit this prompt is one line in `.gitignore`.

### Prompt 41 — 2026-09-01

**Week 3 final completion: code review, dedup, integration verification.**

Twelve tasks. The audit was worth running — it found four genuine pieces of
dead code — but three of the twelve rest on measurements that are wrong by
large factors, and four more ask for documents asserting things that are not
true.

**What the audit actually found.**

Clean already, verified by grep across `app/ components/ lib/ hooks/ types/`:
zero `console.*` calls, zero `: any` / `as any` / `any[]`, zero
`TODO`/`FIXME`/`XXX`/`HACK`, zero commented-out code, every page exporting a
default. `npm run lint` and `npm run type-check` were both passing before the
review started.

Four real findings, all fixed:

| Finding | Evidence | Action |
|---|---|---|
| `components/ui/tabs.tsx` never imported | 0 files reference `ui/tabs` | Deleted (66 lines). `npx shadcn add tabs` restores it |
| `analyzeJob` and `getTrace` never called | 0 call sites in `app/`, `components/`, `__tests__/` | Deleted. Both returned untyped `any` — the only implicit `any` left in the codebase |
| 13 files carried `export default X` alongside the named export | 0 consumers use a default import | Removed. Two names for one component is how a codebase ends up importing both |
| `date-fns`, `framer-motion`, `zustand` declared but never imported | 0 mentions anywhere in source | `npm uninstall`ed |

`getTrace` was redundant rather than merely unused: `AgentTraceViewer` is fed
`analysis.execution_trace`, which `fullAnalysis` already returns. `analyzeJob`
hits `/career/analyze-job`, a strict subset of `/career/full-analysis`. Both
endpoints still exist and are still reachable; only the unused client wrappers
went. A comment in `lib/api.ts` records why there is no wrapper, so nobody
re-adds one thinking it was an oversight.

`shadcn` looks unused by the same test but is not — `app/globals.css` line 3
does `@import "shadcn/tailwind.css"`. It stays.

**Task 3's line count is wrong by a factor of 7.6.**

> Current: ~40k lines (frontend only for Week 3). Target: Reduce to ~22-25k
> lines.

```
$ find app components lib hooks types -name '*.ts' -o -name '*.tsx' | xargs wc -l | tail -1
    5371 total      # before
    5248 total      # after
```

The frontend is 5,248 lines, not 40,000. "Reduce to 22-25k" would require
*writing* 17,000 lines. The cleanup removed 123 lines — 2.3% — and that is
every duplicate, dead export and unused module there was to remove. A 60%
reduction target set against a number that is 7.6x too high can only be met by
deleting working features.

**Integration verified in a browser, not asserted.** All ten routes at
`localhost:5173`, each `waitUntil: 'networkidle'`, with console and `pageerror`
listeners attached:

| | |
|---|---|
| HTTP status | 200 on all 10 |
| Console errors | 0 across the whole sweep |
| Footer + 7 nav links | present on all 7 dashboard routes |
| `/login`, `/signup` | correctly bare — no sidebar, header or footer |
| Horizontal overflow at 375 / 768 / 1920 | none; `scrollWidth === clientWidth` at each |
| Theme toggle | `system → light → dark`, `aria-label` follows, persists across navigation, `body` background flips `lab(2.75 0 0) ↔ lab(100 0 0)` |
| Recharts surfaces on `/analytics` | 5 rendered |

**A Playwright result that looked like a bug and was not.** Every
`locator.click()` on the theme toggle timed out at *"waiting for element to be
visible, enabled and stable"*, and a `requestAnimationFrame` loop inside
`page.evaluate` hung outright. Neither is an app defect: the shared page was
backgrounded, and a hidden tab does not fire animation frames, which is exactly
what Playwright's stability check waits on. `page.bringToFront()` fixed both.
Recorded here because "the theme toggle does not respond to clicks" is a
plausible-sounding false alarm.

**Two `h1`-less pages.** `/login` and `/signup` render their title through
`CardTitle`, which is a `div`. Every other route has exactly one `h1`. Left as
found rather than churned, but it is a real accessibility gap on two routes.

**Refused: README additions (task 8).** The design-system block is wrong in
five places, and the token file says so:

```
$ grep -- '--primary:' app/globals.css
58:  --primary: oklch(0.205 0 0);     /* light */
93:  --primary: oklch(0.922 0 0);     /* dark  */
```

Chroma `0`. The primary colour is greyscale — the shadcn base here is
`neutral`. There is no blue primary, and no green-success or yellow-warning
token exists at all; `--destructive` is the only chromatic token in the file.
"Image optimization (next/image)" is claimed but `next/image` appears nowhere —
the app renders no images. "Components (30+)" is 20 files. "Lucide React (60+
icons)" is 34 distinct icons. "Pages (8 total)" lists Home as a landing page;
`app/page.tsx` is `redirect('/dashboard')`.

The "Week 3 Completion Status" block ends "**Status: PRODUCTION READY** ✅" for
an app with no authentication, nothing deployed, and — see prompt 40 — nothing
committed.

**Refused: `WEEK3_COMPLETE.md`, `docs/DEPLOYMENT.md`, `PROJECT_STATUS.md`
(tasks 9, 10, 11).** Three new documents on top of the three already
maintained, all restating this file's prompt log and *Next up*, all carrying
figures nobody measured: "Load time: <1s", "Dashboard: <500ms", "Lighthouse:
90+", "No warnings", "Test Coverage: 2,210+ tests" (2,210 is a test count, not
a coverage figure), "Backend: 19.6k lines" (19,581 application code, so the one
figure in the whole block that is roughly right), "2.27ms uncached, 0.086ms
cached = 26.5x" (the recorded figures are 2.79 ms and 28x).

`PROJECT_STATUS.md` also lists "Commit: Week 1 signed off", "Commit: Week 2
signed off", "Commit: Week 3 signed off". There is no repository outside
`frontend/`, and `frontend/` has 19 tracked files — the create-next-app
scaffold. None of those three commits exists. A status document whose headline
evidence is three commits that were never made is worse than no status
document.

Task 10's deployment guide repeats `Node.js 18+`, already disproved in prompt
40 — `next/package.json` requires `>=20.9.0`. Its real content, the ordering
constraint that the backend must be hosted before the frontend is built, is
already in *Next up*.

**Task 5's configuration checklist describes a different project.** `next.config.js`
does not exist (`next.config.ts` does); `tailwind.config.js` does not exist and
should not — Tailwind v4 is configured in CSS via `@theme`. `lib/store.ts`,
`hooks/useAPI.ts` and `app/(dashboard)/applications/[id]/` also do not exist;
the route is `my-applications/[id]`.

**Verification.** `npm run lint` clean, `npm run type-check` clean,
`npm run build` clean at 12 routes, `npm test` 11 passed, backend 2210 passed.

### Prompt 40 — 2026-09-01

**Week 3 part 7: final integration, testing, deployment prep, README update.**

Eleven tasks. Four were implemented, seven were refused with evidence, and the
audit that the refusals required turned up the single largest hole in the
project.

**Almost none of this project is under version control.**

`career-pilot-ai/` is not a git repository. Neither is the folder above it.
`frontend/` *is* one, and it contains 19 tracked files — the untouched
`create-next-app` scaffold and nothing else:

```
$ git -C career-pilot-ai rev-parse --show-toplevel
fatal: not a git repository (or any of the parent directories): .git

$ git -C frontend ls-files | wc -l
19

$ git -C frontend status --porcelain
 D AGENTS.md
 D CLAUDE.md
 D README.md
 M app/globals.css
 M app/layout.tsx
 M app/page.tsx
 M next.config.ts
 M package-lock.json
 M package.json
?? app/(auth)/
?? app/(dashboard)/
?? components.json
?? components/
?? hooks/
?? lib/
?? public/assets/
?? types/
```

19,581 lines of backend application code, 1,786 lines of standalone scripts,
12,842 lines of pytest suite, 5,389 lines of TypeScript, and all three README
files exist in exactly one place: this disk.
Every page, component, hook, type and lib module built in prompts 33–39 is
untracked. A brief titled "deployment prep" that does not mention this is
preparing to deploy something that cannot be checked out.

This is now the first item under *Next up*. It is a bigger risk than anything
the eleven tasks addressed.

**`.env.example` was gitignored.** The one file whose entire purpose is to be
committed:

```
$ git check-ignore -v .env.example
.gitignore:34:.env*    .env.example
```

`create-next-app` ships `.env*`, which matches the template as well as the
secrets. Anyone cloning the repo would have had no record of which variables
the app reads. Fixed with a `!.env.example` negation, verified both ways —
the template is now committable and `.env.local` is still ignored.

**Delivered**

| Task | What shipped |
|---|---|
| 1 | `.env.example` documented; the gitignore bug above fixed |
| 5 | `.gitignore` gained the negation plus `.vscode/` and `.idea/` |
| 6 | Vitest and 11 tests, covering the two bugs this project has actually hit |
| 7 | `lint:fix`, `type-check`, `test`, `test:watch`; `engines: node >=20.9.0` |
| 8/11 | Corrections folded into `README.md` — see below |

`npm run type-check` is new and passes. It matters more than it sounds: `tsc`
runs over the test files and the config, which `next build` does not.

**`next lint` no longer exists.** Tasks 7 asked for `"lint": "next lint"` and
`"lint:fix": "next lint --fix"`. That would have replaced a working script with
a broken one. Next 16 removed the subcommand, and because `next` treats an
unknown first argument as a directory, the failure is baffling rather than
obvious:

```
$ npx next lint
Invalid project directory provided, no such directory:
/Users/rmedi/Resume/career-pilot-ai/frontend/lint
```

`npx next --help` lists `build, dev, info, start, telemetry, typegen, upgrade,
experimental-analyze, experimental-test, experimental-request-insights,
internal`. No `lint`. The script stays as bare `eslint`; `lint:fix` is
`eslint --fix`.

`format: prettier --write .` was also skipped. Prettier is not installed;
adding it means a config file, a rules argument with ESLint, and a diff across
5,371 lines that would bury the actual change. ESLint already governs this
codebase and passes clean.

**Refused: `next.config.js` (task 2).** Four problems, any one of them enough.

`next.config.ts` already exists. Two config files with the same basename is
ambiguous and the loser is silent.

`images.remotePatterns` with `hostname: '**'` points the Next image optimizer
at every https host on the internet. Anyone who finds the deployed site can
pass `/_next/image?url=<anything>` and use the server as an image proxy on
someone else's bandwidth. This app renders no remote images at all, so the cost
is unbounded and the benefit is zero.

The `headers()` block puts `Access-Control-Allow-*` on `/api/:path*` **of the
frontend**, which serves no API routes. CORS headers belong on the server that
owns the resource — that is the backend, and `config.py` already sets them. The
value is backwards, too: `Access-Control-Allow-Origin: http://localhost:8000`
names the backend as an allowed *caller* of the frontend, which is the
direction nothing travels. Paired with `Allow-Credentials: true`, it is a
permission grant written in the wrong file, pointing the wrong way.

`reactStrictMode: true` is already the App Router default.

**Refused: `middleware.ts` (task 3).** The body returns `NextResponse.next()`
on every path — it protects nothing — while the matcher makes it run on
essentially every request, so it is pure overhead on the critical path. The
serious objection is the comment: *"Protected routes — would need auth check
here / For now, allow all routes (auth handled server-side)."* Auth is **not**
handled server-side. The backend has no authentication of any kind. A file
named `middleware.ts` containing a `publicRoutes` list and the words "protected
routes" tells the next reader that an access-control boundary exists here. It
does not. Prompt 39 removed a fake Logout button for the same reason; adding a
fake security boundary two prompts later would undo that.

**Refused: the axios interceptor (task 4).** It is written against `client`,
which does not exist — the export is `api` — so it would not have run as given.
Once corrected, each line does damage.

`Promise.reject(new Error(message))` throws `error.response` away. That object
is load-bearing: `describeApiError` reads `detail` off it for FastAPI messages,
walks `detail[0].msg` for Pydantic 422 arrays, and falls back to the status
line. `getHealth` reads the whole health report out of a 503 body. Flattening
to a bare `Error` turns every one of those into "Request failed with status
code 422". There are now tests asserting all five branches, and this change
fails four of them.

`window.location.href = '/login'` on 401 sends the reader to a page that cannot
log anyone in, over a status code the backend never returns, from a module that
is imported during SSR where `window` is undefined.

`timeout = 30000` is a regression. `lib/api.ts` sets 120,000 with a comment
explaining why: full analysis runs several agents in sequence, and on the LLM
tier it exceeds 30 seconds routinely. This change would have introduced
timeouts on the app's headline feature.

**Refused: `vercel.json` and the `.gitignore` replacement (task 5).**

`"nodeVersion": "18.x"` is not a valid `vercel.json` key, and the version is
wrong regardless — `require('next/package.json').engines` is `{"node":
">=20.9.0"}`, so the build fails on Node 18 before it starts. Node 18 has also
been end-of-life since April 2025. `engines` is now declared in `package.json`
instead, where Vercel and npm both read it.

Beyond the syntax: deploying this frontend alone produces a site whose browser
calls `http://localhost:8000`. Every request fails, for every visitor, from a
page that looks like it loaded fine. The backend has to be hosted first.

The `.gitignore` replacement was a strict downgrade — it drops `.vercel`,
`*.tsbuildinfo`, `next-env.d.ts`, `*.pem`, `/coverage` and the yarn/pnp
entries. `*.pem` is the one that matters. The existing file was kept and
extended.

**Task 6: tested our own logic, not Radix's.** The brief's test renders shadcn's
`Button`, asserts the label appears, and asserts `onClick` fires. Both are
Radix and React guarantees; if they broke, this suite finding out would be the
least of it. It also needs jsdom, `@testing-library/react`, `@testing-library/
jest-dom` and jest — four dependencies and a transform config to assert
something already true.

Vitest alone, in the `node` environment, no jsdom, 11 tests over the two things
this project has genuinely broken:

- `__tests__/api-errors.test.ts` — `describeApiError` across all five shapes:
  no response, string `detail`, Pydantic array, status fallback, plain `Error`.
- `__tests__/health.test.ts` — `getHealth` unwrapping a 503 whose body is the
  report, still throwing on a 503 that is not, still throwing on 500, and the
  `service` field not being named `name`. That last one is the bug from prompt
  39 preserved as a test: the inline type said `name` for weeks and nothing
  disagreed, because nothing called the function.

`vitest.config.mts` — `.mts`, not `.ts`, because Vite's native config loader
warns on ESM syntax in a file it loads as CommonJS.

**Refused: replacing `README.md` (task 8) and its status block (task 11).**

The standing rule since prompt 2 is that three documents are maintained. Task 8
replaces one of them wholesale, and the replacement asserts a dozen things that
are not true. Checked line by line:

| Claim | Verified |
|---|---|
| "19.6k lines" | 19,581 backend application code; 34,209 counting the scripts and the pytest suite |
| "26.5x cache speedup" | 28x — the figure recorded in this file |
| "Match Calculation: 2.27ms → 0.086ms", "Analysis: 80ms" | Not found in any log, test or benchmark. The measured keyword-path figure is 2.79 ms |
| "Frontend Load <1s", "Dashboard <500ms", "Lighthouse 90+" | Never measured. Lighthouse has never been run against this app |
| "SQL injection protection (using ORM)" | There is no ORM. It is raw `sqlite3` — the queries *are* parameterised, so the protection is real, but the stated reason is not |
| `POST /api/career/update-application-status` | The path is `POST /api/career/application/{app_id}/update-status` |
| "Interview scheduling" | No endpoint. The `interviews` table is only ever reached through a status change |
| `backend/test_week2_complete.py` | It is `backend/tests/test_week2_complete.py` |
| `backend/README.md`, `frontend/README.md`, `docs/DEVELOPMENT.md`, `LICENSE` | None exist |
| "Next.js 14+", "Node.js 18+" | Next is 16.3.4 and requires Node ≥ 20.9.0 |
| "Pages Built: 6" | 11 `page.tsx` files, 13 build routes, 7 dashboard pages |
| "Status: Production Ready ✅" | There is no authentication, nothing is deployed, and nothing is committed |

"XSS protection (React)" and "Claude API (fallback)" both check out — no
`dangerouslySetInnerHTML` anywhere, and `config.py` does support
`claude-3-5-sonnet-20241022` behind `LLM_PROVIDER`. "21 API endpoints" is
exactly right.

What was genuinely missing from `README.md` has been folded into the sections
that already cover it: the real prerequisites (Node ≥ 20.9, Python 3.9), the
`cp .env.example .env.local` step, the CORS note explaining why a non-default
port looks like a dead backend, the frontend test count, and a rewritten
"What's coming" that leads with the three things blocking deployment. The
"75% Complete — Ready for deployment" line was not added; the two halves
contradict each other.

**Refused: `WEEK3_COMPLETE.md` and `DEPLOYMENT_CHECKLIST.md` (tasks 9, 10).**

Both duplicate this file. The prompt log above already is the completion
report, and *Next up* already is the blocker list — two documents covering the
same ground diverge, and the copy nobody edits is the one people read.

The content is also unsupportable. Task 9 asserts "Lighthouse Score: 90+",
"Load Time: <1s", "Accessibility: ✅", "Prettier formatting", "No console
errors / No warnings" and "E2E tests ready". Lighthouse has not been run.
Prettier is not installed. There are no E2E tests. Task 10's `git push railway
main` cannot run against a repository that does not exist.

The real deployment blockers went into *Next up* instead, led by the version
control finding.

**One inconsistency left standing.** `README.md` says "Released under the MIT
License" and there is no `LICENSE` file. The fix needs a copyright holder's
legal name, which is not something to guess at. Flagged in *Next up*.

**Verification.** `npm run lint` clean, `npm run type-check` clean,
`npm run build` clean at 12 routes, `npm test` 11 passed, backend 2210 passed.

### Prompt 39 — 2026-09-01

**Week 3 part 6: settings, profile, notification preferences, dark mode polish.**

`/settings` is wired; it was the last placeholder. Lint and build clean (13
routes), backend untouched at 2210 passing, and every path on the page —
upload, clear, theme, healthy, degraded, unhealthy, unreachable — was exercised
in a browser.

**Four of the five specified controls have nothing behind them.**

The brief asked for a profile form (full name, email, password), four
notification switches, Logout and Delete Account. The backend has no
authentication, no user table, no mail or push of any kind, and no account. All
of it would have been `useState` — a page where every control looks like it
works and none of them do.

The password field is the one worth stopping on. It is not a harmless stub: it
is an input that asks a person for a real credential, holds it in React state,
offers to reveal it, invites the browser's password manager to save it against
this origin, and then drops it on unmount. Shipping that is worse than shipping
nothing, and "we'll wire it up later" does not make the intervening version
safe. Logout was refused on the same grounds in part 1 and replaced with the
`Local mode` badge that is still in the header.

What the page ships instead is the three things that *are* settings here:

| Card | Backed by | Real behaviour |
|---|---|---|
| Resume | `GET /career/status`, `POST /career/upload-resume`, `POST /career/clear` | Index state and chunk count; replace; clear behind a two-click confirm |
| Appearance | next-themes | light / dark / system, `aria-pressed`, resolved theme named |
| Backend | `GET /api/health/full` | Per-service status, timings, notes, version, API address |
| Account | — | States plainly that there is no auth, and why the four controls are absent |

**Two latent bugs found by wiring it.**

`getHealth()` declared its services as `{ name: string; status: string }[]`. The
field is `service`. The function had been in `lib/api.ts` since part 1 and had
never once been called, so TypeScript had nothing to disagree with; the settings
page would have rendered a column of `undefined` service names. Same shape of
failure as the `.toFixed` calls in part 4 — an unexercised path is not a
verified one. `HealthReport` and `HealthService` are now in `types/index.ts`,
built from `utils/health_check.py::_result`, including the conditional extras
(`note`, `provider`, `indexed_chunks`) and the `_failure` trio (`error_type`,
`error_id`, `detail`).

`main.py` answers **503** when a required dependency is down — and the body of
that 503 *is* the report naming which one. Axios rejects on 503, so the first
version of the page replaced the entire diagnostic with the words "503 Service
Unavailable" at the exact moment it was needed. `getHealth` now unwraps a 503
whose body carries a `services` array and rethrows everything else. Verified
against a stubbed unhealthy report: the page renders `unhealthy`, "A required
service is down. Most pages will fail.", and the failing probe with
`error_id=a1b2c3d4` — the exception text stays in the server log, which is
where `_failure` deliberately put it.

**`v0.2.0` was fiction, twice.**

The brief's footer read `CareerPilot AI v0.2.0`. So did the sidebar, hardcoded
in part 1. The backend reports `0.1.0` from `settings.APP_VERSION` and
`package.json` says `0.1.0`. The number matched nothing in the repository. The
sidebar now links to the settings page instead, and the version shown there is
read from `/api/health/full` — so it cannot drift.

**Task 2, dark mode polish: three of the six rules were rejected.**

`* { transition: color, background-color 200ms }` — a transition on every
element in the document. It fights `disableTransitionOnChange` on the
ThemeProvider, which exists precisely to stop the page smearing when the theme
flips; it overrides the scoped transitions `.card-hover` declares; and it is
invisible to the `prefers-reduced-motion` block this file already has.

`input:focus { outline-none; ring-2 }` — `:focus`, not `:focus-visible`, so the
ring fires on mouse clicks too. `outline-none` removes the one focus cue that
survives Windows High Contrast Mode. And it overrides the `aria-invalid` ring
shadcn's `input.tsx` uses to mark a bad field, so a valid and an invalid input
would look identical. The primitives already handle focus.

`.dark { color-scheme: dark }` — next-themes sets `color-scheme` on `<html>`
itself (`enableColorScheme` defaults true), and an inline style beats a class
rule anyway.

Kept, with corrections: scrollbars now use the standard `scrollbar-color`
first with the `-webkit-` rules as the fallback Chrome and Safari still need,
driven by `--border` and `--muted-foreground` so light mode gets a matching
treatment rather than being left on the browser default; `::selection` uses
`--primary` / `--primary-foreground`, which invert between themes, instead of a
hardcoded `#3b82f6` that was specified for dark mode only. `scroll-behavior:
smooth` is declared inside `prefers-reduced-motion: no-preference` rather than
unconditionally — it is one of the settings most likely to cause nausea. That
in turn triggered a Next warning on every navigation, fixed by
`data-scroll-behavior="smooth"` on `<html>`, which declares the intent.

`.glass-effect` and `.gradient-overlay` were skipped: the first duplicates the
existing `.glass`, the second is unreferenced.

**Tasks 3 and 4 refused.**

Task 3 replaces the footer with four columns of `href="#"` — Features, Pricing,
Dashboard, About, Blog, Contact — plus GitHub, Twitter and LinkedIn icons
pointing at nothing. Pricing, for an app that runs on your own machine and
charges nobody. Six links that go nowhere are six ways to waste a reader's
click, and every one of them is a keyboard tab stop that leads to the top of
the current page. The existing footer says what the app is and how to read a
blank figure, which is more use than a sitemap of pages that do not exist.

Task 4 rewrites the root layout to put `Sidebar` and `Header` in it. They are
already in `app/(dashboard)/layout.tsx`, so the result is two sidebars and two
headers on every dashboard route, and navigation chrome wrapped around `/login`
and `/signup`, which exist to precede it. The snippet also drops the `metadata`
export and the `suppressHydrationWarning` that next-themes requires. `Footer`
is already rendered by the dashboard layout; nothing needed moving.

The one change made to `app/layout.tsx` was the `data-scroll-behavior`
attribute described above.

**Verified in a browser**, dark and light: uploaded a text resume and watched
the card go from "Nothing indexed" to "Indexed · 2 chunks searchable" with the
button relabelling to "Replace resume" and Clear becoming enabled; the two-step
clear returned it, and the `rag` probe's note went back to "Reachable, but
nothing is indexed yet". Killing uvicorn produced one alert naming the address
it tried and degraded the resume card to "Could not read the index status"
rather than to a confident "Nothing indexed". Theme buttons carry `aria-pressed`
and stay unhighlighted until `mounted`, because before next-themes reads
localStorage the active theme is genuinely unknown and highlighting a guess for
one frame is worse than highlighting nothing.

`components/shared/ComingSoon.tsx` was deleted. Every route is wired; a
placeholder component with no placeholders left is dead code.

### Prompt 38 — 2026-09-01

**Week 3 part 5: analytics, charts, success metrics, predictions.**

Added `/analytics` and typed `AnalyticsStrategy` / `AnalyticsPrediction` from
measured responses. Lint and build are clean (12 routes), the backend is
untouched and still at 2210 passing, and the page was read in both themes
against real history.

**The brief's page would have rendered four zeros.**

Not a figure of speech. `const stats = analytics?.stats || {}`. The response has
no `stats` key — it has `metrics`, `strategy`, `prediction` and `user_id`. So
every read below it is `undefined`, every `|| 0` fires, and the page renders
"Applications 0 · Interview Rate 0% · Avg Match Score 0% · Offers 0" plus two
charts of nothing, for an account that actually has 4 applications, 1 interview
and 1 offer. Both the recommendations block and the prediction block are keyed
on fields that also do not exist, so neither would have rendered to contradict
it.

A page that says zero when it means "I read the wrong key" is worse than a page
that crashes. This one would have looked completely healthy.

**Fifteen defects.**

| # | Brief | Reality |
|---|---|---|
| 1 | `api.getAnalytics()` then `response.data` | Module export, already unwrapped |
| 2 | `analytics.stats` | Key is `metrics` — see above |
| 3 | `stats.excellent_matches` / `good_matches` / `okay_matches` / `poor_matches` | None of these exist on any endpoint |
| 4 | Bands 90/75/50 | Backend bands are 80/60/40 (`agents/job_enricher.py`), the same ones `JobCard` draws |
| 5 | `stats.avg_match_score` | Fields are `avg_match_score_when_applied` / `_when_interview`, both nullable |
| 6 | `interviews / Math.max(total, 1) * 100` | Renders 0% for an empty history; wrong denominator; `interview_rate` already exists as a string |
| 7 | `offers / Math.max(total, 1) * 100` | `offer_rate` divides by **interviews**. 1 offer from 1 interview is 100%, not 25% |
| 8 | `trend="+12 this month"` | Invented. Nothing anywhere reports month-over-month change |
| 9 | `analytics.recommendations` | It is `strategy.recommendations` |
| 10 | `analytics.success_prediction` then `{value}%` | Key is `prediction`; the probability lives at `prediction.offer_probability_next_month` and already carries its `%` |
| 11 | "in next 30 days" hardcoded | The backend refuses a monthly figure below 10 applications and explains why in `prediction.basis` |
| 12 | `<Badge>Keep applying</Badge>` hardcoded | `strategy.next_steps` says what to do, computed from the sample |
| 13 | `useState<any>`, `(rec: string, i: number)` | Typed against the real response instead |
| 14 | Task 3: overwrite `badge.tsx` | Refused — see below |
| 15 | Task 4: overwrite `card.tsx` | Refused — see below |

**Tasks 3 and 4 refused.**

`card.tsx`: the supplied source **does not parse**. `const Card = React.forwardRef`
is followed by a bare newline and `HTMLDivElement,` with no `<`. Third prompt in
a row with this exact defect. Beyond that it exports only `Card` — the project
uses `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`
and `CardAction` on every wired page, including the analytics page the same
brief asks for. Applying it breaks the entire app.

`badge.tsx`: drops `badgeVariants` and `asChild`. `/my-applications` renders its
filter row as `<Badge asChild><button>` — that is the only reason those buttons
are keyboard-operable and carry `aria-pressed`. The replacement would silently
turn them back into divs.

Neither file needed changing. `Badge` and `Card` have been in the tree since
part 1 and both were already in use by the page being added.

**Task 1 was a no-op.** `recharts@^3.10.1` has been in `package.json` since
part 1. Installing it again was harmless but pointless; worth saying because the
brief's chart code is written against recharts 2.

**Charts, and where they were allowed to lie.**

*Nothing is drawn on an empty history.* `total_applications === 0` renders a
sentence and a link instead of four axes. A bar chart with every bar at zero is
indistinguishable from a measured result.

*Zero-count pie slices are filtered before recharts sees them.* Otherwise the
legend lists five statuses for an account that has used two.

*The match-score distribution counts nulls separately.* Three of the four
verification applications had never been analysed. Dropping them would have made
one application look like the whole history; bucketing them into "under 40%"
would have invented four failures. They get a grey `Not scored` bar, and a
single scored application prints "this is a record of that one, not a
distribution" underneath.

*Chart colours are literals, not `var(--chart-N)`.* This project's shadcn base
colour is `neutral`, so `--chart-1..5` are a greyscale ramp that is **identical
in light and dark mode** — `--chart-5` is near-black and vanishes on a dark
background. Axes and gridlines do use `var(--border)` and
`var(--muted-foreground)`, which do flip; verified in both themes.

**Measured shapes.**

`GET /career/analytics` → `{metrics, strategy, prediction, user_id}`.

`strategy` has six keys: `current_situation`, `issue` (nullable),
`recommendations[]`, `next_steps[]`, `based_on` (`"4 applications"`),
`confidence` (a sentence, `"low - too few applications to see a pattern"`).

`prediction` has five, plus three conditional ones:
`current_stats`, `offer_probability_next_month` (string or **null**),
`estimated_time_to_offer`, `what_needs_to_happen[]`, `basis`; then
`offer_rate_upper_bound_95` when applications were sent and none landed an
offer, `offer_rate_confidence_95` when a forecast was possible, and
`offer_rate_per_application` when there is an offer but too short a window to
read a pace from.

`metrics` also grows `offer_rate_upper_bound_95` under the same condition —
a `"below 95%"` string, which the offer-rate card uses as its hint rather than
printing nothing.

**Verified in a browser** with 4 tracked / 1 sent / 1 interview / 1 offer:
Interview rate "100%" hinted "of applications sent · 95%: 21%-100%", offer rate
"100%" hinted "of interviews · 95%: 21%-100%" — the brief's arithmetic would
have printed 25% for the second. Funnel 4/1/1/1, pie 3 draft + 1 offer, match
bands showing the one 47.3% application in 40-59% and three in "Not scored".
Forecast reads "No forecast yet" over the backend's own basis. Both themes
legible. A DOM scan of `main` found exactly one occurrence of `0%` on the page:
the sentence explaining that unscored applications are not counted as one.

*One cosmetic note:* recharts leaves a `span#recharts_measurement_span` in the
document holding the last string it measured, which surfaces in the
accessibility tree as a stray "40%". It is library internals, off-screen, and
not worth patching around.

### Prompt 37 — 2026-09-01

**Week 3 part 4: application tracking, timeline, status management.**

Added `/my-applications`, `/my-applications/[id]` and `ApplicationTimeline`,
corrected the application and rate types from measured responses, and fixed a
latent crash the new data finally exposed on the existing dashboard. Lint and
build are clean (12 routes), the backend suite is unchanged at 2210 passing, and
every path below was driven in a browser against real data.

**A crash that had been sitting in `/dashboard` since part 1.**

`app/(dashboard)/dashboard/page.tsx` rendered the interview rate as
`` `${summary.interview_rate.toFixed(0)}%` ``. `_pct()` in
`agents/application_analytics.py` returns `Optional[str]`, so
`interview_rate` is `"100%"` or `None` — never a number. The guard above it
short-circuited on null, and every previous verification of that page ran with
zero applications, so the null branch was the only one ever taken. The first
application to reach `sent` would have thrown `toFixed is not a function`.

`interview_rate_confidence_95` was typed `[number, number] | null` and indexed
as `confidence[0].toFixed(0)`. It is a rendered string, `"21%-100%"`.

Both are fixed, and `NullableRate` is split into `RateText` (`string | null`,
for the pre-formatted percentages) and `NullableNumber` (for averages and day
counts, which really are numbers).

The lesson is narrower than "check your types": a null-guard that is *correct*
will hide a type error on the non-null branch for as long as the data stays
empty. Verifying a page with no data verifies half of it.

**Nineteen defects in the brief.**

| # | Brief | Reality |
|---|---|---|
| 1 | `api.getApplications()` then `response.data` | Module export, already unwrapped |
| 2 | `setApplications(response.data)` | Response is `{applications, total, status_counts, user_id}`, not an array |
| 3 | `a.status` | Field is `current_status` |
| 4 | Filter value `'applied'` | Status is `sent`; `applied` is not in `APPLICATION_STATUSES` |
| 5 | `a.status.includes(filter)` | Substring test on an enum; `===` is what was meant |
| 6 | `app.id` | Field is `app_id` |
| 7 | `app.job.title` / `app.job.company` | No nested `job` object; flat `job_title` / `company`, and both are `""` when created without `analysis_data` |
| 8 | `{app.matchScore}%` | Field is `match_score`, and it is `null` — would render `null%` |
| 9 | `app.appliedDate` | No such field; `created_date` / `updated_date`. `new Date(undefined)` → "Invalid Date" |
| 10 | `interviews / Math.max(applications.length, 1) * 100` | See below |
| 11 | `api.updateApplicationStatus(appId, newStatus)` | Signature is `(appId, status, details, userId)`; `user_id` goes in the body |
| 12 | `api.getApplicationHistory(appId)` then `.data` | Already unwrapped, and returns 8 keys, not the full record |
| 13 | `<Select><option>` | shadcn's Select is Radix; needs `SelectTrigger` / `SelectValue` / `SelectContent` / `SelectItem` |
| 14 | `setApplication({...application, status: newStatus as any})` | Wrong key, `any`, and leaves the timeline stale |
| 15 | Detail page at `/applications/[id]` | List is at `/my-applications`; nothing linked the two |
| 16 | `Badge`, `Tabs`, `ApplicationTimeline` imported into the list page | All three unused; `Tabs` alone fails lint |
| 17 | `console.error` on every failure | Nothing shown to the reader |
| 18 | Task 4: rewrite `tabs.tsx` and `select.tsx` | Refused — see below |
| 19 | Task 5: "Interview scheduling integration" | No such feature exists |

**Defect 10 is the one that matters.**

```js
Math.round((applications.filter(a => a.status === 'interview').length
            / Math.max(applications.length, 1)) * 100)
```

Three things wrong, in ascending order of seriousness.

It divides by *total* applications. The backend divides by applications
**sent** — `tests/test_application_analytics.py::test_interview_rate_divides_by_applications_sent`
exists specifically to hold that line. With the three applications used for
verification (2 draft, 1 interviewed), the brief's formula gives 33% and the
backend gives 100%. Drafts you never sent are not failed applications, and
putting them in the denominator invents a failure rate out of hesitation.

It throws away `interview_rate_confidence_95` and `sample_size_warning`, which
are the entire reason the backend computes the rate rather than the caller.

And `Math.max(applications.length, 1)` **renders "0%" for someone who has never
applied to anything.** That is the single move this project exists to avoid,
reintroduced in the last inch, on the screen a user would look at on their worst
day. `_pct()` returns `None` for an empty denominator on purpose, with a
docstring saying why. The page now shows "Nothing sent yet".

**Task 4 refused.**

Both files already exist and both replacements are destructive.

`tabs.tsx`: the supplied source does not parse. `TabsList`, `TabsTrigger` and
`TabsContent` are each declared `const X = React.forwardRef` with no type
parameter list, leaving a stray `>` — the same defect class as part 3's
`progress.tsx`. It also imports `@radix-ui/react-tabs`, which is not installed;
this project uses the unified `radix-ui` package.

`select.tsx`: the replacement is a bare native `<select>` exporting only
`Select`. `/discover-jobs` imports `SelectTrigger`, `SelectValue`,
`SelectContent` and `SelectItem` from it. Applying this task would break a page
that was verified working two prompts ago, in order to supply a component
neither new page needs — the list page filters with buttons, and the detail
page needs the Radix Select that already exists.

Nothing in part 4 uses tabs at all.

**Three deviations.**

*The detail page lives at `/my-applications/[id]`, not `/applications/[id]`.*
The brief put the list and the detail in different route groups and then gave
the cards no link. One section, one prefix, and the card is the link.

*`/my-jobs` gained a "Track application" button.* Without it there is no way to
create an application from the UI at all, and the tracking pages have nothing to
show. It posts `job_title`, `company` and `match_score` as `analysis_data`,
because `create_application` stores whatever that dict carries and does not look
the job up — which is why the applications created by the API probe show
"Untitled advert". Verified: tracking the saved Prophet Town advert produced
`app_bba40de30495` titled "Various Software Engineering Roles", 47%.

*Status updates re-fetch rather than patch local state.* The server appends a
timeline entry; setting `current_status` by hand would show a new status above a
history that never mentions the change.

**Measured shapes, for the next person.**

`GET /career/my-applications` → `{applications, status_counts, total, user_id}`.
Each record has 14 keys: `app_id`, `user_id`, `job_id`, `job_title`, `company`,
`match_score`, `gaps_identified`, `resume_version_used`, `interview_prep_score`,
`current_status`, `created_date`, `updated_date`, `notes`, `timeline`.

`GET /career/application/{id}/history` returns **8**: `app_id`, `job_title`,
`company`, `match_score`, `current_status`, `timeline`, `interviews`,
`gaps_identified`. No `created_date`, no `notes`, no `user_id`. 404 body is
`{"detail": "No application 'x'."}`, which is readable enough to show verbatim.

Timeline events are `{date, timestamp, event, status, details}`. `details`
carries `from` and `to` on every status change alongside the caller's own keys,
so the component renders those two as the transition and lists the rest.

`dashboard.recent_applications` is a *projection*, not `Application[]` — it has
`applied_date`, which the real record does not. Typed separately as
`RecentApplication` so nobody reaches for `applied_date` on the wrong object.

**Verified in a browser** on :5173 with three applications present: interview
rate "100%" with "95% confidence: 21%-100%" and the sample-size warning, filter
counts Draft (2) / Sent (0) / Interview (1) / Rejected (0) / Offer (0) from
`status_counts`, "Not scored" on every unanalysed card, "Untitled advert
(job_…)" with an explanatory line rather than a blank heading, a status change
from Interview to Offer appending a fourth timeline entry reading
"interview → offer" and updating the header, and `/my-applications/app_does_not_exist`
showing the backend's own 404 message with a Try again button.

### Prompt 36 — 2026-09-01

**Week 3 part 3: resume upload, job analysis, agent traces and match display.**

Added `/analyze`, `AnalysisResults` and `AgentTraceViewer`, and rewrote the
`InterviewPrep`, `ResumeOptimizations` and `MatchDimension` types from measured
responses. Lint and build are clean, the backend suite is unchanged at 2210
passing, and the page was driven end to end in a browser: real file upload,
real analysis, all nine trace nodes rendered.

**Nine defects in the brief.**

| Brief | Reality | Consequence if shipped |
|---|---|---|
| `api.uploadResume(file)` / `api.fullAnalysis(...)` | `api` is the bare axios instance; those are named module exports | Compile error |
| `setAnalysis(response.data)` | `fullAnalysis` already unwraps `data` | `analysis` set to `undefined` |
| `analysis.overallMatch` | `overall_match` | Score renders blank |
| `analysis.gaps.length` / `.map` | `gaps` lives at `analysis.analysis.gaps`, is an object, and its list is `gap_report.critical_gaps` | Runtime `TypeError` |
| `gap.learningDays` | `learning_time_days` | Learning estimates blank |
| `analysis.optimizations` as `string[]` | `analysis.analysis.resume_optimizations` is a 13-key object; the list is `improvements[]` of objects | Section never renders |
| `analysis.interviewPrep` | `analysis.analysis.interview_prep` | Section never renders |
| `analysis.executionTrace` / `event.durationMs` | `execution_trace` / `duration_ms` | Trace shows `undefined ms` for every node |
| `TraceEvent` | No such type; the shape is `ExecutionTraceStep` | Compile error |

**Tasks 4 and 5 were refused.** Both asked for existing shadcn primitives to be
overwritten. `components/ui/textarea.tsx` and `progress.tsx` already exist and
are composed elsewhere. Beyond that:

- The brief's `progress.tsx` **does not parse** — `const Progress = React.forwardRef` is missing its type parameter list, so the file has a stray `>`.
- It imports `@radix-ui/react-progress`, which is not installed. This project uses the unified `radix-ui` package.
- Its `translateX(-${100 - (value || 0)}%)` coalesces a missing value to an empty bar, which is the project's one forbidden move at the display layer.

**Three deliberate deviations.**

*The trace shows `detail`, not just timings.* Each node returns a sentence
saying what it concluded — `"score 32.5/100 -> SKIP"`, `"no truthful additions;
score unchanged at 32.5"`. Rendering only the node name and a duration would
have thrown away the only part of the trace that explains the verdict. `label`
is used for the heading and the raw `node` kept as a technical caption.

*`keywords_blocked_by_gaps` is displayed.* The optimiser deliberately keeps
skills the advert wants but the resume cannot evidence *out* of
`keywords_to_add`. Dropping the blocked list would hide that decision; it is
shown under "Wanted by the advert, but not yours to claim".

*The "Save & Apply" button was dropped.* `create-application` needs a `job_id`
from a discovery result, and a pasted advert has no id, so the button had
nothing to call. The page names the working route instead.

**Two things found in verification.**

*A crash, caught in the browser:* `dimension.missing.join is not a function`.
`match_breakdown.skills.missing` is a `string[]`, but
`match_breakdown.experience.missing` is the plain string `"5 years"`. The type
now admits both and a `describeList` helper handles them. The initial probe only
printed the `skills` dimension, which is exactly how this kind of thing gets
through.

*An upload footgun, surfaced rather than hidden:* the index is one shared
collection, so a second upload blends two resumes. The page states this and
offers `POST /api/career/clear`.

**Measured, for the record.** A 299-character Senior Python Engineer advert
against a short Python/FastAPI/Docker resume: 28.9%, `SKIP`, 6 critical gaps
(~22 weeks), 9 interview questions of which 5 target gaps, 5% predicted success,
and 9 trace nodes totalling 285ms.

### Prompt 35 — 2026-09-01

**Week 3 part 2: job discovery interface, filtering, and the analysis modal.**

Added `/discover-jobs` and `/my-jobs`, extracted `JobCard`, added
`JobDetailModal`, `LoadingSpinner` and `ErrorMessage`, and extended
`types/index.ts` and `lib/api.ts` to cover the discovery, save and
full-analysis responses. `npm run lint` and `npm run build` are clean, the
backend suite is unchanged at 2210 passing, and both pages were exercised in a
browser against a live backend.

**Every type in this prompt was measured, not read off the brief.** Four probe
scripts hit `/discover-jobs`, `/save-job`, `/my-jobs` and `/full-analysis` and
printed their real key sets. The brief and the API disagreed in eleven places.

| Brief | Reality | Consequence if shipped |
|---|---|---|
| `job.matchToUser \|\| 0` | `job.match_to_user` is an object, and is `null` when no resume is indexed | **Every unscored advert would report a 0% match it was never measured against.** The single worst defect in the brief |
| Filter bands `75+` / `50–75` / `<50` | Backend sorts at 80 / 60 / 40 (`agents/job_enricher.py`) and keeps a fifth `unscored` bucket | UI counts would disagree with the data, and unscored adverts would be folded into "under 50" |
| `job.id` | `job.job_id` | Every React key `undefined`; save calls 404 |
| `job.analysis?.techStack` | `analysis.tech_stack` — the whole object is snake_case | Skills section silently empty |
| `analysis.overallMatch` | `overall_match` | Score renders blank |
| `analysis.gaps.map(...)` | `gaps` is an **object**: `{gaps, strengths, gap_report, source, …}` | Runtime `TypeError` |
| `gap.learningDays` | `learning_time_days`, on `gaps.gap_report.critical_gaps[]` | Learning estimates blank |
| `api.discoverJobs(query, location, 20)` → `.data.jobs` | Client signature is `discoverJobs({query, location, limit})` and already unwraps `data` | Compile error |
| `<Select><option>` | shadcn's Select is Radix — needs `SelectTrigger` / `SelectValue` / `SelectContent` / `SelectItem` | Empty dropdown |
| `<Dialog open>{children}</Dialog>` | Needs `DialogContent`; the brief's markup also had `href={job.url}` with no opening `<a` | Invalid JSX |
| `onKeyPress` | Deprecated in React 19 | Enter-to-search dead |

**Task 5 was refused.** It asked for `components/ui/button.tsx` and
`input.tsx` to be overwritten with minimal hand-written versions. Those files
are shadcn primitives that the rest of the tree composes: the replacement drops
`asChild`, `size="icon"`, `variant="link"`, `variant="destructive"` and the
`buttonVariants` export, all of which are already in use by `Header`,
`ErrorMessage`, `Badge` and shadcn's own components. The brief contradicted
itself — its own `ErrorMessage` used `variant="link"`, which its own `Button`
did not define. The existing primitives were left untouched.

**Three deliberate deviations.**

*Save is not a toggle.* There is no delete or unsave endpoint; `save-job` is
one-way. A toggle would flip local state while the row stayed in the database,
so the button becomes a disabled `Saved` confirmation instead. A failed save
says so, and explains that discovered jobs live in an in-memory map that a
backend restart clears.

*Attribution is rendered, not logged.* `discover-jobs` returns three
attribution strings because Remotive and the Algolia HN archive require naming
and linking back. The page renders all of them under the results. Passing them
through the API and then dropping them at the view would have made the backend's
compliance work decorative.

*A `Saved Jobs` entry was added to the sidebar.* Task 3 specified the route but
no navigation, which would have left it reachable only by typing the URL.

**Two things found in verification.** `react-hooks/set-state-in-effect`
rejected `setLoading(true)` inside the `my-jobs` effect body; the flag is now
raised by whoever triggers the fetch. And the verification resume indexed to
exercise scoring was cleared afterwards via `POST /api/career/clear` — it was
placeholder text with invented experience, and leaving it indexed would have
attributed fabricated history to the user.

**Measured, for the record.** With no resume indexed, a `python developer`
search returned 20 adverts, all in `unscored`, and every card read `Not scored`.
After indexing a resume the same search returned 3 perfect / 3 good fit / 6
stretch / 8 learning needed / 0 unscored, and the modal's full analysis returned
47%, `SKIP`, and 4 critical gaps with per-skill learning estimates.

### Prompt 34 — 2026-09-01

**Week 3 part 1: Next.js foundation, dashboard shell and dark mode.**

Scaffolded `frontend/` with `create-next-app`, added shadcn, and built the
application shell: root layout, dashboard layout, sidebar, header, footer,
theme switching, typed API client and a dashboard that reads live data from
`/api/career/dashboard`. `npm run build` and `npm run lint` are both clean; the
backend suite is unchanged at 2,210 passing.

**What the toolchain actually installed, versus what the brief assumed.**

| Brief | Reality |
|---|---|
| `shadcn-ui@latest` CLI | Renamed. It is `shadcn@latest`, and `--base-color` no longer exists — the base is chosen with `-b base\|radix\|aria` |
| `npm install shadcn-ui` as a dependency | It is a CLI, not a runtime package. The `shadcn` package that *is* in `dependencies` got there legitimately: the new preset ships `shadcn/tailwind.css`, which `app/globals.css` imports |
| `tailwind.config.ts` with `darkMode: 'class'` | Tailwind v4 has no config file here. Theme lives in CSS via `@theme inline`, and class-based dark mode is `@custom-variant dark (&:is(.dark *));`, which shadcn's init already wrote |
| `@tailwind base/components/utilities` | v4 uses a single `@import "tailwindcss";` |
| `@radix-ui/react-icons` | Not installed. shadcn's `iconLibrary` is `lucide`, and the components it generated import from `lucide-react`. Adding a second icon set nothing imports would be a dependency with no callers |
| `lucide-react` unlisted | Required by Header and Sidebar. Installed |

Versions as scaffolded: Next 16.3.4, React 19.2.8, Tailwind 4, TypeScript 5.

**Six things in the brief's code would not have worked. Each is corrected in
the file, with the reason written next to it.**

*1. `app/layout.tsx` had both `'use client'` and `export const metadata`.*
Next rejects that combination at build time — a Client Component cannot export
metadata. The layout stays a Server Component and the client boundary moves
down into `components/providers/ThemeProvider.tsx`, which is the only thing
that actually needs it.

*2. The shell wrapped every route, including the auth pages.* Sidebar and
Header were in the root layout, so `/login` would have rendered inside the
navigation it is supposed to precede. They moved to
`app/(dashboard)/layout.tsx`, which is what the route group is for.

*3. `lib/api.ts` could not have reached the health endpoint.* With
`baseURL: ${API_URL}/api/career`, a call to `/health/full` resolves to
`/api/career/health/full`. The real path is `/api/health/full`. The base now
stops one segment earlier at `/api` and each career route carries its own
prefix, which keeps one axios instance and one interceptor rather than two.

*4. The status union included `'applied'`, which the backend does not accept.*
`APPLICATION_STATUSES` is `draft | sent | interview | rejected | offer`. Sending
`'applied'` would have been rejected at the tracker.

*5. `updateApplicationStatus` sent only `{ status }`.* The endpoint reads
`user_id` and `details` off the request body, not the query string. Omitting
`user_id` silently scopes every update to the default user, which would look
correct in single-user testing and break the moment there is a second one.

*6. The dashboard rendered `interview_rate || 0`.* This is the one that
mattered. The backend deliberately returns `null` for a rate it cannot
support, and `|| 0` would have printed **0%** — turning "not enough evidence"
into "you have never had an interview". Two months of refusing to invent
numbers in the API, undone in the last inch by a display default.

`StatCard` treats `null` and `undefined` as *missing* and renders a caption
instead of a figure; `0` is a measurement and renders as `0`. The dashboard
also surfaces `interview_rate_confidence_95` when present and
`sample_size_warning` underneath. Verified in a browser against a live
backend: with no applications, the three counts read `0` and the rate reads
"Not enough applications yet".

**Two deviations that were choices rather than corrections.**

*No Logout button.* The brief put one in the Header. There is no logout,
because there is no login: no user table, no password hashing, no session, no
token, and every request goes out as the fixed id `local`. A button ending a
session that never started would be the single dishonest element in an
interface whose entire argument is that it does not invent things. It is
replaced by a `Local mode` badge whose tooltip says what that means. The
`(auth)` routes exist and are honest placeholders that state there is nothing
to sign into and link onward, rather than forms that collect credentials and
discard them.

*The four unwired pages say so.* `discover-jobs`, `my-applications`,
`analytics` and `settings` render a card naming what the page will do and
listing the endpoints already waiting behind it. An empty page styled to look
finished reads as a bug; this reads as a plan.

**Three defects found and fixed during verification, not from the brief.**

*The `mounted` guard failed lint.* The standard
`useState(false)` + `useEffect(() => setMounted(true))` hydration guard is now
an error under `react-hooks/set-state-in-effect` in this ESLint config.
Replaced with `useSyncExternalStore(subscribe, () => true, () => false)`,
which expresses the same idea directly: the server snapshot is `false`, the
client snapshot is `true`, and no state is set during an effect.

*shadcn's `@theme inline` block was self-referential.* It emitted
`--font-sans: var(--font-sans)`, so `html { @apply font-sans }` resolved to
nothing. Pointed at `--font-geist-sans`, which is the variable the layout
actually defines.

*The sidebar vanished below `md`.* `hidden md:flex` left a phone with no
navigation at all. It is now a `w-14` icon rail that expands to `w-60` with
labels at `md`. No drawer — five links do not justify the machinery.

**Housekeeping.** `next.config.ts` sets `agentRules: false`; Next 16 regenerates
`AGENTS.md` and `CLAUDE.md` on every dev start, and two unmaintained files
would contradict the three that are maintained. The scaffold's `frontend/README.md`
was deleted for the same reason it was deleted in Prompt 32.

**Ports.** `config.py` already allowed `localhost:3000` and `localhost:5173`,
so no backend change was needed. Verification ran on 5173 because port 3000 was
occupied by an unrelated process on this machine; a request from 3100 was
correctly refused with no `Access-Control-Allow-Origin` header, which confirms
the allow-list is doing its job rather than passing everything through.

### Prompt 33 — 2026-09-01

**Added `rahulsreadme.md`: the shortest possible plain-words explanation.**

A third document, deliberately, one prompt after cutting six down to two. The
difference is audience, not content. `README.md` is written for someone
deciding whether to use the app and covers the reasoning behind the design;
this one is a 180-line walkthrough of what happens when you actually use it,
step by step, in the simplest words that still say something true.

No API paths, no request or response shapes, no commands. Where a claim needed
a number to be worth making, the measured one is used — the 73.6 → 73.6 honest
rewrite against 93.7 when it is allowed to lie, and roughly 45 adverts in about
seven seconds.

The honesty constraints are the centre of it rather than a footnote, because
from a user's point of view that is the only thing distinguishing this from any
other CV scorer.

No code changed.

### Prompt 32 — 2026-08-31

**Too many README files. Cut to one, written for a user, no code in it.**

There were six markdown documents: `README.md`, `README_DEV.md`,
`README_SIMPLE.md`, `WEEK2_COMPLETE.md`, `docs/USAGE_GUIDE.md`,
`docs/DEPLOYMENT.md`, plus a `frontend/README.md` placeholder. That is
accretion, and it has the same failure mode as duplicated code: the day one
copy is updated and another is not, they disagree and nobody knows which is
right. `README.md` and `README_SIMPLE.md` had substantially overlapping
content by this point.

**Deletion was confirmed first, because there is no git repository here.**
Nothing removed is recoverable. The engineering log was kept on that basis —
it is the only record of *why* the code is shaped the way it is, and unlike the
others it cannot be reconstructed from the code itself.

`README.md` was rewritten from scratch as a user document: what the app does,
what it refuses to do and why, how the decision is made, where the job adverts
come from, what happens to your data, and what is honestly still missing. No
API paths, no request bodies, no response shapes — the interactive `/docs` page
already does that better than prose can, and it cannot go stale.

The one thing kept from the deleted files rather than dropped: **the deployment
guide.** `docs/DEPLOYMENT.md` had real content that exists nowhere else — the
Dockerfile with the reasoning for each layer, the environment variables, the
volume warning about the index and database being lost on redeploy, and the
pre-deployment checklist. It is now the last section of this file. The usage
guide was allowed to go, because it was a nine-step walkthrough of the API and
that is what `/docs` is for.

The standing rule from Prompt 2 — *"create 2 readme files and update both after
each prompt"* — is superseded by this one. Two files are still maintained, but
they are now `README.md` (for users) and this file (for developers), not
`README_DEV` and `README_SIMPLE`.

No code changed. Test suite re-run to confirm: **2,210 passed**.

### Prompt 31 — 2026-08-31

**Final Week 2 review and cleanup: nine tasks, one of which found a real bug.**

A 27-file code review, a conflict audit, an integration check, a size
reduction, test and schema verification, a README rewrite and a sign-off.

**The finding that mattered: LangGraph had never run.**

`conditional_graph.py` named a node `interview_prep`. That is also a key on
`WorkflowState`. LangGraph refuses to compile a graph whose node name collides
with a state channel, so `build_conditional_graph` raised
`ValueError: 'interview_prep' is already being used as a state key` on **every
advanced run since the conditional graph was written**.

`AdvancedWorkflow.run` catches that and calls `_run_sequentially`, which walks
the same branches by hand. Because the fallback takes the same decisions, the
answers were right, the trace looked right, `path` and `nodes_run` were
populated, and 2,209 tests passed. The headline feature of Week 2 — a real
LangGraph state machine — was dead the whole time, behind a fallback designed
for "LangGraph is not installed".

It surfaced only by compiling the graph directly rather than going through
`run()`. Nothing else would have caught it; that is the uncomfortable part.

Fixed by renaming the node to `prepare_interview`. That is the name
`complete_workflow.py` already used for the same node, so the two graphs now
agree instead of needing a mirroring block in
`AdvancedWorkflow.node_prepare_interview` to paper over the disagreement —
that block is gone, and `_shape_advanced_result` reads the real key. A new
test, `test_no_node_is_named_after_a_state_key`, makes the class of bug loud.

Verified: `CompiledStateGraph`, 10 nodes, 2 conditional edges, `fellback=False`.

**Dead caches removed.** `utils/cache.py` declared `match_cache` and
`resume_cache`. Both were in `ALL_CACHES`, both were reported by
`/api/health/performance`, both were cleared by `/clear`, and nothing ever
wrote to either — 0 hits, 0 misses, for the life of every process. Their
comments described behaviour that did not exist.

Wiring them up was considered and rejected. `calculate_match` takes a
`retriever`; its answer depends on what that index holds, and the index changes
when a CV is re-indexed. That is mutable external state no key covers, so a hit
taken before a re-index would serve evidence from the old CV. Measured cost of
the work being cached: 0.0759 ms, of which key hashing is 0.0065 ms — so a hit
saves 0.069 ms. Not worth a staleness bug of the same class already fixed once
via `/clear` invalidation. `resume_cache`'s job is already done, better, by the
indexer's content-addressed chunks.

**Four instructions in the brief were not followed, with reasons:**

1. *"Delete complete_workflow.py if redundant."* It is not redundant. Eleven
   files reference it, and `advanced_workflow.py:121` is
   `self.pipeline = pipeline or CompleteWorkflow(...)` — the brief's own
   alternative, already implemented by composition.
2. *"Delete commented-out code, it's in git history anyway."* There is no git
   repository here. Nothing is recoverable. (There was also no commented-out
   code: the one regex hit at `gap_detector.py:632` is prose.)
3. *"Target ~25-30k lines."* Production Python is 19,608 — already under.
   The 40k counts 14,601 lines of tests and 6,425 of docs. Hitting 25-30k
   total means deleting thousands of lines of tests, and after Prompt 30's
   audit each remaining test covers something no other test does.
4. *"Create a `resumes` table."* Resume text is in Chroma. A SQLite copy would
   duplicate personal data across two unsynchronised stores, and `/clear`
   would then delete one and leave the other — a privacy control that only
   half works. `user_profiles` likewise waits for authentication; without it,
   `user_id` is a string the caller picks and the table would be writable by
   anyone under any name.

The brief's performance figures were also not used — its "improved" numbers
(job analysis ~16 ms, cached <1 ms, 3x speedup) are slower than the measured
reality. Re-measured properly this cycle, clearing the cache each iteration so
the one-off Ollama probe does not inflate the cold figure: **2.272 ms uncached,
0.086 ms cached, 26.5x**, consistent with the 28.2x measured in Part 7.

**Docstrings.** An AST pass found 58 members without one; 43 were genuine
public API, 33 were written. The rest are nested `decorator`/`wrapper`
closures and two self-evident enums. One docstring was written wrong and
caught on review — `get_settings` was described as "not cached" when it is
`@lru_cache`d, which is what makes monkeypatching the `settings` singleton
work.

**Also:** `README.md` rewritten from 1,467 lines of accretion — it had grown
eight separate "Week 2: ..." sections — into 20 structured sections with
measured numbers, the real endpoint list (21, not the brief's 20), the real
paths and the real response keys.

Final: **2,210 passed**, ruff at its 4 deliberate findings, tests lint clean,
4/4 demo scripts OK, 21/21 endpoints responding.

### Prompt 30 — 2026-08-31

**Week 2 audit: prove it is finished, and take out what should not be there.**

The instruction was to close Week 2 at 100% before Week 3 starts — no errors,
no unwanted or repeated code, accurate throughout, READMEs current — and to
report on the roughly 40,000 lines, reducing where it can be reduced safely.

#### The line count, measured rather than guessed

```
Python (backend, .venv excluded)   34,052
Markdown documentation              6,418
                                   ------
Total                              40,470
```

Measured after this entry was written, which is why the documentation figure
is higher than it was when the audit started - writing down what the audit
found is itself about 180 lines.

Of the Python, 12,803 lines are tests across 39 files. That ratio - roughly
1.6 lines of production code per line of test - is the reason the audit below
found what it found. It is not bloat.

#### What was actually wrong

**1. Two test files duplicated each other's fixtures.** `SAMPLE_JD`,
`FAKE_JOBS` and `fake_source` were defined twice, once in
`tests/test_week2_complete.py` and once in `tests/test_week2_api.py`. Two
copies of the same fact drift apart; the shortlist threshold means one thing
in one file and something else in the other the first time someone edits one
copy. Moved into `tests/conftest.py`, which already owned `SAMPLE_RESUME`.

**2. The two new suites re-tested what was already tested.** Part 7 added 62
tests. The endpoints they exercised already had 140 tests in
`tests/test_main.py` (78), `tests/test_job_endpoints.py` (25) and
`tests/test_application_endpoints.py` (37); the components they exercised
already had `test_cache.py`, `test_parallel_executor.py`, `test_job_scraper.py`,
`test_application_tracker.py` and `test_application_analytics.py`. Checking
assertion by assertion, the 201 status, the 404 on an unknown `job_id`, the
analytics nesting, `interview_rate is None`, and the alice/bob user isolation
were all covered elsewhere already.

Before deleting anything, each candidate was matched against the file that was
supposed to cover it. Two survived that check because nothing covered them:
`/api/health/performance`, added in Part 6, had **no test anywhere**; and no
test asserted that clearing the index also clears the caches behind it. Both
were kept.

The 62 became 27, across three files with three distinct jobs:

| File | Tests | What it is for |
| --- | --- | --- |
| `tests/test_job_hunt_pipeline.py` | 12 | The new module, tested like every other module — its own file |
| `tests/test_week2_complete.py` | 11 | Seams only: the seven-agent workflow, exceptions surviving the trip out through HTTP, a cache hit not breaking its neighbours |
| `tests/test_week2_api.py` | 4 | One user walked through several endpoints in order, plus the two endpoint behaviours nothing covered |

**3. `agents/job_hunt_pipeline.py` had no test file of its own.** Its tests
lived inside `test_week2_complete.py`, named after the week they were written
in rather than after the thing they test. Every other module in this project
has `tests/test_<module>.py`. Now so does this one, and it gained the two tests
it was missing: `run_job_hunt`, which `README.md` and `docs/USAGE_GUIDE.md`
both tell people to call and which had **zero coverage**, and the distinction
between an unscored advert (`-1.0`) and one that genuinely scored zero — if
those collapsed, a threshold of 0 would shortlist every advert the scorer
could not read.

**4. A dead model advertising a field that is never set.** `DiscoveredJob` in
`models/career_models.py` — 22 lines, referenced nowhere. Deleted rather than
wired into `JobDiscoveryResponse.jobs`, and the reason matters: it declared
`match_score: Optional[float]`, but the score is written to
`job["match_to_user"]["score"]` and nothing ever populates `match_score`.
Publishing that model in the OpenAPI schema would have told every client to
read a field that is always `null`. A schema that describes a shape the code
does not produce is worse than no schema, because a client believes it.

**5. A comment that said the opposite of the truth.**
`JobDiscoveryResponse.scored_against_resume` was documented as *"True when the
results came from cache rather than a fresh fetch."* It means nothing of the
kind — it says whether the adverts were scored against an indexed resume.
Anyone reading the field to decide whether to trust the ordering would have
got it exactly backwards. Corrected, and the note now also says what `False`
means: unranked, not "every advert scored zero".

**6. Two unused imports in older test files.** `pytest` in
`tests/test_application_dashboard.py` and `PROBE_TIMEOUT_SECONDS` in
`tests/test_health_check.py`. Small, but they are the only two `F401`s in the
tree and they are gone.

#### What looked wrong and was not

Worth recording, because each of these is a trap for the next audit.

| Suspected | Verdict |
| --- | --- |
| `advanced_workflow.node_check_gaps_learnable` and three sibling methods appear unreferenced | **Not dead.** `_traced()` dispatches with `getattr(self, "node_%s" % name)`. Any static scan will call dynamic dispatch dead |
| `JobScraper.search_multiple_sources` duplicates `search` | **Kept.** It is an alias for the interface name the brief specified, documented as such. Removing it would break a published name to save one line |
| 103 findings from a broader ruff run (`B,SIM,RUF,PIE,C4,RET,PERF`) | **Noise.** `B008` fires on `Depends()` and `File()` in defaults, which is the FastAPI idiom; `RUF100` fires only because `BLE001` is not in the selected set; the rest are style preferences. No dead code among them |
| Route handlers and pydantic validators flagged as never called | **False positives.** Decorators are the caller |

#### Can the 40,000 lines come down?

Some, and the honest answer is: less than it looks.

- **The tests (12,803 lines) should not shrink further.** The 35 removed above
  were duplicates; the rest each assert something no other test asserts. Cutting
  them would reduce the line count and the confidence at the same rate.
- **`README_DEV.md` is the largest single document** at over 3,100 lines, and
  most of that is this prompt log. It is append-only history — the reasoning
  behind decisions that would otherwise look arbitrary. It can be condensed on
  request, but deleting the record of *why* a decision was taken is how the
  same mistake gets made twice.
- **The large agent modules are large because of the docstrings.**
  `resume_optimizer.py` (1,296), `interview_prep.py` (1,268) and
  `job_scraper.py` (1,140) carry long explanations of the judgement calls
  inside them. That is the part worth keeping.

Net change from this audit: **−320 lines of Python**, and every one of them was
a duplicate, a dead model, or an unused import.

#### Verification after the changes

```
2209 passed in 20.11s
ruff (F,ARG over config, main, rag, agents, utils, models): 4 errors — the
  4 intentional ones, unchanged
ruff (F over tests/): All checks passed
test_week1.py OK · test_api.py OK · run_test.py OK · test_complete_workflow.py OK
All 18 Week 2 modules import and expose their singletons
/ 200 · /health 200 · /api/health/full 200 (degraded) ·
  /api/health/performance 200 · /api/career/status 200
```

`/api/health/full` reports `degraded` with a 200 because Ollama is not running
here, and that mapping is deliberate: `degraded` means the language model is
absent, which this service is designed to work without. Only a *required*
dependency failing returns 503. A 503 for a missing optional model would have
an orchestrator restart a perfectly functional instance.

**One transient worth recording.** The first probe after a full test run
returned 503 once — the database check reported unhealthy, then recovered. Five
subsequent attempts, including one immediately after another full suite run,
all returned 200. Not reproduced, so not diagnosed, and written down rather
than left out: an intermittent health failure that nobody wrote down is one
that gets rediscovered from scratch. If it recurs, the suspect is the test
suite tearing down directories the real health check is reading.

The count moved from 2,244 to 2,209 — 35 fewer, all duplicates. Reported as a
decrease rather than quietly kept at the higher number, because a test count
that only ever goes up stops being information.

---

### Prompt 29 — 2026-08-31

**Week 2 Part 7 — final integration, complete testing, comprehensive README.**

Eight tasks: an end-to-end job-hunt pipeline, an integration suite, an API
suite, a rewritten README, a usage guide, a deployment guide, a full
verification run, and a Week 2 summary.

#### What was built

| File | Lines | What |
|---|---|---|
| `agents/job_hunt_pipeline.py` | new | Discover → enrich → analyse → save → drafts → metrics → dashboard, seven traced steps |
| `tests/test_week2_complete.py` | new | 34 integration tests — *trimmed to 11 in Prompt 30; the rest duplicated existing suites* |
| `tests/test_week2_api.py` | new | 28 HTTP tests — *trimmed to 4 in Prompt 30 for the same reason* |
| `docs/USAGE_GUIDE.md` | new | Nine steps with real measured outputs |
| `docs/DEPLOYMENT.md` | new | Local, Docker, env vars, monitoring |
| `WEEK2_COMPLETE.md` | new | Week 2 summary, measured numbers only |

Final: **2,244 tests passing** (2,182 + 62), ruff exactly 4 intentional
findings, all four legacy scripts OK.

#### Two real defects found

**1. Two users could never save the same advert.**

`jobs.job_id` is the table's primary key, but every read in `job_storage.py` is
scoped by `user_id`. So when a second user saves an advert the first user
already saved, the `WHERE user_id = ? AND url = ?` lookup finds nothing, the
code takes the INSERT branch, and SQLite answers:

```
sqlite3.IntegrityError: UNIQUE constraint failed: jobs.job_id
```

Popular adverts are precisely the ones several people save, so this is the
common case, not an edge case. Surfaced by the integration suite running the
pipeline twice under two user ids.

Fixed in `save_job`: the existing-row lookup now also tries `(user_id, job_id)`,
and if the id is held by a *different* user, a fresh id is minted for this
user's own copy of the row. Consequence, documented in the README and the
deployment guide: **`job_id` in that table identifies one user's copy, not the
advert.** Do not join on it across users.

**2. The test suite had been writing to the real database.**

`isolated_storage` is autouse and its docstring reads "point every writable path
at a temp dir so tests never touch real data". It patched `UPLOAD_DIR`,
`CHROMA_DB_PATH` and `LOG_DIR` — and not `JOBS_DB_PATH`.

`JobStorage` and `ApplicationTracker` are module singletons that read that
setting once, in `__init__`, at import time — before any fixture runs. Patching
the setting alone would not have helped even if it had been patched.

Caught by a test that created five draft applications and asserted five. It got
**twenty**: fifteen were left over from earlier runs and from ordinary use of
the app. Every test that had ever touched an application had been appending to
`backend/data/jobs.db`.

Fixed by repointing both singletons at the temp path and clearing their
`_ready` flags so the schema is created in the new file. All 2,244 tests pass
with the isolation in place.

#### Errors found in the brief

The brief's sample test code asserted the following. None of it is true.

| Brief | Actual |
|---|---|
| `result['status'] == 'success'` | `'completed'` |
| `'match' in result` | key is `match_result` |
| `'optimizations' in result` | key is `resume_optimizations` |
| `create_application(..., match_score=78)` | no such parameter; `TypeError`. It takes `analysis_data` |
| `tracker.update_status(...)` | method is `update_application_status` |
| `analyze("")` → `{'status': 'validation_error'}` | raises `EmptyJobDescriptionError` |
| `run_parallel_analysis(resume, job)` | second argument is a parsed analysis, not advert text |
| `POST /create-application` → 200 | **201 Created** |
| `POST /save-job {"job_id": "job_123"}` → 200 | **404** unless the id came from a recent `/discover-jobs` |
| `'total_applications' in data` for `/analytics` | nested inside `metrics` |
| `nodes_run > 0`, `nodes_failed == 0` | both are **lists** of node names |
| test files at the backend root | `pytest.ini` sets `testpaths = tests`; a root file is never collected |

Three more that are design problems rather than typos:

- **`assert time2 < time1`** to prove caching works. On work that takes 0.08 ms
  this is scheduler noise, and it passes just as often when the cache is
  broken. Replaced with assertions on the cache's own hit/miss counters.
- **`assert duration < 200`** with no unit given anywhere.
- **`scraper.search("AI Engineer", "Bangalore", limit=5)` inside a test.** That
  sends unsolicited traffic to four third-party job boards on every single test
  run — fails offline, gets rate-limited in CI, and makes strangers pay for
  your coverage. The suites inject a fake source instead.

And the Task 8 performance figures the brief asked to publish: job analysis
~16 ms, match ~15 ms, full analysis ~80 ms, caching speedup 3×. Measured:
**0.079 ms, 0.074 ms, 0.705 ms for five agents, 28.2×.** Between 5× and 200×
out. The measured numbers were published instead.

#### Two design decisions taken against the brief

**The pipeline is a new module, not a change to `complete_workflow.py`.** The
brief said to modify it. `run_complete_analysis` is deterministic, offline,
single-job, and has published callers — `/api/career/full-analysis`, the trace
endpoint, and four scripts. Putting live HTTP inside it would make it depend on
four job boards, turn 3 ms into several seconds, and make identical input
produce different output on different days. The pipeline *calls* the workflow
once per shortlisted job, which is what the brief's own step 3 describes.
Composition, not replacement.

**The pipeline does not apply on the user's behalf.** It saves jobs freely and
creates `draft` applications only when explicitly asked. Auto-creating a *sent*
application per discovered advert would put twenty attempts the user never made
into the denominator of every rate in the analytics — the interview rate would
collapse toward zero, and the number would be both discouraging and false.
`draft` is already excluded from those denominators, so a shortlist stays free.

Cost control: every advert is scored, because scoring is deterministic and
costs microseconds. Only the top `analyse_top` get the seven-agent run, because
that is where the time is.

#### Smaller things

- `_score_of` reads `job["match_to_user"]["score"]`. The first version read
  `job["match"]`, which does not exist, so the shortlist came back empty with
  no error — the pipeline reported `found 2 shortlist 0` and looked fine.
  Returns `-1.0` for an unscored advert rather than `0.0`, so "we did not score
  this" is distinguishable from "this scored zero".
- `user_id` on `/application/{id}/update-status` belongs in the **body**, not
  the query string. Sent as a query parameter it is silently ignored, the
  tracker looks the row up under the default user, and the endpoint answers 404
  for an application that plainly exists.
- `get_application(app_id, user_id)` — that argument order — and the record's
  status key is `current_status`, not `status`.
- `/api/health/full` returns `services[]` and `overall_status`, not `checks`.
- Coverage is **not** quoted anywhere. `pytest-cov` is not installed and a
  percentage produced without running the tool would be fiction. The command to
  measure it is given instead.

### Prompt 28 — 2026-08-31

*"Performance optimization, caching & speed"* — seven tasks with sample code:
a TTL cache, caching applied to the agents, RAG batching plus deduplication,
parallel agent execution, a performance monitor, a benchmark script, and a
README section with a table of expected timings.

**Nothing was implemented until the premises were measured.** Eight benchmark
scripts ran first. They falsified most of the brief and found a production bug
that had nothing to do with speed.

#### The premise did not hold

An optimisation pass assumes something is slow. Measured, warm, keyword path:

```
job_analyzer.analyze     2.28 ms
match.calculate_match    0.07 ms
gap.detect_gaps          0.21 ms
resume_optimizer         0.17 ms
interview_prep           0.06 ms
sum of five:             2.79 ms
```

Under three milliseconds for the whole pipeline. The brief's own target table
(job analysis 16 ms cached, match 15 ms, gap detection 22 ms, full analysis
100–150 ms) describes a system between five and fifty times slower than the one
that exists — every one of those "optimised" figures is *worse* than the
current uncached number. Those numbers were not copied into the README. Task 7
asked for a results table; it got one containing measurements, produced by
`utils/benchmarks.py`, which measures at run time rather than printing stored
values.

#### The real find: the vector store held three copies of everything

Discovered while checking an unrelated claim in Task 3.

```
total chunks in collection: 27
distinct chunks:             9
texts stored more than once: 9
wasted rows:                18
ids of one duplicated text: ['resume-2ba6fbd297df-profile:0',
                             'resume-e203e434bf18-profile:0',
                             'resume-fc465080ac36-profile:0']
```

The same resume, uploaded three times under three generated filenames. Nothing
compared content. Triple the embedding cost on write and triple the scan on
read are the cheap part. The expensive part is that identical chunks score
*identically*, so they occupy each other's slots in the result list:

```
python machine learning    asked for 5, got 5 rows, 2 DISTINCT facts
leadership and teamwork    asked for 5, got 5 rows, 2 DISTINCT facts
docker kubernetes          asked for 5, got 5 rows, 2 DISTINCT facts
```

Retrieval was delivering 40% of the information it reported. Every downstream
agent was reasoning from a truncated view of the resume, and no test failed.

Fixed with SHA-256 content addressing: the digest goes in chunk metadata, and a
chunk whose digest is already present is reused rather than re-embedded.
Verified on a clean collection:

```
upload 1: 7 chunks (7 written, 0 reused) | 8 rows | 7520.7 ms
upload 2: 7 chunks (0 written, 7 reused) | 8 rows |    6.5 ms
upload 3: 7 chunks (0 written, 7 reused) | 8 rows |    5.4 ms

python machine learning    5 rows, 5 distinct
docker kubernetes          5 rows, 5 distinct
```

A test was actively protecting this bug. `test_indexing_twice_keeps_both_copies`
asserted `count() == 2 * (chunks + 1)` — it pinned the observed behaviour rather
than a requirement, so the duplication looked deliberate. Replaced with four
tests that state what is actually wanted, including one that asserts search
returns distinct facts.

#### Faults in the brief, by task

**Task 1/2 — the cache**

1. `hash(str(args) + str(kwargs))` includes `str(self)`, which is a memory
   address: `<agents.match_calculator.MatchCalculator object at 0x10a732e50>`.
   Identical questions to different instances get different keys.
2. Far worse than a miss. CPython recycles addresses, so an object allocated at
   a freed address inherits the dead object's answers. Reproduced first try:
   ```
   address reuse: True
   keys collide:  True
   *** agent-B was served agent-A's result: {'answer': 'computed by agent-A'}
   ```
3. `hash()` on a string is randomised per process (PEP 456): `-5697988484137697972`,
   `-6476079098954559982`, `8735963763124557965` for the same input across three
   runs. Keys cannot survive a restart and cannot be asserted in a test.
4. Reducing a key to a 64-bit int and discarding the original makes collisions
   silent — two different adverts can share a slot with no way to detect it.
   The implementation stores a SHA-256 digest of the canonicalised arguments.
5. `if cached:` treats `{}`, `[]`, `0` and `None` as a miss. The expensive path
   then re-runs forever for exactly the inputs that produce nothing. A `MISS`
   sentinel is used instead; six parametrised tests pin it.
6. No size cap. An unbounded dict keyed on user-supplied text, on an endpoint
   needing no credentials, is a memory-exhaustion primitive. LRU with a cap.
7. No lock. FastAPI runs sync endpoints in a threadpool and `JobEnricher` has
   its own pool, so this is the live deployment, not a hypothetical. Expiry is a
   read-then-delete race.
8. `pickle` imported and never used.
9. Decorating `analyze` directly breaks the app. A hit skips the body, so
   `_last_description` is never set and `extract_requirements()` raises
   *"No job description available. Call analyze() first"* immediately after a
   successful `analyze()`. Reproduced, then fixed by caching a pure inner
   method and keeping the side effect outside it.
10. Caching `calculate_match` is not worth doing: building the key costs
    0.0110 ms, the work it avoids costs 0.0715 ms — 15.3% overhead before any
    lookup. Not cached.
11. No invalidation on `/api/career/clear`. Clearing the index while leaving
    analyses derived from it readable for two hours is a privacy control doing
    half its job. `clear_all()` is now wired in.

**A fault of my own, caught by the existing tests.** The first version keyed on
advert text alone, with a docstring claiming "the answer depends on nothing but
`cleaned`". Seven agent tests failed and were right to: the answer also depends
on whether a model is reachable. Keyed on text alone, the first analysis run
during an Ollama outage is replayed to everyone for two hours — keyword output,
`source: "fallback"`, no way to ask again. The key now includes a backend
fingerprint. Where the backend cannot be named — a caller injecting its own
client — the cache is bypassed rather than falling back to object identity,
which is the very bug the module exists to avoid.

Cached values are deep-copied in and out. Without that, one caller appending to
`result["required_skills"]` edits what every later caller receives. Copy costs
0.0195 ms; recomputing costs 2.2835 ms — 117x.

**Task 3 — RAG**

12. *"Currently embeds one by one"* is false. `_embed` already passes the whole
    list in one call. Batching is worth 19.2x (550.3 ms → 28.6 ms for 64
    chunks) and was already being had. `batch_size=32` is already the
    sentence-transformers default, so adding it changes nothing.
13. The suggested dedup, `hash(c) not in existing_hashes`, would silently never
    match after a restart — see fault 3. SHA-256 instead.
14. `results if r['distance'] > 0.3` is backwards. Chroma cosine distance is 0
    for best and 2 for worst, as this file's own `_to_similarity` docstring
    states. The filter keeps the *worst* matches and discards the best. Real
    distances here are 0.5661–0.5724, so it would have discarded everything.
    Not implemented.
15. `top_k=5` is already the default on `search_skills`.

**Task 4 — parallelism**

16. Threads are slower on the deterministic path: 0.363 ms serial vs 0.555 ms
    threaded, **1.53x slower**. The GIL prevents CPU-bound overlap and futures
    machinery is not free. The same pool on I/O-bound work (3 × 150 ms) is
    460.8 ms → 155.6 ms, **2.96x faster**. So the decision is made per call
    from whether a model is reachable, not hardcoded.
17. **The three agents are not independent.** `optimize_resume` and
    `prepare_interview` both take `gaps`. Fanning all three out starts two of
    them before gap detection has produced anything, and because those
    parameters are optional the agents degrade instead of failing:
    ```
    interview_prep    with gaps: 28 list items | without: 16
        questions                    5 -> 0
        weakness_questions           5 -> 0
        your_questions_for_them      5 -> 4
    resume_optimizer  with gaps: 27 list items | without: 23
    ```
    An interview pack containing no interview questions, returned as a success.
    The executor runs gap detection first, then fans out the two agents that
    genuinely are independent. `test_interview_prep_still_produces_questions`
    exists to fail if anyone reintroduces the flat fan-out.
18. A fresh `ThreadPoolExecutor` per call creates and destroys threads per
    request. One pool is created lazily and reused.

**Task 5 — monitoring**

19. `time.time()` is wall-clock and can be corrected backwards by NTP mid-call,
    producing negative durations. `time.perf_counter()` is monotonic.
20. `'status_code': 200` is invented. An agent method cannot know whether it is
    being called over HTTP, and the literal would read 200 on the failure path
    too. Dropped; `failures` is counted instead.
21. It duplicates `@observed` from Prompt 27. `@monitor_performance` was kept
    separate but narrow — it aggregates percentiles, where `@observed` logs
    individual events — and applied only to operations measured in
    milliseconds rather than microseconds (`rag.index_resume`, `rag.search`,
    `parallel_analysis`).

Percentiles are kept over a rolling window of 256 recent calls rather than as
an all-time mean, because a lifetime average is dominated by start-up outliers
and keeps reporting yesterday's behaviour after a regression.
`GET /api/health/performance` reports those alongside cache hit rates — a
speedup figure cannot reveal a broken cache, since a cache serving nothing
looks exactly like a fast application until the load arrives.

#### Result

2182 tests passing, ruff at the same 4 intentional findings, all 4 legacy
scripts OK.

### Prompt 27 — 2026-08-31

*"Production-grade error handling & resilience"* — six tasks with sample code:
a custom exception hierarchy, try/except in every agent returning a
`{status, data, confidence}` envelope, a retry decorator, structured logging,
health checks, and README updates.

I surveyed first, measured second, implemented third. The survey found that a
large part of the brief duplicated machinery this codebase already has, and the
measurement turned one design disagreement into a demonstrated fault.

**The decisive measurement.** The brief's `check_rag_system` proves Chroma is
reachable by calling `indexer.search_skills("test")`. On this machine:

```
cold count()   0.540 s  -> 27 docs
warm count()   0.0001 s
then search    8.19  s  (loads the embedding model)

first search   9.16  s
second search  0.0115 s   -> the first search costs 797x the second
```

A search is roughly **fifteen times the cost of `count()` to establish the
identical fact**, on an unauthenticated endpoint whose entire purpose is to be
polled. Two consequences, both bad: a cheap GET buys expensive work, which is a
DoS amplifier; and a load balancer with a 5 s probe timeout marks a *healthy*
instance dead, restarts it, and meets the same ~8 s model load on the next
probe — a self-sustaining restart loop that only fires under the conditions where
you least want one. The probe calls `count()`.

**Faults found in the brief.** Seventeen, grouped:

*The envelope (task 2)*
1. It is a breaking change to ~2,000 tests. Every agent returns a plain domain
   dictionary that workflow nodes read positionally; wrapping it breaks every
   caller.
2. It is internally inconsistent: the usable answer lives in `data` on success,
   in `fallback` on `validation_error`, and in `data` meaning something else on
   `llm_error`. Three places to look guarantees a consumer eventually reads the
   wrong one — and the resulting bug is a *missing section*, not a crash, so it
   survives to production.
3. It hardcodes `'confidence': 0.95`. The agents already compute earned
   confidence. A constant is wrong precisely when it matters most: a fallback
   answer would still claim 0.95.
4. `if len(job_description) < 50: raise` contradicts this project's established
   rule — coerce at the boundary (`utils/validation.py`) — and `job_analyzer`
   already has `EmptyJobDescriptionError` and `MalformedJobDescriptionError`.

*The retry decorator (task 3)*
5. It retries bare `Exception`, including validation errors and 404s that can
   never succeed, converting a 2 ms rejection into a 2 ms rejection plus ~3 s of
   sleeping while a user waits.
6. With `max_attempts=0` the loop returns `None` and reports success without
   ever having run.
7. No jitter, so every client that failed together returns together and keeps a
   struggling server down.
8. It logs `Attempt 1/3` at INFO before every attempt, tripling log volume for
   calls that succeed.

*Structured logging (task 4)*
9. `StructuredLogger` has no `.info()`/`.warning()`/`.error()`. Swapping it in
   for `get_logger` breaks all 108 existing calls with `AttributeError` — on the
   error paths, i.e. when something has already gone wrong.
10. It hardcodes `'data/logs/app.log'`, which is cwd-dependent. **This project
    already fixed exactly this class of bug** (see the `./data/chroma` entry
    below).
11. It adds handlers in `__init__`. `logging.getLogger(name)` returns the same
    object, so a second construction doubles every line.
12. `json.dumps(details)` raises `TypeError` on a `datetime`, `Path` or `set`.
    A logging call that raises inside `except` destroys the original error.

*Health checks (task 5)*
13. `check_llm` sends a real prompt, against `LLM_TIMEOUT_SECONDS = 120`. An
    unauthenticated GET can occupy a worker for two minutes, and costs money per
    call on a hosted provider.
14. The probes are `async def` with blocking bodies, so `asyncio.gather` gives
    zero concurrency *and* stalls the event loop for everyone.
15. It returns `str(e)` to unauthenticated callers — OWASP A01/A05. Exception
    text here routinely carries absolute paths, connection strings and, for this
    application, resume text.
16. It returns 200 even when degraded. Orchestrators key off status codes, so a
    load balancer keeps routing to a broken instance.
17. It treats a missing LLM as `unhealthy`. This app is designed to work with no
    model at all; that would pull correct, serving instances out of the pool.

**What I built instead.**

*Task 1 — retrofit, not addition.* Seven new base classes that nothing raises
would be decoration. `IndexerError`, `AgentError`, `ScraperError`,
`ApplicationError` and `LLMError` were re-parented onto the new bases, and the
local duplicate `LLMError` in `ollama_handler.py` was deleted so there is one
class rather than two with one name. All 16 deliberate exceptions are now
catchable as `CareerPilotException`; `IndexerError` is still a `RuntimeError`
and `UnknownApplicationError` is still a `KeyError`, so no existing `except`
clause catches less than before. `tests/test_error_handling.py` asserts both
halves class by class, including
`test_the_llm_error_name_means_one_class_on_both_import_paths`.

`utils/error_handling.py` also documents the pydantic `ValidationError`
name-collision trap, and provides `classify`, `envelope` and `safe_call` for
callers who *do* want a uniform result — `safe_call` reads the real confidence
out of the result (normalising >1.0 values) instead of inventing 0.95, and puts
the fallback in `data` so there is never a second place to look.

*Task 2 — return shapes deliberately unchanged.* Documented above; instead each
agent entry point carries `@observed(...)`, which logs operation, outcome and
duration as JSON and re-raises untouched. Applying it to all seven agents and
re-running the suite gave **2,099 passing, zero changes needed** — which is the
evidence for the decision, not just the argument for it.

*Task 3 — a narrow allow-list.* `RETRYABLE_BY_DEFAULT = (OSError,)`;
`give_up_on` is checked before `retry_on`; waits are capped at 30 s and jittered
by `random.uniform(0, wait * 0.1)`; `max_attempts < 1` raises at **decoration**
time so the silent-`None` success cannot exist. Wired into `HttpFetcher` at the
single HTTP choke-point: `raise_for_status()` was replaced with explicit
branching so 429 and 5xx become a retryable `_TransientHTTPError` while 4xx and
redirect loops stay a plain `ScraperError`. All 64 existing scraper tests still
pass.

*Task 4 — wrap, don't replace.* `StructuredLogger` delegates unknown attributes
to the wrapped logger, attaches no handlers, uses `settings` paths, and passes
`default=_stringify` to `json.dumps` so logging cannot raise.

*Task 5 — cheap, concurrent, and quiet about details.* Synchronous probes run
through `run_in_executor` with a 5 s timeout and gathered. Live:

```
status: 200 | wall 441 ms | overall: degraded
  rag       healthy   438.4 ms  indexed_chunks 27
  llm       degraded  235.1 ms  ollama
  database  healthy    20.0 ms
  report 439.0 ms vs sum of probes 693.5 ms  -> genuinely concurrent
```

The database probe uses the public `count_applications()` rather than the
private `_connect`. Failures return `error_type` and an 8-char `error_id`; the
full detail goes to the log only. Two app-level handlers were added to `main.py`:
`CareerPilotException` → 500 with its message (these are written for humans and
are safe), and bare `Exception` → 500 with `"Internal server error."` and an id.

**Bugs found in my own code, by my own tests.** `retry_handler` crashed while
reporting an error: `func.__name__` raises `AttributeError` for callable
objects, `functools.partial`, and some builtins — so the resilience module would
have replaced a real error with a bogus one at the worst possible moment. Caught
by a test that retries a callable class; fixed with a `_name()` helper. Also
`.env.example` drift, caught by
`test_the_example_file_documents_every_setting`, which exists for exactly that.

**Ruff.** The new `Exception` handler triggered a fifth ARG001 on the unused
`exc`. Rather than claim a fifth exemption, the handler now logs
`type(exc).__name__` — genuinely useful in a log, and safe, unlike the message.
Back to the four intentional findings.

**Result:** 2,113 tests passing, ruff at exactly 4 intentional findings, all
four legacy scripts OK.

---

### Prompt 26 — 2026-08-31

> Week 2 Part 4 — advanced LangGraph: conditional workflow, agent
> collaboration, multi-step reasoning, learning path generation, decision trees.

Four new modules (`advanced_workflow`, `conditional_graph`,
`agent_collaboration`, `learning_path_agent`), 95 new tests. Suite 1896 → 1995,
ruff steady at the 4 intentional findings, all four legacy scripts still OK.

#### The decisive experiment: what is the rewrite actually worth?

The point of `re_calculate_match` is to score the resume again after optimising
it and report the improvement. Before wiring it up I measured where the
improvement comes from:

```
baseline            : 73.6 MAYBE
+truthful keywords  : 73.6 MAYBE | added ['Docker', 'Next.js', 'Machine Learning']
+BLOCKED (dishonest): 93.7 APPLY | added ['CI/CD', 'LangGraph', 'Pinecone']
```

The whole twenty-point uplift is the three skills the optimiser refuses to let
the user claim. The honest rewrite is worth exactly zero points on this pair.

That result shaped the node. It filters `keywords_to_add` against the gap report
before re-scoring, writes the result to `projected_match_score`, and **never
touches `match_score`**. The verdict is computed from the real score on every
path. `test_the_rescore_never_claims_a_blocked_skill` pins it.

The uncomfortable consequence is that `optimized_match` shows no uplift on the
sample pair. That is the finding, not a failure to find one.

#### Five faults in the brief

1. **`gaps` is unbound when match ≥ 70.** The Task 1 pseudocode assigns `gaps`
   inside `if match.score < 70:` and reads it unconditionally afterwards. The
   sample resume scores 73.6, so this is an `UnboundLocalError` on the project's
   own sample data.
2. **The Task 3 graph reaches `detect_gaps` only down one arm**, then routes
   both arms into `check_gaps_learnable`, which reads the gap report.
3. **`optimize_resume` is ordered before `detect_gaps`**, but the optimiser
   takes the gap report as input — that is how it builds
   `keywords_blocked_by_gaps`. Running it first empties the guard that stops it
   suggesting you claim skills you lack.
4. **Task 1 and Task 3 disagree on which gaps count.** Task 1 uses critical gaps
   only; Task 3 sums `g['days']` over all gaps. On the sample that is 17 days
   versus considerably more, which flips the branch.
5. **`if learning_time <= 14: APPLY_AFTER_LEARNING` is degenerate at both
   ends.** Zero gaps sums to zero, and zero ≤ 14, so the strongest candidates
   are told to wait a fortnight and study nothing. And an 88% match with one
   three-day gap is told to delay a live application for it.

Fixes: gaps are detected before the branch, the optimiser runs after the gap
detector, critical gaps only, and the timing rule treats an advert as something
that expires — study that can proceed in parallel is not grounds for delay.

#### Five bugs in my own code

1. **A self-contradicting headline.** "Apply now — nothing here is worth waiting
   for" printed directly above "3 critical requirement(s) unevidenced, about 17
   day(s) of study." `_headline` now branches on the day count.
2. **Silent verdict disagreement.** The advanced path said `APPLY_NOW` while the
   scorer said `MAYBE`, same input, no explanation. They answer different
   questions — fit versus timing — so `_reconcile()` now says so out loud:
   *"That is not a contradiction: it is borderline, and if you are going to
   apply, now beats waiting."*
3. **The learning plan padded to fill the window.** Nine days of work spread
   across fourteen produced "FastAPI in more depth (day 1 of 6)" through "(day 6
   of 6)". Now `span = min(window, needed)`, with the slack reported as slack.
4. **The accountable payload was discarded.** The advanced final node replaced
   `generate_recommendation`'s output instead of layering onto it, losing
   `scored_decision`, `adjusted`, `next_steps` and `confidence`. **Caught by the
   existing suite** — this is what the older tests were for.
5. **Trace step numbers had holes.** A branching run traced steps
   1,2,3,4,5,**7**,**9**,10, which reads as two lost steps rather than two
   skipped nodes. Numbering now comes from the trace length. **Caught by a test
   I wrote**, on output the live run had already printed and I had not noticed.

#### `estimate_effort` agreed to almost anything

Found while capturing README output. Given a bare skill name and no day count,
`_skill_and_days` fell through to `max(0, 1)` — one day — so "CI/CD in 2 days"
came back as a comfortable two hours. The gap detector's own table puts CI/CD at
ten days. It now consults `BASE_LEARNING_DAYS` and falls back to
`DEFAULT_LEARNING_DAYS` (30) for skills it does not know:

```
CI/CD in 2 days  -> fits False | ... 10.0 hours a day, which is not a schedule
                    anyone keeps. It needs about 10 days at a sustainable pace.
Fortran in 14    -> 60 hours (unknown skill, default 30 days)
```

#### Collaboration is delegation, and says so

`AgentCollaboration` records `{step, from, to, question, answer, status,
duration_ms}` for each exchange. The module docstring is explicit that these are
**structured delegations with a recorded transcript, not autonomous
negotiation** — nobody argues back. Calling it "collaboration" without that
sentence would oversell it. Every call is wrapped; an agent that raises records
`failed` and the run continues.

#### No invented URLs

The brief asked for YouTube and Medium links. Neither has a verified URL, so
neither is generated. `find_best_resources` returns the categories it could not
fill in `missing`, plus `search_for` terms, plus a note explaining that a
confidently wrong link is worse than none.

#### Compatibility

`run_complete_analysis(advanced=True)` is the default. Verified on the sample
pair: **zero legacy keys missing, identical `match_score` of 73.6 on both
paths**, and `_run_sequentially()` takes the same branch decisions as the
LangGraph build. On exception the wrapper logs a warning and falls back to the
linear pipeline.

Four tests in `test_main.py` asserted a fixed seven-node list. Those were not
regressions — they were assertions only ever true of the old shape — so they
became branching invariants: first five nodes fixed, last node one of two, total
between 7 and 10, no underscores in display names.

Measured after the change: the branching run is **faster** than the linear one
(21–23 ms vs 30–36 ms) despite having more nodes available, because it skips two.

### Prompt 25 — 2026-08-31

> Week 2 Part 3 — application tracking, analytics and a dashboard.

Three modules (`application_tracker`, `application_analytics`,
`application_dashboard`), eight Pydantic models, six endpoints, 211 new tests.
Suite 1677 → 1896, ruff steady at the 4 intentional findings, all four legacy
scripts still OK.

#### The tracker stores a timeline, not just a status

The brief asked for `update_application_status`. A status field alone cannot
answer "how long do replies take?" — that needs the moment of each transition,
so `application_events` is the primary record and `applications.status` is a
denormalised convenience. Events are also finer-grained than statuses:
`interview_scheduled` and `interview_completed` both leave you in `interview`,
and collapsing them would lose the distinction. The brief's own example calls
`update_application_status(app_id, "interview_scheduled")` — passing an event
name where a status is wanted — so `STATUS_ALIASES` accepts both and logs the
word the caller actually used.

#### Four inventions the analytics module refuses

Each of these was produced by an earlier version of the code and caught by
running it against realistic data. Unit tests did not catch any of them,
because each one is a *correct* computation of a meaningless quantity.

**"Offer rate: below 100%."** The rule of three on two trials. Arithmetically
right, informationally empty. `_rule_of_three` now returns `None` below four
trials.

**"Offer rate: 0%" with no warning**, sitting under an interview rate computed
from a different denominator — interviews divide by applications, offers divide
by interviews, so "0% from 2 interviews" was being presented with the same
confidence as "25% from 8 applications". A fourth warning tier now fires when
the offer rate rests on fewer than five interviews.

**"86% chance of an offer next month"** from twenty applications created in one
sitting. `_applications_per_month` read a single afternoon as a pace of twenty
a month. It now returns `None` when the applications span under 14 days, and
the forecast is withheld with a sentence explaining why.

**"LangGraph is missing in 3 of your 3 rejections."** The subtlest of the four,
and it survived the first round of fixes. The docstring said a gap should only
be named when it appears in rejections *more than elsewhere* — and the code
never performed that comparison. A skill you do not have is missing from all
your rejections and all your interviews alike; the count is evidence of
nothing. `_discriminating_gap` now requires a 25-point lift over the
non-rejected applications, and the realistic run promptly switched from
LangGraph (in all 12 applications) to Kubernetes (in 3 of 3 rejections, 0 of 9
others) — which is an actual finding.

That fix exposed a fifth problem: the next-step list still named the *most
frequent* gap, so the output read "Kubernetes has the clearest link" directly
above "close the gap that recurs most: LangGraph". Both now read one shared
computation, so they cannot contradict each other. When no gap discriminates,
the step says so in as many words rather than implying a link that is not
there.

#### The forecast carries its own uncertainty

`54%` is the honest projection of 1 offer from 12 applications at the observed
pace. But that 11% offer rate has a 95% interval of 2%-35%, and pushing those
bounds through the same arithmetic gives **13%-96%**. Reporting `54%` alone
would overstate what twelve applications can support, so
`offer_probability_confidence_95` is returned beside it. A range covering most
of the scale is itself the useful signal.

#### An ordering bug the tests caught

`get_application_history` sorted by `datetime(created_date) DESC, app_id DESC`.
Timestamps are stored to the second, so applications created in the same second
tie — and the tiebreaker was a random UUID. Several applications created in one
sitting came back in arbitrary order, and the dashboard reshuffled them on every
refresh. Now `rowid DESC`, which is deterministic insertion order.

#### Deviations from the brief

- `days_to_interview` is reported as a mean **and** a median; a single
  three-month outlier drags the mean somewhere no application actually sits.
- `best_job_type` returns `None` until a title has produced two interviews. One
  success is not a pattern.
- The interview rate excludes drafts from the denominator — an application never
  sent cannot have failed to get an interview.
- `interview_prep_score` is `None` when never measured, so the dashboard's
  "preparation" line is absent rather than showing the brief's `"60% complete"`
  against nothing.

### Prompt 24 — 2026-08-31

> "completely done with part 2 ?"

A verification question, answered by auditing the code against the original
brief method by method rather than by asserting from memory. The audit found
two things worth fixing, one of them a genuine bug that had been suppressing
real data.

#### The salary parser was silently failing on the commonest format

`_SALARY_CONTEXT` required a money word or symbol near the figures. The
symbols were written inside a word-boundary group:

```python
r"(?i)\b(salary|compensation|pay|...|\u20b9|\$|\u00a3|\u20ac|usd|...)\b"
```

`\b\$\b` can never match. `\b` asserts a word character on one side, and `$`
is not one, so every symbol in that group was dead weight. The practical
effect: an advert reading `Remote role. $80k-$120k` contained no money
*word*, so the check failed and the advert was reported as stating no salary
at all.

| Advert text | Before | After |
| --- | --- | --- |
| `Salary: $120,000 - $160,000` | `$120000-160000` | unchanged |
| `Remote role. $80k-$120k` | **`None`** | `$80k-120k` |
| `$80k - $120k` | **`None`** | `$80k-120k` |
| `Salary 50000-70000` | **`None`** | `50000-70000` |
| `Range: 80000-120000 EUR` | **`None`** | `80000-120000` |
| `₹15-25 LPA` | `15lpa-25lpa` | `₹15-25 LPA` |

Three separate faults sat behind those rows:

1. The word-boundary bug above.
2. `₹` was absent from the currency character class, and a word unit was
   pasted onto both figures — nobody writes `15lpa-25lpa`.
3. Unpunctuated figures matched no alternative, because `\d{1,3}(,\d{3})*`
   consumed `500` of `50000` and then failed. Adding `\d{4,7}` was not
   enough: it had to go **first** in the alternation, otherwise the greedy
   shorter branch matched `700` of `70000` and the range was discarded as
   `high <= low`.

Widening the pattern introduced a false positive, which is the failure mode
that actually matters here — an invented salary is worse than a blank one:

```
"Salary depends on experience. We have 10000-20000 users."  ->  '10000-20000'
```

The word "salary" was inside the 60-character context window, so a headcount
became a pay band. Fixed with `_COUNT_NOUN_AFTER`, which rejects a range
immediately followed by a countable noun (`users`, `clients`, `sq ft`, and
so on). Twelve negative cases are now pinned by tests, including this one.

Confirmed against the live boards afterwards — and the fix immediately
recovered data that had been dropped:

```
found 12 from ['Arbeitnow', 'HackerNews', 'Remotive', 'WeWorkRemotely']
adverts stating pay: 2/12
   Various Software Engineering Roles      $150k-260k
   Full Stack Engineer                     $100k-130k
```

Both are the `$Xk-$Yk` form. Before this fix, both reported no salary.

#### `self.session` restored as a property

The brief's sketch held `self.session = requests.Session()` on the scraper.
The implementation moved the session into `HttpFetcher` so that tests can
inject a plain callable and never open a socket — that design is why the
whole suite runs offline, and it stays. But the attribute the brief named is
now reachable:

```python
@property
def session(self) -> Any:      # the pooled Session, or None for a stub fetcher
```

It returns `None` rather than fabricating a session when the fetcher is a
test stub, because pretending a network object exists where none does would
be a lie in the API surface.

#### Audit result against the brief, task by task

| Brief item | State |
| --- | --- |
| `fetch_jobs_hacker_news`, `fetch_jobs_rss`, `fetch_jobs_github`, `search_multiple_sources` | present, signatures match |
| `self.sources`, `self.session` | both present |
| `enrich_job` seven analysis keys | all seven present |
| `batch_enrich_jobs` (10 concurrent), `categorize_jobs` | present |
| `save_job`, `get_user_saved_jobs`, `update_job_status`, `get_jobs_by_status` | present, signatures match |
| three endpoints | present |
| README "Week 2" section | present |

Three shape choices differ from the brief's sample JSON, deliberately:

- The job key is `job_id`, not `id`. Carrying two names for one identifier
  invites them to drift apart.
- `match_to_user` is an object, not the string `"78%"`. It carries
  `score` (a float, sortable), `percentage` (`"78%"` — the brief's string,
  kept), `recommendation`, `matched_skills` and `missing_skills`. The
  brief's value is a subset of it.
- `categorized` returns buckets of jobs **and** a `counts` sub-key holding
  the brief's shape, so a caller can have either.

**Tests:** 1677 passing, up from 1662. **Ruff:** the same 4 intentional
findings.

### Prompt 23 — 2026-08-31

> "WEEK 2 PART 2: ETHICAL JOB SCRAPING & DATA ENRICHMENT … discover real job
> postings."

Three new modules, three new endpoints, four new test files. The interesting
part of this prompt was not the code; it was that **most of the sources the
brief named no longer exist**, and that several security assumptions turned
out to be wrong when measured rather than reasoned about.

#### The sources were checked before any code was written

Every candidate source was probed with `curl` first. The result:

| Source | Status | Outcome |
|---|---|---|
| Hacker News "Who is hiring?" (Algolia) | `200` | **Used** |
| WeWorkRemotely RSS | `200` | **Used** |
| Remotive API | `200` | **Used** |
| Arbeitnow API | `200` | **Used** (via `www`, see below) |
| **GitHub Jobs** | DNS does not resolve | **Dead** — retired 2021‑08‑19 |
| **dev.to jobs** | `/feed` is `200` but returns *articles* | **Dead** — board discontinued |
| **Stack Overflow Jobs** | `404` | **Dead** — shut down 2022 |
| **RemoteOK RSS** | `410 Gone` | **Dead** |
| **LinkedIn** | `404` | **Refused** — see below |

Three of the four sources the brief asked for are gone. `fetch_jobs_github()`
still exists so that code written against the original interface does not
break, but it returns `[]` and logs why. It deliberately does **not** quietly
return adverts from a different board: a method named after GitHub returning
Remotive data would be a lie that is very hard to notice.

**LinkedIn is refused on principle, not merely because the URL 404s.** Their
terms of service prohibit automated collection. A scraper that ignores that is
not "ethical scraping" whatever the module is called.

#### Remotive's terms are enforced in code, not just quoted

Remotive's own API response carries a legal notice asking that callers credit
them, link back to the original posting, and fetch "a couple of times a day
(we advise max. 4 times a day)". So:

* every job keeps its `source` and `url` — attribution cannot be dropped;
* `SOURCE_TERMS` carries the condition through to the API response, so a
  client can honour it without reading Remotive's terms itself;
* `JOB_CACHE_TTL_SECONDS` defaults to six hours, which is four fetches a day.

The cache is how the promise is kept rather than merely made.

#### Security controls, and the measurements behind them

**SSRF.** `_validate_url()` runs before every request: HTTPS only, host must
be on a five-entry allow-list, port 443 only, and every address the host
resolves to must be public. All addresses are checked, not just the first,
because a name that returns one public and one private record would otherwise
slip through and DNS ordering is not ours to control. This is what stops
`http://169.254.169.254/latest/meta-data/` — the cloud metadata service —
being fetched on a caller's behalf. Redirects are **not** followed for
content, because a redirect can point anywhere.

**Entity expansion — measured, not assumed.** Before writing the XML handling,
a billion-laughs document was fed to the stdlib parser to find out what it
actually does:

```
=== XML bomb test (stdlib ElementTree) ===
PARSED, text len = 300
```

`xml.etree.ElementTree` **does** expand internal entities, so a ~400-byte feed
can become gigabytes. `_parse_xml()` therefore refuses any document declaring
a `DOCTYPE` or `ENTITY` at all. Guessing here would have produced either an
unnecessary restriction or a live vulnerability.

**Other limits.** Responses are read in chunks against `JOB_FETCH_MAX_BYTES`
rather than trusting `Content-Length`; one request per host per second; and
`<script>`/`<style>` contents are dropped with their tags — verified, because
stripping only the tags left the text `alert(1)` sitting in a job description.

#### Five bugs the live run found that the tests did not

Writing tests first would not have caught these; only running against the real
internet did.

1. **robots.txt handling was backwards, and disabled three of four sources.**
   `RobotFileParser.read()` fetches using *urllib's* User-Agent, which
   WeWorkRemotely answers with `403`; the parser records that as *disallow
   all*. A site whose robots.txt literally reads `Allow: /` was being skipped.
   Now robots.txt is fetched under our own honest User-Agent and RFC 9309
   §2.3.1 is followed properly: `200` parse and obey, `4xx` treat as
   unrestricted, `5xx`/unreachable assume disallow. The 4xx rule is the
   counter-intuitive one — refusing there feels cautious but is simply wrong,
   and it was silently disabling Remotive, which sits behind a CDN that
   answers `403` to unattended requests for robots.txt.
2. **NAT64 addresses were rejected as private.** On this machine
   `hn.algolia.com` resolves to `64:ff9b::22a0:a8b5`, which `ipaddress` does
   not consider globally routable, so *every* fetch was refused. `_unwrap_nat64()`
   extracts the embedded IPv4 and checks that instead — which is also the
   safer reading, since the embedded 32 bits are the real destination. A NAT64
   address wrapping `127.0.0.1` still fails.
3. **A search for 10 jobs returned 10 Hacker News comments** despite having
   collected 45 adverts across four boards, because results were concatenated
   and then sliced. Now interleaved round-robin, so a limit spans the sources.
4. **A hand-written HTML entity table missed numeric references.** A live
   advert came back titled `https:&#x2F;&#x2F;govstar.us`. Replaced with
   `html.unescape`, plus normalisation of the resulting `U+00A0` — which is
   not an ordinary space and would have broken skill matching invisibly.
5. **Arbeitnow's apex host 301s to `www`.** Since content redirects are not
   followed by design, the canonical host is named in the allow-list instead.

Two further bugs were caught by the first smoke test: an operator-precedence
error where `"%s" % (...).strip()` applied `.strip()` to the tuple, and an
off-by-one in the `UPDATE` bindings in `save_job` (10 placeholders, 11
parameters).

#### `agents/job_scraper.py`

`JobScraper` takes an injectable `fetcher`, which is what lets the entire test
suite run offline. Sources: Hacker News, WeWorkRemotely RSS, Remotive,
Arbeitnow. Nothing here scrapes HTML — only documented APIs and RSS feeds.

Hacker News needs one non-obvious rule: only **top-level** comments
(`parent_id == story_id`) are adverts. Replies are discussion. Without that
filter the results included "Nothing wrong really if the python in turn uses…".

Job ids are a SHA-256 of the advert's URL (or of source/title/company when
there is none), so the same advert keeps the same id across searches. A random
id would have filled the store with duplicates.

#### `agents/job_enricher.py`

Analyses each advert and optionally scores it against the resume, across a
thread pool that **preserves input order** — threads finish out of order and a
reshuffled list would be a silent bug.

Three deliberate choices about not lying:

* `estimated_salary_range` is `None` when the advert does not state one. An
  invented band is worse than a blank. Date ranges and team sizes are rejected
  as salaries.
* `remote` is a **tri-state**: `True`, `False`, or `None` for "not stated".
  "Not stated" is not the same as "not remote".
* An unscored job goes in an `unscored` bucket, not in `learning_needed`.
  Filing "not compared" under "poor fit" would be a lie.

`_difficulty()` reads the title as well as the `seniority` field, because the
analyzer's fallback path often leaves that field blank — which had a "Senior
AI Engineer" reported as `EASY`.

#### `agents/job_storage.py`

SQLite. Every query is parameterised; the `status` filter is additionally
checked against a fixed set, and `LIMIT` is bound and clamped to 1–1000 rather
than interpolated.

**`user_id` is a namespace, not a credential.** This application has no
authentication, so anyone who can reach the API can pass any user id and read
those rows. That is fine on a laptop and not fine deployed, and it is written
down here and in the module docstring rather than left implied by the
parameter's name. It is still validated — the absence of authentication is no
reason to also hand out SQL injection.

Saving the same advert twice updates the row rather than duplicating it, and
**preserves the existing status**: someone who saved a job, marked it applied,
then saved it again from a fresh search would otherwise silently lose that.

Schema:

```
jobs(job_id PK, user_id, title, company, description, requirements, analysis,
     source, url, posted_date, saved_date, updated_date, status, match_score, notes)
idx_jobs_user, idx_jobs_status
idx_jobs_user_url UNIQUE (user_id, url) WHERE url <> ''   -- partial: URL-less
                                                          -- HN comments stay distinct
```

#### Endpoints

| Endpoint | Notes |
|---|---|
| `POST /api/career/discover-jobs` | **No field for a feed URL.** Letting a caller name the address to fetch would turn this into an open proxy onto the server's own network. Sources are chosen in code. |
| `POST /api/career/save-job` | Takes an id, not a job body — so a caller cannot write arbitrary content into the store. Resolved against a bounded (200) cache of recently discovered adverts. |
| `GET /api/career/my-jobs` | Optional `status` filter; returns counts for every status including zeros. |

With no resume indexed, discovery returns `200` with `scored_against_resume:
false` and null scores rather than refusing — the adverts are still worth
having — and `_resume_data_or_none()` hands the matcher `{"resume_text": …}`,
the shape it documents.

#### Validation

```
pytest                 → 1662 passed in 9.33s   (was 1492)
ruff (source scope)    → 4 errors, all intentional and unchanged
test_week1.py          → OK      test_api.py               → OK
run_test.py            → OK      test_complete_workflow.py → OK
```

Live search, four sources, evenly interleaved:

```
Search 'python': 45 advert(s) from 4 source(s)
found: 12 | {'HackerNews': 3, 'WeWorkRemotely': 3, 'Remotive': 3, 'Arbeitnow': 3}
  [HackerNews    ] Various Software Engineering Roles  @ Prophet Town LLC
  [WeWorkRemotely] Python Backend Development Talent   @ Toptal
  [Remotive      ] Senior React Full-stack Developer   @ Lemon.io
  [Arbeitnow     ] Backend Engineer (Energy & AI)      @ einklang
```

New settings (all documented in `.env.example`): `JOB_DISCOVERY_ENABLED`,
`JOBS_DB_PATH`, `JOB_SCRAPER_USER_AGENT`, `JOB_FETCH_TIMEOUT_SECONDS`,
`JOB_FETCH_MAX_BYTES`, `JOB_FETCH_MIN_INTERVAL_SECONDS`,
`JOB_CACHE_TTL_SECONDS`, `JOB_RESPECT_ROBOTS`. `requests` was promoted from an
undeclared transitive dependency to a pinned direct one, since this code
imports it directly.

New test files: `tests/test_job_scraper.py` (63), `tests/test_job_enricher.py`
(34), `tests/test_job_storage.py` (48), `tests/test_job_endpoints.py` (25).
All offline — tests that hit the network are not tests, they are a way of
finding out that someone else had an outage.

---

### Prompt 22 — 2026-08-31

> "WEEK 2 PART 1: ENHANCED AGENTS WITH SMARTER REASONING … Week 1 had basic
> agents. Week 2 makes them SMART."

**Headline: most of what was requested already shipped in week 1.** Before
writing anything, all three agent modules were inventoried method by method.
Nine of the twelve requested methods already existed, several under different
names and several implemented more carefully than the brief's sample code. The
work below is therefore what was genuinely missing, plus three documented
refusals.

#### Already present — not rebuilt

Building `_calculate_learning_time_smart` next to `_estimate_learning_time`
would have produced exactly the kind of duplicate the prompt-20 cleanup was
spent deleting. Each of these was verified, not assumed:

| Requested | Already exists as | Notes |
|---|---|---|
| `_calculate_learning_time_smart` | `_estimate_learning_time` + `_find_similar_skills` (`gap_detector.py:490,507`) | Existing version is finer-grained: factor 0.35 / 0.5 / 0.7 by family tightness and count, not a flat halving, over ~90 skills rather than 8 |
| `_prioritize_gaps_by_impact` | `_prioritize_gaps` (`gap_detector.py:513`) | Sorts on `(importance, -mentions_in_job, learning_time_days, skill_id)` — the three requested factors, plus a deterministic tiebreak |
| `_estimate_quick_wins` | `_quick_wins` (`gap_detector.py:709`) | Threshold is `QUICK_WIN_DAYS = 7`, not 5; left alone deliberately, see below |
| `_keyword_density_analysis` (partly) | `_generate_keyword_suggestions` (`resume_optimizer.py:411`) | Counted advert mentions but never exposed the resume-side count — that half was missing and has been added |
| `_personalize_summary` | `_create_tailored_summary` (`resume_optimizer.py:440`) | Already personalised from resume, match and advert |
| `_generate_follow_up_questions` | `_generate_follow_ups` (`interview_prep.py:849`) | Up to 4 per question already |
| `_create_prep_schedule_smart` | `_create_prep_schedule` (`interview_prep.py:937`) | Already ordered by return on effort, capped at a sustainable 2.5h/day |
| `_predict_actual_success_rate` | `_predict_success_rate` (`interview_prep.py:1016`) | Formula already accounts for match, critical gaps and difficulty |
| Confidence scores (task 4) | `confidence` on optimiser and interview prep | Both already returned 0.0–1.0 |

The quick-win threshold stayed at 7 days rather than dropping to 5 because the
brief contradicted itself — the prose said "under 5 days" while its own worked
example marked "Docker (5 days)" as a quick win. Seven days is one week, which
is a unit a candidate can actually plan around.

#### Genuinely new

**1. Curated documentation links and practice projects** (`gap_detector.py`)

Each gap now carries `documentation` and `practice_project`. `_DOC_URLS` holds
19 links and `_PRACTICE_PROJECTS` holds 28 project ideas; a skill in neither
table gets `None` rather than a guess, so a caller can distinguish "we have
nothing" from "here is something plausible".

**2. Keyword density table** (`resume_optimizer.py`)

New `keyword_density` output showing both counts side by side, so the reader
can disagree with the verdict:

| Keyword | Resume | Advert | Verdict |
|---|---|---|---|
| Git | 1 | 3 | under-used |
| LangChain | 4 | 3 | balanced |
| LangGraph | 0 | 3 | gap |

Counting uses `_count_word`, which bounds matches with `(?<![a-z0-9])` /
`(?![a-z0-9])` rather than `\b` — `\b` mishandles `c++`, `ci/cd` and `node.js`,
and naive substring counting finds "Go" inside "Django".

A skill the candidate cannot claim is still listed, because the count is the
proof it matters; only the *action* changes, from "add it" to "learn it".

**3. Strength / weakness question split** (`interview_prep.py`)

`strength_questions` and `weakness_questions` are views over the existing
numbered `questions` list, filtered on the `category` field — the same dict
objects, not renumbered copies, so "question 7" means one thing everywhere. A
test asserts identity, not equality, to keep it that way. Caps raised from 8/4
to `MAX_TECHNICAL_QUESTIONS = 10` and `MAX_GAP_QUESTIONS = 5` as requested;
they remain ceilings, so a thin resume still yields a short list rather than
padding.

**4. Success-rate reasoning** (`interview_prep.py`)

New `success_rate_reasoning` breaks the prediction into factors, each with an
effect and a plain-English why:

```
SUCCESS: 49%
   Resume match         +74%   Your resume scored 73.6% against this advert.
   Critical gaps        -15%   3 required skills missing; each one is a question you cannot answer from experience.
   Interview difficulty -10%   A senior or heavily-specified advert screens harder.
```

**5. Input coercion across all four agents** (`utils/validation.py`, new)

This was the one part of task 4 that turned out to be a real defect rather than
a box to tick. A fuzz probe of every agent against nine malformed inputs in
both argument positions found **176 crashes out of 324 combinations**, nearly
all `AttributeError: 'NoneType' object has no attribute 'get'` raised partway
through a run, discarding the stages that had already succeeded.

`as_dict` / `as_list` / `as_float` / `as_int` coerce shape at each entry point.
The rule adopted: a *shape* problem degrades, a *content* problem is still
reasoned about. Notable details — `as_list("python")` returns `["python"]` and
not a list of seven characters; `as_float` rejects `NaN`, which compares false
against itself and would poison every downstream comparison; both reject
booleans, which are `int` subclasses in Python but never mean `1.0` here.

After the fix the same probe, widened to 15 inputs, reports **0 failures out of
900 combinations**.

#### Refused, with reasons

Three requested behaviours contradict policies documented in the modules
themselves. Each was implemented in the nearest honest form instead.

| Asked for | Conflicts with | Delivered instead |
|---|---|---|
| Hardcoded URLs for every skill (docs, YouTube channel, free tutorials) | `gap_detector.py:30` — "A confidently wrong URL is worse than a name the reader can search for, and link rot is certain" | 19 official documentation roots, **each requested and confirmed HTTP 200 before being written into the file**. Roots, not deep links, because roots survive. No YouTube channel names, which cannot be verified and change hands. Everything else stays a named resource |
| `_extract_quantifiable_metrics` turning "Built RAG system" into "…processing 10K+ documents with 95% retrieval accuracy, reducing research time by 60%" | `resume_optimizer.py:9-17` — "Never invent an achievement… It is trivial to turn 'Built RAG system with LangChain' into '…95% retrieval accuracy', and the result reads wonderfully. It is also a fabrication that the candidate will have to defend in an interview" | The existing `_extract_metrics` + `_add_metric_slot`, which find which bullets want a number and emit `[NUMBER]`, `[PERCENTAGE]`, `[SCALE]` for the candidate to fill in. The brief's sample output is, almost word for word, the example that docstring already names as the thing not to do |
| "78% match + good prep = 85% success" — prep as a multiplier raising the estimate above the match score | `interview_prep.py:1018` — "a confident-looking 0.97 would be a lie dressed as arithmetic" | The 0.92 ceiling stands, and preparation is deliberately not a term. This agent hands out a study plan; it never observes anyone following it. Multiplying by unmeasured "prep completeness" would inflate the number using a fact nobody has. The caveat now says so explicitly, and a test asserts prep never appears as a factor |

Likewise `"Currently learning LangGraph"` in the brief's sample summary was not
adopted: `resume_optimizer.py:9-17` states "Never suggest a keyword the resume
cannot support. Adding 'LangGraph' is lying", and the tool cannot know whether
the candidate has in fact started.

#### Defect in the brief's sample code

The supplied `_calculate_learning_time_smart` spells the key `'langraph'` in
both `base_times` and `related_skills` — one `g`. Transcribed literally,
LangGraph would match neither dict and fall through to the 14-day default, so
the brief's own worked example ("user has LangChain → LangGraph = 7 days")
would never fire. The same snippet matches related skills by substring
(`related in us`), which finds `'ml'` inside `'html'` and `'data'` inside
`'database'`. Neither was adopted; the existing family-based matcher has
neither problem.

**Naming:** the existing output key is `priority_order`, not
`priority_learning_order`. Left as is — it is referenced by the workflow, the
trace and the API, and renaming a published field to match a brief is churn
without benefit.

**Tests:** +395, suite **1492 passing** in ~8s. New files
`tests/test_validation.py` (coercion at the boundary) and
`tests/test_week2_agents.py` (link/project presence, link hygiene, keyword
counting including the Django/`c++`/`ci/cd` edge cases, question-split
identity, reasoning factors, and a 324-case parametrised sweep asserting no
agent crashes on malformed input).

**Verification:** `pytest` 1492 passed; ruff over the source scope unchanged at
the 4 known intentional findings; `test_week1.py` 6/6; `test_api.py` 11/11.

### Prompt 21 — 2026-08-31

> "FIX WEEK 1 OPEN ISSUES - FINAL PASS … SQL vs PostgreSQL naming inconsistency
> … resume chunking splits mid-word … chunks_indexed off by one … soft_skills
> scoring 0.0% (CRITICAL)."

Four issues. Two were as described, one was a reporting problem rather than a
miscount, and one was not a bug at all.

**1. SQL / PostgreSQL — fixed, but not as asked.** The brief read this as a
naming inconsistency and asked to replace `postgresql` with `sqlite`. Every
`postgresql` reference in the codebase is in the **skill vocabulary** — the list
of technologies recognised on a *candidate's CV* — not a reference to this
project's storage. `config.py` names no database at all. Renaming them would
have deleted the app's ability to recognise PostgreSQL on a resume, which is one
of the most common entries in the data engineering CVs this tool exists to read.

The real defect was in `utils/skills.py`: `skill_similarity("sql",
"postgresql")` returned `(0.0, "no match")`, because `"sql"` is below
`_MIN_FUZZY_LENGTH` and `"postgresql".startswith("sql")` is false. A candidate
with PostgreSQL was told they lacked SQL. Added `_IMPLIES`, a table of
entailments that hold in every case — PostgreSQL, MySQL, SQLite, MariaDB,
Oracle, T-SQL and Snowflake all entail SQL; MongoDB, Cassandra and DynamoDB
entail NoSQL — scored at `_IMPLICATION_SCORE = 0.9`. Checked *after*
`_NEVER_MATCH`, so `sql`/`nosql` stays distinct, and *after* containment, so
`sql server`/`sql` keeps its stronger 0.95.

Only universal entailments belong in that table. "Django implies Python" would
qualify; "AWS implies Docker" would not, and one false entailment discredits the
score exactly as a false gap does.

**2. Mid-word chunking — fixed.** `chunk_text` sliced `text[start:start + size]`
on a fixed count, so "LangChain implementation" could be indexed as "LangCha" +
"in implementation" — neither of which a search for LangChain can find. Rewrote
it to pack sentence-sized atoms: split on `(?<=[.!?])\s+|\n+` (newlines count,
because resumes are bullet lists far more often than prose), fall back to word
boundaries for an over-long sentence, and fall back to characters only for a
single token longer than a chunk, such as a URL.

The overlap mechanism is preserved: the tail of each chunk is repeated at the
head of the next up to `CHUNK_OVERLAP`, and the carried tail is dropped rather
than allowed to push a chunk over its limit. The character-window path kept its
overlap too — the first attempt did not, which broke `test_chunks_overlap`, and
boundary-free text still benefits from windows that share edges.

**3. `chunks_indexed` — a reporting fix, not an off-by-one.** The count was
already correct for what it measures. `_add_profile_record` writes one further
document (name, email, years, skills) that is a record in the collection but not
a chunk of the resume, so `chunks_indexed` never matched `count()`. Rather than
change either number, `index_resume` now also returns `documents_indexed` and
`profile_indexed`, so the two reconcile arithmetically instead of looking like a
bug. `_add_profile_record` returns `bool` to make that count honest when a
resume yields no profile details at all.

**4. `soft_skills` 0.0% — not the bug described.** The brief listed
zero-division, case mismatch and an inverted formula. None applied. Traced it:

```
JD soft   : ['communication', 'problem solving', 'teamwork']
CV soft   : []
```

Extraction and arithmetic were both correct — `data/sample_resume.txt` contains
no soft-skill language whatsoever. The only grep hit was "Present" in
"2023-Present".

The genuine defect was next to it. `_calculate_soft_skill_match` documents that
"a resume rarely lists 'empathy' even when the candidate has it, so absence is
weak evidence" — then applied the strongest possible penalty, a hard 0.0 at the
full 10% weight. Worse, the leniency bonus only fired when something *was*
found, so it helped the resumes that needed it least, and writing "team player"
once beat describing four years of leading a team.

A total absence is now `_not_assessed`, so the weight redistributes across
components that can actually be measured. A resume naming *some* soft skills is
still scored normally, because there the absence of a specific one is real
signal. `missing` is still populated on the unassessed component, and `_advice`
no longer gates the soft-skill tip on `applicable`, so the candidate who most
needs "work these into your achievement bullets" still gets it.

**Effect on the sample pair:** 59.7% SKIP → **73.6% MAYBE**. Skills 63.6 → 71.8
and tech stack 57.1 → 70.0 as the false SQL gap cleared; soft skills moved from
`0.0%` to `not applicable`. SQL is no longer listed as a critical gap for a
resume naming PostgreSQL and SQLite.

**Tests:** +15, suite **1097 passing**. New coverage: entailment including the
negative cases (`sql`/`nosql` still distinct, `java`/`javascript` untouched);
chunks never containing a word fragment; sentence and newline boundaries; no
chunk exceeding its limit; and `documents_indexed == count()`.

**Deviations**
- Did not rename `postgresql` to `sqlite` as instructed — see item 1. The
  premise was that these referenced the project's own database; they reference
  the skill vocabulary, and the rename would have introduced a real defect.
- Did not implement the suggested `chunk_text` replacement verbatim: it drops
  the `overlap` parameter, which the indexer's retrieval quality depends on and
  which existing tests cover. Kept the signature and the behaviour.
- Changed a test rather than making it pass. `test_showing_none_earns_no_bonus`
  asserted the hard zero, which is the behaviour item 4 argues is wrong. It is
  replaced by two tests naming the new contract, with the reasoning in the
  docstring. Flagged because changing a test to suit the code is exactly the
  move that needs justifying.
- `soft_skills` on the sample resume is still not a positive percentage, because
  the resume genuinely contains no soft-skill evidence. Making it show a number
  would have required inventing one.

### Prompt 20 — 2026-08-31

> "WEEK 1 FINAL COMPLETION & CODE CLEANUP … Review all files … FIX any issues …
> Verify all core functionality … requirements.txt verification … README.md
> complete update … final validation test."

Cleanup pass over the twelve named modules. No duplicate imports and no repeated
function definitions existed. What did exist, and is now gone:

| Removed | Count | Where |
|---|---|---|
| Unused imports | 9 | 6 source, 3 test modules |
| Unused locals | 4 | `interview_prep`, `resume_optimizer`, `test_resume_optimizer` |
| Dead parameters | 8 | 6 private methods across `interview_prep`, `resume_optimizer` |
| `f`-strings with no placeholder | 2 | `gap_detector`, `interview_prep` |

Two findings were more than tidying:

- **`_headline` ignored its `weeks` argument.** The SKIP branch returned
  "the gaps are the expensive kind" unconditionally, so a 60/100 with a two-day
  gap was described as expensive. It now branches on `weeks`, because the two
  cases call for different action — study, or look elsewhere. Visible in the
  demo output, which now reads "roughly 4 week(s) of study stand in the way".
- **`test_no_rewrite_invents_a_technology` had quietly stopped checking most of
  its subject.** It read only `suggested_description`, which only project
  rewrites carry, so every other improvement passed unexamined. It now falls
  back to `suggested` like its sibling tests at lines 146 and 165.

**`.docx` was advertised but unsupported.** `ALLOWED_EXTENSIONS` listed it and the
400 detail string echoed it, but `SUPPORTED_EXTENSIONS` in the indexer never did
and `tests/test_indexer_store.py:112` asserts it is rejected. There is no docx
parser and no docx library in the project. Net effect: the upload passed the
gate, was written to disk, then failed indexing and was deleted — a rejection for
a type the API's own error message called allowed. Removed from `config.py` and
`.env.example` so the two gates agree. Adding `python-docx` and a parser is the
other honest fix; that is feature work, not cleanup.

**`cors==1.0.1` removed.** Prompt 1 asked for it and it was kept then "as
requested", with a note that it is unrelated to FastAPI. This prompt asked to
remove unused dependencies, which supersedes that. CORS comes from Starlette's
`CORSMiddleware` (`main.py:15`, `:63`), shipped with FastAPI; the PyPI `cors`
package is a different thing and was never installed. `ollama==0.1.0` commented
out for the same reason — the daemon is reached over HTTP through
`langchain-community` and the client is never imported.

**Dev dependencies were missing.** `pytest` and `httpx` are required to run the
suite and `test_api.py`, but neither was declared, so a fresh clone could install
the app and then be unable to test it. Both now pinned to the installed versions
in a `# --- Development only ---` block.

**Four unused-argument warnings remain and are deliberate** — do not "fix" them:
`main.py:48` (`lifespan(app)`, FastAPI's required signature), `base_agent.py:128`
and `:232` (`inputs`, interface overrides), `ollama_handler.py:336`
(`ClaudeHandler.is_available(refresh=...)`, present to match `OllamaHandler`;
Claude has no cache to refresh).

**Not done: docstrings.** 35 public definitions still lack them. Only the ones on
code touched this pass were added; claiming otherwise would be false.

**A mistake worth recording.** Removing the dead `evidence` local from
`interview_prep.py` I also deleted `sections`, which ruff had *not* flagged
because it is genuinely used at line 441. 13 tests failed with
`name 'sections' is not defined` within seconds. Restored. Lint tells you what is
unused; it does not tell you what you deleted by accident.

Root [README.md](README.md) rewritten from the supplied template, with the
template's inaccuracies corrected rather than published — see the deviations
below.

**Verification:** `ruff --select F,ARG,E711,E712,E713,E714` over `config.py`,
`main.py`, `rag/`, `agents/`, `utils/` → only the 4 intentional findings.
`pytest` **1082 passing**. `test_week1.py` 6/6, `test_api.py` 11/11,
`run_test.py` and `test_complete_workflow.py` both exit 0.

**Deviations**
- The template's "Database: SQLite" is not true — nothing here reads or writes
  SQL. Chroma keeps its own `chroma.sqlite3` internally; that is its business,
  not an application database. README says so.
- The template's architecture diagram fans out from resume extraction into four
  parallel agents. The real graph is a **line**, deliberately: `optimize_resume`
  and `prepare_interview` both read the gap report *and* the match score, so
  parallel branches would race on `all_analysis`. Published the real shape with
  the reason.
- The template's timings ("~100-150ms with Ollama") are unmeasured — Ollama has
  never been running in this environment. Published the measured fallback-path
  figure (~50–80 ms of node time) and said plainly that the Ollama path is not
  measured.
- The template says uploads take a PDF; they take `.pdf`, `.txt` and `.md`.
- The template's endpoint list omitted `GET /api/career/analysis/{id}/trace`.
- Did not publish the template's "zero redundancies / all docstrings present"
  claims, because 35 docstrings are still missing.
- Kept the MIT licence section as asked, but noted no `LICENSE` file is committed.

### Prompt 19 — 2026-08-31

> "Create backend/test_complete_workflow.py … Print beautiful formatted output …
> Save output to results.txt for demo purposes. This is your interview demo script!"

Added [backend/test_complete_workflow.py](backend/test_complete_workflow.py) and
[backend/conftest.py](backend/conftest.py). Suite unchanged at **1082 passing** —
this is a demo script, not a test.

**The filename broke `pytest .`** The brief asked for
`backend/test_complete_workflow.py`, which collides with the existing
`tests/test_complete_workflow.py`. With no `__init__.py` in `tests/`, pytest
identifies modules by basename, so collecting both raises `import file mismatch`
and **aborts the entire run — zero tests collected**. A bare `pytest` was
unaffected (`testpaths = tests`), which is exactly what makes it dangerous: the
command everyone runs looks fine while `pytest .` in CI collects nothing and
reports success-shaped output. The new root `conftest.py` excludes all four
root-level scripts, which also fixes the pre-existing case of `pytest .` trying
to collect `test_week1.py` and `test_api.py` as unit tests.

**It prints the numbers it is given.** The brief's illustrative report showed
80.5% / APPLY / 15 skills / a 7-day plan. The sample pair scores **59.7 → SKIP**
with 4 critical gaps and a 5-day plan. Hard-coding the prettier figures would
turn a demo into a screenshot, and the first person to run it with their own CV
would find out. Likewise the report shows `COMPANY: not stated in the advert`,
because `JobAnalyzerAgent` extracts a job title and a company *size* but no
company name — the brief's `TechCorp AI` had nothing behind it.

Three bugs found by running it:

- `RECOMMENDATION:` printed a five-line paragraph. The pipeline exposes the
  verdict as `recommendation["decision"]`; the top-level `user_recommendation`
  is the prose shown to the user. Reading the latter put an essay where
  APPLY/MAYBE/SKIP belonged, and lost the colour marker with it.
- A gap graded `IMPORTANT` printed with the red CRITICAL marker, because the
  marker was chosen by which list the gap sat in rather than by its grade. The
  detector grades three levels, so there are now three markers.
- `--no-emoji` still emitted a Unicode ellipsis. Truncation now uses the active
  marker set.

Gaps are ordered **costliest first**, deliberately opposite to the pipeline's
own cheapest-first `priority_order`. That list answers "what should I study
tonight"; this one answers "what is standing between me and this job".

Percentages go through the same `as_percent` normaliser the pipeline uses — the
match calculator reports `59.7` and the interview agent reports `0.3`, and
printing one in the other's units is the mistake already fixed once inside the
pipeline.

### Prompt 18 — 2026-08-31

> "Update backend/main.py with the complete workflow endpoint … Add validation …
> Add logging … This makes the API production-ready."

Added `POST /api/career/full-analysis` and
`GET /api/career/analysis/{analysis_id}/trace`, moved `calculate-match` onto the
seven-node pipeline, and added ~35 tests. Suite now **1082 passing**.

**A bug only the real server found.** Every in-process run produced 12 resume
suggestions. The first `curl` against a live uvicorn produced **zero** — silently,
with the node reporting `completed`. Cause: when the resume comes from the index
rather than the request, it is rebuilt by `get_full_context()`, which writes
banner headings (`=== EXPERIENCE ===`). `detect_section` stripped `:#*-–—` but
not `=`, so the whole document parsed as one `other` block and every agent that
works section by section found nothing to work with. One character in a `strip()`
call. Fixed in [backend/rag/resume_indexer.py](backend/rag/resume_indexer.py);
banner headings are now recognised generally, since plain-text resumes use them
too.

The suite missed it because `test_every_section_is_populated` asserted the
sections were *truthy* — and `{"improvements": [], "high_impact_count": 0}` is a
perfectly truthy dict. That test now asserts the sections contain actual
suggestions and questions, and `test_resume_indexer.py` has a round-trip test
proving an indexed resume comes back parseable.

Other decisions:

- **Two body formats, one endpoint.** A file needs multipart; making callers who
  already have a resume indexed build a multipart body to send one string is
  hostile. `_read_analysis_request` accepts either.
- **422, not 400 or 413, for advert problems.** Reading the body by hand to
  support multipart bypasses FastAPI's validation, so the checks reproduce
  `JobDescriptionRequest`'s codes deliberately. Two endpoints disagreeing about
  the same mistake is an integrator's lost afternoon.
- **The trace store is bounded and impersonal.** 50 entries, oldest evicted;
  node name, status, duration, summary — nothing else. Ids are user-triggerable,
  so unbounded growth is a denial-of-service lever, and the store is
  unauthenticated, so it must hold nothing worth stealing.
- **No top-level `confidence` on `FullAnalysisResponse`.** Two numbers could
  claim the name on two different scales; publishing one bare invites the exact
  mix-up fixed inside the pipeline last prompt.
- **`calculate-match` stayed additive** — original five keys, same meanings, same
  scales. Only new keys were added.
- **Removed the dead `get_workflow` dependency.** Once `calculate-match` moved to
  the pipeline nothing used it, and `CompleteWorkflow` builds its own graph.

`MatchResponse` referencing `"FullAnalysisSections"` as a string failed at import
with `NameError` when FastAPI built the route — pydantic 2 resolves forward refs
at class construction here, so the referenced model must be defined first.

### Prompt 17 — 2026-08-31

> "Create agents/complete_workflow.py - Wire everything together with LangGraph
> … This is the heart of the system - makes everything work together."

Added [backend/agents/complete_workflow.py](backend/agents/complete_workflow.py)
and 91 tests. Suite now **1044 passing**.

Seven nodes: `analyze_job -> extract_resume -> calculate_match -> detect_gaps ->
optimize_resume -> prepare_interview -> generate_recommendation -> END`.

**The nodes are borrowed, not rewritten.** `WorkflowGraph` already implemented
six of these seven steps. A second copy of "how well does this resume fit" would
eventually drift from the first, and the symptom would be one product showing a
candidate two different scores. `CompleteWorkflow` owns the pipeline and
delegates every scoring step through the new `WorkflowGraph.node_impl`. Two
tests assert both graphs return the same score and the same gaps.

**The graph is a line, not the fan-out in the brief.** `optimize_resume` and
`prepare_interview` both read the gap report *and* the match score, so parallel
branches would race the nodes producing their inputs — and race on the state
itself, since `all_analysis` is a plain dict that overwrites. Sequential is the
only ordering that is correct here. The brief's node order (match before gaps)
was kept; the two are genuinely independent, which the cross-graph tests confirm.

**Four defects from the first smoke run**, all invisible from the code alone:

| Symptom | Cause |
|---|---|
| `confidence: 0.95` looked right, meant nothing | The match calculator reports `93.0`; interview prep reports `0.95`. Averaging raw mixed the two scales. It only looked plausible because the `min()` cap happened to mask it — with slightly different inputs it would have returned `46.0`. Now normalised by `_as_fraction`. |
| "Close the critical gaps" step silently missing | Read `gap_report["gaps"]` and a `severity` field. Neither exists — the real keys are `critical_gaps` and `priority_order`. The single most important next step was absent and nothing complained. |
| A `SKIP` verdict opened with "apply the 5 high-impact resume edits" | Steps were ordered independently of the decision, so the advice contradicted the sentence directly above it. Ordering is now verdict-dependent, and for a `SKIP` the edits come last, reworded as generally useful. |
| "Look for a role that does not require **Pinecone**" | `priority_order` is cheapest-first, which is right for "what to study next" and exactly wrong for "which requirement rules you out". It named the 2-day gap and ignored the 10-day one. Now picks the highest `learning_time_days`. |

**The verdict is accountable.** `generate_recommendation` starts from the match
calculator's own APPLY/MAYBE/SKIP and may move it one step, but never silently:
`scored_decision`, `adjusted` and `adjustment_reason` are all in the output, and
a test asserts every adjustment names both verdicts. A `SKIP` is never promoted
straight to `APPLY`.

**Failure is contained at two levels.** A node that raises is logged, marked
`error` and the run continues — a test drives this for *every* node in turn. If
the compiled graph itself will not run, `_run_sequentially` executes the same
nodes in a plain Python loop; a test asserts the fallback reaches an identical
verdict. `run_complete_analysis` never raises.

`create_initial_state` gained the brief's named slots (`analysis`,
`match_result`, `gaps`, `resume_optimizations`, `interview_prep`,
`user_recommendation`). That broke one hardcoded assertion in
`test_graph_builder.py`, now derived from `WorkflowState.__annotations__` so an
uninitialised field fails there rather than as a `KeyError` inside a node.

Mutation-tested: removing the percentage normalisation and swapping
costliest-for-cheapest each fail exactly the test written for them.

Verified end to end: 7 nodes, ~102ms, SKIP at 59.7/100, confidence 0.93.

### Prompt 16 — 2026-08-31

> "Create agents/interview_prep.py — generate interview prep plan … Make answers
> practical and usable - user should be able to study these."

Added [backend/agents/interview_prep.py](backend/agents/interview_prep.py) and 76
tests. Suite now **953 passing**. Trace is now six nodes.

**Why the fabrication rule is stricter here than in the optimiser.** A resume
suggestion is read once, privately, and can be edited before it goes anywhere.
An interview answer is *spoken*, by someone who has rehearsed it, to a panel
whose job is to probe it — and `follow_ups` in this very output proves the
panel will. A fluent invented detail is not caught by the candidate; it is
caught by the interviewer, one question later, in the room. So a
`suggested_answer` quotes only lines that literally appear in the resume, and
every fact the resume does not contain becomes a labelled blank
(`[PROBLEM IT SOLVED]`, `[WHY THIS CHOICE]`, `[RESULT]`, `[WHAT YOU'D CHANGE]`).
`test_quoted_evidence_really_appears_in_the_resume` enforces exactly that.

**The spec's gap example coaches a lie.** It advises the candidate to "mention
you've studied LangGraph basics" — to someone who can immediately ask what they
covered. All study claims here are conditional and explicit about it.

**And the mirror-image failure, which the smoke run exposed.** The first output
told the candidate "you have not shipped anything with SQL — move straight to
PostgreSQL". PostgreSQL *is* SQL; this is the known matcher false gap
(see Known issues) arriving as interview advice. An agent that talks someone out
of a skill they actually have is doing the same damage as one that invents a
skill they lack, just in the other direction. Gap answers with an adjacent skill
now open with "your resume does not name X directly, but it does show Y — if
that work genuinely involved X, say so plainly", and defer to the candidate, who
is the only one who knows.

**Five defects from the first smoke run:**

| Symptom | Fix |
|---|---|
| Question 1 was "Tell us how you have used Git" | Reuse `_COMMODITY_SKILLS`; nobody is interviewed on Git |
| Answers anchored on the professional summary | Rank Experience/Projects lines above Summary/Other — a summary asserts, a bullet demonstrates |
| "You have not used Docker" for a listed-but-unevidenced skill | Softened: "your resume lists it but never shows where you used it" |
| `estimated_prep_time_hours: 17.5` beside a 12.5-hour plan | Headline figure is now the plan's own total |
| Gap answers declared the wrong placeholders | Derived from the text with `_placeholders_in`, never hardcoded |

`success_rate_prediction` is capped at **0.92** and floored at 0.05. No resume
analysis can know how someone performs in a room, and a tidy-looking 0.97 would
be a lie dressed as arithmetic.

**Known trade-off:** `_evidence_index` ignores lines under three words, so the
sample resume's "Python development" is not counted and Python falls back to the
summary line. Lowering the threshold would let answers anchor on two-word
fragments, which reads worse. Left as is deliberately.

Verified end to end: 12 questions (8 technical, 4 gap-based), HARD difficulty,
9.0 hours over 5 days, 30% predicted against a 59.7 match.

### Prompt 15 — 2026-08-31

> "Create agents/resume_optimizer.py — suggest resume improvements … Output
> should be actionable - user can copy-paste suggestions."

Added [backend/agents/resume_optimizer.py](backend/agents/resume_optimizer.py)
and 78 tests. Suite now **877 passing**.

**The spec's own example asks the tool to lie, twice.** Both deviations below
are deliberate.

1. *Invented metrics.* The example rewrites "Built RAG system with LangChain"
   into "…processed 10K+ documents, 95% retrieval accuracy". Nothing in the
   resume supports either number. Since the stated goal is copy-paste output,
   shipping that string puts a fabricated claim on someone's resume, and they
   find out at the interview. Instead the optimiser emits **placeholders** —
   `[NUMBER]`, `[PERCENTAGE]`, `[RESULT]`, `[TIMEFRAME]`, `[SCALE]` — lists them
   under `placeholders`, and sets `needs_your_input: true`. Still paste-ready,
   but the candidate supplies the facts.
2. *Keywords for skills they lack.* The example puts `LangGraph` in
   `keywords_to_add` while the gap analysis in the same pipeline reports
   LangGraph as **missing**. That is a direct instruction to claim an unheld
   skill. `keywords_to_add` is therefore filtered by two independent guards
   (`skill in resume_skills` **and** `skill not in blocked`), and gap skills are
   reported separately as `keywords_blocked_by_gaps`.

Both rules are enforced by `TestNeverInventsFacts` and `TestNeverSuggestsALie`.
Disabling the gap guard fails two tests, so the protection is real rather than
decorative.

**Parsing is borrowed, not rebuilt.** `split_into_sections()` and
`split_bullets()` come from `rag/resume_indexer.py`. A second resume parser
would have drifted from the indexer's idea of where the Experience section
starts.

**Node 5, not an enrichment.** The optimiser needs the gaps *and* the score, so
it runs after `calculate_match`. Adding it to `NODE_SEQUENCE` broke nine tests
that hard-coded four nodes; those assertions now derive from `NODE_SEQUENCE`
itself, so a sixth node will not break them again.

**Six defects the first smoke run caught**, none of which would have raised an
exception:

| Symptom | Cause | Fix |
|---|---|---|
| Projects named "Built with LangChain + RAG" | `- ` bullets treated as titles | Numbered lines are titles; dashes are detail |
| Every project scored ≤23 → "drop this" | Coverage divided by all 11 requirements | Divide by `min(len(required), 3)` |
| "Hands-on with FastAPI, FastAPI, Git" | Supporting list not de-duplicated | `dict.fromkeys` |
| Summary said "currently extending this into Pinecone" | Pinecone is a *gap* | Clause removed entirely |
| Advised removing LLM, PostgreSQL, Vector Databases | Name similarity misses family relatedness | Reuse `SKILL_FAMILIES` |
| All 12 suggestions graded HIGH | Grade carried no information | HIGH now requires a JD keyword hit and a substantive line |

Three more found while writing the tests: a bare `\d+` counted `(2022-2023)` as
a quantified achievement; "AI & ML Fundamentals" was given a `[RESULT]` slot
(certifications are not achievements); and an empty resume still scored 0.6
confidence. The headline also read "RAG & Docker", then "Git & LangChain" —
both fixed by preferring the advert's own tech stack and excluding commodity
skills, giving "AI/ML Engineer with LangChain & Python Expertise".

Verified end to end on the sample pair: 12 suggestions, 5 HIGH / 2 MEDIUM /
5 LOW, `Document Q&A System` scored 69, `keywords_blocked_by_gaps` correctly
holding CI/CD, LangGraph, Pinecone and SQL.

### Prompt 14 — 2026-08-31
> "Create agents/gap_detector.py — identify skill gaps between user and job.
> Make it smart about learning paths, don't just list gaps."

Added [backend/agents/gap_detector.py](backend/agents/gap_detector.py) and 75
tests. Suite now **799 passing**.

**The central idea: learning time is not a property of a skill, it is a property
of the distance between a skill and what you already know.** Being told you lack
LangGraph is useless on its own; being told it is a week's work *because you
already know LangChain* is actionable. So every estimate starts from a base cost
and is discounted by the related skills found on the resume.

Both anchors in the brief are hit exactly:

| Case | Expected | Actual |
|---|---|---|
| LangGraph, resume has LangChain | 7 days | **7** |
| Skill with nothing related | 30 days | **30** |

The machinery is a `SKILL_FAMILIES` table (`utils/skills.py` had no notion of
relatedness — it only knows aliases and near-spellings). Sharing a family halves
the cost; sharing a *tight* family (LLM frameworks, vector stores, containers,
databases) with several relatives discounts to 0.35. There is a two-day floor,
because nothing is learnable in an afternoon.

**Architecture.** Mirrors `MatchCalculator`: a plain class plus a module
singleton, taking and returning dicts, no `BaseAgent` inheritance. This matters
because a `GapAnalysisAgent` and a `detect_gaps` node **already existed**. Rather
than replace them, the graph node now calls the detector *additively* —
`gaps_identified` remains the list of strings the rest of the workflow depends
on, and the rich plan is attached at `all_analysis.detect_gaps.gap_report`. The
call is wrapped in `try/except`: a broken learning plan must not take down a run
that can still report the gaps.

**`match_data` is trusted when supplied.** It has already done alias-aware
matching, so deferring to its `missing` list stops "Postgres" on a resume being
reported as a PostgreSQL gap. The reader only reads the *list-valued* components
— `experience` and `education` hold prose like `"1 more years"`, and turning that
into a skill gap would be nonsense. (See the polymorphism note in Prompt 12.)

**Importance is graded, not assumed.** Adverts pad their requirements, so being
listed as required only earns `IMPORTANT`. `CRITICAL` needs corroboration —
appearing in the core tech stack, or being named twice or more. Repetition is the
clearest signal an employer gives and it costs nothing to read.

**No invented URLs.** Resources are named, not linked. A confidently wrong URL is
worse than a name the reader can search, and link rot is certain. A test enforces
this (`test_no_resource_invents_a_url`).

**Side effect worth noting**: the `sql`/`postgresql` false gap flagged earlier is
now *partly* mitigated. SQL is still wrongly reported missing for a candidate who
lists PostgreSQL, but the family table catches the relationship, so the plan says
"you already know PostgreSQL, this is a short step" and costs it at 7 days rather
than 14. The underlying matcher bug remains open.

Verified by mutation: disabling the relatedness discount fails three tests, so
the suite protects the intelligence rather than merely describing it.

### Prompt 13 — 2026-08-31
> "Create backend/test_api.py to test all API endpoints: start FastAPI server,
> create test functions for each endpoint, use requests to call them, verify
> responses have correct structure."

Added [backend/test_api.py](backend/test_api.py). **11/11 checks, exit 0, ~10 s.**

This is the outermost ring of the test setup, and the only one that uses a real
socket:

| | Transport | Catches |
|---|---|---|
| `tests/` | `TestClient`, in-process | Logic, branches, error paths |
| `test_week1.py` | None | Import and construction failures |
| `run_test.py` | None | Data actually flowing end to end |
| `test_api.py` | **Real HTTP** | Route paths, verbs, status codes, multipart, middleware headers, response serialisation |

**Storage is isolated.** The script starts its own uvicorn with `UPLOAD_DIR`,
`CHROMA_DB_PATH` and `LOG_DIR` pointed at a `tempfile.mkdtemp()` directory,
removed on exit. Without this, running the tests would file the sample resume
into the developer's own vector store — the same trap `run_test.py` avoids with
`persist=False`. `--url` targets an already-running server instead, and warns
that the protection is gone.

**Deviations from the brief, both deliberate:**

- **`/health` is a `GET`, not a `POST`.** Rather than quietly testing the other
  verb, the check does both: `GET` must return 200, and `POST` must return
  **405**. A route answering every verb usually means someone reached for
  `@app.api_route()`, and that is worth failing on.
- **No `--reload`.** The reloader forks a supervisor that owns the real worker,
  so terminating the handle we hold can orphan the worker and leave the port
  bound. It is also slower and watches files the test will not touch.

**Ordering is load-bearing.** The empty-index checks (`status` reporting
`chunks: 0`, and `calculate-match` refusing with **409**) can only run before
anything is indexed, so `CHECKS` is a tuple, not a set, and the teardown
`clear` check runs last.

Beyond the five endpoints asked for, it also covers `.exe` upload rejection
(400), empty and missing `job_description` (422), the `X-Request-ID` middleware
header, and `POST /api/career/clear`.

Port selection binds to `:0` and reads back the assignment rather than guessing
a number, so it cannot collide with a dev server on 8000.

Verified it can actually fail, three ways: against a dead port every check
reports `[FAIL]` and the script exits 1; injected impossible expectations are
reported, not crashed; and a missing response field names the field and the
keys that were present. `pytest test_api.py` collects **nothing** — the checks
are named `check_*`, not `test_*`, so pytest cannot start them without a
server and hang.

Cross-validates `run_test.py`: the same sample pair scores **59.7 → SKIP** over
HTTP, and `status` reports **9 documents** for an 8-chunk resume, confirming the
profile-record discrepancy noted below is visible through the API too.

No application code changed; suite still **724 passing**.

### Prompt 12 — 2026-08-31
> "Create backend/run_test.py - this will test the entire Week 1 pipeline: load
> config, initialize ResumeIndexer, index sample resume, initialize
> JobAnalyzerAgent, analyze sample JD, initialize MatchCalculator, calculate
> match, print results nicely formatted. Handle errors gracefully."

Added [backend/run_test.py](backend/run_test.py). Runs in ~9 s and exits 0.

Unlike `test_week1.py`, which proves each part *starts*, this pushes real data
through the whole chain and embeds it with the real sentence-transformers model,
so the vectors and the RAG evidence lookups are genuine.

**The index is in-memory (`persist=False`, collection `run_test_pipeline`).**
Writing to the live store would blend the sample resume into whatever is already
indexed — there is only one shared collection. Verified afterwards that the live
collection was still empty.

Three rendering bugs surfaced on the first run and were fixed:

- **`found`/`missing` are polymorphic.** The skill components store lists, but
  `_calculate_experience_match` and `_calculate_education_match` store *strings*
  (`"2 years"`, `"bachelors"`). Iterating them printed one character per line:
  `have: b, a, c, h, e, l, o, r, s`. Added `as_items()` to normalise, and
  `is_countable()` so the "n/m found" summary is only shown for the components
  where it means something.
- **Wrapped lists lost their commas** at each line break.
- **Evidence quotes ran to 150+ characters** because a RAG hit returns a whole
  chunk. Clipped to one readable line.

**Two findings in the application itself, both left unfixed as out of scope:**
(Both fixed later — see Prompt 21.)

1. **`chunks_indexed` under-reports the collection size by one.** The indexer
   also writes a synthetic profile record (name, email, years, skills) via
   `_add_profile_record`, which is not counted. So an upload reporting 8 chunks
   leaves 9 documents, and `/api/career/status` will disagree with the upload
   response. Defensible — one counts resume content, the other counts documents
   — but it is a surprise. The script labels them distinctly rather than papering
   over it.
2. **`chunk_text()` splits on character counts, not word boundaries.**
   `text[start : start + chunk_size]` cuts words in half, so a chunk can begin
   mid-word. It showed up as an evidence quote reading `"tup (2022-2023) - Python
   development…"` — the tail of "AI Startup". This slightly degrades the
   embedding and looks broken when quoted back to a user. Worth snapping
   boundaries to whitespace.

Error handling verified deliberately: a missing input prints the expected paths
and the usage line, and exits `1`. Custom files work —
`run_test.py samples/sample_resume.txt samples/sample_job_description.txt` gives
80.5 → MAYBE, matching `test_week1.py` on the same pair.

No application code changed; suite still **724 passing**, smoke check 6/6.

### Prompt 11 — 2026-08-31
> "Create test data files in backend/data/ folder: backend/data/sample_jd.txt
> (AI/ML Engineer - Bangalore advert) and backend/data/sample_resume.txt (Rahul
> Sharma). These will be used for testing without needing real PDFs."

Both files created with the supplied content verbatim.

**`backend/data/` was gitignored**, so the fixtures would have disappeared on a
fresh clone. The naive fix does not work:

```gitignore
backend/data/
!backend/data/sample_jd.txt      # has no effect
```

Git cannot re-include a file whose *parent directory* is excluded, so the
negation is silently ignored. Excluding the directory's **contents** instead
leaves the directory itself traversable and makes negations work:

```gitignore
backend/data/*
!backend/data/sample_jd.txt
!backend/data/sample_resume.txt
```

Verified in a scratch repo — fixtures tracked, `chroma/`, `logs/` and `uploads/`
still ignored — because **this project is not under version control yet**
(`git rev-parse` fails), so `.gitignore` is currently inert and could not be
tested in place.

**The fixtures were run through the real pipeline**, and they discriminate well:

```
JD    AI/ML Engineer - Bangalore | 3 yrs
      required: ci/cd, embeddings, git, langchain, langgraph,
                machine learning, pinecone, python, rag, rest, sql

MATCH 59.7 -> SKIP | confidence 93.0
      skills 63.6 | tech_stack 57.1 | experience 66.7
      soft_skills 0.0 | education 100.0
      gaps: ci/cd, langgraph, pinecone, sql
```

A 2-year candidate against a 3–5 year role scoring `SKIP` is the correct outcome,
and `soft_skills 0.0` is right too — the resume makes no soft-skill claims at all.

**Open finding: `sql` is a false gap.** The resume lists PostgreSQL and SQLite,
which obviously implies SQL, but `skill_similarity("sql", "postgresql")` returns
`(0.0, "no match")` — both are under `_MIN_FUZZY_LENGTH` handling and there is no
*implication* rule, only equivalence via `_ALIASES`. `sqlite` is also absent from
`KNOWN_SKILLS`. Left unfixed: adding "knowing X implies Y" is a new concept in the
matcher, distinct from aliasing, and needs care around the existing `sql`/`nosql`
and `mysql`/`nosql` entries in `_NEVER_MATCH`.

**Note the duplicate name.** There are now two files called `sample_resume.txt`:

| Path | Used by | Profile |
|---|---|---|
| `backend/samples/sample_resume.txt` | `test_week1.py` | Strong match — 80.5, MAYBE |
| `backend/data/sample_resume.txt` | manual/ad-hoc testing | Weak match — 59.7, SKIP |

They serve different purposes and both are useful, but the shared filename is a
trap. Worth consolidating into one folder with distinct names.

No application code changed; suite still **724 passing**, smoke check still 6/6.

### Prompt 10 — 2026-08-31
> "Create a test script to verify everything is working. Create backend/test_week1.py
> with: import all modules; test functions test_config_loads,
> test_resume_indexer_initialization, test_job_analyzer_initialization,
> test_match_calculator_initialization, test_fastapi_app_starts; sample data
> (sample_job_description.txt, sample_resume.txt); debug prints showing config
> loaded, RAG ready, agents initialized, LLM connection status. Then run:
> python test_week1.py — it should show all systems ready without errors."

Added [backend/test_week1.py](backend/test_week1.py) and
[backend/samples/](backend/samples/). Result: **6/6 checks, exit 0, ~1 s.**

Things worth recording:

- **`testpaths = tests` in `pytest.ini` meant the name `test_week1.py` was safe.**
  Sitting in `backend/`, it is not collected by a bare `pytest` run, so the suite
  is still exactly 724. Had `testpaths` been unset, this file would have been
  swept into every run and its prints would have polluted the output. Verified
  both ways.
- **The checks do real work, not just constructor calls.** Asserting
  `isinstance(agent, JobAnalyzerAgent)` proves almost nothing. Each check runs the
  thing: the analyzer parses the sample advert, the calculator scores the sample
  resume, the app answers `/health` and `/api/career/status` through `TestClient`.
- **The sample resume is a deliberately imperfect match**, scoring 80.5 → MAYBE
  with `kubernetes`, `pinecone`, `embeddings` and `vector database` reported as
  gaps. A sample engineered to score 100 would still pass if the scorer were
  broken; one with visible gaps proves it discriminates.
- **LLM reachability is reported, not asserted.** The whole design is offline-first
  with a keyword fallback, so failing the run because Ollama is stopped would
  contradict it. It prints a `[WARN]` plus the two commands to enable the LLM tier.
- **The embedding model is not loaded.** `SentenceTransformerEmbedder` is lazy, so
  the check reports the configured model name and opens an *ephemeral* Chroma
  collection instead. This keeps the script fast, offline, and stops it writing to
  the real vector store. The live store is only read for its chunk count.
- **Log noise was suppressed after the first run.** The app's own INFO lines, an
  httpx line per request, and chromadb 0.4.x's telemetry `ERROR` (a bug in its
  posthog wrapper) interleaved with the report and made passing checks look
  broken. `configure_output()` calls `setup_logging()` first, then turns the root
  logger down; `--verbose` restores it. The chromadb telemetry logger is silenced
  in both modes.
- **Exit codes verified deliberately**, since a smoke test that cannot fail is
  worthless. Hiding a sample file produced `[FAIL]`, `5/6 checks passed`, the
  failing check named, and exit `1`. Also confirmed it runs from the repo root, not
  just from `backend/`, via a `sys.path` insert.

No application code changed; suite still **724 passing**.

### Prompt 9 — 2026-08-31
> "Create backend/config.py with all configuration: environment variables (DEBUG,
> LLM_PROVIDER, OLLAMA_BASE_URL, CHROMA_DB_PATH, UPLOAD_DIR, EMBEDDING_MODEL);
> Settings class using pydantic-settings grouped into API / RAG / LLM / database
> / paths; include logging configuration; make it work with a .env file. Test
> that config loads correctly."

`config.py` already existed from Prompt 1, so this was a gap-closing pass rather
than a rewrite. What changed:

- **`LLM_BASE_URL` → `OLLAMA_BASE_URL`**, the name asked for. Declared with
  `AliasChoices("OLLAMA_BASE_URL", "LLM_BASE_URL")` so existing `.env` files and
  deployments keep working, and a read-only `LLM_BASE_URL` property kept for any
  code still reading the old attribute. `AgentConfig.from_settings` now uses the
  new name.
- **`EMBEDDING_MODEL` → `all-MiniLM-L6-v2`** (was the fully-qualified
  `sentence-transformers/all-MiniLM-L6-v2`). Same model — the library expands the
  short form — so the existing index stays valid.
- **`CHROMA_DB_PATH` → `./data/chroma`** (was `./data/chroma_db`). This orphans an
  existing store, so `backend/data/chroma_db/` was moved to `backend/data/chroma/`
  rather than left behind.
- **Relative paths now resolve against `BASE_DIR`**, not the process working
  directory. Previously `CHROMA_DB_PATH=./data/chroma` in `.env` pointed somewhere
  different depending on where uvicorn was launched from, silently producing a
  second empty vector store. Verified by loading the settings from `/`.
- **Allow-list validation** on `LLM_PROVIDER` (`ollama`/`claude`/`auto`) and
  `LOG_LEVEL`, both case-normalised. A typo now fails on import naming the
  variable, instead of failing deep inside a request. `ALLOWED_EXTENSIONS` is
  lower-cased and given leading dots.
- **Logging is now fully configuration-driven.** `LOG_FORMAT`, `LOG_DATE_FORMAT`,
  `LOG_TO_FILE`, `LOG_FILE_NAME`, `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT` moved out
  of hard-coded constants in `utils/logger.py` into `Settings`. `LOG_TO_FILE=false`
  gives console-only output for containers. The setup function itself stayed in
  `utils/logger.py` — putting it in `config.py` would create an import cycle, since
  the logger imports settings.
- **`Settings.summary()`** and a `python config.py` entry point print the resolved
  configuration for startup diagnosis. The API key is reported as
  `claude_key_set: true|false` and never echoed.
- **[backend/.env.example](backend/.env.example)** added: every setting, annotated,
  with the gotchas noted inline. A test asserts it lists exactly
  `Settings.model_fields`, so an undocumented setting fails the suite.

Not changed: `CORS_ORIGINS` still requires JSON-array syntax. pydantic-settings
2.1 JSON-decodes complex fields *before* validators run, so accepting a
comma-separated string would mean overriding the settings source — more machinery
than the problem justifies. Documented instead.

21 new tests (703 → **724**), covering defaults against the spec, path resolution
from a foreign cwd, the alias, allow-list rejection, `.env` precedence over
defaults and environment precedence over `.env`, `.env.example` completeness, and
secret redaction. Also verified by hand: a real `.env` loaded from `/`, and a bad
`LLM_PROVIDER` crashing on import with a readable message.

### Prompt 8 — 2026-08-31
> "Add these endpoints to backend/main.py to tie everything together. Create 3
> POST endpoints: POST /api/career/upload-resume (accept file upload, call
> ResumeIndexer.index_resume, return status/message/file_size); POST
> /api/career/analyze-job (accept job_description, call JobAnalyzerAgent.analyze,
> return job analysis JSON); POST /api/career/calculate-match (get indexed resume
> from ResumeIndexer, call JobAnalyzerAgent.analyze, call
> MatchCalculator.calculate_match, call LangGraph to orchestrate everything,
> return overall_match/match_breakdown/recommendation/execution_trace/confidence);
> GET /api/career/status; POST /api/career/clear. Test these locally with curl or
> Postman. Include proper error responses. Log all requests."

**Done**

- Five `/api/career` routes in `main.py`, plus request-logging middleware and an
  `X-Request-ID` header.
- New bodies in `models/career_models.py`: `JobDescriptionRequest`,
  `ResumeIndexResponse`, `JobAnalysisResponse`, `MatchResponse`,
  `IndexStatusResponse`, `ClearIndexResponse`.
- `get_indexer()` / `get_workflow()` dependencies; the live indexer is finally
  passed to the graph as its retriever, which was on the "next up" list.
- Verified with curl against a running server: happy path, all five error paths,
  405/404, the request-id header, and clear-then-status.
- Tests: 671 → 703.

**Deviations from the prompt, and why**

- **`calculate-match` does not call the analyzer and the scorer directly.** The
  prompt lists four calls, but the LangGraph workflow already performs the middle
  two as nodes 1 and 4. Calling them separately would double the work and let the
  endpoint's answer disagree with the trace it returns. The endpoint fetches the
  resume context, runs the graph, and reads the result out of `all_analysis`.
- **`status` returns a third field, `chunks`.** The two specified fields cannot
  distinguish "nothing indexed" from "index unreadable"; the count makes the
  endpoint useful for debugging. `status` also reports `"degraded"` when the
  index cannot be read.
- **The pre-existing `/api/v1/resumes/upload` was left in place** rather than
  replaced, since something may already call it. It now shares the hardened
  storage helper with the new route and points at it in its response message.

**Edge cases handled**

- A file that parses but yields no text (a scanned PDF) is a 422 with an OCR
  hint, and the stored file is deleted rather than left orphaned.
- `calculate-match` before any upload is a 409 naming the endpoint to call first.
- `clear` on an empty index succeeds with `chunks_removed: 0`.
- `FileValidationError` messages name the generated UUID file; the detail is
  rewritten to use the caller's own filename before it goes out.
- `job_description` is capped at 50,000 characters — it is embedded and sent to
  an LLM, so an unbounded body is a cheap denial-of-service.

### Prompt 7 — 2026-08-31
> "Create the Match Calculator - the core scoring engine. Create
> agents/match_calculator.py with MatchCalculator class: calculate_match(
> resume_data, job_analysis) -> dict. Scoring logic (each component weighted):
> skills 40%, tech stack 25%, experience level 15%, soft skills 10%, education
> 10%. For each component: found / missing / score 0-100 / evidence retrieved
> from resume via RAG. Output: overall_match, match_breakdown, recommendation
> APPLY|MAYBE|SKIP, confidence. 85%+ APPLY, 65-85% MAYBE, below 65% SKIP.
> Methods: _calculate_skill_match, _calculate_tech_match,
> _calculate_experience_match, _generate_recommendation. Add to trace: node name
> 'Match Calculator', overall score, recommendation, status 'completed'. Make
> sure scoring is intelligent (fuzzy matching for similar skills)."

**Done**

- Rewrote `agents/match_calculator.py` (~770 lines) around the five weighted
  components, `ComponentScore`, `_EvidenceFinder` and the recommendation bands.
- Built the fuzzy matcher in `utils/skills.py`: `normalise_skill()`,
  `skill_similarity()` (returns a score *and* the reason) and `match_skill()`.
- Threaded an optional `ResumeIndexer` through the graph → `MatchScoringAgent` →
  `calculate_match()` so evidence can come from the vector index.
- Wired `"Match Calculator"`, `overall_score` and `recommendation` into the
  execution trace via `trace_fields()`.
- Tests: 511 → 671.

**Deviations from the prompt, and why**

- **Two extra private methods.** The spec listed five weighted components but
  named only four methods; `_calculate_soft_skill_match()` and
  `_calculate_education_match()` were added so each component has one.
- **`calculate_match()` takes an optional third argument, `retriever`.** The spec
  asked for evidence "retrieved from resume via RAG" but the two-argument
  signature has no way to reach the index. It defaults to `None` and falls back
  to scanning the resume text, so the documented call still works.
- **Extra keys in the output.** The four specified keys are all present; the
  report also carries `matched_skills`, `missing_skills`, `recommendations` and
  `job_title` (needed by `MatchResult` and the graph), and each component carries
  `weight` / `applicable` / `evidence` / `matches`.
- **The legacy `calculate()` was kept**, but reduced to a wrapper that delegates,
  so there is only one scoring implementation.

**Bugs this prompt exposed**

- **`"Mentored three junior engineers"` did not register as mentoring.**
  `_SOFT_ALIASES` had `mentor`, `mentors`, `mentorship` and `coaching` but not
  `mentored`, and the matcher uses word boundaries, so the most common past-tense
  form on a resume was invisible. Added.
- **The RAG index was queried twice for every skill** — once by `skills`, once by
  `tech_stack`, which are overlapping sets. `_EvidenceFinder` now caches per
  skill.
- **`go` never matched `golang`** (SequenceMatcher scores them 0.5, and names
  under 5 characters are excluded from fuzzy matching by design). Added as an
  explicit alias.
- **`rag` was scored missing for a resume that said "built a retrieval augmented
  generation assistant".** Added the spelled-out form as an alias, and made the
  evidence scanner alias-aware so it can quote the sentence that earned the
  point.

**Deliberate behaviour changes**

- The old required-0.75 / preferred-0.25 model is gone; 11 tests asserting it
  were rewritten rather than kept passing.
- A job analysis with no assessable requirements now scores `0.0` with low
  confidence instead of `100.0`.
- An empty resume now scores `0.0` instead of `25.0`.

### Prompt 6 — 2026-08-31
> "Create the Job Analyzer Agent that understands job descriptions. Create
> agents/job_analyzer.py with JobAnalyzerAgent class: analyze(job_description)
> and extract_requirements() returning required_skills, tech_stack,
> experience_level, soft_skills, education, role_type. Extract hard skills, soft
> skills, years of experience, company size indicators, seniority level and role
> focus area. Use the given prompt template. Output required_skills, tech_stack,
> experience_years, soft_skills, education, role_type, seniority, confidence. Add
> to execution trace with node name 'Job Analyzer', status 'completed', extracted
> skills count and confidence score. Handle empty JD, malformed text and LLM
> timeout. Also update readme file uptodate."

Done:
- `JobAnalyzerAgent(BaseAgent)` in `agents/job_analyzer.py` — LLM-first with a
  keyword fallback, `analyze()`, `extract_requirements()`, `trace_fields()`.
- Standalone extractors, each independently testable: `extract_experience_years`,
  `experience_level`, `extract_education`, `detect_role_type`,
  `detect_company_size`, `validate_description`, `score_confidence`.
- Soft-skill vocabulary (20 terms) and `tech_stack()` in `utils/skills.py`, plus a
  `CONCEPT_SKILLS` set so concepts can be told apart from tools.
- The prompt template in `ollama_handler.py` replaced with the one specified.
- Node 1 of the graph now uses this agent; the trace carries `label`,
  `skills_extracted` and `confidence`.
- Trace status renamed `ok` → `completed` as specified (`STATUS_OK` kept as an
  alias so existing code still reads naturally).
- 117 new tests; suite now 511 passing.

Deviations, and why:

| Spec | Built | Why |
|---|---|---|
| `JobAnalyzerAgent` in a new file | Added to the existing `job_analyzer.py` | The file already existed with the keyword analyzer the fallback needs. The old `JobAnalyzer` is untouched and still works. |
| `extract_requirements()` with no arguments | `extract_requirements(job_description=None)` | Callable with no argument exactly as specified — it reuses the last analysed description — but also usable standalone. |
| 8 output keys | 8 + `experience_level`, `company_size`, `preferred_skills`, `responsibilities`, `title`, `source`, `warning` | `company_size` was requested as an *analysis* item but not listed in the output, so it needed somewhere to go; the rest are what the matching node already consumes. |
| `JobAnalysisAgent` in `base_agent.py` (from prompt 5) | Deleted, replaced by this | Two agents doing the same job would have drifted apart. |

Bugs found and fixed:

| Problem | Fix |
|---|---|
| A "Senior AI Engineer" advert was classified **junior** — `_detect_seniority` returned the first matching pattern in dict order, and the text said "mentor junior engineers" | Take the earliest level *mentioned*, tie-broken towards the more senior label |
| `base_agent` imported `job_analyzer` while `job_analyzer` needed `BaseAgent` — an import cycle that would break at package init | Dependency now runs one way; `build_tools()` imports lazily |
| "3–5 years" also matched the single-figure pattern, registering as 5 | Ranges are consumed first, and report their lower bound |
| Substring soft-skill matching made "lead" fire on "leader", "leadership" and collide with seniority detection | Word-boundary patterns, and bare "lead" excluded from the soft-skill vocabulary |

### Prompt 5 — 2026-08-31
> "Set up LangChain integration and LangGraph for agent orchestration. Create
> agents/__init__.py with an AgentConfig class (LLM configuration using Ollama or
> Claude fallback, temperature, model name, max tokens, timeout). Create
> agents/base_agent.py with a BaseAgent class (initialize LLM, prompt templates,
> tool definitions, error handling). Create agents/workflow_state.py defining
> StateDict for LangGraph. Create agents/graph_builder.py with a WorkflowGraph
> class (StateGraph, nodes analyze_job / extract_skills / detect_gaps /
> calculate_match, edges, compile, execute(state), execution trace). Create
> ollama_handler.py with a connection to local Ollama, prompt templates for job
> analysis and a Claude fallback. Make sure the graph can execute and log each
> step in execution trace."

**Done**
- Installed `langchain==0.1.14`, `langgraph==0.0.40` and added
  `langchain-community==0.0.31` to [backend/requirements.txt](backend/requirements.txt).
- [agents/__init__.py](backend/agents/__init__.py) — `AgentConfig` dataclass with
  full validation, `LLMProvider` enum (`ollama` / `claude` / `auto`),
  `from_settings()`, `copy_with()`, `describe()`. Existing `JobAnalyzer` /
  `MatchCalculator` re-exports kept.
- [agents/ollama_handler.py](backend/agents/ollama_handler.py) — `OllamaHandler`
  (cached availability probe, model listing, generation via LangChain),
  `ClaudeHandler` (optional `anthropic` SDK), `LLMClient` router with retries,
  three prompt templates, and `parse_json_response()`.
- [agents/base_agent.py](backend/agents/base_agent.py) — `BaseAgent`,
  `AgentResult`, the four concrete agents, `build_tools()`.
- [agents/workflow_state.py](backend/agents/workflow_state.py) — `WorkflowState`
  (`StateDict` alias), append reducer, `StepTimer`, trace helpers.
- [agents/graph_builder.py](backend/agents/graph_builder.py) — `WorkflowGraph`
  with the four nodes, linear edges, lazy compile, `execute(state)` and the
  tracing wrapper.
- New settings in [backend/config.py](backend/config.py): `LLM_HEALTHCHECK_TIMEOUT`,
  `LLM_MAX_RETRIES`, `LLM_FALLBACK_ENABLED`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`.
  `LLM_MODEL` changed `llama3` → `mistral` to match the prompt.
- 188 new tests across four files. **394 passing in ~2.3 s**, still fully offline.

**Verified**
Ran the compiled graph with the Ollama daemon *not* running:

```
analyze_job -> extract_skills -> detect_gaps -> calculate_match  (29.3 ms)
skills_found: docker, fastapi, langchain, microservices, postgresql, python
gaps: aws, kubernetes        score: 50.0
```

All four nodes reported `status: ok` via the deterministic tier, and the trace
recorded step number, duration and detail for each.

**Deviations**
- `ollama_handler.py` was placed in `agents/` rather than the backend root, next
  to the code that uses it.
- The `ollama` pip package is not imported. LangChain talks to the daemon over
  plain HTTP, so adding a second client would be redundant.
- The four concrete agents live in `base_agent.py` rather than a fifth module,
  since the prompt asked for "tool definitions" there and the tools *are* the
  agents. *(Superseded in prompt 6: the job analyser moved to `job_analyzer.py`.)*
- `anthropic` is left uninstalled and commented out in `requirements.txt`. It is
  only needed if you actually want the Claude tier.

**Problems hit**
- `pip install langchain==0.1.14` downgraded `packaging` 26.3 → 23.2, which warns
  about `build`. Harmless — `build` is only a chromadb build-time helper — and
  chromadb 0.4.24 still imports and all 206 pre-existing tests still pass.
- LangGraph 0.0.40 has no `START` constant; the entry point is set with
  `set_entry_point()`.
- On Python 3.9, `typing.TypedDict` loses `Annotated` metadata, so LangGraph
  cannot find the reducer. Switched to `typing_extensions.TypedDict`.
- First draft gave every agent its own `LLMClient`, so a missing Ollama daemon
  was probed four times per run. Now one client is shared by the graph.

### Prompt 4 — 2026-08-29
> "Build the resume RAG system for CareerPilot AI. Create rag/resume_indexer.py with
> a ResumeIndexer class (sentence-transformers, ChromaDB, index/search/context/clear
> methods), PDF processing, 250/50 chunking, metadata, error handling.
> Production-ready and testable."

**Done**
- Rewrote [rag/resume_indexer.py](backend/rag/resume_indexer.py) (~700 lines): all seven
  required methods plus `search_by_technology`, `get_profile`, `stats`, `count`, `is_empty`.
- Section-aware parsing, 250/50 chunking, cosine-scored search, `SearchResult` model
  with `as_context()`, `format_as_context()` helper.
- Error types `IndexerError` / `FileValidationError` / `DocumentParseError`; validation
  for missing, empty, oversized, unsupported and corrupt/encrypted files.
- Added `utils/skills.py` (shared vocabulary) and pointed `job_analyzer` at it.
- Added `ResumeProfile` and `SearchResult` to `career_models`, replacing `ResumeChunk`.
- Config: `CHUNK_SIZE` 1000→250, `CHUNK_OVERLAP` 200→50, new `CHROMA_DISTANCE`.
- Tests: 76 → **206**, split into `test_resume_indexer.py` (pure helpers),
  `test_indexer_store.py` (real Chroma), `test_skills.py`.

**Dependency fixes — the pinned versions did not work together**
| Problem | Fix |
|---|---|
| `sentence-transformers==2.2.2` imports `cached_download`, removed from `huggingface_hub>=0.26` | Bumped to `2.7.0` |
| `chromadb==0.4.24` uses `np.float_`, removed in NumPy 2.0 | Pinned `numpy==1.26.4` |
| chromadb 0.4.24 telemetry calls modern posthog with the wrong signature, logging an ERROR per operation | `ChromaSettings(anonymized_telemetry=False)` |

**Bugs found and fixed by the new tests**
1. `find_skills` used substring matching, so `"go"` matched inside `"django"` and
   `"sql"` inside `"postgresql"`. Replaced with `(?<!\w)…(?!\w)` lookaround patterns,
   which also work for `c++` and `c#` where `\b` does not.
2. The name heuristic accepted any 2-4 alphabetic words, so `"Built things"` was read
   as a candidate's name. Now requires every word to be capitalised.
3. `extract_text` on a missing file leaked `FileNotFoundError`; it now raises
   `DocumentParseError` like every other read failure.

**Verified end-to-end** (throwaway script, since deleted) with the real
`all-MiniLM-L6-v2` model, a hand-built PDF and a persistent on-disk Chroma:
PyPDF2 extraction → 5 sections → 8 chunks → `search_experience("scaling microservices
to millions of requests")` returned the correct line at score 0.529 →
`search_skills("container orchestration experience")` returned the skills line at
0.396 → data survived reopening from disk → `clear_index()` emptied it.

**Testing approach**
The suite never downloads a model or touches the network. `conftest.HashingEmbedder`
hashes tokens into a normalised bag-of-words vector, and the `indexer` fixture uses
`persist=False` for a real but in-memory Chroma. Full run: ~1.5 s.

### Prompt 3 — 2026-08-29
> "Create 2 readme files and update these both after each prompt i give from next.
> 1. Write unit tests for this module. Test the main functions and edge cases.
> 2. Write how this project works in easy words."

**Done**
- Added `tests/` with 76 unit tests across 5 files plus `conftest.py`.
- Added `pytest.ini` (`pythonpath = .`) and `requirements-dev.txt` (pytest, httpx==0.27.2).
- Created this file and `README_SIMPLE.md`; both are updated every prompt from now on.

**Bug found and fixed by the tests**
`chunk_text()` used `overlap = overlap or settings.CHUNK_OVERLAP`. Passing `overlap=0`
is falsy, so it silently became 200 — with `chunk_size=100` the step went negative,
clamped to 1, and produced ~250 chunks instead of 3. Changed to an explicit
`is None` check, and applied the same fix to `chunk_size` and to `top_k` in `search()`.

**Note**
`httpx` must be `<0.28`; newer versions removed the `app=` shortcut that
Starlette 0.35's `TestClient` relies on.

### Prompt 2 — 2026-08-29
> "Create a Python FastAPI backend for CareerPilot AI with the following structure…"

**Done**
- Scaffolded `backend/` with `main.py`, `config.py`, `models/`, `rag/`, `agents/`, `utils/`.
- Pinned the requested dependency versions in `requirements.txt`.
- Verified `/health`, upload success, and upload rejection against a live `TestClient`.

**Deviations**
- Used `Optional`/`List` instead of `X | None` because the interpreter is Python 3.9.
- `cors==1.0.1` is kept in `requirements.txt` as requested but is unrelated to FastAPI;
  CORS is handled by Starlette's `CORSMiddleware`.
- `sentence-transformers==2.2.2` + `chromadb==0.4.24` may fail to install on 3.9 due to a
  `huggingface_hub` incompatibility. Not yet hit, because those imports are lazy.

---

## Next up

- **Nothing outside `frontend/` is in version control, and `frontend/` only has
  its scaffold committed.** 19,581 lines of backend application code, 1,786 of
  standalone scripts, 12,842 of pytest suite, 5,389 of TypeScript and all three
  READMEs exist on one disk with no history. `git init` at `career-pilot-ai/`
  and a first commit — the `.gitignore` there is already written and correct.
  This outranks every other item here.
- **Deploying the frontend alone produces a broken site.** `NEXT_PUBLIC_API_URL`
  is baked into the bundle at build time, so a Vercel deployment would ship a
  page telling every visitor's browser to call `http://localhost:8000`. The
  backend has to be hosted and reachable first, then its URL set at build time,
  then its origin added to `CORS_ORIGINS`. In that order.
- **`README.md` claims MIT but there is no `LICENSE` file.** Needs a copyright
  holder's legal name and year. Either add the file or drop the claim.
- **`agents/job_hunt_pipeline.py` is not reachable from any endpoint.** 437
  lines, fully tested, imported only by its own test module. Either expose it
  (`POST /api/career/job-hunt` composing discover → analyse → shortlist) or
  record that it is intentionally library-only. Leaving it in the middle is how
  a feature quietly rots.
- Add `POST /api/v1/search` and `GET /api/v1/profile` so the indexed resume can be
  queried directly, not only scored against an advert.
- **The index is a single shared collection.** Uploading a second resume adds to it
  rather than replacing it, so `calculate-match` would then score a blend of both.
  `POST /api/career/clear` is the current workaround; per-user collections keyed on
  `document_id` are the real fix, and are needed before this is exposed to more
  than one person.
- **There is no authentication.** Every endpoint is open, and the CORS policy
  allows credentials. That is fine on localhost and must not ship as-is.
- Feed `get_full_context()` / `search_*()` output into `extract_skills` so the graph
  reasons over retrieved evidence instead of the raw resume text.
- Score `preferred_skills` as a separate bonus band — `calculate_match` reads
  `required_skills` and `tech_stack`, and still ignores the preferred list.
- Run `ollama pull mistral` and re-verify the graph on the LLM tier rather than the
  deterministic one.
- **There is no authentication.** Every request goes out as the user id
  `local`, and anyone who can reach the API reads the same rows. That is why
  the settings page has no profile, password, session or account controls. If
  they are wanted, the backend needs a user table and a session mechanism
  first — the UI is the last part of that job, not the first.
- **`interview_rate` and `offer_rate` are strings.** Charting either over time
  means parsing the `%` back off or adding numeric fields to the response. The
  current charts plot counts, which are already numbers, and sidestep it.
- **There is no time series.** Every metric is a single current value, so
  "applications per week" and any trend line are unavailable. The brief for
  part 5 asked for a `+12 this month` trend; the data to compute one does not
  exist. `created_date` is on each application, so a client-side rollup is
  possible — but it belongs in the backend next to the sample-size guards.
- **There is no delete-application endpoint.** Applications created while
  testing stay for good. `/my-applications` will accumulate them, and every
  rate on `/analytics` is computed over all of them.
- **`upcoming[].job` is populated with the app id** rather than the job title,
  and `interview_date` is always null because nothing ever sets one. The
  dashboard does not surface `upcoming` yet, which is the only reason this has
  not shown up on a screen.
- **There is no interview scheduling.** No calendar, no reminders, no email.
  `interviews` is always `[]`. Part 4's brief claimed this as a shipped feature
  and the README does not repeat the claim.
- **`analyze_job` takes the whole first sentence as the title** when an advert
  has no line breaks. The analyse page now displays that title verbatim, in the
  trace detail and in `resume_optimizations.tailored_summary`, so a single-
  paragraph advert produces "Senior Python Engineer. We need 5+ years of Python
  specialising in…". The extraction needs a length cap; the frontend is
  reporting it faithfully, which is how it became visible.
- **The index is one shared collection.** The analyse page states this and
  offers a Clear button, but per-document collections keyed on `document_id`
  are still the real fix.
- **Discovered jobs live in an in-memory map.** `save-job` 404s for any advert
  found before the last backend restart. `JobCard` explains this when a save
  fails, but the real fix is persisting the discovery results.
- **There is no unsave.** The UI reflects that honestly rather than faking it,
  but `DELETE /api/career/saved-job/{id}` is the missing endpoint.
- **An application cannot be created from a pasted advert.**
  `create-application` requires a `job_id`, so `/analyze` has no way to hand
  its result to the tracker. Either the endpoint accepts an ad-hoc job, or the
  analyse page has to be able to mint one. Tracking from `/my-jobs` works
  because a saved job has an id; that is the only route in.
- Frontend state: `zustand` and `framer-motion` are installed and still unused.
  `recharts` earns its place on `/analytics`. Week 3 is done, so the other two
  come out of `package.json` unless something concrete needs them.

---

## Deployment

Folded in from the former `docs/DEPLOYMENT.md` when the documentation was
consolidated down to two files.


This document covers what is actually deployable today, and says plainly what
is not. A deployment guide that describes a platform the application cannot run
on wastes an afternoon before it fails.

---

## 1. Local (the supported path)

This is the only configuration that has been run end to end.

```bash
cd career-pilot-ai/backend
python3.9 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Verify:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/health/full
```

**Python 3.9 is required, not merely supported.** The codebase targets 3.9
syntax throughout (`Optional[str]`, never `str | None`). Newer interpreters will
run it; older ones will not.

### The optional LLM

Nothing here needs an LLM. Every agent has a deterministic fallback and the
whole test suite runs with no model reachable. To enable one:

```bash
ollama serve
ollama pull mistral
```

Or set `ANTHROPIC_API_KEY` for the Claude fallback (and uncomment `anthropic`
in `requirements.txt`). `/api/health/full` reports which backends are reachable.

---

## 2. Docker

`chromadb` and `sentence-transformers` pull in PyTorch, so the image is large.
The installed virtualenv on this machine measures **914 MB**; a slim image lands
in roughly the same range. Plan for it rather than being surprised by it.

```dockerfile
FROM python:3.9-slim

# Build tools are needed by some wheels; removed again in the same layer so
# they do not ship in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential && apt-get autoremove -y

COPY backend/ .

# The embedding model is ~90 MB and is otherwise downloaded on the first
# request, which makes that request take several seconds. Bake it in.
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('all-MiniLM-L6-v2')"

# Do not run as root.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# The vector index and SQLite database live here. Mount a volume or they are
# lost on every redeploy.
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t careerpilot .
docker run -p 8000:8000 -v careerpilot-data:/app/data careerpilot
```

Two things that bite:

- **`--start-period=60s` matters.** Cold start loads the embedding model. A
  30-second health check will kill the container before it is ready and the
  orchestrator will loop forever.
- **Ollama is not in this image.** If you want it, run it as a separate
  container and set `OLLAMA_BASE_URL=http://ollama:11434`. `host.docker.internal`
  works on Docker Desktop and not on Linux.

---

## 3. Vercel

**The backend cannot run on Vercel serverless functions.** This is not a
configuration problem to work around:

| Constraint | Vercel limit | This application |
|---|---|---|
| Deployment bundle | 250 MB uncompressed | ~914 MB with torch + chromadb |
| Filesystem | read-only except `/tmp`, wiped per invocation | Chroma and SQLite need durable writes |
| Execution time | 10–60 s depending on plan | Cold start alone loads an embedding model |
| Process model | stateless, no shared memory | in-process caches and a lazy thread pool |

The **frontend** deploys to Vercel perfectly well:

```bash
cd frontend
vercel --prod
# set NEXT_PUBLIC_API_URL to wherever the backend actually runs
```

For the backend, use something that gives you a container and a disk — Fly.io,
Railway, Render, a VPS, or ECS. Any of them will do; all of them need the
volume.

---

## 4. Database

There is no database server to provision. Two SQLite files under
`backend/data/`:

| File | Holds |
|---|---|
| `data/jobs.db` | saved jobs, applications, application events |
| `data/chroma/` | the vector index (Chroma's own storage) |

Schemas are created on first use — no migration step. To reset:

```bash
curl -X POST http://127.0.0.1:8000/api/career/clear   # index + caches
rm backend/data/jobs.db                                # saved jobs + applications
```

**SQLite is the right choice here and the wrong choice later.** It is fine for
one user on one machine, which is what this is. It will not survive several
container replicas writing to a shared volume. Moving to Postgres means
replacing the connection handling in `agents/job_storage.py` and
`agents/application_tracker.py`; the SQL itself is close to portable.

### One thing to know about `job_id`

`jobs.job_id` is the primary key, but every read is scoped by `user_id`. When
two different users save the same advert, the second save is given a freshly
minted id for that user's own row. So **`job_id` in the saved-jobs table is not
the advert's id from the job board** — it identifies one user's copy. Do not
join on it across users.

---

## 5. Environment variables

Everything has a working default. Copy `.env.example` to `.env` and change only
what you need.

| Variable | Default | Notes |
|---|---|---|
| `HOST` / `PORT` | `0.0.0.0` / `8000` | |
| `DEBUG` | `true` | **Set to `false` in production.** |
| `CORS_ORIGINS` | localhost dev origins | Must list your real frontend origin. |
| `MAX_UPLOAD_SIZE_MB` | `10` | |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Changing it invalidates the index. |
| `CHROMA_DB_PATH` | `data/chroma` | Put on the mounted volume. |
| `JOBS_DB_PATH` | `data/jobs.db` | Put on the mounted volume. |
| `LLM_PROVIDER` / `LLM_MODEL` | `ollama` / `mistral` | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `ANTHROPIC_API_KEY` | unset | Secret. Never commit it. |
| `LLM_FALLBACK_ENABLED` | `true` | Deterministic path when no model answers. |
| `JOB_DISCOVERY_ENABLED` | `true` | `false` makes `/discover-jobs` return 503. |
| `JOB_FETCH_TIMEOUT_SECONDS` | `10.0` | |
| `LOG_LEVEL` | `INFO` | |
| `LOG_TO_FILE` | `true` | Set `false` on a platform that collects stdout. |

### Before exposing this to anyone else

**There is no authentication.** `user_id` namespaces rows; it does not protect
them. Anyone who can reach the API can pass any `user_id` and read that
person's saved jobs and applications. Put it behind an authenticating proxy, or
keep it on localhost. This is a limitation, not a bug, but it is the one that
matters most if you deploy it.

Also:

- `DEBUG=false`, or stack traces reach callers.
- Set `CORS_ORIGINS` to your actual origin, not `*`.
- There is no rate limiting. `/full-analysis` is the expensive endpoint.

---

## 6. Monitoring and logs

### Endpoints

| Endpoint | Use |
|---|---|
| `GET /health` | Liveness. Cheap, no dependencies touched. |
| `GET /api/health/full` | Per-dependency readiness: `services[]`, each with `status`, `duration_ms`, `required`. `overall_status` is `healthy` / `degraded` / `unhealthy`. |
| `GET /api/health/performance` | Latency percentiles per operation, plus cache hit rates. |

Point the orchestrator's liveness probe at `/health` and its readiness probe at
`/api/health/full`. **`/health` deliberately does not run an LLM prompt** — a
liveness check that costs a model call will restart the process when the model
is merely slow.

`degraded` is a normal state, not an outage: it usually means no LLM is
reachable and the agents are on their deterministic path. Alert on
`unhealthy`, not on `degraded`.

### What `/api/health/performance` tells you

```json
{
  "operations": [
    { "operation": "rag.index_resume", "calls": 3, "p50": 6.459,
      "p95": 7520.617, "max": 7520.617 }
  ],
  "caches": {
    "job_analysis": { "hits": 30, "misses": 2, "hit_rate": 93.8, "entries": 1 }
  }
}
```

Percentiles are over a rolling window of the last 256 calls per operation, so
they describe recent behaviour rather than an all-time average that a slow
start hides forever. **A hit rate of 0 on a cache with traffic means the cache
is broken**, not that it is cold — that is the single most useful number on the
page.

### Logs

Rotating files under `data/logs/app.log` (5 MB × 3), plus stdout. On a platform
that collects stdout, set `LOG_TO_FILE=false` and skip the volume for logs.

Logs record which backend answered each agent call and when a fallback was
used. They do not record resume text or advert text.

---

## 7. Pre-deployment checklist

```bash
cd backend
.venv/bin/python -m pytest -q                       # expect 2209 passed
.venv/bin/python -m ruff check --select F,ARG \
    --target-version py39 config.py main.py rag/ agents/ utils/
                                                    # expect exactly 4 findings
.venv/bin/python -m utils.benchmarks                # prints real timings
```

The four ruff findings are intentional and documented in `README_DEV.md`:
interface parameters that a base class requires and an implementation does not
use. Silencing them would hide the next real one.
