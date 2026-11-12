"""Media URL helpers for YC profiles and logos."""

from __future__ import annotations

from urllib.parse import urlsplit

# Bookface serves public (unsigned) avatars from this origin. The URLs embedded
# in company pages are often signed with a 1-hour expiry, so we strip the query
# string and keep the stable object path instead.
PUBLIC_ORIGIN = "https://bookface-images.s3.amazonaws.com"


def public_avatar_url(url: str | None) -> str | None:
    """Return a stable public avatar URL (query string removed)."""
    if not url:
        return None
    value = url.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.path.startswith("/avatars/"):
        return f"{PUBLIC_ORIGIN}{parts.path}"
    # Already public or a different CDN path; keep it as-is.
    return value
