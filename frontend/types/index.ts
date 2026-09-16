/**
 * Types mirrored from the backend's actual responses.
 *
 * These were written by calling the API and reading what came back, not from
 * the design sketch. Two consequences are worth stating up front, because
 * both differ from what a reader might expect:
 *
 * 1. Rates are `number | null`. The backend refuses to quote an interview or
 *    offer rate it cannot support, and sends null rather than 0. Anything
 *    that renders these must distinguish the two.
 * 2. A discovered job's score lives at `match_to_user.score`, an object, not
 *    a bare number on the job.
 */

// --------------------------------------------------------------------------
// Accounts
// --------------------------------------------------------------------------

/**
 * The signed-in account, as `/api/auth/me` returns it.
 *
 * There is deliberately no password, hash, salt or token field. The backend
 * never sends any of them, and declaring one here would invite code to look
 * for it. The session itself lives in an httpOnly cookie that JavaScript
 * cannot read at all.
 *
 * `created_date` and `last_login` are nullable: `last_login` is null for an
 * account that has only just signed up, and must not be rendered as a date.
 */
export interface Account {
  user_id: string;
  email: string;
  name: string;
  created_date: string | null;
  last_login: string | null;
}

// --------------------------------------------------------------------------
// Jobs
// --------------------------------------------------------------------------

/** Verdict the backend attaches alongside a score. */
export type MatchVerdict = 'APPLY' | 'MAYBE' | 'SKIP' | string;

export interface MatchToUser {
  score: number;
  verdict?: MatchVerdict;
  /**
   * How much of the advert could actually be read, 0-100 -- not how good the
   * match is. A one-line advert yielding a single skill you happen to have
   * scores 100 on `score` and low here.
   */
  confidence?: number | null;
  matched_skills?: string[];
  missing_skills?: string[];
  /**
   * Plain-English answers to "why should I apply for this job?", derived from
   * the skill overlap rather than generated. Includes the reasons against as
   * well as for -- a list with the gaps left off would be advertising.
   */
  reasons?: string[];
  [key: string]: unknown;
}

/** Difficulty is graded by the enricher during discovery, not by the analyser. */
export type JobDifficulty = 'EASY' | 'MEDIUM' | 'HARD' | string;

export interface JobAnalysis {
  title?: string;
  required_skills?: string[];
  preferred_skills?: string[];
  tech_stack?: string[];
  soft_skills?: string[];
  experience_years?: number | null;
  experience_level?: string | null;
  seniority?: string | null;
  role_type?: string | null;
  company_size?: string | null;
  education?: string | null;
  responsibilities?: string[];
  /** Only present on discovered jobs; the analyser alone does not set it. */
  difficulty?: JobDifficulty | null;
  remote?: boolean | null;
  estimated_salary_range?: string | null;
  confidence?: number | null;
  /** Set when the analysis came from the deterministic path, not an LLM. */
  warning?: string | null;
  source?: string | null;
  [key: string]: unknown;
}

export interface Job {
  job_id: string;
  title: string;
  company: string;
  description?: string;
  url?: string;
  source?: string;
  author?: string;
  thread?: string;
  posted_date?: string;
  /**
   * Days since posting, or null when the source published no date. Null is
   * not zero: rendering it as "0 days ago" would claim the advert went up
   * today, which the source never said.
   */
  days_old?: number | null;
  analysis?: JobAnalysis | null;
  /**
   * Null when no resume was indexed at discovery time. Null is not zero: it
   * means the advert was never scored, so nothing may coalesce it to 0.
   */
  match_to_user?: MatchToUser | null;
  [key: string]: unknown;
}

/** The buckets the backend sorts discovered jobs into. */
export type JobBucket =
  | 'perfect_match'
  | 'good_fit'
  | 'stretch_goal'
  | 'learning_needed'
  | 'unscored';

export interface CategorizedJobs {
  perfect_match: Job[];
  good_fit: Job[];
  stretch_goal: Job[];
  learning_needed: Job[];
  unscored: Job[];
  counts: Record<JobBucket, number>;
  by_difficulty: Record<string, number>;
}

/**
 * A job that has been persisted. The saved row is not the discovered dict:
 * the score is flattened to `match_score`, and storage fields appear.
 */
