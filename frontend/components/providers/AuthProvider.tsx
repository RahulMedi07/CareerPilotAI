'use client';

import { useRouter } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';

import { describeApiError, getAccount, login as apiLogin, logout as apiLogout, signup as apiSignup } from '@/lib/api';
import type { Account } from '@/types';

interface AuthState {
  /** The signed-in account, or null when signed out. */
  account: Account | null;
  /** True until the first `/auth/me` answers. See the note below. */
  loading: boolean;
  /** Set when the backend could not be reached at all -- not on a 401. */
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/**
 * Holds the answer to "who is signed in", asked once on load.
 *
 * The session is an httpOnly cookie, so this cannot inspect it directly and
 * must ask the backend. That is why `loading` exists and why it starts true:
 * for one render the app genuinely does not know, and a guard that treats
 * "don't know yet" as "signed out" would bounce every returning user to the
 * login page before their session had been checked.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    getAccount()
      .then((found) => {
        if (cancelled) return;
        setAccount(found);
        setError(null);
      })
      .catch((err) => {
        // Reaching here means the backend is unreachable or broken -- a 401
        // resolves to null instead. Recording it separately stops the UI
        // saying "please sign in" when the real problem is a dead server.
        if (!cancelled) setError(describeApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setAccount(await apiLogin(email, password));
  }, []);

  const signUp = useCallback(async (email: string, password: string, name: string) => {
    setAccount(await apiSignup(email, password, name));
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Cleared even if the request failed. The alternative is a UI that
      // still shows someone signed in after they asked to leave, which is
      // worse on a shared machine than a server-side row outliving the click.
      setAccount(null);
      router.push('/login');
    }
  }, [router]);

  return (
    <AuthContext.Provider value={{ account, loading, error, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return context;
}
