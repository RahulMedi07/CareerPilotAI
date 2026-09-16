import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AuthProvider } from "@/components/providers/AuthProvider";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CareerPilot AI",
  description: "Score your resume against a job advert, then act on the result.",
};

/**
 * This file is deliberately a Server Component.
 *
 * A layout cannot both declare `'use client'` and export `metadata`; Next
 * rejects the combination at build time. The client-only work lives in
 * ThemeProvider, which this file renders as a child.
 *
 * The Sidebar and Header are not here either. They belong to the application
 * shell, so they live in app/(dashboard)/layout.tsx -- putting them here
 * would wrap the auth pages in the navigation they are supposed to precede.
 *
 * `suppressHydrationWarning` is required by next-themes: it sets the theme
 * class on <html> before React hydrates, so that attribute legitimately
 * differs between the server markup and the first client read.
 *
 * `data-scroll-behavior="smooth"` acknowledges the `scroll-behavior: smooth`
 * rule in globals.css. Without it Next warns on every navigation, because it
 * scrolls the document itself on a route change and a smooth scroll there
 * animates rather than jumping. The attribute says the behaviour is intended.
 *
 * AuthProvider wraps everything, including the login page -- that page needs
 * `useAuth` to sign in. The guard that actually keeps signed-out visitors out
 * is separate, and lives on the dashboard layout.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
