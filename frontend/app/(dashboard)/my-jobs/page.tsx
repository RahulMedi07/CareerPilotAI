'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { JobCard, type SaveState } from '@/components/dashboard/JobCard';
import { JobDetailModal } from '@/components/dashboard/JobDetailModal';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Button } from '@/components/ui/button';
import { createApplication, describeApiError, getMyJobs } from '@/lib/api';
import type { SavedJob } from '@/types';

export default function MyJobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<SavedJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SavedJob | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [trackStates, setTrackStates] = useState<Record<string, SaveState>>({});

  // `loading` is raised by whoever triggers the fetch, not inside the effect.
  // Setting state synchronously in an effect body causes a cascading render
  // and is rejected by react-hooks/set-state-in-effect.
  const retry = () => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;

    getMyJobs()
      .then((data) => {
        if (cancelled) return;
        // The response is an object, not a bare array: {jobs, total,
        // status_counts, user_id}.
        setJobs(data.jobs ?? []);
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

  // The title, company and score are passed through so the application does not
  // land in the tracker with empty strings and a null match. `create_application`
  // stores whatever `analysis_data` carries and nothing else -- it does not look
  // the job up.
  const handleTrack = async (job: SavedJob) => {
    setTrackStates((current) => ({ ...current, [job.job_id]: 'saving' }));

    try {
      const created = await createApplication({
        jobId: job.job_id,
        analysisData: {
          job_title: job.title,
          company: job.company,
          match_score: job.match_score ?? null,
        },
      });
      setTrackStates((current) => ({ ...current, [job.job_id]: 'saved' }));
      router.push(`/my-applications/${created.application_id}`);
    } catch {
      setTrackStates((current) => ({ ...current, [job.job_id]: 'failed' }));
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Saved jobs</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Adverts you kept. These are stored on disk, so they survive a restart — unlike search
          results, which are held only for the current server session.
        </p>
      </header>

      {error ? (
        <ErrorMessage message={error} onRetry={retry} />
      ) : loading ? (
        <LoadingSpinner message="Loading saved jobs…" />
      ) : jobs.length > 0 ? (
        <>
          <p className="text-sm text-muted-foreground">
            {jobs.length} saved {jobs.length === 1 ? 'job' : 'jobs'}
          </p>
          <div className="grid gap-4">
            {jobs.map((job) => (
              <JobCard
                key={job.job_id}
                job={job}
                onOpen={() => setSelected(job)}
                onTrack={() => handleTrack(job)}
                trackState={trackStates[job.job_id] ?? 'idle'}
              />
            ))}
          </div>
        </>
      ) : (
        <div className="py-12 text-center">
          <p className="text-sm text-muted-foreground">Nothing saved yet.</p>
          <Button asChild variant="outline" className="mt-3">
            <Link href="/discover-jobs">Find some adverts</Link>
          </Button>
        </div>
      )}

      <JobDetailModal
        job={selected}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      />
    </div>
  );
}
