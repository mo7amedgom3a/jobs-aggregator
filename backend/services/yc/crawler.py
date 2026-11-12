"""Orchestrates the manually-triggered YC founder sourcing pipeline.

Flow per batch:
    YC directory API → companies → company page (Inertia props: company,
    founders, job postings, launches) → optional founder pages for missing
    socials/bios → website email discovery.

Only the directory uses the public JSON API; everything else reads the
server-rendered HTML (which embeds the full Inertia page payload) so no YC
account is required.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlsplit

from config.settings import (
    YC_API_BASE,
    YC_BATCHES,
    YC_COMPANY_TIME_BUDGET,
    YC_DISCOVER_EMAILS,
    YC_MAX_COMPANIES_PER_BATCH,
    YC_MAX_PAGES_PER_BATCH,
    YC_SITE_BASE,
)
from repository.yc import YCRepository
from services.yc.email_finder import discover_company_email, emails_from_response, extract_emails
from services.yc.fetcher import fetch, fetch_json, response_text, text_of
from services.yc.media import public_avatar_url

logger = logging.getLogger("job_aggregator.services.yc.crawler")

_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
_STOP_EVENT = threading.Event()

_STATE: dict[str, Any] = {
    "running": False,
    "stopping": False,
    "stage": "idle",
    "batch": None,
    "batches": [],
    "companies_total": 0,
    "companies_done": 0,
    "companies_skipped": 0,
    "founders_found": 0,
    "jobs_found": 0,
    "emails_found": 0,
    "errors": [],
    "current_company": None,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
}


def _persisted_is_stale(state: dict[str, Any], max_age_hours: float = 8.0) -> bool:
    started = state.get("started_at")
    if not started:
        return False
    try:
        started_at = datetime.fromisoformat(str(started))
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started_at).total_seconds() > max_age_hours * 3600
    except (ValueError, TypeError):
        return False


def run_state() -> dict[str, Any]:
    with _LOCK:
        state = dict(_STATE)
        state["errors"] = list(_STATE["errors"])[-20:]
    if state.get("running") or state.get("last_result"):
        return state
    # A crawl may be running in a different API worker; read the durable copy.
    try:
        persisted = YCRepository().load_pipeline_state()
        if persisted:
            if persisted.get("running") and _persisted_is_stale(persisted):
                persisted["running"] = False
                persisted["stage"] = "stale"
            return persisted
    except Exception:  # pragma: no cover - DB may be unavailable
        pass
    return state


def _persist_state(state: dict[str, Any]) -> None:
    try:
        YCRepository().save_pipeline_state(state)
    except Exception as exc:  # pragma: no cover - never block the crawl on state writes
        logger.debug("Could not persist YC crawl state: %s", exc)


def _set_state(**kwargs: Any) -> None:
    with _LOCK:
        _STATE.update(kwargs)
        snapshot = dict(_STATE)
        snapshot["errors"] = list(_STATE["errors"])[-50:]
    _persist_state(snapshot)


def _increment(field: str, amount: int = 1) -> None:
    with _LOCK:
        _STATE[field] = int(_STATE.get(field) or 0) + amount


def _add_error(message: str) -> None:
    with _LOCK:
        errors = list(_STATE.get("errors") or [])
        errors.append(message)
        _STATE["errors"] = errors[-50:]


def request_stop() -> bool:
    """Ask the running crawl to stop after the current request/company."""
    with _LOCK:
        running = bool(_STATE.get("running"))
    if running:
        _STOP_EVENT.set()
        _set_state(stopping=True, stage="stopping")
    return running


def stop_requested() -> bool:
    return _STOP_EVENT.is_set()


# ─── Parsing helpers ─────────────────────────────────────────────────────────


def inertia_props(response: Any) -> dict[str, Any]:
    """Decode the HTML-escaped Inertia page payload embedded in the page."""
    text = response_text(response)
    match = re.search(r'data-page="([^"]+)"', text)
    if not match:
        return {}
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except (ValueError, TypeError):
        return {}
    props = payload.get("props")
    return props if isinstance(props, dict) else {}


def _kebab(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "founder"


_BATCH_SEASONS = {"W": "Winter", "P": "Spring", "S": "Summer", "F": "Fall"}


def batch_label(value: str | None) -> str | None:
    """Normalize a YC batch code (``P26``) to its display name (``Spring 2026``)."""
    if not value:
        return value
    value = value.strip()
    match = re.fullmatch(r"([WSFP])(\d{2})", value, flags=re.IGNORECASE)
    if not match:
        return value
    season = _BATCH_SEASONS[match.group(1).upper()]
    return f"{season} 20{match.group(2)}"


def _founder_links_by_name(company_response: Any) -> dict[str, str]:
    """Map founder display names to their YC ``/founders/...`` slugs."""
    mapping: dict[str, str] = {}
    try:
        anchors = company_response.css('a[href^="/founders/"]')
    except Exception:  # pragma: no cover - selector safety
        anchors = []
    for anchor in anchors:
        href = (anchor.attrib.get("href") or "").strip()
        slug = href.rsplit("/", 1)[-1]
        if not slug:
            continue
        name = " ".join(t.strip() for t in anchor.css("span::text").getall() if t.strip())
        if name and name not in mapping:
            mapping[name] = slug
    return mapping


def _founders_from_props(
    props: dict[str, Any],
    company_response: Any,
    company_slug: str,
) -> list[dict[str, Any]]:
    company = props.get("company") or {}
    raw_founders = company.get("founders") or []
    if not isinstance(raw_founders, list):
        return []

    links = _founder_links_by_name(company_response) if company_response is not None else {}
    founders: list[dict[str, Any]] = []
    for entry in raw_founders:
        if not isinstance(entry, dict):
            continue
        if entry.get("is_active") is False:
            continue
        name = (entry.get("full_name") or "").strip()
        if not name:
            continue
        slug = links.get(name) or _kebab(name)
        founders.append(
            {
                "yc_slug": slug,
                "name": name,
                "title": entry.get("title"),
                "bio": entry.get("founder_bio"),
                "profile_url": f"{YC_SITE_BASE}/founders/{slug}",
                "avatar_url": public_avatar_url(entry.get("avatar_thumb_url")),
                "x_url": (entry.get("twitter_url") or "").strip() or None,
                "x_handle": None,
                "linkedin_url": (entry.get("linkedin_url") or "").strip() or None,
                "batches": [label for label in [batch_label(company.get("batch"))] if label],
                "yc_has_email": bool(entry.get("has_email")),
            }
        )
    return founders


def _founders_from_html(company_response: Any) -> list[dict[str, Any]]:
    """Fallback for companies whose props omit founder records."""
    links = _founder_links_by_name(company_response)
    return [
        {
            "yc_slug": slug,
            "name": name,
            "title": None,
            "bio": None,
            "profile_url": f"{YC_SITE_BASE}/founders/{slug}",
            "avatar_url": None,
            "x_url": None,
            "x_handle": None,
            "linkedin_url": None,
            "batches": [],
            "yc_has_email": False,
        }
        for name, slug in links.items()
    ]


def _parse_founder_page(response: Any, slug: str, fallback_name: str) -> dict[str, Any]:
    name = text_of(response, "h1") or fallback_name or slug

    title = ""
    for candidate in response.css("p.text-gray-900::text").getall():
        cleaned = " ".join(str(candidate).split())
        if cleaned:
            title = cleaned
            break

    bio_parts = [
        " ".join(str(part).split())
        for part in response.css("div.prose p::text").getall()
        if str(part).strip()
    ]
    bio = "\n\n".join(dict.fromkeys(bio_parts))

    x_url = ""
    for href in response.css('a[href*="twitter.com"]::attr(href)').getall() + response.css(
        'a[href*="x.com"]::attr(href)'
    ).getall():
        href = href.strip()
        if not href or any(skip in href for skip in ("ycombinator", "/intent/", "/share", "/home")):
            continue
        host = urlsplit(href).netloc.lower().removeprefix("www.")
        if host in {"x.com", "twitter.com"}:
            x_url = href
            break

    linkedin_url = ""
    for href in response.css('a[href*="linkedin.com/in/"]::attr(href)').getall():
        linkedin_url = href.strip()
        if linkedin_url:
            break

    batches: list[str] = []
    for href in response.css('a[href*="batch="]::attr(href)').getall():
        if "batch=" not in href:
            continue
        value = href.split("batch=", 1)[1].split("&", 1)[0].replace("+", " ")
        label = batch_label(value)
        if label and label not in batches:
            batches.append(label)

    x_handle = ""
    if x_url:
        path = urlsplit(x_url).path.strip("/").split("/")[0]
        if path:
            x_handle = f"@{path}"

    try:
        personal_emails = emails_from_response(response)
    except Exception:  # pragma: no cover - best effort
        personal_emails = []

    avatar_url = None
    for src in response.css("figure img::attr(src)").getall() + response.css(
        'img[alt*="Founder of"]::attr(src)'
    ).getall():
        if src:
            avatar_url = public_avatar_url(src)
            if avatar_url:
                break

    return {
        "name": name,
        "title": title or None,
        "bio": bio or None,
        "avatar_url": avatar_url,
        "x_url": x_url or None,
        "x_handle": x_handle or None,
        "linkedin_url": linkedin_url or None,
        "batches": batches,
        "personal_email": personal_emails[0] if personal_emails else None,
    }


def _jobs_from_props(props: dict[str, Any]) -> list[dict[str, Any]]:
    postings = props.get("jobPostings") or []
    if not isinstance(postings, list):
        return []
    jobs: dict[str, dict[str, Any]] = {}
    for posting in postings:
        if not isinstance(posting, dict):
            continue
        url = (posting.get("url") or "").strip()
        job_slug = url.rsplit("/", 1)[-1] if url else str(posting.get("id") or "")
        if not job_slug or job_slug in jobs:
            continue
        jobs[job_slug] = {
            "yc_job_slug": job_slug,
            "title": (posting.get("title") or job_slug).strip(),
            "url": f"{YC_SITE_BASE}{url}" if url.startswith("/") else url or None,
            "location": posting.get("location"),
        }
    return list(jobs.values())


def _parse_jobs_html(response: Any, company_slug: str) -> list[dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    prefix = f"/companies/{company_slug}/jobs/"
    try:
        anchors = response.css(f'a[href^="{prefix}"]')
    except Exception:  # pragma: no cover - selector safety
        anchors = []
    for anchor in anchors:
        href = (anchor.attrib.get("href") or "").strip()
        if not href:
            continue
        job_slug = href.rsplit("/", 1)[-1]
        if not job_slug or job_slug in jobs:
            continue
        title = " ".join(t.strip() for t in anchor.css("::text").getall() if t.strip())
        jobs[job_slug] = {
            "yc_job_slug": job_slug,
            "title": title or job_slug,
            "url": f"{YC_SITE_BASE}{href}",
            "location": None,
        }
    return list(jobs.values())


def _launch_text(props: dict[str, Any]) -> str:
    launches = props.get("launches") or []
    if not isinstance(launches, list):
        return ""
    return "\n\n".join(
        str(launch.get("body") or "") for launch in launches if isinstance(launch, dict)
    )


# ─── Per-company crawl ───────────────────────────────────────────────────────


def _process_company(
    repository: YCRepository,
    company: dict[str, Any],
    *,
    discover_emails: bool,
) -> dict[str, int]:
    slug = company["slug"]
    counts = {"founders": 0, "jobs": 0, "emails": 0}
    company_started = time.monotonic()

    def budget_exceeded() -> bool:
        return (time.monotonic() - company_started) > YC_COMPANY_TIME_BUDGET

    company = {
        **company,
        "batch_code": company.get("batch"),
        "batch": batch_label(company.get("batch")),
    }
    company_id = repository.upsert_company(company)

    if stop_requested():
        return counts

    try:
        company_response = fetch(f"{YC_SITE_BASE}/companies/{slug}")
    except Exception as exc:  # noqa: BLE001 - keep crawling other companies
        logger.warning("Company page failed for %s: %s", slug, exc)
        _add_error(f"{slug}: company page failed ({exc})")
        company_response = None

    props = inertia_props(company_response) if company_response is not None else {}

    contact_email: str | None = None
    contact_source: str | None = None
    if discover_emails and company_response is not None and not budget_exceeded():
        try:
            contact = discover_company_email(
                company_response,
                company.get("website"),
                extra_text=_launch_text(props),
            )
            contact_email = contact.get("email")
            contact_source = contact.get("source")
            if contact_email:
                counts["emails"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("Email discovery failed for %s: %s", slug, exc)

    # Jobs: Inertia props (no extra request) with an HTML fallback when the
    # props were unavailable.
    if stop_requested():
        return counts
    jobs = _jobs_from_props(props)
    if not props and company_response is not None and not budget_exceeded():
        try:
            jobs_response = fetch(f"{YC_SITE_BASE}/companies/{slug}/jobs")
            if getattr(jobs_response, "status", None) == 200:
                jobs = _parse_jobs_html(jobs_response, slug)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Jobs page failed for %s: %s", slug, exc)
    try:
        repository.upsert_company_jobs(company_id, jobs)
        counts["jobs"] = len(jobs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jobs save failed for %s: %s", slug, exc)

    # Founders: Inertia props first, HTML anchors as fallback.
    founders = _founders_from_props(props, company_response, slug)
    if not founders and company_response is not None:
        founders = _founders_from_html(company_response)

    for founder in founders:
        if stop_requested():
            break
        needs_page = not founder.get("x_url") or not founder.get("linkedin_url") or not founder.get("bio")
        if needs_page and founder.get("yc_slug") and not budget_exceeded():
            try:
                founder_response = fetch(f"{YC_SITE_BASE}/founders/{founder['yc_slug']}")
                if getattr(founder_response, "status", None) == 200:
                    detail = _parse_founder_page(
                        founder_response, founder["yc_slug"], founder.get("name") or ""
                    )
                    founder.update(
                        {key: value for key, value in detail.items() if value and key != "personal_email"}
                    )
                    personal_email = detail.get("personal_email")
                    if personal_email:
                        founder["email"] = personal_email
                        founder["email_source"] = "founder_page"
                        founder["email_confidence"] = "verified"
                        counts["emails"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Founder page failed for %s: %s", founder.get("yc_slug"), exc)
                _add_error(f"{slug}/{founder.get('yc_slug')}: founder page failed ({exc})")

        if not founder.get("x_handle") and founder.get("x_url"):
            path = urlsplit(founder["x_url"]).path.strip("/").split("/")[0]
            founder["x_handle"] = f"@{path}" if path else None

        if not founder.get("email") and contact_email:
            founder["email"] = contact_email
            founder["email_source"] = contact_source
            founder["email_confidence"] = (
                "guessed" if contact_source == "pattern_guess" else "verified"
            )

        try:
            repository.upsert_founder(company_id, founder)
            counts["founders"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Founder upsert failed for %s: %s", founder.get("yc_slug"), exc)
            _add_error(f"{slug}/{founder.get('yc_slug')}: founder save failed ({exc})")

    try:
        repository.set_company_contact(company_id, contact_email, contact_source, counts["jobs"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Company contact save failed for %s: %s", slug, exc)

    return counts


# ─── Entry point ─────────────────────────────────────────────────────────────


def collect_yc(
    batches: list[str] | None = None,
    max_companies_per_batch: int | None = None,
    max_pages_per_batch: int | None = None,
    skip_existing: bool = False,
    discover_emails: bool | None = None,
) -> dict[str, Any]:
    """Crawl YC batches and persist companies, founders, jobs and contacts.

    Designed to be run in a background thread; callers should check
    :func:`run_state` for progress. Only one crawl can run at a time.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        return {"status": "already_running", **run_state()}

    selected_batches = batches or YC_BATCHES
    company_cap = max_companies_per_batch if max_companies_per_batch is not None else YC_MAX_COMPANIES_PER_BATCH
    page_cap = max_pages_per_batch if max_pages_per_batch is not None else YC_MAX_PAGES_PER_BATCH
    email_scan = YC_DISCOVER_EMAILS if discover_emails is None else discover_emails

    started_at = datetime.now(timezone.utc).isoformat()
    _STOP_EVENT.clear()
    _set_state(
        running=True,
        stopping=False,
        stage="starting",
        batch=None,
        batches=selected_batches,
        companies_total=0,
        companies_done=0,
        companies_skipped=0,
        founders_found=0,
        jobs_found=0,
        emails_found=0,
        errors=[],
        current_company=None,
        started_at=started_at,
        finished_at=None,
        last_result=None,
    )

    repository = YCRepository()
    try:
        repository.init_schema()
    except Exception as exc:  # noqa: BLE001
        logger.error("YC repository schema init failed: %s", exc)
        _add_error(f"schema init failed: {exc}")

    summary = {
        "batches": {},
        "companies": 0,
        "companies_skipped": 0,
        "founders": 0,
        "jobs": 0,
        "emails": 0,
        "started_at": started_at,
    }

    try:
        for batch in selected_batches:
            if stop_requested():
                break
            _set_state(stage="directory", batch=batch)
            page_url = f"{YC_API_BASE}/companies?batch={quote_plus(batch)}&page=1"
            page_number = 1
            batch_companies = 0
            batch_stats = {"companies": 0, "founders": 0, "jobs": 0, "emails": 0}

            while page_url:
                if stop_requested():
                    break
                if page_cap and page_number > page_cap:
                    break
                try:
                    data = fetch_json(page_url)
                except Exception as exc:  # noqa: BLE001
                    logger.error("YC directory page failed (%s): %s", page_url, exc)
                    _add_error(f"{batch} page {page_number}: {exc}")
                    break

                companies = data.get("companies") or []
                with _LOCK:
                    _STATE["companies_total"] = int(_STATE.get("companies_total") or 0) + len(companies)

                for company in companies:
                    if stop_requested():
                        break
                    if company_cap and batch_companies >= company_cap:
                        break
                    batch_companies += 1

                    if skip_existing and repository.company_exists(company["slug"]):
                        _increment("companies_done")
                        _increment("companies_skipped")
                        summary["companies_skipped"] += 1
                        continue

                    _set_state(stage="company", current_company=f"{company.get('name')} ({company['slug']})")
                    try:
                        counts = _process_company(
                            repository,
                            company,
                            discover_emails=email_scan,
                        )
                        batch_stats["companies"] += 1
                        batch_stats["founders"] += counts["founders"]
                        batch_stats["jobs"] += counts["jobs"]
                        batch_stats["emails"] += counts["emails"]
                        _increment("founders_found", counts["founders"])
                        _increment("jobs_found", counts["jobs"])
                        _increment("emails_found", counts["emails"])
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Company crawl failed for %s: %s", company.get("slug"), exc, exc_info=True)
                        _add_error(f"{company.get('slug')}: {exc}")
                    finally:
                        _increment("companies_done")
                        _set_state(current_company=None)

                if company_cap and batch_companies >= company_cap:
                    break

                next_page = data.get("nextPage")
                total_pages = int(data.get("totalPages") or 0)
                if not next_page or (total_pages and page_number >= total_pages):
                    break
                page_url = next_page
                page_number += 1

            summary["batches"][batch] = batch_stats
            summary["companies"] += batch_stats["companies"]
            summary["founders"] += batch_stats["founders"]
            summary["jobs"] += batch_stats["jobs"]
            summary["emails"] += batch_stats["emails"]
            logger.info("YC batch %s finished: %s", batch, batch_stats)

        stopped = stop_requested()
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["stopped"] = stopped
        _set_state(
            running=False,
            stopping=False,
            stage="stopped" if stopped else "idle",
            current_company=None,
            finished_at=summary["finished_at"],
            last_result=summary,
        )
        return {"status": "stopped" if stopped else "completed", **summary}
    except Exception as exc:  # noqa: BLE001 - surface fatal errors to the UI
        logger.error("YC crawl crashed: %s", exc, exc_info=True)
        _add_error(f"crawl crashed: {exc}")
        _set_state(
            running=False,
            stopping=False,
            stage="failed",
            current_company=None,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {"status": "failed", "error": str(exc), **summary}
    finally:
        _STOP_EVENT.clear()
        _RUN_LOCK.release()
