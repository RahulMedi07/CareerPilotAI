# Rahul's README

**A simple guide to what this app does, in plain words.**

---

## What it is

You have a CV. You see a job you like. You wonder: *should I even bother
applying?*

This app answers that. It reads your CV, reads the job advert, and tells you
yes, not yet, or no — and shows you why.

It runs on your own laptop. Nothing is sent anywhere.

---

## What happens, step by step

### 0. You make an account

The very first screen asks you to create one: an email address and a password.
That's all. It takes a few seconds.

It's worth doing rather than resenting, because it's what makes everything
after this *yours*. Your CV, your saved jobs, your applications are tied to
that account, and someone else using the same copy of the app gets their own
set and can't see yours.

If you close the app and come back, it remembers you for a couple of weeks. If
you open a page directly without being signed in, it sends you to the sign-in
screen and then puts you back on the page you were trying to reach, rather than
dumping you on the front page.

### 1. You give it your CV — once

**Once you're signed in, this is the first thing the app asks for.** The front
page has one thing on it: a box to put your CV in. Nothing else works until it
has one, so it doesn't pretend otherwise.

A **PDF** works. A **Word document** (`.docx`) works. A plain text file works.
An old-style `.doc` doesn't — open it in Word and save it again as `.docx` and
it will be fine, and the app tells you that rather than just failing.

You upload it once. You don't upload it again for every job.

The app reads it and remembers what you know: your skills, your tools, your
experience. Once it has, that same front page turns into a short summary of
what it found, plus four numbered links — read my CV, find jobs, prep for the
interview, ask the assistant. That's the whole app, in the order you'd use it.

One thing to watch: if you upload a **second** CV later, it gets **added** to
the first rather than swapping it out, and the app then scores you against both
CVs mixed together. If what you meant was to swap, press "Clear index" on the
Settings page first, then upload the new one. The app used to claim the
opposite — it said uploading replaced the old CV — which was simply wrong, and
the wording has been fixed.

### 1a. It tells you what your CV says about you

Go to **Your resume**. No advert needed. It tells you:

- what kind of job your CV reads as, and what level
- how many years it says you have — or **"Not stated"**, if your CV never puts
  a number on it. It will not guess one, and it will never show you a 0
- your highest qualification. B.E., B.Tech, BCA, BBA, B.Com, M.E., M.Tech and
  MCA are all understood, so an Indian CV isn't read as having no education.
  If your CV names no degree, it says **"Not stated"** rather than making
  something up
- every skill it can actually find, sorted into groups
- what's good about the CV, and what to fix first
- which job titles are worth applying for

This is roughly the picture a recruiter forms in the first ten seconds, before
they compare you to any particular job.

### 2. You give it a job

Three ways:

- **Do nothing.** Open **Find Jobs** and it has already searched, using
  words it worked out from your own CV. It prints those words under the search
  box. If it has read you wrong — it thinks you're a backend developer and
  you're not — you can see that straight away and type your own.
- **Paste an advert in** that you found yourself, or
- **Type your own search** — "AI Engineer" — and it goes and fetches real, live
  adverts from job sites.

Two things about that search:

**It only looks in India,** so there's no country to choose. Most of what it
finds comes straight from Indian companies' own jobs pages — Paytm, Meesho,
CRED, Groww, Postman, Druva and a few more. Those companies put their openings
online for their own website to show, and the app just reads that. On the day
this was written those twelve companies had **354 Indian jobs** between them.

You might wonder why LinkedIn, Indeed, Naukri, Foundit and Wellfound aren't in
there. It's not laziness — none of them allow it. LinkedIn and Indeed have
rules that specifically forbid a program reading their listings, and Naukri,
Foundit and Wellfound don't publish anything a program can read. So the app
uses the companies themselves instead, which gets you the same jobs from the
source.

**There is one way to get a lot of those jobs anyway, and it's allowed.**
Those big sites sell their listings on to companies whose whole job is
passing them along. Adzuna is one of them. Because Adzuna is *allowed* to
hand the jobs out, the app can just ask it — no sneaking around. You get the
job in the app, with a link straight to it, same as everything else.

