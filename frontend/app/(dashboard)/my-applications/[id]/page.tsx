'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { ApplicationTimeline } from '@/components/dashboard/ApplicationTimeline';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { describeApiError, getApplicationHistory, updateApplicationStatus } from '@/lib/api';
import { APPLICATION_STATUSES } from '@/types';
import type { ApplicationHistory, ApplicationStatus } from '@/types';

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  draft: 'Draft',
  sent: 'Sent',
  interview: 'Interview scheduled',
  rejected: 'Rejected',
  offer: 'Offer received',
};

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const appId = params.id;

  const [application, setApplication] = useState<ApplicationHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [nextStatus, setNextStatus] = useState<string>('');
  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const retry = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;

    getApplicationHistory(appId)
      .then((data) => {
        if (cancelled) return;
        setApplication(data);
        setNextStatus(data.current_status);
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
  }, [appId, reloadKey]);

  const handleStatusUpdate = async () => {
    if (!application || nextStatus === application.current_status) return;

    setUpdating(true);
    setUpdateError(null);

    try {
      await updateApplicationStatus(appId, nextStatus);
      // Refetched rather than patched locally: the update appends a timeline
      // entry on the server, and setting `current_status` by hand would show a
      // new status above a history that never mentions the change.
      setReloadKey((key) => key + 1);
    } catch (err) {
      setUpdateError(describeApiError(err));
    } finally {
      setUpdating(false);
    }
  };

  const title = application?.job_title?.trim();
  const company = application?.company?.trim();

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <Button asChild variant="link" size="sm" className="h-auto p-0">
        <Link href="/my-applications">
          <ArrowLeft className="size-4" aria-hidden />
          All applications
        </Link>
      </Button>

      {error ? (
        <ErrorMessage message={error} onRetry={retry} />
      ) : loading ? (
        <LoadingSpinner message="Loading application…" />
      ) : application ? (
        <>
          <header className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold">
                <span className="gradient-text">{title || 'Untitled advert'}</span>
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {company || 'Company not captured'} · {appId}
              </p>
            </div>
            <Badge variant="outline" className="px-3 py-1 text-sm">
              {STATUS_LABELS[application.current_status as ApplicationStatus] ??
                application.current_status}
            </Badge>
          </header>

          {!title ? (
            /*
              create-application stores whatever `analysis_data` carried. When
              it was empty the title and company are empty strings, and saying
              so is more use than printing a blank heading.
            */
            <p className="text-xs text-muted-foreground">
              This application was created without analysis data, so the advert&rsquo;s title and
              company were never captured. Running the analysis before creating it fills these in.
            </p>
          ) : null}

          <section className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <p className="text-sm text-muted-foreground">Match score</p>
                <p className="mt-1 font-semibold">
                  {/* Null is not zero: no analysis was attached. */}
                  {typeof application.match_score === 'number' ? (
                    <span className="text-2xl">{Math.round(application.match_score)}%</span>
                  ) : (
                    <span className="text-base text-muted-foreground">Not scored</span>
                  )}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-sm text-muted-foreground">Events</p>
                <p className="mt-1 text-2xl font-semibold">{application.timeline.length}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-sm text-muted-foreground">Gaps identified</p>
                <p className="mt-1 font-semibold">
                  {/*
                    The API stores an empty list both when the analysis found no
                    gaps and when no analysis was ever attached, so an empty list
                    on its own means nothing. A score is the evidence that
                    something was measured: with one, an empty list really is
                    zero gaps; without one, the count is simply unknown.
                  */}
                  {application.gaps_identified.length > 0 ||
                  typeof application.match_score === 'number' ? (
                    <span className="text-2xl">{application.gaps_identified.length}</span>
                  ) : (
                    <span className="text-base text-muted-foreground">Not analysed</span>
                  )}
                </p>
              </CardContent>
            </Card>
          </section>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Update status</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-3">
                {/*
                  A Radix Select, so it needs a trigger and items -- plain
                  <option> children render nothing. The five values are the
                  backend's own; "applied" is not one of them.
                */}
                <Select value={nextStatus} onValueChange={setNextStatus}>
                  <SelectTrigger className="w-56" aria-label="New status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {APPLICATION_STATUSES.map((status) => (
                      <SelectItem key={status} value={status}>
                        {STATUS_LABELS[status]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Button
                  onClick={handleStatusUpdate}
                  disabled={updating || nextStatus === application.current_status}
                >
                  {updating ? 'Updating…' : 'Update'}
                </Button>
              </div>

              {updateError ? <ErrorMessage message={updateError} /> : null}

              <p className="text-xs text-muted-foreground">
                Status changes are appended to the history below. Nothing is overwritten, so a
                rejection after an interview keeps both.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">History</CardTitle>
            </CardHeader>
            <CardContent>
              <ApplicationTimeline events={application.timeline} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
