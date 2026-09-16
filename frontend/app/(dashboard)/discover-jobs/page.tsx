'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, FileText, Globe, MapPin, Search, Sparkles } from 'lucide-react';

import { JobCard, type SaveState } from '@/components/dashboard/JobCard';
import { JobDetailModal } from '@/components/dashboard/JobDetailModal';
import { SearchElsewhere } from '@/components/dashboard/SearchElsewhere';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { describeApiError, discoverJobs, saveJob } from '@/lib/api';
import type { Job, JobBucket, JobDiscoveryResponse } from '@/types';

/**
 * The filters are the backend's own buckets, not client-side score bands.
 *
 * The design sketch filtered on `>= 75`, `50-75` and `< 50` in the browser.
 * Those numbers exist nowhere in the backend, which sorts adverts at 80 / 60 /
 * 40 and keeps a fifth bucket for adverts it never scored. Re-deriving bands
 * here would have produced a UI that disagreed with the data it was filtering,
 * and would have folded unscored adverts into "under 50" — the one reading
 * they definitely do not have.
 */
const BUCKETS: { key: JobBucket | 'all'; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'perfect_match', label: 'Perfect match' },
  { key: 'good_fit', label: 'Good fit' },
  { key: 'stretch_goal', label: 'Stretch' },
  { key: 'learning_needed', label: 'Learning needed' },
  { key: 'unscored', label: 'Not scored' },
];

/**
 * Every search is restricted to India. There is no picker because there is no
 * choice to offer: showing a dropdown with one entry is a control that cannot
 * do anything.
 *
 * The backend matches this against each advert's location field as a whole
 * word. Both of those matter, and both were bugs found while making this
 * change: a substring match put Indiana roles in an india search, and
 * searching the advert body put a London job there because the company
 * mentioned an office in India.
 */
const LOCATION = 'india';

/**
 * How recent an advert has to be before it is worth applying to.
 *
 * Seven days, and the backend treats it as a ceiling rather than a preference:
 * it will never return anything older, and an advert with no posted date at
 * all is not shown either, because it cannot be shown to be inside the window.
 *
 * That means a narrow search can legitimately come back short or empty. The
 * backend says so in `freshness_note`, which is rendered verbatim below. A
 * quiet fallback to month-old adverts would fill the page, and would break the
 * one promise this page makes.
 */
const MAX_AGE_DAYS = 7;

/** What the current search is. Replacing this object is what runs a search. */
type SearchParams = {
  query?: string;
  auto_from_resume?: boolean;
  /*
    Empty means "anywhere". India is the default and the point of the page.
    Most results now come from Indian companies' own vacancy boards, so the
    restriction usually costs nothing -- but the general feeds are still in
    the mix, and a narrow term can still empty the page. Being stuck there
    with no way off is worse than being told the restriction is what is
    costing you the results, so the escape hatch stays. It is never taken
    automatically: a page headed "India" must not quietly show Berlin.
  */
  location?: string;
};

