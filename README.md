# Job Automation Search API

This project runs a local FastAPI service that builds advanced job-search dorks, searches DuckDuckGo, parses results into normalized job objects, and feeds n8n workflows.

## Quick Start

Run the full stack (PostgreSQL + Redis + backend + frontend) with a single command:

```bash
./run.sh
```

This script will:

1. Start **PostgreSQL** and **Redis** containers via Docker Compose
2. Create a Python virtual environment (`.venv`) inside `backend/` if missing
3. Install backend dependencies (`pip3 install -r requirements.txt`) and Playwright's Chromium browser
4. Start the **backend** on `http://0.0.0.0:8000` (uvicorn, 2 workers)
5. Install frontend dependencies (`npm install`) and start the **frontend** dev server

The running processes are tracked in a `.running_pids` file so they can be cleaned up later.

Stop everything (containers + backend + frontend processes):

```bash
./stop.sh
```

## Running Manually (Step by Step)

Start the infrastructure:

```bash
docker compose up -d
```

Start the backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
playwright install chromium
source .venv/bin/activate; uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Check that the API is healthy:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "job-dork-search",
  "time": "2026-05-26T03:28:32.643973"
}
```

### Why the backend runs as a local process and not a container

The backend depends on Playwright/Chromium for headless browser automation. Building a container image with Chromium is slow and produces a very large image every time you rebuild. Running it locally keeps installs cached in the virtual environment, makes iteration faster, and avoids pulling/rebuilding heavy browser layers. So only the lightweight dependencies (PostgreSQL and Redis) run as containers.

## Main Search Endpoint

Endpoint:

```text
POST http://localhost:8000/search
```

Basic example:

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["devops", "terraform", "kubernetes"],
    "job_sites": ["linkedin.com/jobs", "indeed.com/jobs", "lever.co", "greenhouse.io"],
    "location": "onsite",
    "countries": ["egypt"],
    "job_type": "full-time",
    "days_back": 5,
    "recent_hours": 24,
    "posted_today": true,
    "sort_by_posted_at": true,
    "max_results": 50,
    "reset_cache": false
  }' | jq
```

Response shape:

```json
{
  "jobs": [
    {
      "id": "md5-url-hash",
      "title": "DevOps Engineer",
      "company": "Example",
      "url": "https://...",
      "description": "Short snippet...",
      "location": "Remote",
      "salary": "",
      "source": "lever",
      "dork_query": "site:jobs.lever.co ...",
      "posted_at": "2026-05-26T03:27:56.094201",
      "score": 7.5
    }
  ],
  "total_found": 22,
  "new_jobs": 50,
  "cached_skipped": 0,
  "recency_skipped": 6,
  "queries_run": 20,
  "duration_ms": 4200,
  "timestamp": "2026-05-26T03:27:56.100000"
}
```

## Fresh 24-hour feed, scoring & ranking

Every job returned by `/search` is restricted to the **last 24 hours** and
scored on two dimensions. Results are also **remote-only by default**:
listings that mention `hybrid`, `on-site`, `in-office`, `office-based`,
`in person`, or `relocation` are rejected even if they also mention "remote".
Set `REMOTE_ONLY=false` in `backend/.env` or pass `"remote": false` to opt out.

| Field | Meaning |
| --- | --- |
| `score` | Composite ranking score (0–10) = 60% relevance + 40% authenticity |
| `relevance` | Keyword match in title/description/tags + recency + salary/description quality |
| `authenticity` | "Is this job real?" score — penalises scam phrasing, link shorteners, placeholder companies, missing descriptions |
| `verdict` | `legit`, `suspicious`, or `likely_scam` |
| `reasons` | Human-readable explanation of the score |

`/search` accepts `sort` (`score` or `recent`), `min_score` (0–10), and
`posted_hours` (default and recommended value: `24`). Scores are computed at
ingestion time and stored in PostgreSQL, so ranking survives restarts; legacy
rows are backfilled automatically on startup.

## Hiring posts from LinkedIn, X & Reddit