It's free, but you have to switch it on once:

1. Go to <https://developer.adzuna.com> and sign up. Takes a minute.
2. They give you an **Application ID** and an **Application Key**.
3. Open `backend/.env` and paste them in:

   ```
   ADZUNA_APP_ID=paste-the-id-here
   ADZUNA_APP_KEY=paste-the-key-here
   ```

4. Restart the backend.

After that, every search also asks Adzuna for Indian jobs posted in the last
seven days. If you never do this, nothing goes wrong — the app just carries
on without that one source.

**And you still get to those closed sites in one click.** Under every search
there's a
row of buttons — LinkedIn, Naukri, Indeed, Foundit, Wellfound — and pressing
one opens that same search on that site, set to India and the last seven days
where the site allows it. Only your search words go across. You land there
logged in as yourself, which is the normal way to use those sites, and the one
thing a program isn't allowed to do on your behalf.

If a search still comes back empty, you get a button saying **"Search anywhere
instead"** — offered, not done for you, because quietly showing you jobs in
London under a heading that says India would be worse.

**Every job has an "Apply" button that goes to the real posting.** For a while
the jobs found on Hacker News went to the discussion page instead — somewhere
to read about the job, not somewhere to apply for it. They now go to the
company's own careers page, which was written in the advert all along.

**It only shows jobs posted in the last 7 days,** newest first. That's a hard
rule, not a preference. Nothing older gets through, and if an advert never said
when it was posted, it doesn't get shown either — "we don't know how old this
is" isn't the same as "it's recent". So the list is sometimes short, or even
empty, and when that happens the page says so at the top instead of quietly
reaching back a month to look busier. Every job card shows its own posted date.

### 2a. Each job tells you why it's worth your time

Under every job there's a short **"why this one is worth your time"**:

- which of your skills it already asks for — named, not just counted
- what you'd be learning on the job
- what kind of role it is and what level it's pitched at

All of that is read straight off the comparison it already did, so you can check
any line of it against your own CV in a few seconds. And it puts the bad news
next to the good news. A list of reasons to apply with the reasons *not* to left
out is an advert, not advice — and you're the one who'd be sitting in the
interview being asked about the half it left out.

### 3. It reads the advert

It works out what the job really needs, what's just nice to have, and how
senior it is.

### 4. It scores you

You get a number out of 100.

But the number on its own is useless, so it also shows you **the proof**. If it
says you know Python, it shows you the exact line on your CV that says so. You
can check its working.

Sometimes you get no number at all, and that's on purpose. If the advert is all
waffle — "join our passionate team, own things end to end" — and never names a
single skill, tool, or number of years, then there is nothing to compare your CV
against. It says **"Not scored"** and leaves it there. It used to say "0%" and
"skip this one", which read like *you* were the problem when really the advert
was. A 0% you actually earn — they want ten years of COBOL and you've never
touched it — is still shown as 0%.

The same thing happens the other way round, and that one's sneakier. Say an
advert says nothing about the actual job but does say "two years' experience".
You've got two years. That's a perfect match — on the only thing it could
check. A copywriting job once came top of a search at **100%, apply now**, off
an AI/ML CV, purely because of that. Two years of anything is two years. So now,
if the only things it could measure were years, a degree and soft skills, it
doesn't publish a number at all. Those things don't tell you whether *this* job
is right for you.

And if you only type a couple of words into the box — "Python developer" — it
tells you that's too short to read, instead of scoring it. It used to say 100%
and "nothing major standing in the way", off sixteen characters.

### 5. It tells you what's missing

Not just a list. It splits them in two:

- **Things that will stop you** getting an interview
- **Things that won't really matter**

And for each one, roughly how long it would take you to learn.

### 6. It decides

This is the useful bit. You get one of three answers:

- **Apply now** — you're a good fit, go for it
- **Learn a bit first** — you're close, and the gaps are small enough to close
  in a couple of weeks