export interface SavedJob {
  job_id: string;
  user_id: string;
  title: string;
  company: string;
  description?: string;
  requirements?: unknown;
  analysis?: JobAnalysis | null;
  source?: string;
  url?: string;
  // Optional because only some feeds publish them. An advert that states
  // neither is normal, and neither field is ever inferred.
  location?: string;
  salary?: string;
  status?: string;
  notes?: string;
  match_score?: number | null;
  posted_date?: string;
  saved_date?: string;
  updated_date?: string;
}

export interface MyJobsResponse {
  jobs: SavedJob[];
  total: number;
  status_counts: Record<string, number>;
  user_id: string;
}

export interface SaveJobResponse {
  saved: boolean;
  job_id: string;
  user_jobs_count: number;
}

export interface JobDiscoveryResponse {
  jobs: Job[];
  categorized: CategorizedJobs;
  total_found: number;
  sources_used: string[];
  /**
   * Some feeds require attribution as a condition of use. The backend passes
   * the wording through so a client can honour it; showing it is not optional.
   */
  attribution: string[];
  /** False means the list is unranked -- not that every advert scored zero. */
  scored_against_resume: boolean;
  /**
   * Every phrase actually searched. With an auto search this is how the user
   * finds out what the server decided they do for a living, so it is shown
   * rather than kept: a wrong guess must be visible and correctable.
   */
  queries_used: string[];
  /** True when those phrases came from the CV rather than the search box. */
  derived_from_resume: boolean;
  /**
   * The age window actually applied, which is not always the one requested.
   * Null means no date filter survived and the list spans every age.
   */
  max_age_days_used?: number | null;
  /**
   * Set only when the requested window was widened or dropped. Show it
   * verbatim: "nothing posted in the last two days" must never be allowed to
   * look like "nothing matches you".
   */
  freshness_note?: string | null;
  /** How many returned adverts carried no posting date at all. */
  undated_count?: number;
}

// --------------------------------------------------------------------------
// Resume insights
// --------------------------------------------------------------------------

/**
 * What one CV says about its owner, with no job advert involved.
 *
 * Note the nullable `experience_years`. `null` means the CV never states a
 * duration, which is a different fact from "no experience" -- rendering it as
 * 0 would put a claim on screen that the candidate then has to argue with.
 */
export interface ResumeInsights {
  headline: string;
  primary_role: string;
  seniority: string;
  /** `null` means the CV does not say. Never render this as 0. */
  experience_years: number | null;
  /** Highest qualification named. `null` when the CV names none. */
  education: string | null;
  skills: string[];
  /** Skills bucketed for display. Empty groups are absent, not empty arrays. */
  skill_groups: Record<string, string[]>;
  strengths: string[];
  improvements: string[];
  suggested_roles: string[];
  /** Ready-made job-board phrases, so the user never has to invent a search. */
  search_queries: string[];
  /** `'llm'` when a model wrote this, `'fallback'` when fixed rules did. */
  source: string;
  warning: string | null;
  resume_source: string;
}

// --------------------------------------------------------------------------
// Assistant
// --------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  reply: string;
  /**
   * `'llm'` or `'fallback'`. This must be surfaced, not hidden. A chat box
   * looks equally intelligent either way, and this field is the only thing
   * that distinguishes a written answer from a pattern-matched one.
   */
  source: string;
  backend: string | null;
  warning: string | null;
  suggestions: string[];
  /** False when nothing is indexed, so the UI can point at the upload page. */
  resume_available: boolean;
}

// --------------------------------------------------------------------------
// Interview preparation
// --------------------------------------------------------------------------

/**
 * A thing to research about the employer, transcribed from a live response.
 *
 * Not a string. `company_questions` and `your_questions_for_them` both look
 * like plain lists of sentences and are not; rendering either one directly
 * throws "Objects are not valid as a React child".
 */
export interface CompanyQuestion {
  topic: string;
  suggested_research?: string[];
  your_angle?: string;
}

/** An entry in `your_questions_for_them`. */
export interface QuestionForThem {
  question: string;
  why_ask?: string;
}

/**
 * Feedback on one practice answer.
 *
 * `score` is `null` whenever no model read the answer, which is the normal
 * case with no API key set. Render that as "Not scored" — never as 0, and
 * never hide the field, because the absence of a score is the honest signal
 * that nothing judged this.
 */
