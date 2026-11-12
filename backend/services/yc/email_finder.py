"""Email discovery for YC companies and founders.

Emails are never guaranteed on YC profile pages, so we look in three places:

1. ``mailto:`` links rendered on the YC company page (usually from the launch
   post, e.g. ``founders@akkari.io``) — highest confidence.
2. Public company website pages (homepage, /contact, /about) — verified.
3. Common role-based patterns on the company domain — guessed, flagged so the
   review queue can treat them cautiously.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from config.settings import YC_MAX_WEBSITE_PAGES, YC_WEBSITE_TIMEOUT
from services.yc.fetcher import fetch, response_text

logger = logging.getLogger("job_aggregator.services.yc.email_finder")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Asset filenames, tracking vendors, and documentation placeholders.
_NOISE_DOMAINS = {
    "example.com",
    "example.org",
    "domain.com",
    "yourdomain.com",
    "yourcompany.com",
    "yourteam.com",
    "your-site.com",
    "mydomain.com",
    "company.com",
    "acme.com",
    "email.com",
    "sentry.io",
    "sentry-next.wixpress.com",
    "wixpress.com",
    "sentry.wixpress.com",
    "2x.png",
    "3x.png",
    "support.sentry.io",
    "ycombinator.com",
    "localhost",
}
_NOISE_LOCAL_PARTS = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "postmaster",
    "webmaster",
    "abuse",
    "privacy",
    "legal",
    "unsubscribe",
    "wordpress",
    "sentry",
    "user",
    "your",
    "you",
    "youremail",
    "your-email",
    "email",
    "name",
    "username",
    "test",
    "someone",
}

# Preferred inboxes for founder outreach, in order.
_PREFERRED_LOCAL_PARTS = [
    "founders",
    "founder",
    "hello",
    "hi",
    "team",
    "contact",
    "careers",
    "jobs",
    "info",
    "ceo",
]


def _is_noise(email: str) -> bool:
    lowered = email.lower().strip(".,;:()<>\"'")
    if lowered.count("@") != 1:
        return True
    local, _, domain = lowered.partition("@")
    if not local or not domain:
        return True
    if domain in _NOISE_DOMAINS or any(domain.endswith(f".{d}") for d in _NOISE_DOMAINS):
        return True
    if local in _NOISE_LOCAL_PARTS:
        return True
    if any(lowered.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")):
        return True
    if "u003" in lowered or "%" in lowered:
        return True
    return False


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for match in EMAIL_RE.findall(text or ""):
        candidate = match.strip(".,;:()<>\"'")
        if not _is_noise(candidate) and candidate.lower() not in {e.lower() for e in found}:
            found.append(candidate)
    return found


def emails_from_response(response: Any) -> list[str]:
    """Collect mailto links plus any email literals in the page HTML."""
    emails: list[str] = []
    try:
        for href in response.css('a[href^="mailto:"]::attr(href)').getall():
            address = href.split(":", 1)[1].split("?", 1)[0]
            for email in extract_emails(address):
                if email.lower() not in {e.lower() for e in emails}:
                    emails.append(email)
    except Exception:  # pragma: no cover - selector safety
        pass
    for email in extract_emails(response_text(response)):
        if email.lower() not in {e.lower() for e in emails}:
            emails.append(email)
    return emails


def _rank(email: str) -> tuple[int, int]:
    local = email.split("@", 1)[0].lower()
    try:
        preference = _PREFERRED_LOCAL_PARTS.index(local)
    except ValueError:
        preference = len(_PREFERRED_LOCAL_PARTS)
    return (preference, len(email))


def _best(emails: list[str]) -> str | None:
    filtered = [e for e in emails if not _is_noise(e)]
    if not filtered:
        return None
    return sorted(filtered, key=_rank)[0]


def _website_pages(website: str) -> list[str]:
    if not website:
        return []
    parts = urlsplit(website)
    if not parts.scheme or not parts.netloc:
        return []
    base = f"{parts.scheme}://{parts.netloc}"
    candidates = [website, urljoin(base, "/contact"), urljoin(base, "/about"), urljoin(base, "/careers")]
    seen: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.append(url)
    return seen[: max(1, YC_MAX_WEBSITE_PAGES)]


def _host(value: str | None) -> str:
    if not value:
        return ""
    netloc = urlsplit(value).netloc.lower()
    return netloc.removeprefix("www.")


def _matches_host(email: str, host: str) -> bool:
    """True when the email domain belongs to the company's website host."""
    if not host:
        return False
    domain = email.split("@", 1)[-1].lower()
    return domain == host or host.endswith(f".{domain}") or domain.endswith(f".{host}")


def discover_company_email(
    company_response: Any,
    website: str | None,
    extra_text: str = "",
) -> dict[str, str | None]:
    """Return ``{email, source, confidence}`` for a company.

    ``source`` is one of ``company_page``, ``website`` or ``pattern_guess``.
    ``extra_text`` carries launch-post content extracted from the Inertia props.
    """
    if company_response is not None:
        page_emails = emails_from_response(company_response)
        if extra_text:
            for email in extract_emails(extra_text):
                if email.lower() not in {e.lower() for e in page_emails}:
                    page_emails.append(email)
        best = _best(page_emails)
        if best:
            return {"email": best, "source": "company_page", "confidence": "verified"}

    for url in _website_pages(website or ""):
        try:
            response = fetch(url, timeout=YC_WEBSITE_TIMEOUT)
            if getattr(response, "status", None) != 200:
                continue
            host = _host(url)
            candidates = [e for e in emails_from_response(response) if _matches_host(e, host)]
            best = _best(candidates)
            if best:
                return {"email": best, "source": f"website:{url}", "confidence": "verified"}
        except Exception as exc:  # noqa: BLE001 - website may block or be down
            logger.debug("Website email lookup failed for %s: %s", url, exc)

    guessed = guess_company_email(website)
    if guessed:
        return {"email": guessed, "source": "pattern_guess", "confidence": "guessed"}
    return {"email": None, "source": None, "confidence": None}


def guess_company_email(website: str | None) -> str | None:
    """Guess a role inbox from the company domain (never called when disabled)."""
    from config.settings import YC_EMAIL_PATTERN_GUESS

    if not YC_EMAIL_PATTERN_GUESS or not website:
        return None
    parts = urlsplit(website)
    domain = (parts.netloc or "").lower().removeprefix("www.")
    if not domain or "." not in domain:
        return None
    for local in ("founders", "hello", "team"):
        candidate = f"{local}@{domain}"
        if not _is_noise(candidate):
            return candidate
    return None