export default function DiscoverJobsPage() {
  const [query, setQuery] = useState('');
  const [bucket, setBucket] = useState<JobBucket | 'all'>('all');

  const [result, setResult] = useState<JobDiscoveryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const [saveStates, setSaveStates] = useState<Record<string, SaveState>>({});
  const [selected, setSelected] = useState<Job | null>(null);

  /*
    The first search runs itself, from the CV, with nothing typed.

    Asking someone to invent a search term is asking them to guess which words
    a job board indexed -- the one thing the app already knows from their
    resume. The manual box stays for overriding the guess, and `queries_used`
    on the response says what the guess was, so a wrong one is visible rather
    than silent.
  */
  const [params, setParams] = useState<SearchParams>({
    auto_from_resume: true,
    location: LOCATION,
  });

  // `loading` is raised by whoever triggers the fetch, not inside the effect.
  // Setting state synchronously in an effect body causes a cascading render
  // and is rejected by react-hooks/set-state-in-effect. A fresh object is
  // stored each time so that repeating the same search still re-runs it.
  const runSearch = (next: SearchParams) => {
    setLoading(true);
    setParams({ location: LOCATION, ...next });
  };

  useEffect(() => {
    let cancelled = false;

    discoverJobs({ ...params, max_age_days: MAX_AGE_DAYS, limit: 20 })
      .then((data) => {
        if (cancelled) return;
        setResult(data);
        setError(null);
        setBucket('all');
        setSaveStates({});
      })
      .catch((err) => {
        if (cancelled) return;
        setError(describeApiError(err));
        setResult(null);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setSearched(true);
      });

    return () => {
      cancelled = true;
    };
  }, [params]);

  const handleSearch = () => {
    if (!query.trim()) return;
    runSearch({ query: query.trim() });
  };

  const handleSave = async (jobId: string) => {
    setSaveStates((prev) => ({ ...prev, [jobId]: 'saving' }));
    try {
      await saveJob(jobId);
      setSaveStates((prev) => ({ ...prev, [jobId]: 'saved' }));
    } catch {
      setSaveStates((prev) => ({ ...prev, [jobId]: 'failed' }));
    }
  };

  // A 409 is the first-run state, not a fault: nothing has been uploaded yet.
  // A 422 means the CV is indexed but names too little to infer a role. Both
  // need a way forward rather than a red alert box.
  const noResume = error?.includes('No resume available') ?? false;
  const noRole = error?.includes('does not name enough technologies') ?? false;

  const categorized = result?.categorized;
  const rawJobs: Job[] = bucket === 'all' ? (result?.jobs ?? []) : (categorized?.[bucket] ?? []);

  /*
    The backend sorts each bucket by score, but `jobs` is the flat discovery
    order, so "All" arrived unsorted while every filtered view was ranked. Best
    match first is the only order that makes sense on a list you scan top-down.

    Unscored adverts sink rather than being dropped. `null` is not zero -- it
    means no resume was indexed when this was found -- so they keep their place
    at the bottom instead of being ranked as total mismatches.
  */
  const visibleJobs: Job[] =
    bucket === 'all'
      ? [...rawJobs].sort((a, b) => {
          const scoreOf = (job: Job) =>
            typeof job.match_to_user?.score === 'number' ? job.match_to_user.score : -1;
          return scoreOf(b) - scoreOf(a);
        })
      : rawJobs;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Discover opportunities</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {params.location
            ? `Jobs in India, posted in the last ${MAX_AGE_DAYS} days, matched against your resume. Anything older, or with no posting date, is not shown.`
            : `Jobs from anywhere, posted in the last ${MAX_AGE_DAYS} days, matched against your resume. Anything older, or with no posting date, is not shown.`}{' '}
          They come from Indian companies&apos; own vacancy boards — Paytm, Meesho, CRED, Groww,
          Postman, Druva and others — plus Adzuna, Hacker News, Remotive, Arbeitnow and public RSS
          feeds.
        </p>
      </header>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            placeholder="Job title, skill or company…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            // onKeyPress is deprecated in React and is not the supported way to
            // catch Enter; onKeyDown is.
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleSearch();
            }}
            className="pl-9"
            aria-label="Search query"
          />
        </div>

        <div className="flex items-center gap-2 rounded-md border border-input bg-muted/40 px-3 py-2 text-sm text-muted-foreground sm:w-40">
          <MapPin className="size-4 shrink-0" aria-hidden />
          <span>{params.location ? 'India only' : 'Anywhere'}</span>
        </div>

        <Button onClick={handleSearch} disabled={loading || !query.trim()}>
          {loading ? 'Searching…' : 'Search'}
        </Button>

        <Button
          variant="outline"
          onClick={() => runSearch({ auto_from_resume: true })}
          disabled={loading}
          title="Search for the roles your CV points at"
        >
          <Sparkles className="size-4" aria-hidden />
          Use my CV
        </Button>
      </div>

      {/*
        Naming the phrases is the point, not decoration. The server inferred
        them from the CV, and a user who does not agree with "backend
        developer" can only correct it if they are told that is what was
        searched for.
      */}
      {result && result.derived_from_resume && result.queries_used.length > 0 ? (
        <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
          Searched from your CV:{' '}
          {result.queries_used.map((phrase, index) => (
            <span key={phrase}>
              {index > 0 ? ', ' : ''}
              <span className="font-medium text-foreground">{phrase}</span>
            </span>
          ))}
          . Not what you do? Type your own search above.
        </p>
      ) : null}

      {noResume || noRole ? (
        <div className="space-y-4 rounded-lg border bg-card p-8 text-center">
          <FileText className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            {noResume
              ? 'You have not uploaded a resume yet, so there is nothing to work out your roles from. Upload one, or type a search above.'
              : 'Your CV does not name enough technologies to infer a role from. Add a skills section, or type a search above.'}
          </p>
          <Button asChild variant="outline">
            <Link href={noResume ? '/' : '/my-resume'}>
              {noResume ? 'Upload your CV' : 'See what your CV says'}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        </div>
      ) : error ? (
        <ErrorMessage message={error} onRetry={() => runSearch(params)} />
      ) : null}

      {/*
        Gated on `total_found` as well as the flag. The backend's empty-result
        branch returns before it ever looks at the resume, so
        `scored_against_resume` is false on a zero-result search even when an
        index is loaded — this banner read "No resume is indexed" while the
        settings page correctly reported 21 chunks. With no cards on screen
        there is also nothing for it to explain.

        The wording says the adverts were not scored rather than asserting why.
        An unreadable index produces the same flag as an absent one, and the
        response does not distinguish them.
      */}
      {result && result.total_found > 0 && !result.scored_against_resume ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
          These adverts were not matched against your resume, so they are listed in the order the
          feeds returned them. Check your resume is uploaded on the Settings page. Every score
          reads &ldquo;Not scored&rdquo; rather than 0% — the two mean different things.
        </p>
      ) : null}

      {/*
        Printed word for word from the server. It only appears when the two-day
        window was actually widened, and saying so is the whole point: a list
        quietly padded with month-old adverts is worse than a short one.
      */}
      {result?.freshness_note ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
          {result.freshness_note}
        </p>
      ) : null}

      {/*
        Adverts whose feed published no posting date. These only ever reach the
        screen when the date filter was dropped altogether -- while a window is
        in force they are excluded, because "we do not know how old this is"
        is not the same answer as "recent enough".
      */}
      {result && result.total_found > 0 && (result.undated_count ?? 0) > 0 ? (
        <p className="text-xs text-muted-foreground">
          {result.undated_count} of these adverts carry no posting date, so their age is unknown.
          They are listed after the dated ones.
        </p>
      ) : null}

      {result && categorized ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">Filter:</span>
          {BUCKETS.map(({ key, label }) => {
            const count = key === 'all' ? result.jobs.length : (categorized.counts?.[key] ?? 0);

            return (
              <Badge
                key={key}
                variant={bucket === key ? 'default' : 'outline'}
                asChild
                className={count === 0 && key !== 'all' ? 'opacity-50' : undefined}
              >
                <button type="button" onClick={() => setBucket(key)} aria-pressed={bucket === key}>
                  {label} ({count})
                </button>
              </Badge>
            );
          })}
        </div>
      ) : null}

      {loading ? <LoadingSpinner message="Fetching adverts from live feeds…" /> : null}
      {!loading && result ? (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {visibleJobs.length} of {result.total_found} shown
            {result.sources_used.length ? ` · sources: ${result.sources_used.join(', ')}` : ''}
          </p>

          {visibleJobs.length > 0 ? (
            <div className="grid gap-4">
              {visibleJobs.map((job) => (
                <JobCard
                  key={job.job_id}
                  job={job}
                  saveState={saveStates[job.job_id] ?? 'idle'}
                  onSave={() => handleSave(job.job_id)}
                  onOpen={() => setSelected(job)}
                />
              ))}
            </div>
          ) : (
            /*
              An empty bucket and an empty search are different problems and
              need different advice. Telling someone to "try another filter"
              when the search itself found nothing sends them round a set of
              buckets that are all empty too.
            */
            <div className="space-y-4 py-8 text-center">
              <p className="text-sm text-muted-foreground">
                {result.total_found === 0
                  ? params.location
                    ? 'No adverts located in India matched that search. Try a broader term, or drop the location filter below.'
                    : 'Nothing matched that search anywhere. Try a broader term.'
                  : 'Nothing in this bucket. Try another filter.'}
              </p>

              {/*
                Offered rather than done automatically. Quietly showing US
                roles under a heading that says India would be the worse
                failure of the two.
              */}
              {result.total_found === 0 && params.location ? (
                <Button
                  variant="outline"
                  onClick={() => runSearch({ ...params, location: '' })}
                  disabled={loading}
                >
                  <Globe className="size-4" aria-hidden />
                  Search anywhere instead
                </Button>
              ) : null}

              {result.total_found === 0 && !params.location ? (
                <Button
                  variant="outline"
                  onClick={() => runSearch({ ...params, location: LOCATION })}
                  disabled={loading}
                >
                  <MapPin className="size-4" aria-hidden />
                  Back to India only
                </Button>
              ) : null}
            </div>
          )}

          {/*
            Remotive's terms require naming them as the source and linking
            back; the Hacker News archive asks for attribution to the posting
            author. The backend passes this wording through precisely so a
            client can honour it, which means rendering it, not logging it.
          */}
          {result.attribution.length > 0 ? (
            <footer className="border-t pt-4">
              <p className="text-xs font-medium text-muted-foreground">Source attribution</p>
              <ul className="mt-1 space-y-1">
                {result.attribution.map((line) => (
                  <li key={line} className="text-xs text-muted-foreground">
                    {line}
                  </li>
                ))}
              </ul>
            </footer>
          ) : null}
        </div>
      ) : null}

      {!searched && !loading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Results are fetched live, so this takes a few seconds.
        </p>
      ) : null}

      {/*
        Shown once a search has run, whatever it found. Three good results
        still leave someone wanting the boards everyone else is on, and a
        page that found nothing is exactly when the offer is most useful.

        Read from `params`, which only changes when a search is submitted,
        rather than from the input box. Half-typed text in the box has not
        been searched for here, so sending it to LinkedIn would open a
        different search from the one on screen.
      */}
      {searched && !loading ? (
        <SearchElsewhere
          query={params.query?.trim() || result?.queries_used?.[0] || ''}
        />
      ) : null}

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
