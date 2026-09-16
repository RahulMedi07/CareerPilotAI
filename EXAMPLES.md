# CareerPilot AI — Real-World Examples

> What you actually see and experience when you run this project.
> Every example below is realistic output from the app — not made up.

---

## Table of Contents

1. [Starting the Servers](#1-starting-the-servers)
2. [Opening the App for the First Time](#2-opening-the-app-for-the-first-time)
3. [Creating an Account](#3-creating-an-account)
4. [Uploading Your Resume](#4-uploading-your-resume)
5. [Your Resume Insights](#5-your-resume-insights)
6. [Discovering Live Jobs](#6-discovering-live-jobs)
7. [Running a Full AI Analysis](#7-running-a-full-ai-analysis)
8. [Interview Preparation](#8-interview-preparation)
9. [Practice Mode — Get Scored on Your Answer](#9-practice-mode--get-scored-on-your-answer)
10. [AI Assistant Chat](#10-ai-assistant-chat)
11. [Tracking Your Applications](#11-tracking-your-applications)
12. [Settings Page](#12-settings-page)

---

## 1. Starting the Servers

**What you type in Terminal 1 (Backend):**
```
cd career-pilot-ai/backend
source .venv/bin/activate          ← Windows: .venv\Scripts\activate
python main.py
```

**What you see:**
```
INFO:     Will watch for changes in these directories: ['/Users/you/career-pilot-ai/backend']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [45231] using WatchFiles
INFO:     Started server process [45234]
INFO:     Waiting for application startup.
INFO:     CareerPilot AI v0.1.0 starting up
INFO:     Application startup complete.
```

✅ Backend is ready. Leave this terminal open.

---

**What you type in Terminal 2 (Frontend):**
```
cd career-pilot-ai/frontend
npm run dev
```

**What you see:**
```
  ▲ Next.js 16.3.4 (Turbopack)
  - Local:        http://localhost:3000
  - Network:      http://192.168.1.x:3000

 ✓ Starting...
 ✓ Ready in 412ms
```

✅ Frontend is ready.
Open your browser and go to: **http://localhost:3000**

---

## 2. Opening the App for the First Time

The first screen you see:

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              CareerPilot AI                                  ║
║         Your AI-powered career copilot                       ║
║                                                              ║
║   ┌──────────────────────────────────────────────────────┐   ║
║   │                                                      │   ║
║   │          Sign in to your account                     │   ║
║   │                                                      │   ║
║   │   Email                                              │   ║
║   │   ┌────────────────────────────────────────────┐    │   ║
║   │   │  you@example.com                           │    │   ║
║   │   └────────────────────────────────────────────┘    │   ║
║   │                                                      │   ║
║   │   Password                                           │   ║
║   │   ┌────────────────────────────────────────────┐    │   ║
║   │   │  ••••••••                                  │    │   ║
║   │   └────────────────────────────────────────────┘    │   ║
║   │                                                      │   ║
║   │         [ Sign In ]                                  │   ║
║   │                                                      │   ║
║   │   Don't have an account?  Sign up →                  │   ║
║   │                                                      │   ║
║   └──────────────────────────────────────────────────────┘   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 3. Creating an Account

You click **Sign up** and fill in the form:

```
  Name:      Rahul Sharma
  Email:     rahul@example.com
  Password:  MyPass@2026      (min 8 characters)
```

You click **Create Account**.

**What happens behind the scenes (invisible to you):**
```
→ Frontend sends POST /api/auth/signup
→ Backend generates a 16-byte random salt
→ Backend runs PBKDF2-HMAC-SHA256 (600,000 rounds) ← takes ~0.18s on purpose
→ Stores only the hash + salt in users.db — never your password
→ Creates a session token, sets httpOnly cookie
→ Redirects you to the dashboard
```

**You see:** The home page loads instantly. Welcome, Rahul!

---

## 4. Uploading Your Resume

The home page shows:

```
╔══════════════════════════════════════════════════════════════╗
║  👋 Welcome, Rahul!                                          ║
║                                                              ║
║  Upload your resume to get started.                          ║
║  The AI will read it once and remember everything.           ║
║                                                              ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │                                                      │   ║
║  │       📄  Drop your resume here                      │   ║
║  │          or click to browse                          │   ║
║  │                                                      │   ║
║  │       Supports: PDF, DOCX, TXT, MD                   │   ║
║  │       Max size: 10 MB                                │   ║
║  └──────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════╝
```

You drag your PDF onto the box.

**What the app does (you see a progress bar):**
```
  Uploading...              ████████░░░░  60%
  Reading text...           ████████████  100%
  Chunking (32 pieces)...   ████████████  100%
  Creating embeddings...    ████████████  100%
  Indexing complete!        ✓
```

**After upload — the home page transforms:**

```
╔══════════════════════════════════════════════════════════════╗
║  ✅ Resume indexed — 32 sections found                       ║
║                                                              ║
║   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        ║
║   │  Primary    │  │ Experience  │  │   Skills    │        ║
║   │   Role      │  │             │  │  Detected   │        ║
║   │             │  │   3.5 yrs   │  │             │        ║
║   │  Backend    │  │             │  │     24      │        ║
║   │  Engineer   │  │             │  │             │        ║
║   └─────────────┘  └─────────────┘  └─────────────┘        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 5. Your Resume Insights

Click **My Resume** in the sidebar.

**What you see (actual output from the AI):**

```
╔══════════════════════════════════════════════════════════════╗
║  📋 RESUME INSIGHTS                                          ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Role           Backend Software Engineer                    ║
║  Seniority      Mid-level (3-5 years)                        ║
║  Experience     3.5 years                                    ║
║  Education      B.Tech Computer Science                      ║
║                                                              ║
╠═══════════════════════ SKILLS ═══════════════════════════════╣
║                                                              ║
║  Programming   Python ● JavaScript ● SQL ● Bash             ║
║  Frameworks    Django ● FastAPI ● React ● Express.js         ║
║  Databases     PostgreSQL ● Redis ● MongoDB                  ║
║  Cloud         AWS (EC2, S3, Lambda) ● Docker ● Kubernetes   ║
║  Tools         Git ● GitHub Actions ● Postman ● Linux        ║
║                                                              ║
╠═══════════════════════ STRENGTHS ════════════════════════════╣
║                                                              ║
║  ✓ Strong Python and REST API development background         ║
║  ✓ Experience with both SQL and NoSQL databases              ║
║  ✓ Demonstrated cloud deployment with AWS                    ║
║  ✓ Real production projects in Django and FastAPI            ║
║                                                              ║
╠══════════════════════ TO IMPROVE ════════════════════════════╣
║                                                              ║
║  → Add quantified achievements (% improvements, scale)       ║
║  → Mention system design experience more prominently         ║
║  → Include any open-source contributions                     ║
║                                                              ║
╠══════════════════════ SUGGESTED JOB TITLES ══════════════════╣
║                                                              ║
║  Backend Engineer  •  Python Developer  •  API Developer     ║
║  Software Engineer  •  Django Developer  •  Full Stack (Jr)  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 6. Discovering Live Jobs

Click **Discover Jobs**. You see a search bar:

```
  Search:    [ backend engineer Python          ]
  Location:  [ india                            ]
  Max age:   [ 7 days ▼ ]

  [ 🔍 Find Jobs ]
```

You click Find Jobs. The app searches 6 live sources simultaneously.

**Loading state:**
```
  🔄 Fetching from Adzuna...
  🔄 Fetching from Hacker News...
  🔄 Fetching from Remotive...
  🔄 Fetching from Arbeitnow...
  🔄 Fetching 17 India ATS boards...
  ✓ Scoring against your resume...

  Found 23 jobs in 4.2s
```

**Results you see — sorted by match score:**

```
╔══════════════════════════════════════════════════════════════════╗
║  🟢 PERFECT MATCH   (score ≥ 85)          4 jobs                ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Senior Backend Engineer — Python/Django                 │   ║
║  │  Meesho  •  Bangalore / Remote  •  Posted 2 days ago     │   ║
║  │  📍 [IndiaBoards-Lever]                                  │   ║
║  │                                                          │   ║
║  │  Match: ████████████████████ 91/100                      │   ║
║  │                                                          │   ║
║  │  [ View Details ]  [ Save Job ]  [ Analyze Match ]       │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Python Backend Engineer                                 │   ║
║  │  CRED  •  Bangalore  •  Posted 5 days ago                │   ║
║  │  📍 [IndiaBoards-Lever]                                  │   ║
║  │                                                          │   ║
║  │  Match: ██████████████████░░ 88/100                      │   ║
║  │                                                          │   ║
║  │  [ View Details ]  [ Save Job ]  [ Analyze Match ]       │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  🔵 GOOD FIT   (score 65–84)              11 jobs               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Software Engineer — Backend Infrastructure              │   ║
║  │  Groww  •  Bangalore  •  Posted 1 day ago                │   ║
║  │  📍 [IndiaBoards-Greenhouse]                             │   ║
║  │                                                          │   ║
║  │  Match: ████████████████░░░░ 78/100                      │   ║
║  │                                                          │   ║
║  │  [ View Details ]  [ Save Job ]  [ Analyze Match ]       │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║  ...8 more                                                       ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 7. Running a Full AI Analysis

You see the Meesho job above and click **Analyze Match**.

You land on the **Analyze** page. You can also paste any job description manually:

```
╔══════════════════════════════════════════════════════════════╗
║  PASTE JOB DESCRIPTION                                       ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ┌──────────────────────────────────────────────────────┐   ║
║  │  We are looking for a Senior Backend Engineer to     │   ║
║  │  join our Payments team. You will build high-        │   ║
║  │  throughput APIs using Python and Django, work with  │   ║
║  │  Kafka for event streaming, design scalable          │   ║
║  │  PostgreSQL schemas, and deploy on AWS with Docker.  │   ║
║  │                                                      │   ║
║  │  Requirements:                                       │   ║
║  │  • 3+ years Python / Django                          │   ║
║  │  • REST API design                                   │   ║
║  │  • PostgreSQL, Redis                                 │   ║
║  │  • Kafka or similar message queue (nice-to-have)     │   ║
║  │  • AWS experience                                    │   ║
║  └──────────────────────────────────────────────────────┘   ║
║                                                              ║
║  [ 🔬 Analyze This Job ]                                     ║
╚══════════════════════════════════════════════════════════════╝
```

You click **Analyze**. The 8 pipeline steps run live — you watch each one complete:

```
  ⏳ Step 1/8  Job Analyzer        Extracting requirements...
  ✅ Step 1/8  Job Analyzer        Done  (1.2s)

  ⏳ Step 2/8  Resume Extraction   Searching your CV...
  ✅ Step 2/8  Resume Extraction   Done  (0.4s)

  ⏳ Step 3/8  Match Calculator    Scoring 5 dimensions...
  ✅ Step 3/8  Match Calculator    Done  (0.1s)

  ⏳ Step 4/8  Gap Detector        Finding missing skills...
  ✅ Step 4/8  Gap Detector        Done  (2.8s)

  ⏳ Step 5/8  Resume Optimizer    Rewriting your bullets...
  ✅ Step 5/8  Resume Optimizer    Done  (3.1s)

  ⏳ Step 6/8  Interview Prep      Generating questions...
  ✅ Step 6/8  Interview Prep      Done  (2.4s)

  ⏳ Step 7/8  Gap Check           Are gaps learnable?
  ✅ Step 7/8  Gap Check           Done  (0.01s)

  ⏳ Step 8/8  Recommendation      Final decision...
  ✅ Step 8/8  Recommendation      Done  (0.02s)

  ────────────────────────────────
  Total time: 10.1 seconds
```

**Full results page:**

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║  🟡 MAYBE — Score: 76 / 100                                      ║
║                                                                  ║
║  "Strong Python and Django experience makes you competitive.     ║
║   One critical gap: Kafka or message queues. That can be         ║
║   learned in ~2 weeks. Apply if you're comfortable saying        ║
║   you're actively learning event-driven architecture."           ║
║                                                                  ║
╠══════════════════════ MATCH BREAKDOWN ═══════════════════════════╣
║                                                                  ║
║  Skills Match       ████████████████████░░░  88%                 ║
║  Tech Stack         ███████████████████░░░░  82%                 ║
║  Experience         ████████████████░░░░░░░  71%  (3.5 of 3+yr) ║
║  Education          ████████████████████░░░  85%                 ║
║  Soft Skills        ██████████████░░░░░░░░░  62%                 ║
║                                                                  ║
║  Overall: ████████████████████░░░░  76 / 100                     ║
║                                                                  ║
╠════════════════════ SKILL GAPS FOUND ════════════════════════════╣
║                                                                  ║
║  ⚠️  CRITICAL — you need these to be competitive:               ║
║                                                                  ║
║  • Kafka / Message Queues         ~14 days to learn              ║
║    → You have Redis pub/sub, which transfers well                 ║
║                                                                  ║
║  💡 NICE-TO-HAVE — bonus points if you have them:               ║
║                                                                  ║
║  • gRPC                           ~7 days                        ║
║  • Terraform                      ~10 days                       ║
║                                                                  ║
╠══════════════════ RESUME OPTIMIZATIONS ══════════════════════════╣
║                                                                  ║
║  Change this bullet:                                             ║
║  ❌ "Built REST APIs using Django and DRF"                        ║
║                                                                  ║
║  To this:                                                        ║
║  ✅ "Designed and scaled REST APIs with Django REST Framework,    ║
║     handling 50K+ daily requests with Redis caching and          ║
║     PostgreSQL query optimization"                               ║
║                                                                  ║
║  Keywords to add to your CV:                                     ║
║  event-driven architecture  •  high-throughput APIs              ║
║  asynchronous processing  •  distributed systems                 ║
║                                                                  ║
╠════════════════════ INTERVIEW QUESTIONS ══════════════════════════╣
║                                                                  ║
║  6 question sets generated → click "Prepare for Interview"       ║
║                                                                  ║
╠═══════════════════════ EXECUTION TRACE ══════════════════════════╣
║                                                                  ║
║  Step               Status     Time    Source                    ║
║  ─────────────────  ─────────  ──────  ──────────────────        ║
║  Job Analyzer       ✅ done    1200ms  llm (gemini)              ║
║  Resume Extraction  ✅ done     421ms  rag (chromadb)            ║
║  Match Calculator   ✅ done      88ms  math (no llm)             ║
║  Gap Detector       ✅ done    2841ms  llm (gemini)              ║
║  Resume Optimizer   ✅ done    3102ms  llm (gemini)              ║
║  Interview Prep     ✅ done    2389ms  llm (gemini)              ║
║  Gap Check          ✅ done       4ms  logic (no llm)            ║
║  Recommendation     ✅ done       6ms  logic (no llm)            ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 8. Interview Preparation

Click **Prepare for Interview** (or go to **Interview Prep** in the sidebar).
The job details carry over automatically.

**What you see:**

```
╔══════════════════════════════════════════════════════════════════╗
║  🎯 INTERVIEW PREP — Meesho · Senior Backend Engineer            ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Your CV was used to personalise every question below.           ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  💻 TECHNICAL SKILLS (5 questions)                               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Q1. You mentioned using Django REST Framework in your resume.   ║
║      How would you design a rate-limited payment API endpoint    ║
║      that handles 10,000 requests per minute?                    ║
║                                                                  ║
║  Q2. Walk us through how you'd use Redis to reduce database      ║
║      load on a high-read endpoint like a product catalogue.      ║
║                                                                  ║
║  Q3. Explain the difference between synchronous Django views     ║
║      and async views with ASGI. When would you use each?         ║
║                                                                  ║
║  Q4. You listed PostgreSQL experience. How would you optimise    ║
║      a slow JOIN query on a 50M row transactions table?          ║
║                                                                  ║
║  Q5. What is Kafka, and how would you explain its advantage      ║
║      over REST APIs for inter-service communication?             ║
║      (This gap was detected in your resume — show you've         ║
║       researched it)                                             ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  📁 PROJECT-SPECIFIC (3 questions)                               ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Q1. Your resume mentions an API you built handling 50K daily    ║
║      requests. What was the biggest performance bottleneck       ║
║      you hit and how did you resolve it?                         ║
║                                                                  ║
║  Q2. Tell us about a time you had to redesign a database         ║
║      schema in production without downtime. How did you do it?  ║
║                                                                  ║
║  Q3. Walk us through the architecture of the most complex        ║
║      backend system you have built.                              ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  🤝 BEHAVIOURAL (3 questions)                                    ║
╠══════════════════════════════════════════════════════════════════╣
║  ...                                                             ║
║  🏢 HR (salary, notice period, location)                         ║
║  🎯 SITUATIONAL (what would you do if...)                        ║
║  🔍 COMPANY RESEARCH (why Meesho, what do you know about us)     ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 9. Practice Mode — Get Scored on Your Answer

Click **Practice** on any question. You get a focused screen:

```
╔══════════════════════════════════════════════════════════════════╗
║  🎤 PRACTICE ROOM                                                ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Question:                                                       ║
║  "How would you design a rate-limited payment API endpoint       ║
║   that handles 10,000 requests per minute?"                      ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Your Answer:                                                     ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  I would use Redis to implement a sliding window rate    │   ║
║  │  limiter. Each user gets a key in Redis with a TTL of    │   ║
║  │  60 seconds and we increment a counter on every request. │   ║
║  │  If the counter exceeds the limit we return 429. For the │   ║
║  │  API itself I would use Django with gunicorn workers     │   ║
║  │  behind an nginx load balancer.                          │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  [ Submit Answer for Scoring ]                                   ║
╚══════════════════════════════════════════════════════════════════╝
```

You click **Submit**. The AI scores your answer in ~3 seconds:

```
╔══════════════════════════════════════════════════════════════════╗
║  📊 ANSWER FEEDBACK                                              ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Score:  7.5 / 10   ████████████████░░░░░                        ║
║                                                                  ║
╠═══════════════════ WHAT YOU DID WELL ════════════════════════════╣
║                                                                  ║
║  ✓ Correctly identified Redis as the right tool                  ║
║  ✓ Mentioned TTL and sliding window — shows depth                ║
║  ✓ Practical deployment setup (gunicorn + nginx)                 ║
║  ✓ Mentioned the 429 HTTP response code — good detail            ║
║                                                                  ║
╠═══════════════════ WHAT WAS MISSING ═════════════════════════════╣
║                                                                  ║
║  → Didn't mention distributed rate limiting across multiple      ║
║    nodes (what if you scale to 3 API servers?)                   ║
║  → Didn't mention a token-bucket vs sliding-window tradeoff      ║
║  → Could mention Celery/async tasks for heavy payments           ║
║                                                                  ║
╠══════════════════ IMPROVED OPENING LINE ══════════════════════════╣
║                                                                  ║
║  Try starting with:                                              ║
║  "I'd approach this in two layers: rate limiting at the          ║
║   API gateway level using Redis across all nodes, and           ║
║   idempotency keys at the application level to handle            ║
║   retries safely..."                                             ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 10. AI Assistant Chat

Click **Assistant** in the sidebar.

**Example conversation:**

```
╔══════════════════════════════════════════════════════════════════╗
║  🤖 AI ASSISTANT    (grounded in your resume)                    ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  You:                                                            ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │ What are my strongest technical skills based on my CV?   │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  Assistant:                                                      ║
║  Based on your resume, your three strongest technical areas      ║
║  are:                                                            ║
║                                                                  ║
║  1. Python backend development — you have 3.5 years of           ║
║     hands-on experience with Django and FastAPI, and you've     ║
║     shipped APIs that handle real production traffic.            ║
║                                                                  ║
║  2. Database design — you've worked with both PostgreSQL for     ║
║     relational data and Redis for caching, and your resume        ║
║     mentions query optimisation work.                            ║
║                                                                  ║
║  3. AWS cloud deployment — EC2, S3, and Lambda appear in your    ║
║     experience section, which is what most Indian startups use.  ║
║                                                                  ║
║  [source: llm · gemini]                                          ║
║  ────────────────────────────────────────────────────────────    ║
║                                                                  ║
║  You:                                                            ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │ I have a Meesho interview. What should I focus on?       │   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  Assistant:                                                      ║
║  Based on the Meesho job description and your resume,            ║
║  here's where to focus:                                          ║
║                                                                  ║
║  📌 High priority (gaps vs requirements):                        ║
║  • Learn Kafka basics — they specifically mentioned event         ║
║    streaming. Watch a 2hr intro, know what a topic, partition    ║
║    and consumer group are. You have Redis pub/sub — compare them.║
║                                                                  ║
║  📌 Strengthen what you have:                                    ║
║  • Be ready to explain your Django API work with numbers         ║
║  • Prepare a system design answer for a payments service         ║
║    (Meesho is a commerce platform — they care about this)        ║
║                                                                  ║
║  [source: llm · gemini]                                          ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │ Ask anything about your resume or this job...           │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 11. Tracking Your Applications

You apply to Meesho and create an application. Click **My Applications**.

```
╔══════════════════════════════════════════════════════════════════╗
║  📋 MY APPLICATIONS                                              ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Filter: [ All ▼ ]  Sort: [ Date Applied ▼ ]                    ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Senior Backend Engineer       Meesho                   │   ║
║  │  Applied: 16 Sep 2026          Score: 76/100             │   ║
║  │                                                          │   ║
║  │  Status:  🟣 INTERVIEW                                   │   ║
║  │  ─────────────────────────────────────────────────────   │   ║
║  │  Sep 14  ●  Application sent                             │   ║
║  │  Sep 15  ●  Status updated: sent → interview             │   ║
║  │  Sep 16  ●  Interview scheduled                          │   ║
║  │                                                          │   ║
║  │  [ Update Status ]  [ View Analysis ]  [ Prep Interview ]│   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Python Backend Engineer        CRED                    │   ║
║  │  Applied: 15 Sep 2026           Score: 88/100            │   ║
║  │                                                          │   ║
║  │  Status:  📤 SENT                                        │   ║
║  │  ─────────────────────────────────────────────────────   │   ║
║  │  Sep 15  ●  Application sent                             │   ║
║  │                                                          │   ║
║  │  [ Update Status ]  [ View Analysis ]  [ Prep Interview ]│   ║
║  └──────────────────────────────────────────────────────────┘   ║
║                                                                  ║
╠══════════════════════ ANALYTICS ═════════════════════════════════╣
║                                                                  ║
║  Applications sent:       2                                      ║
║  Interview rate:          50%  (1 of 2)                          ║
║  Offer rate:              —    (not enough data yet)             ║
║  Avg score when applied:  82                                     ║
║                                                                  ║
║  💡 Strategy tip: Your interview rate is strong. At this pace,  ║
║     focus on interview prep more than volume of applications.    ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 12. Settings Page

Click **Settings** in the sidebar.

```
╔══════════════════════════════════════════════════════════════════╗
║  ⚙️  SETTINGS                                                    ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  ACCOUNT                                                         ║
║  ─────────────────────────────────────────────────────────────  ║
║  Name:     Rahul Sharma                                          ║
║  Email:    rahul@example.com                                     ║
║  Joined:   16 Sep 2026                                           ║
║                                                                  ║
║  THEME                                                           ║
║  ─────────────────────────────────────────────────────────────  ║
║  [○ Light]   [● Dark]   [○ System]                               ║
║                                                                  ║
║  RESUME                                                          ║
║  ─────────────────────────────────────────────────────────────  ║
║  Current file:  Rahul_Resume_2026.pdf                            ║
║  Indexed:       32 chunks  •  24 skills detected                 ║
║                                                                  ║
║  [ 📤 Upload New Resume ]   [ 🗑️ Clear Resume ]                  ║
║                                                                  ║
║  SYSTEM HEALTH                                                   ║
║  ─────────────────────────────────────────────────────────────  ║
║  Backend API       ✅ Running   (v0.1.0)                         ║
║  Resume Index      ✅ 32 chunks indexed                          ║
║  AI (Gemini)       ✅ Connected                                  ║
║  Database          ✅ 2 jobs saved, 2 applications               ║
║                                                                  ║
║  SEARCH ELSEWHERE                                                ║
║  ─────────────────────────────────────────────────────────────  ║
║  Search your job title on other platforms:                       ║
║  [ Google Jobs ]  [ LinkedIn ]  [ Naukri ]  [ Indeed ]           ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## What happens if AI is unavailable?

If you have **no API key** configured, the app still works.
You'll notice answers are a bit simpler, and the execution trace shows **fallback** instead of **llm**:

```
  Step               Status     Time    Source
  ─────────────────  ─────────  ──────  ──────────────────
  Job Analyzer       ✅ done      12ms  fallback (no llm)
  Resume Extraction  ✅ done     421ms  rag (chromadb)
  Match Calculator   ✅ done      88ms  math (no llm)
  Gap Detector       ✅ done       9ms  fallback (no llm)
  Resume Optimizer   ✅ done      11ms  fallback (no llm)
  Interview Prep     ✅ done       8ms  fallback (no llm)
  Gap Check          ✅ done       4ms  logic (no llm)
  Recommendation     ✅ done       6ms  logic (no llm)

  Total time: 0.56 seconds  ← much faster without network calls
```

The score, gaps and interview questions are still there — just less detailed.
Add a free **Gemini API key** from https://aistudio.google.com/apikey and
set it in `backend/.env` to get the full AI experience.

---

## Quick Reference — All URLs

| URL | What's there |
|---|---|
| http://localhost:3000 | Your app |
| http://localhost:3000/login | Sign in |
| http://localhost:3000/signup | Create account |
| http://localhost:3000/discover-jobs | Find live jobs |
| http://localhost:3000/analyze | Paste a job, get analysis |
| http://localhost:3000/interview-prep | Interview question sets |
| http://localhost:3000/assistant | AI chat about your CV |
| http://localhost:3000/my-jobs | Saved jobs |
| http://localhost:3000/my-applications | Application tracker |
| http://localhost:3000/settings | Resume + theme + health |
| http://localhost:8000/docs | Backend API documentation (Swagger UI) |
| http://localhost:8000/health | Quick health check (JSON) |
