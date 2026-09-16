import axios, { AxiosError } from 'axios';

import type {
  Account,
  AnalysisResult,
  AnalyticsResponse,
  ApplicationsResponse,
  ApplicationHistory,
  ChatMessage,
  ChatResponse,
  HealthReport,
  IndexStatus,
  InterviewPrepResult,
  PracticeFeedback,
  JobDiscoveryResponse,
  MyJobsResponse,
  ResumeInsights,
  SaveJobResponse,
} from '@/types';

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/**
 * One client, rooted at `/api`.
 *
 * The design sketch rooted it at `/api/career` and then called
 * `/health/full` through it, which resolves to `/api/career/health/full` --
 * a path the backend does not serve. The health routes live under `/api`
 * directly, so the base stops one segment earlier and every career route
 * carries its own `/career` prefix. That keeps a single instance, a single
 * interceptor, and no path that only works by accident.
 */
export const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000, // Full analysis runs several agents; 30s is not enough.
  // The session lives in an httpOnly cookie, which the browser will only
  // attach to a cross-origin request if asked. Without this every call after
  // signing in comes back 401. The cookie is httpOnly precisely so that this
  // file cannot read it -- a token in localStorage is readable by any script
  // that gets onto the page.
  withCredentials: true,
});

// `DEFAULT_USER_ID` used to live here, fixed at 'local'. It is gone: the
// backend now derives the account from the session cookie and ignores any id
// sent by the caller, so a constant here would be a comforting fiction.

/**
 * Turns an axios failure into something worth showing a person.
 *
 * FastAPI puts its reason in `detail`; falling straight through to
 * `error.message` would surface "Request failed with status code 422", which
 * tells the reader nothing they can act on.
 */
export function describeApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{ detail?: unknown }>;

    if (!axiosError.response) {
      return `Could not reach the backend at ${API_URL}. Is it running?`;
    }

    const detail = axiosError.response.data?.detail;

    if (typeof detail === 'string') {
      return detail;
    }

    if (Array.isArray(detail) && detail.length > 0) {
      // Pydantic validation errors arrive as a list of objects.
      const first = detail[0] as { msg?: string };
      if (first?.msg) {
        return first.msg;
      }
    }

    return `${axiosError.response.status} ${axiosError.response.statusText}`.trim();
  }

  return error instanceof Error ? error.message : 'Unknown error.';
}

// --------------------------------------------------------------------------
// Resume
// --------------------------------------------------------------------------

export async function uploadResume(file: File) {
  const form = new FormData();
  form.append('file', file);

  // The Content-Type header is deleted rather than overwritten: the browser
  // has to add the multipart boundary itself, and it will not do that if a
  // value is already present.
  const { data } = await api.post('/career/upload-resume', form, {
    headers: { 'Content-Type': undefined },
  });

  return data as { status: string; message: string; file_size: number };
}

export async function getIndexStatus() {
  const { data } = await api.get<IndexStatus>('/career/status');
  return data;
}

export async function clearIndex() {
  const { data } = await api.post('/career/clear');
  return data as { status: string; message: string; chunks_removed: number };
}

// --------------------------------------------------------------------------
// Analysis
// --------------------------------------------------------------------------

export async function fullAnalysis(jobDescription: string, resumeText?: string) {
  const { data } = await api.post<AnalysisResult>('/career/full-analysis', {
    job_description: jobDescription,
    ...(resumeText ? { resume_text: resumeText } : {}),
  });
  return data;
}

// `POST /career/analyze-job` and `GET /career/analysis/{id}/trace` have no
// wrapper here. The first is a strict subset of full-analysis, and the second
// returns a trace that full-analysis already includes as `execution_trace`.
// Both wrappers existed, were never called, and returned untyped `any`.

// --------------------------------------------------------------------------
// Resume insights, assistant and interview prep
// --------------------------------------------------------------------------

/**
 * Describe the CV on its own, with no job advert.
 *
 * Sends an empty object rather than omitting the body: the endpoint accepts
 * JSON, multipart or nothing at all, and an explicit `{}` keeps the request
 * unambiguous. Pass `resumeText` to analyse text that is not indexed.
 *
 * Answers 409 when no resume exists anywhere, which `describeApiError` turns
 * into the backend's own wording about uploading one.
 */
export async function getResumeInsights(resumeText?: string) {
  const { data } = await api.post<ResumeInsights>(
    '/career/resume-insights',
    resumeText ? { resume_text: resumeText } : {},
  );
  return data;
}

/**
 * Ask one question about the indexed CV.
 *
 * Stateless by design: the whole transcript is sent every time because the
 * backend keeps no session. Check `resume_available` on the reply -- the
 * endpoint answers 200 with a "upload your CV first" message rather than
 * erroring, so a chat box that cannot help still explains why.
 */
export async function sendChatMessage(
  message: string,
  history: ChatMessage[] = [],
  job: { title?: string; description?: string } = {},
) {
  const { data } = await api.post<ChatResponse>('/career/chat', {
    message,
    history,
    // Sent as text rather than an id so the assistant works for a job the
    // user pasted in as well as one they picked from search, and so there is
    // no server-side "current job" for two tabs to disagree about.
    job_title: job.title ?? '',
    job_description: job.description ?? '',
  });
  return data;
}

/**
 * Ask for feedback on a practice answer.
 *
 * `score` comes back `null` unless a model read the answer. That is not an
 * error state and must not be rendered as zero.
 */
export async function getPracticeFeedback(question: string, answer: string, skill = '') {
  const { data } = await api.post<PracticeFeedback>('/career/practice-answer', {
    question,
    answer,
    skill,
  });
  return data;
}

