import { getApiBase } from "@/features/jobs/api";
import type {
  OutreachListResponse,
  OutreachMessage,
  OutreachSendRequest,
  OutreachSendResponse,
  YCCompaniesResponse,
  YCCrawlRequest,
  YCCrawlResponse,
  YCDraftRequest,
  YCDraftResponse,
  YCFoundersResponse,
  YCJobsResponse,
  YCStatusResponse,
} from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function startYCCrawl(
  req: YCCrawlRequest,
): Promise<YCCrawlResponse> {
  const res = await fetch(`${getApiBase()}/yc/collect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return json<YCCrawlResponse>(res);
}

export async function getYCStatus(
  signal?: AbortSignal,
): Promise<YCStatusResponse> {
  return json<YCStatusResponse>(
    await fetch(`${getApiBase()}/yc/status`, { signal }),
  );
}

export async function stopYCCrawl(): Promise<YCCrawlResponse> {
  return json<YCCrawlResponse>(
    await fetch(`${getApiBase()}/yc/collect/stop`, { method: "POST" }),
  );
}

export async function getYCJobs(
  params: {
    batch?: string;
    q?: string;
    companySlug?: string;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<YCJobsResponse> {
  const url = new URL(`${getApiBase()}/yc/jobs`);
  if (params.batch) url.searchParams.append("batch", params.batch);
  if (params.q) url.searchParams.append("q", params.q);
  if (params.companySlug)
    url.searchParams.append("company_slug", params.companySlug);
  url.searchParams.append("limit", String(params.limit ?? 200));
  url.searchParams.append("offset", String(params.offset ?? 0));
  return json<YCJobsResponse>(await fetch(url.toString(), { signal }));
}

export async function getYCCompanies(
  params: {
    batch?: string;
    q?: string;
    isHiring?: boolean;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<YCCompaniesResponse> {
  const url = new URL(`${getApiBase()}/yc/companies`);
  if (params.batch) url.searchParams.append("batch", params.batch);
  if (params.q) url.searchParams.append("q", params.q);
  if (params.isHiring) url.searchParams.append("is_hiring", "true");
  url.searchParams.append("limit", String(params.limit ?? 200));
  url.searchParams.append("offset", String(params.offset ?? 0));
  return json<YCCompaniesResponse>(await fetch(url.toString(), { signal }));
}

export async function getYCFounders(
  params: {
    batch?: string;
    q?: string;
    hasEmail?: boolean;
    hasX?: boolean;
    hasLinkedin?: boolean;
    companySlug?: string;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<YCFoundersResponse> {
  const url = new URL(`${getApiBase()}/yc/founders`);
  if (params.batch) url.searchParams.append("batch", params.batch);
  if (params.q) url.searchParams.append("q", params.q);
  if (params.hasEmail) url.searchParams.append("has_email", "true");
  if (params.hasX) url.searchParams.append("has_x", "true");
  if (params.hasLinkedin) url.searchParams.append("has_linkedin", "true");
  if (params.companySlug)
    url.searchParams.append("company_slug", params.companySlug);
  url.searchParams.append("limit", String(params.limit ?? 200));
  url.searchParams.append("offset", String(params.offset ?? 0));
  return json<YCFoundersResponse>(await fetch(url.toString(), { signal }));
}

export async function draftOutreach(
  req: YCDraftRequest,
): Promise<YCDraftResponse> {
  const res = await fetch(`${getApiBase()}/yc/outreach/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return json<YCDraftResponse>(res);
}

export async function getOutreach(
  params: {
    status?: string;
    channel?: string;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
): Promise<OutreachListResponse> {
  const url = new URL(`${getApiBase()}/yc/outreach`);
  url.searchParams.append("status", params.status ?? "draft");
  if (params.channel && params.channel !== "all")
    url.searchParams.append("channel", params.channel);
  url.searchParams.append("limit", String(params.limit ?? 200));
  url.searchParams.append("offset", String(params.offset ?? 0));
  return json<OutreachListResponse>(await fetch(url.toString(), { signal }));
}

export async function updateOutreach(
  id: number,
  patch: { subject?: string | null; body?: string | null; status?: string },
): Promise<OutreachMessage> {
  const res = await fetch(`${getApiBase()}/yc/outreach/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return json<OutreachMessage>(res);
}

export async function approveOutreach(id: number): Promise<OutreachMessage> {
  return json<OutreachMessage>(
    await fetch(`${getApiBase()}/yc/outreach/${id}/approve`, {
      method: "POST",
    }),
  );
}

export async function skipOutreach(id: number): Promise<OutreachMessage> {
  return json<OutreachMessage>(
    await fetch(`${getApiBase()}/yc/outreach/${id}/skip`, { method: "POST" }),
  );
}

export async function sendOutreach(
  req: OutreachSendRequest,
): Promise<OutreachSendResponse> {
  const res = await fetch(`${getApiBase()}/yc/outreach/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return json<OutreachSendResponse>(res);
}

export function exportFoundersUrl(batch?: string): string {
  const url = new URL(`${getApiBase()}/yc/export.csv`);
  if (batch) url.searchParams.append("batch", batch);
  return url.toString();
}
