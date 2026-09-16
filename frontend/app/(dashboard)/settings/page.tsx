'use client';

import { useEffect, useState } from 'react';
import { FileText, Monitor, Moon, Sun, Trash2, Upload, UserRound } from 'lucide-react';

import { useAuth } from '@/components/providers/AuthProvider';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useDarkMode } from '@/hooks/useDarkMode';
import {
  clearIndex,
  describeApiError,
  getHealth,
  getIndexStatus,
  uploadResume,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import type { HealthReport, IndexStatus } from '@/types';

/** Mirrors `ALLOWED_EXTENSIONS` and `MAX_UPLOAD_SIZE_MB` in `backend/config.py`. */
const ACCEPTED = '.pdf,.docx,.txt,.md';
const MAX_BYTES = 10 * 1024 * 1024;

const THEMES = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const;

/**
 * Every control on this page changes something real.
 *
 * The brief asked for a profile form (full name, email, password), four
 * notification switches, a Logout button and a Delete Account button. There is
 * a user table and a session now, so signing out is real and the account card
 * shows who you are. The rest still has nothing behind it: the backend has no
 * change-password or delete-account endpoint, and no mail or push of any kind.
 * Wiring those to `useState` would produce controls that look like they work
 * and do not -- the same failure as a metric that reads 0% because the key was
 * misspelled, except here a person would type their real password into it
 * first.
 *
 * So this page settles for what the backend actually exposes: the resume
 * index, the theme, and the signed-in account. The account
 * card says plainly why the rest is missing rather than implying it lives
 * elsewhere.
 *
 * Health is fetched but not displayed while it is fine. A panel of probe
 * names, timings and an API address is a developer's view of the app, and
 * nobody opens Settings to read one -- no shopping site shows you its
 * database latency. It surfaces only as a plain sentence when something is
 * genuinely broken.
 */
export default function SettingsPage() {
  const { mounted, theme, resolvedTheme, setTheme } = useDarkMode();
  const { account, signOut } = useAuth();

  const [index, setIndex] = useState<IndexStatus | null>(null);
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    getIndexStatus()
      .then((status) => {
        if (!cancelled) setIndex(status);
      })
      .catch(() => {
        // The outage notice covers an unreachable backend. A second red
        // banner for the same outage is noise.
        if (!cancelled) setIndex(null);
      });

    getHealth()
      .then((report) => {
        if (cancelled) return;
        setHealth(report);
        setHealthError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setHealth(null);
        setHealthError(describeApiError(err));
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const refresh = () => setReloadKey((key) => key + 1);

  // Said in terms of what the person loses, not which probe failed. `degraded`
  // is worth a word because the assistant quietly answers from rules instead
  // of the model, and that is a change someone would otherwise blame on
  // themselves.
  const outage =
    healthError !== null
      ? 'Cannot reach the server right now. Nothing you have saved is lost.'
      : health?.overall_status === 'unhealthy'
        ? 'Part of the app is not working, so some pages may fail to load.'
        : health?.overall_status === 'degraded'
          ? 'The AI assistant is unavailable, so its answers will be simpler than usual. Everything else works normally.'
          : null;

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Checked here as well as on the server so the reader finds out before a
    // 10MB round trip, not after it.
    if (file.size > MAX_BYTES) {
      setError(`${file.name} is larger than the 10MB limit.`);
      event.target.value = '';
      return;
    }

    setBusy(true);
    setError(null);

    try {
      await uploadResume(file);
      refresh();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
      // Reset the input so re-picking the same file fires a change event.
      event.target.value = '';
    }
  };

  const handleClear = async () => {
    setBusy(true);
    setError(null);

    try {
      await clearIndex();
      setConfirmClear(false);
      refresh();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const indexed = index?.resume_indexed ?? false;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Settings</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          What this app has stored, how it looks, and who you are signed in as.
        </p>
      </header>

      {error ? <ErrorMessage message={error} /> : null}

      {/* Health is checked, but silence is the success case. A working app
          does not report on itself; it just works. This speaks up only when
          something is actually broken, and says what the person can do. */}
      {outage ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4">
          <p className="text-sm font-medium">{outage}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={refresh}>
            Try again
          </Button>
        </div>
      ) : null}

      {/* ------------------------------------------------------------------ */}
      {/* Resume index                                                        */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="size-5" aria-hidden />
            Resume
          </CardTitle>
          <CardDescription>
            Uploading another resume <strong>adds</strong> to what is already here rather than
            replacing it, and your job matches are then scored against all of them at once. Remove
            what is here first if you meant to swap.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
            <Badge variant={indexed ? 'default' : 'secondary'}>
              {indexed ? 'Saved' : 'Not uploaded yet'}
            </Badge>
            <p className="text-sm text-muted-foreground">
              {indexed
                ? 'Your resume is saved. Every job match and interview question is built from it.'
                : index
                  ? 'Upload your resume to get job matches and interview questions.'
                  : 'Could not load your resume.'}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {/* Same id/htmlFor pairing the analyse page uses: a file input
                cannot be opened programmatically without a user gesture, so
                the label is the control and the input stays screen-reader
                reachable rather than `display: none`. */}
            <input
              type="file"
              id="settings-resume-upload"
              accept={ACCEPTED}
              onChange={handleUpload}
              disabled={busy}
              className="sr-only"
            />
            <label
              htmlFor="settings-resume-upload"
              className={cn(
                buttonVariants({ variant: 'outline' }),
                busy ? 'pointer-events-none opacity-50' : 'cursor-pointer',
              )}
            >
              <Upload className="size-4" aria-hidden />
              {/* Not "Replace resume". `index_resume` writes the new chunks
                  under a fresh document id and never clears the old ones, so a
                  button promising a replacement would describe the opposite of
                  what the click does. */}
              {busy ? 'Working…' : indexed ? 'Add another resume' : 'Upload resume'}
            </label>

            {/* Clearing is irreversible and the backend has no undo, so it
                costs two deliberate clicks rather than one stray one. */}
            {confirmClear ? (
              <>
                <Button variant="destructive" onClick={handleClear} disabled={busy}>
                  <Trash2 className="size-4" aria-hidden />
                  Yes, remove it
                </Button>
                <Button variant="ghost" onClick={() => setConfirmClear(false)} disabled={busy}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                onClick={() => setConfirmClear(true)}
                disabled={busy || !indexed}
              >
                <Trash2 className="size-4" aria-hidden />
                Remove resume
              </Button>
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            .pdf, .docx, .txt or .md · up to 10MB. Your file is read on the computer running this
            app and is not sent anywhere else.
          </p>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Appearance                                                          */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>
            Stored in this browser, not on your account, so signing in elsewhere
            starts from your system setting again.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Until next-themes has read localStorage the active theme is
              genuinely unknown. Highlighting a guess and correcting it a frame
              later is worse than highlighting nothing for one frame. */}
          <div role="group" aria-label="Theme" className="flex flex-wrap gap-2">
            {THEMES.map(({ value, label, icon: Icon }) => {
              const active = mounted && theme === value;
              return (
                <Button
                  key={value}
                  variant={active ? 'default' : 'outline'}
                  onClick={() => setTheme(value)}
                  aria-pressed={mounted ? active : undefined}
                  className="flex-1"
                >
                  <Icon className="size-4" aria-hidden />
                  {label}
                </Button>
              );
            })}
          </div>

          <p className="text-sm text-muted-foreground">
            {!mounted
              ? 'Reading your saved preference…'
              : theme === 'system'
                ? `Following your operating system, which is currently ${resolvedTheme ?? 'unknown'}.`
                : `Fixed to ${theme}, whatever your operating system is set to.`}
          </p>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Account                                                             */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserRound className="size-5" aria-hidden />
            Account
          </CardTitle>
          <CardDescription>{account?.email ?? 'Signed in'}</CardDescription>
        </CardHeader>

        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            You are signed in as{' '}
            <span className="font-medium text-foreground">
              {account?.name || account?.email}
            </span>
            . Your resume, saved jobs and applications are private to this account. Nobody else
            signing in can see them.
          </p>
          <p>
            Your password is never stored in a readable form, and signing out ends the session
            everywhere rather than only forgetting it in this browser.
          </p>
          {/* Saying what is missing beats a control that looks real and
              silently drops what someone typed into it. */}
          <p>
            Changing your password, deleting your account, email reminders, and removing saved
            jobs one at a time are not available yet. They are not hidden away somewhere — they
            are not built, and a form that quietly did nothing would be worse than none.
          </p>

          <Button variant="outline" onClick={() => void signOut()}>
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