The **Hiring Posts** page (and `POST /search/social/run`) scans public posts
containing phrases like "we are hiring", "hiring now", "looking to hire",
"send your CV", etc., keeps only posts from the last 24 hours **that advertise
remote roles** (hybrid/onsite posts are filtered out), and applies the same
relevance + authenticity scoring.

This is deliberately **manual** — run it from the frontend 2–3 times per day,
never on the hourly scheduler, so the LinkedIn/X accounts are not rate-limited.

1. Put the credentials in `auth-access.txt` at the repo root (git-ignored) or in
   `backend/.env`:
   ```text
   linkedin
   email
   you@example.com
   password
   your-password

   x
   username
   your-handle-or-email
   password
   your-password

   reddit
   username
   your-reddit-username
   password
   your-password
   ```
2. `SOCIAL_HEADLESS=false` (the default) opens a browser window on the first
   run. The login form is filled automatically from these credentials; if
   LinkedIn/X ask for a challenge/2FA, complete it once in that window. The
   persistent profile is stored in `backend/.sessions/` and reused afterwards,
   so later scans skip the login entirely. X's new two-step login
   (username → password) is handled automatically.
3. From the UI: **Hiring Posts → Scan hiring posts now**. Results appear ranked
   once the background scan finishes.

### Re-login / security checks from the UI

If a platform signs the session out, or LinkedIn/X asks for a security check
("verify it's you", CAPTCHA, 2FA), use the **Open LinkedIn login / Open X login**
buttons on the Hiring Posts page (or `POST /search/social/session/open`). They
launch a visible Chromium window with the **same saved profile** the scanner
uses, so anything you complete there is persisted for the next scan.

```bash
curl -X POST http://localhost:8001/search/social/session/open \
  -H "Content-Type: application/json" \
  -d '{"platform": "linkedin"}'
# platform: linkedin | x | reddit
```

- The window opens on the machine running the backend (use it locally).
- Log in / complete the check, then **close the window**. Scans are blocked
  while a login window is open because Chromium locks the profile directory.
- Windows close automatically after `SOCIAL_BROWSER_TIMEOUT` seconds (default
  `900`) so a forgotten window cannot block scans forever.
- `GET /search/social/status` includes a `sessions` map with the open/closed
  state of each platform's login browser.

### Reddit source

Reddit is read through its public Atom feeds, so it works without logging in:

```text
https://www.reddit.com/r/forhire/new/.rss
https://www.reddit.com/r/jobbit/new/.rss
https://www.reddit.com/r/remotejobs/new/.rss
https://www.reddit.com/r/hiring/new/.rss
```

`r/forhire` is always scanned; the others rotate daily within a 3-feed budget to
respect Reddit's tight public rate limit (~1 request every 20 seconds). Both
`[Hiring]` and `[For Hire]` posts appear in these feeds — candidate ads are
dropped, then the shared remote/tech/24h/region filters run as usual.

Optional tuning in `backend/.env`:

```text
REDDIT_SUBREDDITS=forhire,jobbit,remotejobs,hiring
REDDIT_MAX_SUBREDDITS=3
REDDIT_REQUEST_DELAY=20
REDDIT_RATE_LIMIT_WAIT=40
REDDIT_USERNAME=your-reddit-username
REDDIT_PASSWORD=your-password
```

