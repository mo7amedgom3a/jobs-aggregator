"""Orchestrates the manually-triggered social hiring-post scans."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from config.settings import (
    LINKEDIN_EMAIL,
    LINKEDIN_PASSWORD,
    POSTED_HOURS,
    REMOTE_ONLY,
    SOCIAL_ENABLED,
    SOCIAL_MAX_POSTS_PER_PLATFORM,
    X_PASSWORD,
    X_USERNAME,
)
from repository.jobs import JobRepository
from services.filters import (
    TECH_ROLE_PATTERN,
    detect_hiring_phrases,
    is_remote_text,
    is_within_window,
)
from services.scoring import score_hiring_post
from services.social.browser import has_saved_profile
from services.social.linkedin_posts import collect_linkedin_posts
from services.social.x_posts import collect_x_posts

logger = logging.getLogger("job_aggregator.services.social.collector")

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "running": False,
    "platforms": [],
    "started_at": None,
    "finished_at": None,
    "last_result": None,
}

COLLECTORS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "linkedin": collect_linkedin_posts,
    "x": collect_x_posts,
}


def platform_status() -> dict[str, Any]:
    return {
        "enabled": SOCIAL_ENABLED,
        "linkedin": {
            "credentials": bool(LINKEDIN_EMAIL and LINKEDIN_PASSWORD),
            "saved_session": has_saved_profile("linkedin"),
        },
        "x": {
            "credentials": bool(X_USERNAME and X_PASSWORD),
            "saved_session": has_saved_profile("x"),
        },
        "state": run_state(),
    }


def run_state() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def _set_state(**kwargs: Any) -> None:
    with _LOCK:
        _STATE.update(kwargs)


def collect_social_posts(
    keywords: list[str],
    platforms: list[str] | None = None,
    max_posts: int | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Scrape, filter, score, and persist hiring posts from social platforms."""
    selected = [p.lower() for p in (platforms or ["linkedin", "x"]) if p]
    selected = [p for p in selected if p in COLLECTORS]
    if not selected:
        selected = list(COLLECTORS)

    limit = max_posts or SOCIAL_MAX_POSTS_PER_PLATFORM
    summary: dict[str, Any] = {
        "platforms": {},
        "errors": {},
        "saved": 0,
        "seen": 0,
        "skipped": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _set_state(
        running=True,
        platforms=selected,
        started_at=summary["started_at"],
        finished_at=None,
        last_result=None,
    )

    repository = JobRepository()
    try:
        repository.init_schema()
    except Exception as exc:  # schema already handled at app startup
        logger.warning("Social collector could not init schema: %s", exc)

    now = datetime.now(timezone.utc)
    for platform in selected:
        collector = COLLECTORS[platform]
        try:
            if platform == "linkedin":
                raw_posts = collector(keywords, max_posts=limit, location=location)
            else:
                raw_posts = collector(keywords, max_posts=limit)
        except Exception as exc:  # noqa: BLE001 - surface every failure to the UI
            logger.error("Social collector '%s' failed: %s", platform, exc, exc_info=True)
            summary["errors"][platform] = str(exc)
            summary["platforms"][platform] = {"fetched": 0, "saved": 0, "skipped": 0}
            continue

        summary["seen"] += len(raw_posts)
        platform_stats = {"fetched": len(raw_posts), "saved": 0, "skipped": 0}

        for post in raw_posts:
            text = post.get("text") or ""
            if len(text.strip()) < 20:
                platform_stats["skipped"] += 1
                continue

            phrases = detect_hiring_phrases(text)
            if not phrases:
                platform_stats["skipped"] += 1
                continue

            # Keep only tech-role posts; "hiring manager" mentions are not job ads.
            if not TECH_ROLE_PATTERN.search(text):
                platform_stats["skipped"] += 1
                continue
            if phrases == ["hiring"] and "hiring manager" in text.lower():
                platform_stats["skipped"] += 1
                continue

            # Remote-only policy: skip posts that are hybrid/onsite or not remote.
            if REMOTE_ONLY and not is_remote_text(text):
                platform_stats["skipped"] += 1
                continue

            if not is_within_window(post.get("posted_at"), hours=POSTED_HOURS, strict=True, now=now):
                platform_stats["skipped"] += 1
                continue

            matched_keywords = [
                kw for kw in keywords if kw and kw.lower() in text.lower()
            ]
            post["keywords_matched"] = list(dict.fromkeys(phrases + matched_keywords))
            post["_breakdown"] = score_hiring_post(post, keywords=keywords, now=now)
            post["_keywords"] = keywords

            try:
                was_new, _ = repository.save_hiring_post(post)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to save hiring post: %s", exc)
                platform_stats["skipped"] += 1
                continue

            if was_new:
                platform_stats["saved"] += 1
                summary["saved"] += 1
            else:
                platform_stats["skipped"] += 1

        summary["skipped"] += platform_stats["skipped"]
        summary["platforms"][platform] = platform_stats
        logger.info(
            "Social collector '%s': fetched=%d saved=%d skipped=%d",
            platform,
            platform_stats["fetched"],
            platform_stats["saved"],
            platform_stats["skipped"],
        )

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    _set_state(
        running=False,
        finished_at=summary["finished_at"],
        last_result=summary,
    )
    return summary
