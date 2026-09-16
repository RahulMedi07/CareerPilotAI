'use client';

import Link from 'next/link';
import { LogOut, Moon, Sun } from 'lucide-react';

import { useAuth } from '@/components/providers/AuthProvider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useDarkMode } from '@/hooks/useDarkMode';

/**
 * Top bar: product name, build mode, who is signed in, theme toggle, sign out.
 *
 * The sign-out button used to be refused on the grounds that ending a session
 * that was never started would be a lie. There is a real session now, so the
 * button is the honest thing and its absence would be the surprise -- people
 * look for it here, not three clicks away in Settings.
 */
export function Header() {
  const { mounted, isDark, toggle } = useDarkMode();
  const { account, signOut } = useAuth();

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b bg-background/80 px-4 backdrop-blur-md sm:px-6">
      <div className="flex items-center gap-3">
        <Link href="/" className="text-lg font-semibold sm:text-xl">
          <span className="gradient-text">CareerPilot AI</span>
        </Link>
        <Badge
          variant="secondary"
          title="Everything runs on this computer. Your resume is not sent anywhere else."
          className="hidden sm:inline-flex"
        >
          Local mode
        </Badge>
      </div>

      <div className="flex items-center gap-1 sm:gap-2">
        {/* Nothing is shown while the account is still being fetched: a name
            that appears and then changes reads as a bug. */}
        {account ? (
          <span
            className="hidden max-w-[14rem] truncate text-sm text-muted-foreground md:inline"
            title={account.email}
          >
            {account.name || account.email}
          </span>
        ) : null}

        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          // Before the mount effect runs the browser's theme is unknown, so
          // the label stays generic rather than naming the wrong direction.
          aria-label={
            mounted ? (isDark ? 'Switch to light theme' : 'Switch to dark theme') : 'Toggle theme'
          }
        >
          {/* Both icons are rendered and cross-faded with CSS, so the server
              and the first client render produce identical markup. */}
          <Sun className="size-4 scale-100 rotate-0 transition-transform dark:scale-0 dark:-rotate-90" aria-hidden />
          <Moon className="absolute size-4 scale-0 rotate-90 transition-transform dark:scale-100 dark:rotate-0" aria-hidden />
        </Button>

        {account ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={signOut}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" aria-hidden />
          </Button>
        ) : null}
      </div>
    </header>
  );
}
