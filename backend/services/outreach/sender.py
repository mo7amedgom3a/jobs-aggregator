"""Send approved outreach messages (email, X DM, LinkedIn DM).

Nothing is ever sent automatically: only rows with ``status='approved'`` are
picked up here. DM channels reuse the persistent Playwright profiles created by
``services.social.browser`` so saved logins survive between runs.
"""

from __future__ import annotations

import logging
import random
import smtplib
import time
from email.message import EmailMessage
from typing import Any

from config.settings import (
    OUTREACH_DM_MAX_DELAY,
    OUTREACH_DM_MIN_DELAY,
    OUTREACH_EMAIL_MAX_PER_RUN,
    OUTREACH_LINKEDIN_MAX_PER_RUN,
    OUTREACH_X_MAX_PER_RUN,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)
from repository.yc import YCRepository

logger = logging.getLogger("job_aggregator.services.outreach.sender")

CHANNEL_LIMITS = {
    "email": OUTREACH_EMAIL_MAX_PER_RUN,
    "x": OUTREACH_X_MAX_PER_RUN,
    "linkedin": OUTREACH_LINKEDIN_MAX_PER_RUN,
}


def _smtp_ready() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


# ─── Email ───────────────────────────────────────────────────────────────────


def send_email(message: dict[str, Any], dry_run: bool = False) -> None:
    body = message.get("body") or ""
    recipient = message.get("recipient") or ""
    subject = message.get("subject") or "Quick intro"
    if dry_run:
        logger.info("[dry-run] email → %s | %s", recipient, subject)
        return
    if not _smtp_ready():
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_FROM (and SMTP_USER/SMTP_PASSWORD) in backend/.env."
        )

    email = EmailMessage()
    email["From"] = SMTP_FROM
    email["To"] = recipient
    email["Subject"] = subject
    email.set_content(body)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(email)


# ─── X DM ────────────────────────────────────────────────────────────────────


def send_x_dm(recipient: str, body: str, dry_run: bool = False) -> None:
    handle = recipient.lstrip("@")
    if dry_run:
        logger.info("[dry-run] X DM → @%s | %s", handle, body[:120])
        return

    from services.social.browser import SocialAuthError, browser_context

    with browser_context("x") as page:
        page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
        if any(part in page.url for part in ("/i/flow/login", "/login", "/i/flow/signup")):
            raise SocialAuthError(
                "X session is not logged in. Open the hiring-posts page and run an X scan once "
                "to establish the saved browser profile."
            )

        button = page.query_selector('[data-testid="sendDMFromProfile"]')
        if button is None:
            button = page.query_selector('button:has-text("Message")')
        if button is None:
            raise RuntimeError(
                f"X DM button not available for @{handle} (the account may not accept messages)."
            )
        button.click()

        composer = page.wait_for_selector(
            '[data-testid="dmComposerTextInput"]', timeout=15000
        )
        composer.click()
        page.keyboard.type(body, delay=15)

        send_button = page.query_selector('[data-testid="dmComposerSendButton"]')
        if send_button is None:
            page.keyboard.press("Enter")
        else:
            send_button.click()
        page.wait_for_timeout(2500)


# ─── LinkedIn DM ─────────────────────────────────────────────────────────────


def send_linkedin_dm(profile_url: str, body: str, dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[dry-run] LinkedIn DM → %s | %s", profile_url, body[:120])
        return

    from services.social.browser import SocialAuthError, browser_context

    with browser_context("linkedin") as page:
        page.goto(profile_url, wait_until="domcontentloaded")
        if any(part in page.url for part in ("/login", "authwall", "/checkpoint")):
            raise SocialAuthError(
                "LinkedIn session is not logged in. Open the hiring-posts page and run a LinkedIn "
                "scan once to establish the saved browser profile."
            )

        button = None
        for selector in (
            "button.message-anywhere-button",
            "a.message-anywhere-button",
            'button[aria-label*="Message"]',
            'main button:has-text("Message")',
        ):
            button = page.query_selector(selector)
            if button is not None:
                break
        if button is None:
            raise RuntimeError(
                f"LinkedIn messaging is not available for {profile_url} "
                "(no Message button — the person may restrict messages)."
            )
        button.click()

        composer = page.wait_for_selector(
            "div.msg-form__contenteditable, div[role='textbox'][contenteditable='true']",
            timeout=15000,
        )
        composer.click()
        page.keyboard.type(body, delay=15)
        page.wait_for_timeout(600)

        send_button = page.query_selector("button.msg-form__send-button")
        if send_button is None:
            page.keyboard.press("Enter")
        else:
            send_button.click()
        page.wait_for_timeout(2500)


# ─── Batch sending ───────────────────────────────────────────────────────────


def _send_one(message: dict[str, Any], dry_run: bool) -> None:
    channel = message.get("channel")
    if channel == "email":
        send_email(message, dry_run=dry_run)
    elif channel == "x":
        if not message.get("x_handle") and not (message.get("recipient") or "").startswith("@"):
            raise RuntimeError("No X handle for this founder.")
        send_x_dm(message.get("recipient") or message.get("x_handle") or "", message.get("body") or "", dry_run=dry_run)
    elif channel == "linkedin":
        send_linkedin_dm(
            message.get("recipient") or message.get("linkedin_url") or "",
            message.get("body") or "",
            dry_run=dry_run,
        )
    else:
        raise RuntimeError(f"Unsupported channel: {channel}")


def send_approved(
    repository: YCRepository,
    channel: str,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send every approved message for ``channel`` (capped by the run limit)."""
    cap = limit or CHANNEL_LIMITS.get(channel, 10)
    messages, _ = repository.list_outreach(
        status="approved",
        channel=channel,
        limit=max(1, cap),
        offset=0,
    )

    summary = {
        "channel": channel,
        "dry_run": dry_run,
        "attempted": 0,
        "sent": 0,
        "failed": 0,
        "errors": [],
    }

    for message in messages:
        summary["attempted"] += 1
        try:
            _send_one(message, dry_run=dry_run)
            repository.update_outreach(
                int(message["id"]),
                status="sent" if not dry_run else "approved",
                error=None,
                sent=not dry_run,
            )
            summary["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - record and continue
            logger.error("Outreach send failed for %s: %s", message.get("id"), exc, exc_info=True)
            repository.update_outreach(
                int(message["id"]),
                status="failed",
                error=str(exc)[:500],
                sent=False,
            )
            summary["failed"] += 1
            summary["errors"].append(str(exc)[:200])

        if channel in {"x", "linkedin"} and not dry_run:
            time.sleep(random.uniform(OUTREACH_DM_MIN_DELAY, OUTREACH_DM_MAX_DELAY))
        elif not dry_run:
            time.sleep(random.uniform(2, 5))

    return summary
