import type { LucideIcon } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface StatCardProps {
  label: string;
  /**
   * `null` means the backend declined to report this number, and is rendered
   * as `emptyText` rather than as zero. This distinction is the whole point
   * of the component: an interview rate of null is "not enough applications
   * yet", and showing 0% would be a claim the data does not support.
   */
  value: string | number | null | undefined;
  icon?: LucideIcon;
  hint?: string;
  emptyText?: string;
  className?: string;
}

export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  emptyText = 'Not enough data yet',
  className,
}: StatCardProps) {
  const missing = value === null || value === undefined || value === '';

  return (
    <Card className={cn('card-hover', className)}>
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p
            className={cn(
              'mt-1 truncate font-semibold',
              missing ? 'text-base text-muted-foreground' : 'text-2xl',
            )}
          >
            {missing ? emptyText : value}
          </p>
          {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        {Icon ? <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden /> : null}
      </CardContent>
    </Card>
  );
}
