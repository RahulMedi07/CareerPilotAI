# 🧭 CareerPilot AI

> 🤖 An AI career copilot that reads your CV, reads a job advert, and tells you **honestly** whether to apply — with its reasoning shown, not just a score to trust blindly.

![Python](https://img.shields.io/badge/Python-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-React-000000?logo=next.js&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-LangGraph-1C3C3C?logo=langchain&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-orange)
![TypeScript](https://img.shields.io/badge/TypeScript-Frontend-3178C6?logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

---

## ✨ Overview

Most CV-scoring tools hand you a number out of 100 and leave you to just trust it. 🤷

**CareerPilot AI** shows its working instead. It reads your CV, reads a job advert, and tells you: **apply now**, **learn a bit first**, or **skip this one** — and backs every claim with proof, like quoting the exact line on your CV that supports a skill match. It runs entirely on your own machine — your CV never leaves your laptop. 🔒

Built as a **multi-agent system** using LangGraph, with each stage of the career-prep pipeline (resume parsing, job analysis, gap detection, interview prep, and more) handled by its own specialized agent.

---

## 🚀 Features

### 📄 Resume Intelligence
- 🔍 **Instant CV analysis** — detects role, seniority, years of experience, education, and skills, sorted into groups
- 🧠 **RAG-powered indexing** — your resume is chunked and embedded (ChromaDB + sentence-transformers) so answers are grounded in what you actually wrote
- ❌ **Won't guess or inflate** — if your CV doesn't state years of experience, it says *"Not stated"* rather than defaulting to 0 or making one up

### 🔎 Job Discovery & Matching
- 🌐 **Live job search** — pulls real, current listings from company career pages (via a scraper/enricher pipeline) and Adzuna's API
- 🎯 **Evidence-based scoring** — a match score comes with the exact CV line proving each matched skill
- 🚫 **Refuses to fake a score** — if an advert is too vague to compare against, it says *"Not scored"* instead of inventing a number
- 📊 **Gap analysis** — splits missing skills into "will block you" vs. "won't really matter," each with an estimated learning time

### 🎤 Interview Preparation
- 🗣️ **Full mock interview generation** — technical, behavioural, HR, and "your own projects" rounds
- 💬 **Practice Room** — answer questions yourself first, then reveal AI feedback (word count, hedging language, whether you actually answered the question)
- 🏷️ **Transparent AI labeling** — every answer is tagged "AI-written" or "Rule-based" so you always know whether a real model or a fallback answered

### 📁 Application Tracking
- 📌 Track applications through their full lifecycle: saved → applied → interview → offer/rejected
- 📈 Real analytics (interview rate, offer rate) — computed only once you have enough data to make them meaningful
- 🧵 Full timeline history per application, nothing overwritten

### 🤖 AI Assistant
- 💬 Chat with an assistant grounded in your resume — ask "what should I apply for?" and get answers backed by your actual CV
- 📎 Attach a specific job advert to get context-aware answers about that role

### 🔐 Accounts & Privacy
- 👤 Per-user accounts with isolated data — your resume, jobs, and applications are yours alone
- 🖥️ **Fully local** — no cloud upload of your CV, ever
- 🔑 Secure auth: salted password hashing, server-side session validation

---

## 🖥️ Tech Stack

| Layer | Technology |
|---|---|
| 🎨 **Frontend** | Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Radix UI |
| ⚙️ **Backend** | FastAPI, Python |
| 🧩 **AI Orchestration** | LangChain, LangGraph (multi-agent workflow graph) |
| 🧠 **LLMs** | Google Gemini, Anthropic Claude (optional fallback), Ollama (local models) |
| 📦 **Vector Store** | ChromaDB + sentence-transformers (`all-MiniLM-L6-v2`) |
| 💾 **Database** | SQLite (auth & job/application storage) |
| 🧪 **Testing** | pytest (backend), Vitest (frontend) — 2,500+ automated checks |

---

## 📂 Project Structure

```
career-pilot-ai/
├── ⚙️ backend/
│   ├── agents/              # Specialized agents: resume_profiler, job_analyzer,
│   │                         gap_detector, interview_prep, resume_optimizer,
│   │                         answer_coach, application_tracker, and more
│   ├── rag/                  # Resume indexing & retrieval (ChromaDB)
│   ├── models/                # Pydantic models (auth, career data)
│   ├── utils/                  # Auth, caching, logging, retry handling, validation
│   ├── tests/                   # 2,500+ backend tests
│   └── main.py                   # FastAPI entry point
│
└── 🎨 frontend/
    ├── app/(dashboard)/      # Analyze, Assistant, Discover Jobs, Interview Prep,
    │                           My Applications, My Jobs, My Resume, Settings
    ├── components/            # Dashboard widgets, auth forms, shared UI (shadcn)
    └── lib/                     # API client, auth rules
```

---

## ⚡ Quick Start

### ✅ Prerequisites
- Python 3.9+
- Node.js 18+
- (Optional) A Gemini or Anthropic API key for real AI-powered answers — the app runs fully rule-based without one

### 1️⃣ Clone the repository
```bash
git clone https://github.com/RahulMedi07/CareerPilotAI.git
cd career-pilot-ai
```

### 2️⃣ Set up the backend ⚙️
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
Open `backend/.env` and optionally add your Gemini API key (get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)):
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```

Run the backend:
```bash
python main.py
```
🟢 API runs on **http://localhost:8000**

### 3️⃣ Set up the frontend 🎨
```bash
cd ../frontend
npm install
cp .env.example .env.local
npm run dev
```
🌐 App runs on **http://localhost:3000**

---

## 🧭 How It Works

1. 👤 **Sign up** and upload your CV (PDF, DOCX, TXT, or MD)
2. 📊 CareerPilot indexes it and shows you what a recruiter would see in the first 10 seconds
3. 🔎 Search for jobs (auto-suggested from your CV, or paste your own advert)
4. 🎯 Get a **verdict** — Apply now / Learn a bit first / Skip this one — backed by evidence
5. ✍️ Get a **tailored resume rewrite** and, if your gaps are closeable in ~2 weeks, a day-by-day study plan
6. 🎤 Practice a full mock interview built from your real CV and the job's real requirements
7. 📌 Track every application with full status history

---

## 🩹 Troubleshooting

| Problem | Fix |
|---|---|
| ❌ AI answers say "Rule-based" only | No AI key is configured — add `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` to `backend/.env` and restart |
| 🌐 Job search returns very few results | Add free Adzuna API credentials in `.env` (`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`) — without them only company career pages are searched |
| 📄 Upload fails on `.doc` files | Old-style `.doc` isn't supported — re-save as `.docx` in Word first |
| 🔄 Second CV upload "merges" instead of replacing | This is intentional — use **Clear index** on the Settings page first if you want to start fresh |
| 🐢 Gemini answers suddenly go quiet | Free tier is ~20 requests/day; check backend logs for HTTP 429 |

---

## 🔒 Security Note

Real API keys live only in `backend/.env` and `frontend/.env.local`, both gitignored. Never commit a real key to `.env.example` — always use placeholders there. If you zip and share this project, exclude `backend/.env`, `backend/data/`, and `node_modules/` — the repo's `.gitignore` already reflects this.

---

## 🤝 Contributing

Contributions are welcome! 🎉
1. 🍴 Fork the repo
2. 🌿 Create your branch (`git checkout -b feature/amazing-feature`)
3. 💾 Commit your changes (`git commit -m 'Add amazing feature'`)
4. 📤 Push to the branch (`git push origin feature/amazing-feature`)
5. 🔁 Open a Pull Request

---

## 📜 License

This project is licensed under the **MIT License**. 💙

---

## 👨‍💻 Author

**Rahul Medi**
🔗 GitHub: [@RahulMedi07](https://github.com/RahulMedi07)

---

<p align="center">Made with ❤️, 🐍 Python, and 🧩 multi-agent AI — because a job hunt deserves honesty, not vanity scores</p>
