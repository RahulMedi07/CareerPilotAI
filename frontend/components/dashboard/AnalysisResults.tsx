'use client';

import { AlertCircle, BookOpen, CheckCircle2, Lock, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import type { AnalysisResult, Gap } from '@/types';

/**
 * The full-analysis result, read from where the fields actually are.
 *
 * The design sketch reached for `analysis.overallMatch`, `analysis.gaps` as an
 * array, `analysis.optimizations` as an array of strings and
 * `gap.learningDays`. None of those exist. The response nests one level -- the
 * sections live under `analysis.analysis` -- uses snake_case throughout, and
 * `gaps` is an object whose `gap_report.critical_gaps` holds the list.
 */

const RECOMMENDATION_TONE: Record<string, string> = {
  APPLY: 'border-green-300 bg-green-50 text-green-900 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-200',
  MAYBE: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200',
  SKIP: 'border-red-300 bg-red-50 text-red-900 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200',
  // Neutral on purpose. Nothing was measured, so neither encouragement nor
  // discouragement would be earned.
  NOT_SCORED: 'border-border bg-muted/40 text-foreground',
};

const DIMENSION_LABELS: Record<string, string> = {
  skills: 'Skills',
  tech_stack: 'Tech stack',
  experience: 'Experience',
  education: 'Education',
  soft_skills: 'Soft skills',
};

/**
 * `missing` arrives as a string array on the skill dimensions and as a plain
 * string on experience and education. Both have to be handled; assuming an
 * array threw `dimension.missing.join is not a function` the first time this
 * component met a real response.
 */
function describeList(value: string[] | string | undefined): string | null {
  if (typeof value === 'string') return value.trim() ? value : null;
  if (Array.isArray(value) && value.length > 0) return value.join(', ');
  return null;
}

function GapRow({ gap }: { gap: Gap }) {
  return (
    <li className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="font-medium">{gap.skill}</span>
        <div className="flex items-center gap-2">
          {gap.importance ? (
            <Badge variant={gap.importance === 'CRITICAL' ? 'destructive' : 'secondary'}>
              {gap.importance}
            </Badge>
          ) : null}
          {/* A missing estimate is left blank rather than printed as 0 days. */}
          {typeof gap.learning_time_days === 'number' ? (
            <span className="text-xs text-muted-foreground">~{gap.learning_time_days} days</span>
          ) : null}
        </div>
      </div>

      {gap.why ? <p className="mt-1 text-sm text-muted-foreground">{gap.why}</p> : null}

      {gap.similar_skills_user_has && gap.similar_skills_user_has.length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Closest things you already have: {gap.similar_skills_user_has.join(', ')}
        </p>
      ) : null}
    </li>
  );
}

