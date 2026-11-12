"""FastAPI application factory for the job aggregation backend."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

# Load backend/.env explicitly so the app also works when started from the
# repository root (e.g. `uvicorn backend.app:app`).
load_dotenv(backend_dir / ".env")

# Configure logging before importing dependencies so their startup messages
# (Redis connection status, missing API keys) are visible.
logging.basicConfig(level=logging.INFO)

from dependencies import get_job_repository, get_yc_repository
from routes.cache import router as cache_router
from routes.health import router as health_router
from routes.jobs import router as jobs_router
from routes.queries import router as queries_router
from routes.search import router as search_router
from routes.yc import router as yc_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Job Board Scraping & Aggregation Engine",
        description=(
            "A unified high-performance job board scraping and aggregation API. "
            "Integrates parallel Playwright scrapers (LinkedIn, Indeed) and Google API Search dorks. "
            "Includes 1-hour database cache caching, URL deduplication, custom query dorking, "
            "and health indicators."
        ),
        version="4.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(queries_router)
    app.include_router(cache_router)
    app.include_router(jobs_router)
    app.include_router(yc_router)

    @app.on_event("startup")
    async def startup() -> None:
        repository = get_job_repository()
        repository.init_schema()
        try:
            yc_repository = get_yc_repository()
            yc_repository.init_schema()
            # A crawl thread cannot survive a process restart; clear any
            # persisted "running" flag left behind by a killed process.
            persisted = yc_repository.load_pipeline_state()
            if persisted and persisted.get("running"):
                from datetime import datetime, timezone

                persisted.update(
                    running=False,
                    stopping=False,
                    stage="stopped",
                    current_company=None,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                yc_repository.save_pipeline_state(persisted)
        except Exception as exc:  # never block startup on the YC pipeline
            logging.getLogger("job_aggregator.app").warning("YC schema init skipped: %s", exc)
        try:
            repository.backfill_scores()
        except Exception as exc:  # never block startup on score backfill
            logging.getLogger("job_aggregator.app").warning("Score backfill skipped: %s", exc)

    return app


app = create_app()
