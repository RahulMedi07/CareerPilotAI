# CareerPilot AI — Project Overview

> A full-stack AI-powered career tool. Upload your CV once; the app tells you
> whether to apply for a job, what you are missing, how to fix your resume, and
> what you will be asked in the interview — with every answer traced back to
> the actual text of your CV.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Architecture](#3-architecture)
4. [Core Features](#4-core-features)
5. [How It Works — Deep Dive](#5-how-it-works--deep-dive)
6. [Database Schema](#6-database-schema)
7. [APIs / Endpoints](#7-apis--endpoints)
8. [Setup & Run Instructions](#8-setup--run-instructions)
9. [Interview Prep Section](#9-interview-prep-section)
10. [Possible Improvements](#10-possible-improvements)

---

## 1. Project Overview

CareerPilot AI is a **locally-running, full-stack career intelligence tool** built for software engineers in the Indian job market. The problem it solves is specific: most job platforms tell you what jobs exist; none tell you whether you should actually apply for a particular one, or why. CareerPilot reads your CV and a job advert together, scores your match against every stated requirement, identifies what you are missing and how long it would take to learn, rewrites your CV for the specific role, and generates a full round of tailored interview questions — all without sending your data anywhere.

The target user is a developer who is actively job-hunting and wants an honest, evidence-based view of where they stand before spending time on an application. The app surfaces its reasoning at every step: the match score is not a black box — it is a breakdown by skills, tech stack, experience years and education, each traced back to a line on the CV that proves it. An answer from the AI is labelled `llm` or `fallback` so the user always knows how it was produced.

The entire system runs on your own machine. Accounts, session tokens, the resume index, saved jobs and application history are all stored in local SQLite databases and a local vector store. No third-party service ever sees your CV or your career data unless you supply an LLM API key to make the AI answers richer — and even then, only the prompt is sent, never the raw file.

---

## 2. Tech Stack

### Frontend

| Tool | Version | Purpose |
|---|---|---|
| **Next.js** | 16.3.4 | React framework, App Router, Turbopack dev server |
| **TypeScript** | 5.x | Static typing across all components and API calls |
| **Tailwind CSS** | v4 | Utility-first styling, custom OKLCH colour palette |
| **shadcn/ui** | latest | Headless component primitives (Card, Badge, Select, Dialog…) |
| **Radix UI** | via shadcn | Accessible dialog, select, and disclosure primitives |
| **Axios** | 1.20 | HTTP client with typed responses and 120 s timeout |
| **Lucide React** | latest | Icon set |
| **next-themes** | latest | System / light / dark theme with no flash |
| **Vitest** | 4.1 | Unit test runner |

### Backend

| Tool | Version | Purpose |
|---|---|---|
| **Python** | 3.9 | Runtime |
| **FastAPI** | 0.109 | REST API framework, async, OpenAPI auto-docs |
| **Uvicorn** | 0.27 | ASGI server with watchfiles auto-reload |
| **Pydantic v2** | 2.5 | Request/response validation and settings |
| **pydantic-settings** | 2.1 | Typed config from `.env` |
| **LangChain** | 0.1.14 | Agent orchestration primitives |
| **LangGraph** | 0.0.40 | Stateful multi-node workflow graph |
| **langchain-community** | 0.0.31 | Ollama LLM integration |
| **sentence-transformers** | 2.7.0 | `all-MiniLM-L6-v2` embedding model for RAG |
| **ChromaDB** | 0.4.24 | Local vector store for resume embeddings |
| **NumPy** | 1.26.4 | Required by ChromaDB (pinned — v2 removed `np.float_`) |
| **PyPDF2** | 3.0.1 | PDF text extraction |
| **python-docx** | via sentence-transformers | `.docx` parsing |
| **python-multipart** | 0.0.6 | File upload handling |
| **requests** | 2.32.5 | Outbound HTTP for job feeds and Gemini API |
| **python-dotenv** | 1.0.0 | `.env` loader |
| **pytest** | 8.3.4 | Test runner (2 517 tests) |
| **httpx** | 0.27.2 | FastAPI `TestClient` |

### Databases

| Store | Technology | What it holds |
|---|---|---|
| **Vector store** | ChromaDB (SQLite-backed) | Resume text chunks as 384-dim embeddings |
| **User accounts** | SQLite (`users.db`) | `users` table, `sessions` table |
| **Jobs + applications** | SQLite (`jobs.db`) | `jobs`, `applications`, `application_events`, `interviews` |

### LLM Providers (configurable, all optional)

| Provider | How connected | Notes |
|---|---|---|
| **Google Gemini** | Direct REST via `requests` | Recommended; free tier available |
| **Anthropic Claude** | `anthropic` SDK (optional install) | Fallback when Gemini fails |
| **Ollama** | `langchain-community` | Fully local; no API key; needs `ollama pull mistral` |

### Job Data Sources

| Source | How accessed | India-specific |
|---|---|---|
| **Adzuna** | Licensed REST API (free key) | ✅ `api.adzuna.com/v1/api/jobs/in/…` |
| **Hacker News "Who's Hiring"** | Algolia search API | — |
| **Remotive** | Public REST API | — |
| **Arbeitnow** | Public REST API | — |
| **WeWorkRemotely** | RSS feed | — |
| **Indian ATS boards** | Greenhouse / Lever / Ashby JSON | ✅ Paytm, Meesho, CRED, Groww, Postman, Druva, and 11 more |

### Testing

- **pytest** — 2 517 backend tests across 35+ test files
- **Vitest** — 11 frontend tests (`health.test.ts`, `api-errors.test.ts`)
- **FastAPI TestClient** (httpx) — full HTTP integration tests without a live server

---

## 3. Architecture

### High-level flow

```
Browser (Next.js)
      │
      │  HTTP + httpOnly cookie session
      ▼
FastAPI (port 8000)
      │
      ├── Auth layer ──────────────────► SQLite users.db
      │   (PBKDF2 passwords, opaque tokens)
      │
      ├── RAG layer ───────────────────► ChromaDB (vector store)
      │   (sentence-transformers embed)
      │
      ├── AI pipeline (LangGraph) ─────► LLM (Gemini / Claude / Ollama)
      │   8-node workflow graph            or deterministic fallback
      │
      ├── Job discovery ───────────────► External APIs & RSS feeds
      │   (robots.txt, rate limiting,       Adzuna, HN, Remotive,
      │    SSRF protection)                 India ATS boards
      │
      └── Storage ─────────────────────► SQLite jobs.db
          (jobs, applications, events)
```

### Folder structure

```
career-pilot-ai/
│
├── backend/
│   ├── main.py                 ← FastAPI app, all 26 API routes
│   ├── config.py               ← Pydantic Settings, all env vars typed
│   ├── models/
│   │   ├── auth_models.py      ← LoginRequest, SignupRequest, AccountResponse
│   │   └── career_models.py    ← All 30+ Pydantic response models
│   ├── agents/
│   │   ├── base_agent.py       ← Abstract BaseAgent (LLM + fallback skeleton)
│   │   ├── complete_workflow.py ← 8-step pipeline orchestrator
│   │   ├── graph_builder.py    ← LangGraph WorkflowGraph
│   │   ├── workflow_state.py   ← TypedDict shared state (LangGraph nodes)
│   │   ├── job_analyzer.py     ← Extracts skills/requirements from advert
│   │   ├── match_calculator.py ← Scores CV against 5 dimensions
│   │   ├── gap_detector.py     ← Finds missing skills + learning time
│   │   ├── resume_optimizer.py ← Rewrites CV bullet points for role
│   │   ├── resume_profiler.py  ← Standalone CV analysis (no job)
│   │   ├── interview_prep.py   ← Generates 6 question categories
│   │   ├── answer_coach.py     ← Scores a practice answer
│   │   ├── career_chat.py      ← Stateless assistant (RAG-grounded)
│   │   ├── job_scraper.py      ← All external job feed fetchers
│   │   ├── job_enricher.py     ← Parallel score/classify discovered jobs
│   │   ├── job_storage.py      ← SQLite jobs CRUD
│   │   ├── application_tracker.py ← SQLite applications + events CRUD
│   │   └── application_analytics.py ← Interview rates, predictions
│   ├── rag/
│   │   └── resume_indexer.py   ← Parse → chunk → embed → store → search
│   └── utils/
│       ├── auth.py             ← PBKDF2 passwords, opaque session tokens
│       ├── cache.py            ← Thread-safe TTL + LRU cache (SHA-256 keys)
│       ├── error_handling.py   ← Exception hierarchy
│       ├── health_check.py     ← RAG / LLM / DB probes
│       ├── logger.py           ← Structured rotating file logger
│       ├── performance_monitor.py ← p50/p95/max latency per operation
│       ├── retry_handler.py    ← Exponential backoff decorator
│       ├── skills.py           ← 200+ skill vocabulary for keyword matching
│       └── validation.py       ← Safe coercions (as_int, as_list, as_dict)
│
└── frontend/
    ├── app/
    │   ├── layout.tsx          ← Root layout: ThemeProvider + AuthProvider
    │   ├── login/page.tsx      ← Sign-in form
    │   ├── signup/page.tsx     ← Account creation form
    │   └── (dashboard)/        ← All protected pages (RequireAuth guard)
    │       ├── layout.tsx      ← Sidebar + Header + Footer shell
    │       ├── page.tsx        ← Home: upload flow → resume summary
    │       ├── my-resume/      ← CV breakdown (role, skills, strengths)
    │       ├── discover-jobs/  ← Job search (7-day filter, India default)
    │       ├── analyze/        ← Full analysis: job + CV → 8-step result
    │       ├── interview-prep/ ← 6-category question set + practice mode
    │       ├── assistant/      ← Chat grounded in indexed CV
    │       ├── my-jobs/        ← Saved adverts
    │       ├── my-applications/← Application list + detail + status updates
    │       └── settings/       ← Resume management, theme, account
    ├── components/
    │   ├── auth/               ← AuthForm, RequireAuth guard
    │   ├── dashboard/          ← JobCard, AnalysisResults, PracticeRoom…
    │   ├── layout/             ← Header, Sidebar, Footer
    │   ├── providers/          ← AuthProvider (React context), ThemeProvider
    │   ├── shared/             ← ErrorMessage, LoadingSpinner, SourceBadge
    │   └── ui/                 ← shadcn primitives (button, card, input…)
    ├── lib/
    │   ├── api.ts              ← All API call wrappers (typed, Axios)
    │   ├── auth-rules.ts       ← MIN_PASSWORD_LENGTH shared constant
    │   └── interview-handoff.ts ← sessionStorage bridge: job → interview prep
    └── types/index.ts          ← All TypeScript interfaces mirrored from API

```

### Key design patterns

- **Agent + fallback**: Every AI agent (8 of them) has a deterministic fallback so the pipeline always completes, with or without an API key. The `source` field (`"llm"` vs `"fallback"`) is always returned so the UI can say which mode ran.
- **LangGraph stateful workflow**: The 8-step pipeline uses a `TypedDict` state that flows node-to-node. `execution_trace` uses `Annotated[List, operator.add]` so each node appends without overwriting.
- **RAG over resume**: The CV is chunked (250 tokens, 50 overlap), embedded with `all-MiniLM-L6-v2`, stored in ChromaDB, and searched semantically rather than by keyword. This means "built REST services" matches "FastAPI microservices" without exact wording.
- **Thread-safe TTL cache**: `utils/cache.py` uses SHA-256 of canonical JSON as the key (not `hash()`, which is process-randomised since Python 3.3) and a threading lock for the LRU eviction loop.
- **Opaque session tokens**: Login stores only `SHA-256(token)` in the DB; the raw token lives in an `httpOnly` cookie the browser cannot read. Logout deletes the row — no JWT revocation list needed.
- **SSRF protection in job scraper**: Every outbound URL is checked against `ALLOWED_HOSTS`, DNS-resolved and rejected if the IP is private/loopback/link-local, redirects are not followed blindly, responses are size-capped at 2 MB, and XML DTDs are rejected.

---

## 4. Core Features

- **Resume upload** — PDF, DOCX, TXT or MD (up to 10 MB), chunked and embedded into a local vector store on upload. One upload; every downstream feature reads from it.
- **Resume insights** — Standalone CV analysis with no job involved: primary role, seniority, years of experience, education, skills grouped by category, strengths, improvements, and suggested job titles to search for.
- **Job discovery** — Live job search filtered to the last 7 days, India by default. Sources: Adzuna (licensed), Hacker News, Remotive, Arbeitnow, WeWorkRemotely RSS, plus 17 Indian company ATS boards (Paytm, Meesho, CRED, Groww, Postman, Druva, and others).
- **Full AI analysis** — 8-step pipeline: extract job requirements → extract resume skills → calculate match (0–100, across 5 dimensions) → detect skill gaps (with learning time estimates) → optimise resume (bullet-point rewrites) → prepare interview questions → generate recommendation (APPLY / MAYBE / SKIP). Full execution trace returned.
- **Interview preparation** — Six question categories: technical skills, project-specific (quoting your own CV), behavioural, situational/scenario, HR (salary, notice period), and company research. Optional job advert to tailor them.
- **Practice mode** — One question at a time; type your answer and get scored feedback (strengths, gaps, improved opening line).
- **AI assistant** — Stateless chat grounded in the indexed CV. Optionally attach a job advert. Every reply labelled `llm` or `fallback`.
- **Saved jobs** — One-click save from search results. Persisted in SQLite; survives server restart. Unlike discovered jobs which are in-memory only.
- **Application tracker** — Create, update and track job applications through five statuses: draft → sent → interview → rejected / offer. Full event timeline recorded on every status change.
- **Analytics** — Interview rate (with 95% confidence interval), offer rate, average match score when applied vs interviewed, days-to-interview median, and a strategy recommendation. All rates reported as `null` when sample is too small.
- **Settings** — Resume management (upload, clear), light/dark/system theme toggle (stored in browser, not account), health status panel when something is broken.
- **Auth** — Email/password accounts, PBKDF2-HMAC-SHA256 (600 000 iterations), opaque `httpOnly` session cookies, 2-week TTL, instant revocation on logout.

---

## 5. How It Works — Deep Dive

### Auth flow

1. **Signup**: `POST /api/auth/signup` → `UserStore.create_user()` generates a `usr_` prefixed UUID, hashes the password with PBKDF2-HMAC-SHA256 (600 000 iterations, 16-byte random salt per NIST SP 800-132), stores only the hash + salt in `users.db`. Returns `AccountResponse`.
2. **Login**: `POST /api/auth/login` → `UserStore.verify_password()` uses `hmac.compare_digest` (constant-time) to check the hash. On success, `UserStore.create_session()` generates `secrets.token_hex(32)` (256-bit token), stores `SHA-256(token)` in `sessions` table with an expiry 336 hours out, and sets an `httpOnly` `Set-Cookie` header.
3. **Session guard** (`main.py` `get_current_user`): reads the cookie → hashes it → queries `sessions` table → checks expiry → returns `user_id`. Every protected endpoint calls this as a FastAPI `Depends`.
4. **Logout**: `POST /api/auth/logout` → deletes the session row. Token stops working immediately.

### Resume upload & RAG indexing

1. `POST /api/career/upload-resume` — multipart file → `_store_upload()` writes to `data/uploads/{uuid}.{ext}`.
2. `ResumeIndexer.index_resume(path)`:
   - **Parse**: `.pdf` → PyPDF2; `.docx` → `python-docx`; `.txt`/`.md` → plain read.
   - **Chunk**: sliding window 250 tokens / 50 overlap. Each chunk also gets a `section` tag (contact, skills, experience, education, projects, etc.) inferred from surrounding headings.
   - **Embed**: `sentence-transformers` `all-MiniLM-L6-v2` → 384-dimensional float vectors.
   - **Store**: `chromadb` collection keyed on `(user_id, document_id)` so each user's index is isolated.
3. `ResumeIndexer.search_skills(query, top_k=5)` → semantic nearest-neighbour search, returns chunk text + distance score.

### Full analysis pipeline (`complete_workflow.py`)

```
POST /api/career/full-analysis
         │
         ▼
   CompleteWorkflow.run(job_description, user_id)
         │
         ├─ 1. analyze_job       JobAnalyzerAgent (LLM) / fallback: regex + vocab
         │      Extracts required_skills, preferred_skills, tech_stack,
         │      experience_years, experience_level, role_type
         │
         ├─ 2. extract_resume    RAG search (top 24 chunks) + ResumeProfilerAgent
         │      Builds skills_found, years, role, seniority from indexed CV
         │
         ├─ 3. calculate_match   MatchCalculator (no LLM)
         │      5 dimensions: skills, tech_stack, experience, education,
         │      soft_skills. Weighted average → score 0-100 + verdict
         │
         ├─ 4. detect_gaps       GapDetectorAgent (LLM) / fallback: set diff
         │      critical_gaps with learning_time_days, nice_to_have_gaps,
         │      total_learning_weeks
         │
         ├─ 5. optimize_resume   ResumeOptimizer (LLM) / fallback: rule-based
         │      improvements[], keywords_to_add, tailored_summary,
         │      high_impact_count
         │
         ├─ 6. prepare_interview InterviewPrepAgent (LLM) / fallback: templates
         │      questions[], behavioral, hr, scenario, project questions
         │
         ├─ 7. check_gaps_learnable  pure logic node
         │      compares total_learning_days vs 14-day window
         │
         └─ 8. final_recommendation  pure logic node
                APPLY (score≥80), MAYBE (60-79), SKIP (<60 or too many gaps)
                 → user_recommendation plain English string
```

Every node records `(name, status, duration_ms, output_summary)` in `execution_trace`. If a node throws, it is marked `error` and the pipeline continues with defaults — the caller always gets a full result object and never a 500.

### Job discovery flow

1. `POST /api/career/discover-jobs` with `{query, location, auto_from_resume, max_age_days: 7}`.
2. If `auto_from_resume=true`, `ResumeProfilerAgent` infers role + search phrases from the CV.
3. `JobScraper` fans out to all enabled sources concurrently (thread pool), with per-host rate limiting (1 req/s minimum) and 6-hour response caching.
4. Every URL is checked: `ALLOWED_HOSTS` allowlist → DNS resolve → reject private IPs (SSRF guard) → fetch (2 MB cap) → robots.txt (cached per host).
5. `JobEnricher` runs `JobAnalyzerAgent` on every discovered advert in a 10-worker thread pool to score it against the user's resume.
6. Results bucketed: `perfect_match` (≥80), `good_fit` (60–79), `stretch_goal` (40–59), `learning_needed` (<40), `unscored`.
7. Only adverts ≤7 days old are returned. Adverts with no `posted_date` are excluded while a date filter is active.

### State management (frontend)

No Redux, no Zustand. Every page manages its own state with `useState` + `useEffect`. The auth state (`account`, `signIn`, `signOut`) lives in `AuthProvider` (React context in `components/providers/AuthProvider.tsx`). The only cross-page state transfer is the "prepare for this interview" handoff: `lib/interview-handoff.ts` writes job title + description to `sessionStorage`; `interview-prep/page.tsx` reads it on mount.

### Error handling approach

- **Backend**: Custom exception hierarchy (`CareerPilotException`, `AnalysisError`, `RAGIndexingError`, `JobScrapingError`). FastAPI exception handlers in `main.py` map these to `422`/`409`/`503`. The `409` status is used specifically for "no resume uploaded" so the frontend can distinguish it from a real error.
- **Frontend**: `describeApiError(error)` in `lib/api.ts` unwraps Pydantic's `detail` field (which can be a string or a list of validation error objects) and returns a human sentence. A 401 on `/api/auth/me` resolves to `null` (expected unauthenticated state) rather than throwing.
- **LLM failures**: Every `BaseAgent` subclass catches `LLMUnavailableError` and `LLMResponseError`, logs a warning, and returns its fallback output. The `source` field in the response records which path ran.

### Caching

`utils/cache.py` implements a thread-safe, size-capped (default 256 entries), TTL-expiring LRU cache:
- **Key**: `SHA-256(json.dumps(args, sort_keys=True))` — stable across restarts, collision-resistant, handles falsy values with a sentinel.
- **Used for**: job analysis results (7 200 s TTL) — the same advert asked about by two users at once hits the cache on the second call.
- **Not cached**: resume search results (per-user, personalised) and auth operations.

---

## 6. Database Schema

Three separate SQLite databases, each with a single concern.

### `data/users.db` — Authentication

```sql
users (
  user_id       TEXT PRIMARY KEY,   -- "usr_" + 16-char hex
  email         TEXT NOT NULL,       -- unique (case-insensitive index)
  name          TEXT DEFAULT '',
  password_hash BLOB NOT NULL,       -- PBKDF2-HMAC-SHA256, 600 000 iters
  salt          BLOB NOT NULL,       -- 16 random bytes, per-user
  iterations    INTEGER NOT NULL,
  created_date  TEXT NOT NULL,       -- ISO 8601 UTC
  last_login    TEXT                 -- nullable
)

sessions (
  token_hash   TEXT PRIMARY KEY,    -- SHA-256(raw_token), never the token
  user_id      TEXT REFERENCES users ON DELETE CASCADE,
  created_date TEXT NOT NULL,
  expires_date TEXT NOT NULL         -- created + SESSION_TTL_HOURS (336 h)
)
```

**Why separate from jobs.db?** You can delete job history without losing your account, and vice versa.

### `data/jobs.db` — Jobs and Applications

```sql
jobs (
  job_id       TEXT PRIMARY KEY,   -- deterministic hash of URL or title+company
  user_id      TEXT NOT NULL,
  title        TEXT NOT NULL,
  company      TEXT DEFAULT '',
  description  TEXT DEFAULT '',
  requirements TEXT DEFAULT '{}',  -- JSON
  analysis     TEXT DEFAULT '{}',  -- JSON (JobAnalysis)
  source       TEXT DEFAULT '',    -- "Adzuna", "HackerNews", "Paytm", …
  url          TEXT DEFAULT '',
  posted_date  TEXT DEFAULT '',
  saved_date   TEXT NOT NULL,
  updated_date TEXT NOT NULL,
  status       TEXT DEFAULT 'saved', -- saved|analyzed|applied|rejected|interview|offer
  match_score  REAL,               -- null = not yet scored
  notes        TEXT DEFAULT ''
)

applications (
  app_id          TEXT PRIMARY KEY,  -- UUID
  user_id         TEXT NOT NULL,
  job_id          TEXT DEFAULT '',
  job_title       TEXT DEFAULT '',
  company         TEXT DEFAULT '',
  match_score     REAL,              -- null when created without analysis
  gaps_identified TEXT DEFAULT '[]', -- JSON array of skill names
  status          TEXT DEFAULT 'draft', -- draft|sent|interview|rejected|offer
  created_date    TEXT NOT NULL,
  updated_date    TEXT NOT NULL,
  notes           TEXT DEFAULT ''
)

application_events (
  event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id TEXT REFERENCES applications ON DELETE CASCADE,
  event_type     TEXT NOT NULL,      -- "created", "status_changed", …
  details        TEXT DEFAULT '{}',  -- JSON with from/to status
  status_after   TEXT DEFAULT '',
  created_date   TEXT NOT NULL
)

interviews (
  interview_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id     TEXT REFERENCES applications ON DELETE CASCADE,
  interview_date     TEXT DEFAULT '',
  interviewer        TEXT DEFAULT '',
  performance_rating TEXT DEFAULT '',
  notes              TEXT DEFAULT '',
  next_round         INTEGER DEFAULT 0
)
```

**Why SQLite?** The data is small (hundreds to low thousands of rows per user), relational, written by one process, and needs zero server setup. A job board's worth of data fits in a few MB; SQLite handles it without ceremony.

**Why JSON columns for `analysis` / `requirements`?** Job analysis results are deeply nested and vary by source. Normalising them into 15 columns would make every query a join; JSON with typed Pydantic deserialization on read is the practical choice at this scale.

### `data/chroma/` — Vector Store (ChromaDB)

Not a table schema — a collection named `resumes`. Each document is a resume chunk with metadata:

```
{
  id:       "{user_id}_{doc_id}_{chunk_index}",
  embedding: float[384],           -- all-MiniLM-L6-v2
  document:  "chunk text",
  metadata: {
    user_id, doc_id, chunk_index,
    section,   -- "skills", "experience", "projects", …
    source,    -- "pdf", "docx", "txt"
    file_name,
    created_at
  }
}
```

---

## 7. APIs / Endpoints

All routes are in `backend/main.py`. Base URL: `http://localhost:8000`.

### Auth

| Method | Path | Purpose | Auth required |
|---|---|---|---|
| POST | `/api/auth/signup` | Create account | No |
| POST | `/api/auth/login` | Sign in, set session cookie | No |
| POST | `/api/auth/logout` | Delete session row | Yes |
| GET | `/api/auth/me` | Return current account | Yes (401 if none) |

**Login response:**
```json
{ "user_id": "usr_abc123", "email": "me@x.com", "name": "Rahul", "created_date": "…", "last_login": "…" }
```

### Resume & Analysis

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/career/upload-resume` | Multipart file → index into ChromaDB |
| GET | `/api/career/status` | `{ resume_indexed, chunks }` |
| POST | `/api/career/clear` | Remove all resume chunks for user |
| POST | `/api/career/resume-insights` | Standalone CV analysis |
| POST | `/api/career/full-analysis` | 8-step job match pipeline |
| GET | `/api/career/analysis/{id}/trace` | Execution trace for a past analysis |
| POST | `/api/career/analyze-job` | Job-only analysis (no resume) |

**Full analysis request:**
```json
{ "job_description": "…full advert text…" }
```
**Full analysis response (abbreviated):**
```json
{
  "analysis_id": "abc123",
  "overall_match": 71.8,
  "recommendation": "MAYBE",
  "user_recommendation": "Worth a shot. 72/100 with 6 critical gaps…",
  "analysis": { "job_analysis": {…}, "match_breakdown": {…}, "gaps": {…}, "resume_optimizations": {…}, "interview_prep": {…} },
  "execution_trace": [ { "step": 1, "node": "analyze_job", "status": "completed", "duration_ms": 4959 }, … ],
  "total_analysis_time_ms": 10816
}
```

### Job Discovery & Saved Jobs

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/career/discover-jobs` | Search live feeds with 7-day filter |
| POST | `/api/career/save-job` | Persist a discovered job to SQLite |
| GET | `/api/career/my-jobs` | List user's saved jobs |

**Discover request:**
```json
{ "query": "backend engineer", "location": "india", "max_age_days": 7, "auto_from_resume": false, "limit": 20 }
```

### Applications

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/career/create-application` | Create application from saved job |
| POST | `/api/career/application/{id}/update-status` | Move through pipeline |
| GET | `/api/career/my-applications` | List with status counts |
| GET | `/api/career/application/{id}/history` | Event timeline |
| GET | `/api/career/analytics` | Rates, predictions, strategy |

### AI Features

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/career/chat` | Stateless CV-grounded chat |
| POST | `/api/career/interview-prep` | Generate 6-category question set |
| POST | `/api/career/practice-answer` | Score a typed answer |

### Health & Observability

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Simple `{ status: "ok" }` |
| GET | `/api/health/full` | RAG / LLM / DB probe results |
| GET | `/api/health/performance` | p50/p95/max latency per operation |
| GET | `/docs` | OpenAPI (Swagger UI, auto-generated) |

---

## 8. Setup & Run Instructions

See **SETUP.md** in the project root for full platform-specific instructions (Mac, Linux, Windows).

**Quick start (Mac/Linux):**

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add GEMINI_API_KEY or ANTHROPIC_API_KEY
python main.py              # → http://localhost:8000

# Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local  # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                 # → http://localhost:3000
```

---

## 9. Interview Prep Section

### Why did you choose X over Y?

**FastAPI over Flask or Django**
FastAPI gives you automatic OpenAPI docs, async support, and Pydantic validation in one package. Flask would need four separate libraries to match that. Django is too opinionated for a single-service AI backend — its ORM, admin, and template engine would all be unused. FastAPI's `Depends` injection system made the auth guard (`get_current_user`) a one-liner at each route.

**SQLite over PostgreSQL or MongoDB**
The data model is relational (users → sessions, applications → events), the dataset is small (hundreds of rows per user), and the app runs on a single machine with a single process. PostgreSQL adds a server, a connection pool, and a network hop for no benefit at this scale. MongoDB would lose the foreign-key cascades that keep orphan events from piling up when an application is deleted. SQLite is exactly right here — and when the app grows to multi-user cloud deployment, the ORM layer (Pydantic + raw sqlite3) is the only thing that changes.

**ChromaDB over Pinecone or pgvector**
The key requirement is zero external services — the CV never leaves the machine. Pinecone is SaaS. pgvector adds a Postgres dependency. ChromaDB runs in-process against a local SQLite file and needs no setup beyond `pip install`. The tradeoff is that it does not scale horizontally, but for a single-user local tool that is not a tradeoff.

**LangGraph over plain function calls**
The 8-step pipeline has nodes that depend on earlier results (`optimize_resume` needs the gap report, `prepare_interview` needs both the match score and the gaps). LangGraph makes those dependencies explicit in the graph definition and handles the state merging. The `Annotated[List, operator.add]` reducer for `execution_trace` is the clearest example: without it, each node would overwrite the trace instead of appending. The fallback (plain Python loop in `complete_workflow.py`) exists for resilience — the graph is not required to complete the pipeline.

**`all-MiniLM-L6-v2` over OpenAI embeddings**
Local, free, and fast (384 dimensions vs 1536). The model was specifically designed for semantic similarity of short sentences, which is exactly what skill matching requires. Using an OpenAI embedding would break the "nothing leaves your machine" guarantee.

**Opaque session tokens over JWTs**
A JWT cannot be revoked without a server-side revocation list, at which point you have a session table anyway. Storing only `SHA-256(token)` — never the token — means a copy of the database cannot be used to resume any live session. This is explicitly documented in `utils/auth.py`.

**`httpOnly` cookies over `localStorage` tokens**
A token in `localStorage` is readable by any JavaScript on the page. An `httpOnly` cookie is not — it is attached by the browser automatically but cannot be read by `document.cookie`. The auth guide in `lib/api.ts` explains this choice in a comment: `withCredentials: true` is set so the cookie travels on cross-origin requests.

**PBKDF2 over bcrypt or scrypt**
`hashlib.scrypt` is unavailable on macOS's LibreSSL build (documented in `utils/auth.py`). `argon2` would add a dependency. PBKDF2-HMAC-SHA256 at 600 000 iterations is OWASP's recommendation when the better algorithms are unavailable, and 0.18 s/attempt on the dev machine makes brute-force expensive.

**Deterministic fallback on every AI agent**
The brief required the app to work without an API key. Every `BaseAgent` subclass implements a `fallback()` method that uses regex patterns, the `utils/skills.py` vocabulary (200+ skills), and set operations to produce a usable answer. The `source` field (`"llm"` or `"fallback"`) is always returned so the caller knows which mode ran.

---

### Likely interview questions with model answers

**"Walk me through the architecture."**
> "It's a standard client-server setup. Next.js on port 3000 talks to FastAPI on port 8000. The backend has four main subsystems: an auth layer using SQLite and PBKDF2 passwords, a RAG layer using ChromaDB and sentence-transformers to embed and search the user's resume, an 8-step LangGraph pipeline that scores a job advert against that resume, and a job discovery engine that fetches from Adzuna, Hacker News, Remotive, and 17 Indian company ATS boards. All state is local — two SQLite files and a local vector store."

**"How does the resume matching work?"**
> "The job advert is analyzed to extract required skills, preferred skills, and tech stack. The resume is searched semantically — not by keyword — using the vector embeddings, so 'built REST microservices' matches 'FastAPI' without exact wording. The match calculator scores five dimensions independently: skills, tech stack, years of experience, education, and soft skills. Each has a weight; the weighted average becomes the 0–100 score. A score of 80+ is APPLY, 60–79 is MAYBE, below 60 is SKIP."

**"How is auth handled?"**
> "Passwords are hashed with PBKDF2-HMAC-SHA256 at 600 000 iterations with a per-user 16-byte salt — never stored in readable form. On login, a 256-bit random token is generated, its SHA-256 hash is stored in the sessions table with a 2-week expiry, and the raw token goes into an httpOnly cookie. Every protected endpoint calls `get_current_user` which hashes the cookie value and queries the sessions table. Logout deletes the row — instant revocation with no JWT revocation list."

**"Why does the app work without an API key?"**
> "Every agent has two paths: an LLM path and a deterministic fallback. The fallback uses the `utils/skills.py` vocabulary (200+ skill terms), regex patterns, and set operations. For example, if no LLM is available, the gap detector takes the set difference between `required_skills` (from the job analyzer's regex path) and `skills_found` (from keyword matching in the resume). The result is less nuanced than an LLM answer, but it is never empty or wrong."

**"How do you prevent SQL injection?"**
> "Every query in `job_storage.py`, `application_tracker.py`, and `auth.py` uses parameterised statements — `cursor.execute('SELECT … WHERE user_id = ?', (user_id,))`. There is no string interpolation of user data into SQL anywhere in the project. The `status` filter additionally validates against a fixed tuple (`STATUSES`) before it reaches any query."

**"How does the job scraper avoid being blocked or violating ToS?"**
> "Four things. One: only sources that provide a documented API or RSS feed are used — no HTML scraping. LinkedIn is explicitly refused because they have no public feed and prohibit automated collection. Two: robots.txt is fetched and obeyed for every host, with the result cached. Three: a per-host rate limiter enforces at least 1 second between requests. Four: discovered responses are cached for 6 hours so Remotive's 'max 4 times a day' request is honoured in code."

**"How would you handle a slow LLM response?"**
> "Each LLM call in `agents/ollama_handler.py` has a configurable timeout (`LLM_TIMEOUT_SECONDS`, default 120 s). If it exceeds that, it throws `LLMUnavailableError`, which `BaseAgent.run()` catches and routes to the fallback. The frontend sets a 120 s Axios timeout too, because a full analysis runs 6+ LLM calls. The execution trace shows how long each node actually took."

**"What's the caching strategy?"**
> "One custom in-process cache in `utils/cache.py`. It uses SHA-256 of the canonically serialised arguments as the key — not Python's `hash()`, which is process-randomised since 3.3 and unstable. It has a configurable size cap (256 entries by default) to prevent memory exhaustion from adversarial inputs, a TTL, and a threading lock. Job analysis results are cached for 7 200 seconds. Resume search results are not cached because they are personalised per user."

---

### Challenges inferred from the code (and how they are solved)

| Challenge | Where it shows up | Solution |
|---|---|---|
| LLM is optional but results must always complete | Every agent file | `BaseAgent.fallback()` abstract method; `source` field in every response |
| LangGraph `execution_trace` being overwritten by each node | `workflow_state.py` | `Annotated[List, _append]` custom reducer |
| ChromaDB `np.float_` removed in NumPy 2.0 | `requirements.txt` comment | Pinned `numpy==1.26.4` |
| macOS LibreSSL missing `hashlib.scrypt` | `utils/auth.py` comment | Fell back to PBKDF2 |
| Job board HTML scraping is brittle and against ToS | `job_scraper.py` header | Only APIs and RSS feeds; LinkedIn explicitly refused |
| `hash()` is process-randomised; can't use as cache key | `utils/cache.py` comment | SHA-256 of canonical JSON |
| Falsy cache results (empty list, 0) treated as misses | `utils/cache.py` | Sentinel object for "no entry" vs "entry is falsy" |
| Two tabs disagreeing on "currently selected job" | `lib/interview-handoff.ts` | sessionStorage bridge; job pasted into prep page, not stored server-side |
| Uvicorn reload on Windows requires `__main__` guard | `main.py` line 1903 | `if __name__ == "__main__":` |

---

### Scalability and security considerations

**What is handled:**
- SSRF: URL allowlist + DNS private-IP rejection in `job_scraper.py`
- SQL injection: 100% parameterised queries
- Password security: PBKDF2 + per-user salt + 600 000 iterations
- Session security: opaque token, only hash stored, httpOnly cookie
- Memory exhaustion from cache: size-capped LRU
- Memory exhaustion from responses: 2 MB response cap
- XML entity expansion (billion laughs): DTD rejection in XML parser
- File upload: extension + size check client-side and server-side

**What is NOT handled (technical debt / known gaps):**
- No rate limiting on auth endpoints (brute-force login possible)
- No CSRF token (mitigated by `httpOnly` cookie + `SameSite` but not hardened)
- Single-machine only — ChromaDB and SQLite don't scale horizontally
- No email verification on signup
- No password reset flow
- ChromaDB user isolation is by `user_id` filter, not by separate collection — a bug in the query could theoretically return another user's chunks
- `CLAUDE_MODEL` in `.env` is never reached (Anthropic SDK is commented out of requirements.txt)
- The `interviews` table is created but never written to from the API layer

---

### Elevator pitch (60 seconds)

> "CareerPilot AI is a local-first career tool for developers. You upload your CV once, and then for any job advert you paste in, it runs an 8-step AI pipeline: it reads the advert to extract what the role requires, searches your CV semantically to find what you already have, calculates a match score across five dimensions, identifies the skill gaps with how long each would take to learn, rewrites your CV bullet points for that specific role, and generates a full set of tailored interview questions. It also searches live job boards — filtered to the last 7 days and focused on the Indian market — and matches them against your resume automatically. Everything runs on your own laptop. Nothing is ever sent to a third party, and every AI answer is labelled with how it was produced so you always know what you're looking at."

---

### 5-minute technical walkthrough

**Minute 1 — The problem and the approach**
> "The problem is that most CV tools either score you against a job in a black box, or they show you jobs without telling you whether you're actually competitive for them. CareerPilot does both, and shows the reasoning. The approach is a local RAG system — the CV is embedded into a vector store so it can be searched semantically — combined with an 8-step LangGraph pipeline that processes both the CV and the advert together."

**Minute 2 — The stack and why**
> "FastAPI backend because of native async, Pydantic validation, and auto-generated OpenAPI docs. Next.js frontend with the App Router because server components and route groups make the auth guard a single declaration. SQLite because the data is relational and single-machine — no server overhead. ChromaDB for the vector store because it's in-process and keeps the 'nothing leaves your machine' promise. The LLM is configurable: Gemini, Claude, or Ollama. Every agent has a deterministic fallback so the pipeline always completes."

**Minute 3 — The core pipeline**
> "The full analysis is 8 nodes in a LangGraph graph. Node 1 extracts job requirements. Node 2 extracts resume skills from the vector store. Node 3 calculates match across five dimensions — skills, tech stack, experience, education, soft skills. Node 4 detects gaps and estimates learning time. Node 5 rewrites CV bullets for the specific role. Node 6 generates interview questions. Nodes 7 and 8 are pure logic: is there time to learn the gaps, and what's the recommendation. Each node appends to an execution trace, so you can see exactly how the result was reached and how long each step took."

**Minute 4 — Auth and security**
> "Auth is username and password, with PBKDF2-HMAC-SHA256 hashing (600 000 iterations, per-user random salt). Sessions are opaque 256-bit tokens stored as their SHA-256 hash — the raw token lives only in an httpOnly cookie, never in the database. Logout deletes the row. The job scraper enforces an URL allowlist, DNS rejection of private IP ranges to prevent SSRF, robots.txt compliance, per-host rate limiting, and a 2 MB response cap. Every SQL query is parameterised."

**Minute 5 — What I'd do differently**
> "The biggest gap is that ChromaDB user isolation is by query filter rather than separate collections — a bug could leak chunks between users. At scale I'd give each user their own collection, or move to pgvector where row-level security is a first-class feature. I'd also add rate limiting on the auth endpoints, email verification, and a proper password reset flow. The `interviews` table schema is there but the API layer never writes to it — that's the next feature. And the Gemini free tier hits 429s under load; the retry logic handles it gracefully, but a paid key or a model-agnostic load balancer would be cleaner."

---

## 10. Possible Improvements

| Area | Current state | What would be better |
|---|---|---|
| **Vector store isolation** | User chunks filtered by `user_id` at query time | Separate ChromaDB collection per user; row-level security |
| **Auth hardening** | No rate limiting on `/api/auth/login` | Exponential backoff after N failed attempts; account lockout |
| **CSRF** | Mitigated by `httpOnly` + `SameSite` cookie | Explicit CSRF token on state-mutating routes |
| **Email verification** | Signup accepts any email without verification | Send a confirmation link; mark account as `verified` |
| **Password reset** | Not implemented (documented honestly in Settings) | Time-limited reset tokens via email |
| **Interviews table** | Schema exists, never written to | Wire `POST /api/career/application/{id}/add-interview` |
| **Claude support** | `ANTHROPIC_API_KEY` in `.env` but SDK commented out of `requirements.txt` | Uncomment `anthropic==0.34.2` and test the fallback chain |
| **Multi-user scaling** | SQLite + single process | PostgreSQL + pgvector for cloud deployment; connection pool |
| **Resume replacement** | Upload adds to existing index; user must manually clear first | Per-document versioning; upload replaces the previous document |
| **Job result persistence** | Discovered jobs live in-memory on the server; restart loses them | Store in `jobs.db` with a TTL; current saved jobs already do this |
| **Frontend testing** | 11 tests covering health + API error handling only | Component tests with React Testing Library; E2E with Playwright |
| **`.docx` support** | `python-docx` listed in `rag/resume_indexer.py` but `SUPPORTED_EXTENSIONS` only lists `.pdf`, `.txt`, `.md` | Verify `.docx` extraction path is exercised and covered by a test |
| **Gemini rate limits** | 429s handled by retry + fallback | Paid API key or per-minute token budgeting |
| **No deployment config** | Local only; no Docker, no CI | `Dockerfile` + `docker-compose.yml`; GitHub Actions for tests |
