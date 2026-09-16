'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Check, FileText, Loader2, Upload } from 'lucide-react';

import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { SourceBadge } from '@/components/shared/SourceBadge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { describeApiError, getResumeInsights, uploadResume } from '@/lib/api';
import type { ResumeInsights } from '@/types';

/** Mirrors `ALLOWED_EXTENSIONS` and `MAX_UPLOAD_SIZE_MB` in `backend/config.py`. */
const ACCEPTED = '.pdf,.docx,.txt,.md';
const MAX_BYTES = 10 * 1024 * 1024;

/**
 * The distinguishing string in the 409 the backend returns when nothing has
 * been indexed. That response is the first-run state, not a fault, and this
 * page is built around telling the two apart.
 */
const NOTHING_UPLOADED = 'No resume available';

/** Never print "0 years" for a CV that simply never gave a number. */
function yearsLabel(years: number | null): string {
  if (years === null || Number.isNaN(years)) return 'Not stated';
  return years === 1 ? '1 year' : `${years} years`;
}

function titleCase(value: string): string {
  if (!value) return 'Unknown';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** The whole app, in the order it is meant to be used. */
const STEPS = [
  { href: '/my-resume', label: 'Read my resume back to me', hint: 'Skills, level and gaps' },
  { href: '/discover-jobs', label: 'Find matching jobs', hint: 'Live openings in India' },
  { href: '/interview-prep', label: 'Prepare for the interview', hint: 'Questions from your CV' },
  { href: '/assistant', label: 'Ask the assistant', hint: 'It has read your resume' },
];

/**
 * The front door, and deliberately the only thing here on a first visit.
 *
 * Nothing else in this app works without a resume: job matching, interview
 * questions and the assistant all read from the same index. A landing page
 * full of empty statistics would let someone wander through four screens
 * before finding that out. So this asks for the CV first and shows nothing
 * else until it has one.
 */
export default function HomePage() {
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);

  const [insights, setInsights] = useState<ResumeInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const reload = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;

    getResumeInsights()
      .then((data) => {
        if (cancelled) return;
        setInsights(data);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(describeApiError(err));
        setInsights(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const name = file.name.toLowerCase();
    if (!ACCEPTED.split(',').some((ext) => name.endsWith(ext.trim()))) {
      setUploadError(`${file.name} is not a .pdf, .docx, .txt or .md file.`);
      event.target.value = '';
      return;
    }

    // Checked here as well as on the server so the reader finds out before a
    // 10MB round trip, not after it.
    if (file.size > MAX_BYTES) {
      setUploadError(`${file.name} is larger than the 10MB limit.`);
      event.target.value = '';
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      await uploadResume(file);
      reload();
    } catch (err) {
      setUploadError(describeApiError(err));
    } finally {
      setUploading(false);
      // Reset the input so re-picking the same file fires a change event.
      event.target.value = '';
    }
  };

  const noResume = Boolean(error && error.includes(NOTHING_UPLOADED));
  const brokenBackend = Boolean(error) && !noResume;

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-3xl py-16">
        <LoadingSpinner message="Checking whether you have uploaded a resume…" />
      </div>
    );
  }

  // A real outage. Distinguished from "nothing uploaded yet" on purpose: one
  // of these is the user's next action, the other is not their fault at all.
  if (brokenBackend) {
    return (
      <div className="mx-auto w-full max-w-3xl py-16">
        <ErrorMessage message={error as string} onRetry={reload} />
      </div>
    );
  }

  if (noResume) {
    return (
      <div className="mx-auto w-full max-w-2xl py-10">
        <div className="text-center">
          <h1 className="text-3xl font-semibold sm:text-4xl">
            <span className="gradient-text">Start with your resume</span>
          </h1>
          <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">
            Everything here reads from your CV — the jobs you are shown, the interview questions
            and the assistant. Upload it once and the rest of the app comes to life.
          </p>
        </div>

        <Card className="mt-8">
          <CardContent className="py-10">
            <label
              htmlFor="home-resume"
              className="flex cursor-pointer flex-col items-center gap-4 rounded-xl border-2 border-dashed border-border px-6 py-12 text-center transition-colors hover:border-primary/60 hover:bg-muted/40"
            >
              {uploading ? (
                <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
              ) : (
                <Upload className="size-8 text-muted-foreground" aria-hidden />
              )}
              <div>
                <p className="font-medium">
                  {uploading ? 'Reading your resume…' : 'Choose your resume'}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  .pdf, .docx, .txt or .md · up to 10MB
                </p>
              </div>
            </label>
            <input
              ref={fileInput}
              id="home-resume"
              type="file"
              accept={ACCEPTED}
              className="sr-only"
              disabled={uploading}
              onChange={handleUpload}
            />

            {uploadError ? (
              <div className="mt-6">
                <ErrorMessage message={uploadError} />
              </div>
            ) : null}
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Your file is parsed on your own machine by the local backend. It is not sent anywhere
          else.
        </p>
      </div>
    );
  }

  if (!insights) return null;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Welcome back</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your resume is loaded. Pick up wherever you left off.
        </p>
      </header>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <CardTitle className="flex items-center gap-2">
            <Check className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />
            Your resume is ready
          </CardTitle>
          <SourceBadge source={insights.source} />
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm leading-relaxed">{insights.headline}</p>

          <dl className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border bg-muted/40 p-3">
              <dt className="text-xs text-muted-foreground">Reads as</dt>
              <dd className="mt-1 text-sm font-medium">{titleCase(insights.primary_role)}</dd>
            </div>
            <div className="rounded-lg border bg-muted/40 p-3">
              <dt className="text-xs text-muted-foreground">Level</dt>
              <dd className="mt-1 text-sm font-medium">{titleCase(insights.seniority)}</dd>
            </div>
            <div className="rounded-lg border bg-muted/40 p-3">
              <dt className="text-xs text-muted-foreground">Experience</dt>
              {/* "Not stated" and "0 years" are different answers. */}
              <dd
                className={
                  insights.experience_years === null
                    ? 'mt-1 text-sm font-medium text-muted-foreground'
                    : 'mt-1 text-sm font-medium'
                }
              >
                {yearsLabel(insights.experience_years)}
              </dd>
            </div>
          </dl>

          {insights.skills.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {insights.skills.slice(0, 12).map((skill) => (
                <Badge key={skill} variant="secondary">
                  {skill}
                </Badge>
              ))}
              {insights.skills.length > 12 ? (
                <Badge variant="outline">+{insights.skills.length - 12} more</Badge>
              ) : null}
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2 pt-1">
            <Button onClick={() => router.push('/discover-jobs')}>
              Find matching jobs
              <ArrowRight className="size-4" aria-hidden />
            </Button>
            <Button variant="outline" onClick={() => fileInput.current?.click()} disabled={uploading}>
              {uploading ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <FileText className="size-4" aria-hidden />
              )}
              {uploading ? 'Reading…' : 'Replace resume'}
            </Button>
          </div>

          <input
            ref={fileInput}
            type="file"
            accept={ACCEPTED}
            className="sr-only"
            disabled={uploading}
            onChange={handleUpload}
          />

          {uploadError ? <ErrorMessage message={uploadError} /> : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        {STEPS.map((step, position) => (
          <Link
            key={step.href}
            href={step.href}
            className="group flex items-start gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-muted/40"
          >
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
              {position + 1}
            </span>
            <span>
              <span className="block text-sm font-medium">{step.label}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{step.hint}</span>
            </span>
            <ArrowRight
              className="ml-auto mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
              aria-hidden
            />
          </Link>
        ))}
      </div>
    </div>
  );
}