`REDDIT_USERNAME`/`REDDIT_PASSWORD` alone are not enough for Reddit's HTTP API —
it requires a registered "script" app. If you add `REDDIT_CLIENT_ID` and
`REDDIT_CLIENT_SECRET` (from <https://www.reddit.com/prefs/apps>), the collector
uses the authenticated OAuth JSON API with much higher rate limits and fetches
all configured subreddits in one scan. Otherwise it falls back to the public
feeds above.

Endpoints:

```text
POST /search/social/run          # start a manual scan (background)
POST /search/social/session/open # open a headed browser to re-login / clear checks
GET  /search/social              # ranked posts (24h, filters: platform, min_score, keywords)
GET  /search/social/status       # credential/session availability + last scan result
```

> **Security:** `auth-access.txt` and `backend/.sessions/` are git-ignored. Do
> not commit them. Automated access to logged-in LinkedIn/X accounts is against
> their terms of service — use your own account and keep volume low.

## MENA remote aggregation (Saudi Arabia, UAE, Egypt, Qatar, …)

Job searches accept any of `egypt`, `saudi arabia`, `united arab emirates`
(`uae`/`emirates`/`dubai`), `qatar`, `kuwait`, `bahrain`, `oman`, `jordan`,
`middle east`/`mena`/`gulf`. Country names are expanded to capital/city and
Arabic terms in the database filter, the spiders, and the Google dorks.

Newly registered MENA spiders:

| Country | LinkedIn | Indeed |
| --- | --- | --- |
| Egypt | `linkedin_eg` | `indeed_eg` |
| Saudi Arabia | `linkedin_sa` | `indeed_sa` |
| United Arab Emirates | `linkedin_ae` | `indeed_ae` |
| Qatar | `linkedin_qatar` | `indeed_qa` |
| Kuwait | `linkedin_kuwait` | `indeed_kw` |
| Bahrain | `linkedin_bahrain` | `indeed_bh` |
| Oman | `linkedin_oman` | `indeed_om` |
| Jordan | `linkedin_jordan` | `indeed_jo` |

All LinkedIn jobs are queried with `f_WT=2` (remote) and Indeed with the
`DSQF7` remote attribute, so hybrid/onsite listings never enter the pipeline.
`middle east` / `mena` / `gulf` fans out to every MENA spider.

```bash
# Remote jobs across the Gulf + Egypt
curl -X POST http://localhost:8001/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["devops", "backend", "python"],
    "countries": ["egypt","saudi arabia","united arab emirates","qatar","kuwait","bahrain","oman","jordan"],
    "remote": true,
    "sort": "score",
    "posted_hours": 24,
    "limit": 100
  }' | jq '.results[] | {country, job_boards: [.job_boards[] | {name, count: (.jobs|length)}]}'
```

### Control panel (manual per-country scrapes)

The **Control Panel** (`/control`) runs one board for one country, e.g.
Egypt → LinkedIn (`linkedin_eg`) or Egypt → Indeed (`indeed_eg`). The scrape runs
in the background and saves to PostgreSQL; **View scraped jobs** opens Job Search
with **Location type: Any**, so onsite/hybrid listings are visible too.

- **Control-panel scrapes keep onsite, hybrid, and any-location jobs.** They set
  `include_onsite=true`, which skips the remote-only policy and removes
  LinkedIn's `f_WT=2` flag. The normal `/search` and scheduled remote runs keep
  the remote-only policy.
- **LinkedIn** is still limited to the last 24h (`f_TPR=r86400`). Arabic relative
  dates (`قبل ٧ ساعة`) are parsed. On normal remote runs (not control-panel),
  MENA cards usually show the city instead of "Remote", so the source's remote
  filter is recorded as a `Remote` tag.
- **Indeed** now serves a client-rendered app behind Cloudflare, so its spiders
  use the `stealth` browser fetcher (`wait: 8000`, `load_dom`) and no longer use
  the retired `sc=0kf:attr(DSQF7)` remote parameter (it returns “No Result”).
  A scrape can take ~2 minutes while Cloudflare is solved.
- Indeed country boards (`eg.indeed.com`, `sa.indeed.com`, …) are onsite-heavy
  and no longer expose a remote facet. Remote-only sub-aggregation is available
  by setting `include_onsite` to `false` in the API request; in that mode, if a
  country board returns fewer than 5 jobs the aggregator supplements it with
  Indeed's **global remote** pool (`www.indeed.com/jobs?l=Remote`), saved under
  the `indeed_remote` source and grouped by the job's real location (`Remote`,
  `United States`, …). The control panel always sends `include_onsite: true`.
