"""Backfill founder avatars for rows crawled before avatar support existed.

Re-reads each company page, extracts the (signed) founder avatar URLs from the
Inertia payload, converts them to stable public URLs, and updates the matching
founder rows. Safe to re-run.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from config.settings import YC_SITE_BASE
from repository.yc import YCRepository
from services.yc.crawler import inertia_props
from services.yc.fetcher import fetch
from services.yc.media import public_avatar_url

logger = logging.getLogger("job_aggregator.services.yc.avatars")

_STATE: dict[str, Any] = {"running": False, "done": 0, "total": 0, "updated": 0, "errors": 0}


def avatar_state() -> dict[str, Any]:
    return dict(_STATE)


def backfill_avatars(
    max_companies: int = 0,
    delay: float | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Populate ``yc_founders.avatar_url`` from company pages."""
    import services.yc.fetcher as fetcher_module

    if delay is not None:
        fetcher_module.YC_REQUEST_DELAY = max(0.0, delay)

    repository = YCRepository()
    repository.init_schema()

    companies, total = repository.list_companies(limit=5000)
    targets = companies[:max_companies] if max_companies else companies

    _STATE.update(running=True, done=0, total=len(targets), updated=0, errors=0)
    started = time.monotonic()

    for index, company in enumerate(targets, start=1):
        if stop_event is not None and stop_event.is_set():
            break
        slug = company.get("slug")
        if not slug:
            continue
        try:
            response = fetch(f"{YC_SITE_BASE}/companies/{slug}")
            props = inertia_props(response)
            entries = (props.get("company") or {}).get("founders") or []
            avatars: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = (entry.get("full_name") or "").strip()
                avatar = public_avatar_url(entry.get("avatar_thumb_url"))
                if name and avatar:
                    avatars[name] = avatar

            if avatars:
                founders, _ = repository.list_founders(company_slug=slug, limit=1000)
                for founder in founders:
                    avatar = avatars.get(founder.get("name") or "")
                    if avatar and avatar != founder.get("avatar_url"):
                        repository.update_founder_avatar(int(founder["id"]), avatar)
                        _STATE["updated"] = int(_STATE["updated"]) + 1
        except Exception as exc:  # noqa: BLE001 - continue with other companies
            logger.debug("Avatar backfill failed for %s: %s", slug, exc)
            _STATE["errors"] = int(_STATE["errors"]) + 1

        _STATE["done"] = index
        if index % 25 == 0:
            logger.info(
                "Avatar backfill %d/%d companies, %d avatars updated",
                index,
                len(targets),
                _STATE["updated"],
            )

    _STATE["running"] = False
    summary = {
        "status": "completed",
        "companies": _STATE["done"],
        "total": len(targets),
        "updated": _STATE["updated"],
        "errors": _STATE["errors"],
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "database_total": total,
    }
    logger.info("Avatar backfill finished: %s", summary)
    return summary