export interface PracticeFeedback {
  score: number | null;
  verdict: string;
  strengths: string[];
  gaps: string[];
  /** Checkable statements about the answer. Present in both modes. */
  observations: string[];
  covered: string[];
  missing: string[];
  improved_opening: string;
  source: string;
  backend: string;
  note: string;
}

export interface InterviewPrepResult {
  interview_difficulty: string;
  estimated_prep_time_hours: number | null;
  questions: InterviewQuestion[];
  behavioral_questions: BehavioralQuestion[];
  /** The HR round: notice period, salary, why you are leaving. */
  hr_questions: BehavioralQuestion[];
  /** "What would you do if..." -- answerable without the experience. */
  scenario_questions: BehavioralQuestion[];
  /**
   * Quoted from the candidate's own project and experience bullets, so this
   * is empty when the CV has none to quote rather than being padded with
   * invented projects.
   */
  project_questions: ProjectQuestion[];
  /** Each weakness paired with something to do about it before the interview. */
  areas_to_improve: ImprovementArea[];
  company_questions: CompanyQuestion[];
  your_questions_for_them: QuestionForThem[];
  preparation_plan: PrepDay[];
  question_count: number;
  /**
   * False means the questions came from the CV alone. The UI says so rather
   * than implying a target role that was never supplied.
   */
  tailored_to_job: boolean;
  honesty_note: string;
  source: string;
  resume_source: string;
}

// --------------------------------------------------------------------------
// Applications
// --------------------------------------------------------------------------

/**
 * The five statuses the backend actually accepts. Note `sent`, not `applied`.
 */
export type ApplicationStatus = 'draft' | 'sent' | 'interview' | 'rejected' | 'offer';

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  'draft',
  'sent',
  'interview',
  'rejected',
  'offer',
];

/**
 * One entry of an application's `timeline`.
 *
 * Measured, not guessed: the keys are `event` / `status` / `details`, and
 * `details` carries `from` and `to` alongside whatever the caller passed.
 */
export interface ApplicationEvent {
  /** `created`, `application_sent`, `interview_scheduled`, ... */
  event: string;
  /** `YYYY-MM-DD`. */
  date: string;
  /** Full ISO 8601 with offset. */
  timestamp?: string;
  status?: ApplicationStatus | string;
  details?: Record<string, unknown>;
}

export interface Application {
  app_id: string;
  user_id?: string;
  job_id?: string;
  /** Empty string when the application was created without analysis data. */
  job_title?: string;
  /** Empty string when the application was created without analysis data. */
  company?: string;
  /** Null when the application was created before any analysis ran. */
  match_score?: number | null;
  /** The record's own field is `current_status`, not `status`. */
  current_status: ApplicationStatus | string;
  gaps_identified?: string[];
  timeline?: ApplicationEvent[];
  interviews?: unknown[];
  interview_prep_score?: number | null;
  resume_version_used?: string;
  created_date?: string;
  updated_date?: string;
  notes?: string;
}

/**
 * `GET /career/application/{id}/history` returns a subset, not an `Application`.
 *
 * There is no `created_date`, `notes` or `user_id` on it. The first timeline
 * entry is the only record of when it was created.
 */
export interface ApplicationHistory {
  app_id: string;
  job_title?: string;
  company?: string;
  match_score?: number | null;
  current_status: ApplicationStatus | string;
  timeline: ApplicationEvent[];
  interviews: unknown[];
  gaps_identified: string[];
}

export interface ApplicationsResponse {
  applications: Application[];
  total: number;
  status_counts: Record<string, number>;
  user_id: string;
}

// --------------------------------------------------------------------------
// Analysis
// --------------------------------------------------------------------------

/**
 * One missing skill, as the gap detector reports it.
 *
 * Note `learning_time_days`, not `learningDays`, and note that these live at
 * `analysis.gaps.gap_report.critical_gaps` -- `analysis.gaps` is an object,
 * not an array, so it cannot be mapped over directly.
 */
export interface Gap {
  skill: string;
  skill_id?: string;
  required?: boolean;
  user_has?: boolean;
  importance?: 'CRITICAL' | 'NICE_TO_HAVE' | string;
  why?: string;
  mentions_in_job?: number;
  learning_time_days?: number;
  similar_skills_user_has?: string[];
  learning_resources?: string[];
  learning_path?: unknown;
  practice_project?: string;
  recommendation?: string;
  documentation?: string;
}

