'use client';

import { useSyncExternalStore } from 'react';
import { useTheme } from 'next-themes';

/**
 * Never notifies, because the value it reports never changes after
 * hydration. `useSyncExternalStore` still needs a subscribe function, so this
 * one registers nothing and unsubscribes nothing.
 */
const subscribeToNothing = () => () => {};

/**
 * Reading the active theme without causing a hydration mismatch.
 *
 * The server cannot know which theme the browser will pick, so the first
 * client render has to match the server's markup exactly. The usual
 * `useState(false)` + `useEffect(() => setMounted(true))` pair does this, but
 * React's lint rules now reject setting state synchronously in an effect.
 * `useSyncExternalStore` expresses the same thing directly: it returns the
 * server snapshot (`false`) during render and hydration, and the client
 * snapshot (`true`) afterwards.
 *
 * Until `mounted` is true the theme is reported as undefined, and callers are
 * expected to render something neutral rather than guess at a sun or a moon.
 */
export function useDarkMode() {
  const { theme, resolvedTheme, setTheme } = useTheme();

  const mounted = useSyncExternalStore(
    subscribeToNothing,
    () => true,
    () => false,
  );

  return {
    mounted,
    theme: mounted ? theme : undefined,
    resolvedTheme: mounted ? resolvedTheme : undefined,
    isDark: mounted ? resolvedTheme === 'dark' : undefined,
    setTheme,
    toggle: () => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark'),
  };
}
