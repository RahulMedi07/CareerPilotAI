'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import { useAuth } from '@/components/providers/AuthProvider';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { describeApiError } from '@/lib/api';
import { MIN_PASSWORD_LENGTH } from '@/lib/auth-rules';

/**
 * The sign-in and sign-up form. One component, because the two differ by a
 * single field and duplicating them would let them drift apart.
 */
export function AuthForm({ mode }: { mode: 'login' | 'signup' }) {
  const isSignup = mode === 'signup';
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isSignup) {
        await signUp(email, password, name);
      } else {
        await signIn(email, password);
      }
      // `next` carries the page the guard interrupted, so signing in returns
      // you to where you were going rather than to the dashboard.
      router.push(params.get('next') ?? '/');
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-12">
      <h1 className="text-2xl font-semibold">
        {isSignup ? 'Create an account' : 'Sign in'}
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {isSignup
          ? 'Your resume, saved jobs and applications are kept to your account alone.'
          : 'Welcome back.'}
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        {isSignup ? (
          <div className="space-y-1.5">
            <label htmlFor="name" className="text-sm font-medium">
              Name <span className="text-muted-foreground">(optional)</span>
            </label>
            <Input
              id="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoComplete="name"
              maxLength={120}
            />
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <Input
            id="email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            maxLength={254}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <Input
            id="password"
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            // A browser that knows this is a new password offers to generate
            // and store a strong one. Getting this attribute wrong is the
            // difference between a password manager helping and hindering.
            autoComplete={isSignup ? 'new-password' : 'current-password'}
            // Only on signup. Enforcing a minimum on the sign-in form would
            // tell someone guessing which passwords are not worth trying.
            minLength={isSignup ? MIN_PASSWORD_LENGTH : undefined}
          />
          {isSignup ? (
            <p className="text-xs text-muted-foreground">
              At least {MIN_PASSWORD_LENGTH} characters. Length is what matters;
              a phrase you can remember beats a short jumble you cannot.
            </p>
          ) : null}
        </div>

        {error ? <ErrorMessage message={error} /> : null}

        <Button type="submit" disabled={busy} className="w-full">
          {busy ? 'Working…' : isSignup ? 'Create account' : 'Sign in'}
        </Button>
      </form>

      <p className="mt-6 text-sm text-muted-foreground">
        {isSignup ? (
          <>
            Already have an account?{' '}
            <Link href="/login" className="font-medium text-foreground underline">
              Sign in
            </Link>
          </>
        ) : (
          <>
            No account yet?{' '}
            <Link href="/signup" className="font-medium text-foreground underline">
              Create one
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