export function AnalysisResults({ analysis }: { analysis: AnalysisResult }) {
  const sections = analysis.analysis ?? {};
  const gapsSection = sections.gaps;
  const report = gapsSection?.gap_report;
  const criticalGaps = report?.critical_gaps ?? [];
  const niceToHaveGaps = report?.nice_to_have_gaps ?? [];
  const optimisations = sections.resume_optimizations;
  const prep = sections.interview_prep;
  const breakdown = sections.match_breakdown ?? {};

  const tone = RECOMMENDATION_TONE[analysis.recommendation] ?? RECOMMENDATION_TONE.MAYBE;

  return (
    <div className="space-y-4">
      <Card className={tone}>
        <CardContent className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium opacity-75">Match score</p>
              {/*
                A null score means the advert stated nothing measurable, so
                every row of the breakdown below reads "Not counted". Printing
                `0%` here claimed a measurement that was never taken, and put a
                red SKIP on a job the app had not actually assessed.
              */}
              <p className="text-4xl font-bold tabular-nums">
                {typeof analysis.overall_match === 'number'
                  ? `${analysis.overall_match}%`
                  : 'Not scored'}
              </p>
            </div>
            <Badge variant="outline" className="border-current px-3 py-1 text-base">
              {analysis.recommendation === 'NOT_SCORED'
                ? 'NO VERDICT'
                : analysis.recommendation}
            </Badge>
          </div>

          {/*
            The backend writes a sentence explaining its own verdict. Showing
            that instead of a canned "This role matches your profile well"
            means the reason on screen is the reason the graph actually used.
          */}
          <p className="text-sm">{analysis.user_recommendation}</p>
        </CardContent>
      </Card>

      {Object.keys(breakdown).length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Where the score came from</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(breakdown).map(([key, dimension]) => {
              const missing = describeList(dimension.missing);
              const explanation = dimension.reason ?? dimension.note;

              return (
                <div key={key}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span>{DIMENSION_LABELS[key] ?? key}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {dimension.applicable ? (
                        <>
                          {Math.round(dimension.score)}%
                          <span className="ml-2 text-xs">
                            weight {Math.round((dimension.weight ?? 0) * 100)}%
                          </span>
                        </>
                      ) : (
                        // Not applicable is not a zero score: the advert said
                        // nothing about this dimension, so it is excluded from
                        // the total rather than counted against you.
                        <span className="text-xs">Not counted</span>
                      )}
                    </span>
                  </div>

                  {dimension.applicable ? (
                    <Progress value={dimension.score} className="mt-1" />
                  ) : null}

                  {explanation ? (
                    <p className="mt-1 text-xs text-muted-foreground">{explanation}</p>
                  ) : dimension.applicable && missing ? (
                    <p className="mt-1 text-xs text-muted-foreground">Missing: {missing}</p>
                  ) : null}
                </div>
              );
            })}
          </CardContent>
        </Card>
      ) : null}

      {criticalGaps.length > 0 || niceToHaveGaps.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertCircle className="size-4 text-amber-600" aria-hidden />
              Skill gaps
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {gapsSection?.source === 'fallback' ? (
              <p className="text-xs text-muted-foreground">
                The AI was not available, so these come from comparing your skills to the advert
                directly rather than AI reading it.
              </p>
            ) : null}

            {criticalGaps.length > 0 ? (
              <ul className="space-y-2">
                {criticalGaps.map((gap) => (
                  <GapRow key={gap.skill_id ?? gap.skill} gap={gap} />
                ))}
              </ul>
            ) : null}

            {niceToHaveGaps.length > 0 ? (
              <>
                <p className="pt-1 text-sm font-medium">Nice to have</p>
                <ul className="space-y-2">
                  {niceToHaveGaps.map((gap) => (
                    <GapRow key={gap.skill_id ?? gap.skill} gap={gap} />
                  ))}
                </ul>
              </>
            ) : null}

            {report?.summary ? (
              <p className="border-t pt-3 text-sm text-muted-foreground">{report.summary}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {optimisations ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CheckCircle2 className="size-4 text-green-600" aria-hidden />
              Resume changes
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {optimisations.improvements && optimisations.improvements.length > 0 ? (
              <ul className="space-y-3">
                {optimisations.improvements.map((improvement, index) => (
                  <li key={`${improvement.section}-${index}`} className="rounded-md border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium">{improvement.section}</span>
                      {improvement.impact ? (
                        <Badge variant={improvement.impact === 'HIGH' ? 'default' : 'secondary'}>
                          {improvement.impact} impact
                        </Badge>
                      ) : null}
                    </div>
                    {improvement.suggested ?? improvement.suggested_description ? (
                      <p className="mt-2 text-sm">
                        {improvement.suggested ?? improvement.suggested_description}
                      </p>
                    ) : null}
                    {improvement.why ? (
                      <p className="mt-1 text-xs text-muted-foreground">{improvement.why}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No rewrites suggested. That is a result, not a blank: the optimiser only proposes
                wording it can support from what your resume already says.
              </p>
            )}

            {optimisations.keywords_to_add && optimisations.keywords_to_add.length > 0 ? (
              <div>
                <p className="text-sm font-medium">Keywords worth adding</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {optimisations.keywords_to_add.map((keyword) => (
                    <Badge key={keyword} variant="secondary">
                      {keyword}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {/*
              These are deliberately NOT in keywords_to_add. The advert wants
              them and the resume cannot evidence them, so suggesting them
              would be suggesting a lie. They are shown as blocked instead.
            */}
            {optimisations.keywords_blocked_by_gaps &&
            optimisations.keywords_blocked_by_gaps.length > 0 ? (
              <div>
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <Lock className="size-3.5 text-muted-foreground" aria-hidden />
                  Wanted by the advert, but not yours to claim
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {optimisations.keywords_blocked_by_gaps.map((keyword) => (
                    <Badge key={keyword} variant="outline">
                      {keyword}
                    </Badge>
                  ))}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Learn them and they move to the list above. Until then they stay off your resume.
                </p>
              </div>
            ) : null}

            {optimisations.tailored_summary ? (
              <div>
                <p className="text-sm font-medium">Suggested summary</p>
                <p className="mt-1 rounded-md bg-muted p-3 text-sm">
                  {optimisations.tailored_summary}
                </p>
              </div>
            ) : null}

            {optimisations.honesty_note ? (
              <p className="border-t pt-3 text-xs text-muted-foreground">
                {optimisations.honesty_note}
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {prep ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookOpen className="size-4 text-blue-600" aria-hidden />
              Interview prep
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              {prep.interview_difficulty ? (
                <Badge variant="outline">{prep.interview_difficulty}</Badge>
              ) : null}
              {typeof prep.question_count === 'number' ? (
                <Badge variant="outline">{prep.question_count} questions</Badge>
              ) : null}
              {typeof prep.prep_days === 'number' ? (
                <Badge variant="outline">{prep.prep_days} days of prep</Badge>
              ) : null}
              {/*
                success_rate_prediction is a fraction (0.05), not a percentage.
                Printing it raw would read "0.05%".
              */}
              {typeof prep.success_rate_prediction === 'number' ? (
                <Badge variant="outline">
                  {Math.round(prep.success_rate_prediction * 100)}% predicted success
                </Badge>
              ) : null}
            </div>

            {prep.questions && prep.questions.length > 0 ? (
              <ul className="space-y-2">
                {prep.questions.slice(0, 3).map((question, index) => (
                  <li key={question.id ?? index} className="rounded-md bg-muted p-2">
                    <p className="text-sm font-medium">{question.question}</p>
                    {question.why_asked ? (
                      <p className="mt-0.5 text-xs text-muted-foreground">{question.why_asked}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}

            {prep.questions && prep.questions.length > 3 ? (
              <p className="text-xs text-muted-foreground">
                +{prep.questions.length - 3} more, including{' '}
                {prep.gap_question_count ?? 0} built around your gaps.
              </p>
            ) : null}

            {prep.honesty_note ? (
              <p className="border-t pt-3 text-xs text-muted-foreground">{prep.honesty_note}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/*
        The sketch ended with a "Save & Apply" button. There is nothing for it
        to call: create-application needs a job_id from a discovery result, and
        a pasted advert has no id. A button that only looked like it worked
        would be worse than no button, so the honest route is named instead.
      */}
      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        To track this as an application, find the advert on Discover Jobs and save it there — an
        application has to hang off a real job record, and a pasted description has no id.
      </p>
    </div>
  );
}
