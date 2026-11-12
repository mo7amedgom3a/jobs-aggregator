"""Draft personalized outreach messages for YC founders."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from config.settings import (
    OUTREACH_KEYWORDS,
    OUTREACH_MAX_JOBS_IN_MESSAGE,
    OUTREACH_SENDER_COMPANY,
    OUTREACH_SENDER_LINK,
    OUTREACH_SENDER_NAME,
)
from repository.yc import YCRepository

logger = logging.getLogger("job_aggregator.services.outreach.drafting")

CHANNELS = ("email", "x", "linkedin")

_CHANNEL_LABELS = {
    "email": "email",
    "x": "X",
    "linkedin": "LinkedIn",
}


def _first_name(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "there"


def _sender_signature() -> str:
    parts = [p for p in (OUTREACH_SENDER_NAME, OUTREACH_SENDER_COMPANY) if p]
    signature = " — ".join(parts) if parts else "JobDork"
    if OUTREACH_SENDER_LINK:
        signature = f"{signature}\n{OUTREACH_SENDER_LINK}"
    return signature


def _rank_jobs(jobs: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    """Return the roles most relevant to the configured keywords (empty if none)."""
    def score(job: dict[str, Any]) -> int:
        title = (job.get("title") or "").lower()
        return sum(1 for keyword in keywords if keyword and keyword.lower() in title)

    ranked = sorted(jobs, key=lambda job: (-score(job), job.get("title") or ""))
    relevant = [job for job in ranked if score(job) > 0]
    return relevant[: max(1, OUTREACH_MAX_JOBS_IN_MESSAGE)]


def _jobs_phrase(jobs: list[dict[str, Any]]) -> str:
    titles = [job.get("title") for job in jobs if job.get("title")]
    if not titles:
        return ""
    if len(titles) == 1:
        return titles[0]
    return ", ".join(titles[:-1]) + f" and {titles[-1]}"


def build_message(
    founder: dict[str, Any],
    company: dict[str, Any],
    jobs: list[dict[str, Any]],
    channel: str,
    keywords: list[str] | None = None,
) -> dict[str, str | None]:
    """Return ``{subject, body}`` for one founder/channel."""
    relevant_jobs = _rank_jobs(jobs, keywords or OUTREACH_KEYWORDS)
    first_name = _first_name(founder.get("name") or "")
    company_name = company.get("name") or "your team"
    one_liner = (company.get("one_liner") or "").strip()
    jobs_phrase = _jobs_phrase(relevant_jobs)
    signature = _sender_signature()

    intro_context = f"{company_name}"
    if one_liner:
        intro_context = f"{company_name} ({one_liner})"

    roles_line = (
        f"I noticed {company_name} is hiring for {jobs_phrase}."
        if jobs_phrase
        else f"I came across {company_name} and wanted to reach out."
    )

    if channel == "email":
        subject = (
            f"Quick intro — {jobs_phrase} at {company_name}"
            if jobs_phrase
            else f"Quick intro — {company_name}"
        )
        body = (
            f"Hi {first_name},\n\n"
            f"I came across {intro_context} while looking at this year's YC companies.\n\n"
            f"{roles_line} I work across backend/platform engineering and would love to be "
            f"considered if you're still growing the team.\n\n"
            f"Happy to send a short CV or jump on a quick call — whatever is easiest.\n\n"
            f"Best,\n{signature}\n"
        )
        return {"subject": subject, "body": body}

    # X / LinkedIn: short, conversational, no subject.
    platform = _CHANNEL_LABELS.get(channel, channel)
    opening = (
        f"Hi {first_name} — saw {company_name} is hiring"
        f"{f' for {jobs_phrase}' if jobs_phrase else ''}."
        if jobs_phrase
        else f"Hi {first_name} — came across {company_name}"
        f"{f' ({one_liner})' if one_liner else ''} and wanted to reach out."
    )
    body = (
        f"{opening} I'm a backend/platform engineer and would love to be considered. "
        f"Happy to share a short CV here on {platform} if you're open to it. Thanks!"
    )
    return {"subject": None, "body": body}


def _recipient(founder: dict[str, Any], channel: str) -> str | None:
    if channel == "email":
        return founder.get("email") or None
    if channel == "x":
        handle = founder.get("x_handle") or ""
        if handle:
            return handle if handle.startswith("@") else f"@{handle}"
        url = founder.get("x_url") or ""
        if url:
            return url.rsplit("/", 1)[-1] or None
        return None
    if channel == "linkedin":
        return founder.get("linkedin_url") or None
    return None


def draft_outreach(
    repository: YCRepository,
    channels: list[str] | None = None,
    keywords: list[str] | None = None,
    batch: str | None = None,
    company_slug: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Create draft messages for founders that have a usable contact."""
    selected = [c for c in (channels or CHANNELS) if c in CHANNELS]
    keywords = keywords or OUTREACH_KEYWORDS

    founders, total = repository.list_founders(
        batch=batch,
        company_slug=company_slug,
        limit=limit,
        offset=0,
    )
    if not founders:
        return {
            "status": "empty",
            "founders_scanned": 0,
            "drafts_created": 0,
            "skipped": 0,
            "by_channel": {channel: 0 for channel in selected},
        }

    company_ids = sorted({int(founder["company_id"]) for founder in founders})
    jobs_by_company = repository.list_company_jobs(company_ids)

    summary: dict[str, Any] = {
        "status": "completed",
        "founders_scanned": len(founders),
        "founders_total": total,
        "drafts_created": 0,
        "skipped": 0,
        "by_channel": {channel: 0 for channel in selected},
    }

    for founder in founders:
        company = {
            "name": founder.get("company_name"),
            "one_liner": founder.get("company_one_liner"),
            "batch": founder.get("company_batch"),
        }
        jobs = jobs_by_company.get(int(founder["company_id"]), [])
        for channel in selected:
            recipient = _recipient(founder, channel)
            if not recipient:
                summary["skipped"] += 1
                continue

            fingerprint = hashlib.sha256(
                f"{founder['id']}:{channel}".encode("utf-8")
            ).hexdigest()

            message = build_message(founder, company, jobs, channel, keywords=keywords)
            created = repository.create_outreach(
                founder_id=int(founder["id"]),
                company_id=int(founder["company_id"]),
                channel=channel,
                recipient=recipient,
                subject=message.get("subject"),
                body=message.get("body") or "",
                fingerprint=fingerprint,
            )
            if created:
                summary["drafts_created"] += 1
                summary["by_channel"][channel] += 1
            else:
                summary["skipped"] += 1

    logger.info("Outreach drafting finished: %s", summary)
    return summary
