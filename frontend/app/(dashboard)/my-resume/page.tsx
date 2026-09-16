'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, FileText, Lightbulb, MessageSquare, RefreshCw } from 'lucide-react';

import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { SourceBadge } from '@/components/shared/SourceBadge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { describeApiError, getResumeInsights } from '@/lib/api';
import type { ResumeInsights } from '@/types';

/**
 * Render a stated duration, or say plainly that it was never stated.
 *
 * The one thing this must never do is print "0". `null` here means the CV
 * does not mention a number of years, which is a different fact from having
 * none of them, and a 0 on screen is a claim the candidate has to argue with.
 */
function yearsLabel(years: number | null): string {
  if (years === null || Number.isNaN(years)) return 'Not stated';
  return years === 1 ? '1 year' : `${years} years`;
}

function titleCase(value: string): string {
  if (!value) return 'Unknown';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function MyResumePage() {
  const [insights, setInsights] = useState<ResumeInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // `loading` is raised by whoever triggers the fetch, not inside the effect.
  // Setting state synchronously in an effect body causes a cascading render
  // and is rejected by react-hooks/set-state-in-effect.
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

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold sm:text-3xl">
            <span className="gradient-text">Your resume</span>
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            What your CV says about you, read on its own. No job advert involved — this is the
            picture a recruiter forms before they compare you to anything.
          </p>
        </div>

        <Button variant="outline" onClick={reload} disabled={loading}>
          <RefreshCw className="size-4" aria-hidden />
          Re-read
        </Button>
      </header>

      {loading ? <LoadingSpinner message="Reading your resume…" /> : null}

      {/*
        A 409 here is not a failure, it is the first-run state: nothing has
        been uploaded. Showing a red alert box for it would tell a new user
        their app is broken on the one screen that is supposed to onboard
        them, so it gets its own calm panel pointing at the upload page.
      */}
      {!loading && error ? (
        error.includes('No resume available') ? (
          <Card>
            <CardContent className="space-y-4 py-10 text-center">
              <FileText className="mx-auto size-8 text-muted-foreground" aria-hidden />
              <div>
                <p className="font-medium">No resume uploaded yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Upload your CV and this page will describe it back to you.
                </p>
              </div>
              <Button asChild>
                <Link href="/">
                  Upload your CV
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <ErrorMessage message={error} onRetry={reload} />
        )
      ) : null}

      {!loading && insights ? (
        <>
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <CardTitle>In a sentence</CardTitle>
              <SourceBadge source={insights.source} />
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm leading-relaxed">{insights.headline}</p>

              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">Reads as</dt>
                  <dd className="mt-1 text-sm font-medium">
                    {titleCase(insights.primary_role)}
                  </dd>
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">Level</dt>
                  <dd className="mt-1 text-sm font-medium">{titleCase(insights.seniority)}</dd>
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">Experience</dt>
                  {/*
                    "Not stated" and "0 years" are different answers. The
                    muted styling on the former stops it reading as a score.
                  */}
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
                <div className="rounded-lg border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">Education</dt>
                  {/* Muted when absent, for the same reason as Experience. */}
                  <dd
                    className={
                      insights.education
                        ? 'mt-1 text-sm font-medium'
                        : 'mt-1 text-sm font-medium text-muted-foreground'
                    }
                  >
                    {insights.education ? titleCase(insights.education) : 'Not stated'}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          {Object.keys(insights.skill_groups).length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>What you can evidence ({insights.skills.length})</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {Object.entries(insights.skill_groups).map(([group, members]) => (
                  <div key={group}>
                    <p className="text-xs font-medium text-muted-foreground">{group}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {members.map((skill) => (
                        <Badge key={skill} variant="secondary">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                No technology on your CV matched the vocabulary this app knows. That usually
                means the skills are buried in prose rather than listed.
              </CardContent>
            </Card>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            {insights.strengths.length > 0 ? (
              <Card>
                <CardHeader>
                  <CardTitle>Working in your favour</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2 text-sm">
                    {insights.strengths.map((item) => (
                      <li key={item} className="flex gap-2">
                        <span aria-hidden className="text-muted-foreground">
                          &bull;
                        </span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ) : null}

            <Card>
              <CardHeader className="flex-row items-center gap-2">
                <Lightbulb className="size-4 text-muted-foreground" aria-hidden />
                <CardTitle>Fix these first</CardTitle>
              </CardHeader>
              <CardContent>
                {insights.improvements.length > 0 ? (
                  <ul className="space-y-2 text-sm">
                    {insights.improvements.map((item) => (
                      <li key={item} className="flex gap-2">
                        <span aria-hidden className="text-muted-foreground">
                          &bull;
                        </span>
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Nothing obviously missing from the document itself.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          {insights.suggested_roles.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Roles worth applying for</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-1.5">
                  {insights.suggested_roles.map((role) => (
                    <Badge key={role} variant="outline">
                      {role}
                    </Badge>
                  ))}
                </div>
                <p className="text-sm text-muted-foreground">
                  These come from the technologies your CV names, not from anything it says about
                what you want.{' '}
                {insights.search_queries.length > 0
                  ? `Discover Jobs searches the closest of them first: ${insights.search_queries.join(', ')}.`
                  : 'Discover Jobs can search them for you and link to each posting.'}
                </p>
                <div className="flex flex-wrap gap-3">
                  <Button asChild>
                    <Link href="/discover-jobs">
                      Find these jobs
                      <ArrowRight className="size-4" aria-hidden />
                    </Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link href="/interview-prep">Prepare for an interview</Link>
                  </Button>
                  <Button asChild variant="ghost">
                    <Link href="/assistant">
                      <MessageSquare className="size-4" aria-hidden />
                      Ask about my CV
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
