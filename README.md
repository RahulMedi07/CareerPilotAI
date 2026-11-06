# CareerPilot AI

**Should you apply for this job? CareerPilot reads your CV, reads the advert, and gives you an answer — with its reasoning shown.**

Most CV tools give you a score out of a hundred and leave you to trust it.
CareerPilot shows its working. Which of your skills it found and the line on
your CV that proves each one. What the job asks for that you haven't got.
Whether you could learn those things in the time available. What to change on
your CV. What they're likely to ask you at interview.

It runs on your own laptop. Your CV never leaves it. There's no service to sign
up to and nothing to pay — the account you create is a row in a file next to
the app, on your own disk.

---

## What you get out of it

**It asks for your CV first.** The home page has one thing on it until you have
uploaded one, because nothing else in the app has anything to read until then.
A PDF or a Word `.docx` both work, as do plain `.txt` and `.md`. Once it is in,
the same page turns into a summary of what it found and four numbered links —
read my resume back to me, find matching jobs, prepare for the interview, ask
the assistant — which is the whole app, in order.

**Tell you what your CV says about you.** What role it reads as, what level, what
you can actually evidence, what is working in your favour and what to fix first.
No job advert involved — this is the picture a recruiter forms before they
compare you to anything.

**Go and find the jobs.** It works out what to search for from your own CV and
searches for you, then links you straight to each posting. It looks for openings
in India, newest first, aiming at adverts posted in the last couple of days. You
do not have to guess which words a job board indexed. It shows you the phrases
it searched, so if it has read you wrong you can see that and type your own.

**Tell you why each one is worth your time.** Every advert carries a short
answer to "why should I apply for this?" — which of your skills it already
matches, named rather than counted, what you would be learning on the job, and
what kind of role and level it is pitched at. All of it is read off the
comparison the app has already done, so you can check any line of it against
your own CV in a second. The gap is stated next to the overlap: a list of
reasons to apply with the reasons against left off is an advert, not advice.

**Get you ready for the interview.** Questions built from what your CV claims,
what they will probe about the company, and questions worth asking them back.
Paste an advert and the questions aim at that role; leave it blank and you get a
first-round screen on your own skills.

**Question your own projects.** Alongside the technical round, it picks lines
off your resume — the things you actually built — and asks you to defend them,
quoting your own words back rather than paraphrasing. If you cannot talk for two
minutes about a line on your CV, that line is a liability, and better to find
out now.

**The HR round, and the awkward ones.** The "tell me about yourself", "why are
you leaving", "what are you looking for" conversation is kept separate from the
behavioural questions, because it is a different room with a different person in
it. And there is a set of on-the-spot scenarios aimed at the kind of role the
advert describes.

**Where you are thin.** The last section is the honest one: the things the
advert asks for that your CV does not evidence, each with what to do about it
before the interview. Only real technologies appear here — it will not tell you
to "build one small thing with Backend".

**Answer questions about your career.** There is an assistant you can talk to.
It is grounded in your CV, and you can paste an advert into it so its answers
are about that job rather than in general. Every reply is labelled with who
wrote it — a model, or the fixed rules that run when no model is configured.
When it does not know, it says so instead of making something up.

**Practise answering, not just reading.** On the Interview Prep page you get one
question at a time with an empty box, and you type your answer before you are
shown a suggested one. Reading a good answer feels almost exactly like being able
to give one, and the difference only shows up in the room. Ask for feedback and
it tells you how long your answer was, whether you named a real number, which
hedges you used — "sort of", "I guess" — and whether you ever actually mentioned
the thing you were asked about. With an AI key configured it also gives you a
mark out of ten. Without one it says **Not scored** rather than inventing a
number, because a made-up mark is worse than no mark.

Then, once you paste in a job advert, it comes back with:

**A verdict.** Apply now, apply after some focused learning, or skip this one.
Not just a number — an actual recommendation, and the reasoning behind it.

**A score you can argue with.** Say it gives you 74%. It will tell you it found
Python, FastAPI and LangChain on your CV and quote the line each came from, and
that the advert also wanted Kubernetes, which it couldn't find anywhere on your
CV.

**Your gaps, sorted by whether they matter.** Some missing skills will stop you
getting an interview. Others won't. It separates the two, and for each one
estimates how long it would take you to get up to speed.

**A rewritten CV, tailored to that advert.** Reworded bullet points, and
keywords the advert uses that you should be using too.

**A study plan, but only when one makes sense.** If your gaps could realistically
be closed in a couple of weeks and the advert isn't closing tomorrow, you get a
day-by-day plan. If they'd take three months, you don't, because the job won't
wait.

**Interview questions weighted towards your weak spots.** That's where the hard
questions come from.

**A record of everything you've applied for** — where each one stands, and how it
got there. Sent on the 4th, interview on the 11th, rejected on the 18th.

**Honest figures on your own job hunt.** Your interview rate and your offer
rate, shown on the applications list itself, with the range they are actually
confident about and a plain sentence when the sample is too small to mean
anything.

---

## The thing that makes it different

Everything above, a dozen other tools do. Here's what this one does that they
don't: **it refuses to tell you things it doesn't actually know.**

