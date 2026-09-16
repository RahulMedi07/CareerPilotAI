import { AlertCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * `message` has no default on purpose.
 *
 * "Something went wrong" tells a reader nothing they can act on. Every caller
 * has a real reason available from `describeApiError`, so passing one is
 * required rather than optional.
 */
export function ErrorMessage({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900/40 dark:bg-red-950/30"
    >
      <div className="flex gap-3">
        <AlertCircle className="mt-0.5 size-5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
        <div className="flex-1">
          <p className="text-sm text-red-900 dark:text-red-200">{message}</p>
          {onRetry ? (
            <Button
              variant="link"
              size="sm"
              onClick={onRetry}
              className="mt-1 h-auto p-0 text-red-700 dark:text-red-300"
            >
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
