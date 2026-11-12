"""Shared Playwright helpers for the manual social "hiring posts" scrapers.

These collectors are *not* part of the hourly scheduler. They are triggered
explicitly from the frontend (2-3 times per day) and reuse a persistent
browser profile so the LinkedIn/X login survives between runs.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote_plus

from config.settings import (
    SOCIAL_HEADLESS,
    SOCIAL_NAV_TIMEOUT_MS,
    SOCIAL_SESSION_DIR,
)

logger = logging.getLogger("job_aggregator.services.social.browser")


class SocialAuthError(RuntimeError):
    """Raised when a social platform cannot be accessed (missing creds, 2FA...)."""


def profile_dir(platform: str) -> Path:
    path = Path(SOCIAL_SESSION_DIR) / f"{platform}_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def has_saved_profile(platform: str) -> bool:
    """True when a previous run stored a browser profile for the platform."""
    path = Path(SOCIAL_SESSION_DIR) / f"{platform}_profile"
    return path.exists() and any(path.iterdir())


@contextmanager
def browser_context(platform: str, headless: bool | None = None) -> Iterator[Any]:
    """Yield a Playwright page backed by a persistent, per-platform profile."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SocialAuthError(
            "Playwright is not installed. Run `pip install -r requirements.txt` "
            "and `playwright install chromium`."
        ) from exc

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir(platform)),
            headless=SOCIAL_HEADLESS if headless is None else headless,
            viewport={"width": 1400, "height": 1000},
            locale="en-US",
            timezone_id="UTC",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_navigation_timeout(SOCIAL_NAV_TIMEOUT_MS)
            page.set_default_timeout(SOCIAL_NAV_TIMEOUT_MS)
            yield page
        finally:
            try:
                context.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass


def linkedin_search_url(query: str, location: str | None = None) -> str:
    """Build a LinkedIn *posts* (content) search URL limited to the last 24h."""
    base = (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote_plus(query)}"
        '&datePosted=%22past-24h%22'
        '&sortBy=%22date_posted%22'
    )
    if location:
        base += f"&location={quote_plus(location)}"
    return base


def search_url_linkedin(keywords: list[str], location: str | None = None) -> str:
    query = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords) or '"hiring"'
    return linkedin_search_url(query, location=location)


def normalize_relative_date(raw: str | None) -> str | None:
    """Turn LinkedIn-style labels ("2h •", "1d •", "45m") into "2 hours ago"."""
    if not raw:
        return None
    text = raw.replace("•", " ").strip()
    if not text:
        return None
    match = re.search(r"(\d+)\s*(mo|yr|[smhdwy])", text, re.IGNORECASE)
    if not match:
        return text
    amount = match.group(1)
    unit = match.group(2).lower()
    mapping = {
        "s": "seconds",
        "m": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
        "mo": "months",
        "y": "years",
        "yr": "years",
    }
    return f"{amount} {mapping.get(unit, 'days')} ago"


def clean_text(value: str | None, limit: int = 4000) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]
