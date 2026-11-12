# YC Founder Sourcing & Outreach Pipeline

Automates the workflow:

```
YC directory (2025–2026 batches)
  → companies
  → active founders (bio, title)
  → contacts (X, LinkedIn, email)
  → open roles
  → personalized outreach drafts
  → human review
  → send (email / X DM / LinkedIn DM)
```

Nothing is sent automatically. Drafts must be **approved** from the frontend first.

## Data sources

| Step | Source | Notes |
|---|---|---|
| Company list | `https://api.ycombinator.com/v0.1/companies?batch=...&page=...` | Public JSON API, paginated (20/page). |
| Company details, founders, jobs, launches | `https://www.ycombinator.com/companies/{slug}` | Server-rendered page embeds the full Inertia payload (`data-page`), so one request gives founders, job postings and launch content. |
| Founder details | `https://www.ycombinator.com/founders/{slug}` | Only fetched when the Inertia payload is missing a bio/social link; adds batches and canonical bio. |
| Emails | YC launch post `mailto:` links → company website (`/`, `/contact`, `/about`, `/careers`) → role-pattern guess | Verified vs `guessed` confidence is stored so the review queue can flag guesses. |

No YC login is required. Requests are throttled (`YC_REQUEST_DELAY`, default 1.2s).

## Database tables

- `yc_companies` — company record, batch, hiring badge, website, team size, discovered email, jobs count.
- `yc_founders` — active founders, bio/title, X handle + URL, LinkedIn URL, email + source/confidence, `yc_has_email`.
- `yc_company_jobs` — open roles scraped from the company page.
- `outreach_messages` — one row per founder/channel, with `status` (`draft → approved → sent | failed | skipped`) and a unique fingerprint (never duplicate a founder/channel).

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/yc/collect` | Start a background crawl (`batches`, caps, `skip_existing`, `discover_emails`). |
| `POST` | `/yc/collect/stop` | Request a cooperative stop of the running crawl. |
| `GET` | `/yc/status` | Crawl progress + pipeline stats. |
| `GET` | `/yc/companies` | List companies (`batch`, `is_hiring`, `q`, paging). |
| `GET` | `/yc/founders` | List founders with jobs (`batch`, `q`, `has_email`, `has_x`, `has_linkedin`, `company_slug`). |
| `GET` | `/yc/jobs` | List open roles across companies (`batch`, `q`, `company_slug`, paging). |
| `POST` | `/yc/outreach/draft` | Generate drafts for founders with a usable contact (`channels`, `keywords`, `batch`, `company_slug`, `limit`). |
| `GET` | `/yc/outreach` | Review queue (`status`, `channel`, paging). |
| `GET` | `/yc/outreach/{id}` | One message. |
| `PATCH` | `/yc/outreach/{id}` | Edit subject/body or change status. |
| `POST` | `/yc/outreach/{id}/approve` | Approve a draft. |
| `POST` | `/yc/outreach/{id}/skip` | Skip a draft. |
| `POST` | `/yc/outreach/send` | Send approved messages for one channel (`dry_run` supported). |
| `GET` | `/yc/export.csv` | Export founders/contacts as CSV. |

## Frontend

Route: **`/yc-founders`** (linked from the top nav as “YC Founders”).

- **Collection** — pick batches (all 2025 + 2026 by default), start the crawl, watch live progress and errors. A **Stop collection** button requests a cooperative stop; every HTTP request also has a hard timeout and requests are skipped after the stop flag is set.
- **Founders / Companies / Open roles** — searchable, filterable lists (with “Load more” paging) showing founder avatars, company logos, X/LinkedIn/email chips, open roles, and company details.
- **Outreach queue** — generate drafts, edit, approve/skip, then send approved messages per channel. Dry-run is the default in the UI.

## Configuration (`backend/.env`)

```ini
# Crawl
YC_ENABLED=true
YC_BATCHES=Winter 2025,Spring 2025,Summer 2025,Fall 2025,Winter 2026,Spring 2026,Summer 2026,Fall 2026
YC_REQUEST_DELAY=1.2
YC_MAX_COMPANIES_PER_BATCH=0        # 0 = unlimited
YC_MAX_PAGES_PER_BATCH=0            # 0 = unlimited
YC_DISCOVER_EMAILS=true
YC_MAX_WEBSITE_PAGES=3
# Max seconds spent enriching one company before moving on.
YC_COMPANY_TIME_BUDGET=120
YC_EMAIL_PATTERN_GUESS=true

# Outreach copy / signature
OUTREACH_SENDER_NAME=Your Name
OUTREACH_SENDER_COMPANY=Your Company
OUTREACH_SENDER_LINK=https://example.com
OUTREACH_KEYWORDS=backend,python,devops,platform,ai,llm,full stack
OUTREACH_MAX_JOBS_IN_MESSAGE=3

# Per-run caps (keep DMs low to avoid platform challenges)
OUTREACH_EMAIL_MAX_PER_RUN=50
OUTREACH_X_MAX_PER_RUN=20
OUTREACH_LINKEDIN_MAX_PER_RUN=10
OUTREACH_DM_MIN_DELAY=45
OUTREACH_DM_MAX_DELAY=120

# Email channel (SMTP)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASSWORD=...
SMTP_FROM=you@example.com
SMTP_USE_TLS=true
```

DM sending reuses the persistent Playwright profiles from `services/social/browser.py`
(`.sessions/linkedin_profile`, `.sessions/x_profile`). If a profile is not logged in,
open the **Hiring Posts** page and run a scan once to complete the login, then retry.

## CLI

```bash
cd backend
python3 -m usecases.yc_collect --stats
python3 -m usecases.yc_collect --batches "Spring 2026" --max-companies 5 --max-pages 1
python3 -m usecases.yc_collect --skip-existing --no-emails
python3 -m usecases.yc_collect --draft --batch "Spring 2026" --channels email,linkedin
python3 -m usecases.yc_avatars --limit 50 --delay 0.5   # backfill founder avatars
```

## Safety notes

- **Review queue only** — sending requires explicit approval; the dry-run flow is the default.
- **Platform ToS** — automated DMs on X/LinkedIn can violate their terms and risk account
  restrictions. Volumes are capped and randomized; stop immediately if a challenge appears.
- **Guessed emails** are marked `email_confidence=guessed` and shown as “guessed” in the UI.
- **Polite crawling** — the pipeline uses the public YC API and throttled page requests.
