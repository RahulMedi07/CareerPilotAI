import { Loader2 } from 'lucide-react';

export function LoadingSpinner({ message = 'Loading…' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12" role="status">
      <Loader2 className="mb-2 size-8 animate-spin text-blue-600" aria-hidden />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