- **Skip this one** — the gaps are too big, save your time

And a fourth non-answer: **no verdict**, when the advert gave it nothing to go
on. Better than a confident guess.

### 7. It rewrites your CV for that job

Reworded bullet points. Better keywords. Tailored to that one advert.

### 8. It makes you a study plan — but only sometimes

If your gaps could be closed in about two weeks, you get a day-by-day plan.

If they'd take three months, you don't get one. Because the job won't wait
three months for you, and a plan you can't finish in time is just noise.

### 9. It gets you ready for the interview

It writes you practice questions. Most of them are about your **weak spots**,
because that's where the hard questions come from.

You don't need an advert for this. Open **Interview Prep** and press the button
with the box empty, and it builds a first-round screen out of what your own CV
claims. It puts a note at the top saying the questions aren't aimed at any
particular job, because they aren't.

And if the job came from the app, you don't have to copy anything. Open a job
on the search page and press **"Prepare for this interview"** — it carries the
advert over for you and says which job it filled in from. It fills the box in
but doesn't press the button, so opening a job to have a look doesn't cost you
anything.

You get the whole interview, in the order it actually happens:

- **Technical questions**, with the reason each one gets asked
- **About what you have actually built** — it takes lines straight off your
  resume, word for word, and asks you to walk through them. Not made up, not
  reworded: your own sentence, quoted back. If you can't talk for two minutes
  about a line on your CV, that line is a liability, and it's much better to
  find that out now than in the room. Lines the advert also cares about get a
  little badge on them so you know which to rehearse first.
- **The behavioural round** — tell me about a time when…
- **If they put you on the spot** — awkward what-would-you-do scenarios, picked
  to suit the kind of job the advert describes
- **The HR conversation** — why are you leaving, what are you looking for, what
  are your salary expectations. Kept in its own section because it's a different
  room with a different person in it, and the answers work differently.
- **What to research about the company**, and **questions worth asking them back**
- **Where you are thin** — last, and the honest one

That last section lists what the advert wants that your CV doesn't show, and
what to do about each one before the interview. It only names real technologies.
At one point it told a user to "build one small thing with Backend before the
interview", because the AI had summarised a job advert as needing "backend
engineering" instead of listing Python, FastAPI, Kubernetes and PostgreSQL like
the advert actually did. "Backend" isn't a thing you can go and build. That's
fixed — it now checks that a gap is an actual named tool before suggesting you
go and learn it, and if the AI hands back a vague answer like that it throws it
away and reads the advert itself instead.

### 9a. You can just ask it things

There's an **Assistant** page. Type a question about your CV — what should I
apply for, what's weak, how do I prepare — and it answers using what's in your
resume.

There's also a little panel on that page saying **"Asking about a specific
job?"**. Open it, paste the advert in, and from then on its answers are about
*that* job rather than about your career in general — so "am I a fit?" gets a
real answer instead of a shrug.

Every answer has a small label on it saying **who wrote it**: "AI-written" if a
real AI model did, "Rule-based" if it came from the app's own fixed rules. Out
of the box there's no AI model set up, so everything says "Rule-based", and the
answers themselves say so too. That's on purpose. An app that dresses up a
lookup table as artificial intelligence is lying to you about the one thing you'd
want to know.

If you want the real thing, put an Anthropic API key in `backend/.env` and
restart it. The labels will change on their own.

### 9b. You practise, instead of just reading

This is the part that actually helps.

The page opens on **Practise**, which shows you **one question at a time and an
empty box**. You type your answer first. The suggested answer is hidden behind a
button until you ask for it.

That order is deliberate. Reading a good answer feels almost exactly like being
able to give one. The difference only turns up when someone is looking at you
and waiting, and by then it's too late to find out.

When you've written something, press **Get feedback**. It tells you things you
can check yourself:

- how many words you wrote, and whether that's too short to say anything
- whether you named an actual number, or just said it went well
- which hedging words you used — it quotes them back at you: "sort of", "I guess"
- whether you ever actually mentioned the thing you were asked about

