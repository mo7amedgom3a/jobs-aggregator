"""YC founder sourcing & outreach endpoints."""

from __future__ import annotations

import csv
import io
import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from config.settings import YC_ENABLED
from dependencies import get_yc_repository
from models.yc import (
    OutreachListResponse,
    OutreachMessage,
    OutreachSendRequest,
    OutreachSendResponse,
    OutreachUpdateRequest,
    YCCollectRequest,
    YCCompaniesResponse,
    YCCompany,
    YCCrawlResponse,
    YCDraftRequest,
    YCDraftResponse,
    YCFounder,
    YCFoundersResponse,
    YCJob,
    YCJobRow,
    YCJobsResponse,
    YCStatusResponse,
)
from repository.yc import YCRepository

logger = logging.getLogger("job_aggregator.routes.yc")

router = APIRouter(prefix="/yc", tags=["yc"])


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _split(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _company(row: dict[str, Any]) -> YCCompany:
    return YCCompany(
        id=int(row["id"]),
        slug=row.get("slug") or "",
        name=row.get("name") or "",
        batch=row.get("batch"),
        one_liner=row.get("one_liner"),
        website=row.get("website"),
        team_size=row.get("team_size"),
        status=row.get("status"),
        is_hiring=bool(row.get("is_hiring")),
        industries=_split(row.get("industries")),
        locations=_split(row.get("locations")),
        small_logo_url=row.get("small_logo_url"),
        email=row.get("email"),
        email_source=row.get("email_source"),
        jobs_count=int(row.get("jobs_count") or 0),
        founders_count=int(row.get("founders_count") or 0),
    )


def _message(row: dict[str, Any]) -> OutreachMessage:
    return OutreachMessage(
        id=int(row["id"]),
        channel=row.get("channel") or "",
        recipient=row.get("recipient") or "",
        subject=row.get("subject"),
        body=row.get("body") or "",
        status=row.get("status") or "draft",
        error=row.get("error"),
        created_at=_iso(row.get("created_at")),
        sent_at=_iso(row.get("sent_at")),
        founder_name=row.get("founder_name"),
        founder_title=row.get("founder_title"),
        company_name=row.get("company_name"),
        company_slug=row.get("company_slug"),
        company_batch=row.get("company_batch"),
        company_one_liner=row.get("company_one_liner"),
        x_handle=row.get("x_handle"),
        linkedin_url=row.get("linkedin_url"),
    )


# ─── Crawl ───────────────────────────────────────────────────────────────────


def _run_collect(req: YCCollectRequest) -> None:
    from services.yc import collect_yc

    logger.info("Starting YC collection: batches=%s", req.batches or "default")
    try:
        summary = collect_yc(
            batches=req.batches,
            max_companies_per_batch=req.max_companies_per_batch,
            max_pages_per_batch=req.max_pages_per_batch,
            skip_existing=req.skip_existing,
            discover_emails=req.discover_emails,
        )
        logger.info("YC collection finished: %s", summary.get("status"))
    except Exception as exc:  # noqa: BLE001
        logger.error("YC collection crashed: %s", exc, exc_info=True)


@router.post(
    "/collect",
    response_model=YCCrawlResponse,
    summary="Start a YC batch crawl (companies → founders → contacts)",
    description=(
        "Runs in the background. Crawls the public YC directory API for the selected "
        "batches, then each company/founder page, and stores companies, founders, "
        "social profiles, emails and open roles."
    ),
)
async def collect(req: YCCollectRequest) -> YCCrawlResponse:
    from services.yc import run_state

    if not YC_ENABLED:
        return YCCrawlResponse(
            status="error",
            message="The YC pipeline is disabled. Set YC_ENABLED=true in backend/.env.",
        )
    state = run_state()
    if state.get("running"):
        return YCCrawlResponse(
            status="already_running",
            message="A YC crawl is already running. Check /yc/status for progress.",
        )

    thread = threading.Thread(target=_run_collect, args=(req,), daemon=True, name="yc-collect")
    thread.start()
    return YCCrawlResponse(
        status="initiated",
        message=(
            "YC crawl started. Full 2025+2026 coverage can take a while — "
            "poll /yc/status or refresh the Companies tab."
        ),
    )


@router.post(
    "/collect/stop",
    response_model=YCCrawlResponse,
    summary="Stop the running YC crawl",
    description=(
        "Requests a cooperative stop. The crawl finishes the current HTTP request, "
        "then stops before the next company. Requests also have hard timeouts, so "
        "a hung site cannot stall the pipeline indefinitely."
    ),
)
async def stop_collect() -> YCCrawlResponse:
    from services.yc import request_stop

    stopped = request_stop()
    return YCCrawlResponse(
        status="stopping" if stopped else "idle",
        message=(
            "Stop requested. The crawl will halt after the current request finishes."
            if stopped
            else "No YC crawl is currently running."
        ),
    )


@router.get(
    "/status",
    response_model=YCStatusResponse,
    summary="YC crawl progress & pipeline statistics",
)
async def status(repository: YCRepository = Depends(get_yc_repository)) -> YCStatusResponse:
    from services.yc import run_state

    return YCStatusResponse(state=run_state(), stats=repository.pipeline_stats())


# ─── Read companies / founders ───────────────────────────────────────────────


@router.get(
    "/companies",
    response_model=YCCompaniesResponse,
    summary="List stored YC companies",
)
async def list_companies(
    batch: str | None = None,
    is_hiring: bool | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    repository: YCRepository = Depends(get_yc_repository),
) -> YCCompaniesResponse:
    rows, total = repository.list_companies(
        batch=batch, is_hiring=is_hiring, q=q, limit=limit, offset=offset
    )
    return YCCompaniesResponse(
        total=total,
        limit=limit,
        offset=offset,
        companies=[_company(row) for row in rows],
    )


@router.get(
    "/founders",
    response_model=YCFoundersResponse,
    summary="List founders with their X / LinkedIn / email contacts",
)
async def list_founders(
    batch: str | None = None,
    q: str | None = None,
    has_email: bool | None = None,
    has_x: bool | None = None,
    has_linkedin: bool | None = None,
    company_slug: str | None = None,
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    repository: YCRepository = Depends(get_yc_repository),
) -> YCFoundersResponse:
    rows, total = repository.list_founders(
        batch=batch,
        q=q,
        has_email=has_email,
        has_x=has_x,
        has_linkedin=has_linkedin,
        company_slug=company_slug,
        limit=limit,
        offset=offset,
    )
    company_ids = sorted({int(row["company_id"]) for row in rows})
    jobs_by_company = repository.list_company_jobs(company_ids)

    founders: list[YCFounder] = []
    for row in rows:
        company_id = int(row["company_id"])
        founders.append(
            YCFounder(
                id=int(row["id"]),
                yc_slug=row.get("yc_slug") or "",
                name=row.get("name") or "",
                title=row.get("title"),
                bio=row.get("bio"),
                profile_url=row.get("profile_url"),
                avatar_url=row.get("avatar_url"),
                x_url=row.get("x_url"),
                x_handle=row.get("x_handle"),
                linkedin_url=row.get("linkedin_url"),
                email=row.get("email"),
                email_source=row.get("email_source"),
                email_confidence=row.get("email_confidence"),
                yc_has_email=bool(row.get("yc_has_email")),
                batches=_split(row.get("batches")),
                company_id=company_id,
                company_name=row.get("company_name"),
                company_slug=row.get("company_slug"),
                company_batch=row.get("company_batch"),
                company_one_liner=row.get("company_one_liner"),
                company_website=row.get("company_website"),
                company_logo_url=row.get("company_logo_url"),
                company_is_hiring=bool(row.get("company_is_hiring")),
                company_jobs_count=int(row.get("company_jobs_count") or 0),
                jobs=[YCJob(**job) for job in jobs_by_company.get(company_id, [])],
            )
        )
    return YCFoundersResponse(total=total, limit=limit, offset=offset, founders=founders)


@router.get(
    "/jobs",
    response_model=YCJobsResponse,
    summary="List open roles across stored YC companies",
)
async def list_jobs(
    batch: str | None = None,
    q: str | None = None,
    company_slug: str | None = None,
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    repository: YCRepository = Depends(get_yc_repository),
) -> YCJobsResponse:
    rows, total = repository.list_jobs(
        batch=batch, q=q, company_slug=company_slug, limit=limit, offset=offset
    )
    return YCJobsResponse(
        total=total,
        limit=limit,
        offset=offset,
        jobs=[
            YCJobRow(
                id=int(row["id"]),
                title=row.get("title") or "",
                url=row.get("url"),
                location=row.get("location"),
                yc_job_slug=row.get("yc_job_slug"),
                company_name=row.get("company_name"),
                company_slug=row.get("company_slug"),
                company_batch=row.get("company_batch"),
                company_website=row.get("company_website"),
                company_one_liner=row.get("company_one_liner"),
                company_logo_url=row.get("company_logo_url"),
                company_is_hiring=bool(row.get("company_is_hiring")),
            )
            for row in rows
        ],
    )


# ─── Outreach drafting ───────────────────────────────────────────────────────


@router.post(
    "/outreach/draft",
    response_model=YCDraftResponse,
    summary="Generate outreach drafts for founders with contact info",
)
async def draft(
    req: YCDraftRequest,
    repository: YCRepository = Depends(get_yc_repository),
) -> YCDraftResponse:
    from services.outreach import draft_outreach

    summary = draft_outreach(
        repository=repository,
        channels=req.channels,
        keywords=req.keywords,
        batch=req.batch,
        company_slug=req.company_slug,
        limit=req.limit,
    )
    return YCDraftResponse(**summary)


@router.get(
    "/outreach",
    response_model=OutreachListResponse,
    summary="List outreach messages (draft review queue)",
)
async def list_outreach(
    status: str = "draft",
    channel: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    repository: YCRepository = Depends(get_yc_repository),
) -> OutreachListResponse:
    rows, total = repository.list_outreach(
        status=status, channel=channel, limit=limit, offset=offset
    )
    return OutreachListResponse(
        total=total,
        limit=limit,
        offset=offset,
        messages=[_message(row) for row in rows],
    )


def _require_message(repository: YCRepository, message_id: int) -> dict[str, Any]:
    message = repository.get_outreach(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail=f"Outreach message {message_id} not found")
    return message


@router.get(
    "/outreach/{message_id}",
    response_model=OutreachMessage,
    summary="Get one outreach message",
)
async def get_outreach(
    message_id: int,
    repository: YCRepository = Depends(get_yc_repository),
) -> OutreachMessage:
    return _message(_require_message(repository, message_id))


@router.patch(
    "/outreach/{message_id}",
    response_model=OutreachMessage,
    summary="Edit a draft or change its status",
)
async def update_outreach(
    message_id: int,
    req: OutreachUpdateRequest,
    repository: YCRepository = Depends(get_yc_repository),
) -> OutreachMessage:
    _require_message(repository, message_id)
    allowed = {"draft", "approved", "skipped", "failed", "sent"}
    if req.status and req.status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")
    repository.update_outreach(
        message_id,
        status=req.status,
        subject=req.subject,
        body=req.body,
    )
    return _message(_require_message(repository, message_id))


@router.post(
    "/outreach/{message_id}/approve",
    response_model=OutreachMessage,
    summary="Approve one draft for sending",
)
async def approve_outreach(
    message_id: int,
    repository: YCRepository = Depends(get_yc_repository),
) -> OutreachMessage:
    _require_message(repository, message_id)
    repository.update_outreach(message_id, status="approved")
    return _message(_require_message(repository, message_id))


@router.post(
    "/outreach/{message_id}/skip",
    response_model=OutreachMessage,
    summary="Skip one draft",
)
async def skip_outreach(
    message_id: int,
    repository: YCRepository = Depends(get_yc_repository),
) -> OutreachMessage:
    _require_message(repository, message_id)
    repository.update_outreach(message_id, status="skipped")
    return _message(_require_message(repository, message_id))


# ─── Sending ─────────────────────────────────────────────────────────────────


def _run_send(channel: str, limit: int | None, dry_run: bool) -> None:
    from services.outreach import send_approved
    from services.outreach.sender import CHANNEL_LIMITS

    logger.info("Starting approved outreach send: channel=%s dry_run=%s", channel, dry_run)
    try:
        summary = send_approved(
            YCRepository(),
            channel=channel,
            limit=limit or CHANNEL_LIMITS.get(channel),
            dry_run=dry_run,
        )
        logger.info("Outreach send finished: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.error("Outreach send crashed: %s", exc, exc_info=True)


@router.post(
    "/outreach/send",
    response_model=OutreachSendResponse,
    summary="Send all approved messages for one channel",
    description=(
        "Sends only messages with status='approved'. DM channels use the saved browser "
        "profiles and are strictly rate-limited; use dry_run=true to preview first."
    ),
)
async def send(req: OutreachSendRequest) -> OutreachSendResponse:
    if req.channel not in {"email", "x", "linkedin"}:
        raise HTTPException(status_code=400, detail="channel must be email, x or linkedin")
    if not req.dry_run:
        thread = threading.Thread(
            target=_run_send,
            args=(req.channel, req.limit, req.dry_run),
            daemon=True,
            name=f"yc-send-{req.channel}",
        )
        thread.start()
        return OutreachSendResponse(
            channel=req.channel,
            dry_run=False,
            attempted=0,
            sent=0,
            failed=0,
            errors=["Send started in the background. Watch /yc/outreach for status updates."],
        )

    from services.outreach import send_approved
    from services.outreach.sender import CHANNEL_LIMITS

    summary = send_approved(
        YCRepository(),
        channel=req.channel,
        limit=req.limit or CHANNEL_LIMITS.get(req.channel),
        dry_run=req.dry_run,
    )
    return OutreachSendResponse(**summary)


# ─── Export ──────────────────────────────────────────────────────────────────


@router.get(
    "/export.csv",
    summary="Export founders and contacts as CSV",
    response_class=StreamingResponse,
)
async def export_csv(
    batch: str | None = None,
    repository: YCRepository = Depends(get_yc_repository),
) -> StreamingResponse:
    rows, _ = repository.list_founders(batch=batch, limit=10000, offset=0)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "company",
            "batch",
            "company_website",
            "founder",
            "title",
            "email",
            "email_source",
            "x",
            "linkedin",
            "founder_profile",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("company_name"),
                row.get("company_batch"),
                row.get("company_website"),
                row.get("name"),
                row.get("title"),
                row.get("email"),
                row.get("email_source"),
                row.get("x_url"),
                row.get("linkedin_url"),
                row.get("profile_url"),
            ]
        )
    buffer.seek(0)
    filename = f"yc-founders-{batch or 'all'}.csv".replace(" ", "-")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