That sounds like a small thing. It isn't. It's the single most important design
decision in the project, and it shows up everywhere:

**It won't put a skill on your CV that you don't have.** The obvious way to make
a CV tool look impressive is to add every keyword from the advert. Your score
jumps twenty points and everybody's happy — until the interview, where you have
to talk about Kubernetes. We tested exactly this on the sample CV. The honest
rewrite moved the score from 73.6 to 73.6 — no change at all. Allowing it to
add three skills the person didn't have took it to 93.7. That entire twenty-point
"improvement" was made of things you'd be lying about. We kept the honest
version, which means the headline improvement is often zero, and it says so in
plain words rather than hiding it.

**It won't quote you a success rate from four applications.** If you've sent
three applications and had one interview, that's not a 33% interview rate,
that's three applications. Below five, it declines to give a figure at all.
Above five, it gives you the range as well as the number — because twelve
applications and nine interviews is "somewhere between 47% and 91%", not "75%".

**It won't invent a salary.** Most adverts don't state one. It leaves it blank
rather than guessing, because you'd be the one negotiating against a made-up
figure.

**It won't make up a web link.** Every learning resource it points you at was
actually opened and checked. A skill with no verified link gets nothing rather
than a plausible-looking guess.

**It won't tell you that a pattern exists when it doesn't.** An early version
announced "LangGraph is missing in 3 of your 3 rejections" — which sounds like a
finding and is nothing of the sort, because LangGraph was missing from all
twelve applications, including the ones that got interviews. It now only flags a
skill when it's genuinely more common in your rejections than your successes.

**It won't apply for anything on your behalf.** It could. The tempting version
fires off twenty applications while you make coffee. But it also reports your
interview rate, and that's a fraction with your applications on the bottom of
it. Twenty applications you never really sent would sit in that fraction
forever, dragging the answer towards zero and telling you something false about
how your hunt is going. The most it does is put a job in your "to apply" pile.

---

## How it actually decides

Worth understanding, because it explains why two different jobs can give you
very different-looking answers.

**First it reads the advert** and pulls out what's required, what's merely nice
to have, how senior the role is, and what you'd actually be doing.

**Then it looks you up.** Your CV isn't stored as one lump of text — it's broken
into pieces and filed so that the app can search it by meaning rather than by
exact words. That's what lets it know that "built a RAG pipeline" is evidence
for LangChain experience, and quote you the line.

**Then it scores you**, across several weighted dimensions rather than one
blunt keyword count.

**Then it takes one of several routes**, and this is the interesting part. The
app doesn't do the same ten steps for everyone:

- If you're already a strong match, it skips the CV-rewriting step entirely and
  tells you why — above a certain score, rewording genuinely cannot help you,
  and pretending otherwise wastes your time.
- If rewording *did* move your score, it re-scores you and carries on with the
  better number.
- If you've got gaps, it asks whether they could be closed in roughly a
  fortnight. If yes, you get a study plan. If no, you don't.
- Then it prepares your interview questions and gives you the final verdict.

It shows you which steps it skipped and why, so a short run doesn't look like a
broken one.

---

## Finding jobs

You don't have to paste adverts in one at a time. Type a title or a skill and
it'll go and fetch live adverts, read each one, score it against your CV, and
sort them into perfect matches, good fits, stretch goals and needs-learning.

Three things worth knowing about where those come from:

**The search is restricted to India, and to the last seven days.** There is
no region picker, because there is no longer a choice to make. Newest adverts
come first.

The adverts come from twelve Indian employers' own vacancy boards — Paytm,
Meesho, CRED, Groww, Postman, Druva, Observe.AI and others — plus Hacker News,
Remotive, Arbeitnow and public RSS feeds. Measured on a real run: 513 adverts
fetched, 354 of them located in India.

**Every result links straight to the posting you apply on.** Hacker News
adverts used to link to the comment thread they were posted in, which is
somewhere to read rather than somewhere to apply; the employer's own careers
link is now taken from the advert instead, and the discussion is kept
separately for anyone who wants it.

Seven days is a promise rather than a target. Nothing older is shown, whatever
else happens, and an advert that never stated a posting date is not shown
either — "we do not know how old this is" is not the same answer as "recent
enough". The honest consequence is that a narrow search can come back with
very few results, or none. When that happens the page says so plainly instead
of quietly reaching back a month to look busier. Each card carries its own
posted date.

When India genuinely empties the list, the page offers you a **Search anywhere
instead** button. It is offered rather than done for you: quietly showing US
roles under a heading that says India would be the worse failure of the two.

**Most of the adverts come from Indian companies' own vacancy pages.** Paytm,
Meesho, CRED, Groww, Postman, Druva, Epifi, Zenoti, Netradyne, Sigmoid,
Observe.AI and Atlan all publish their live openings as a public feed for their
own careers page to display. Reading that feed is reading what the company
chose to publish. On the day this was written those twelve carried 513 adverts
between them, 354 of them in India. Alongside them sit the Hacker News monthly
hiring thread, Remotive, Arbeitnow and public RSS feeds, which occasionally
carry an Indian role too.

