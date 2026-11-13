"""Application orchestrator for spider and Google searches."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from models.job import SearchRequest
from services.filters import is_blacklisted_company
from services.google_search import GoogleJobSearchService
from services.spider_runner import SpiderRunner
from config.settings import (
    SITES,
    KEYWORDS,
    INDEED_KEYWORDS,
    DEFAULT_MAX_CONCURRENT_SPIDERS,
    DEFAULT_INDEED_LIMIT,
    DEFAULT_MAX_PAGES,
)

logger = logging.getLogger("job_aggregator.services.orchestrator")


class JobOrchestrator:
    """Coordinates custom spiders and Google dork searches."""

    def __init__(
        self,
        spider_runner: SpiderRunner | None = None,
        google_search_service: GoogleJobSearchService | None = None,
        max_concurrent_spiders: int = DEFAULT_MAX_CONCURRENT_SPIDERS,
    ) -> None:
        if spider_runner is None:
            from dependencies import get_spider_runner
            spider_runner = get_spider_runner()
        if google_search_service is None:
            from dependencies import get_google_job_search_service
            google_search_service = get_google_job_search_service()

        self.spider_runner = spider_runner
        self.google_search_service = google_search_service
        self.max_concurrent_spiders = max_concurrent_spiders

    async def orchestrate(self, req: SearchRequest) -> dict[str, list[dict[str, Any]]]:
        keywords = req.keywords or KEYWORDS
        

        is_remote = self._is_remote(req)
        location = self._location(req, is_remote)
        primary_country = req.countries[0].title() if req.countries else "Egypt"

        base_env_overrides = self._build_env_overrides(req, keywords)
        spiders_to_run = self._select_spiders(
            is_remote,
            primary_country,
            location,
            base_env_overrides,
            countries=req.countries,
        )
        logger.info("Determined spiders to execute: %s", spiders_to_run)

        semaphore = asyncio.Semaphore(self.max_concurrent_spiders)

        async def run_spider(name: str) -> list[dict[str, Any]]:
            # Find spider config to check for site-specific keywords in settings
            cfg = next((s for s in SITES if s.name == name), None)
            
            # Use request keywords if user specified them; otherwise fall back to settings keywords if defined
            # If not defined in settings, use the fallback keywords.
            if req.keywords:
                spider_keywords = req.keywords
            elif cfg and cfg.keywords:
                spider_keywords = cfg.keywords
            else:
                spider_keywords = keywords
                
            spider_env = self._build_env_overrides(req, spider_keywords)
            # Propagate any other settings configured during selection
            for k, v in base_env_overrides.items():
                if k not in spider_env:
                    spider_env[k] = v
                    
            async with semaphore:
                return await self.spider_runner.run(name, spider_env)

        spider_tasks = [run_spider(name) for name in spiders_to_run]
        google_task = self.google_search_service.search_jobs(
            keywords=keywords,
            sites=req.job_sites,
            location="remote",
            max_results=req.max_results,
            exclude_major_boards=True,
        )

        task_results = await asyncio.gather(*spider_tasks, google_task, return_exceptions=True)
        results: dict[str, list[dict[str, Any]]] = {"linkedin": [], "indeed": [], "google": []}

        google_result = task_results[-1]
        if isinstance(google_result, Exception):
            logger.error("Google search failed: %s", google_result)
        else:
            results["google"] = google_result

        for idx, spider_name in enumerate(spiders_to_run):
            result = task_results[idx]
            if isinstance(result, Exception):
                logger.error("Spider '%s' failed: %s", spider_name, result)
                continue
            if "linkedin" in spider_name:
                results["linkedin"].extend(result)
            elif "indeed" in spider_name:
                results["indeed"].extend(result)
            else:
                results.setdefault(spider_name, []).extend(result)

        for source in results:
            results[source] = [
                job for job in results[source]
                if not is_blacklisted_company(job.get("company"))
            ]

        return results

    def _is_remote(self, req: SearchRequest) -> bool:
        if req.work_type == "remote":
            return True
        if req.work_type == "onsite":
            return False
        return (req.location == "remote") if req.location else True

    def _location(self, req: SearchRequest, is_remote: bool) -> str:
        if is_remote and (not req.location or req.location == "remote"):
            return "remote"
        return req.location or "Cairo"

    def _build_env_overrides(self, req: SearchRequest, keywords: list[str]) -> dict[str, str]:
        search_term = " OR ".join([f'"{keyword}"' if " " in keyword else keyword for keyword in keywords])
        # Indeed's broad OR matching turns bare terms like "Engineer" into
        # civil/mechanical/teaching results, so use the focused tech list unless
        # the caller supplied explicit keywords. Quoted phrases and long OR
        # chains (10+ terms) return an empty page on Indeed, so keep the query
        # unquoted and capped at 4 terms.
        indeed_keywords = keywords if keywords != KEYWORDS else INDEED_KEYWORDS
        indeed_keywords = [str(kw).strip() for kw in indeed_keywords if str(kw).strip()][:4]
        indeed_search_term = " OR ".join(indeed_keywords)
        return {
            "LINKEDIN_KEYWORDS": search_term,
            # Always restrict LinkedIn to the last 24 hours and remote jobs.
            "LINKEDIN_TPR": "r86400",
            "LINKEDIN_F_WT": "2",
            "INDEED_QUERY": indeed_search_term,
            # Indeed: 1 = last 24 hours. The old DSQF7 remote attribute now
            # returns "No Result" on every country board, so remote intent is
            # enforced by the shared text filter instead.
            "INDEED_FROMAGE": "1",
            "INDEED_SC": "",
            "INDEED_LIMIT": str(DEFAULT_INDEED_LIMIT),
            "MAX_PAGES": str(DEFAULT_MAX_PAGES),
        }

    def _country_spiders(self, country_input: str, location: str) -> list[str]:
        """Return the regional LinkedIn/Indeed spiders for one country."""
        country = (country_input or "").lower().strip()
        location_lower = (location or "").lower()

        if "egypt" in country or "cairo" in location_lower or country in {"eg", "مصر"}:
            return ["linkedin_eg", "indeed_eg"]
        if "saudi" in country or country in {"sa", "ksa", "السعودية"}:
            return ["linkedin_sa", "indeed_sa"]
        if "emirates" in country or country in {"ae", "uae", "dubai", "الإمارات"}:
            return ["linkedin_ae", "indeed_ae"]
        if "germany" in country or country == "de":
            return ["linkedin_germany", "indeed_germany"]
        if "united kingdom" in country or country in {"uk", "gb"} or "london" in location_lower:
            return ["linkedin_uk", "indeed_uk"]
        if "poland" in country or country == "pl":
            return ["linkedin_poland"]
        if "spain" in country or "barcelona" in location_lower or country == "es":
            return ["linkedin_spain", "linkedin_barcelona"]
        if "canada" in country or country == "ca":
            return ["linkedin_canada"]
        if "qatar" in country or "doha" in location_lower or country in {"qa", "قطر"}:
            return ["linkedin_qatar", "indeed_qa"]
        if "kuwait" in country or country in {"kw", "الكويت"}:
            return ["linkedin_kuwait", "indeed_kw"]
        if "bahrain" in country or country in {"bh", "البحرين"}:
            return ["linkedin_bahrain", "indeed_bh"]
        if "oman" in country or "muscat" in location_lower or country in {"om", "عمان"}:
            return ["linkedin_oman", "indeed_om"]
        if "jordan" in country or "amman" in location_lower or country in {"jo", "الأردن"}:
            return ["linkedin_jordan", "indeed_jo"]
        if any(token in country for token in ("middle east", "mena", "gulf", "gcc", "arab")):
            return [
                "linkedin_sa", "linkedin_ae", "linkedin_eg", "linkedin_qatar",
                "linkedin_kuwait", "linkedin_bahrain", "linkedin_oman", "linkedin_jordan",
                "indeed_sa", "indeed_ae", "indeed_eg", "indeed_qa",
                "indeed_kw", "indeed_bh", "indeed_om", "indeed_jo",
            ]
        return []

    def _select_spiders(
        self,
        is_remote: bool,
        primary_country: str,
        location: str,
        env_overrides: dict[str, str],
        countries: list[str] | None = None,
    ) -> list[str]:
        enabled_names = {site.name for site in SITES if site.enabled}
        global_remote_boards = {
            "remoteok", "weworkremotely", "jobicy", "remotive", "himalayas", "trueup",
            "indeed_remote",
        }

        if is_remote:
            # Run global remote boards + only the region-specific spiders for the
            # requested countries (instead of every regional spider).
            selected: list[str] = [
                name for name in global_remote_boards if name in enabled_names
            ]
            for country in (countries or [primary_country]):
                selected.extend(self._country_spiders(country, location))

            if not any("linkedin" in name or "indeed" in name for name in selected):
                selected.extend(name for name in enabled_names if name not in global_remote_boards)

            deduped: list[str] = []
            for name in selected:
                if name in enabled_names and name not in deduped:
                    deduped.append(name)
            return deduped

        selected = self._country_spiders(primary_country, location)
        if not selected:
            env_overrides["LINKEDIN_LOCATION"] = location
            env_overrides["INDEED_LOCATION"] = location
            selected = ["linkedin", "indeed"]

        return [name for name in selected if name in enabled_names]

