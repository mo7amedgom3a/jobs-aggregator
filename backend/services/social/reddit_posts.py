"""Manual Reddit hiring-post collector.

Reddit is read through its public Atom feeds (``/r/<sub>/new/.rss``) because the
unauthenticated JSON endpoints are blocked from many networks. When a Reddit
"script" app is configured (``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET``) the
OAuth JSON API is used instead, which has far higher rate limits and can
authenticate with ``REDDIT_USERNAME`` / ``REDDIT_PASSWORD``.

Like the LinkedIn/X collectors this runs only when triggered from the
frontend, never from the hourly scheduler. Reddit's public rate limit is tight
(~1 request per 10-15 seconds), so the feed list is small and requests are
paced by ``REDDIT_REQUEST_DELAY``.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from config.settings import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_MAX_SUBREDDITS,
    REDDIT_PASSWORD,
    REDDIT_RATE_LIMIT_WAIT,
    REDDIT_REQUEST_DELAY,
    REDDIT_SUBREDDITS,
    REDDIT_TIMEOUT,
    REDDIT_USER_AGENT,
    REDDIT_USERNAME,
    SOCIAL_MAX_POSTS_PER_PLATFORM,
)
from services.social.browser import clean_text

logger = logging.getLogger("job_aggregator.services.social.reddit")

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_BREAK_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_HTML_PARA_RE = re.compile(r"</\s*p\s*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
#: RSS feeds append this boilerplate to every self post.
_SUBMITTED_RE = re.compile(
    r"submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]", re.IGNORECASE
)

#: Posts where the *candidate* is advertising themselves rather than a role.
_FOR_HIRE_RE = re.compile(r"\[\s*(?:for[\s-]*hire|forhire)\s*\]", re.IGNORECASE)

_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0.0}


def _headers() -> dict[str, str]:
    return {
        "User-Agent": REDDIT_USER_AGENT,
        "Accept": "application/atom+xml, application/json;q=0.9, */*;q=0.8",
    }


def _plain_text(markup: str | None) -> str:
    """Convert Reddit's escaped HTML content into readable plain text."""
    if not markup:
        return ""
    text = _HTML_COMMENT_RE.sub(" ", markup)
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_PARA_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _SUBMITTED_RE.sub(" ", text)
    text = html_lib.unescape(text)
    return clean_text(text, 4000)


def _iso(value: str | None) -> str:
    if not value:
        return ""
    candidate = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).astimezone(timezone.utc).isoformat()
    except ValueError:
        return value.strip()


def _posted_epoch(value: str | None) -> float:
    """Sort key for mixed/invalid timestamps (newest first, unknown last)."""
    if not value:
        return 0.0
    candidate = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).timestamp()
    except ValueError:
        return 0.0


def _is_for_hire(title: str, flair: str | None = None) -> bool:
    return bool(_FOR_HIRE_RE.search(title or "") or _FOR_HIRE_RE.search(flair or ""))


def _build_post(
    *,
    subreddit: str,
    title: str,
    body: str,
    author: str,
    permalink: str,
    posted_at: str,
) -> dict[str, Any] | None:
    title = clean_text(title, 400)
    body = _plain_text(body)
    if not title:
        return None

    permalink = permalink or ""
    if permalink.startswith("/"):
        post_url = f"https://www.reddit.com{permalink}"
    elif permalink:
        post_url = permalink
    else:
        post_url = f"https://www.reddit.com/r/{subreddit}/new/"

    author = (author or "").strip()
    if author.startswith("/u/"):
        author = author[3:]
    if author and not author.startswith("u/"):
        author = f"u/{author}"
    if author:
        author = f"{author} · r/{subreddit}"

    return {
        "platform": "reddit",
        "author": author,
        "author_url": (
            f"https://www.reddit.com/user/{author.split(' · ')[0][2:]}/"
            if author
            else ""
        ),
        "text": f"{title}\n\n{body}".strip(),
        "post_url": post_url,
        "posted_at": posted_at,
    }


def parse_reddit_rss(xml_text: str, subreddit: str = "") -> list[dict[str, Any]]:
    """Parse a Reddit Atom feed into raw hiring-post dicts."""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Reddit feed for r/%s was not valid XML", subreddit or "?")
        return []

    posts: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", _ATOM_NS):
        title = entry.findtext("a:title", default="", namespaces=_ATOM_NS)
        if _is_for_hire(title):
            continue

        link = entry.find("a:link", _ATOM_NS)
        permalink = link.get("href", "") if link is not None else ""

        author = entry.findtext("a:author/a:name", default="", namespaces=_ATOM_NS)
        posted = entry.findtext("a:updated", default="", namespaces=_ATOM_NS) or entry.findtext(
            "a:published", default="", namespaces=_ATOM_NS
        )
        body = entry.findtext("a:content", default="", namespaces=_ATOM_NS) or entry.findtext(
            "a:summary", default="", namespaces=_ATOM_NS
        )

        post = _build_post(
            subreddit=subreddit,
            title=title,
            body=body,
            author=author,
            permalink=permalink,
            posted_at=_iso(posted),
        )
        if post:
            posts.append(post)
    return posts