If you've set up an AI key, it also gives you a **mark out of ten** and tells you
what was strong and what was missing.

If you haven't, it says **"Not scored"**. It does not give you a five out of ten
to fill the space. Nothing read your answer, so nothing is qualified to mark it,
and saying so is more useful than a number someone made up.

There's also **Explain more** on every question, which tells you what the
interviewer is really testing when they ask it.

If you'd rather read the whole set at once, press **Read the whole set** at the
top.

### 10. You apply, and it keeps track

Save the job. Mark it as applied. Then update it as things happen: interview,
rejected, offer.

It remembers the dates, not just the status. So it can tell you things like
"replies usually take about a week, so silence before then means nothing yet."

### 11. It tells you how your hunt is really going

On the **Applications** page there are four figures at the top: how many you're
tracking, how many you actually sent, your interview rate and your offer rate.

There used to be a whole separate **Analytics** page with funnels and pie charts
and a forecast, and a **Dashboard** page of tiles. Both are gone. They were
pages that summarised other pages, and the forecast mostly refused to forecast
anyway. The numbers that mattered moved to the applications list, where the
actual data is.

---

## The important part: it won't lie to you

This is the main thing that makes it different. Most CV tools try to make you
feel good. This one tries to be right.

**It won't add skills you don't have.** The easy way to make your score jump is
to stuff your CV with every word from the advert. We tested it. Doing it
honestly moved the score from 73.6 to 73.6 — no change. Letting it add three
skills the person didn't actually have took it to 93.7.

So that whole 20-point "improvement" was made of lies. And you'd have to sit in
the interview and defend them. It won't do it.

**It won't guess your success rate from tiny numbers.** Sent 3 applications and
got 1 interview? That is not a "33% success rate". That's 3 applications. Below
5, it says nothing at all.

**It won't invent a salary.** Most adverts don't say. It leaves it blank instead
of guessing, because you'd be the one negotiating against a made-up number.

**It won't make up links.** Every study link it gives you was actually opened
and checked by a human.

**It won't guess how long you've worked.** If your CV doesn't say, the app says
"Not stated". Not "0 years". Those are different facts, and a 0 on the screen is
something you'd then have to argue your way out of.

**It won't pretend to be an AI when it isn't.** If no AI model is set up, it
tells you that, in the answer, every time.

**And it won't pretend the AI answered when the AI didn't.** The free Google
allowance is a daily one, and it's small — you get a couple of dozen goes, and
one full job analysis uses about six of them. When you run out, the AI goes
quiet until tomorrow. That's not a bug and nothing has broken. What matters is
what happens next: the app doesn't quietly hand you a rule-based answer dressed
up as a judgement. It says the model couldn't be reached, that nobody scored
what you wrote, and that what follows is a list of what is and isn't in your
answer rather than an opinion on how good it was. A silent downgrade would be
worse than no answer, because you'd trust it.

**It won't count something it never looked at.** On the page for a single
application there's a box saying how many skill gaps it found. If you added the
application by hand without running the analysis first, it used to say **0** —
which reads as "good news, no gaps", when the truth was "nobody checked". It now
says *Not analysed*, the same way the score next to it already said *Not
scored*. A zero and a blank are different facts, and only one of them is
something you can act on.

**It won't apply to jobs for you.** It could. But then your "interview rate"
would be based on 20 applications you never really sent, and the number it shows
you would be a lie.

**And it shouldn't scare you about your own data.** There was a status page
inside the app that once said the database had failed. It hadn't — the app was
just still starting up, and the check mistook "still loading" for "broken". It
now waits a second and looks again before saying anything that alarming. A
warning you learn to ignore is worse than no warning, because the day it's real
you'll ignore that one too.

**And it shouldn't call something a perfect match when it can barely read it.**
One job came back as a 100% match. It wasn't. The advert was written in German,
the app could only make out a single word it recognised — "python" — and you
have Python, so one out of one is a hundred percent. Technically true, and
completely useless.

