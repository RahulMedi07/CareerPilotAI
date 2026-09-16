import { Cpu, Ruler } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * Says who wrote the thing next to it: a language model, or fixed rules.
 *
 * This exists because the two are indistinguishable on screen. Every analysis
 * in this app degrades to deterministic keyword matching when no model is
 * configured, and that fallback is good enough to look like intelligence
 * while being nothing of the sort. Hiding the difference would let the
 * interface imply a capability the machine does not have, so the difference
 * is rendered.
 *
 * `title` carries the longer explanation rather than a paragraph of body
 * copy, because this badge sits in card headers where there is no room.
 */
export function SourceBadge({ source, className }: { source: string; className?: string }) {
  const byModel = source === 'llm';
  const Icon = byModel ? Cpu : Ruler;

  return (
    <span
      title={
        byModel
          ? 'Written by AI.'
          : 'Built from your own resume by matching it against the job, not written by AI. The wording is fixed; the details are yours.'
      }
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        byModel
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300'
          : 'border-border bg-muted text-muted-foreground',
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {byModel ? 'AI-written' : 'Rule-based'}
    </span>
  );
}
