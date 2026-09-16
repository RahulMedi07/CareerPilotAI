/**
 * Carries one advert from a job result to the interview prep page.
 *
 * `sessionStorage` rather than a query parameter because adverts run to
 * several thousand characters, well past what a URL carries reliably, and
 * rather than a store because the two pages never exist at the same time.
 *
 * It is read once and cleared. A handoff left lying around would mean a later,
 * unrelated visit to interview prep silently built questions for a job the
 * user had already moved on from.
 */
const KEY = 'careerpilot:interview-advert';

export type InterviewHandoff = {
  title: string;
  company: string;
  description: string;
};

export function stashJobForInterview(job: InterviewHandoff): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(KEY, JSON.stringify(job));
}

/** Returns the stashed advert and removes it, or null if there is none. */
export function takeJobForInterview(): InterviewHandoff | null {
  if (typeof window === 'undefined') return null;

  const raw = window.sessionStorage.getItem(KEY);
  if (!raw) return null;
  window.sessionStorage.removeItem(KEY);

  try {
    const parsed = JSON.parse(raw) as Partial<InterviewHandoff>;
    // A description is the only field the prep endpoint actually needs; the
    // other two are labels. Without it there is nothing to hand over.
    if (!parsed?.description) return null;
    return {
      title: parsed.title ?? '',
      company: parsed.company ?? '',
      description: parsed.description,
    };
  } catch {
    return null;
  }
}