Two things changed. That number is now grey instead of green, with a line under
it saying little of the advert could be read. And the filter at the top of the
page no longer counts it under "Perfect match", which is the bit that nearly
slipped through — the card had been made honest while the label above it was
still making the same promise.

**And it shouldn't leak your keys when you share it.** If you zip this folder
and send it to someone, the obvious way is wrong twice. It's 1.8 GB, nearly all
of it stuff their computer would rebuild anyway — and it contains the file with
your Gemini key and your job-search keys sitting in plain text, plus your CV and
every application you've tracked. A zip gets forwarded. Keys don't come back.

The README now has a "Sending it to someone else" section with the exact
command that leaves all of that out. It comes to about 1.2 MB. I tested it by
actually unzipping it somewhere else and starting it from nothing, which is how
I found the next thing.

**One test only passed on this laptop.** The checks that prove the app works
were quietly reading a settings file that only exists on my machine. On a fresh
copy one of them failed — not because anything was broken, but because the test
was leaning on something that wasn't in the box. It now ignores that file, so
the result is the same wherever you run it. Worth knowing: a test that passes
only where it was written isn't really a test yet.

**One thing to say when you send it.** The app runs with no keys at all, but
job searching will find about two adverts instead of a dozen or more. That's
the missing job-board key, not a broken app, and the page says so — but tell
them, so their first impression isn't an empty screen.

---

## Your data

Everything stays on your laptop. Your CV is not uploaded to anyone.

There's a "clear everything" button, and it really does clear everything —
including the hidden copies the app keeps to run faster. A delete button that
leaves copies behind isn't a delete button.

You now sign in, and what you see is yours. Someone else can use the same copy
of the app and get their own resume, their own saved jobs, their own
applications — and neither of you can see the other's.

The part worth understanding is *why* that holds. Before, the app asked the
question "who are you?" in the request itself, which is like a bank asking
which account you'd like to look at and then just showing it to you. Now the
server works out who you are from your sign-in and ignores anything the request
claims about it. Your CV goes further still: each account's resume is kept in a
separate box, so if the code ever looked in the wrong box it would find nothing
rather than finding your CV in someone else's hands. Coming back empty is a bug
you notice; showing the wrong person's CV is one you don't.

Your password isn't stored anywhere, not even scrambled-and-reversible. What's
kept is a one-way fingerprint of it, made deliberately slow so that guessing
millions of passwords against the file would take an unreasonable amount of
time. Signing out doesn't just forget you in this browser — it cancels the
session on the server, so a session left open on a borrowed laptop actually
stops working.

One thing to be careful about: **there's no "forgot password".** If you lose
it, that account and its data are gone. Pick something you'll remember.

---

## What it can't do yet

Being straight about this:

- **No password reset, no password change, no delete account.** Three things a
  real app would have. They're missing because each needs machinery that isn't
  built, and the settings page says so instead of showing you a form that
  throws away what you type. Login itself is real now.
- **It only exists on this computer.** Nearly none of it has been saved into
  the system programmers use to keep a history of their work, which means
  there's no backup and no way to undo a bad day. Nothing is lost yet, but a
  disk failure would take the lot. This is the first thing that needs fixing —
  before any of the clever features.
- **It can't go on the internet yet.** The website is wired to a program
  running on your own machine. Put the website online as it stands and it would
  load perfectly and then fail on every single click, because it would still be
  looking for that program on the visitor's computer instead of yours. Putting
  it online properly means finding a home for the behind-the-scenes half first.
- **The website is mostly wired.** There is a proper website now, with a
  sidebar, a dark mode, a front page that asks for your CV before anything else,
  a page where you paste a job advert to get a full answer, a job search that
  finds real adverts and scores them, an interview prep page, an assistant, a
  page for the jobs you keep, a page listing every application you're tracking
  with the full story of what happened to each, and a settings page. Every one
  of them does something real.