No one employer is allowed to swamp the page. Paytm alone posts more than all
the others combined, so results are dealt out one company at a time rather than
taken in order — otherwise a page of ten results was ten Paytm adverts.

**LinkedIn, Indeed, Naukri, Foundit and Wellfound are not included, and cannot
be.** This is not an oversight and not something left for later:

- **LinkedIn** offers no public jobs API, and their User Agreement forbids
  automated collection outright.
- **Indeed** withdrew its Jobs API to existing partners only; new access is
  closed, and their robots.txt disallows the job pages.
- **Naukri** and **Foundit** publish no API and their terms prohibit automated
  extraction.
- **Wellfound** publishes no open feed either.

There is no clever way around any of that. An app that scraped them anyway
would be breaking their terms and would break the first time they changed their
page. The company boards above were chosen because they are the honest way to
get the same thing: real, current, Indian vacancies.

**There is, however, a legitimate way to reach much of the same market.** Those
boards license their listings to aggregators, and Adzuna is one of them: it
redistributes adverts it has the right to redistribute, and hands out API keys
for exactly this use. Going through the licensee is the front door.

Adzuna is switched off until you give it a key, and it is free:

1. Sign up at <https://developer.adzuna.com> — it takes a minute.
2. Copy your **Application ID** and **Application Key**.
3. Put them in `backend/.env`:

   ```
   ADZUNA_APP_ID=your-id-here
   ADZUNA_APP_KEY=your-key-here
   ```

4. Restart the backend.

From then on, every search also asks Adzuna's India service for adverts posted
in the last seven days, and each one arrives with a link straight to the
posting. Leave the two blank and nothing breaks — that source simply sits out,
which is why the app works perfectly well before you get round to it.

**You also get a set of links out to the closed boards.** Every search shows a
row of buttons — LinkedIn, Naukri, Indeed, Foundit, Wellfound — that open that
same search on those sites, filtered to India and the last seven days wherever
the site's own search supports it. Only the words you searched for travel.
You arrive signed in as yourself, which is the ordinary way to use those sites
and the one thing a scraper could never do.

**Three of the job boards this was originally meant to use no longer exist.**
GitHub Jobs shut in 2021, Stack Overflow's board closed in 2022, dev.to
discontinued theirs. Rather than assume, each was tried with a real request
before anything was built on it.

Where a job board asks for something in return — Remotive asks to be credited,
linked back to, and queried no more than about four times a day — those terms
are honoured in the way the app actually behaves, not just quoted in a document.

---

## Your data

Everything stays on your machine. Your CV is filed locally, your applications
are recorded locally, and no part of it is sent anywhere.

There's a clear-my-data option, and it genuinely clears everything — including
the working copies the app keeps to speed itself up. That sounds obvious, but a
saved copy that survives the delete button is deleted data that's still sitting
there, and it's a mistake that's easy to make. There's a test whose only job is
to make sure the delete button reaches every copy.

### Your account

You sign in, and what you see is yours. More than one person can use the same
copy of the app — each gets their own resume, their own saved jobs and their
own applications, and neither can see the other's.

That separation is enforced by the server, not by the screen. Earlier the app
took your word for who you were, so anyone who knew how to ask could read
anyone's data. Now the server works it out from your sign-in and ignores what
the request claims. Your resume in particular is kept in its own separate
store per account, so a mistake in the code returns nothing rather than
returning someone else's CV. The match scores on the job search read from that
same per-account store, so the number you see is about your CV and no one
else's — and if you haven't uploaded one, the app says it didn't score rather
than quietly scoring you against nothing. The full analysis is built the same
way: its own machinery per account, so the report you read was written about
your CV and not about whoever used the app before you.

Your password is never stored. What's kept is a slow, salted hash of it — the
kind that's designed to be expensive to attack even if someone walks off with
the file. Signing out ends the session on the server there and then, rather
than just forgetting it in your browser. If you stay signed in, that lasts two
weeks.

Three things genuinely aren't built yet, and the Settings page says so rather
than pretending: you can't change your password, delete your account, or reset
a forgotten password. If you forget it, the account is not recoverable. Worth
knowing before you pick one.

---

## Getting it running

You need **Python 3.9, 3.10, 3.11 or 3.12** and **Node 20.9 or newer**.

Both ends of the Python range matter. Next.js 16 refuses to build on Node 18,
which is past its end of life. And **Python 3.13 will not work** — it is the
version a new laptop installs by default today, so this is the likeliest way a
fresh copy fails. `numpy==1.26.4` publishes no 3.13 build, so `pip install`
tries to compile it from source and stops on a wall of C errors that look like
a broken project rather than a version mismatch. If that happens, check
`python3 --version` first.

From the `backend` folder:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

That `cp` matters. Several sections below tell you to "open `backend/.env`",
and on a fresh copy that file does not exist yet — it is deliberately left out
of anything you share, because it is where the keys live.

Then, in a second terminal, from the `frontend` folder:

```
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. If you'd rather skip the website, the backend's
own page at `http://localhost:8000/docs` still lets you try everything by
filling in forms.

If you run the website on a different port, add that address to `CORS_ORIGINS`
in `backend/config.py` as well as setting it in `.env.local`. The browser
blocks the requests otherwise, and it will look like the backend is down when
it isn't.

