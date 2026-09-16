'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowUp, Bot, User } from 'lucide-react';

import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { SourceBadge } from '@/components/shared/SourceBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { describeApiError, sendChatMessage } from '@/lib/api';
import type { ChatMessage } from '@/types';

/** A reply plus the label saying who wrote it. */
interface Turn extends ChatMessage {
  source?: string;
}

const OPENERS = [
  'Summarise my resume',
  'What roles should I apply for?',
  'What is weak in my CV?',
  'How should I prepare for an interview?',
];

export default function AssistantPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumeMissing, setResumeMissing] = useState(false);

  /*
    The advert the user is asking about, held here in the page rather than on
    the server.

    A server-side "currently selected job" would be one piece of state that
    two open tabs could disagree about, and the disagreement would surface as
    the assistant answering about the wrong role with no way to tell. Pasting
    the text means what the model was given is exactly what is on screen.
  */
  const [jobTitle, setJobTitle] = useState('');
  const [jobDescription, setJobDescription] = useState('');

  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, sending]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || sending) return;

    // The transcript sent to the server is the one *before* this message,
    // because the message itself travels in its own field. Appending first
    // and then sending the whole array would duplicate the question.
    const priorHistory: ChatMessage[] = turns.map(({ role, content }) => ({ role, content }));

    setTurns((prev) => [...prev, { role: 'user', content: message }]);
    setDraft('');
    setSending(true);
    setError(null);

    try {
      const reply = await sendChatMessage(message, priorHistory, {
        title: jobTitle.trim(),
        description: jobDescription.trim(),
      });
      setResumeMissing(!reply.resume_available);
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', content: reply.reply, source: reply.source },
      ]);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Ask about your career</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Grounded in the CV you have uploaded, and in the advert you paste below if you paste
          one. Every answer is labelled with who wrote it — a model, or the fixed rules that run
          when no model is configured.
        </p>
      </header>

      {/*
        Collapsed by default. Most questions are about the CV alone, and an
        empty textarea sitting above the conversation would imply the
        assistant needs one before it can be useful.
      */}
      <details className="rounded-lg border bg-card p-4">
        <summary className="cursor-pointer text-sm font-medium">
          Asking about a specific job?
          {jobDescription.trim() ? (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {jobTitle.trim() || 'Advert attached'}
            </span>
          ) : (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              Paste the advert and answers will use it
            </span>
          )}
        </summary>

        <div className="mt-4 space-y-3">
          <Input
            placeholder="Job title, e.g. Backend Engineer at Acme"
            value={jobTitle}
            onChange={(event) => setJobTitle(event.target.value)}
            aria-label="Job title"
          />
          <Textarea
            placeholder="Paste the job description here…"
            value={jobDescription}
            onChange={(event) => setJobDescription(event.target.value)}
            rows={6}
            aria-label="Job description"
          />
          {jobDescription.trim() ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setJobTitle('');
                setJobDescription('');
              }}
            >
              Clear the advert
            </Button>
          ) : null}
        </div>
      </details>

      {resumeMissing ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
          You have not uploaded a resume yet, so there is nothing for the assistant to read.{' '}
          <Link href="/" className="font-medium underline underline-offset-2">
            Upload one to get started.
          </Link>
        </p>
      ) : null}

      <div className="min-h-[22rem] space-y-4 rounded-lg border bg-card p-4">
        {turns.length === 0 ? (
          <div className="space-y-4 py-8 text-center">
            <Bot className="mx-auto size-8 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              Ask anything about your resume. These four work without a model configured:
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {OPENERS.map((opener) => (
                <Button
                  key={opener}
                  variant="outline"
                  size="sm"
                  onClick={() => void send(opener)}
                  disabled={sending}
                >
                  {opener}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        {turns.map((turn, index) => (
          <div
            // Index is a safe key here: turns are only ever appended, never
            // reordered or removed, so a given position keeps its message.
            key={`${turn.role}-${index}`}
            className={cn('flex gap-3', turn.role === 'user' ? 'justify-end' : 'justify-start')}
          >
            {turn.role === 'assistant' ? (
              <Bot className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : null}

            <div
              className={cn(
                'max-w-[80%] space-y-1.5 rounded-lg px-3 py-2 text-sm',
                turn.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
              )}
            >
              <p className="whitespace-pre-wrap leading-relaxed">{turn.content}</p>
              {turn.role === 'assistant' && turn.source ? (
                <SourceBadge source={turn.source} />
              ) : null}
            </div>

            {turn.role === 'user' ? (
              <User className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : null}
          </div>
        ))}

        {sending ? (
          <p className="text-sm text-muted-foreground" role="status">
            Thinking…
          </p>
        ) : null}

        <div ref={endRef} />
      </div>

      {error ? <ErrorMessage message={error} /> : null}

      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about your resume…"
          aria-label="Your question"
          maxLength={2000}
          disabled={sending}
        />
        <Button type="submit" disabled={sending || !draft.trim()} aria-label="Send">
          <ArrowUp className="size-4" aria-hidden />
        </Button>
      </form>
    </div>
  );
}
