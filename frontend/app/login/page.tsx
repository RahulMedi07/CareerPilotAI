import { Suspense } from 'react';

import { AuthForm } from '@/components/auth/AuthForm';

/**
 * Wrapped in Suspense because `AuthForm` reads the `next` query parameter
 * with `useSearchParams`, which Next requires a boundary around.
 */
export default function LoginPage() {
  return (
    <Suspense>
      <AuthForm mode="login" />
    </Suspense>
  );
}
