'use client';

import { ThemeProvider as NextThemesProvider } from 'next-themes';
import type { ComponentProps } from 'react';

/**
 * Thin wrapper around next-themes.
 *
 * This exists as its own file for one structural reason: next-themes needs
 * `'use client'`, and the root layout must stay a Server Component so it can
 * keep exporting `metadata`. A file cannot do both, so the client boundary is
 * pushed down to here and the layout imports it as a normal component.
 *
 * `attribute="class"` matches the `dark` custom variant declared in
 * globals.css, which is scoped to descendants of `.dark`.
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
