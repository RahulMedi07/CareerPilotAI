'use client';

import { ExternalLink } from 'lucide-react';

/*
  Links out to the big job boards, which this app is not allowed to read.

  LinkedIn, Indeed, Naukri and Foundit all forbid automated collection, and
  Wellfound publishes no open feed either -- `CLOSED_JOB_BOARDS` in
  `agents/job_scraper.py` records the specific prohibition for each. That is a
  rule about programs reading their listings, not about people: opening a
  pre-filled search in your own browser, signed in as yourself, is exactly
  what the sites are for.

  So the search term travels, and nothing else does. No credentials, no
  automation, no results coming back into the app. The India filter and the
  seven-day window are set through each site's own published query parameters
  so the page you land on matches the one you left.
*/

/*
  Best effort by nature: these are the sites' public search parameters, and a
  site is free to rename one. If that happens the extra filter is ignored and
  the link still lands on a search for the right words, which is a soft
  failure rather than a broken button.
*/
const BOARDS: { name: string; url: (query: string) => string; note: string }[] = [
  {
    name: 'LinkedIn',
    // f_TPR=r604800 is "past week" expressed in seconds.
    url: (q) =>
      `https://www.linkedin.com/jobs/search/?keywords=${q}&location=India&f_TPR=r604800`,
    note: 'Past week · India',
  },
  {
    name: 'Naukri',
    url: (q) => `https://www.naukri.com/jobs-in-india?k=${q}&jobAge=7`,
    note: 'Last 7 days · India',
  },
  {
    name: 'Indeed',
    url: (q) => `https://in.indeed.com/jobs?q=${q}&l=India&fromage=7`,
    note: 'Last 7 days · India',
  },
  {
    name: 'Foundit',
    url: (q) => `https://www.foundit.in/srp/results?query=${q}&locations=India`,
    note: 'India',
  },
  {
    name: 'Wellfound',
    url: (q) => `https://wellfound.com/jobs?query=${q}&location=india`,
    note: 'Startups · India',
  },
];

export function SearchElsewhere({ query }: { query: string }) {
  const trimmed = query.trim();
  if (!trimmed) return null;

  // Encoded once, here, so a term containing & or # cannot reshape the URL.
  const encoded = encodeURIComponent(trimmed);

  return (
    <section className="rounded-lg border bg-muted/30 p-4">
      <h2 className="text-sm font-medium">Keep looking on the big boards</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        These sites do not let a program read their listings, so their jobs cannot appear
        above. Opening one searches <span className="font-medium">{trimmed}</span> there
        yourself, in a new tab.
      </p>

      <ul className="mt-3 flex flex-wrap gap-2">
        {BOARDS.map((board) => (
          <li key={board.name}>
            <a
              href={board.url(encoded)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
              title={board.note}
            >
              {board.name}
              <ExternalLink className="size-3 opacity-60" aria-hidden />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
