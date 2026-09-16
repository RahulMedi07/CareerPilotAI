'use client';

import { AlertCircle, CheckCircle2, Clock, Loader2, MinusCircle } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ExecutionTraceStep } from '@/types';

/**
 * The nine-node workflow, drawn as a timeline.
 *
 * The trace is the point of the project: it is the record of which agent ran,
 * in what order, how long it took and what it concluded. Rendering only the
 * node name and a duration would throw away `detail`, which is the one field
 * that says *why* the graph did what it did -- "score 32.5/100 -> SKIP",
 * "no truthful additions; score unchanged". Those lines are shown.
 *
 * The design sketch read `event.durationMs` and `event.node`. The API sends
 * `duration_ms`, and it sends a human-readable `label` alongside the raw
 * `node`; `label` is preferred and `node` is kept as the technical caption.
 */

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed' || status === 'success') {
    return <CheckCircle2 className="size-5 shrink-0 text-green-600 dark:text-green-500" />;
  }
  if (status === 'running' || status === 'in_progress') {
    return <Loader2 className="size-5 shrink-0 animate-spin text-blue-600 dark:text-blue-500" />;
  }
  if (status === 'skipped') {
    return <MinusCircle className="size-5 shrink-0 text-muted-foreground" />;
  }
  // Anything unrecognised is treated as a problem rather than quietly styled
  // as a success.
  return <AlertCircle className="size-5 shrink-0 text-red-600 dark:text-red-500" />;
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  if (ms >= 10) return `${Math.round(ms)}ms`;
  // Sub-10ms nodes really do run in hundredths of a millisecond; rounding
  // them to "0ms" would suggest they did not run at all.
  return `${ms.toFixed(2)}ms`;
}

export function AgentTraceViewer({
  trace,
  totalMs,
  nodesFailed = [],
}: {
  trace: ExecutionTraceStep[];
  /** The backend's own total. Summing the steps would miss the time between them. */
  totalMs?: number;
  nodesFailed?: string[];
}) {
  if (!trace || trace.length === 0) return null;

  const summedMs = trace.reduce((total, step) => total + (step.duration_ms ?? 0), 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">How this was worked out</CardTitle>
      </CardHeader>

      <CardContent>
        <ol className="space-y-0">
          {trace.map((step, index) => (
            <li key={`${step.step}-${step.node}`} className="flex gap-3">
              <div className="flex flex-col items-center">
                <StatusIcon status={step.status} />
                {index < trace.length - 1 ? (
                  <div className="my-1 w-px flex-1 bg-border" aria-hidden />
                ) : null}
              </div>

              <div className={index < trace.length - 1 ? 'flex-1 pb-5' : 'flex-1'}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <p className="text-sm font-medium">
                    {step.step}. {step.label ?? step.node}
                  </p>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground tabular-nums">
                    <Clock className="size-3" aria-hidden />
                    {formatMs(step.duration_ms ?? 0)}
                  </span>
                </div>

                {step.detail ? (
                  <p className="mt-0.5 text-sm text-muted-foreground">{step.detail}</p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-4 space-y-1 border-t pt-4 text-sm text-muted-foreground">
          <p>
            {/*
              Two numbers, because they answer different questions. The summed
              node time is how long the agents worked; the reported total also
              includes the graph's own overhead. Showing only the sum would
              quietly under-report the wall clock.
            */}
            {trace.length} steps · {formatMs(summedMs)} of work
            {typeof totalMs === 'number' ? ` · ${formatMs(totalMs)} in total` : ''}
          </p>

          {nodesFailed.length > 0 ? (
            <p className="text-red-600 dark:text-red-400">
              Some steps did not finish, so the result below is missing whatever they were meant
              to work out.
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
