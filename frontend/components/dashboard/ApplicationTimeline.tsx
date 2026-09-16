'use client';

import { CheckCircle2, Circle, FileText, Send, Trophy, XCircle } from 'lucide-react';

import type { ApplicationEvent } from '@/types';

/**
 * An application's history, drawn in order.
 *
 * The event keys are `event` / `date` / `status` / `details` -- measured, not
 * assumed. `details` carries `from` and `to` on every status change alongside
 * whatever the caller passed, so those two are pulled out and rendered as the
 * transition rather than repeated in the generic key/value list.
 */

const EVENT_LABELS: Record<string, string> = {
  created: 'Application created',
  application_sent: 'Application sent',
  interview_scheduled: 'Interview scheduled',
  rejected: 'Rejected',
  offer_received: 'Offer received',
  status_changed: 'Status changed',
};

const STATUS_ICONS: Record<string, typeof Circle> = {
  draft: FileText,
  sent: Send,
  interview: CheckCircle2,
  rejected: XCircle,
  offer: Trophy,
};

const STATUS_TONES: Record<string, string> = {
  draft: 'text-muted-foreground',
  sent: 'text-blue-600 dark:text-blue-400',
  interview: 'text-amber-600 dark:text-amber-400',
  rejected: 'text-red-600 dark:text-red-400',
  offer: 'text-green-600 dark:text-green-400',
};

function humanise(key: string): string {
  return key.replace(/_/g, ' ').replace(/^./, (character) => character.toUpperCase());
}

function formatTimestamp(event: ApplicationEvent): string {
  // The full ISO timestamp is preferred because two events on the same day are
  // common; `date` alone would show them as simultaneous.
  const raw = event.timestamp ?? event.date;
  const parsed = new Date(raw);

  if (Number.isNaN(parsed.getTime())) return raw;

  return event.timestamp
    ? parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : parsed.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

export function ApplicationTimeline({ events }: { events: ApplicationEvent[] }) {
  if (!events || events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No history recorded. Every application gets at least a `created` entry, so an empty
        timeline means the record was written outside the normal path.
      </p>
    );
  }

  return (
    <ol>
      {events.map((event, index) => {
        const status = String(event.status ?? '');
        const Icon = STATUS_ICONS[status] ?? Circle;
        const tone = STATUS_TONES[status] ?? 'text-muted-foreground';

        const details = event.details ?? {};
        const from = details.from;
        const to = details.to;
        // `from`/`to` are rendered as the transition above, so they are not
        // repeated in the key/value list below.
        const rest = Object.entries(details).filter(([key]) => key !== 'from' && key !== 'to');

        return (
          <li key={`${event.timestamp ?? event.date}-${event.event}-${index}`} className="flex gap-3">
            <div className="flex flex-col items-center">
              <Icon className={`size-5 shrink-0 ${tone}`} aria-hidden />
              {index < events.length - 1 ? (
                <div className="my-1 w-px flex-1 bg-border" aria-hidden />
              ) : null}
            </div>

            <div className={index < events.length - 1 ? 'flex-1 pb-6' : 'flex-1'}>
              <p className="text-sm font-medium">
                {EVENT_LABELS[event.event] ?? humanise(event.event)}
              </p>
              <p className="text-xs text-muted-foreground">{formatTimestamp(event)}</p>

              {from && to ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {String(from)} &rarr; {String(to)}
                </p>
              ) : null}

              {rest.length > 0 ? (
                <dl className="mt-2 rounded-md bg-muted p-2 text-xs">
                  {rest.map(([key, value]) => (
                    <div key={key} className="flex gap-1.5">
                      <dt className="font-medium">{humanise(key)}:</dt>
                      <dd className="text-muted-foreground">{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
