'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { CalendarCheck, FileText, Send, Trophy } from 'lucide-react';

import { StatCard } from '@/components/dashboard/StatCard';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { describeApiError, getAnalytics, getApplications } from '@/lib/api';
import { APPLICATION_STATUSES } from '@/types';
import type { AnalyticsMetrics, Application, ApplicationStatus } from '@/types';

/**
 * `sent`, not `applied`. The five values come from `APPLICATION_STATUSES` in
 * `backend/agents/application_tracker.py`; the design sketch filtered on
 * `applied`, which the API rejects, and did so with `status.includes(filter)`,
 * a substring test that would also match nothing.
 */
const STATUS_LABELS: Record<ApplicationStatus, string> = {
  draft: 'Draft',
  sent: 'Sent',
  interview: 'Interview',
  rejected: 'Rejected',
  offer: 'Offer',
};

const STATUS_TONES: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  sent: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  interview: 'bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300',
  offer: 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300',
};

function describeApplication(application: Application): string {
  // `job_title` is an empty string when the application was created without
  // analysis data. Falling through to the job id is uglier than inventing a
  // title, and accurate.
  const title = application.job_title?.trim();
  if (title) return title;
  return application.job_id ? `Untitled advert (${application.job_id})` : 'Untitled advert';
}

function formatDate(value: string | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [metrics, setMetrics] = useState<AnalyticsMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ApplicationStatus | 'all'>('all');
  const [reloadKey, setReloadKey] = useState(0);

  const retry = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;

    Promise.all([getApplications(), getAnalytics()])
      .then(([list, analytics]) => {
        if (cancelled) return;
        setApplications(list.applications ?? []);
        setCounts(list.status_counts ?? {});
        setMetrics(analytics.metrics);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(describeApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const visible =
    filter === 'all'
      ? applications
      : applications.filter((application) => application.current_status === filter);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">My applications</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Every application you are tracking, with the history of how each one moved.
        </p>
      </header>

      {error ? (
        <ErrorMessage message={error} onRetry={retry} />
      ) : loading ? (
        <LoadingSpinner message="Loading applications…" />
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Tracked"
              value={applications.length}
              emptyText="None yet"
              icon={FileText}
            />
            {/*
              These two count how many applications have *ever* reached a
              stage. The filter badges below count how many sit at that stage
              *now*, and the two disagree on purpose: an application that was
              sent and then progressed to an offer is 1 here and 0 under
              "Sent". Both were labelled "Sent", side by side, reading "Sent 1"
              directly above "Sent (0)" — which looks like a broken page rather
              than two different questions. The labels now say which is which.
            */}
            <StatCard
              label="Ever sent"
              value={metrics?.applications_sent}
              emptyText="None yet"
              icon={Send}
            />
            <StatCard
              label="Ever interviewed"
              value={metrics?.interviews_scheduled}
              emptyText="None yet"
              icon={CalendarCheck}
            />
            {/*
              The rate comes from the backend, which divides by applications
              *sent* and returns null when that is zero. The sketch computed
              interviews / max(total, 1) in the browser, which reports "0%" for
              someone who has not applied to anything and silently changes the
              denominator to include drafts.
            */}
            <StatCard
              label="Interview rate"
              value={metrics?.interview_rate ?? null}
              emptyText="Nothing sent yet"
              hint={
                metrics?.interview_rate_confidence_95
                  ? `95% confidence: ${metrics.interview_rate_confidence_95}`
                  : undefined
              }
              icon={Trophy}
            />
          </section>

          {metrics?.sample_size_warning ? (
            <p className="text-xs text-muted-foreground">{metrics.sample_size_warning}</p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Currently at stage:</span>
            <Badge variant={filter === 'all' ? 'default' : 'outline'} asChild>
              <button type="button" onClick={() => setFilter('all')} aria-pressed={filter === 'all'}>
                All ({applications.length})
              </button>
            </Badge>
            {APPLICATION_STATUSES.map((status) => (
              <Badge
                key={status}
                variant={filter === status ? 'default' : 'outline'}
                asChild
                className={(counts[status] ?? 0) === 0 ? 'opacity-50' : undefined}
              >
                <button
                  type="button"
                  onClick={() => setFilter(status)}
                  aria-pressed={filter === status}
                >
                  {STATUS_LABELS[status]} ({counts[status] ?? 0})
                </button>
              </Badge>
            ))}
          </div>

          {visible.length > 0 ? (
            <div className="space-y-3">
              {visible.map((application) => {
                const created = formatDate(application.created_date);
                const updated = formatDate(application.updated_date);

                return (
                  <Link
                    key={application.app_id}
                    href={`/my-applications/${application.app_id}`}
                    className="block"
                  >
                    <Card className="card-hover">
                      <CardContent className="space-y-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <h2 className="font-medium">{describeApplication(application)}</h2>
                            <p className="text-sm text-muted-foreground">
                              {application.company?.trim() || 'Company not captured'}
                            </p>
                          </div>
                          <span
                            className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                              STATUS_TONES[application.current_status] ?? STATUS_TONES.draft
                            }`}
                          >
                            {STATUS_LABELS[application.current_status as ApplicationStatus] ??
                              application.current_status}
                          </span>
                        </div>

                        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                          <span>
                            Match:{' '}
                            {/*
                              Null means the application was created without an
                              analysis attached, not that it scored zero.
                            */}
                            {typeof application.match_score === 'number'
                              ? `${Math.round(application.match_score)}%`
                              : 'Not scored'}
                          </span>
                          {created ? <span>Created {created}</span> : null}
                          {updated && updated !== created ? <span>Updated {updated}</span> : null}
                          <span>
                            {application.timeline?.length ?? 0}{' '}
                            {(application.timeline?.length ?? 0) === 1 ? 'event' : 'events'}
                          </span>
                        </div>
                      </CardContent>
                    </Card>
                  </Link>
                );
              })}
            </div>
          ) : (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                {applications.length === 0 ? (
                  <>
                    Nothing tracked yet. Save an advert on{' '}
                    <Link href="/discover-jobs" className="underline">
                      Discover Jobs
                    </Link>{' '}
                    to start one.
                  </>
                ) : (
                  'No applications with that status.'
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
