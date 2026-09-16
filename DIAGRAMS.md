# CareerPilot AI — System Diagrams

> All diagrams in one place. Plain text so they work in any editor, GitHub, or Notepad.
> Read top-to-bottom: each diagram zooms in a little more than the last.

---

## Table of Contents

1. [System Architecture Diagram](#1-system-architecture-diagram)
2. [User Flow Diagram](#2-user-flow-diagram)
3. [Data Flow Diagram (DFD)](#3-data-flow-diagram-dfd)
4. [Entity-Relationship (ER) Diagram](#4-entity-relationship-er-diagram)
5. [AI Pipeline Flow Diagram](#5-ai-pipeline-flow-diagram)
6. [Authentication Flow Diagram](#6-authentication-flow-diagram)
7. [Resume Upload & RAG Indexing Flow](#7-resume-upload--rag-indexing-flow)
8. [Job Discovery Flow Diagram](#8-job-discovery-flow-diagram)
9. [Application Tracker State Diagram](#9-application-tracker-state-diagram)
10. [Component Hierarchy Diagram](#10-component-hierarchy-diagram)
11. [Database Schema Diagram](#11-database-schema-diagram)
12. [LLM Fallback Decision Diagram](#12-llm-fallback-decision-diagram)
13. [Deployment / Process Diagram](#13-deployment--process-diagram)

---

## 1. System Architecture Diagram

> **What it shows:** The big picture — all the pieces of the app and how they connect.

```
╔══════════════════════════════════════════════════════════════════╗
║                        USER'S BROWSER                           ║
║                                                                  ║
║   ┌────────────────────────────────────────────────────────┐    ║
║   │               NEXT.JS FRONTEND  (port 3000)            │    ║
║   │                                                         │    ║
║   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │    ║
║   │  │  Login / │ │ Discover │ │ Analyze  │ │Interview │  │    ║
║   │  │  Sign Up │ │  Jobs    │ │   Job    │ │   Prep   │  │    ║
║   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │    ║
║   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │    ║
║   │  │  My      │ │   My     │ │    AI    │ │Settings  │  │    ║
║   │  │  Resume  │ │   Jobs   │ │Assistant │ │          │  │    ║
║   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │    ║
║   └─────────────────────┬──────────────────────────────────┘    ║
╚═════════════════════════│════════════════════════════════════════╝
                          │
             HTTP + httpOnly Cookie Session
                          │
╔═════════════════════════▼════════════════════════════════════════╗
║                   FASTAPI BACKEND  (port 8000)                  ║
║                                                                  ║
║   ┌────────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────┐  ║
║   │    AUTH    │ │  RAG LAYER   │ │AI PIPELINE │ │   JOB    │  ║
║   │   LAYER    │ │              │ │(LangGraph) │ │DISCOVERY │  ║
║   │            │ │ sentence-    │ │            │ │          │  ║
║   │ PBKDF2     │ │ transformers │ │ 8-step     │ │ 6 live   │  ║
║   │ passwords  │ │ embed CV     │ │ workflow   │ │ sources  │  ║
║   │ opaque     │ │ ChromaDB     │ │            │ │          │  ║
║   │ tokens     │ │ search       │ │            │ │          │  ║
║   └─────┬──────┘ └──────┬───────┘ └─────┬──────┘ └────┬─────┘  ║
╚═════════│═══════════════│═══════════════│═════════════│═════════╝
          │               │               │             │
          ▼               ▼               ▼             ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ SQLite   │   │ ChromaDB │   │  LLM     │   │ Internet │
    │ users.db │   │ vectors  │   │ (Gemini/ │   │ APIs     │
    │ sessions │   │ (resume  │   │  Claude/ │   │ (Adzuna, │
    │          │   │  chunks) │   │  Ollama) │   │  HN, etc)│
    └──────────┘   └──────────┘   └──────────┘   └──────────┘
    ┌──────────┐
    │ SQLite   │
    │ jobs.db  │
    │ apps.db  │
    └──────────┘
```

**In simple words:**
- Your browser runs the pretty frontend (Next.js)
- The frontend talks to the backend (FastAPI) using HTTP
- The backend has 4 main jobs: manage logins, search your CV, run AI, find jobs
- Everything is stored locally — 2 SQLite files + 1 vector database

---

## 2. User Flow Diagram

> **What it shows:** Step-by-step journey of a brand-new user opening the app.

```
                      ┌─────────────────┐
                      │  Open browser   │
                      │ localhost:3000  │
                      └────────┬────────┘
                               │
                               ▼
                      ┌─────────────────┐
                      │  Logged in?     │
                      └────┬──────┬─────┘
                     YES   │      │  NO
                           │      ▼
                           │  ┌─────────────────┐
                           │  │  Sign Up / Login │
                           │  │  page           │
                           │  └────────┬────────┘
                           │           │ Submit form
                           │           ▼
                           │  ┌─────────────────┐
                           │  │ Account created  │
                           │  │ Session cookie   │
                           │  │ set (2 weeks)   │
                           │  └────────┬────────┘
                           │           │
                           └───────────▼
                      ┌─────────────────────────┐
                      │      HOME PAGE           │
                      │  Resume uploaded? ───NO──►  Upload CV  ──►  CV indexed
                      │       │ YES                 (PDF/DOCX)       in ChromaDB
                      └───────┼─────────────────┘
                              │
              ┌───────────────┼───────────────────┐
              │               │                   │
              ▼               ▼                   ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ Discover     │  │ Analyze a    │  │  Interview   │
    │ Jobs         │  │ Job Advert   │  │  Prep        │
    │              │  │              │  │              │
    │ Search live  │  │ Paste JD     │  │ Get 6 sets   │
    │ feeds →      │  │ → 8-step AI  │  │ of questions │
    │ see matches  │  │ → score+tips │  │ tailored to  │
    │              │  │              │  │ your CV      │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           │                 │                  │
           ▼                 ▼                  ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ Save Job     │  │ Save Job +   │  │ Practice     │
    │ to My Jobs   │  │ Create       │  │ answers →    │
    │              │  │ Application  │  │ get scored   │
    └──────────────┘  └──────────────┘  └──────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ My Applications  │
                    │ Track status:    │
                    │ draft → sent →   │
                    │ interview →      │
                    │ offer/rejected   │
                    └──────────────────┘
```

---

## 3. Data Flow Diagram (DFD)

> **What it shows:** Where data comes from, where it goes, what transforms it.
> DFD Level 0 = overview; Level 1 = detailed.

### Level 0 — The whole system in one box

```
                ┌─────────────────────────────────┐
   CV File ────►│                                 │──► Match Score
   Job Advert ─►│        CareerPilot AI           │──► Skill Gaps
   User Input ─►│                                 │──► Interview Qs
   API Key ────►│                                 │──► Job Listings
                └─────────────────────────────────┘
```

### Level 1 — Inside the system

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  USER                                                            │
  │                                                                  │
  │  [CV File] ──────────────────────────────────────────────────┐  │
  │  [Password] ──────────────────────────────────────────────┐  │  │
  │  [Job Advert text] ───────────────────────────────────┐  │  │  │
  │  [Job search query] ──────────────────────────────┐  │  │  │  │
  └──────────────────────────────────────────────────│──│──│──│──┘
                                                     │  │  │  │
                        ┌────────────────────────────▼──▼  │  │
                        │   1. AUTH PROCESS                 │  │
                        │   - Hash password (PBKDF2)        │  │
                        │   - Create session token          │  │
                        │   - Store SHA-256(token)          │  │
                        └──────────────┬────────────────────│──┘
                                       │                    │
                        ┌──────────────▼────────────────────▼──┐
                        │   2. RESUME INDEXER                   │
                        │   - Parse PDF/DOCX to text            │
                        │   - Chunk into 250-token windows      │
                        │   - Embed with all-MiniLM-L6-v2      │
                        │   - Store 384-dim vectors             │
                        └──────────────┬────────────────────────┘
                                       │ embeddings
                                       ▼
                              ┌─────────────────┐
                              │   ChromaDB      │
                              │   (vector store)│
                              └────────┬────────┘
                                       │ semantic search results
                        ┌──────────────▼────────────────────────┐
                        │   3. AI PIPELINE (8 steps)            │
                        │   - Analyze job advert                │
                        │   - Extract resume skills (via RAG)   │
                        │   - Calculate match score             │
                        │   - Detect skill gaps                 │
                        │   - Optimize resume bullets           │
                        │   - Generate interview questions      │
                        │   - Final recommendation              │
                        └──────────────┬────────────────────────┘
                                       │ LLM calls
                                       ▼
                              ┌─────────────────┐
                              │  Gemini / Claude │
                              │  / Ollama / or   │
                              │  fallback rules  │
                              └────────┬────────┘
                                       │ structured JSON answers
                        ┌──────────────▼────────────────────────┐
                        │   4. JOB DISCOVERY                    │
                        │   - Rate-limited requests to APIs     │
                        │   - robots.txt check                  │
                        │   - Filter to last 7 days             │
                        │   - Score each job vs your CV         │
                        └──────────────┬────────────────────────┘
                                       │
                        ┌──────────────▼────────────────────────┐
                        │   5. STORAGE                          │
                        │   - Save jobs, applications to SQLite │
                        │   - Record every status change        │
                        └──────────────┬────────────────────────┘
                                       │ query results
                                       ▼
                              ┌─────────────────┐
                              │   RESPONSE TO   │
                              │   BROWSER       │
                              │   (JSON)        │
                              └─────────────────┘
```

---

## 4. Entity-Relationship (ER) Diagram

> **What it shows:** All database tables, their columns, and how they link to each other.

```
╔══════════════════════════════╗         ╔══════════════════════════════╗
║            USERS             ║         ║           SESSIONS           ║
╠══════════════════════════════╣         ╠══════════════════════════════╣
║ PK  user_id     TEXT         ║◄────────║ PK  token_hash  TEXT         ║
║     email       TEXT UNIQUE  ║  1       ║ FK  user_id     TEXT         ║
║     name        TEXT         ║  to      ║     created_date TEXT        ║
║     password_hash BLOB       ║  many   ║     expires_date TEXT        ║
║     salt        BLOB         ║         ╚══════════════════════════════╝
║     iterations  INTEGER      ║
║     created_date TEXT        ║         ╔══════════════════════════════╗
║     last_login  TEXT         ║         ║            JOBS              ║
╚══════════════════════════════╝         ╠══════════════════════════════╣
                                         ║ PK  job_id      TEXT         ║
           (separate database)           ║     user_id     TEXT         ║
                                         ║     title       TEXT         ║
╔══════════════════════════════╗         ║     company     TEXT         ║
║         APPLICATIONS         ║         ║     description TEXT         ║
╠══════════════════════════════╣         ║     requirements TEXT (JSON) ║
║ PK  app_id      TEXT         ║         ║     analysis    TEXT (JSON)  ║
║     user_id     TEXT         ║         ║     source      TEXT         ║
║     job_id      TEXT ─────────────────►║     url         TEXT         ║
║     job_title   TEXT         ║         ║     posted_date TEXT         ║
║     company     TEXT         ║   1     ║     saved_date  TEXT         ║
║     match_score REAL         ║   to    ║     status      TEXT         ║
║     gaps_identified TEXT     ║   many  ║     match_score REAL         ║
║     status      TEXT         ║◄────────║     notes       TEXT         ║
║     created_date TEXT        ║         ╚══════════════════════════════╝
║     updated_date TEXT        ║
║     notes       TEXT         ║
╚══════════════════════════════╝
          │ 1
          │ to
          │ many
          │
          ├─────────────────────────────────────────────────────────────┐
          │                                                             │
          ▼                                                             ▼
╔══════════════════════════════╗         ╔══════════════════════════════╗
║     APPLICATION_EVENTS       ║         ║          INTERVIEWS          ║
╠══════════════════════════════╣         ╠══════════════════════════════╣
║ PK  event_id    INTEGER      ║         ║ PK  interview_id INTEGER     ║
║ FK  application_id TEXT      ║         ║ FK  application_id TEXT      ║
║     event_type  TEXT         ║         ║     interview_date TEXT      ║
║     details     TEXT (JSON)  ║         ║     interviewer    TEXT      ║
║     status_after TEXT        ║         ║     performance_rating TEXT  ║
║     created_date TEXT        ║         ║     notes         TEXT       ║
╚══════════════════════════════╝         ║     next_round    INTEGER    ║
                                         ╚══════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║                    CHROMADB  (Vector Store)                         ║
║                    Not a SQL table — a collection of embeddings     ║
╠══════════════════════════════════════════════════════════════════════╣
║  id          "{user_id}_{doc_id}_{chunk_index}"                     ║
║  embedding   float[384]   ← all-MiniLM-L6-v2 output                ║
║  document    "chunk of resume text"                                 ║
║  metadata:   user_id, section (skills/experience/etc),             ║
║              source (pdf/txt), file_name, created_at               ║
╚══════════════════════════════════════════════════════════════════════╝

  Database files:
  ├── data/users.db  ──  USERS + SESSIONS tables
  ├── data/jobs.db   ──  JOBS + APPLICATIONS + APPLICATION_EVENTS + INTERVIEWS
  └── data/chroma/   ──  CHROMADB vector collection
```

**Relationships in plain words:**
- One **user** has many **sessions** (you can be logged in from multiple devices)
- One **user** has many **jobs** (each job is saved per-user)
- One **user** has many **applications**
- One **application** has many **events** (a timeline of every status change)
- One **application** has many **interviews** (each round is a separate row)

---

## 5. AI Pipeline Flow Diagram

> **What it shows:** The 8-step AI analysis that runs when you paste a job advert.

```
              USER pastes job advert + clicks "Analyze"
                              │
                              ▼
              ╔═══════════════════════════════╗
              ║  POST /api/career/full-analysis║
              ╚═══════════════╤═══════════════╝
                              │
         ┌────────────────────▼────────────────────┐
         │            STEP 1: ANALYZE JOB           │
         │                                          │
         │  Input:  raw job advert text             │
         │  Action: extract structured info         │
         │  Output: required_skills, tech_stack,    │
         │          experience_years, role_type     │
         │  Mode:   LLM  OR  regex+keyword fallback │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │         STEP 2: EXTRACT RESUME           │
         │                                          │
         │  Input:  user_id (to find their CV)      │
         │  Action: semantic search in ChromaDB     │
         │          (top 24 chunks retrieved)       │
         │  Output: skills_found, years_experience, │
         │          current_role, education_level   │
         │  Mode:   RAG (no LLM needed here)        │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │         STEP 3: CALCULATE MATCH          │
         │                                          │
         │  Input:  required_skills + skills_found  │
         │  Action: score 5 dimensions:             │
         │          • Skills match      (weighted)  │
         │          • Tech stack match  (weighted)  │
         │          • Experience years  (weighted)  │
         │          • Education level   (weighted)  │
         │          • Soft skills       (weighted)  │
         │  Output: overall_score 0-100, breakdown  │
         │  Mode:   pure math, NO LLM               │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │          STEP 4: DETECT GAPS             │
         │                                          │
         │  Input:  required_skills - skills_found  │
         │  Action: identify missing skills         │
         │          estimate learning time per gap  │
         │  Output: critical_gaps[], nice_to_have[],│
         │          total_learning_weeks            │
         │  Mode:   LLM  OR  set-difference fallback│
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │        STEP 5: OPTIMIZE RESUME           │
         │                                          │
         │  Input:  CV text + job requirements      │
         │  Action: rewrite CV bullet points        │
         │          to match this specific role     │
         │  Output: improved bullets[], keywords    │
         │          to add, tailored_summary        │
         │  Mode:   LLM  OR  rule-based fallback    │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │       STEP 6: PREPARE INTERVIEW          │
         │                                          │
         │  Input:  job requirements + CV skills    │
         │  Action: generate 6 question categories: │
         │          technical / project-specific /  │
         │          behavioural / situational /     │
         │          HR / company research           │
         │  Mode:   LLM  OR  template fallback      │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │      STEP 7: CHECK GAPS LEARNABLE        │
         │                                          │
         │  Logic: total_learning_days ≤ 14?        │
         │  Pure Python — no LLM needed             │
         └────────────────────┬────────────────────┘
                              │
         ┌────────────────────▼────────────────────┐
         │     STEP 8: FINAL RECOMMENDATION         │
         │                                          │
         │  score ≥ 80  → ✅ APPLY                  │
         │  score 60-79 → 🟡 MAYBE                  │
         │  score < 60  → ❌ SKIP                   │
         │  + plain English explanation             │
         │  Pure Python — no LLM needed             │
         └────────────────────┬────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │   RESPONSE to browser:       │
              │   • Score (0-100)            │
              │   • Recommendation           │
              │   • Match breakdown          │
              │   • Skill gaps + learn time  │
              │   • Improved CV bullets      │
              │   • Interview questions      │
              │   • Execution trace          │
              │   (every step timed + logged)│
              └──────────────────────────────┘

  If ANY step fails → it is marked "error" and pipeline CONTINUES
  with safe defaults. You always get a result — never a crash.
```

---

## 6. Authentication Flow Diagram

> **What it shows:** How login, sessions, and logout work under the hood.

```
  ─────────────── SIGN UP ────────────────────────────────────────────

  User enters email + password
          │
          ▼
  Frontend validation (min 8 chars, valid email)
          │
          ▼
  POST /api/auth/signup
          │
          ▼
  ┌───────────────────────────────────────────┐
  │  Backend: UserStore.create_user()         │
  │                                           │
  │  1. Generate 16-byte random SALT          │
  │  2. Hash:  PBKDF2-HMAC-SHA256             │
  │             (password + salt,             │
  │              600,000 iterations)          │
  │  3. Store in users.db:                    │
  │     user_id, email, hash, salt            │
  │  4. Password never stored — only the hash │
  └───────────────────────────────────────────┘
          │
          ▼
  Account created → user sees dashboard

  ─────────────── LOGIN ──────────────────────────────────────────────

  User enters email + password
          │
          ▼
  POST /api/auth/login
          │
          ▼
  ┌───────────────────────────────────────────┐
  │  Backend: UserStore.verify_password()     │
  │                                           │
  │  1. Look up user by email                 │
  │  2. Re-hash password with stored salt     │
  │  3. Compare with hmac.compare_digest()    │
  │     (constant-time — no timing attacks)   │
  │                                           │
  │  If match:                                │
  │  4. Generate 256-bit random TOKEN         │
  │  5. Store SHA-256(token) in sessions.db   │
  │     with expiry = now + 336 hours (2 wks) │
  │  6. Set httpOnly cookie: session=TOKEN    │
  │     (browser stores it, JS can't read it) │
  └───────────────────────────────────────────┘
          │
          ▼
  Cookie sent to browser → user logged in

  ─────────────── EVERY PROTECTED REQUEST ────────────────────────────

  Browser sends request (cookie attached automatically)
          │
          ▼
  ┌───────────────────────────────────────────┐
  │  Backend: get_current_user() [Depends]    │
  │                                           │
  │  1. Read cookie value (raw token)         │
  │  2. Compute SHA-256(raw token)            │
  │  3. Look up SHA-256 in sessions table     │
  │  4. Check expires_date > now              │
  │  5. Return user_id                        │
  │     OR raise 401 Unauthorized             │
  └───────────────────────────────────────────┘

  ─────────────── LOGOUT ─────────────────────────────────────────────

  User clicks Sign Out
          │
          ▼
  POST /api/auth/logout
          │
          ▼
  DELETE session row from sessions.db
          │
          ▼
  Token stops working INSTANTLY
  (No JWT revocation list needed)
```

---

## 7. Resume Upload & RAG Indexing Flow

> **What it shows:** How your CV gets processed and stored so the AI can search it.

```
  User selects a PDF / DOCX / TXT file
          │
          ▼
  POST /api/career/upload-resume  (multipart/form-data)
          │
          ▼
  ┌─────────────────────────────────────────────────────────┐
  │  STEP A: FILE VALIDATION                                │
  │                                                         │
  │  • Extension must be .pdf / .docx / .txt / .md          │
  │  • File size must be ≤ 10 MB                            │
  │  • Saved to: data/uploads/{uuid}.{ext}                  │
  └───────────────────────────┬─────────────────────────────┘
                              │
          ┌────────────────────▼──────────────────────┐
          │  STEP B: TEXT EXTRACTION                   │
          │                                            │
          │  .pdf  → PyPDF2 reads each page            │
          │  .docx → python-docx reads paragraphs      │
          │  .txt  → plain read()                      │
          │  .md   → plain read()                      │
          │                                            │
          │  Output: one long string of plain text     │
          └────────────────────┬──────────────────────┘
                               │
          ┌────────────────────▼──────────────────────┐
          │  STEP C: CHUNKING                          │
          │                                            │
          │  Sliding window:                           │
          │  • Chunk size:    250 tokens               │
          │  • Overlap:        50 tokens               │
          │                                            │
          │  "Skills: Python, Django, REST..."         │
          │  → chunk 1: tokens 0-249                   │
          │  → chunk 2: tokens 200-449  (50 overlap)   │
          │  → chunk 3: tokens 400-649  ...            │
          │                                            │
          │  Each chunk gets a SECTION tag:            │
          │  contact / skills / experience /           │
          │  education / projects / other              │
          └────────────────────┬──────────────────────┘
                               │
          ┌────────────────────▼──────────────────────┐
          │  STEP D: EMBEDDING                         │
          │                                            │
          │  Model: all-MiniLM-L6-v2                   │
          │  (runs locally, ~80MB, one-time download)  │
          │                                            │
          │  "Python Django REST" → [0.12, -0.34, ...] │
          │   one chunk → 384 floating-point numbers   │
          └────────────────────┬──────────────────────┘
                               │
          ┌────────────────────▼──────────────────────┐
          │  STEP E: STORE IN CHROMADB                 │
          │                                            │
          │  Each chunk stored as:                     │
          │  • id:        user_abc_doc123_chunk_0      │
          │  • vector:    float[384]                   │
          │  • text:      original chunk text          │
          │  • metadata:  user_id, section, filename   │
          │                                            │
          │  Old chunks for this user are DELETED      │
          │  before new ones are added (clean replace) │
          └────────────────────┬──────────────────────┘
                               │
                               ▼
          ┌────────────────────────────────────────────┐
          │  STEP F: SEMANTIC SEARCH (at analysis time) │
          │                                             │
          │  Query: "5 years Python experience"         │
          │                                             │
          │  1. Embed query → float[384]                │
          │  2. Find top-5 nearest vectors in ChromaDB │
          │     (cosine distance)                       │
          │  3. Return matching CV text chunks          │
          │                                             │
          │  "Python 5yr" MATCHES "built APIs in       │
          │  Python for 4 years" — semantic, not exact  │
          └────────────────────────────────────────────┘
```

---

## 8. Job Discovery Flow Diagram

> **What it shows:** How the app finds live jobs and scores them against your CV.

```
  User enters: "backend engineer" + location "india" + max 7 days
          │
          ▼
  POST /api/career/discover-jobs
          │
          ▼
  ┌──────────────────────────────────────────────────────┐
  │  auto_from_resume = true?                            │
  │  → YES: ask ResumeProfilerAgent                      │
  │         "what job titles match this CV?"             │
  │         and use those as search terms                │
  └──────────────────────────────────────────────────────┘
          │
          ▼ (parallel — all at same time)
  ┌──────────────────────────────────────────────────────┐
  │  FETCH FROM 6 SOURCES                                │
  │                                                      │
  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
  │  │  Adzuna API  │  │ HackerNews   │  │ Remotive  │  │
  │  │ (India only) │  │ "Who's Hiring│  │   API     │  │
  │  │  licensed    │  │  " thread    │  │           │  │
  │  └──────────────┘  └──────────────┘  └───────────┘  │
  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
  │  │  Arbeitnow   │  │WeWorkRemotely│  │  Indian   │  │
  │  │     API      │  │   RSS feed   │  │  Company  │  │
  │  │              │  │              │  │  ATS Boards│ │
  │  └──────────────┘  └──────────────┘  └───────────┘  │
  │                                                      │
  │  Indian company ATS boards:                          │
  │  Paytm, Meesho, CRED, Groww, Postman, Druva,        │
  │  Epifi, Sigmoid, Zenoti, Netradyne, Airbnb + more   │
  └──────────────────────────────────────────────────────┘
          │
          ▼
  ┌──────────────────────────────────────────────────────┐
  │  SAFETY CHECKS (for each URL before fetching)        │
  │                                                      │
  │  ✓ Is host in ALLOWED_HOSTS list?                    │
  │  ✓ Does robots.txt allow us?                         │
  │  ✓ Does DNS resolve to a public IP?                  │
  │    (rejects 192.168.x.x, 10.x.x.x, etc.)            │
  │  ✓ Response ≤ 2 MB?                                  │
  │  ✓ Minimum 1 second between requests to same host   │
  └──────────────────────────────────────────────────────┘
          │
          ▼
  ┌──────────────────────────────────────────────────────┐
  │  FILTER                                              │
  │                                                      │
  │  Remove jobs older than 7 days                       │
  │  Remove duplicates (same URL = same job)             │
  └──────────────────────────────────────────────────────┘
          │
          ▼
  ┌──────────────────────────────────────────────────────┐
  │  SCORE EACH JOB vs YOUR CV (parallel, 10 workers)   │
  │                                                      │
  │  JobEnricher runs JobAnalyzerAgent on each job       │
  │  → match_score 0-100 per job                        │
  └──────────────────────────────────────────────────────┘
          │
          ▼
  ┌──────────────────────────────────────────────────────┐
  │  SORT INTO BUCKETS                                   │
  │                                                      │
  │  🟢 perfect_match    score ≥ 80                      │
  │  🔵 good_fit         score 60-79                     │
  │  🟡 stretch_goal     score 40-59                     │
  │  🔴 learning_needed  score < 40                      │
  │  ⚪ unscored         (could not be analyzed)         │
  └──────────────────────────────────────────────────────┘
          │
          ▼
  Response: job listings with scores, source badges, apply links
```

---

## 9. Application Tracker State Diagram

> **What it shows:** The lifecycle of one job application from start to finish.

```
                    ┌──────────────┐
                    │    CREATE    │
                    │ application  │
                    └──────┬───────┘
                           │
                           ▼
           ┌───────────────────────────────┐
           │           DRAFT               │
           │  You have saved the job but   │
           │  haven't submitted yet.        │
           └───────────────┬───────────────┘
                           │  You apply
                           ▼
           ┌───────────────────────────────┐
           │            SENT               │
           │  Application submitted.        │
           │  Waiting for a response.       │
           └───────────────┬───────────────┘
                           │  They respond
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
  ┌───────────────────────┐  ┌───────────────────────┐
  │       INTERVIEW       │  │       REJECTED         │
  │  You got a call /     │  │  No further action     │
  │  technical round.     │  │  needed.               │
  └───────────┬───────────┘  └───────────────────────┘
              │
              ├────────────────────────────────────┐
              │                                    │
              ▼                                    ▼
  ┌───────────────────────┐           ┌───────────────────────┐
  │         OFFER         │           │       REJECTED         │
  │  You got an offer!    │           │  After interview.      │
  └───────────────────────┘           └───────────────────────┘

  Every arrow above records an EVENT row in application_events:
  { event_type: "status_changed", from: "sent", to: "interview",
    timestamp: "2026-09-16T12:00:00Z" }

  This gives you a full timeline of every application on the
  "My Applications" detail page.
```

---

## 10. Component Hierarchy Diagram

> **What it shows:** How the frontend pages and components are structured.

```
  app/layout.tsx  (ROOT)
  ├── <ThemeProvider>     ← manages dark/light/system theme
  └── <AuthProvider>      ← holds logged-in user state (React context)
      │
      ├── app/login/page.tsx
      │   └── <AuthForm mode="login">
      │
      ├── app/signup/page.tsx
      │   └── <AuthForm mode="signup">
      │
      └── app/(dashboard)/layout.tsx   ← PROTECTED (RequireAuth guard)
          ├── <Sidebar>                ← navigation links
          ├── <Header>                 ← theme toggle + logout button
          │
          ├── page.tsx  (Home / Upload)
          │   ├── <StatCard>           ← skill count, experience
          │   └── <LoadingSpinner>
          │
          ├── my-resume/page.tsx
          │   └── <AnalysisResults>    ← skill breakdown, strengths
          │
          ├── discover-jobs/page.tsx
          │   ├── <JobCard>            ← one card per job result
          │   │   └── <SourceBadge>    ← "Adzuna" / "HN" / etc.
          │   └── <JobDetailModal>     ← popup with full job info
          │
          ├── analyze/page.tsx
          │   └── <AgentTraceViewer>   ← shows 8 pipeline steps live
          │
          ├── interview-prep/page.tsx
          │   └── <PracticeRoom>       ← one Q at a time + scoring
          │
          ├── assistant/page.tsx       ← chat interface
          │
          ├── my-jobs/page.tsx
          │   └── <JobCard> (saved)
          │
          ├── my-applications/page.tsx
          │   └── <ApplicationTimeline>
          │
          ├── my-applications/[id]/page.tsx
          │   ├── <ApplicationTimeline>
          │   └── status update buttons
          │
          └── settings/page.tsx
              └── <SearchElsewhere>    ← Google/LinkedIn/Indeed links
```

---

## 11. Database Schema Diagram

> **What it shows:** Every column, data type, and constraint in the SQLite databases.

### `data/users.db`

```
 TABLE: users
 ┌─────────────────┬──────────┬──────────────────────────────────────────┐
 │ Column          │ Type     │ Notes                                     │
 ├─────────────────┼──────────┼──────────────────────────────────────────┤
 │ user_id (PK)    │ TEXT     │ "usr_" + 16-char hex, e.g. usr_a1b2c3d4  │
 │ email           │ TEXT     │ UNIQUE (case-insensitive index)           │
 │ name            │ TEXT     │ display name                              │
 │ password_hash   │ BLOB     │ PBKDF2-HMAC-SHA256 output (32 bytes)     │
 │ salt            │ BLOB     │ 16 random bytes, unique per user          │
 │ iterations      │ INTEGER  │ 600,000 (OWASP minimum for PBKDF2)       │
 │ created_date    │ TEXT     │ ISO 8601 UTC e.g. 2026-09-16T12:00:00Z  │
 │ last_login      │ TEXT     │ nullable — updated on each login          │
 └─────────────────┴──────────┴──────────────────────────────────────────┘

 TABLE: sessions
 ┌─────────────────┬──────────┬──────────────────────────────────────────┐
 │ Column          │ Type     │ Notes                                     │
 ├─────────────────┼──────────┼──────────────────────────────────────────┤
 │ token_hash (PK) │ TEXT     │ SHA-256(raw_token) — never the token      │
 │ user_id (FK)    │ TEXT     │ → users.user_id, CASCADE on delete        │
 │ created_date    │ TEXT     │ when the session was created              │
 │ expires_date    │ TEXT     │ created + 336 hours (2 weeks)             │
 └─────────────────┴──────────┴──────────────────────────────────────────┘
```

### `data/jobs.db`

```
 TABLE: jobs
 ┌─────────────────┬──────────┬──────────────────────────────────────────┐
 │ Column          │ Type     │ Notes                                     │
 ├─────────────────┼──────────┼──────────────────────────────────────────┤
 │ job_id (PK)     │ TEXT     │ deterministic hash of URL                │
 │ user_id         │ TEXT     │ owner of this saved job                   │
 │ title           │ TEXT     │                                           │
 │ company         │ TEXT     │                                           │
 │ description     │ TEXT     │ full job text                             │
 │ requirements    │ TEXT     │ JSON {skills:[], experience:…}            │
 │ analysis        │ TEXT     │ JSON full JobAnalysis result              │
 │ source          │ TEXT     │ "Adzuna" / "HackerNews" / "Paytm" etc    │
 │ url             │ TEXT     │ link to original posting                  │
 │ posted_date     │ TEXT     │ when the job was posted                   │
 │ saved_date      │ TEXT     │ when you saved it                         │
 │ status          │ TEXT     │ saved/analyzed/applied/rejected/          │
 │                 │          │ interview/offer                           │
 │ match_score     │ REAL     │ 0-100, null if not yet analyzed           │
 │ notes           │ TEXT     │ your personal notes                       │
 └─────────────────┴──────────┴──────────────────────────────────────────┘

 TABLE: applications
 ┌───────────────────────┬──────────┬────────────────────────────────────┐
 │ Column                │ Type     │ Notes                              │
 ├───────────────────────┼──────────┼────────────────────────────────────┤
 │ app_id (PK)           │ TEXT     │ UUID                               │
 │ user_id               │ TEXT     │                                    │
 │ job_id                │ TEXT     │ → jobs.job_id                      │
 │ job_title             │ TEXT     │ denormalised for quick display     │
 │ company               │ TEXT     │ denormalised                       │
 │ match_score           │ REAL     │ score at time of applying          │
 │ gaps_identified       │ TEXT     │ JSON ["Python", "Kubernetes"]      │
 │ status                │ TEXT     │ draft/sent/interview/rejected/     │
 │                       │          │ offer                              │
 │ created_date          │ TEXT     │                                    │
 │ updated_date          │ TEXT     │                                    │
 │ notes                 │ TEXT     │                                    │
 └───────────────────────┴──────────┴────────────────────────────────────┘

 TABLE: application_events
 ┌───────────────────────┬──────────┬────────────────────────────────────┐
 │ Column                │ Type     │ Notes                              │
 ├───────────────────────┼──────────┼────────────────────────────────────┤
 │ event_id (PK)         │ INTEGER  │ auto-increment                     │
 │ application_id (FK)   │ TEXT     │ → applications.app_id              │
 │ event_type            │ TEXT     │ "status_changed", "note_added"…    │
 │ details               │ TEXT     │ JSON {from:"sent", to:"interview"} │
 │ status_after          │ TEXT     │ what status was set to             │
 │ created_date          │ TEXT     │                                    │
 └───────────────────────┴──────────┴────────────────────────────────────┘

 TABLE: interviews
 ┌───────────────────────┬──────────┬────────────────────────────────────┐
 │ Column                │ Type     │ Notes                              │
 ├───────────────────────┼──────────┼────────────────────────────────────┤
 │ interview_id (PK)     │ INTEGER  │ auto-increment                     │
 │ application_id (FK)   │ TEXT     │ → applications.app_id              │
 │ interview_date        │ TEXT     │                                    │
 │ interviewer           │ TEXT     │ interviewer name / company name    │
 │ performance_rating    │ TEXT     │ "good", "average", "poor"          │
 │ notes                 │ TEXT     │ how it went                        │
 │ next_round            │ INTEGER  │ 1 = yes, 0 = no                    │
 └───────────────────────┴──────────┴────────────────────────────────────┘
```

---

## 12. LLM Fallback Decision Diagram

> **What it shows:** How the app decides whether to use AI or built-in rules.
> This is why the app works even without a Gemini/Ollama API key.

```
               Agent is called (e.g. GapDetectorAgent)
                              │
                              ▼
               ┌──────────────────────────────┐
               │  Is LLM_PROVIDER configured? │
               │  Is API key present?         │
               └──────┬───────────────┬───────┘
                 YES   │               │  NO
                       ▼               ▼
               ┌────────────┐   ┌────────────────────────────┐
               │  Try LLM   │   │  Use FALLBACK immediately  │
               │  (Gemini / │   │  (keyword matching, set    │
               │  Claude /  │   │   difference, templates)   │
               │  Ollama)   │   └─────────────┬──────────────┘
               └─────┬──────┘                 │
                     │                        │
              ┌──────▼──────┐                 │
              │ LLM replies │                 │
              │ in time and │                 │
              │ valid JSON? │                 │
              └──┬──────┬───┘                 │
            YES  │      │  NO (timeout,       │
                 │      │  bad response,      │
                 │      │  or API error)      │
                 │      ▼                     │
                 │  ┌─────────────────────┐   │
                 │  │  Log warning,       │   │
                 │  │  use FALLBACK       │   │
                 │  └──────────┬──────────┘   │
                 │             │              │
                 └──────────┬──┘              │
                            └────────────────►┘
                                             │
                                             ▼
                         ┌───────────────────────────────────┐
                         │  Result returned with:            │
                         │  source: "llm"  or  "fallback"   │
                         │  (always visible in the UI trace) │
                         └───────────────────────────────────┘
```

**Fallback methods per agent:**

| Agent | Fallback method |
|---|---|
| Job Analyzer | Regex + 200-skill keyword vocabulary |
| Resume Profiler | Keyword search in CV text |
| Gap Detector | Set difference: required − found |
| Resume Optimizer | Rule-based bullet rewriting templates |
| Interview Prep | Pre-written question templates by category |
| Career Chat | "No AI available" polite response |

---

## 13. Deployment / Process Diagram

> **What it shows:** What is actually running on your machine when the app is live.

```
  YOUR LAPTOP
  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │  TERMINAL 1                      TERMINAL 2                    │
  │  ┌───────────────────────────┐   ┌───────────────────────────┐ │
  │  │  python main.py           │   │  npm run dev              │ │
  │  │                           │   │                           │ │
  │  │  Uvicorn ASGI server      │   │  Next.js + Turbopack     │ │
  │  │  FastAPI app              │   │  dev server               │ │
  │  │                           │   │                           │ │
  │  │  Listening: 0.0.0.0:8000  │   │  Listening: localhost:3000│ │
  │  └───────────────────────────┘   └───────────────────────────┘ │
  │            │                                 │                  │
  │            │                                 │                  │
  │            ▼                                 ▼                  │
  │  ┌───────────────────────────┐   ┌───────────────────────────┐ │
  │  │  In-process threads:      │   │  Browser tabs:            │ │
  │  │  • Main API thread        │   │  http://localhost:3000    │ │
  │  │  • JobEnricher pool       │   │                           │ │
  │  │    (10 worker threads)    │   │  Talks to backend via:    │ │
  │  │  • Background scrapers    │   │  http://localhost:8000    │ │
  │  └───────────────────────────┘   └───────────────────────────┘ │
  │            │                                                     │
  │            ▼                                                     │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  LOCAL FILES                                               │ │
  │  │                                                            │ │
  │  │  backend/data/users.db   ← accounts & sessions            │ │
  │  │  backend/data/jobs.db    ← saved jobs & applications      │ │
  │  │  backend/data/chroma/    ← resume vector embeddings       │ │
  │  │  backend/data/uploads/   ← your uploaded CV files         │ │
  │  │  backend/data/logs/      ← rotating app logs              │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │                                                                 │
  │            │  outbound only (job discovery)                     │
  │            ▼                                                     │
  │  ┌────────────────────────────────────────────────────────────┐ │
  │  │  INTERNET                                                  │ │
  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │ │
  │  │  │  Adzuna  │ │HackerNews│ │ Remotive │ │Greenhouse / │  │ │
  │  │  │   API    │ │  Algolia │ │  API     │ │Lever / Ashby│  │ │
  │  │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘  │ │
  │  │  ┌──────────────────────────────────────────────────────┐  │ │
  │  │  │  Gemini API  /  Claude API  /  Ollama (localhost)    │  │ │
  │  │  └──────────────────────────────────────────────────────┘  │ │
  │  └────────────────────────────────────────────────────────────┘ │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

  YOUR RESUME AND ACCOUNT DATA NEVER LEAVE THIS BOX
  (unless you configure an LLM API key — then only the prompt text is sent)
```

---

*All diagrams drawn in plain ASCII/Unicode — readable in any text editor, terminal, or GitHub.*
