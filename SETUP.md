# CareerPilot AI — Setup Guide

Everything runs on your own laptop. Your resume never leaves it.

---

## ⚡ Sharing via Google Drive / USB (Windows Laptop)

If you received this project as a folder from Google Drive or a USB drive,
**do this before copying**:

> **EXCLUDE these folders — they are large, Mac-specific, and will NOT work on Windows:**
>
> | Folder | Why exclude |
> |---|---|
> | `backend/.venv/` | Python virtual environment (Mac binaries, ~950 MB) |
> | `frontend/node_modules/` | Node.js packages (Mac binaries, ~620 MB) |
> | `frontend/.next/` | Build cache (Mac-specific, ~550 MB) |
> | `backend/data/` | User data & databases (optional — fresh start is better) |
>
> **What you DO need to copy:**
> - All source code (`backend/`, `frontend/` minus the folders above)
> - `.env.example` files
> - `SETUP.md`, `README.md`, `PROJECT_OVERVIEW.md`

After copying to your Windows machine, follow **Step 1** below (skip the git clone, you already have the code) then go straight to **Step 2**.

---

## Requirements

| Tool | Minimum version | Download |
|---|---|---|
| **Python** | 3.9 – 3.12 | https://www.python.org/downloads/ |
| **Node.js** | 20.9+ | https://nodejs.org/ |
| **Git** | any | https://git-scm.com/ |

> **Windows only — install this first:**
> `sentence-transformers` and `chromadb` compile C++ code during install.
> You need **Microsoft C++ Build Tools** or the install will fail.
> Download free from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
> In the installer, tick **"Desktop development with C++"** and click Install.

---

## Step 1 — Get the code

**Option A — From Google Drive / USB (you already have the folder):**
```
Open the folder you copied from Drive. That is your project root.
cd into it — that's your career-pilot-ai folder.
```

**Option B — From git:**
```bash
git clone <your-repo-url> career-pilot-ai
cd career-pilot-ai
```

---

## Step 2 — Backend setup

### 2a. Create a virtual environment

**Mac / Linux:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the script, run this once first:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 2b. Install Python dependencies

```bash
pip install -r requirements.txt
```

> First install takes **3–10 minutes** — it downloads PyTorch and the
> sentence-transformer model used for resume embeddings (~500 MB total).

### 2c. Create your `.env` file

**Mac / Linux:**
```bash
cp .env.example .env
```

**Windows:**
```cmd
copy .env.example .env
```

Open `.env` in any text editor and fill in **at least one** LLM option:

```
# --- Option A: Google Gemini (recommended — free tier, no install needed) ---
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
GEMINI_API_KEY=your_key_here
# Get a free key at: https://aistudio.google.com/apikey

# --- Option B: Anthropic Claude ---
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=your_key_here

# --- Option C: Ollama (fully local, no API key, needs Ollama installed) ---
LLM_PROVIDER=ollama
LLM_MODEL=mistral
OLLAMA_BASE_URL=http://localhost:11434
# Install Ollama from: https://ollama.com  then run: ollama pull mistral
```

**Optional — Adzuna job search** (adds Indian company listings, free signup):
```
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
# Sign up at: https://developer.adzuna.com
```

### 2d. Start the backend server

```bash
python main.py
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     CareerPilot AI v0.1.0 starting up
INFO:     Application startup complete.
```

**Leave this terminal open.**

---

## Step 3 — Frontend setup

Open a **new terminal / Command Prompt window**.

### 3a. Install Node dependencies

```bash
cd frontend
npm install
```

### 3b. Create your `.env.local` file

**Mac / Linux:**
```bash
cp .env.example .env.local
```

**Windows:**
```cmd
copy .env.example .env.local
```

Make sure `frontend/.env.local` contains:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3c. Start the frontend

```bash
npm run dev
```

You should see:
```
▲ Next.js 16.x (Turbopack)
- Local: http://localhost:3000
✓ Ready in ~400ms
```

**Leave this terminal open too.**

---

## Step 4 — Open the app

Go to **http://localhost:3000** in your browser.

1. **Create an account** — email + password (stored on your machine only)
2. **Upload your resume** — PDF, DOCX, TXT or MD, up to 10 MB
3. **Explore** — Find Jobs (last 7 days), Interview Prep, AI Assistant, and more

---

## Running it again next time

No reinstall needed. Just activate the environment and start both servers.

**Terminal 1 — Backend:**

Mac/Linux:
```bash
cd career-pilot-ai/backend
source .venv/bin/activate
python main.py
```

Windows:
```cmd
cd career-pilot-ai\backend
.venv\Scripts\activate
python main.py
```

**Terminal 2 — Frontend:**
```bash
cd career-pilot-ai/frontend
npm run dev
```

Then open **http://localhost:3000**.

---

## Troubleshooting

### `Connection refused` on localhost:3000
Frontend is not running. Run `npm run dev` inside the `frontend/` folder.

### `Connection refused` on localhost:8000
Backend is not running. Run `python main.py` inside `backend/` with the venv active.

### `error: Microsoft Visual C++ 14.0 is required` (Windows)
Install **Microsoft C++ Build Tools** from https://visualstudio.microsoft.com/visual-cpp-build-tools/
Tick "Desktop development with C++" during install, then re-run `pip install -r requirements.txt`.

### `pip install` fails on `hnswlib` or `chroma` (Windows)
Same fix — install Microsoft C++ Build Tools above.

### `torch` takes forever to install
Normal — PyTorch is ~500 MB. Let it finish. It only downloads once.

### AI features return empty / fallback answers
Your API key is missing or wrong. Open `backend/.env` and check `LLM_PROVIDER`
and the matching key (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, etc.).

### `'python3' is not recognized` (Windows)
Windows uses `python` not `python3`. Replace every `python3` with `python`.

### PowerShell says `cannot be loaded because running scripts is disabled`
Run this once in PowerShell as Administrator:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Resume disappears after restart
The index lives in `backend/data/chroma/` and survives restarts. If it is
gone, just upload your CV again from the home page or Settings.

---

## Project structure

```
career-pilot-ai/
├── backend/                ← FastAPI + Python
│   ├── main.py             ← entry point  →  python main.py
│   ├── .env                ← your config (gitignored, never commit)
│   ├── .env.example        ← copy this to .env
│   ├── requirements.txt    ← pip install -r requirements.txt
│   └── data/               ← resume index, databases, logs (gitignored)
│       ├── chroma/         ← vector store (resume embeddings)
│       ├── uploads/        ← uploaded CV files
│       ├── jobs.db         ← saved jobs (SQLite)
│       └── users.db        ← accounts (SQLite, hashed passwords)
│
└── frontend/               ← Next.js 16 + TypeScript
    ├── app/                ← pages (login, dashboard, jobs, etc.)
    ├── components/         ← UI components
    ├── .env.local          ← your config (gitignored, never commit)
    └── package.json        ← npm install + npm run dev
```

---

## What works without an API key

Even with no API key set, the app runs — it falls back to pattern-matching
rules instead of a language model. Job matching, gap detection and interview
questions still work; the answers are less nuanced than with a model.

To get the full AI experience, a **Gemini free key** is the easiest option:
takes two minutes at https://aistudio.google.com/apikey, costs nothing.
