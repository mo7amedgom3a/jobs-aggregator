"""PostgreSQL repository for the YC founder sourcing & outreach pipeline."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - handled at runtime when DB is used.
    psycopg = None
    dict_row = None

from config.settings import DATABASE_URL

logger = logging.getLogger("job_aggregator.repository.yc")


class YCRepository:
    """Data access for YC companies, founders, jobs, and outreach drafts."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or DATABASE_URL

    @contextmanager
    def _connect(self) -> Iterator:
        if psycopg is None:
            raise RuntimeError("psycopg is not installed. Install psycopg[binary] to use PostgreSQL.")
        with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5) as conn:
            yield conn

    # ─── Schema ──────────────────────────────────────────────────────────────

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS yc_companies (
                    id BIGSERIAL PRIMARY KEY,
                    yc_id BIGINT UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    batch TEXT,
                    batch_code TEXT,
                    one_liner TEXT,
                    long_description TEXT,
                    website TEXT,
                    team_size INTEGER,
                    status TEXT,
                    is_hiring BOOLEAN DEFAULT FALSE,
                    industries TEXT,
                    regions TEXT,
                    locations TEXT,
                    small_logo_url TEXT,
                    email TEXT,
                    email_source TEXT,
                    jobs_count INTEGER DEFAULT 0,
                    last_crawled_at TIMESTAMPTZ,
                    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_yc_companies_batch ON yc_companies (batch);
                CREATE INDEX IF NOT EXISTS idx_yc_companies_hiring ON yc_companies (is_hiring);

                CREATE TABLE IF NOT EXISTS yc_founders (
                    id BIGSERIAL PRIMARY KEY,
                    company_id BIGINT NOT NULL REFERENCES yc_companies(id) ON DELETE CASCADE,
                    yc_slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    title TEXT,
                    bio TEXT,
                    profile_url TEXT,
                    avatar_url TEXT,
                    x_url TEXT,
                    x_handle TEXT,
                    linkedin_url TEXT,
                    email TEXT,
                    email_source TEXT,
                    email_confidence TEXT,
                    yc_has_email BOOLEAN DEFAULT FALSE,
                    batches TEXT,
                    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_yc_founders_company ON yc_founders (company_id);
                CREATE INDEX IF NOT EXISTS idx_yc_founders_email ON yc_founders (email);

                ALTER TABLE yc_founders ADD COLUMN IF NOT EXISTS yc_has_email BOOLEAN DEFAULT FALSE;
                ALTER TABLE yc_founders ADD COLUMN IF NOT EXISTS avatar_url TEXT;
                ALTER TABLE yc_companies ADD COLUMN IF NOT EXISTS batch_code TEXT;
                ALTER TABLE yc_companies ADD COLUMN IF NOT EXISTS email TEXT;
                ALTER TABLE yc_companies ADD COLUMN IF NOT EXISTS email_source TEXT;
                ALTER TABLE yc_companies ADD COLUMN IF NOT EXISTS jobs_count INTEGER DEFAULT 0;
                ALTER TABLE yc_companies ADD COLUMN IF NOT EXISTS last_crawled_at TIMESTAMPTZ;

                CREATE TABLE IF NOT EXISTS yc_company_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    company_id BIGINT NOT NULL REFERENCES yc_companies(id) ON DELETE CASCADE,
                    yc_job_slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    location TEXT,
                    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (company_id, yc_job_slug)
                );

                CREATE INDEX IF NOT EXISTS idx_yc_company_jobs_company ON yc_company_jobs (company_id);

                CREATE TABLE IF NOT EXISTS outreach_messages (
                    id BIGSERIAL PRIMARY KEY,
                    founder_id BIGINT NOT NULL REFERENCES yc_founders(id) ON DELETE CASCADE,
                    company_id BIGINT NOT NULL REFERENCES yc_companies(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    fingerprint TEXT NOT NULL UNIQUE,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sent_at TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach_messages (status);
                CREATE INDEX IF NOT EXISTS idx_outreach_channel ON outreach_messages (channel);
                CREATE INDEX IF NOT EXISTS idx_outreach_founder ON outreach_messages (founder_id);

                CREATE TABLE IF NOT EXISTS yc_pipeline_state (
                    id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        logger.info("YC pipeline schema is ready.")

    # ─── Durable crawl state (shared across API workers) ─────────────────────

    def save_pipeline_state(self, state: dict[str, Any]) -> None:
        import json

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO yc_pipeline_state (id, state, updated_at)
                VALUES (1, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()
                """,
                (json.dumps(state),),
            )

    def load_pipeline_state(self) -> dict[str, Any] | None:
        import json

        with self._connect() as conn:
            row = conn.execute("SELECT state FROM yc_pipeline_state WHERE id = 1").fetchone()
        if not row:
            return None
        try:
            return json.loads(row["state"])
        except (ValueError, TypeError):
            return None

    # ─── Companies ───────────────────────────────────────────────────────────

    def upsert_company(self, company: dict[str, Any]) -> int:
        payload = {
            "yc_id": company.get("id"),
            "slug": company["slug"],
            "name": company.get("name") or company["slug"],
            "batch": company.get("batch"),
            "batch_code": company.get("batch_code"),
            "one_liner": company.get("oneLiner"),
            "long_description": company.get("longDescription"),
            "website": company.get("website"),
            "team_size": company.get("teamSize"),
            "status": company.get("status"),
            "is_hiring": "isHiring" in (company.get("badges") or []),
            "industries": ",".join(company.get("industries") or []),
            "regions": ",".join(company.get("regions") or []),
            "locations": ",".join(company.get("locations") or []),
            "small_logo_url": company.get("smallLogoUrl"),
        }
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO yc_companies
                    (yc_id, slug, name, batch, batch_code, one_liner, long_description, website,
                     team_size, status, is_hiring, industries, regions, locations,
                     small_logo_url, last_crawled_at)
                VALUES
                    (%(yc_id)s, %(slug)s, %(name)s, %(batch)s, %(batch_code)s, %(one_liner)s,
                     %(long_description)s, %(website)s, %(team_size)s, %(status)s,
                     %(is_hiring)s, %(industries)s, %(regions)s, %(locations)s,
                     %(small_logo_url)s, NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    yc_id = COALESCE(EXCLUDED.yc_id, yc_companies.yc_id),
                    name = EXCLUDED.name,
                    batch = EXCLUDED.batch,
                    batch_code = COALESCE(EXCLUDED.batch_code, yc_companies.batch_code),
                    one_liner = EXCLUDED.one_liner,
                    long_description = COALESCE(NULLIF(EXCLUDED.long_description, ''), yc_companies.long_description),
                    website = COALESCE(EXCLUDED.website, yc_companies.website),
                    team_size = COALESCE(EXCLUDED.team_size, yc_companies.team_size),
                    status = COALESCE(EXCLUDED.status, yc_companies.status),
                    is_hiring = EXCLUDED.is_hiring,
                    industries = EXCLUDED.industries,
                    regions = EXCLUDED.regions,
                    locations = EXCLUDED.locations,
                    small_logo_url = COALESCE(EXCLUDED.small_logo_url, yc_companies.small_logo_url),
                    scraped_at = NOW()
                RETURNING id
                """,
                payload,
            ).fetchone()
        return int(row["id"])

    def set_company_contact(
        self,
        company_id: int,
        email: str | None,
        source: str | None,
        jobs_count: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE yc_companies
                   SET email = COALESCE(%s, email),
                       email_source = COALESCE(%s, email_source),
                       jobs_count = COALESCE(%s, jobs_count),
                       last_crawled_at = NOW()
                 WHERE id = %s
                """,
                (email, source, jobs_count, company_id),
            )

    def company_exists(self, slug: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM yc_companies WHERE slug = %s", (slug,)).fetchone()
        return row is not None

    # ─── Founders ────────────────────────────────────────────────────────────

    def upsert_founder(self, company_id: int, founder: dict[str, Any]) -> int:
        payload = {
            "company_id": company_id,
            "yc_slug": founder["yc_slug"],
            "name": founder.get("name") or founder["yc_slug"],
            "title": founder.get("title"),
            "bio": founder.get("bio"),
            "profile_url": founder.get("profile_url"),
            "avatar_url": founder.get("avatar_url"),
            "x_url": founder.get("x_url"),
            "x_handle": founder.get("x_handle"),
            "linkedin_url": founder.get("linkedin_url"),
            "email": founder.get("email"),
            "email_source": founder.get("email_source"),
            "email_confidence": founder.get("email_confidence"),
            "yc_has_email": bool(founder.get("yc_has_email")),
            "batches": ",".join(founder.get("batches") or []),
        }
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO yc_founders
                    (company_id, yc_slug, name, title, bio, profile_url, avatar_url,
                     x_url, x_handle, linkedin_url, email, email_source,
                     email_confidence, yc_has_email, batches)
                VALUES
                    (%(company_id)s, %(yc_slug)s, %(name)s, %(title)s, %(bio)s,
                     %(profile_url)s, %(avatar_url)s, %(x_url)s, %(x_handle)s,
                     %(linkedin_url)s, %(email)s, %(email_source)s,
                     %(email_confidence)s, %(yc_has_email)s, %(batches)s)
                ON CONFLICT (yc_slug) DO UPDATE SET
                    company_id = EXCLUDED.company_id,
                    name = EXCLUDED.name,
                    title = COALESCE(EXCLUDED.title, yc_founders.title),
                    bio = COALESCE(NULLIF(EXCLUDED.bio, ''), yc_founders.bio),
                    profile_url = COALESCE(EXCLUDED.profile_url, yc_founders.profile_url),
                    avatar_url = COALESCE(EXCLUDED.avatar_url, yc_founders.avatar_url),
                    x_url = COALESCE(EXCLUDED.x_url, yc_founders.x_url),
                    x_handle = COALESCE(EXCLUDED.x_handle, yc_founders.x_handle),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, yc_founders.linkedin_url),
                    email = COALESCE(EXCLUDED.email, yc_founders.email),
                    email_source = COALESCE(EXCLUDED.email_source, yc_founders.email_source),
                    email_confidence = COALESCE(EXCLUDED.email_confidence, yc_founders.email_confidence),
                    yc_has_email = EXCLUDED.yc_has_email,
                    batches = COALESCE(NULLIF(EXCLUDED.batches, ''), yc_founders.batches),
                    scraped_at = NOW()
                RETURNING id
                """,
                payload,
            ).fetchone()
        return int(row["id"])

    def update_founder_avatar(self, founder_id: int, avatar_url: str | None) -> None:
        if not avatar_url:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE yc_founders SET avatar_url = %s WHERE id = %s",
                (avatar_url, founder_id),
            )

    # ─── Company jobs ────────────────────────────────────────────────────────

    def upsert_company_jobs(self, company_id: int, jobs: list[dict[str, Any]]) -> None:
        if not jobs:
            return
        with self._connect() as conn:
            for job in jobs:
                conn.execute(
                    """
                    INSERT INTO yc_company_jobs (company_id, yc_job_slug, title, url, location)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (company_id, yc_job_slug) DO UPDATE SET
                        title = EXCLUDED.title,
                        url = COALESCE(EXCLUDED.url, yc_company_jobs.url),
                        location = COALESCE(EXCLUDED.location, yc_company_jobs.location),
                        scraped_at = NOW()
                    """,
                    (
                        company_id,
                        job["yc_job_slug"],
                        job.get("title") or job["yc_job_slug"],
                        job.get("url"),
                        job.get("location"),
                    ),
                )

    # ─── Outreach ────────────────────────────────────────────────────────────

    def create_outreach(
        self,
        founder_id: int,
        company_id: int,
        channel: str,
        recipient: str,
        subject: str | None,
        body: str,
        fingerprint: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO outreach_messages
                    (founder_id, company_id, channel, recipient, subject, body, fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO NOTHING
                RETURNING id
                """,
                (founder_id, company_id, channel, recipient, subject, body, fingerprint),
            ).fetchone()
        return row is not None

    def list_companies(
        self,
        batch: str | None = None,
        is_hiring: bool | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if batch:
            where.append("c.batch = %s")
            params.append(batch)
        if is_hiring is not None:
            where.append("c.is_hiring = %s")
            params.append(is_hiring)
        if q:
            where.append("(c.name ILIKE %s OR c.one_liner ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM yc_companies c {clause}", params
            ).fetchone()["total"]
            rows = conn.execute(
                f"""
                SELECT c.*, COUNT(f.id) AS founders_count
                  FROM yc_companies c
                  LEFT JOIN yc_founders f ON f.company_id = c.id
                  {clause}
                 GROUP BY c.id
                 ORDER BY COALESCE(RIGHT(c.batch_code, 2), '') DESC,
                          CASE UPPER(LEFT(c.batch_code, 1))
                               WHEN 'F' THEN 4 WHEN 'S' THEN 3 WHEN 'P' THEN 2 ELSE 1
                          END DESC, c.name ASC
                 LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            ).fetchall()
        return list(rows), int(total)

    def list_founders(
        self,
        batch: str | None = None,
        q: str | None = None,
        has_email: bool | None = None,
        has_x: bool | None = None,
        has_linkedin: bool | None = None,
        company_slug: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if batch:
            where.append("c.batch = %s")
            params.append(batch)
        if company_slug:
            where.append("c.slug = %s")
            params.append(company_slug)
        if q:
            where.append("(f.name ILIKE %s OR c.name ILIKE %s OR f.title ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        if has_email:
            where.append("f.email IS NOT NULL AND f.email <> ''")
        if has_x:
            where.append("f.x_url IS NOT NULL AND f.x_url <> ''")
        if has_linkedin:
            where.append("f.linkedin_url IS NOT NULL AND f.linkedin_url <> ''")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                  FROM yc_founders f
                  JOIN yc_companies c ON c.id = f.company_id
                  {clause}
                """,
                params,
            ).fetchone()["total"]
            rows = conn.execute(
                f"""
                SELECT f.*, c.name AS company_name, c.slug AS company_slug,
                       c.batch AS company_batch, c.one_liner AS company_one_liner,
                       c.website AS company_website, c.is_hiring AS company_is_hiring,
                       c.small_logo_url AS company_logo_url,
                       c.jobs_count AS company_jobs_count
                  FROM yc_founders f
                  JOIN yc_companies c ON c.id = f.company_id
                  {clause}
                 ORDER BY COALESCE(RIGHT(c.batch_code, 2), '') DESC,
                          CASE UPPER(LEFT(c.batch_code, 1))
                               WHEN 'F' THEN 4 WHEN 'S' THEN 3 WHEN 'P' THEN 2 ELSE 1
                          END DESC, f.name ASC
                 LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            ).fetchall()
        return list(rows), int(total)

    def list_company_jobs(self, company_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not company_ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT company_id, title, url, location
                  FROM yc_company_jobs
                 WHERE company_id = ANY(%s)
                 ORDER BY title ASC
                """,
                (company_ids,),
            ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["company_id"]), []).append(dict(row))
        return grouped

    def list_jobs(
        self,
        batch: str | None = None,
        q: str | None = None,
        company_slug: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if batch:
            where.append("c.batch = %s")
            params.append(batch)
        if company_slug:
            where.append("c.slug = %s")
            params.append(company_slug)
        if q:
            where.append("(j.title ILIKE %s OR c.name ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                  FROM yc_company_jobs j
                  JOIN yc_companies c ON c.id = j.company_id
                  {clause}
                """,
                params,
            ).fetchone()["total"]
            rows = conn.execute(
                f"""
                SELECT j.id, j.title, j.url, j.location, j.yc_job_slug,
                       c.name AS company_name, c.slug AS company_slug,
                       c.batch AS company_batch, c.website AS company_website,
                       c.one_liner AS company_one_liner, c.is_hiring AS company_is_hiring,
                       c.small_logo_url AS company_logo_url
                  FROM yc_company_jobs j
                  JOIN yc_companies c ON c.id = j.company_id
                  {clause}
                 ORDER BY COALESCE(RIGHT(c.batch_code, 2), '') DESC,
                          CASE UPPER(LEFT(c.batch_code, 1))
                               WHEN 'F' THEN 4 WHEN 'S' THEN 3 WHEN 'P' THEN 2 ELSE 1
                          END DESC, j.title ASC
                 LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            ).fetchall()
        return list(rows), int(total)

    def list_outreach(
        self,
        status: str | None = "draft",
        channel: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if status and status != "all":
            where.append("m.status = %s")
            params.append(status)
        if channel and channel != "all":
            where.append("m.channel = %s")
            params.append(channel)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM outreach_messages m {clause}", params
            ).fetchone()["total"]
            rows = conn.execute(
                f"""
                SELECT m.*, f.name AS founder_name, f.title AS founder_title,
                       f.x_url, f.x_handle, f.linkedin_url, f.profile_url,
                       c.name AS company_name, c.slug AS company_slug,
                       c.batch AS company_batch, c.one_liner AS company_one_liner
                  FROM outreach_messages m
                  JOIN yc_founders f ON f.id = m.founder_id
                  JOIN yc_companies c ON c.id = m.company_id
                  {clause}
                 ORDER BY m.created_at DESC
                 LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            ).fetchall()
        return list(rows), int(total)

    def get_outreach(self, message_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT m.*, f.name AS founder_name, f.title AS founder_title,
                       f.x_url, f.x_handle, f.linkedin_url,
                       c.name AS company_name, c.slug AS company_slug,
                       c.batch AS company_batch, c.one_liner AS company_one_liner
                  FROM outreach_messages m
                  JOIN yc_founders f ON f.id = m.founder_id
                  JOIN yc_companies c ON c.id = m.company_id
                 WHERE m.id = %s
                """,
                (message_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_outreach(
        self,
        message_id: int,
        status: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        error: str | None = None,
        sent: bool = False,
    ) -> bool:
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        if subject is not None:
            sets.append("subject = %s")
            params.append(subject)
        if body is not None:
            sets.append("body = %s")
            params.append(body)
        if error is not None:
            sets.append("error = %s")
            params.append(error)
        if sent:
            sets.append("sent_at = NOW()")
        if not sets:
            return False
        params.append(message_id)
        with self._connect() as conn:
            row = conn.execute(
                f"UPDATE outreach_messages SET {', '.join(sets)} WHERE id = %s RETURNING id",
                params,
            ).fetchone()
        return row is not None

    def outreach_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM outreach_messages GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def pipeline_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            companies = conn.execute("SELECT COUNT(*) AS n FROM yc_companies").fetchone()["n"]
            founders = conn.execute("SELECT COUNT(*) AS n FROM yc_founders").fetchone()["n"]
            with_email = conn.execute(
                "SELECT COUNT(*) AS n FROM yc_founders WHERE email IS NOT NULL AND email <> ''"
            ).fetchone()["n"]
            with_x = conn.execute(
                "SELECT COUNT(*) AS n FROM yc_founders WHERE x_url IS NOT NULL AND x_url <> ''"
            ).fetchone()["n"]
            with_linkedin = conn.execute(
                "SELECT COUNT(*) AS n FROM yc_founders WHERE linkedin_url IS NOT NULL AND linkedin_url <> ''"
            ).fetchone()["n"]
            jobs = conn.execute("SELECT COUNT(*) AS n FROM yc_company_jobs").fetchone()["n"]
        return {
            "companies": int(companies),
            "founders": int(founders),
            "founders_with_email": int(with_email),
            "founders_with_x": int(with_x),
            "founders_with_linkedin": int(with_linkedin),
            "company_jobs": int(jobs),
            "outreach": self.outreach_stats(),
        }
