'use client';

import { useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Lightbulb,
  Loader2,
  MessageCircleQuestion,
  Sparkles,
} from 'lucide-react';

import { SourceBadge } from '@/components/shared/SourceBadge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import { describeApiError, getPracticeFeedback, sendChatMessage } from '@/lib/api';
import type { InterviewQuestion, PracticeFeedback } from '@/types';

interface PracticeRoomProps {
  questions: InterviewQuestion[];
}

/**
 * One question at a time, with the answer hidden until asked for.
 *
 * A list of twelve questions with twelve model answers printed underneath is
 * a document, not practice. Reading a good answer feels like knowing it. The
 * only part of this that does any work is the gap between being asked and
 * being shown, so the answer stays behind a button and the box for your own
 * attempt comes first.
 */
export function PracticeRoom({ questions }: PracticeRoomProps) {
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});
  const [practised, setPractised] = useState<Record<number, boolean>>({});

  const [draft, setDraft] = useState('');
  const [feedback, setFeedback] = useState<PracticeFeedback | null>(null);
  const [checking, setChecking] = useState(false);

  const [deeper, setDeeper] = useState('');
  const [deeperSource, setDeeperSource] = useState('');
  const [explaining, setExplaining] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const total = questions.length;
  const question = questions[index];
  const doneCount = Object.values(practised).filter(Boolean).length;

  // Everything below the question is about *this* question. Carrying a
  // previous answer's feedback onto the next one would be worse than showing
  // nothing, so moving between questions clears it.
  const goTo = (next: number) => {
    setIndex(next);
    setDraft('');
    setFeedback(null);
    setDeeper('');
    setDeeperSource('');
    setError(null);
  };

  const handleCheck = async () => {
    if (!draft.trim()) return;
    setChecking(true);
    setError(null);
    try {
      setFeedback(
        await getPracticeFeedback(question.question, draft.trim(), question.skill ?? ''),
      );
      setPractised((prev) => ({ ...prev, [index]: true }));
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setChecking(false);
    }
  };

  const handleExplain = async () => {
    setExplaining(true);
    setError(null);
    try {
      const reply = await sendChatMessage(
        `In an interview I have been asked: "${question.question}". ` +
          `Explain what the interviewer is really testing, and what a strong answer covers.`,
      );
      setDeeper(reply.reply);
      setDeeperSource(reply.source);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setExplaining(false);
    }
  };

  if (total === 0 || !question) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          There are no questions to practise yet.
        </CardContent>
      </Card>
    );
  }

  const isRevealed = revealed[index] ?? false;
  const followUps = Array.isArray(question.follow_ups) ? (question.follow_ups as string[]) : [];

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            Question {index + 1} of {total}
          </span>
          <span className="text-muted-foreground">
            {doneCount} practised
            {/*
              Deliberately not a percentage. "58% ready" is a number nothing
              measured; the count of questions you have attempted is a fact.
            */}
          </span>
        </div>
        <Progress value={((index + 1) / total) * 100} />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start gap-2">
            <MessageCircleQuestion
              className="mt-0.5 size-5 shrink-0 text-muted-foreground"
              aria-hidden
            />
            <CardTitle className="text-base leading-snug">{question.question}</CardTitle>
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {question.skill ? <Badge variant="secondary">{question.skill}</Badge> : null}
            {question.category ? <Badge variant="outline">{question.category}</Badge> : null}
            {practised[index] ? (
              <Badge variant="outline" className="gap-1">
                <Check className="size-3" aria-hidden />
                Practised
              </Badge>
            ) : null}
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {question.why_asked ? (
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Why they ask:</span>{' '}
              {question.why_asked}
            </p>
          ) : null}

          <div className="space-y-2">
            <label htmlFor="practice-answer" className="text-sm font-medium">
              Your answer
            </label>
            <Textarea
              id="practice-answer"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Say it the way you would say it out loud…"
              rows={6}
            />
            <div className="flex flex-wrap gap-2">
              <Button onClick={handleCheck} disabled={checking || !draft.trim()}>
                {checking ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="size-4" aria-hidden />
                )}
                {checking ? 'Reading it…' : 'Get feedback'}
              </Button>
              <Button
                variant="outline"
                onClick={() => setRevealed((prev) => ({ ...prev, [index]: !isRevealed }))}
              >
                {isRevealed ? (
                  <EyeOff className="size-4" aria-hidden />
                ) : (
                  <Eye className="size-4" aria-hidden />
                )}
                {isRevealed ? 'Hide the scaffold' : 'Show a scaffold'}
              </Button>
              <Button variant="outline" onClick={handleExplain} disabled={explaining}>
                {explaining ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Lightbulb className="size-4" aria-hidden />
                )}
                Explain more
              </Button>
            </div>
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          {feedback ? <FeedbackPanel feedback={feedback} /> : null}

          {isRevealed && question.suggested_answer ? (
            <div className="rounded-lg border bg-muted/40 p-4">
              <p className="text-xs font-medium">A scaffold, not a script</p>
              <p className="mt-1.5 text-sm whitespace-pre-wrap text-muted-foreground">
                {question.suggested_answer}
              </p>
            </div>
          ) : null}

          {deeper ? (
            <div className="rounded-lg border p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium">What they are really testing</p>
                <SourceBadge source={deeperSource} />
              </div>
              <p className="mt-1.5 text-sm whitespace-pre-wrap text-muted-foreground">{deeper}</p>
            </div>
          ) : null}

          {followUps.length > 0 ? (
            <div className="rounded-lg border border-dashed p-4">
              <p className="text-xs font-medium">They might follow up with</p>
              <ul className="mt-1.5 space-y-1">
                {followUps.map((item) => (
                  <li key={item} className="flex gap-2 text-sm text-muted-foreground">
                    <span aria-hidden>&bull;</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => goTo(index - 1)} disabled={index === 0}>
          <ArrowLeft className="size-4" aria-hidden />
          Previous
        </Button>
        <Button variant="outline" onClick={() => goTo(index + 1)} disabled={index >= total - 1}>
          Next question
          <ArrowRight className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

/**
 * Render the coach's reply.
 *
 * The score is the delicate part. `null` means nothing read the answer, and it
 * is shown as "Not scored" with the reason, rather than being hidden — a
 * missing score that is silently omitted looks like a rendering bug, but a
 * missing score that explains itself is information.
 */
function FeedbackPanel({ feedback }: { feedback: PracticeFeedback }) {
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium">
            {feedback.score === null ? 'Not scored' : `${feedback.score} / 10`}
          </span>
          {feedback.verdict ? (
            <span className="text-sm text-muted-foreground">{feedback.verdict}</span>
          ) : null}
        </div>
        <SourceBadge source={feedback.source} />
      </div>

      {feedback.note ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
          {feedback.note}
        </p>
      ) : null}

      {feedback.strengths.length > 0 ? (
        <FeedbackList title="What worked" items={feedback.strengths} />
      ) : null}
      {feedback.gaps.length > 0 ? (
        <FeedbackList title="What it left out" items={feedback.gaps} />
      ) : null}
      {feedback.observations.length > 0 ? (
        <FeedbackList title="About what you wrote" items={feedback.observations} />
      ) : null}

      {feedback.improved_opening ? (
        <div>
          <p className="text-xs font-medium">A stronger opening</p>
          <p className="mt-1 text-sm whitespace-pre-wrap text-muted-foreground">
            {feedback.improved_opening}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function FeedbackList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium">{title}</p>
      <ul className="mt-1 space-y-1">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-sm text-muted-foreground">
            <span aria-hidden>&bull;</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
