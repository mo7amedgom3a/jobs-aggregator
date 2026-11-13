"""PostgreSQL repository for scraped jobs and scrape runs."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator
from urllib.parse import urlsplit

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - handled at runtime when DB is used.
    psycopg = None
    dict_row = None

logger = logging.getLogger("job_aggregator.repository.jobs")


DEFAULT_DATABASE_URL = "postgresql://job_user:job_password@postgres:5432/job_automation"
from config.settings import DEFAULT_SEARCH_LIMIT, DEFAULT_SEARCH_OFFSET

#: Errors worth retrying while PostgreSQL is still starting up.
_RETRYABLE_CONNECT_ERRORS = (psycopg.OperationalError,) if psycopg is not None else ()

_UNRESOLVED_HOST_HINT = (
    "If the hostname cannot be resolved, you are probably running the backend "
    "outside Docker while DATABASE_URL still points at the compose service name. "
    "Use 127.0.0.1 with the published port (5433) from backend/.env."
)


def describe_database_url(url: str) -> str:
    """Return a log-safe ``host:port/database`` summary (never the password)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid DATABASE_URL>"
    host = parts.hostname or "<missing-host>"
    port = parts.port or 5432
    database = (parts.path or "/").lstrip("/") or "<missing-db>"
    return f"{host}:{port}/{database}"