export interface GapReport {
  critical_gaps: Gap[];
  nice_to_have_gaps: Gap[];
  critical_count: number;
  nice_to_have_count: number;
  quick_wins?: Gap[];
  priority_order?: string[];
  blocking_learning_days?: number;
  total_learning_time_weeks?: number;
  summary?: string;
  source?: string;
}

export interface GapsSection {
  gaps: string[];
  preferred_gaps: string[];
  strengths: string[];
  explanation?: string;
  /** "fallback" when no LLM was reachable. Worth surfacing, not hiding. */
  source?: string;
  warning?: string | null;
  gap_report?: GapReport;
}

export interface InterviewQuestion {
  question: string;
  id?: number;
  category?: string;
  /** The skill the question is aimed at, when there is one. */
  skill?: string;
  why_asked?: string;
  /** Free text such as `"High - 2 places on your resume evidence it"`. */
  your_strength?: string;
  suggested_answer?: string;
  [key: string]: unknown;
}

export interface BehavioralQuestion {
  question: string;
  context?: string;
  suggested_approach?: string;
}

/** A question built by quoting a line from the candidate's own CV. */
export interface ProjectQuestion extends BehavioralQuestion {
  category?: string;
  skills?: string[];
  /** True when the quoted line uses something this advert asks for. */
  matches_advert?: boolean;
}

export interface ImprovementArea {
  area: string;
  why: string;
  what_to_do: string;
}

export interface PrepDay {
  day: number;
  focus: string;
  time_hours: number;
  tasks: string[];
}

export interface SuccessRateFactor {
  factor: string;
  /** Signed, already formatted: `"+32%"`, `"-20%"`. */
  effect: string;
  why: string;
}

/**
 * The real `analysis.interview_prep` block.
 *
 * Transcribed from a response, not from the design sketch. The sketch had
 * `talking_points`, `questions_to_ask` and `readiness_score`; none of those
 * exist. `success_rate_prediction` is a fraction (0.05), not a percentage.
 */
export interface InterviewPrep {
  questions?: InterviewQuestion[];
  strength_questions?: InterviewQuestion[];
  weakness_questions?: InterviewQuestion[];
  behavioral_questions?: BehavioralQuestion[];
  company_questions?: { topic: string; suggested_research?: string[]; your_angle?: string }[];
  your_questions_for_them?: { question: string; why_ask?: string }[];
  preparation_plan?: PrepDay[];
  interview_difficulty?: string;
  estimated_prep_time_hours?: number;
  prep_days?: number;
  question_count?: number;
  gap_question_count?: number;
  /** A fraction between 0 and 1. Multiply before displaying. */
  success_rate_prediction?: number;
  success_rate_reasoning?: {
    predicted?: number;
    as_percentage?: number;
    factors?: SuccessRateFactor[];
  };
  confidence?: number;
  honesty_note?: string;
  source?: string;
  [key: string]: unknown;
}

export interface ResumeImprovement {
  section: string;
  current?: string;
  suggested?: string;
  suggested_description?: string;
  why?: string;
  /** `HIGH` / `MEDIUM` / `LOW`. */
  impact?: string;
  placeholders?: string[];
  needs_your_input?: boolean;
}

export interface KeywordDensityRow {
  keyword: string;
  in_resume: number;
  in_job_advert: number;
  verdict: string;
  action: string;
}

/**
 * The real `analysis.resume_optimizations` block.
 *
 * An object, not the array of strings the design sketch assumed. Note
 * `keywords_blocked_by_gaps`: skills the advert wants that the user cannot
 * honestly claim. They are deliberately kept out of `keywords_to_add` and
 * have to be displayed as blocked, not as suggestions.
 */
export interface ResumeOptimizations {
  resume_title?: string;
  tailored_summary?: string;
  improvements?: ResumeImprovement[];
  projects_to_highlight?: { name?: string; why?: string; [key: string]: unknown }[];
  keywords_to_add?: string[];
  keywords_to_remove?: { keyword: string; action?: string; why?: string }[];
  keywords_blocked_by_gaps?: string[];
  keyword_density?: KeywordDensityRow[];
  reordering?: { move_up?: string[]; move_down?: string[] };
  confidence?: number;
  high_impact_count?: number;
  honesty_note?: string;
  source?: string;
  [key: string]: unknown;
}

