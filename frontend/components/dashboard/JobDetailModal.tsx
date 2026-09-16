'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ExternalLink, Loader2, MessageCircleQuestion } from 'lucide-react';

import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { describeApiError, fullAnalysis } from '@/lib/api';
import { stashJobForInterview } from '@/lib/interview-handoff';
import { cn } from '@/lib/utils';
import type { AnalysisResult, Job, SavedJob } from '@/types';

const VERDICT_TONE: Record<string, string> = {
  APPLY: 'bg-green-600 text-white',
  MAYBE: 'bg-amber-500 text-white',
  SKIP: 'bg-red-600 text-white',
  // Neutral: nothing was measured, so no colour is earned either way.
  NOT_SCORED: 'bg-muted text-muted-foreground',
};

export function JobDetailModal({
  job,
  open,
  onOpenChange,
}: {
  job: Job | SavedJob | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  // Hands this advert to the prep page rather than making the user find it
  // again and paste it in. Without the description there is nothing to aim
  // the questions at, so the button is not offered at all.
  const handlePrepare = () => {
    if (!job?.description) return;
    stashJobForInterview({
      title: job.title,
      company: job.company,
      description: job.description,
    });
    router.push('/interview-prep');
  };

  const handleAnalyse = async () => {
    if (!job?.description) return;

    setAnalysing(true);
    setError(null);

    try {
      // No resume_text is sent: the pipeline uses the indexed resume, which is
      // the one the rest of the app scores against. Passing the advert twice
      // would score it against itself.
      setAnalysis(await fullAnalysis(job.description));
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setAnalysing(false);
    }
  };

  // Analysis belongs to one advert. Leaving it on screen while a different job
  // is opened would attribute one job's gaps to another.
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setAnalysis(null);
      setError(null);
    }
    onOpenChange(next);
  };

  if (!job) return null;

  const gapsSection = analysis?.analysis?.gaps;
  const report = gapsSection?.gap_report;
  const criticalGaps = report?.critical_gaps ?? [];
  const jobAnalysis = job.analysis ?? null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] gap-0 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-6 text-left">{job.title}</DialogTitle>
          <DialogDescription className="text-left">{job.company}</DialogDescription>
        </DialogHeader>

        <div className="mt-4 space-y-6">
          {job.url ? (
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline dark:text-blue-400"
            >
              Original posting <ExternalLink className="size-3.5" aria-hidden />
            </a>
          ) : null}

          {jobAnalysis ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat
                label="Experience asked for"
                value={
                  jobAnalysis.experience_years ? `${jobAnalysis.experience_years}+ years` : null
                }
              />
              <Stat label="Difficulty" value={jobAnalysis.difficulty ?? null} />
              <Stat label="Seniority" value={jobAnalysis.seniority ?? null} />
            </div>
          ) : null}

          {error ? <ErrorMessage message={error} onRetry={handleAnalyse} /> : null}

          {analysing ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="size-5 animate-spin" aria-hidden />
              Working through this advert…
            </div>
          ) : analysis ? (
            <div className="space-y-5">
              <div className="rounded-lg border p-4">
                <p className="text-sm text-muted-foreground">Match score</p>
                <div className="mt-1 flex items-center gap-3">
                  {/* Null means the advert stated nothing measurable, which is
                      not the same as a zero. See `AnalysisResults`. */}
                  <p className="text-3xl font-bold tabular-nums">
                    {typeof analysis.overall_match === 'number'
                      ? `${Math.round(analysis.overall_match)}%`
                      : 'Not scored'}
                  </p>
                  <Badge className={cn(VERDICT_TONE[analysis.recommendation] ?? '')}>
                    {analysis.recommendation === 'NOT_SCORED'
                      ? 'NO VERDICT'
                      : analysis.recommendation}
                  </Badge>
                </div>
                {analysis.user_recommendation ? (
                  <p className="mt-3 text-sm text-muted-foreground">
                    {analysis.user_recommendation}
                  </p>
                ) : null}
              </div>

              {/*
                The gap detector says when it fell back to the deterministic
                path because no LLM was reachable. Hiding that would present a
                keyword comparison as a considered judgement.
              */}
              {gapsSection?.source === 'fallback' ? (
                <p className="flex items-start gap-2 text-xs text-muted-foreground">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  The AI was not available, so these gaps come from comparing your skills to the
                  advert directly rather than AI reading it.
                </p>
              ) : null}

              {gapsSection?.strengths?.length ? (
                <section>
                  <h3 className="mb-2 text-sm font-semibold">What you already have</h3>
                  <div className="flex flex-wrap gap-1.5">
                    {gapsSection.strengths.map((skill) => (
                      <Badge key={skill} variant="secondary" className="text-xs">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </section>
              ) : null}

              {/*
                `analysis.gaps` is an object, not an array, and the per-skill
                detail lives at `gaps.gap_report.critical_gaps` with the field
                `learning_time_days`.
              */}
              {criticalGaps.length > 0 ? (
                <section>
                  <h3 className="mb-2 text-sm font-semibold">
                    Critical gaps ({report?.critical_count ?? criticalGaps.length})
                  </h3>
                  <ul className="divide-y rounded-lg border">
                    {criticalGaps.map((gap) => (
                      <li key={gap.skill_id ?? gap.skill} className="p-3">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-sm font-medium">{gap.skill}</span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {typeof gap.learning_time_days === 'number'
                              ? `~${gap.learning_time_days} days to learn`
                              : 'no estimate'}
                          </span>
                        </div>
                        {gap.why ? (
                          <p className="mt-1 text-xs text-muted-foreground">{gap.why}</p>
                        ) : null}
                        {gap.similar_skills_user_has?.length ? (
                          <p className="mt-1 text-xs text-muted-foreground">
                            Closest thing you have: {gap.similar_skills_user_has.join(', ')}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  {report?.summary ? (
                    <p className="mt-2 text-xs text-muted-foreground">{report.summary}</p>
                  ) : null}
                </section>
              ) : gapsSection ? (
                <p className="text-sm text-muted-foreground">
                  {gapsSection.explanation ?? 'No critical gaps found against this advert.'}
                </p>
              ) : null}

              {analysis.nodes_failed?.length ? (
                <p className="text-xs text-muted-foreground">
                  Some steps did not complete: {analysis.nodes_failed.join(', ')}. The sections
                  they would have filled are missing rather than guessed.
                </p>
              ) : null}
            </div>
          ) : (
            <Button onClick={handleAnalyse} disabled={!job.description} className="w-full">
              Run full analysis
            </Button>
          )}

          <Button
            variant="outline"
            onClick={handlePrepare}
            disabled={!job.description}
            className="w-full"
          >
            <MessageCircleQuestion className="size-4" aria-hidden />
            Prepare for this interview
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('mt-0.5 text-sm font-medium', value === null && 'text-muted-foreground')}>
        {value === null ? 'Not stated' : value}
      </p>
    </div>
  );
}
