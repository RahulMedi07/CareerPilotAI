'use client';

import {
  Banknote,
  Bookmark,
  BookmarkCheck,
  Briefcase,
  Building2,
  CalendarDays,
  ExternalLink,
  MapPin,
  Sparkles,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { Job, SavedJob } from '@/types';

/**
 * The same thresholds `agents/job_enricher.py` uses to bucket adverts
 * (PERFECT_MATCH_MIN / GOOD_FIT_MIN / STRETCH_GOAL_MIN).
 *
 * The design sketch used 75 and 50. Those disagree with the backend, so an
 * advert the API had placed in `good_fit` could have been coloured as a poor
 * match by the card sitting next to the filter that put it there. One source
 * of truth, copied deliberately rather than invented.
 */
const PERFECT_MATCH_MIN = 80;
const GOOD_FIT_MIN = 60;
const STRETCH_GOAL_MIN = 40;

/**
 * Below this, the advert was too thin to have earned the number it produced.
 *
 * Measured, not picked: a German-language advert yielding one readable skill
 * scored 100% at confidence 50, while a full eight-skill advert scored 79.5
 * at confidence 67.5. The honest reading of the first is "of the one thing we
 * could make out, you have it" -- which is not a perfect match, and must not
 * be coloured like one.
 */
const LOW_CONFIDENCE_MAX = 60;

function scoreTone(score: number, lowConfidence: boolean) {
  if (lowConfidence) return 'text-muted-foreground';
  if (score >= PERFECT_MATCH_MIN) return 'text-green-600 dark:text-green-400';
  if (score >= GOOD_FIT_MIN) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= STRETCH_GOAL_MIN) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

/**
 * How sure the backend was that it had read the advert, or null for a saved
 * row, which stores the score without it.
 */
function readConfidence(job: Job | SavedJob): number | null {
  if ('match_to_user' in job) {
    const confidence = job.match_to_user?.confidence;
    return typeof confidence === 'number' ? confidence : null;
  }
  return null;
}

/** Discovered jobs carry `match_to_user.score`; saved rows carry `match_score`. */
function readScore(job: Job | SavedJob): number | null {
  if ('match_to_user' in job) {
    const score = job.match_to_user?.score;
    return typeof score === 'number' ? score : null;
  }
  return typeof job.match_score === 'number' ? job.match_score : null;
}

/**
 * Why no percentage is shown, in words.
 *
 * A missing score has two quite different causes, and giving the wrong one is
 * a small lie of its own. Either no resume was indexed when the advert was
 * fetched, or the advert listed nothing role-specific to compare a resume
 * against -- a copywriting post has no tech stack, so scoring it on years of
 * experience alone would hand it a number it never earned. The backend tells
 * the two apart: `match_to_user` is absent in the first case and present with
 * a null score in the second.
 */
function scoreNote(job: Job | SavedJob): string {
  if ('match_to_user' in job) {
    return job.match_to_user ? 'Advert lists no comparable skills' : 'No resume uploaded';
  }
  return 'Not scored when saved';
}

export type SaveState = 'idle' | 'saving' | 'saved' | 'failed';

/**
 * How old the advert is, in words, or `null` when the feed did not say.
 *
 * `days_old` is null for every source that publishes no date, and null is not
 * zero: "Posted today" on an advert of unknown age is exactly the invented
 * freshness that sends someone chasing a role filled months ago. When the age
 * is unknown this returns null and the caller prints nothing at all.
 */
function ageLabel(days: number | null | undefined): string | null {
  if (typeof days !== 'number' || Number.isNaN(days)) return null;
  if (days <= 0) return 'Posted today';
  if (days === 1) return 'Posted yesterday';
  return `Posted ${days} days ago`;
}

interface JobCardProps {
  job: Job | SavedJob;
  onSave?: () => void;
  saveState?: SaveState;
  onOpen?: () => void;
  onTrack?: () => void;
  trackState?: SaveState;
}

export function JobCard({
  job,
  onSave,
  saveState = 'idle',
  onOpen,
  onTrack,
  trackState = 'idle',
}: JobCardProps) {
  const score = readScore(job);
  const confidence = readConfidence(job);
  const lowConfidence = confidence !== null && confidence < LOW_CONFIDENCE_MAX;
  const analysis = job.analysis ?? null;
  const techStack = analysis?.tech_stack ?? analysis?.required_skills ?? [];
  const verdict = 'match_to_user' in job ? job.match_to_user?.verdict : undefined;

  // Both arrive only from feeds that publish them (Remotive sends salary,
  // Arbeitnow sends location), so both are absent more often than not. They
  // are rendered when present and omitted when not -- never filled in with a
  // guess or an estimate, because the salary line is the one a candidate
  // would negotiate against.
  const location = typeof job.location === 'string' ? job.location : '';
  const salary = typeof job.salary === 'string' ? job.salary : '';

  // The plain-English answer to "why should I apply for this?", written by
  // the backend from the same overlap it scored the advert with. Saved rows
  // predate the field, so it is optional everywhere.
  const reasons = 'match_to_user' in job ? (job.match_to_user?.reasons ?? []) : [];
  const posted = ageLabel('days_old' in job ? job.days_old : null);

  return (
    <Card className="card-hover">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-2 text-base font-semibold sm:text-lg">{job.title}</h3>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Building2 className="size-4" aria-hidden />
                {job.company}
              </span>
              {job.source ? <Badge variant="outline">{job.source}</Badge> : null}
              {location ? (
                <span className="flex items-center gap-1">
                  <MapPin className="size-4" aria-hidden />
                  {location}
                </span>
              ) : null}
              {salary ? (
                <span className="flex items-center gap-1">
                  <Banknote className="size-4" aria-hidden />
                  {salary}
                </span>
              ) : null}
              {analysis?.difficulty ? (
                <Badge variant="secondary">{analysis.difficulty}</Badge>
              ) : null}
              {analysis?.experience_years ? (
                <span>{analysis.experience_years}+ yrs</span>
              ) : null}
              {/* Omitted entirely when the feed published no date. */}
              {posted ? (
                <span className="flex items-center gap-1">
                  <CalendarDays className="size-4" aria-hidden />
                  {posted}
                </span>
              ) : null}
            </div>
          </div>

          {/*
            A missing score is rendered as a sentence, never as 0%.
            The score is null when the advert was never measured -- no resume
            indexed, or nothing role-specific in the advert to measure against
            -- and printing 0% there would report an advert as a total
            mismatch it was never compared with. `scoreNote` says which.
          */}
          <div className="shrink-0 text-right">
            {score === null ? (
              <>
                <p className="text-sm font-medium text-muted-foreground">Not scored</p>
                <p className="mt-0.5 max-w-[9rem] text-xs text-muted-foreground">
                  {scoreNote(job)}
                </p>
              </>
            ) : (
              <>
                <p className={cn('text-3xl font-bold tabular-nums', scoreTone(score, lowConfidence))}>
                  {Math.round(score)}%
                </p>
                {lowConfidence ? (
                  <p className="mt-0.5 max-w-[9rem] text-xs text-muted-foreground">
                    Little of this advert could be read — treat the score loosely
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">{verdict ?? 'Match'}</p>
                )}
              </>
            )}
          </div>
        </div>

        {job.description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground">{job.description}</p>
        ) : null}

        {/*
          The question this whole card exists to answer. It includes the gaps
          as well as the overlap, because a list of reasons to apply with the
          reasons against left off is an advert, not advice.
        */}
        {reasons.length > 0 ? (
          <div className="rounded-lg border bg-muted/40 p-3">
            <p className="text-xs font-medium">Why this one is worth your time</p>
            <ul className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              {reasons.map((reason) => (
                <li key={reason} className="flex gap-2">
                  <span aria-hidden>&bull;</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {techStack.length > 0 ? (
          <div>
            <p className="mb-2 text-xs text-muted-foreground">Named in the advert:</p>
            <div className="flex flex-wrap gap-1.5">
              {techStack.slice(0, 6).map((tech) => (
                <Badge key={tech} variant="secondary" className="text-xs">
                  {tech}
                </Badge>
              ))}
              {techStack.length > 6 ? (
                <Badge variant="outline" className="text-xs">
                  +{techStack.length - 6}
                </Badge>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {onSave ? (
            /*
              There is no delete-job endpoint, so this is not a toggle. Once a
              job is saved the button becomes a disabled confirmation; a
              second click that only cleared local state would tell the reader
              it had been removed when the row is still in the database.
            */
            <Button
              variant="outline"
              size="sm"
              onClick={onSave}
              disabled={saveState === 'saving' || saveState === 'saved'}
            >
              {saveState === 'saved' ? (
                <BookmarkCheck className="size-4" aria-hidden />
              ) : (
                <Bookmark className="size-4" aria-hidden />
              )}
              {saveState === 'saved' ? 'Saved' : saveState === 'saving' ? 'Saving…' : 'Save'}
            </Button>
          ) : null}

          {onOpen ? (
            <Button size="sm" onClick={onOpen}>
              <Sparkles className="size-4" aria-hidden />
              Analyse
            </Button>
          ) : null}

          {onTrack ? (
            <Button
              variant="outline"
              size="sm"
              onClick={onTrack}
              disabled={trackState === 'saving' || trackState === 'saved'}
            >
              <Briefcase className="size-4" aria-hidden />
              {trackState === 'saved'
                ? 'Tracking'
                : trackState === 'saving'
                  ? 'Starting…'
                  : 'Track application'}
            </Button>
          ) : null}

          {job.url ? (
            <Button variant="secondary" size="sm" asChild>
              {/*
                Remotive and the Hacker News archive both require a link back
                to the original posting as a condition of use. This is that
                link, not a convenience.

                It names the source rather than saying "Apply Now", because
                this app cannot apply on anyone's behalf and a button that
                promises to would be lying about where the click goes.
              */}
              <a href={job.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="size-4" aria-hidden />
                Apply on {job.source || 'the original posting'}
              </a>
            </Button>
          ) : null}
        </div>

        {saveState === 'failed' ? (
          <p className="text-xs text-red-600 dark:text-red-400">
            Could not save. Discovered jobs are held in memory for this server session — search
            again, then save.
          </p>
        ) : null}

        {trackState === 'failed' ? (
          <p className="text-xs text-red-600 dark:text-red-400">
            Could not start tracking this application.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