/**
 * One dimension of `analysis.match_breakdown`.
 *
 * `found` and `missing` are **not** uniformly typed. `skills` and `tech_stack`
 * send string arrays; `experience` and `education` send a single string such as
 * `"not stated"` / `"5 years"`. Calling `.join()` on the second pair throws,
 * which is exactly what happened the first time this rendered.
 */
export interface MatchDimension {
  score: number;
  weight: number;
  /** False when the advert said nothing about this dimension. */
  applicable: boolean;
  found?: string[] | string;
  missing?: string[] | string;
  /** Set on `soft_skills` when the advert named none. */
  reason?: string;
  /** Set on `experience` when the resume states no length of service. */
  note?: string;
  required?: string;
  meets_requirement?: boolean;
  evidence?: Record<string, string>;
  [key: string]: unknown;
}

/** The `analysis` block of a full-analysis response. */
export interface AnalysisSections {
  job_analysis?: JobAnalysis;
  /** Keyed by dimension: skills, tech_stack, experience, education, soft_skills. */
  match_breakdown?: Record<string, MatchDimension>;
  gaps?: GapsSection;
  resume_optimizations?: ResumeOptimizations;
  interview_prep?: InterviewPrep;
  learning_path?: Record<string, unknown>;
  [key: string]: unknown;
}

/**
 * A step of `execution_trace` on a full-analysis response.
 *
 * Not the same shape as `GET /api/career/analysis/{id}/trace`, which returns
 * `{ name, status, duration_ms, output_summary }`. Two endpoints, two shapes.
 */
export interface ExecutionTraceStep {
  step: number;
  node: string;
  status: string;
  duration_ms: number;
  timestamp?: string;
  detail?: string;
  /** Human-readable node name, e.g. `"Match Calculator (re-run)"`. */
  label?: string;
  /** Present on some nodes only; absent is not zero. */
  confidence?: number;
  skills_extracted?: number;
  [key: string]: unknown;
}

export interface TraceNode {
  name: string;
  status: string;
  duration_ms: number;
  output_summary?: string;
}

export interface AnalysisResult {
  analysis_id: string;
  /**
   * Null when the advert specified no skills, technologies, years or
   * qualifications, leaving every dimension inapplicable and no average to
   * take. Null is not zero: zero means measured and unmatched.
   */
  overall_match: number | null;
  /** APPLY / MAYBE / SKIP, or NOT_SCORED when `overall_match` is null. */
  recommendation: string;
  user_recommendation: string;
  analysis: AnalysisSections;
  execution_trace: ExecutionTraceStep[];
  total_analysis_time_ms: number;
  /** `"completed"` on success -- not `"success"`. */
  status: string;
  nodes_failed: string[];
}

// --------------------------------------------------------------------------
// Analytics and dashboard
// --------------------------------------------------------------------------

/**
 * A rate the backend may decline to report.
 *
 * **Already formatted.** `_pct()` in `agents/application_analytics.py` returns
 * `Optional[str]` -- `"100%"`, `"0%"`, or `None`. It is not a number, so it
 * must not be appended to with `%` and `.toFixed()` cannot be called on it.
 *
 * Null is a real answer: it means "nothing to divide by", and must never be
 * coalesced to 0 for display. Zero applications is not a 0% interview rate.
 */
export type RateText = string | null;

/** A number the backend may decline to report, e.g. an average with no sample. */
export type NullableNumber = number | null;

export interface AnalyticsMetrics {
  total_applications: number;
  applications_sent: number;
  interviews_scheduled: number;
  /** Interviews divided by applications **sent**, not by applications tracked. */
  interview_rate: RateText;
  offers_received: number;
  /** Offers divided by **interviews**, not by applications. `_pct(offers, interviews)`. */
  offer_rate: RateText;
  rejections: number;
  still_open: number;
  avg_match_score_when_applied: NullableNumber;
  avg_match_score_when_interview: NullableNumber;
  best_job_type: string | null;
  common_gaps: string[];
  gaps_in_rejections: string[];
  days_to_interview: NullableNumber;
  days_to_interview_median: NullableNumber;
  days_to_interview_observations: number;
  /** A rendered range such as `"21%-100%"`, not a numeric tuple. */
  interview_rate_confidence_95: string | null;
  offer_rate_confidence_95: string | null;
  /** `"below 95%"`. Only present when applications were sent and none landed an offer. */
  offer_rate_upper_bound_95?: string | null;
  /** Present when the sample is too small for the rates above to mean much. */
  sample_size_warning?: string | null;
}

