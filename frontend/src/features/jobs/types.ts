export interface FormState {
  keywords: string[];
  countries: string[];
  company: string | null;
  remote: boolean | null;
  limit: number;
  offset: number;
  sort: "score" | "recent";
  minScore: number;
  postedHours: number;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  url: string;
  description: string;
  location: string;
  salary: string;
  source: string;
  site: string;
  tags: string[];
  scraped_at: string;
  posted_at?: string | null;
  score?: number | null;
  relevance?: number | null;
  authenticity?: number | null;
  verdict?: "legit" | "suspicious" | "likely_scam" | string | null;
  reasons?: string[];
  // compatibility fallbacks
  easy_apply?: boolean;
  job_type?: string;
  job_level?: string;
  is_remote?: boolean;
}

export interface JobBoard {
  name: string;
  jobs: Job[];
}

export interface CountryGroup {
  country: string;
  job_boards: JobBoard[];
}

export interface PaginatedSearchResponse {
  total: number;
  limit: number;
  offset: number;
  results: CountryGroup[];
}

export interface CountryInfo {
  name: string;
  job_boards: string[];
  spiders: string[];
}

export interface CountriesResponse {
  countries: Record<string, CountryInfo>;
}

export interface SubAggregateRequest {
  country: string;
  job_board: string;
}

export interface SubAggregateResponse {
  status: string;
  message: string;
}

export interface CacheStatsResponse {
  seen_urls: number;
  oldest_entry: string | null;
}

export interface ClearCacheResponse {
  cleared: number;
  message: string;
}

export interface DeleteOldJobsResponse {
  deleted_count: number;
  deleted_jobs: Job[];
}

export interface HiringPost {
  id: string;
  platform: "linkedin" | "x" | string;
  author: string;
  author_url?: string | null;
  text: string;
  post_url: string;
  posted_at?: string | null;
  keywords_matched: string[];
  scraped_at?: string | null;
  score?: number | null;
  relevance?: number | null;
  authenticity?: number | null;
  verdict?: "legit" | "suspicious" | "likely_scam" | string | null;
  reasons?: string[];
}

export interface HiringPostsResponse {
  total: number;
  limit: number;
  offset: number;
  posted_hours: number;
  posts: HiringPost[];
}

export interface SocialScanRequest {
  keywords: string[];
  platforms: string[];
  max_posts: number;
  location?: string | null;
}

export interface SocialScanResponse {
  status: string;
  message: string;
}

export interface SocialStatusResponse {
  allowed: boolean;
  platforms: Record<string, { credentials: boolean; saved_session: boolean }>;
  state: {
    running: boolean;
    platforms: string[];
    started_at: string | null;
    finished_at: string | null;
    last_result: Record<string, unknown> | null;
  };
}
