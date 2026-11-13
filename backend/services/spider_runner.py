"""Service responsible for running configured spiders and reading their results."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from repository.jobs import JobRepository
from config.settings import DEFAULT_RECENT_HOURS

logger = logging.getLogger("job_aggregator.services.spider_runner")


class SpiderRunner:
    """Runs a named spider in an executor thread."""

    def __init__(self, repository: JobRepository, recent_hours: int = DEFAULT_RECENT_HOURS) -> None:
        self.repository = repository
        self.recent_hours = recent_hours

    async def run(self, spider_name: str, env_overrides: dict[str, str]) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run_sync, spider_name, env_overrides)

    def _run_sync(self, spider_name: str, env_overrides: dict[str, str]) -> list[dict[str, Any]]:
        old_env = os.environ.copy()
        try:
            for key, value in env_overrides.items():
                os.environ[key] = str(value)

            from config.settings import SITES
            from scheduler.runner import run_spider
            from storage.db import init_db

            init_db()
            cfg = next((site for site in SITES if site.name == spider_name), None)
            if cfg is None:
                logger.error("No SiteConfig found for spider '%s'", spider_name)
                return []

            cfg.enabled = True
            if "indeed" in spider_name or "linkedin" in spider_name:
                pages = int(env_overrides.get("MAX_PAGES", "0"))
                # Indeed goes through a stealth browser + Cloudflare, so extra
                # pages cost minutes; one page per run is enough for a 24h feed.
                if "indeed" in spider_name and pages > 1:
                    pages = 1
                cfg.max_pages = pages

            logger.info("Executing spider '%s'", spider_name)
            summary = run_spider(cfg)
            if summary.get("status") == "failed":
                raise RuntimeError(
                    f"Spider '{spider_name}' failed: {summary.get('error', 'unknown error')}"
                )

            results = [
                self._normalize_job(row, spider_name)
                for row in self.repository.recent_jobs(hours=self.recent_hours, source=spider_name)
            ]
            logger.info("Spider '%s' finished with %d recent jobs", spider_name, len(results))
            return results
        except Exception as exc:
            logger.error("Failed running spider '%s': %s", spider_name, exc, exc_info=True)
            raise
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def _normalize_job(self, row: dict[str, Any], spider_name: str) -> dict[str, Any]:
        scraped_at = row.get("scraped_at")
        if isinstance(scraped_at, datetime):
            scraped_at_value = scraped_at.isoformat()
        else:
            scraped_at_value = str(scraped_at or "")

        posted_at = row.get("posted_at")
        posted_at_value = (
            posted_at.isoformat()
            if isinstance(posted_at, datetime)
            else (str(posted_at) if posted_at else scraped_at_value)
        )

        tags = row.get("tags") or ""
        return {
            "title": row.get("title") or "",
            "company": row.get("company") or "",
            "location": row.get("location") or "",
            "url": row.get("url") or "",
            "job_url": row.get("url") or "",
            "description": row.get("description") or "",
            "tags": tags.split(",") if isinstance(tags, str) and tags else [],
            "salary": row.get("salary") or "",
            "source": row.get("source") or spider_name,
            "scraped_at": scraped_at_value,
            "posted_at": posted_at_value,
            "date_posted": posted_at_value,
            "score": row.get("score"),
            "relevance": row.get("relevance"),
            "authenticity": row.get("authenticity"),
            "verdict": row.get("verdict"),
            "reasons": [r for r in str(row.get("score_reasons") or "").split(" | ") if r],
            "site": "linkedin" if "linkedin" in spider_name else ("indeed" if "indeed" in spider_name else spider_name),
        }
