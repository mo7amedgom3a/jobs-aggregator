"""
Central configuration for the Job Board Scraping Engine.
Adjust per-site settings here without touching spider logic.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# Explicit path so settings also work when imported from outside backend/.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ─── Fetcher Strategy ────────────────────────────────────────────────────────
# "http"     → Fetcher       (fastest, for plain HTTP job boards)
# "dynamic"  → DynamicFetcher (JS-rendered pages, moderate protection)
# "stealth"  → StealthyFetcher (Cloudflare, heavy bot detection, CAPTCHAs)

FetcherType = Literal["http", "dynamic", "stealth"]

KEYWORDS = ["software engineer", "DevOps", "backend", "AWS", "terraform", "python", "Golang", "Full Stack", "Engineer", "Devloper", ".NET", "react", "frontend", "AI", "LLM", "API"]

#: Focused query for Indeed. The generic KEYWORDS list includes bare terms like
#: "Engineer"/"AI" that Indeed matches against civil/mechanical/sales/teaching
#: roles, flooding country boards with onsite noise.
INDEED_KEYWORDS = [
    "software engineer",
    "devops",
    "backend developer",
    "full stack developer",
    "data engineer",
    "cloud engineer",
    "platform engineer",
    "site reliability engineer",
    "python developer",
    "java developer",
]
@dataclass
class SiteConfig:
    name: str
    start_urls: list[str]
    fetcher: FetcherType = "http"
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)  # Dynamic job search keywords
    # Polite crawl settings (per-site overrides)
    concurrent_requests: int = 4
    concurrent_requests_per_domain: int = 2
    download_delay: float = 1.5        # seconds between requests
    max_blocked_retries: int = 3
    robots_txt_obey: bool = True
    # Pagination — CSS selector for "next page" link
    next_page_selector: str = "a[rel='next']::attr(href)"
    # Max pages per run (safety cap; 0 = unlimited)
    max_pages: int = 0
    # Extra kwargs forwarded to the underlying fetcher
    proxies: list[str] = field(default_factory=list)
    extra_fetch_kwargs: dict = field(default_factory=dict)
 
 
# ─── Registered Job Boards ───────────────────────────────────────────────────
# Only add sites that explicitly permit scraping in their robots.txt / ToS.
 
SITES: list[SiteConfig] = [
    SiteConfig(
        name="remoteok",
        start_urls=["https://remoteok.com/remote-dev-jobs"],
        fetcher="stealth",
        download_delay=2.0,
        next_page_selector="a.next::attr(href)",
        extra_fetch_kwargs={"network_idle": True},
    ),
    SiteConfig(
        name="weworkremotely",
        start_urls=[
            "https://weworkremotely.com/categories/remote-programming-jobs",
            "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs",
        ],
        fetcher="http",
        download_delay=2.0,
    ),
    SiteConfig(
        name="jobicy",
        start_urls=["https://jobicy.com/api/v2/remote-jobs"],
        fetcher="http",
        download_delay=1.5,
    ),
    SiteConfig(
        name="remotive",
        start_urls=["https://remotive.com/api/remote-jobs?category=software-dev"],
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="himalayas",
        start_urls=["https://himalayas.app/jobs/api"],
        fetcher="http",
        download_delay=3.0,
    ),
    SiteConfig(
        name="trueup",
        start_urls=["https://www.trueup.io/jobs"],
        fetcher="stealth",
        download_delay=3.0,
        extra_fetch_kwargs={"network_idle": True},
    ),
    SiteConfig(
        name="linkedin",
        start_urls=["https://www.linkedin.com/jobs/search"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="indeed",
        start_urls=["https://www.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    # ─── LinkedIn Country-Specific Usecases ────────────────────────────────────
    SiteConfig(
        name="linkedin_sa",
        start_urls=["https://sa.linkedin.com/jobs/search?location=Saudi%20Arabia&geoId=100459316"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_eg",
        start_urls=["https://eg.linkedin.com/jobs/search?location=Egypt&geoId=106155005"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_ae",
        start_urls=["https://ae.linkedin.com/jobs/search?location=United%20Arab%20Emirates&geoId=104305776"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_barcelona",
        start_urls=["https://www.linkedin.com/jobs/search?location=Barcelona&geoId=107025191"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_germany",
        start_urls=["https://de.linkedin.com/jobs/search?location=Germany&geoId=101282230"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_uk",
        start_urls=["https://uk.linkedin.com/jobs/search?location=United%20Kingdom&geoId=101165590&f_TPR=r86400&f_WT=2"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_poland",
        start_urls=["https://www.linkedin.com/jobs/search?location=Poland&geoId=105072130"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_spain",
        start_urls=["https://www.linkedin.com/jobs/search?location=Spain&geoId=105646813"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_canada",
        start_urls=["https://www.linkedin.com/jobs/search?location=Canada&geoId=101174742"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    # ─── Additional MENA LinkedIn boards (remote filtered by f_WT=2) ───────────
    SiteConfig(
        name="linkedin_qatar",
        start_urls=["https://qa.linkedin.com/jobs/search?location=Qatar"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_kuwait",
        start_urls=["https://kw.linkedin.com/jobs/search?location=Kuwait"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_bahrain",
        start_urls=["https://bh.linkedin.com/jobs/search?location=Bahrain"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_oman",
        start_urls=["https://om.linkedin.com/jobs/search?location=Oman"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    SiteConfig(
        name="linkedin_jordan",
        start_urls=["https://jo.linkedin.com/jobs/search?location=Jordan"],
        keywords=KEYWORDS,
        fetcher="http",
        download_delay=3.0,
        robots_txt_obey=False,
    ),
    # ─── Indeed Country-Specific Usecases ──────────────────────────────────────
    SiteConfig(
        name="indeed_eg",
        start_urls=["https://eg.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_sa",
        start_urls=["https://sa.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_ae",
        start_urls=["https://ae.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_uk",
        start_urls=["https://uk.indeed.com/jobs?q=software+engineer&l=%22remote%22&fromage=1"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_germany",
        start_urls=["https://de.indeed.com/jobs?q=Software+Engineer&l=%22remote%22&fromage=1"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    # ─── Additional MENA Indeed boards (remote-only via sc=DSQF7) ─────────────
    SiteConfig(
        name="indeed_qa",
        start_urls=["https://qa.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_kw",
        start_urls=["https://kw.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_bh",
        start_urls=["https://bh.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_om",
        start_urls=["https://om.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    SiteConfig(
        name="indeed_jo",
        start_urls=["https://jo.indeed.com/jobs"],
        keywords=KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            # Playwright timeouts are milliseconds.
            "timeout": 90000,
            # Indeed renders job cards client-side; wait for hydration.
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
    # Global remote pool. Country boards (eg/sa/...) no longer expose a remote
    # filter and are onsite-dominated, while www.indeed.com honours l=Remote.
    SiteConfig(
        name="indeed_remote",
        start_urls=["https://www.indeed.com/jobs?l=Remote"],
        keywords=INDEED_KEYWORDS,
        fetcher="stealth",
        download_delay=3.0,
        robots_txt_obey=False,
        next_page_selector="a[data-dd-action-name='next-page']::attr(href), a[data-testid='pagination-page-next']::attr(href), a[aria-label='Next Page']::attr(href), a[aria-label='Next']::attr(href), a[aria-label*='Next']::attr(href)",
        extra_fetch_kwargs={
            "timeout": 90000,
            "wait": 8000,
            "network_idle": True,
            "load_dom": True,
        },
    ),
]

# ─── Scheduler ───────────────────────────────────────────────────────────────
SCHEDULE_INTERVAL_HOURS: int = 1      # run the full engine every hour
CRAWL_DIR: str = "crawl_checkpoints"  # pause/resume state directory
LOG_DIR: str = "logs"

# ─── Recency & scoring ───────────────────────────────────────────────────────
# Hard recency window (hours). Every job/post must be posted within this window.
POSTED_HOURS: int = int(os.getenv("POSTED_HOURS", "24"))
# When true, items whose posting date cannot be parsed are dropped.
STRICT_RECENT: bool = os.getenv("STRICT_RECENT", "true").lower() in {"1", "true", "yes", "on"}
# When true, only remote jobs/posts are kept (hybrid/onsite are rejected).
REMOTE_ONLY: bool = os.getenv("REMOTE_ONLY", "true").lower() in {"1", "true", "yes", "on"}

# Composite score = RELEVANCE_WEIGHT * relevance + AUTHENTICITY_WEIGHT * authenticity
RELEVANCE_WEIGHT: float = float(os.getenv("RELEVANCE_WEIGHT", "0.6"))
AUTHENTICITY_WEIGHT: float = float(os.getenv("AUTHENTICITY_WEIGHT", "0.4"))
# Minimum composite score returned by /search when the request does not set one.
DEFAULT_MIN_SCORE: float = float(os.getenv("DEFAULT_MIN_SCORE", "0"))

# ─── Social "hiring posts" scraping ──────────────────────────────────────────
# These run only when triggered from the frontend (2-3 times per day) — never
# from the hourly scheduler — to avoid account rate limits.
SOCIAL_ENABLED: bool = os.getenv("SOCIAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
SOCIAL_MAX_POSTS_PER_PLATFORM: int = int(os.getenv("SOCIAL_MAX_POSTS_PER_PLATFORM", "40"))
SOCIAL_HEADLESS: bool = os.getenv("SOCIAL_HEADLESS", "false").lower() in {"1", "true", "yes", "on"}
SOCIAL_NAV_TIMEOUT_MS: int = int(os.getenv("SOCIAL_NAV_TIMEOUT_MS", "45000"))
# How long an interactive "open login browser" window may stay open before it
# is closed automatically (seconds). Prevents a forgotten window from blocking
# scans forever.
SOCIAL_BROWSER_TIMEOUT: int = int(os.getenv("SOCIAL_BROWSER_TIMEOUT", "900"))
# Persisted Playwright storage state (cookies) so we do not log in every run.
SOCIAL_SESSION_DIR: str = os.getenv(
    "SOCIAL_SESSION_DIR",
    str(Path(__file__).resolve().parent.parent / ".sessions"),
)

# Phrases that signal a hiring post on social platforms.
HIRING_PHRASES: list[str] = [
    "we are hiring",
    "we're hiring",
    "we are looking for",
    "we're looking for",
    "hiring now",
    "hiring!",
    "now hiring",
    "job opening",
    "job opportunity",
    "open role",
    "open position",
    "join our team",
    "join my team",
    "looking to hire",
    "actively hiring",
    "immediate hiring",
    "dm me",
    "send your cv",
    "send your resume",
    "share your cv",
    "share your resume",
]


def _load_local_auth() -> dict[str, str]:
    """Parse the repo-local ``auth-access.txt`` credentials file.

    The file uses a simple platform / field / value layout, for example::

        linkedin
        email
        someone@example.com
        password
        secret

    Environment variables always win over this file.
    """
    auth_path = Path(__file__).resolve().parent.parent.parent / "auth-access.txt"
    values: dict[str, str] = {}
    if not auth_path.exists():
        return values

    try:
        lines = [
            line.strip()
            for line in auth_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        ]
    except OSError:
        return values

    platform = ""
    known_fields = {
        "email",
        "username",
        "user",
        "password",
        "pass",
        "token",
        "cookie",
        "cookies",
    }
    known_platforms = {"linkedin", "x", "twitter", "indeed", "google", "reddit"}

    index = 0
    while index < len(lines):
        line = lines[index]
        lowered = line.lower()
        if not line:
            index += 1
            continue
        if lowered in known_platforms:
            platform = "x" if lowered == "twitter" else lowered
            index += 1
            continue
        if lowered in known_fields and index + 1 < len(lines):
            value = lines[index + 1].strip()
            if value and value.lower() not in known_fields and value.lower() not in known_platforms:
                key = f"{platform}_{lowered}".strip("_")
                values[key] = value
                index += 2
                continue
        index += 1

    return values


_LOCAL_AUTH = _load_local_auth()

LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL") or _LOCAL_AUTH.get("linkedin_email", "")
LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD") or _LOCAL_AUTH.get("linkedin_password", "")
LINKEDIN_COOKIES: str = os.getenv("LINKEDIN_COOKIES", "")
X_USERNAME: str = (
    os.getenv("X_USERNAME")
    or os.getenv("X_EMAIL")
    or _LOCAL_AUTH.get("x_username", "")
    or _LOCAL_AUTH.get("x_email", "")
)
X_PASSWORD: str = os.getenv("X_PASSWORD") or _LOCAL_AUTH.get("x_password", "")
X_COOKIES: str = os.getenv("X_COOKIES", "")

# ─── Reddit hiring posts ─────────────────────────────────────────────────────
# Reddit blocks unauthenticated JSON from many networks, so the collector reads
# the public Atom feeds (/r/<sub>/new/.rss). If a Reddit "script" app is
# registered (client id + secret), the OAuth JSON API is used instead, which has
# much higher rate limits and can use REDDIT_USERNAME/REDDIT_PASSWORD.
REDDIT_USERNAME: str = os.getenv("REDDIT_USERNAME") or _LOCAL_AUTH.get("reddit_username", "")
REDDIT_PASSWORD: str = os.getenv("REDDIT_PASSWORD") or _LOCAL_AUTH.get("reddit_password", "")
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv(
    "REDDIT_USER_AGENT",
    "job-aggregator/1.0 (manual remote hiring-post scan)",
)
# Subreddits that actually carry tech hiring posts. Keep this list small: the
# public feed limit is tight (roughly one request every 10-15 seconds).
REDDIT_SUBREDDITS: list[str] = [
    sub.strip()[2:] if sub.strip().lower().startswith("r/") else sub.strip()
    for sub in os.getenv(
        "REDDIT_SUBREDDITS",
        "forhire,jobbit,remotejobs,hiring",
    ).split(",")
    if sub.strip()
]
REDDIT_MAX_SUBREDDITS: int = int(os.getenv("REDDIT_MAX_SUBREDDITS", "3"))
REDDIT_REQUEST_DELAY: float = float(os.getenv("REDDIT_REQUEST_DELAY", "20"))
REDDIT_RATE_LIMIT_WAIT: float = float(os.getenv("REDDIT_RATE_LIMIT_WAIT", "40"))
REDDIT_TIMEOUT: int = int(os.getenv("REDDIT_TIMEOUT", "25"))

# ─── YC founder sourcing & outreach ──────────────────────────────────────────
# The pipeline is triggered manually from the frontend, never by the scheduler.
YC_ENABLED: bool = os.getenv("YC_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
YC_API_BASE: str = os.getenv("YC_API_BASE", "https://api.ycombinator.com/v0.1")
YC_SITE_BASE: str = os.getenv("YC_SITE_BASE", "https://www.ycombinator.com")
# Human-readable batch names accepted by the public YC directory API.
YC_BATCHES: list[str] = [
    b.strip()
    for b in os.getenv(
        "YC_BATCHES",
        "Winter 2025,Spring 2025,Summer 2025,Fall 2025,"
        "Winter 2026,Spring 2026,Summer 2026,Fall 2026",
    ).split(",")
    if b.strip()
]
# Seconds between requests to ycombinator.com (be polite; the API is public).
YC_REQUEST_DELAY: float = float(os.getenv("YC_REQUEST_DELAY", "1.2"))
YC_REQUEST_TIMEOUT: int = int(os.getenv("YC_REQUEST_TIMEOUT", "25"))
# Company website email lookups get a shorter timeout so one dead site cannot
# stall the whole crawl.
YC_WEBSITE_TIMEOUT: int = int(os.getenv("YC_WEBSITE_TIMEOUT", "12"))
# Safety caps (0 = unlimited).
YC_MAX_COMPANIES_PER_BATCH: int = int(os.getenv("YC_MAX_COMPANIES_PER_BATCH", "0"))
YC_MAX_PAGES_PER_BATCH: int = int(os.getenv("YC_MAX_PAGES_PER_BATCH", "0"))
# Email discovery on company websites (homepage + /contact + /about ...).
YC_DISCOVER_EMAILS: bool = os.getenv("YC_DISCOVER_EMAILS", "true").lower() in {"1", "true", "yes", "on"}
YC_MAX_WEBSITE_PAGES: int = int(os.getenv("YC_MAX_WEBSITE_PAGES", "3"))
YC_EMAIL_PATTERN_GUESS: bool = os.getenv("YC_EMAIL_PATTERN_GUESS", "true").lower() in {"1", "true", "yes", "on"}
# Per-company time budget for optional enrichment (website emails + founder
# pages). When exceeded, the crawl stores what it has and moves on.
YC_COMPANY_TIME_BUDGET: int = int(os.getenv("YC_COMPANY_TIME_BUDGET", "120"))

# ─── Outreach ────────────────────────────────────────────────────────────────
OUTREACH_ENABLED: bool = os.getenv("OUTREACH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
OUTREACH_SENDER_NAME: str = os.getenv("OUTREACH_SENDER_NAME", "")
OUTREACH_SENDER_COMPANY: str = os.getenv("OUTREACH_SENDER_COMPANY", "")
OUTREACH_SENDER_LINK: str = os.getenv("OUTREACH_SENDER_LINK", "")
OUTREACH_KEYWORDS: list[str] = [
    k.strip()
    for k in os.getenv("OUTREACH_KEYWORDS", "backend,python,devops,platform,ai,llm,full stack").split(",")
    if k.strip()
]
OUTREACH_MAX_JOBS_IN_MESSAGE: int = int(os.getenv("OUTREACH_MAX_JOBS_IN_MESSAGE", "3"))
OUTREACH_DEFAULT_CHANNEL: str = os.getenv("OUTREACH_DEFAULT_CHANNEL", "email")
# Per-run send caps. Keep DM volume low to avoid platform challenges.
OUTREACH_X_MAX_PER_RUN: int = int(os.getenv("OUTREACH_X_MAX_PER_RUN", "20"))
OUTREACH_LINKEDIN_MAX_PER_RUN: int = int(os.getenv("OUTREACH_LINKEDIN_MAX_PER_RUN", "10"))
OUTREACH_EMAIL_MAX_PER_RUN: int = int(os.getenv("OUTREACH_EMAIL_MAX_PER_RUN", "50"))
# Randomized pause between DM sends (seconds) to avoid platform challenges.
OUTREACH_DM_MIN_DELAY: int = int(os.getenv("OUTREACH_DM_MIN_DELAY", "45"))
OUTREACH_DM_MAX_DELAY: int = int(os.getenv("OUTREACH_DM_MAX_DELAY", "120"))

# SMTP (email channel)
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "") or SMTP_USER
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}

# ─── Storage ─────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://job_user:job_password@postgres:5432/job_automation",
)
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", str(7 * 24 * 3600)))
DEDUP_WINDOW_HOURS: int = int(os.getenv("DEDUP_WINDOW_HOURS", "24"))

# Kept only for backwards-compatible function signatures in storage.db.
SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", "jobs.db")


# ─── Central Aggregator & Limit Constants ───────────────────────────────────
DEFAULT_SEARCH_LIMIT: int = 500
MAX_SEARCH_LIMIT: int = 1000
DEFAULT_SEARCH_OFFSET: int = 0
DEFAULT_RECENT_HOURS: int = 24
DEFAULT_INDEED_LIMIT: int = 50  # 0 = no limit, fetch all available within date range
DEFAULT_MAX_PAGES: int = 2
DEFAULT_MAX_CONCURRENT_SPIDERS: int = 2