def parse_reddit_json(payload: dict[str, Any], subreddit: str = "") -> list[dict[str, Any]]:
    """Parse an OAuth ``/new`` listing into raw hiring-post dicts."""
    children = ((payload or {}).get("data") or {}).get("children") or []
    posts: list[dict[str, Any]] = []
    for child in children:
        data = (child or {}).get("data") or {}
        if not data or data.get("stickied") or data.get("over_18"):
            continue
        title = str(data.get("title") or "")
        flair = data.get("link_flair_text")
        if _is_for_hire(title, str(flair) if flair else ""):
            continue

        created = data.get("created_utc")
        posted_at = ""
        if created is not None:
            try:
                posted_at = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                posted_at = ""

        body = str(data.get("selftext") or "")
        if not body and data.get("url"):
            body = str(data.get("url") or "")

        post = _build_post(
            subreddit=str(data.get("subreddit") or subreddit),
            title=title,
            body=body,
            author=str(data.get("author") or ""),
            permalink=str(data.get("permalink") or ""),
            posted_at=posted_at,
        )
        if post:
            posts.append(post)
    return posts


def _oauth_token(client: httpx.Client) -> str:
    """Fetch (and cache) an OAuth token using the password grant."""
    now = time.time()
    if _TOKEN_CACHE["token"] and float(_TOKEN_CACHE["expires_at"]) > now + 60:
        return str(_TOKEN_CACHE["token"])

    response = client.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        data={
            "grant_type": "password",
            "username": REDDIT_USERNAME,
            "password": REDDIT_PASSWORD,
        },
        headers={"User-Agent": REDDIT_USER_AGENT},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Reddit OAuth token request failed ({response.status_code}): "
            f"{response.text[:200]}"
        )

    payload = response.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Reddit OAuth response did not include an access_token")

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + float(payload.get("expires_in") or 3600)
    return token


def _uses_oauth() -> bool:
    return bool(
        REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and REDDIT_USERNAME and REDDIT_PASSWORD
    )


def _fetch_subreddit(client: httpx.Client, subreddit: str) -> list[dict[str, Any]]:
    """Fetch one subreddit via OAuth JSON when configured, else the Atom feed."""
    if _uses_oauth():
        try:
            token = _oauth_token(client)
            response = client.get(
                f"https://oauth.reddit.com/r/{subreddit}/new",
                params={"limit": 100, "raw_json": 1},
                headers={
                    "User-Agent": REDDIT_USER_AGENT,
                    "Authorization": f"Bearer {token}",
                },
            )
            if response.status_code == 200:
                return parse_reddit_json(response.json(), subreddit)
            logger.warning(
                "Reddit OAuth feed r/%s returned %s; falling back to public RSS",
                subreddit,
                response.status_code,
            )
        except Exception as exc:  # noqa: BLE001 - fall through to RSS
            logger.warning("Reddit OAuth feed r/%s failed: %s", subreddit, exc)

    response = client.get(
        f"https://www.reddit.com/r/{subreddit}/new/.rss",
        params={"limit": 100},
        headers=_headers(),
        follow_redirects=True,
    )
    if response.status_code == 429:
        logger.warning(
            "Reddit rate-limited r/%s; waiting %.0fs before one retry",
            subreddit,
            REDDIT_RATE_LIMIT_WAIT,
        )
        time.sleep(REDDIT_RATE_LIMIT_WAIT)
        response = client.get(
            f"https://www.reddit.com/r/{subreddit}/new/.rss",
            params={"limit": 100},
            headers=_headers(),
            follow_redirects=True,
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Reddit feed r/{subreddit} returned {response.status_code}"
        )
    return parse_reddit_rss(response.text, subreddit)


def collect_reddit_posts(
    keywords: list[str],
    max_posts: int | None = None,
    countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return raw hiring-post dicts from Reddit's newest tech/hiring feeds.

    ``keywords`` and ``countries`` are accepted for interface parity with the
    other collectors: Reddit feeds are not keyword-scoped, so posts are filtered
    later by the shared hiring/remote/tech/region pipeline.
    """
    limit = max_posts or SOCIAL_MAX_POSTS_PER_PLATFORM
    configured = list(dict.fromkeys(REDDIT_SUBREDDITS))
    cap = max(1, REDDIT_MAX_SUBREDDITS)
    if len(configured) > cap:
        # Always keep r/forhire (the highest-signal board) and rotate the rest
        # daily so every feed is covered without exceeding Reddit's tight
        # public-feed rate limit in a single scan.
        preferred = [sub for sub in configured if sub.lower() == "forhire"]
        rest = [sub for sub in configured if sub.lower() != "forhire"]
        if rest:
            start = datetime.now(timezone.utc).timetuple().tm_yday % len(rest)
            rest = rest[start:] + rest[:start]
        configured = preferred + rest
    subreddits = configured[:cap]
    logger.info("Reddit feeds: %s (keywords=%s, countries=%s)", subreddits, keywords, countries)

    raw_posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    buffer_limit = max(limit * 3, limit)

    with httpx.Client(timeout=REDDIT_TIMEOUT) as client:
        for index, subreddit in enumerate(subreddits):
            if index:
                time.sleep(REDDIT_REQUEST_DELAY)
            try:
                posts = _fetch_subreddit(client, subreddit)
            except Exception as exc:  # noqa: BLE001 - keep scanning other feeds
                logger.warning("Reddit feed r/%s failed: %s", subreddit, exc)
                continue

            logger.info("Reddit r/%s returned %d posts", subreddit, len(posts))
            for post in posts:
                key = (post.get("post_url") or post.get("text", "")[:120]).lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                raw_posts.append(post)
                if len(raw_posts) >= buffer_limit:
                    break
            if len(raw_posts) >= buffer_limit:
                break

    # Newest first: feeds are already ordered, but merging several feeds means
    # we must sort before applying the caller's cap.
    raw_posts.sort(
        key=lambda post: _posted_epoch(post.get("posted_at")),
        reverse=True,
    )
    logger.info("Reddit collected %d raw posts", len(raw_posts))
    return raw_posts[:limit]