/**
 * Build interview questions. The advert is optional.
 *
 * Without one the questions come from the CV's own skills and
 * `tailored_to_job` comes back false, which the UI is expected to say out
 * loud rather than presenting generic questions as targeted ones.
 */
export async function getInterviewPrep(jobDescription = '') {
  const { data } = await api.post<InterviewPrepResult>('/career/interview-prep', {
    job_description: jobDescription,
  });
  return data;
}

// --------------------------------------------------------------------------
// Job discovery
// --------------------------------------------------------------------------

export async function discoverJobs(params: {
  query?: string;
  location?: string;
  limit?: number;
  /**
   * Ignore `query` and search for what the indexed CV points at instead.
   * Answers 409 when nothing is indexed rather than quietly searching the
   * default term, which would return a convincing page of adverts for
   * somebody else's career.
   */
  auto_from_resume?: boolean;
  /**
   * Only adverts posted within this many days. Omit for any age.
   *
   * The server widens this on its own when it would otherwise return almost
   * nothing, and reports what it did in `freshness_note`. Show that note --
   * a list quietly spanning a month under a "last 2 days" heading is worse
   * than no filter at all.
   */
  max_age_days?: number;
}) {
  const { data } = await api.post<JobDiscoveryResponse>('/career/discover-jobs', params);
  return data;
}

/**
 * `jobId` must come from a discovery call made in this server session.
 *
 * Discovered adverts live in an in-memory map on the backend, so an id stops
 * resolving when the server restarts and the call answers 404. There is no
 * matching delete endpoint: saving is one-way, and the UI must not offer an
 * unsave that would only ever change local state.
 */
export async function saveJob(
  jobId: string,
  options: { status?: string; notes?: string } = {},
) {
  const { data } = await api.post<SaveJobResponse>('/career/save-job', {
    job_id: jobId,
    status: options.status ?? 'saved',
    notes: options.notes ?? '',
  });
  return data;
}

export async function getMyJobs() {
  const { data } = await api.get<MyJobsResponse>('/career/my-jobs');
  return data;
}

// --------------------------------------------------------------------------
// Applications
// --------------------------------------------------------------------------

export async function createApplication(options: {
  jobId: string;
  analysisData?: Record<string, unknown>;
  status?: string;
}) {
  const { data } = await api.post('/career/create-application', {
    job_id: options.jobId,
    analysis_data: options.analysisData ?? {},
    status: options.status ?? 'draft',
  });
  return data as { application_id: string; status: string };
}

export async function updateApplicationStatus(
  appId: string,
  status: string,
  details: Record<string, unknown> = {},
) {
  const { data } = await api.post(`/career/application/${appId}/update-status`, {
    status,
    details,
  });
  return data as { updated: boolean; app_id: string; status: string };
}

export async function getApplications() {
  const { data } = await api.get<ApplicationsResponse>('/career/my-applications');
  return data;
}

export async function getApplicationHistory(appId: string) {
  const { data } = await api.get<ApplicationHistory>(
    `/career/application/${appId}/history`,
  );
  return data;
}

// --------------------------------------------------------------------------
// Analytics, health
// --------------------------------------------------------------------------

// `getDashboard` used to live here. Its page is gone, and an exported wrapper
// nothing calls is just a claim that the app still has a dashboard. The
// backend endpoint is untouched.

/**
 * Still here after the analytics page was removed: the applications list uses
 * these counts for its summary cards.
 */
export async function getAnalytics() {
  const { data } = await api.get<AnalyticsResponse>('/career/analytics');
  return data;
}

/**
 * Note the path: `/api/health/full`, outside the `/career` prefix.
 *
 * The return type used to be written inline as `{ name: string; status: string }[]`.
 * The field is `service`, not `name`. Nothing called this function until the
 * settings page did, so TypeScript had no reason to disagree with the lie and
 * the page would have rendered a column of `undefined`.
 *
 * The 503 is unwrapped rather than thrown. `main.py` answers 503 when a
 * *required* dependency is down -- and the body of that 503 is the full report
 * naming which one. Letting axios reject would replace the one screen that
 * explains the outage with the words "503 Service Unavailable", exactly when
 * the reader needs the detail. Anything else (unreachable, 500, a body that is
 * not a report) still throws.
 */
export async function getHealth() {
  try {
    const { data } = await api.get<HealthReport>('/health/full');
    return data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 503) {
      const body = error.response.data as Partial<HealthReport> | undefined;
      if (body && Array.isArray(body.services)) {
        return body as HealthReport;
      }
    }
    throw error;
  }
}

// --------------------------------------------------------------------------
// Accounts
//
// The session is an httpOnly cookie set by the backend. Nothing in this file
// reads it, and nothing stores a token: `getAccount` asking the server is the
// only honest way to know whether the session is still good, because a cookie
// this code cannot see is also a cookie this code cannot check.
// --------------------------------------------------------------------------

export async function signup(email: string, password: string, name = '') {
  const { data } = await api.post<Account>('/auth/signup', { email, password, name });
  return data;
}

export async function login(email: string, password: string) {
  const { data } = await api.post<Account>('/auth/login', { email, password });
  return data;
}

export async function logout() {
  const { data } = await api.post<{ status: string; message: string }>('/auth/logout');
  return data;
}

/**
 * The signed-in account, or `null` when there is no session.
 *
 * A 401 here is the expected answer for a signed-out visitor, not a failure,
 * so it resolves to `null` rather than throwing. Anything else -- a backend
 * that is down, a 500 -- still throws, because "not signed in" and "cannot
 * reach the server" must not look the same to the caller: the first sends
 * someone to the login page, the second would strand them there.
 */
export async function getAccount(): Promise<Account | null> {
  try {
    const { data } = await api.get<Account>('/auth/me');
    return data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      return null;
    }
    throw error;
  }
}