- The Indeed query uses a focused 4-term tech list (`software engineer`,
  `devops`, `backend developer`, `full stack developer`). Quoted phrases and
  long OR chains (10+ terms) make Indeed return an empty page.
- If a 24h Indeed pass produces **no usable jobs**, the same browser session
  automatically retries once with `fromage=2` (48 hours). The retry reuses the
  already-solved Cloudflare session, so it adds seconds rather than another
  browser launch.
- Control-panel runs are capped to one page per board (`MAX_PAGES=1`) so a
  manual click stays fast.

### Social scans for MENA

`POST /search/social/run` accepts `countries` and `strict_region`:

```bash
curl -X POST http://localhost:8001/search/social/run \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["devops", "backend", "data engineer"],
    "platforms": ["linkedin", "x", "reddit"],
    "countries": ["egypt","saudi arabia","united arab emirates","qatar","middle east"],
    "max_posts": 40,
    "strict_region": true
  }'
```

- **LinkedIn**: one content-search query per country, e.g.
  `hiring devops remote Egypt`, `"we are hiring" backend remote Qatar`
  (LinkedIn does not support long OR clauses in post search).
- **X**: English hashtag queries (`#hiring`, `#remotejobs`) plus Arabic hashtag
  queries (`#وظائف`, `#توظيف`) scoped to Gulf/Egypt cities, always `remote`.
- **Reddit**: newest posts from `r/forhire`, `r/jobbit`, `r/remotejobs` and
  `r/hiring` (public Atom feeds; `[For Hire]` candidate ads are dropped).
- `strict_region: true` keeps only posts whose text mentions one of the
  selected countries/cities or `MENA`/`Gulf`/`EMEA`.

Read the results with:

```bash
curl "http://localhost:8001/search/social?platform=all&min_score=5&limit=50" | jq '.posts[] | {platform, author, score, verdict, post_url}'
```

## Other websites you can scrape

Already supported out of the box:

| Source | Type | Notes |
| --- | --- | --- |
| LinkedIn (`linkedin_*`) | Job board | Country variants; remote + 24h filters |
| Indeed (`indeed_*`) | Job board | Country variants; remote attribute |
| Reddit (`r/forhire`, `r/jobbit`, `r/remotejobs`, `r/hiring`) | Social hiring posts | Public Atom feeds; manual scans only |
| RemoteOK | Remote board | Plain HTML |
| We Work Remotely | Remote board | Programming/DevOps categories |
| Jobicy | API | `/api/v2/remote-jobs` |
| Remotive | API | `category=software-dev` |
| Himalayas | API | Remote jobs JSON |
| TrueUp | Job board | Stealth fetcher (JS-heavy) |
| Greenhouse / Lever / Workable / Ashby | ATS | Via Google dorks (`site:`) |
| Google / Serper / SerpApi | Search engine | Set `SERPER_API_KEY` or `SERPAPI_API_KEY` |

High-value sites to add next (MENA first):

| Site | Region | Type | Notes |
| --- | --- | --- | --- |
| **Bayt.com** | MENA | Job board | Largest Gulf board; search pages are HTML |
| **GulfTalent** | Gulf | Job board | Strong UAE/Saudi coverage |
| **Naukrigulf** | Gulf | Job board | Naukri's Gulf edition |
| **Wuzzuf** | Egypt | Job board | Egypt's largest tech board |
| **Akhtaboot** | MENA | Job board | Jordan/Lebanon/Gulf |
| **Tanqeeb** | MENA | Aggregator | Aggregates many Gulf boards |
| **Dubizzle Jobs** | UAE | Classifieds | Dubai/Abu Dhabi listings |
| **Laimoon** | MENA | Aggregator | Gulf + Egypt |
| **GulfCareerHunt** | Gulf | Social/board | Frequent LinkedIn/X hiring posts |
| **Wellfound** | Global | Startup jobs | Remote-friendly; HTML/JSON |
| **Glassdoor** | Global | Job board | Heavy bot protection |
| **ZipRecruiter** | US | Job board | Requires session/API |
| **Dice** | US tech | Job board | API-ish endpoints |
| **Hacker News “Who is hiring”** | Global | Forum | Free Algolia API (`hn.algolia.com/api/v1`) |
| **Remote.co / JustRemote / Working Nomads / NoDesk / Jobspresso** | Global remote | Boards | Mostly static HTML/RSS |
| **FlexJobs** | Global remote | Paid board | Requires subscription |
| **Jobvite / SmartRecruiters / Recruitee / Teamtailor / Personio** | Global | ATS | Public board APIs/JSON |
| **Workday** | Global | ATS | `myworkdayjobs.com` JSON endpoints, per-company |
| **Adzuna / Jooble / Careerjet / Arbeitnow / Findwork** | Global | Aggregator APIs | Free/paid API keys |