- **The settings page tells you who you're signed in as.** It names your
  account, explains that the server decides that rather than the request, and
  gives you a Sign out button that really ends the session. There's a second
  one in the bar across the top, next to your name, since that's where people
  look first. What it still
  doesn't have is a change-password or delete-account form — because those need
  machinery that doesn't exist, and a form that silently discards a new
  password is worse than no form. What it does have is real: swap or delete
  your CV, pick your theme, and a live check on whether the backend and its
  parts are actually working.
- **It keeps the whole history.** Open an application and you see when it was
  created, when it went out, when the interview got booked, and what changed at
  each step. Nothing gets overwritten, so a rejection after an interview still
  shows the interview.
- **It won't fake your interview rate.** If you've applied to nothing, it says
  "nothing sent yet" instead of "0%". If you've applied to one thing and got an
  interview, it says 100% and then immediately tells you one application isn't
  a measurement of anything.
- **Every page has actually been opened.** All twelve of them load, none of
  them complains in the background, and none of them runs off the edge of a
  phone screen. That was checked by opening them, not by assuming.
- **It has been checked with the engine switched off.** The app was loaded
  with its backend deliberately stopped. Every page said "Could not reach the
  backend — is it running?" and offered a Try again button. Nothing crashed,
  nothing showed a made-up zero, and nothing pretended you had been signed out.
- **Two people have been sat side by side and checked.** Two accounts, two
  completely different CVs, both asking for a full report on the same advert.
  Each got a report about their own CV. That check exists because the app once
  got it wrong — see below.
- **The behind-the-scenes half is checked four different ways.** There are
  2,512 quick automatic checks, and then four slower ones that do what the
  quick ones can't: build the real thing rather than a stand-in, push a real CV
  and a real advert all the way through, print the demo report, and talk to all
  21 of the app's own addresses over a real connection. All of them pass.
- **The whole thing gets used, not just tested.** The last check ran thirty real
  adverts through it, opened every page, and read the server's own log. That
  turned up six things the automatic checks couldn't see: a copywriting job
  scoring 100%, one of the four job boards quietly failing on every search, the
  ordinary word "rest" being read as the REST API skill, jobs it couldn't score
  being shown as "0%", a short advert crashing the interview page, and two words
  being scored as a perfect match. All six are fixed. Passing your own tests
  isn't the same as working.
- **It won't sell you a job it couldn't actually read.** One job card said "the
  advert didn't list its skills clearly enough to compare" and then, four lines
  below, "this is one of the closest matches found". Both can't be true. It no
  longer claims a close match when there was nothing to compare. It also stopped
  printing "the advert is pitched at unknown level", which is a blank dressed up
  as a fact.
- **It once mixed two people up, and that's fixed.** For a while, the very
  first person to ask for a full report after the server started had their CV
  quietly stuck to the machinery. Everyone who asked afterwards got a report
  written about *that* CV, with their own name on it. Nobody had noticed
  because that one report is the slowest thing the app does, so it was the one
  step never checked by hand. Everyone now gets their own machinery, and there
  is a check that fails loudly if that ever stops being true. The honest lesson:
  the thing you skip because it's slow is the thing nobody has ever tested.
- **You can see it think.** The analysis page draws all nine steps it took, in
  order, with what each one worked out. If you don't trust the score, you can
  read the reasoning instead of arguing with a number.
- **It needs a bit of history.** The advice about your job hunt needs around 20
  applications before it's really worth listening to. It'll tell you that
  rather than guess.

---

## What it looks like

The app was restyled: warm off-white paper instead of flat grey, a deep green
for buttons instead of the blue-and-purple gradient, and ordinary type — the
fonts already on your machine, with a serif for page titles. The bright
"techy" gradient on every heading is gone.

Nothing about how it *works* changed with that — same pages, same buttons, same
answers. It's paint, not plumbing.

One small thing that was genuinely broken got fixed on the way: the orange
"maybe" badge was pale orange with white text on it, which is close to
unreadable. It's a darker ochre now, and every colour in the app has been
measured against the background it sits on so the text is legible.

---

## In one line

**It reads your CV and a job advert, tells you honestly whether to apply, and
shows you exactly why it thinks so.**