### The first resume upload is slower than every one after it

The first time you upload a CV on a new machine, it will sit there for a while
before anything happens. Nothing is wrong. Reading a CV needs a small language
model called `all-MiniLM-L6-v2`, and it is not in the download — it is fetched
the first time it is actually needed and cached in `~/.cache/huggingface`,
where it takes about **90 MB**. Measured on this machine, that cache is 87 MB.

Two consequences worth knowing before you blame the app. **The first upload
needs an internet connection**, even if you are running Ollama locally and
expected the whole thing to be offline; every upload after it is offline. And
on a fresh install the health page can report `unhealthy` for the first minute
or so, because the check times out while that download is still going. It
settles by itself — on the clean-machine test above it was healthy about 25
seconds after startup once the model was cached, and it reports `degraded`
rather than `healthy` until you add an AI key, which is the correct answer to
"no key configured yet", not a fault.

**Optionally**, install [Ollama](https://ollama.ai) and pull a model. This gives
you better-worded suggestions. The app works completely without it — every
single feature has a fallback that runs without any AI model at all, which is
why it starts instantly and works on a laptop with no graphics card. If Ollama
isn't running, the health page reports "working, but not at full strength"
rather than "broken", because that's the truth.

### The keys that decide how many jobs you see

There are two different keys and they do unrelated jobs. Mixing them up is the
most likely reason a fresh copy disappoints you.

A **Gemini key** controls the *wording* — whether advice is written by a model
or assembled from rules. The next section covers it.

**Adzuna keys control how many adverts exist at all**, and without them the app
falls back to reading a handful of company career pages directly. This is not a
small difference. Measured on the same search, the same minute, same CV:

| | Adverts found | Sources |
| --- | --- | --- |
| With Adzuna keys | 14 | Adzuna, plus career pages |
| Without | **2** | One career page |

They are free, they need no card, and they take about two minutes: register at
[developer.adzuna.com](https://developer.adzuna.com), then put the application
ID and key on the `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` lines of `backend/.env`.

Nothing breaks without them. Discovery still runs, still scores what it finds
against your CV, and tells you plainly that only two adverts turned up rather
than pretending that is the whole market. But two is not enough to job hunt
with, so if the page looks empty on a new machine, check these before assuming
something is broken.

### Turning the AI on

Without a model, the assistant and the resume reading still run — they just run
on fixed rules, and they say so on every answer. There are three ways to give
them a real model, and you only need one.

**A Google Gemini key** is the cheapest way in, because Google gives a free
allowance without a card. Get one from
[Google AI Studio](https://aistudio.google.com/apikey), open `backend/.env`, put
it on the `GEMINI_API_KEY` line, set `LLM_PROVIDER=gemini`, and restart the
backend.

**An Anthropic key** works the same way, on the `ANTHROPIC_API_KEY` line, with
`LLM_PROVIDER=claude`. This one is paid.

**Ollama** runs a model on your own machine, so it costs nothing and sends
nothing anywhere, but it needs a few gigabytes of disk and a reasonably modern
laptop. Install it, pull a model, and leave `LLM_PROVIDER=auto`.

Three things worth knowing. An OpenAI key will not work; the app talks to
Ollama, Gemini and Claude only. The key belongs in that file and nowhere else —
never paste it into a chat window, a commit, or a screenshot; `.env` is already
ignored by git. And the free Gemini allowance is a **daily** one, counted per
model, and it is small — on the order of a couple of dozen requests, while one
full resume analysis spends about six. When it runs out the answers quietly go
back to being rule-based until the next day. That is the allowance doing its
job, not the app breaking, and the answer will tell you so rather than pretend
it was judged.

Once a key is set, the labels on the assistant's answers change from
"Rule-based" to "AI-written". That label is the only reliable way to tell which
one you are reading, which is exactly why it is there.

---

## Sending it to someone else

Zipping the folder as it sits on disk is the wrong move twice over. It is
**2.2 GB**, and almost all of that is rebuildable on the other machine. Worse,
it contains `backend/.env`, and that file has your Gemini key and your Adzuna
keys in plain text. A zip is not a private channel — it gets forwarded,
uploaded, and sat in inboxes.

Four folders account for nearly all the weight, and none of them should travel:

| Folder | Size | Why it must not go |
| --- | --- | --- |
| `backend/.venv` | 938 MB | Hard-codes paths from *this* machine; broken on arrival |
| `frontend/node_modules` | 612 MB | Platform-specific binaries; `npm install` rebuilds it |
| `frontend/.next` | 566 MB | Build output, regenerated on first run |
| `backend/data` | 42 MB | **Your CV, your saved jobs, your applications — and now the accounts file, which holds email addresses and password hashes** |

From the folder *above* `career-pilot-ai`:

```
zip -r careerpilot.zip career-pilot-ai \
  -x "*/.venv/*" "*/node_modules/*" "*/.next/*" "*/__pycache__/*" \
     "*/.git/*" "*/data/chroma/*" "*/data/uploads/*" "*/data/logs/*" \
     "*/data/*.db" "*/data/*.db-*" \
     "*/.env" "*/.env.local" "*/.DS_Store"
```

Three of those patterns are easy to leave out and each one leaks something:

- **`*/data/*.db-*`** catches `users.db-wal` and `users.db-shm`. SQLite writes
  to a `-wal` sidecar first, so excluding only `*.db` can ship rows — password
  hashes among them — that had not been folded into the main file yet. They are
  often empty, which is exactly what makes the gap easy to miss.
- **`*/data/logs/*`** is 15 MB of runtime log, and without it the archive is
  roughly ten times smaller. It holds no keys, emails or session tokens, but it
  does carry internal account ids and the filenames of CVs you uploaded.
- **`*/.env`** is the one that actually matters. Everything else is
  embarrassing; this one is your key.

That lands at **just under 1 MB**. It keeps the two sample files in
`backend/data`, so the person opening it has something to try immediately, and
it keeps `.env.example`, which is the file they copy to make their own `.env`.

Before sending, check the archive rather than trusting the command:

```
unzip -l careerpilot.zip | grep -iE '\.env$|\.db|chroma|uploads|logs/'
```

Anything listed other than `.env.example` should not be there.

They then follow **Getting it running** above, and supply their own keys. Yours
stay on your laptop, which is the only place a key should ever be.

One thing to say out loud when you send it: the app will start and work with no
keys at all, but job discovery will find about two adverts instead of a dozen
or more. That is the missing Adzuna keys, not a broken build, and the page says
so — but it is worth mentioning so nobody's first impression is an empty
screen.

The other thing worth saying: they will need to create an account when they
open it. Yours doesn't travel — the accounts file is excluded along with the
rest of `backend/data` — so their first screen is a sign-up form, not a
password prompt they can't answer.

---

## The order to do things in

The sidebar is arranged in the order you would actually use it, and following it
top to bottom is the whole workflow. Everything downstream of step 1 depends on
your CV being indexed, so the app asks for it before anything else.

**First, an account.** The first time you open it you'll be asked to create one
— an email and a password, nothing else. It takes a moment and it's what makes
the rest of it yours. If you open a page directly it will send you to the sign-in
screen and then carry you back to the page you were after.

**Home** is the front door and it has one job: get your CV in. Until it has one
it shows an upload box and nothing else. Once it has one it shows you what it
read \u2014 the headline, the role it reads as, your level, your years, your skills
\u2014 and the four numbered steps below.

**1. My Resume.** The full read: every skill it can evidence and the line that
proves each one, what is working in your favour, what to fix first.

**2. Find Jobs.** Press "Use my CV" and it searches with phrases taken from
your own resume. It shows you those phrases, so if it has misread you, you can
see that and type your own instead. Best matches come first. Anything it could
not measure sits at the bottom marked "Not scored", with a line saying why —
either no CV was indexed at the time, or the advert listed nothing comparable.
A copywriting post has no tech stack to compare a backend CV against, and it
will say so rather than score you on years alone. Each card says why it is
worth your time and when it was posted.

**3. Analyse.** Paste an advert \u2014 or press Analyse on a job you found in step 2.
This is where the score, the verdict and the gap list come from.

**4. Interview Prep.** Paste the same advert to aim the questions at that role,
or leave it blank for a first-round screen on your own skills. Practise in the
box before you look at the suggested answer.

**5. Saved Jobs and Applications.** Save anything worth returning to, and move
an application through draft, sent, interview, and then rejected or offer.

The **Assistant** is not a step. It is available at any point to ask about what
you are looking at, and you can paste an advert into it so its answers are about
that job in particular.

---

## The website

**It is a twelve-page app** — home, your resume, job search, a job analyser,
interview prep, an assistant, saved jobs, your applications and its detail page,
and settings — plus a sign-in and a sign-up page in front of them. There is a
sidebar, a light and dark theme that follows your system setting until you
override it, and a layout that works on a phone.

Every page is wired to the backend. Nothing in the app is a placeholder any more.

**Home** is where you land, and where you upload. It asks for your CV before it
offers you anything else, because everything else depends on it. When one is
already indexed it becomes a short summary of what was read, with the four steps
of the workflow underneath and a **Replace resume** button if you want to swap
it.

**Your resume** is the long version of that summary. It reads your CV on its own,
with no advert involved, and tells you what it says about you: the role it reads
as, your level, the years it states \u2014 or **"Not stated"**, if your CV never gives
a number \u2014 your highest qualification, every skill it can evidence, grouped by
kind, what is working in your favour, what to fix first, and the roles worth
applying for.

Indian degrees are read properly: B.E., B.Tech, BCA, BBA, B.Com, M.E., M.Tech
and MCA all count, alongside the international spellings. If your CV names no
qualification the card says **"Not stated"** rather than inventing one.

**Analyse** is where you upload your CV and paste an advert. You get a score,
a verdict, a breakdown of where the score came from, the skills the advert
asks for that your CV doesn't evidence, suggested rewrites, and a preview of
the interview questions to expect.

Underneath all of that it draws the **agent trace** — the nine steps the system
actually took, in order, each with its timing and a line saying what it
concluded. "Match Calculator: score 32.5/100 → SKIP". "Match Calculator
(re-run): no truthful additions; score unchanged." You can read the reasoning
instead of taking the number on faith, which is the whole point of the thing.

**Job search** runs against the live feeds. **It searches for you the moment you
open it**, using phrases worked out from your own CV, and prints those phrases
underneath the search box — so if it has decided you are a backend developer and
you are not, you can see that and type your own search instead. Either way you
get back real adverts located in India, newest first, from the last seven
days — and a line above the results if there were few or none, saying so rather
than quietly showing you older ones.

Each card shows the skills named in the advert, how hard the job looks, when it
was posted, your match if you've uploaded a CV, and a short **"why this one is
worth your time"** — the skills of yours it already matches, what you'd be
picking up on the job, and the kind of role and level it is. The filter buttons
across the top are the backend's own categories, not bands invented for the
screen, so the counts you see are the counts the scoring actually produced.

If India comes back empty, there's a **Search anywhere instead** button rather
than a silent switch to somewhere else.

Hitting **Analyse** on any advert runs the full pipeline on it and shows the
result in place: your score, the verdict, and the specific things the advert
asks for that your CV doesn't evidence, each with a rough estimate of how long
they'd take to learn.

**Save** keeps an advert on the Saved Jobs page. Saving is one-way — there's no
unsave, so the button turns into a confirmation rather than a toggle that would
lie to you about what it had done.

**Track application** on a saved advert starts tracking an attempt at it, and
drops you on that application's page.

**Interview prep** works with or without an advert. Paste one and the questions
aim at that role. Leave it blank and you get a first-round screen built from
what your CV itself claims — and the page says so, plainly, rather than implying
it knows a job you never told it about.

You do not have to paste anything if the job came from the app. Open a job on
the search page and choose **Prepare for this interview**, and it carries the
advert across for you and names the role it filled in from, so you can see
where the questions are aimed. It is filled in, not submitted: you still press
the button, so a job opened out of curiosity does not spend a model call.

It comes back in the order an interview actually runs. Technical questions with
the reason each is asked and a scaffold for the answer. **Your own projects** —
lines lifted word for word off your resume, each one asking you to walk through
what the hard part was, with a badge on the ones the advert also asks for. The
behavioural round. **On-the-spot scenarios** aimed at the kind of role the
advert describes. **The HR conversation**, kept separate because it is a
different room with a different person in it. What to research about the
company, and questions worth asking them back.

Last comes **where you are thin**: what the advert asks for that your CV does
not evidence, and what to do about each one before the interview. It only names
things that are actually technologies — asked to read an advert that a model
summarised as requiring "backend engineering", an earlier version told the user
to "build one small thing with Backend", which is not an instruction anyone can
follow.

**Assistant** is a chat box. Ask it to summarise your resume, what roles to go
for, what is weak, how to prepare. It is grounded in your CV, and there is a
panel where you can paste a specific advert so the answers are about that job
rather than about your career in general. **Every answer carries a label saying
who wrote it** — "AI-written" if a model did, "Rule-based" if the fixed rules
did. When it cannot answer something without a model, it tells you that rather
than inventing an answer that sounds right.

**My applications** is the list of everything you're tracking. Filter buttons
across the top carry the real counts per status — Draft, Sent, Interview,
Rejected, Offer — so a filter that would show you nothing says so before you
click it. Each card gives the job, the company, where it stands, the match
score, when it was created, and how many things have happened to it.

The four figures above that list come from the backend, not from arithmetic
done in the browser. Your interview rate is interviews divided by applications
*sent* — drafts you never sent don't dilute it — and it arrives with the range
it's actually confident about. One interview from one application is "100%, 95%
confidence: 21%-100%", followed by a sentence telling you that one application
is not a measurement of anything. If you've sent nothing, it reads "Nothing sent
yet", not "0%".

**Opening an application** shows its whole history as a timeline: created,
sent, interview scheduled, offer received, each with its time, what the status
moved from and to, and any detail that was recorded with it. Nothing is
overwritten, so a rejection after an interview keeps both.

You change the status from a dropdown on the same page. The change is appended
to the timeline and the page reloads from the server afterwards, so what you're
reading is what was actually stored rather than an optimistic guess.

If you started tracking an application before running an analysis, the title
and company were never captured — the page says exactly that instead of showing
a blank heading, and the match reads "Not scored".

**Analytics and the dashboard are gone.** Both were pages that summarised other
pages. The dashboard was a set of tiles that restated what My Resume and Job
Search already said, and the analytics page drew funnels and forecasts over a
handful of applications — with, to its credit, a forecast that refused to
predict until it had ten of them. A page whose main feature is declining to
show you anything is a page that did not need to exist. The four figures it was
built around now sit on **My applications**, where the data is.

**The two rates are not the same fraction.** Your interview rate is interviews
over applications *sent*. Your offer rate is offers over *interviews*. The page
says which is which under each one, because a single "success rate" that
quietly changes its denominator is worse than no rate at all.

**Settings** holds the three things there are actually settings for.

Your **resume**: whether one is indexed, how many searchable pieces it was cut
into, a button to add one, and a button to clear it. Clearing asks you to
confirm, because there's no undo and no library of past versions. Note that
uploading a second resume **adds** it to the index rather than replacing the
first — measured, the count went from 8 pieces to 21 — and analyses then score
against both at once. Clear the index first if what you meant was to swap.

Your **theme**: light, dark, or follow the operating system. It's saved in your
browser, and the page tells you which your system is currently resolving to
when you pick that option.

The **backend**: a live health check. Overall status, then each service — the
search index, the language model, the database — with its state, how long it
took to answer, and a note saying what's wrong when something is. The language
model is marked optional because the app genuinely works without one. If the
backend can't be reached at all, the card says so and names the address it
tried.

**And an account section.** It names who you're signed in as, explains that the
server decides that rather than the request, and gives you a Sign out button
that ends the session on the server rather than only in this browser. There is
a second Sign out in the top bar, next to your name, because that is where
most people look for it first.

There's still no change-password, delete-account or notification switch. Those
controls were specified for this page and are left out on purpose: each one
would need an endpoint that doesn't exist, so each would have been a form that
quietly threw away whatever you typed into it — and one of them would have been
asking for a real password.

Every search lists where its results came from. That's not decoration: the job
boards this pulls from ask to be named and linked back to, and honouring that is
a condition of using them.

**The thing worth noticing** is what the app does with a number it doesn't
have. Your interview rate reads "Not enough applications yet" — not "0%". An
advert you haven't been scored against reads "Not scored" — not "0% match". A
scoring category the advert never mentioned reads "Not counted" — not "0/100".
A gap count for an application nobody analysed reads "Not analysed" — not "0
gaps", which would have read as good news. Those mean opposite things: one is
missing information, the other is a measurement of failure. The whole app is
built on that distinction, and it would have been easy to lose it in the last
inch, at the point where a number gets printed on a screen.

That rule now covers the headline score too. Paste a vague advert — one that
describes the team and the culture but never names a skill, a technology, a
number of years or a qualification — and there is genuinely nothing to measure
you against. The app says **"Not scored"** and gives no verdict, rather than
the "0% — SKIP" it used to print above a breakdown whose every row already said
"Not counted". A real 0% is still shown as 0%: ask for ten years of COBOL from
a Python CV and you will get a low number, because that one was measured.

**And it works in the other direction too**, which is the harder half. An
advert can leave out everything about the role and still mention "two years'
experience" — and if the only thing your CV can be compared against is that one
line, matching it produces a *perfect* score from almost no evidence. That is
how a Freelance Copywriter post came top of a search run from an AI/ML CV at
100%, recommended: apply. Two years of anything satisfies a request for two
years. Years, degrees and soft skills are still scored, but a score built out of
nothing else is now withheld rather than published, because it says nothing
about whether this particular job is right for you.

**Type two words and it will not pretend to have read an advert.** "Python
developer" is sixteen characters; it used to come back 100%, "nothing major
standing in the way". Now every route that takes an advert refuses the same
input the same way and tells you it is too short to analyse. On the Interview
Prep page, where the advert box is genuinely optional, it also reminds you that
clearing the box is a valid option — you will get questions from your CV
instead. Typing a little should never be worse than typing nothing.

**One thing to know about uploading.** Your CV goes into a single index, and a
second upload is added to the first rather than replacing it — which would mean
scoring you against a blend of two CVs. The page says so, and gives you a Clear
button, rather than letting you find out from a score that quietly stopped
making sense. PDF, Word `.docx`, `.txt` and `.md` are all accepted; an old
binary `.doc` is not, and it says so and tells you to re-save it rather than
producing nonsense from it.

**There is a login,** and it is a real one. Sign-in and sign-up pages existed
once as decoration and were removed for being decoration; they are back because
there is now something behind them. Passwords are hashed, sessions are held in
a cookie this app's own JavaScript cannot read, and every page behind the
sidebar sends you to sign in if you aren't. Your CV still never leaves your
machine — the accounts live in a file next to the backend, on your own disk.

**Every page has been opened and checked**, not just built: every address loads,
none of them reports an error in the browser's console, and nothing spills off
the side of the screen at phone, tablet or desktop width. Switching the theme
was checked the same way — it changes, it sticks when you move between pages,
and it survives a refresh.

---

## When something looks wrong

**"Your match score is 0."** Either you haven't uploaded a CV yet, or the
advert really does ask for things your CV doesn't show. If the advert was vague
enough that nothing could be measured, you'll see "Not scored" instead of a
number — paste the full posting and try again.

**"The health page says degraded."** That's Ollama not running. Expected, and
everything works.

**"The health page said the database was unhealthy, then said it was fine."**
It was fine both times. If you checked in the first few seconds after starting
the backend, the check could collide with the program still loading itself and
mistake that for a broken database. It now waits a moment and looks again, so
it should not tell you that any more. If it says unhealthy *and keeps saying
it*, that one is real.

**"The answers went back to saying Rule-based, and they used to say
AI-written."** If you're on the free Gemini allowance, you have almost certainly
spent the day's quota. It resets. The backend log says `429` when this is what
happened, and the answer itself will tell you nobody scored it rather than hand
you a made-up mark. Waiting until tomorrow, or switching `GEMINI_MODEL` to a
different model in `backend/.env`, both work — the allowance is counted per
model, not per key.

**"The website loads but says it can't reach the backend."** Start the backend
too — it's a separate terminal, and the website is only a display for it.

**"Port 3000 is already in use."** Something else on your machine has it. Run
`npm run dev -- -p 3100` instead; the backend accepts that address, and 5173,
as well as 3000.

**"It won't let me save a job."** Discovered jobs are held in memory for the
current session. Search again, then save.

**"My interview rate says 0%."** That one is real, not a placeholder — it
means applications have gone out and none has reached an interview yet. Look at
the range underneath it before reading anything into it: after a single
application it says something like "95% confidence: 0%–79%", which is the page
telling you it does not yet know. The rate stays blank only until you have sent
your first application.

**"The first request was slow."** One-off, while it warms up. Everything after
it is fast.

**"It says it needs more data."** The rates and the advice need a real number
of applications behind them before they're worth much. It'd rather say that
than guess.

**"Job search found nothing in India."** Very likely true rather than broken.
The window is seven days and it is a hard limit, so a narrow search on a quiet
week honestly comes back empty. Try a broader term, or use the **Search
anywhere instead** button if you want to see what is out there.

**"There are only three results."** That is the seven-day rule doing its job.
Nothing older is shown, and an advert that never published a date is not shown
either, so the list is short rather than padded.

**"It won't take my CV."** If it's an old binary `.doc`, open it in Word and
save it as `.docx` or PDF. If it's a PDF made from a scan, the text is a picture
and there is nothing to read — export it again with selectable text.

---

## How fast it is

Measured on a laptop, with no AI model running — so these are the fallback paths:

| | |
|---|---|
| Reading a job advert | about 2 milliseconds |
| Reading one it's seen before | under a tenth of a millisecond |
| Scoring you against it | about 1 millisecond |
| The complete analysis, start to finish | about 31 milliseconds |
| Re-uploading a CV you've already uploaded | about 6 milliseconds, and it writes nothing |

Two honest caveats. These are the no-AI numbers; with Ollama running a real
model, the model dominates and everything moves into the seconds. And the app
only keeps one set of working copies for speed — there used to be three, but two
of them had never once been used, so they were removed rather than left on the
status page looking like features.

---

## What's honest about the state of it

The app works and is thoroughly tested — 2,210 automated checks on the backend,
all passing, plus 11 on the website. Four further scripts check the things the
fast suite deliberately can't see: that every real component still imports and
constructs, that real data survives the whole pipeline, that the demo report
still prints, and that all 21 endpoints still answer over a real network
socket. All four pass. But three things are worth saying out loud rather than
burying.

**The main feature of the last fortnight had never once run.** The app's
assembly line was built on a well-known piece of machinery for routing work down
different paths. That machinery had been refusing to start every single time
since the day it was installed, because one of the workstations had been given
the same name as one of the boxes the line carries its paperwork in — and it
won't accept two things with one name.

The uncomfortable part is that nothing looked wrong. A backup arrangement,
written for the case where the machinery was never installed, quietly picked up
the work and walked it down the same path by hand. Same turnings, same answers.
So the results were right, the records were right, and every one of the tests
passed. It was found only by walking up to the machinery and switching it on
directly instead of asking the line whether it was working. It's fixed, and
there's now a test that shouts if anyone makes the same mistake again.

**No coverage percentage is claimed.** The tool that measures how much of the
code the tests actually exercise isn't installed here, and a made-up number
would be worse than no number. For the same reason there is no page-speed score
anywhere in this file: nobody has run the tool that produces one.

**The website's 11 checks are deliberately few.** They cover the two places
this project has actually been bitten — the code that turns a failed request
into a sentence a person can act on, and the health check that used to throw
away its own diagnostic at the exact moment something was broken. Tests that
confirm a button renders its own label would raise the count and prove nothing.

---

## What's coming

**Before any of it can be put online, two things are still missing**, and it's
worth being blunt about them because "ready to deploy" is a claim this app
hasn't earned yet.

Accounts now exist, and the server no longer takes your word for who you are.
But putting it on the public internet needs more than that: HTTPS (the sign-in
cookie only marks itself secure when the app isn't in debug mode), some limit
on how fast someone can guess passwords, and a way to reset a forgotten one.

The website is hard-wired to a backend at `localhost`. Putting the website
online without moving the backend somewhere reachable would give you a site
that loads and then fails on every request.

And almost none of it is committed to version control yet — only the frontend
folder is a repository, and it still contains just the starter files.

**After that:** change-password and delete-account, more job boards — Indian
ones in particular, which is the honest fix for the empty India searches — cover
letters written under the same no-unbacked-claims rule, background job-hunting
that
runs while you're not looking, calendar and email hooks for interview
scheduling, and longer-term trends once there's enough history to justify
them.

---

## For developers

This file is deliberately non-technical. If you want the engineering detail —
the architecture, every design decision and the reasoning behind it, what was
tried and rejected, and the full prompt-by-prompt build log — that's all in
**`README_DEV.md`**.

Released under the MIT License.
