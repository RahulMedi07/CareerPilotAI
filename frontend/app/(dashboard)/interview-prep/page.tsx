'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, FileText, MessageCircleQuestion } from 'lucide-react';

import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { SourceBadge } from '@/components/shared/SourceBadge';
import { PracticeRoom } from '@/components/dashboard/PracticeRoom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { describeApiError, getInterviewPrep } from '@/lib/api';
import { takeJobForInterview } from '@/lib/interview-handoff';
import type { InterviewPrepResult } from '@/types';

export default function InterviewPrepPage() {
  const [advert, setAdvert] = useState('');
  const [result, setResult] = useState<InterviewPrepResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'practice' | 'study'>('practice');
  // Which job was carried over from a search result, if any. Kept only to
  // name it on screen -- the questions come from `advert`.
  const [fromJob, setFromJob] = useState<{ title: string; company: string } | null>(null);

  /*
    An advert handed over from a job card arrives here. Filling the box is all
    this does: the user still presses the button, so a job opened by accident
    does not spend a model call.

    The lint rule below guards against effects that set state derived from
    other state, which cascades renders. This reads sessionStorage -- an
    external store that does not exist during server rendering -- so it cannot
    be done in a lazy `useState` initialiser without the server rendering an
    empty box and the client rendering a full one, which is a hydration
    mismatch. Reading an external system once on mount is what an effect is
    for, and it runs exactly once.
  */
  useEffect(() => {
    const handoff = takeJobForInterview();
    if (!handoff) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    setAdvert(handoff.description);
    setFromJob({ title: handoff.title, company: handoff.company });
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await getInterviewPrep(advert.trim()));
    } catch (err) {
      setError(describeApiError(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const noResume = error?.includes('No resume available') ?? false;

  // The skill questions can come back empty while the rest of the set is full,
  // so the empty notice must not claim nothing was built.
  const otherRoundsBuilt = Boolean(
    result &&
      (result.behavioral_questions.length > 0 ||
        result.hr_questions.length > 0 ||
        result.scenario_questions.length > 0 ||
        result.project_questions.length > 0),
  );

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Interview preparation</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Questions built from your own resume. Open a job from Find Jobs and choose{' '}
          <span className="font-medium">Prepare for this interview</span> to aim them at that
          role, paste an advert below, or leave it blank for a first-round screen on what your CV
          claims.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>The job advert (optional)</CardTitle>
          {fromJob ? (
            <CardDescription>
              Filled in from {fromJob.title}
              {fromJob.company ? ` at ${fromJob.company}` : ''}. Edit it or clear it if you
              want questions from your CV alone.
            </CardDescription>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            value={advert}
            onChange={(event) => {
              setAdvert(event.target.value);
              // Once it has been edited the label no longer describes what is
              // in the box.
              setFromJob(null);
            }}
            placeholder="Paste the job description here, or leave this empty…"
            rows={6}
            aria-label="Job advert"
          />
          <Button onClick={() => void run()} disabled={loading}>
            {loading ? 'Building questions…' : 'Build my questions'}
          </Button>
        </CardContent>
      </Card>

      {loading ? <LoadingSpinner message="Working through your resume…" /> : null}

      {!loading && error ? (
        noResume ? (
          <Card>
            <CardContent className="space-y-4 py-10 text-center">
              <FileText className="mx-auto size-8 text-muted-foreground" aria-hidden />
              <p className="text-sm text-muted-foreground">
                There is no resume to build questions from yet.
              </p>
              <Button asChild>
                <Link href="/settings">
                  Upload your CV
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <ErrorMessage message={error} onRetry={() => void run()} />
        )
      ) : null}

      {!loading && result ? (
        <>
          {/*
            Said out loud rather than implied. Without an advert these are
            questions about the CV, and presenting them as targeted at a role
            the user never named would be the same lie as scoring an advert
            that stated no requirements.
          */}
          {!result.tailored_to_job ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
              No advert was supplied, so these questions are drawn from the skills your own CV
              claims — not from a specific role. Paste an advert above to aim them.
            </p>
          ) : null}

          {/*
            Practice is the default tab, not Study.

            Reading a good answer feels almost exactly like being able to give
            one, and the difference only shows up in the room. Landing on the
            list of questions-with-answers invites reading; landing on a single
            question with an empty box does not.
          */}
          <div className="flex gap-2" role="tablist" aria-label="Preparation mode">
            {(['practice', 'study'] as const).map((value) => (
              <Button
                key={value}
                role="tab"
                aria-selected={mode === value}
                variant={mode === value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setMode(value)}
              >
                {value === 'practice' ? 'Practise' : 'Read the whole set'}
              </Button>
            ))}
          </div>

          {mode === 'practice' ? <PracticeRoom questions={result.questions} /> : null}

          {mode === 'study' ? (
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              {/* "Technical" because this card holds only the skill and gap
                  questions. An unqualified count reads as the whole set, and
                  the rounds below would contradict it. */}
              <CardTitle>
                {result.question_count} technical question{result.question_count === 1 ? '' : 's'}
              </CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant="outline">{result.interview_difficulty}</Badge>
                <SourceBadge source={result.source} />
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {result.questions.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No technical questions could be built: neither the advert nor your CV named a
                  specific technology to ask about.
                  {otherRoundsBuilt
                    ? ' The rounds below were still built from your resume.'
                    : ''}
                </p>
              ) : (
                result.questions.map((question, index) => (
                  <div key={`${question.question}-${index}`} className="rounded-lg border p-4">
                    <div className="flex items-start gap-2">
                      <MessageCircleQuestion
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                        aria-hidden
                      />
                      <p className="text-sm font-medium">{question.question}</p>
                    </div>

                    {question.skill ? (
                      <Badge variant="secondary" className="mt-2">
                        {question.skill}
                      </Badge>
                    ) : null}

                    {question.why_asked ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        <span className="font-medium">Why they ask:</span> {question.why_asked}
                      </p>
                    ) : null}

                    {question.suggested_answer ? (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                          A scaffold for your answer
                        </summary>
                        <p className="mt-1.5 text-xs whitespace-pre-wrap text-muted-foreground">
                          {question.suggested_answer}
                        </p>
                      </details>
                    ) : null}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
          ) : null}

          {/*
            The most personal section on the page, so it comes first. Every
            question here quotes a line from the user's own resume back at
            them, which is exactly what an interviewer does.
          */}
          {result.project_questions.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>About what you have actually built</CardTitle>
                <CardDescription>
                  Taken word for word from your resume. If you cannot talk for two minutes about
                  a line on your CV, that line is a liability.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.project_questions.map((item, index) => (
                  <div key={`${item.question}-${index}`} className="rounded-lg border p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="text-sm font-medium">{item.question}</p>
                      {item.matches_advert ? (
                        <Badge variant="default" className="shrink-0">
                          In the advert
                        </Badge>
                      ) : null}
                    </div>
                    {item.skills && item.skills.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {item.skills.map((skill) => (
                          <Badge key={skill} variant="secondary" className="text-xs">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                    {item.context ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">{item.context}</p>
                    ) : null}
                    {item.suggested_approach ? (
                      <p className="mt-1.5 text-xs whitespace-pre-wrap text-muted-foreground">
                        <span className="font-medium">How to approach it:</span>{' '}
                        {item.suggested_approach}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {result.behavioral_questions.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Behavioural round</CardTitle>
                <CardDescription>
                  These are asked regardless of the stack. Have one real story ready for each.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.behavioral_questions.map((item, index) => (
                  <div key={`${item.question}-${index}`} className="rounded-lg border p-4">
                    <p className="text-sm font-medium">{item.question}</p>
                    {item.context ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">{item.context}</p>
                    ) : null}
                    {item.suggested_approach ? (
                      <p className="mt-1.5 text-xs whitespace-pre-wrap text-muted-foreground">
                        <span className="font-medium">How to approach it:</span>{' '}
                        {item.suggested_approach}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {/*
            Kept apart from the behavioural round on purpose. "Tell me about a
            conflict" and "the service is down at 2am, what do you do" are
            scored by different people looking for different things.
          */}
          {result.scenario_questions.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>If they put you on the spot</CardTitle>
                <CardDescription>
                  Situational questions for your kind of role. Think out loud when you answer
                  these — the reasoning is what is being marked, not the answer.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.scenario_questions.map((item, index) => (
                  <div key={`${item.question}-${index}`} className="rounded-lg border p-4">
                    <p className="text-sm font-medium">{item.question}</p>
                    {item.context ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">{item.context}</p>
                    ) : null}
                    {item.suggested_approach ? (
                      <p className="mt-1.5 text-xs whitespace-pre-wrap text-muted-foreground">
                        <span className="font-medium">How to approach it:</span>{' '}
                        {item.suggested_approach}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {/*
            The round people prepare least and get caught by most. Notice
            period and salary are handled with what is actually normal in
            India rather than generic advice.
          */}
          {result.hr_questions.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>The HR conversation</CardTitle>
                <CardDescription>
                  Nobody rehearses these and everybody is asked them. Have an answer before you
                  are on the call.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.hr_questions.map((item, index) => (
                  <div key={`${item.question}-${index}`} className="rounded-lg border p-4">
                    <p className="text-sm font-medium">{item.question}</p>
                    {item.context ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">{item.context}</p>
                    ) : null}
                    {item.suggested_approach ? (
                      <p className="mt-1.5 text-xs whitespace-pre-wrap text-muted-foreground">
                        <span className="font-medium">How to approach it:</span>{' '}
                        {item.suggested_approach}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {result.company_questions.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Research before you go in</CardTitle>
                <CardDescription>
                  What they will probe, and what to have read beforehand.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.company_questions.map((item, index) => (
                  <div key={`${item.topic}-${index}`} className="rounded-lg border p-4">
                    <p className="text-sm font-medium">{item.topic}</p>
                    {item.suggested_research && item.suggested_research.length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {item.suggested_research.map((line) => (
                          <li key={line} className="flex gap-2 text-xs text-muted-foreground">
                            <span aria-hidden>&bull;</span>
                            <span>{line}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {item.your_angle ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        <span className="font-medium">Your angle:</span> {item.your_angle}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {result.your_questions_for_them.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Ask them these</CardTitle>
                <CardDescription>
                  An interview you ask nothing in reads as an interview you did not want.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3 text-sm">
                  {result.your_questions_for_them.map((item, index) => (
                    <li key={`${item.question}-${index}`} className="flex gap-2">
                      <span aria-hidden className="text-muted-foreground">
                        &bull;
                      </span>
                      <span>
                        {item.question}
                        {item.why_ask ? (
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {item.why_ask}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {/*
            Last, and deliberately so. This is the part that is uncomfortable
            to read, and burying it at the top would make the rest of the page
            feel like a verdict rather than preparation.
          */}
          {result.areas_to_improve.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Where you are thin</CardTitle>
                <CardDescription>
                  Not a rejection. These are the places an interviewer is most likely to push,
                  and each one says what to do about it.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.areas_to_improve.map((item, index) => (
                  <div key={`${item.area}-${index}`} className="rounded-lg border p-4">
                    <p className="text-sm font-medium">{item.area}</p>
                    {item.why ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">{item.why}</p>
                    ) : null}
                    {item.what_to_do ? (
                      <p className="mt-1.5 text-xs text-muted-foreground">
                        <span className="font-medium">What to do:</span> {item.what_to_do}
                      </p>
                    ) : null}
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {result.honesty_note ? (
            <p className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
              {result.honesty_note}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
