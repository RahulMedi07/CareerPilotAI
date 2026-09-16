'use client';

import { useRouter, usePathname } from 'next/navigation';
import { useEffect } from 'react';

import { useAuth } from '@/components/providers/AuthProvider';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';

/**
 * Sends signed-out visitors to the login page.
 *
 * This is a convenience, not the security boundary. Anyone can edit the
 * JavaScript that runs here; what actually protects the data is that every
 * endpoint answers 401 without a session. The guard exists so a signed-out
 * visitor sees a login form instead of a dashboard full of failed requests.
 *
 * Three states, kept distinct on purpose:
 *   - still checking  -> a spinner, because bouncing now would eject a user
 *                        whose session is perfectly good
 *   - backend down    -> the error, because sending someone to a login page
 *                        that also cannot reach the server is a dead end
 *   - signed out      -> redirect, carrying where they were headed
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { account, loading, error } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !error && account === null) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [account, loading, error, pathname, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-md px-4 py-12">
        <ErrorMessage message={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }

  if (account === null) {
    // The redirect above is in flight. Rendering the dashboard for one frame
    // would flash its layout at someone not entitled to see it.
    return null;
  }

  return <>{children}</>;
}