### Adding a new site

1. Add a `SiteConfig` in `backend/config/settings.py` (name, start URL,
   fetcher: `http`, `dynamic`, or `stealth`, pagination selector).
2. Add a spider class in `backend/spiders/job_spiders.py` implementing
   `extract_jobs()` and yielding `title`, `company`, `location`, `url`,
   `description`, `tags`, `salary`, `date_posted`.
3. Register it in `ALL_SPIDERS` and (if country-specific) in
   `find_matching_spiders()` and `/search/countries`.
4. For social platforms, add a collector under `backend/services/social/` and
   register it in `COLLECTORS`.

```python
# settings.py
SiteConfig(
    name="bayt_uae",
    start_urls=["https://www.bayt.com/en/uae/jobs/?filters[remote]=1"],
    fetcher="http",
    download_delay=2.5,
)

# job_spiders.py
class BaytUAESpider(BaseJobSpider):
    site_config = _cfg("bayt_uae")

    async def extract_jobs(self, response):
        for card in response.css("li.has-pointer-d"):
            yield {
                "title": card.css("h2 a::text").get("").strip(),
                "company": card.css("b::text").get("").strip(),
                "location": card.css(".t-mute::text").get("").strip(),
                "url": "https://www.bayt.com" + card.css("h2 a::attr(href)").get(""),
                "description": " ".join(card.css(".t-small::text").getall()).strip(),
                "tags": [],
                "salary": "",
                "date_posted": card.css("time::attr(datetime)").get(""),
            }
```

> Always check a site's `robots.txt` and Terms of Service before scraping, use
> polite delays, and prefer official APIs/feeds where they exist.

## Use Cases

### Country and Region Targeting

Use the `countries` array to expand geographic dorks.

- `egypt`: searches remote, hybrid, and onsite jobs using Egypt/Cairo terms.
- `mena`: searches remote jobs across MENA/Middle East/Gulf terms.
- `eu` or `europe`: searches remote jobs across EU/Europe terms.
- `usa` or `us`: searches remote US jobs.
- `canada` or `canda`: searches remote Canada jobs.
- `uk`: searches remote UK jobs.
- `worldwide`: searches global remote jobs.

Unknown country names still work. For example, `"countries": ["germany"]` creates remote Germany dorks.

`days_back: 1` makes DuckDuckGo use its past-day search window and adds an `after:` dork date.

`recent_hours: 24` applies a strict API-side filter against each parsed `posted_at`. With `strict_recent: true`, jobs without a parseable timestamp are excluded instead of being treated as new.

Use `sort_by_posted_at: true` to sort newest jobs first.

### Recency Modes

Last hour only:

```json
{
  "days_back": 1,
  "recent_hours": 1,
  "strict_recent": true,
  "sort_by_posted_at": true
}
```

Today only:

```json
{
  "days_back": 1,
  "posted_today": true,
  "strict_recent": true,
  "sort_by_posted_at": true
}
```

Last 24 hours:

```json
{
  "days_back": 1,
  "recent_hours": 24,
  "strict_recent": true,
  "sort_by_posted_at": true
}
```