class JobRepository:
    """Synchronous repository used by both FastAPI services and spider hooks."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    @contextmanager
    def _connect(self) -> Iterator:
        if psycopg is None:
            raise RuntimeError("psycopg is not installed. Install psycopg[binary] to use PostgreSQL.")
        with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5) as conn:
            yield conn

    def init_schema(self, attempts: int = 5, delay_seconds: float = 2.0) -> None:
        """Create the schema, retrying while PostgreSQL finishes starting up."""
        endpoint = describe_database_url(self.database_url)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jobs (
                            id BIGSERIAL PRIMARY KEY,
                            fingerprint TEXT NOT NULL UNIQUE,
                            title TEXT NOT NULL,
                            company TEXT,
                            location TEXT,
                            url TEXT NOT NULL,
                            description TEXT,
                            tags TEXT,
                            salary TEXT,
                            source TEXT NOT NULL,
                            posted_at TIMESTAMPTZ,
                            score DOUBLE PRECISION,
                            relevance DOUBLE PRECISION,
                            authenticity DOUBLE PRECISION,
                            verdict TEXT,
                            score_reasons TEXT,
                            scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );

                        -- Additive migrations for databases created before scoring.
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION;
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS relevance DOUBLE PRECISION;
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS authenticity DOUBLE PRECISION;
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS verdict TEXT;
                        ALTER TABLE jobs ADD COLUMN IF NOT EXISTS score_reasons TEXT;

                        CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs (fingerprint);
                        CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs (scraped_at);
                        CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source);
                        CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs (posted_at);
                        CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (score DESC);

                        CREATE TABLE IF NOT EXISTS scrape_runs (
                            id BIGSERIAL PRIMARY KEY,
                            source TEXT NOT NULL,
                            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            finished_at TIMESTAMPTZ,
                            items_new INTEGER DEFAULT 0,
                            items_dupe INTEGER DEFAULT 0,
                            status TEXT DEFAULT 'running'
                        );

                        CREATE TABLE IF NOT EXISTS hiring_posts (
                            id BIGSERIAL PRIMARY KEY,
                            fingerprint TEXT NOT NULL UNIQUE,
                            platform TEXT NOT NULL,
                            author TEXT,
                            author_url TEXT,
                            text TEXT,
                            post_url TEXT NOT NULL,
                            posted_at TIMESTAMPTZ,
                            keywords_matched TEXT,
                            score DOUBLE PRECISION,
                            relevance DOUBLE PRECISION,
                            authenticity DOUBLE PRECISION,
                            verdict TEXT,
                            score_reasons TEXT,
                            scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );

                        CREATE INDEX IF NOT EXISTS idx_hiring_posts_platform ON hiring_posts (platform);
                        CREATE INDEX IF NOT EXISTS idx_hiring_posts_posted_at ON hiring_posts (posted_at);
                        CREATE INDEX IF NOT EXISTS idx_hiring_posts_score ON hiring_posts (score DESC);
                        """
                    )
                logger.info("PostgreSQL schema is ready (%s).", endpoint)
                return
            except _RETRYABLE_CONNECT_ERRORS as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "PostgreSQL not reachable at %s (attempt %d/%d): %s. Retrying in %.0fs...",
                    endpoint,
                    attempt,
                    attempts,
                    exc,
                    delay_seconds,
                )
                time.sleep(delay_seconds)

        logger.error(
            "Could not connect to PostgreSQL at %s. Start it with "
            "'docker compose up -d postgres' and check DATABASE_URL in backend/.env. "
            "%s Last error: %s",
            endpoint,
            _UNRESOLVED_HOST_HINT,
            last_error,
        )
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Could not connect to PostgreSQL at {endpoint}.")

    def is_duplicate(self, fingerprint: str, dedup_window_hours: int = 24) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=dedup_window_hours)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE fingerprint = %s AND scraped_at >= %s LIMIT 1",
                (fingerprint, cutoff),
            ).fetchone()
        return row is not None

    def save_job(
        self,
        job: dict,
        source: str,
        dedup_window_hours: int = 24,
    ) -> tuple[bool, str]:
        fingerprint = self.fingerprint(job, source)

        from services.filters import is_blacklisted_title
        if is_blacklisted_title(job.get("title")):
            logger.info("Dropping non-software job: %s", job.get("title"))
            return False, fingerprint

        if self.is_duplicate(fingerprint, dedup_window_hours=dedup_window_hours):
            return False, fingerprint

        tags = job.get("tags", [])
        tags_value = ",".join(tags) if isinstance(tags, list) else str(tags or "")

        # Score the job once at ingestion time so ranking survives in the DB.
        from services.filters import parse_posted_at
        from services.scoring import score_job

        posted_at = parse_posted_at(job.get("posted_at") or job.get("date_posted"))
        breakdown = score_job(job, keywords=job.get("_keywords"))

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO jobs
                    (fingerprint, title, company, location, url, description, tags, salary, source,
                     posted_at, score, relevance, authenticity, verdict, score_reasons)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    fingerprint,
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("url", ""),
                    job.get("description", ""),
                    tags_value,
                    job.get("salary", ""),
                    source,
                    posted_at,
                    breakdown.score,
                    breakdown.relevance,
                    breakdown.authenticity,
                    breakdown.verdict,
                    " | ".join(breakdown.reasons),
                ),
            ).fetchone()
        return row is not None, fingerprint

    def start_run(self, source: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO scrape_runs (source) VALUES (%s) RETURNING id",
                (source,),
            ).fetchone()
        return int(row["id"])

    def finish_run(
        self,
        run_id: int,
        items_new: int,
        items_dupe: int,
        status: str = "completed",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scrape_runs
                   SET finished_at = NOW(), items_new = %s, items_dupe = %s, status = %s
                 WHERE id = %s
                """,
                (items_new, items_dupe, status, run_id),
            )

    def recent_jobs(self, hours: int = 24, source: str | None = None) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        params: list[object] = [cutoff]
        query = "SELECT * FROM jobs WHERE COALESCE(posted_at, scraped_at) >= %s"
        if source:
            query += " AND source = %s"
            params.append(source)
        query += " ORDER BY COALESCE(posted_at, scraped_at) DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_jobs_by_fingerprints(self, fingerprints: list[str]) -> list[dict]:
        if not fingerprints:
            return []
        placeholders = ", ".join(["%s"] * len(fingerprints))
        query = f"SELECT * FROM jobs WHERE fingerprint IN ({placeholders})"
        with self._connect() as conn:
            rows = conn.execute(query, fingerprints).fetchall()
        return [dict(row) for row in rows]

    def delete_old_jobs(
        self,
        days: int | None = None,
        hours: int | None = None,
        minutes: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        truncate: bool = False,
    ) -> list[dict]:
        """Deletes jobs based on relative age, date range, or truncates the table."""
        if truncate:
            query = "DELETE FROM jobs RETURNING *"
            params = ()
        elif start_date is not None or end_date is not None:
            clauses = []
            params_list = []
            if start_date is not None:
                clauses.append("scraped_at >= %s")
                params_list.append(start_date)
            if end_date is not None:
                clauses.append("scraped_at <= %s")
                params_list.append(end_date)
            query = f"DELETE FROM jobs WHERE {' AND '.join(clauses)} RETURNING *"
            params = tuple(params_list)
        else:
            # Default fallback to 2 days if no options are specified
            if days is None and hours is None and minutes is None:
                days = 2
            
            delta = timedelta(
                days=days or 0,
                hours=hours or 0,
                minutes=minutes or 0,
            )
            cutoff = datetime.now(timezone.utc) - delta
            query = "DELETE FROM jobs WHERE scraped_at < %s RETURNING *"
            params = (cutoff,)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def search_jobs(
        self,
        keywords: list[str] | None = None,
        countries: list[str] | None = None,
        company: str | None = None,
        remote: bool | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
        offset: int = DEFAULT_SEARCH_OFFSET,
        posted_hours: int | None = 24,
        min_score: float | None = None,
        sort_by: str = "score",
    ) -> tuple[list[dict], int]:
        where_clauses = []
        params = []

        if posted_hours is not None:
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(hours=posted_hours)
            where_clauses.append("COALESCE(posted_at, scraped_at) >= %s")
            params.append(cutoff)

        if min_score is not None:
            where_clauses.append("COALESCE(score, 0) >= %s")
            params.append(float(min_score))

        if keywords:
            keyword_clauses = []
            for kw in keywords:
                if kw.strip():
                    keyword_clauses.append("(title ILIKE %s OR description ILIKE %s OR tags ILIKE %s)")
                    like_pattern = f"%{kw.strip()}%"
                    params.extend([like_pattern, like_pattern, like_pattern])
            if keyword_clauses:
                where_clauses.append("(" + " OR ".join(keyword_clauses) + ")")
        
        if countries:
            country_expansion = {
                "egypt": ["egypt", "cairo", "alexandria", "مصر", "\\_eg"],
                "eg": ["egypt", "cairo", "alexandria", "مصر", "\\_eg"],
                "saudi arabia": ["saudi", "riyadh", "jeddah", "السعودية", "\\_sa"],
                "saudi": ["saudi", "riyadh", "jeddah", "السعودية", "\\_sa"],
                "sa": ["saudi", "riyadh", "jeddah", "السعودية", "\\_sa"],
                "united arab emirates": ["uae", "dubai", "abu dhabi", "united arab emirates", "الامارات", "\\_ae", "emirates"],
                "uae": ["uae", "dubai", "abu dhabi", "united arab emirates", "الامارات", "\\_ae", "emirates"],
                "ae": ["uae", "dubai", "abu dhabi", "united arab emirates", "الامارات", "\\_ae", "emirates"],
                "emirates": ["uae", "dubai", "abu dhabi", "united arab emirates", "الامارات", "\\_ae", "emirates"],
                "emarties": ["uae", "dubai", "abu dhabi", "united arab emirates", "الامارات", "\\_ae", "emirates"],
                "germany": ["germany", "berlin", "munich", "frankfurt", "deutschland", "\\_germany"],
                "de": ["germany", "berlin", "munich", "frankfurt", "deutschland", "\\_germany"],
                "poland": ["poland", "warsaw", "krakow", "polska", "\\_poland"],
                "pl": ["poland", "warsaw", "krakow", "polska", "\\_poland"],
                "spain": ["spain", "barcelona", "madrid", "españa", "\\_spain", "\\_barcelona"],
                "es": ["spain", "barcelona", "madrid", "españa", "\\_spain", "\\_barcelona"],
                "canada": ["canada", "toronto", "vancouver", "montreal", "\\_canada"],
                "ca": ["canada", "toronto", "vancouver", "montreal", "\\_canada"],
                "united states": ["usa", "united states", "us", "new york", "san francisco", "california"],
                "usa": ["usa", "united states", "us", "new york", "san francisco", "california"],
                "us": ["usa", "united states", "us", "new york", "san francisco", "california"],
                "united kingdom": ["uk", "united kingdom", "london", "england"],
                "uk": ["uk", "united kingdom", "london", "england"],
                "qatar": ["qatar", "doha", "قطر"],
                "qa": ["qatar", "doha", "قطر"],
                "kuwait": ["kuwait", "kuwait city", "الكويت"],
                "kw": ["kuwait", "kuwait city", "الكويت"],
                "bahrain": ["bahrain", "manama", "البحرين"],
                "bh": ["bahrain", "manama", "البحرين"],
                "oman": ["oman", "muscat", "عمان"],
                "om": ["oman", "muscat", "عمان"],
                "jordan": ["jordan", "amman", "الأردن"],
                "jo": ["jordan", "amman", "الأردن"],
                "middle east": ["middle east", "mena", "gcc", "gulf", "saudi", "uae", "emirates", "egypt", "qatar", "kuwait", "bahrain", "oman", "jordan"],
                "mena": ["middle east", "mena", "gcc", "gulf", "saudi", "uae", "emirates", "egypt", "qatar", "kuwait", "bahrain", "oman", "jordan"],
            }
            country_clauses = []
            for c in countries:
                if c.strip():
                    c_key = c.lower().strip()
                    terms = country_expansion.get(c_key, [c.strip()])
                    for term in terms:
                        country_clauses.append("(location ILIKE %s OR tags ILIKE %s OR source ILIKE %s)")
                        like_pattern = f"%{term}%"
                        params.extend([like_pattern, like_pattern, like_pattern])
            if country_clauses:
                where_clauses.append("(" + " OR ".join(country_clauses) + ")")
            
        if company:
            where_clauses.append("company ILIKE %s")
            params.append(f"%{company}%")
            
        if remote is not None:
            remote_terms = [
                "remote",
                "work from home",
                "wfh",
                "anywhere",
                "worldwide",
                "telecommute",
                "remote-first",
                "home-based",
                "distributed",
            ]
            onsite_terms = [
                "hybrid",
                "on-site",
                "onsite",
                "in-office",
                "office-based",
                "in person",
                "relocation",
                "no remote",
            ]
            # Location/title/tags are the reliable fields; descriptions are noisy.
            columns = ("location", "title", "tags")

            positive_clauses = []
            for term in remote_terms:
                positive_clauses.append(
                    "(" + " OR ".join(f"{col} ILIKE %s" for col in columns) + ")"
                )
                params.extend([f"%{term}%"] * len(columns))
            positive_sql = "(" + " OR ".join(positive_clauses) + ")"

            if remote:
                negative_clauses = []
                for term in onsite_terms:
                    negative_clauses.append(
                        "(" + " OR ".join(f"{col} ILIKE %s" for col in columns) + ")"
                    )
                    params.extend([f"%{term}%"] * len(columns))
                negative_sql = "(" + " OR ".join(negative_clauses) + ")"
                where_clauses.append(f"{positive_sql} AND NOT {negative_sql}")
            else:
                where_clauses.append(f"NOT {positive_sql}")

        where_str = ""
        if where_clauses:
            where_str = " AND " + " AND ".join(where_clauses)

        # 1. Get total count
        count_query = f"SELECT COUNT(*) as count FROM jobs WHERE 1=1{where_str}"
        
        # 2. Get paginated results
        order_by = (
            "COALESCE(score, 0) DESC, COALESCE(posted_at, scraped_at) DESC"
            if sort_by == "score"
            else "COALESCE(posted_at, scraped_at) DESC, COALESCE(score, 0) DESC"
        )
        results_query = (
            f"SELECT * FROM jobs WHERE 1=1{where_str} "
            f"ORDER BY {order_by} LIMIT %s OFFSET %s"
        )
        results_params = params + [limit, offset]

        with self._connect() as conn:
            # We run count first
            count_row = conn.execute(count_query, params).fetchone()
            total_count = int(count_row["count"]) if count_row else 0
            
            rows = conn.execute(results_query, results_params).fetchall()
            jobs = [dict(row) for row in rows]
            
        return jobs, total_count

    # ── Social hiring posts ────────────────────────────────────────────────

    def backfill_scores(self, limit: int = 5000) -> int:
        """Score legacy job rows that were stored before the scoring layer existed."""
        from services.scoring import score_job

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE score IS NULL OR verdict IS NULL LIMIT %s",
                (limit,),
            ).fetchall()
            if not rows:
                return 0

            updated = 0
            for row in rows:
                job = dict(row)
                tags = job.get("tags") or ""
                if isinstance(tags, str):
                    job["tags"] = [t for t in tags.split(",") if t]
                breakdown = score_job(job)
                conn.execute(
                    """
                    UPDATE jobs
                       SET score = %s, relevance = %s, authenticity = %s,
                           verdict = %s, score_reasons = %s
                     WHERE id = %s
                    """,
                    (
                        breakdown.score,
                        breakdown.relevance,
                        breakdown.authenticity,
                        breakdown.verdict,
                        " | ".join(breakdown.reasons),
                        job["id"],
                    ),
                )
                updated += 1

        logger.info("Backfilled scores for %d legacy jobs", updated)
        return updated

    @staticmethod
    def post_fingerprint(post: dict) -> str:
        import re

        author = str(post.get("author") or "").strip().lower()
        # Normalise punctuation differences ("Name ·", "Name", "Name @handle").
        author = re.sub(r"[^\w\s@]+$", "", author).strip()
        url = str(post.get("post_url") or post.get("url") or "").strip().lower()
        url = url.split("?")[0].rstrip("/")
        text = re.sub(r"\s+", " ", str(post.get("text") or "")).strip().lower()[:180]
        raw = "|".join(
            [
                str(post.get("platform") or "").strip().lower(),
                url,
                author,
                text,
            ]
        )
        return hashlib.sha1(raw.encode()).hexdigest()

    def save_hiring_post(self, post: dict) -> tuple[bool, str]:
        """Persist a scored social hiring post. Returns (was_new, fingerprint)."""
        from services.filters import parse_posted_at
        from services.scoring import score_hiring_post

        fingerprint = self.post_fingerprint(post)
        existing = None
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM hiring_posts WHERE fingerprint = %s LIMIT 1",
                (fingerprint,),
            ).fetchone()
        if existing is not None:
            return False, fingerprint

        posted_at = parse_posted_at(post.get("posted_at"))
        breakdown = post.get("_breakdown") or score_hiring_post(
            post, keywords=post.get("_keywords")
        )
        keywords_value = post.get("keywords_matched") or []
        if isinstance(keywords_value, (list, tuple)):
            keywords_value = ",".join(str(k) for k in keywords_value)

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO hiring_posts
                    (fingerprint, platform, author, author_url, text, post_url, posted_at,
                     keywords_matched, score, relevance, authenticity, verdict, score_reasons)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    fingerprint,
                    post.get("platform", ""),
                    post.get("author", ""),
                    post.get("author_url", ""),
                    post.get("text", ""),
                    post.get("post_url") or post.get("url", ""),
                    posted_at,
                    keywords_value,
                    breakdown.score,
                    breakdown.relevance,
                    breakdown.authenticity,
                    breakdown.verdict,
                    " | ".join(breakdown.reasons),
                ),
            ).fetchone()
        return row is not None, fingerprint

    def search_hiring_posts(
        self,
        platform: str | None = None,
        keywords: list[str] | None = None,
        min_score: float | None = None,
        posted_hours: int | None = 24,
        limit: int = 50,
        offset: int = 0,
        remote_only: bool = True,
    ) -> tuple[list[dict], int]:
        where_clauses = []
        params: list[object] = []

        if posted_hours is not None:
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(hours=posted_hours)
            where_clauses.append("COALESCE(posted_at, scraped_at) >= %s")
            params.append(cutoff)

        if remote_only:
            remote_terms = [
                "remote",
                "work from home",
                "wfh",
                "anywhere",
                "worldwide",
                "telecommute",
                "remote-first",
                "home-based",
                # Arabic remote phrasing (including underscore hashtags)
                "عن بعد",
                "عن_بعد",
                "من المنزل",
                "من_المنزل",
                "ريموت",
            ]
            onsite_terms = [
                "hybrid",
                "on-site",
                "onsite",
                "in-office",
                "office-based",
                "in person",
                # Arabic onsite/hybrid phrasing
                "حضوري",
                "هجين",
                "من المكتب",
            ]
            positive = []
            for term in remote_terms:
                positive.append("text ILIKE %s")
                params.append(f"%{term}%")
            negative = []
            for term in onsite_terms:
                negative.append("text ILIKE %s")
                params.append(f"%{term}%")
            where_clauses.append(
                "(" + " OR ".join(positive) + ") AND NOT (" + " OR ".join(negative) + ")"
            )

        if platform and platform.lower() != "all":
            where_clauses.append("platform = %s")
            params.append(platform.lower())

        if min_score is not None:
            where_clauses.append("COALESCE(score, 0) >= %s")
            params.append(float(min_score))

        if keywords:
            keyword_clauses = []
            for kw in keywords:
                if kw.strip():
                    keyword_clauses.append("(text ILIKE %s OR keywords_matched ILIKE %s)")
                    like = f"%{kw.strip()}%"
                    params.extend([like, like])
            if keyword_clauses:
                where_clauses.append("(" + " OR ".join(keyword_clauses) + ")")

        where_str = ""
        if where_clauses:
            where_str = " AND " + " AND ".join(where_clauses)

        count_query = f"SELECT COUNT(*) AS count FROM hiring_posts WHERE 1=1{where_str}"
        results_query = (
            f"SELECT * FROM hiring_posts WHERE 1=1{where_str} "
            "ORDER BY COALESCE(score, 0) DESC, COALESCE(posted_at, scraped_at) DESC "
            "LIMIT %s OFFSET %s"
        )
        results_params = params + [limit, offset]

        with self._connect() as conn:
            count_row = conn.execute(count_query, params).fetchone()
            total = int(count_row["count"]) if count_row else 0
            rows = conn.execute(results_query, results_params).fetchall()
        return [dict(row) for row in rows], total

    def recent_hiring_posts(self, hours: int = 24, platform: str | None = None) -> list[dict]:
        posts, _ = self.search_hiring_posts(
            platform=platform, posted_hours=hours, limit=500, offset=0
        )
        return posts

    @staticmethod
    def fingerprint(job: dict, source: str | None = None) -> str:
        # Generate fingerprint based on job title, company, and source to prevent duplicates in aggregation
        title = (job.get("title") or "").strip().lower()
        company = (job.get("company") or "").strip().lower()
        src = (source or job.get("source") or job.get("site") or "").strip().lower()
        raw = f"{title}|{company}|{src}"
        return hashlib.sha1(raw.encode()).hexdigest()