export interface AnalyticsStrategy {
  current_situation: string;
  issue: string | null;
  recommendations: string[];
  next_steps: string[];
  /** e.g. `"4 applications"`. */
  based_on: string;
  /** A sentence, not a number: `"low - too few applications to see a pattern"`. */
  confidence: string;
}

/**
 * The forecast, or the backend's refusal to make one.
 *
 * `offer_probability_next_month` is null unless there are at least ten
 * applications *and* at least one offer *and* enough elapsed time to read a
 * monthly pace from. `basis` always explains which of those was missing.
 */
export interface AnalyticsPrediction {
  current_stats: {
    applications_sent: number;
    interviews_scheduled: number;
    offers_received: number;
    interview_rate: RateText;
    interview_rate_confidence_95: string | null;
  };
  /** A formatted string such as `"37%"`, or null when no forecast is possible. */
  offer_probability_next_month: RateText;
  estimated_time_to_offer: string | null;
  what_needs_to_happen: string[];
  basis: string;
  /** Present when there are applications but no offers yet. */
  offer_rate_upper_bound_95?: string;
  offer_rate_confidence_95?: string;
  /** Present when there is an offer but too short a window to read a pace. */
  offer_rate_per_application?: string;
}

export interface AnalyticsResponse {
  metrics: AnalyticsMetrics;
  strategy: AnalyticsStrategy;
  prediction: AnalyticsPrediction;
  user_id: string;
}

export interface DashboardSummary {
  total_applications: number;
  applications_sent: number;
  interviews: number;
  offers: number;
  interview_rate: RateText;
  interview_rate_confidence_95: string | null;
}

/** `recent_applications` is a projection, not a full `Application` record. */
export interface RecentApplication {
  app_id: string;
  /** The job title, or the app id when no analysis data was captured. */
  job: string;
  status: ApplicationStatus | string;
  match: number | null;
  applied_date: string | null;
  next_date: string | null;
}

export interface UpcomingItem {
  app_id: string;
  job: string;
  interview_date: string | null;
  preparation: unknown;
  match: number | null;
}

export interface DashboardResponse {
  summary: DashboardSummary;
  status_counts: Record<string, number>;
  recent_applications: RecentApplication[];
  upcoming: UpcomingItem[];
  analytics: AnalyticsMetrics;
}

// --------------------------------------------------------------------------
// Resume index
// --------------------------------------------------------------------------

export interface IndexStatus {
  resume_indexed: boolean;
  status: string;
  chunks: number;
}

// --------------------------------------------------------------------------
// Health
// --------------------------------------------------------------------------

/**
 * One probe from `GET /api/health/full`.
 *
 * The identifying key is `service`, **not** `name`. `getHealth` in lib/api.ts
 * declared `name` inline and was never called, so nothing caught it until the
 * settings page tried to render a list of `undefined`. Built from
 * `utils/health_check.py::_result`, which always writes the first four fields
 * and then splices in whatever the individual probe passed as `**extra`.
 */
export interface HealthService {
  service: string;
  /** 'healthy' | 'degraded' | 'unhealthy' — not an enum on the wire. */
  status: string;
  /** A failing required service is what turns the whole report unhealthy. */
  required: boolean;
  duration_ms: number;

  /** Probe-specific extras. Present or absent depending on which probe ran. */
  note?: string;
  provider?: string;
  indexed_chunks?: number;

  /** Written by `_failure` only. The message itself stays in the server log. */
  error_type?: string;
  error_id?: string;
  detail?: string;
}

export interface HealthReport {
  /** 'healthy' if every probe passed, 'degraded' if only optional ones failed. */
  overall_status: string;
  app: string;
  version: string;
  services: HealthService[];
  duration_ms: number;
  timestamp: string;
}
