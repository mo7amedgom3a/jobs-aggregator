export interface YCCompany {
  id: number;
  slug: string;
  name: string;
  batch?: string | null;
  one_liner?: string | null;
  website?: string | null;
  team_size?: number | null;
  status?: string | null;
  is_hiring: boolean;
  industries: string[];
  locations: string[];
  small_logo_url?: string | null;
  email?: string | null;
  email_source?: string | null;
  jobs_count: number;
  founders_count: number;
}

export interface YCJob {
  title: string;
  url?: string | null;
  location?: string | null;
}

export interface YCFounder {
  id: number;
  yc_slug: string;
  name: string;
  title?: string | null;
  bio?: string | null;
  profile_url?: string | null;
  avatar_url?: string | null;
  x_url?: string | null;
  x_handle?: string | null;
  linkedin_url?: string | null;
  email?: string | null;
  email_source?: string | null;
  email_confidence?: string | null;
  yc_has_email: boolean;
  batches: string[];
  company_id: number;
  company_name?: string | null;
  company_slug?: string | null;
  company_batch?: string | null;
  company_one_liner?: string | null;
  company_website?: string | null;
  company_logo_url?: string | null;
  company_is_hiring: boolean;
  company_jobs_count: number;
  jobs: YCJob[];
}

export interface YCCompaniesResponse {
  total: number;
  limit: number;
  offset: number;
  companies: YCCompany[];
}

export interface YCFoundersResponse {
  total: number;
  limit: number;
  offset: number;
  founders: YCFounder[];
}

export interface YCJobsResponse {
  total: number;
  limit: number;
  offset: number;
  jobs: YCJobRow[];
}

export interface YCJobRow {
  id: number;
  title: string;
  url?: string | null;
  location?: string | null;
  yc_job_slug?: string | null;
  company_name?: string | null;
  company_slug?: string | null;
  company_batch?: string | null;
  company_website?: string | null;
  company_one_liner?: string | null;
  company_logo_url?: string | null;
  company_is_hiring: boolean;
}

export interface YCCrawlRequest {
  batches?: string[] | null;
  max_companies_per_batch?: number | null;
  max_pages_per_batch?: number | null;
  skip_existing?: boolean;
  discover_emails?: boolean | null;
}

export interface YCCrawlResponse {
  status: string;
  message: string;
}

export interface YCCrawlState {
  running: boolean;
  stopping: boolean;
  stage: string;
  batch?: string | null;
  batches: string[];
  companies_total: number;
  companies_done: number;
  companies_skipped: number;
  founders_found: number;
  jobs_found: number;
  emails_found: number;
  errors: string[];
  current_company?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  last_result?: Record<string, unknown> | null;
}

export interface YCPipelineStats {
  companies: number;
  founders: number;
  founders_with_email: number;
  founders_with_x: number;
  founders_with_linkedin: number;
  company_jobs: number;
  outreach: Record<string, number>;
}

export interface YCStatusResponse {
  state: YCCrawlState;
  stats: YCPipelineStats;
}

export interface YCDraftRequest {
  channels: string[];
  keywords?: string[] | null;
  batch?: string | null;
  company_slug?: string | null;
  limit?: number;
}

export interface YCDraftResponse {
  status: string;
  founders_scanned: number;
  drafts_created: number;
  skipped: number;
  by_channel: Record<string, number>;
}

export interface OutreachMessage {
  id: number;
  channel: "email" | "x" | "linkedin" | string;
  recipient: string;
  subject?: string | null;
  body: string;
  status: string;
  error?: string | null;
  created_at?: string | null;
  sent_at?: string | null;
  founder_name?: string | null;
  founder_title?: string | null;
  company_name?: string | null;
  company_slug?: string | null;
  company_batch?: string | null;
  company_one_liner?: string | null;
  x_handle?: string | null;
  linkedin_url?: string | null;
}

export interface OutreachListResponse {
  total: number;
  limit: number;
  offset: number;
  messages: OutreachMessage[];
}

export interface OutreachSendRequest {
  channel: string;
  limit?: number | null;
  dry_run?: boolean;
}

export interface OutreachSendResponse {
  channel: string;
  dry_run: boolean;
  attempted: number;
  sent: number;
  failed: number;
  errors: string[];
}
