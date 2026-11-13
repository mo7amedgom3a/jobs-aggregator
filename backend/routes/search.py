"""Search endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, BackgroundTasks

from cache.cache import DeduplicationCache
from dependencies import get_cache, get_google_job_search_service, get_orchestrator, get_job_repository
from models.job import (
    SearchRequest,
    SearchResponse,
    JobSearchRequest,
    CountryGroup,
    PaginatedSearchResponse,
    SubAggregateRequest,
    CountryInfo,
    CountriesResponse,
    HiringPostsResponse,
    HiringPost,
    SocialScanRequest,
    SocialScanResponse,
    SocialSessionRequest,
    SocialSessionResponse,
    SocialStatusResponse,
)
from repository.jobs import JobRepository
from services.google_search import GoogleJobSearchService
from services.orchestrator import JobOrchestrator
from config.settings import KEYWORDS, INDEED_KEYWORDS
logger = logging.getLogger("job_aggregator.routes.search")

router = APIRouter(prefix="/search", tags=["search"])


def resolve_country(job: dict) -> str:
    source = (job.get("source") or "").lower()
    
    # Direct source mappings
    if "eg" in source:
        return "Egypt"
    if "sa" in source:
        return "Saudi Arabia"
    if "ae" in source:
        return "United Arab Emirates"
    if "germany" in source:
        return "Germany"
    if "uk" in source:
        return "United Kingdom"
    if "poland" in source:
        return "Poland"
    if "canada" in source:
        return "Canada"
    if "spain" in source or "barcelona" in source:
        return "Spain"
    if "qatar" in source or source.endswith("_qa"):
        return "Qatar"
    if "kuwait" in source or source.endswith("_kw"):
        return "Kuwait"
    if "bahrain" in source or source.endswith("_bh"):
        return "Bahrain"
    if "oman" in source or source.endswith("_om"):
        return "Oman"
    if "jordan" in source or source.endswith("_jo"):
        return "Jordan"
        
    # Check location/tags
    loc = (job.get("location") or "").lower()
    tags = "".join(job.get("tags") or []).lower()
    
    countries_to_check = {
        "Egypt": ["egypt", "cairo", "alexandria"],
        "Saudi Arabia": ["saudi", "riyadh", "jeddah"],
        "United Arab Emirates": ["uae", "dubai", "abu dhabi", "united arab emirates", "emirates", "emarties"],
        "Germany": ["germany", "berlin", "munich", "frankfurt"],
        "Poland": ["poland", "warsaw", "krakow"],
        "Canada": ["canada", "toronto", "vancouver", "montreal"],
        "Spain": ["spain", "barcelona", "madrid"],
        "United States": ["usa", "united states", "us", "new york", "san francisco", "california"],
        "United Kingdom": ["uk", "united kingdom", "london", "england"],
        "Qatar": ["qatar", "doha"],
        "Kuwait": ["kuwait", "kuwait city"],
        "Bahrain": ["bahrain", "manama"],
        "Oman": ["oman", "muscat"],
        "Jordan": ["jordan", "amman"],
    }
    
    for country, keywords in countries_to_check.items():
        if any(kw in loc for kw in keywords) or any(kw in tags for kw in keywords):
            return country
            
    return "Remote"


def clean_job_board_name(source: str) -> str:
    src = source.lower()
    if src.startswith("linkedin"):
        return "linkedin"
    if src.startswith("indeed"):
        return "indeed"
    return src


def is_job_remote(job: dict) -> bool:
    from services.filters import is_hybrid_or_onsite, is_remote_only

    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    tags = "".join(job.get("tags") or []).lower()
    source = (job.get("source") or "").lower()

    # Explicitly hybrid/onsite wins over any "remote" mention.
    if is_hybrid_or_onsite(f"{title} {location} {tags}"):
        return False

    remote_sources = {"remoteok", "weworkremotely", "jobicy", "remotive", "himalayas", "trueup"}
    if source in remote_sources:
        return True

    return is_remote_only(job)


@router.post(
    "",
    response_model=PaginatedSearchResponse,
    summary="Search Aggregated Jobs",
    description="Retrieves aggregated job listings from the database, grouped by country and job board, returning remote jobs.",
)
async def search_jobs(
    req: JobSearchRequest,
    repository: JobRepository = Depends(get_job_repository),
) -> dict[str, Any]:
    import hashlib
    from services.scoring import score_job

    logger.info("Search request received: %s", req)
    db_jobs, total_count = repository.search_jobs(
        keywords=req.keywords,
        countries=req.countries,
        company=req.company,
        remote=req.remote,
        limit=req.limit,
        offset=req.offset,
        posted_hours=req.posted_hours,
        min_score=req.min_score,
        sort_by=req.sort,
    )
    
    grouped_data = {} # country -> job_board_name -> list of jobs
    
    for row in db_jobs:
        tags_val = row.get("tags") or ""
        tags_list = tags_val.split(",") if tags_val else []
        posted_at_value = row.get("posted_at")
        scraped_at_value = row.get("scraped_at")

        def _iso(value: Any) -> str:
            return value.isoformat() if hasattr(value, "isoformat") else str(value or "")

        reasons_value = row.get("score_reasons") or ""
        job_dict = {
            "id": hashlib.md5(row.get("url", "").encode()).hexdigest(),
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "url": row.get("url", ""),
            "description": row.get("description", ""),
            "location": row.get("location", ""),
            "salary": row.get("salary", ""),
            "source": row.get("source", ""),
            "site": row.get("source", ""),
            "tags": tags_list,
            "scraped_at": _iso(scraped_at_value),
            "posted_at": _iso(posted_at_value) if posted_at_value else _iso(scraped_at_value),
        }

        # Backfill scores for rows ingested before scoring existed.
        if row.get("score") is None:
            breakdown = score_job(job_dict, keywords=req.keywords)
            job_dict.update(
                {
                    "score": breakdown.score,
                    "relevance": breakdown.relevance,
                    "authenticity": breakdown.authenticity,
                    "verdict": breakdown.verdict,
                    "reasons": breakdown.reasons,
                }
            )
        else:
            job_dict.update(
                {
                    "score": round(row["score"], 2) if row.get("score") is not None else None,
                    "relevance": round(row["relevance"], 2) if row.get("relevance") is not None else None,
                    "authenticity": round(row["authenticity"], 2) if row.get("authenticity") is not None else None,
                    "verdict": row.get("verdict"),
                    "reasons": [r for r in reasons_value.split(" | ") if r],
                }
            )
        
        # Filter remote/non-remote based on requested parameter
        if req.remote is not None:
            is_remote = is_job_remote(job_dict)
            if is_remote != req.remote:
                continue
            
        country = resolve_country(job_dict)
        board = clean_job_board_name(job_dict["source"])
        
        grouped_data.setdefault(country, {}).setdefault(board, []).append(job_dict)
        
    response_data = []
    for country_name, boards in grouped_data.items():
        board_groups = []
        for board_name, jobs_list in boards.items():
            # Sort jobs in each board by score or recency.
            if req.sort == "recent":
                jobs_list.sort(key=lambda x: x.get("posted_at") or x.get("scraped_at", ""), reverse=True)
            else:
                jobs_list.sort(
                    key=lambda x: (x.get("score") or 0, x.get("posted_at") or x.get("scraped_at", "")),
                    reverse=True,
                )
            board_groups.append({
                "name": board_name,
                "jobs": jobs_list
            })
        response_data.append({
            "country": country_name,
            "job_boards": board_groups
        })
        
    return {
        "total": total_count,
        "limit": req.limit,
        "offset": req.offset,
        "results": response_data
    }


@router.post(
    "/orchestrate",
    response_model=dict[str, list[dict]],
    summary="Orchestrate Spiders & Google Search",
    description="Runs concurrent country-specific scrapers (using Playwright) and Google Search queries in parallel. Restricts execution to spiders matching the target country and remote parameters.",
)
async def search_orchestrate(
    req: SearchRequest,
    orchestrator: JobOrchestrator = Depends(get_orchestrator),
    cache: DeduplicationCache = Depends(get_cache),
) -> dict[str, list[dict]]:
    logger.info("Received orchestrated search request")
    if req.reset_cache:
        cache.clear()
    return await orchestrator.orchestrate(req)


async def run_full_aggregation(
    orchestrator: JobOrchestrator,
    cache: DeduplicationCache,
    repository: JobRepository,
) -> None:
    logger.info("Starting background full aggregation run...")
    try:
        req = SearchRequest()
        # Live scrape / aggregation
        results = await orchestrator.orchestrate(req)
        flat_jobs = flatten_results(results, max_results=500, sources=["linkedin", "indeed", "google"])

        # Save all aggregated jobs to database (idempotent, duplicates handled via UNIQUE fingerprint)
        fingerprints = []
        for job in flat_jobs:
            source = job.get("source") or job.get("site") or "aggregate"
            job["_keywords"] = req.keywords
            fp = repository.fingerprint(job, source=source)
            fingerprints.append(fp)
            repository.save_job(job, source=source)

        # Cache the list of fingerprints for 1 hour (3600 seconds)
        import json
        cache_key = "aggregate:latest"
        cache.set_value(cache_key, json.dumps(fingerprints), 3600)
        logger.info("Background aggregation completed successfully. Saved %d jobs.", len(flat_jobs))
    except Exception as e:
        logger.error("Error in background aggregation task: %s", e, exc_info=True)


@router.post(
    "/aggregate",
    summary="Trigger Background Aggregation Process",
    description="Initiates background tasks to scrape jobs from all registered spiders and run the Google Search template. Caches results and saves them in the database.",
)
async def search_aggregate(
    background_tasks: BackgroundTasks,
    orchestrator: JobOrchestrator = Depends(get_orchestrator),
    cache: DeduplicationCache = Depends(get_cache),
    repository: JobRepository = Depends(get_job_repository),
) -> dict[str, str]:
    logger.info("Initiating background job aggregation task")
    background_tasks.add_task(
        run_full_aggregation,
        orchestrator=orchestrator,
        cache=cache,
        repository=repository
    )
    return {"status": "initiated", "message": "Aggregation process started in the background."}


@router.post(
    "/jobspy",
    response_model=list[dict],
    summary="Legacy JobSpy Search Compatibility Route",
    description="A flattened list containing jobs specifically aggregated from LinkedIn and Indeed. Compatible with legacy client applications.",
)
async def search_jobspy(
    req: SearchRequest,
    orchestrator: JobOrchestrator = Depends(get_orchestrator),
    cache: DeduplicationCache = Depends(get_cache),
) -> list[dict[str, Any]]:
    logger.info("Routing legacy search/jobspy endpoint to custom spider engine")
    if req.reset_cache:
        cache.clear()

    results = await orchestrator.orchestrate(req)
    return flatten_results(results, max_results=req.max_results, sources=["linkedin", "indeed"])


def flatten_results(
    results: dict[str, list[dict[str, Any]]],
    max_results: int,
    sources: list[str],
) -> list[dict[str, Any]]:
    from services.scoring import score_and_annotate

    unified: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for source in sources:
        for job in results.get(source, []):
            url = job.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            job["site"] = source
            unified.append(score_and_annotate(job))

    unified.sort(key=lambda job: job.get("score", 0), reverse=True)
    return unified[:max_results]


def find_matching_spiders(country: str, job_board: str) -> list[str]:
    c = country.lower().strip()
    jb = job_board.lower().strip()
    
    country_mappings = {
        "egypt": ["eg", "egypt"],
        "eg": ["eg", "egypt"],
        "saudi arabia": ["sa", "saudi"],
        "saudi": ["sa", "saudi"],
        "sa": ["sa", "saudi"],
        "united arab emirates": ["ae", "uae", "emirates"],
        "uae": ["ae", "uae", "emirates"],
        "ae": ["ae", "uae", "emirates"],
        "emirates": ["ae", "uae", "emirates"],
        "emarties": ["ae", "uae", "emirates"],
        "germany": ["germany", "de"],
        "de": ["germany", "de"],
        "poland": ["poland", "pl"],
        "pl": ["poland", "pl"],
        "spain": ["spain", "barcelona", "es"],
        "es": ["spain", "barcelona", "es"],
        "barcelona": ["barcelona", "spain"],
        "canada": ["canada", "ca"],
        "ca": ["canada", "ca"],
        "united kingdom": ["uk", "gb", "united kingdom"],
        "uk": ["uk", "gb", "united kingdom"],
        "gb": ["uk", "gb", "united kingdom"],
        "qatar": ["qatar", "qa"],
        "qa": ["qatar", "qa"],
        "doha": ["qatar", "qa"],
        "kuwait": ["kuwait", "kw"],
        "kw": ["kuwait", "kw"],
        "bahrain": ["bahrain", "bh"],
        "bh": ["bahrain", "bh"],
        "oman": ["oman", "om"],
        "om": ["oman", "om"],
        "jordan": ["jordan", "jo"],
        "jo": ["jordan", "jo"],
        "middle east": ["sa", "ae", "eg", "qa", "kw", "bh", "om", "jo", "saudi", "uae", "egypt", "qatar", "kuwait", "bahrain", "oman", "jordan"],
        "mena": ["sa", "ae", "eg", "qa", "kw", "bh", "om", "jo", "saudi", "uae", "egypt", "qatar", "kuwait", "bahrain", "oman", "jordan"],
    }
    
    country_targets = country_mappings.get(c, [c])
    
    from config.settings import SITES
    matched = []
    for site in SITES:
        name = site.name.lower()
        if jb in name:
            parts = name.split('_')
            suffix = parts[1] if len(parts) > 1 else ""
            if any(t == suffix or t in parts for t in country_targets):
                matched.append(site.name)
            elif any(t in name for t in country_targets if len(t) > 2):
                matched.append(site.name)
                
    if not matched:
        for site in SITES:
            name = site.name.lower()
            if jb in name and any(t in name for t in country_targets):
                matched.append(site.name)
                
    return matched


async def run_sub_aggregation(
    country: str,
    job_board: str,
    orchestrator: JobOrchestrator,
    cache: DeduplicationCache,
    repository: JobRepository,
    include_onsite: bool = True,
) -> None:
    logger.info(
        "Starting background sub-aggregation for country=%s, job_board=%s (include_onsite=%s)...",
        country,
        job_board,
        include_onsite,
    )
    try:
        from services.filters import is_blacklisted_company
        import json
        import asyncio

        spiders_to_run = find_matching_spiders(country, job_board)
        if not spiders_to_run:
            logger.warning("No matching spiders found for country=%s, job_board=%s", country, job_board)
            return

        req = SearchRequest(countries=[country])
        default_req_keywords = KEYWORDS
        use_settings_keywords = not req.keywords or req.keywords == default_req_keywords

        
        
        logger.info("Executing sub-aggregation spiders: %s", spiders_to_run)
        
        semaphore = asyncio.Semaphore(orchestrator.max_concurrent_spiders)

        async def run_spider(name: str) -> list[dict[str, Any]]:
            from config.settings import SITES
            cfg = next((s for s in SITES if s.name == name), None)
            
            if cfg and cfg.keywords and use_settings_keywords:
                spider_keywords = cfg.keywords
            else:
                spider_keywords = req.keywords or KEYWORDS
                
            spider_env = orchestrator._build_env_overrides(req, spider_keywords)
            # Control-panel triggers scrape one page per board: Indeed needs a
            # stealth browser and pagination would multiply the Cloudflare wait.
            spider_env["MAX_PAGES"] = "1"
            if include_onsite:
                # Keep onsite/hybrid/any-location jobs and remove LinkedIn's
                # remote-only query flag (f_WT=2).
                spider_env["INCLUDE_ONSITE"] = "true"
                spider_env["LINKEDIN_F_WT"] = ""
            async with semaphore:
                return await orchestrator.spider_runner.run(name, spider_env)

        spider_tasks = [run_spider(name) for name in spiders_to_run]
        task_results = await asyncio.gather(*spider_tasks, return_exceptions=True)
        
        results: dict[str, list[dict[str, Any]]] = {}
        for idx, spider_name in enumerate(spiders_to_run):
            result = task_results[idx]
            if isinstance(result, Exception):
                logger.error("Sub-aggregation spider '%s' failed: %s", spider_name, result)
                continue
            
            board_name = "linkedin" if "linkedin" in spider_name else ("indeed" if "indeed" in spider_name else spider_name)
            results.setdefault(board_name, []).extend(result)
            
        for source in results:
            results[source] = [
                job for job in results[source]
                if not is_blacklisted_company(job.get("company"))
            ]

        # Country Indeed boards no longer expose a remote filter and are mostly
        # onsite. When they yield only a handful of jobs (or none), supplement
        # with Indeed's global remote pool (www.indeed.com?l=Remote), which is
        # saved under the `indeed_remote` source and grouped by its actual
        # location ("Remote" / United States / ...).
        if (
            not include_onsite
            and job_board.lower() == "indeed"
            and len(results.get("indeed", [])) < 5
        ):
            logger.info(
                "Indeed country board returned %d job(s); adding global remote "
                "Indeed results",
                len(results.get("indeed", [])),
            )
            try:
                remote_env = orchestrator._build_env_overrides(req, INDEED_KEYWORDS)
                remote_env["MAX_PAGES"] = "1"
                remote_jobs = await orchestrator.spider_runner.run(
                    "indeed_remote", remote_env
                )
                logger.info(
                    "Global Indeed remote fallback returned %d job(s)",
                    len(remote_jobs),
                )
                results.setdefault("indeed", []).extend(remote_jobs)
            except Exception as exc:  # noqa: BLE001 - the country run still stands
                logger.error("Global Indeed remote fallback failed: %s", exc, exc_info=True)

        flat_jobs = flatten_results(results, max_results=500, sources=list(results.keys()))

        fingerprints = []
        for job in flat_jobs:
            source = job.get("source") or job.get("site") or "aggregate"
            job["_keywords"] = req.keywords
            fp = repository.fingerprint(job, source=source)
            fingerprints.append(fp)
            repository.save_job(job, source=source)

        cache_key = f"aggregate:sub:{country.lower()}:{job_board.lower()}:latest"
        cache.set_value(cache_key, json.dumps(fingerprints), 3600)
        logger.info("Background sub-aggregation for country=%s, job_board=%s completed successfully. Saved %d jobs.", country, job_board, len(flat_jobs))
    except Exception as e:
        logger.error("Error in background sub-aggregation task: %s", e, exc_info=True)


@router.post(
    "/aggregate/sub",
    summary="Trigger Background Sub-Aggregation Process",
    description="Initiates background tasks to scrape jobs from specific spiders matching target country and job board, saving results in the database.",
)
async def search_sub_aggregate(
    req: SubAggregateRequest,
    background_tasks: BackgroundTasks,
    orchestrator: JobOrchestrator = Depends(get_orchestrator),
    cache: DeduplicationCache = Depends(get_cache),
    repository: JobRepository = Depends(get_job_repository),
) -> dict[str, str]:
    logger.info("Initiating background job sub-aggregation task for country=%s, job_board=%s", req.country, req.job_board)
    background_tasks.add_task(
        run_sub_aggregation,
        country=req.country,
        job_board=req.job_board,
        orchestrator=orchestrator,
        cache=cache,
        repository=repository,
        include_onsite=req.include_onsite,
    )
    return {"status": "initiated", "message": f"Sub-aggregation process started in the background for {req.job_board} in {req.country}."}


@router.get(
    "/countries",
    response_model=CountriesResponse,
    summary="Get Supported Countries and Job Boards",
    description="Returns a dictionary of supported countries, their display names, available job boards, and the specific spiders associated with them.",
)
async def get_supported_countries() -> CountriesResponse:
    # List of base country slugs/names mapped to display names
    country_list = [
        ("egypt", "Egypt"),
        ("saudi arabia", "Saudi Arabia"),
        ("united arab emirates", "United Arab Emirates"),
        ("germany", "Germany"),
        ("united kingdom", "United Kingdom"),
        ("poland", "Poland"),
        ("spain", "Spain"),
        ("canada", "Canada"),
        ("qatar", "Qatar"),
        ("kuwait", "Kuwait"),
        ("bahrain", "Bahrain"),
        ("oman", "Oman"),
        ("jordan", "Jordan"),
    ]
    job_boards = ["linkedin", "indeed"]
    
    country_info_dict = {}
    for slug, display_name in country_list:
        matched_boards = []
        matched_spiders = []
        for jb in job_boards:
            spiders = find_matching_spiders(slug, jb)
            if spiders:
                matched_boards.append(jb)
                matched_spiders.extend(spiders)
        
        country_info_dict[slug] = CountryInfo(
            name=display_name,
            job_boards=matched_boards,
            spiders=matched_spiders
        )
        
    return CountriesResponse(countries=country_info_dict)


# ─── Social hiring posts (manual scans, 2-3 per day) ─────────────────────────


def _serialize_hiring_post(row: dict) -> HiringPost:
    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def _round(value: Any) -> float | None:
        return round(float(value), 2) if value is not None else None

    keywords_value = row.get("keywords_matched") or ""
    if isinstance(keywords_value, str):
        keywords = [k for k in keywords_value.split(",") if k]
    else:
        keywords = list(keywords_value)

    reasons_value = row.get("score_reasons") or ""
    reasons = [r for r in str(reasons_value).split(" | ") if r]
    return HiringPost(
        id=row.get("fingerprint") or str(row.get("id", "")),
        platform=row.get("platform", ""),
        author=row.get("author") or "",
        author_url=row.get("author_url"),
        text=row.get("text") or "",
        post_url=row.get("post_url") or "",
        posted_at=_iso(row.get("posted_at")),
        keywords_matched=keywords,
        scraped_at=_iso(row.get("scraped_at")),
        score=_round(row.get("score")),
        relevance=_round(row.get("relevance")),
        authenticity=_round(row.get("authenticity")),
        verdict=row.get("verdict"),
        reasons=reasons,
    )


def run_social_scan(req: SocialScanRequest) -> None:
    """Background worker for a manual social scan."""
    from services.social import collect_social_posts

    logger.info("Starting manual social scan for platforms=%s", req.platforms)
    try:
        summary = collect_social_posts(
            keywords=req.keywords,
            platforms=req.platforms,
            max_posts=req.max_posts,
            location=req.location,
            countries=req.countries,
            strict_region=req.strict_region,
        )
        logger.info("Manual social scan finished: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.error("Manual social scan crashed: %s", exc, exc_info=True)


@router.post(
    "/social/run",
    response_model=SocialScanResponse,
    summary="Trigger a manual hiring-post scan (LinkedIn / X / Reddit)",
    description=(
        "Starts a background scan of social hiring posts. Intended to be triggered "
        "from the frontend a few times per day — it is not part of the hourly scheduler."
    ),
)
async def scan_social_posts(
    req: SocialScanRequest,
    background_tasks: BackgroundTasks,
) -> SocialScanResponse:
    from config.settings import SOCIAL_ENABLED
    from services.social import run_state
    from services.social.session import any_session_running

    if not SOCIAL_ENABLED:
        return SocialScanResponse(
            status="error",
            message="Social scanning is disabled. Set SOCIAL_ENABLED=true in backend/.env.",
        )
    state = run_state()
    if state.get("running"):
        return SocialScanResponse(
            status="already_running",
            message="A social scan is already running. Wait for it to finish.",
        )
    if any_session_running():
        return SocialScanResponse(
            status="error",
            message=(
                "A login browser window is open. Finish the login/security check and "
                "close the window before starting a scan."
            ),
        )

    background_tasks.add_task(run_social_scan, req)
    return SocialScanResponse(
        status="initiated",
        message=(
            f"Scanning {', '.join(req.platforms)} for hiring posts from the last 24 hours. "
            "This can take a minute — refresh the hiring-post results shortly."
        ),
    )


@router.post(
    "/social/session/open",
    response_model=SocialSessionResponse,
    summary="Open a headed browser to log in / clear security checks",
    description=(
        "Launches a visible Chromium window with the saved Playwright profile for a "
        "platform. Use it to re-login or complete a CAPTCHA/2FA, then close the window; "
        "the persisted session is reused by the next scan."
    ),
)
async def open_social_session(req: SocialSessionRequest) -> SocialSessionResponse:
    from config.settings import SOCIAL_ENABLED
    from services.social.session import open_session

    if not SOCIAL_ENABLED:
        return SocialSessionResponse(
            status="error",
            platform=req.platform,
            message="Social scanning is disabled. Set SOCIAL_ENABLED=true in backend/.env.",
        )

    try:
        result = open_session(req.platform, req.url)
    except ValueError as exc:
        return SocialSessionResponse(
            status="error", platform=req.platform, message=str(exc)
        )

    return SocialSessionResponse(
        status=result.get("status", "opened"),
        platform=result.get("platform", req.platform),
        message=result.get("message", "Browser window opened."),
    )


@router.get(
    "/social",
    response_model=HiringPostsResponse,
    summary="List ranked social hiring posts",
    description="Returns hiring posts from the last 24 hours, ranked by relevance and authenticity.",
)
async def list_social_posts(
    platform: str = "all",
    keywords: str | None = None,
    min_score: float | None = None,
    posted_hours: int = 24,
    limit: int = 50,
    offset: int = 0,
    remote_only: bool = True,
    repository: JobRepository = Depends(get_job_repository),
) -> HiringPostsResponse:
    keyword_list = [k.strip() for k in (keywords or "").split(",") if k.strip()] or None
    posted_hours = max(1, min(posted_hours, 24))
    rows, total = repository.search_hiring_posts(
        platform=platform,
        keywords=keyword_list,
        min_score=min_score,
        posted_hours=posted_hours,
        limit=limit,
        offset=offset,
        remote_only=remote_only,
    )
    return HiringPostsResponse(
        total=total,
        limit=limit,
        offset=offset,
        posted_hours=posted_hours,
        posts=[_serialize_hiring_post(row) for row in rows],
    )


@router.get(
    "/social/status",
    response_model=SocialStatusResponse,
    summary="Social scan capability & state",
    description="Reports whether LinkedIn/X/Reddit credentials and sessions are available, plus the last scan result.",
)
async def social_status() -> SocialStatusResponse:
    from services.social import platform_status
    from services.social.session import session_state

    status = platform_status()
    return SocialStatusResponse(
        allowed=bool(status.get("enabled")),
        platforms={
            name: value
            for name, value in status.items()
            if name not in {"enabled", "state"} and isinstance(value, dict)
        },
        sessions=session_state(),
        state=status.get("state", {}),
    )
