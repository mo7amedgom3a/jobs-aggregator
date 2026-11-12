"""Pydantic request/response models for the YC pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class YCCollectRequest(BaseModel):
    batches: list[str] | None = Field(
        default=None,
        description="Human-readable YC batch names to crawl. Defaults to YC_BATCHES (all 2025 + 2026 batches).",
        examples=[["Spring 2026"]],
    )
    max_companies_per_batch: int | None = Field(
        default=None,
        ge=0,
        description="Safety cap per batch (0 = unlimited).",
    )
    max_pages_per_batch: int | None = Field(
        default=None,
        ge=0,
        description="Safety cap on directory API pages per batch (0 = unlimited).",
    )
    skip_existing: bool = Field(
        default=True,
        description="Skip companies already stored (useful to resume a large multi-hour crawl).",
    )
    discover_emails: bool | None = Field(
        default=None,
        description="Override email discovery on company websites for this run.",
    )


class YCCrawlResponse(BaseModel):
    status: str
    message: str


class YCCompany(BaseModel):
    id: int
    slug: str
    name: str
    batch: str | None = None
    one_liner: str | None = None
    website: str | None = None
    team_size: int | None = None
    status: str | None = None
    is_hiring: bool = False
    industries: list[str] = []
    locations: list[str] = []
    small_logo_url: str | None = None
    email: str | None = None
    email_source: str | None = None
    jobs_count: int = 0
    founders_count: int = 0


class YCJob(BaseModel):
    title: str
    url: str | None = None
    location: str | None = None


class YCFounder(BaseModel):
    id: int
    yc_slug: str
    name: str
    title: str | None = None
    bio: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None
    x_url: str | None = None
    x_handle: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    email_source: str | None = None
    email_confidence: str | None = None
    yc_has_email: bool = False
    batches: list[str] = []
    company_id: int
    company_name: str | None = None
    company_slug: str | None = None
    company_batch: str | None = None
    company_one_liner: str | None = None
    company_website: str | None = None
    company_logo_url: str | None = None
    company_is_hiring: bool = False
    company_jobs_count: int = 0
    jobs: list[YCJob] = []


class YCCompaniesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    companies: list[YCCompany]


class YCFoundersResponse(BaseModel):
    total: int
    limit: int
    offset: int
    founders: list[YCFounder]


class YCJobRow(BaseModel):
    id: int
    title: str
    url: str | None = None
    location: str | None = None
    yc_job_slug: str | None = None
    company_name: str | None = None
    company_slug: str | None = None
    company_batch: str | None = None
    company_website: str | None = None
    company_one_liner: str | None = None
    company_logo_url: str | None = None
    company_is_hiring: bool = False


class YCJobsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: list[YCJobRow]


class YCDraftRequest(BaseModel):
    channels: list[str] = Field(
        default_factory=lambda: ["email", "x", "linkedin"],
        description="Channels to draft for. Only founders with that contact are included.",
    )
    keywords: list[str] | None = Field(
        default=None,
        description="Keywords used to pick the most relevant open roles.",
    )
    batch: str | None = Field(default=None, description="Limit drafting to one YC batch.")
    company_slug: str | None = Field(default=None, description="Limit drafting to one company.")
    limit: int = Field(default=500, ge=1, le=5000)


class YCDraftResponse(BaseModel):
    status: str
    founders_scanned: int
    drafts_created: int
    skipped: int
    by_channel: dict[str, int]


class OutreachMessage(BaseModel):
    id: int
    channel: str
    recipient: str
    subject: str | None = None
    body: str
    status: str
    error: str | None = None
    created_at: str | None = None
    sent_at: str | None = None
    founder_name: str | None = None
    founder_title: str | None = None
    company_name: str | None = None
    company_slug: str | None = None
    company_batch: str | None = None
    company_one_liner: str | None = None
    x_handle: str | None = None
    linkedin_url: str | None = None


class OutreachListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    messages: list[OutreachMessage]


class OutreachUpdateRequest(BaseModel):
    subject: str | None = None
    body: str | None = None
    status: str | None = Field(
        default=None,
        description="New status: draft | approved | skipped | failed.",
    )


class OutreachSendRequest(BaseModel):
    channel: str = Field(description="email | x | linkedin")
    limit: int | None = Field(default=None, ge=1, le=200)
    dry_run: bool = Field(default=False, description="Preview without contacting anyone.")


class OutreachSendResponse(BaseModel):
    channel: str
    dry_run: bool
    attempted: int
    sent: int
    failed: int
    errors: list[str] = []


class YCStatusResponse(BaseModel):
    state: dict[str, Any]
    stats: dict[str, Any]