### 1. DevOps Remote Jobs, Latest 24 Hours

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["devops", "kubernetes", "terraform", "aws"],
    "job_sites": ["linkedin.com/jobs", "indeed.com/jobs", "weworkremotely.com", "remotive.com"],
    "location": "remote",
    "countries": ["egypt", "mena", "eu", "usa", "canada"],
    "job_type": "full-time",
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 20
  }' | jq '.jobs[] | {title, company, source, score, url}'
```

### 2. ATS-Only Search, 30+ Results

Best for direct application links from Greenhouse, Lever, Workable, and Ashby.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["backend engineer", "platform engineer", "fastapi", "golang"],
    "job_sites": ["greenhouse.io", "lever.co", "workable.com", "jobs.ashbyhq.com"],
    "location": "remote",
    "countries": ["egypt", "mena", "eu", "usa", "canada"],
    "job_type": "full-time",
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 60
  }' | jq
```

### 3. Contract/Freelance Cloud Roles, Latest 24 Hours

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["cloud engineer", "aws", "terraform", "serverless"],
    "job_sites": ["linkedin.com/jobs", "indeed.com/jobs", "wellfound.com", "lever.co"],
    "location": "remote",
    "countries": ["mena", "eu", "usa", "canada", "uk"],
    "job_type": "contract",
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 40
  }' | jq '.jobs[] | {title, company, location, salary, score, url}'
```

### 4. Egypt Jobs: Remote, Hybrid, and Onsite

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["backend engineer", "devops", "platform engineer", "full stack engineer"],
    "job_sites": ["linkedin.com/jobs", "indeed.com/jobs", "greenhouse.io", "lever.co"],
    "location": "remote",
    "countries": ["egypt"],
    "job_type": "full-time",
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 50
  }' | jq
```

For Egypt, the generated dorks include remote, hybrid, and onsite variants automatically.

### 5. MENA/EU/USA/Canada Remote Sweep

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["terraform", "kubernetes", "python", "golang", "aws"],
    "job_sites": ["linkedin.com/jobs", "indeed.com/jobs", "remotive.com", "greenhouse.io", "lever.co"],
    "location": "remote",
    "countries": ["mena", "eu", "usa", "canada"],
    "job_type": "full-time",
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 60
  }' | jq '.jobs[] | {title, company, location, source, score, url}'
```

### 6. Fresh Scan Without API Cache

Use `reset_cache: true` when testing and you want the API to forget its in-memory URL cache.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["python fastapi", "backend engineer"],
    "job_sites": ["lever.co", "greenhouse.io"],
    "location": "remote",
    "countries": ["egypt", "mena", "eu", "usa", "canada"],
    "days_back": 1,
    "recent_hours": 24,
    "strict_recent": true,
    "sort_by_posted_at": true,
    "max_results": 40,
    "reset_cache": true
  }' | jq
```

If a job board/search snippet does not expose a date like `2 hours ago`, `today`, `2026-05-26`, or another parseable timestamp, strict mode filters it out. Set `"strict_recent": false` if you prefer to keep unknown-date jobs and sort them after dated jobs.

## Preview Generated Dorks

Use this before a real search to inspect the generated queries.

```bash
curl "http://localhost:8000/queries/preview?keywords=devops,kubernetes&sites=linkedin.com/jobs,greenhouse.io&location=remote&countries=egypt,mena,eu,usa,canada&days_back=1" | jq
```

The builder creates four strategy types:

- `intitle+site`: best for LinkedIn, WWR, Remotive.
- `inurl+ats`: best for Greenhouse, Lever, Workable, Ashby.
- `broad+filters`: adds job type and experience filters.
- `broad-multi`: broad sweep with `job posting`, `apply now`, and `after:YYYY-MM-DD`.

## Cache Utilities

View API cache stats:

```bash
curl http://localhost:8000/cache/stats | jq
```

Clear API cache:

```bash
curl -X DELETE http://localhost:8000/cache | jq
```

Note: this API cache is separate from the n8n SQLite `seen_jobs` table. The API cache prevents duplicate URLs during local search runs, while SQLite prevents sending the same job to Telegram again.
