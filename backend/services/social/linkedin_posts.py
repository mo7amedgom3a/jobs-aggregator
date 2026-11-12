"""Manual LinkedIn hiring-post collector.

Logs in with the credentials from ``backend/.env`` / ``auth-access.txt`` and
scrapes the *content* search (posts) for hiring phrases inside the last 24
hours. Triggered from the frontend only.

Login handling notes:
- A persistent Chromium profile keeps the ``li_at`` cookie between runs.
- Navigating to ``/login`` while already authenticated redirects to ``/feed``;
  that is treated as a successful session instead of waiting for ``#username``.
"""

from __future__ import annotations

import logging
from typing import Any

from config.settings import (
    LINKEDIN_EMAIL,
    LINKEDIN_PASSWORD,
    SOCIAL_MAX_POSTS_PER_PLATFORM,
    SOCIAL_NAV_TIMEOUT_MS,
)
from services.social.browser import (
    SocialAuthError,
    browser_context,
    clean_text,
    has_saved_profile,
    linkedin_search_url,
    normalize_relative_date,
)

logger = logging.getLogger("job_aggregator.services.social.linkedin")

_LOGIN_URL = "https://www.linkedin.com/login"
_FEED_URL = "https://www.linkedin.com/feed/"

_AUTH_WALL_MARKERS = (
    "/login",
    "/checkpoint",
    "/authwall",
    "/uas/login",
    "/signup",
)

_USERNAME_SELECTOR = (
    "#username, input[name='session_key'], "
    "input[autocomplete='username'], input[name='email']"
)
_PASSWORD_SELECTOR = (
    "#password, input[name='session_password'], "
    "input[autocomplete='current-password'], input[type='password']"
)
_SUBMIT_SELECTOR = (
    "button[type='submit'], "
    "button[data-litms-control-urn*='login-submit'], "
    "button[aria-label='Sign in'], "
    "form button"
)

_LOGGED_IN_SELECTORS = (
    "div.feed-shared-update-v2, "
    "img.global-nav__me-photo, "
    "button.global-nav__primary-link-me-menu-trigger, "
    "nav.global-nav, "
    "[data-test-global-nav]"
)

_EXTRACT_JS = """
() => {
  const anchors = (el) => Array.from(el.querySelectorAll('a[href]'));
  const isProfile = (href) => /\\/(in|company|school)\\//.test(href || '');
  const abs = (href) => {
    try { return new URL(href, location.origin).href; } catch (e) { return ''; }
  };

  const results = [];
  const seen = new Set();

  for (const el of document.querySelectorAll('main [role="listitem"]')) {
    // Ignore nested list items (e.g. comment threads) if any.
    if (el.parentElement && el.parentElement.closest('[role="listitem"]')) continue;

    const links = anchors(el);
    const profileLink = links.find((a) => isProfile(a.getAttribute('href')) && (a.innerText || '').trim().length > 0);
    const author = profileLink ? (profileLink.innerText || '').split('\\n')[0].trim() : '';
    const authorUrl = profileLink ? abs(profileLink.getAttribute('href')) : '';

    const permalink = links
      .map((a) => a.getAttribute('href'))
      .find((h) => h && (/\\/feed\\/update\\//.test(h) || /\\/posts\\//.test(h) || /activity/.test(h)));

    const lines = (el.innerText || '')
      .split('\\n')
      .map((s) => s.trim())
      .filter(Boolean);

    // Timestamp line in the new SDUI is a bare relative label: 22m / 1h / 3d / 2w / 5mo,
    // optionally followed by "• Edited".
    const tsRegex = /^(\\d+)\\s*(mo|yr|[smhdwy])(\\s*[•·].*)?$/i;
    const tsIdx = lines.findIndex((l) => tsRegex.test(l));
    const timestamp = tsIdx >= 0 ? lines[tsIdx] : '';

    const followIdx = lines.findIndex((l) => l.toLowerCase() === 'follow');
    let start = 0;
    if (tsIdx >= 0) start = tsIdx + 1;
    if (followIdx >= 0) start = Math.max(start, followIdx + 1);

    const stopMarkers = new Set([
      '… more', '... more', 'see more', 'show less',
      'like', 'comment', 'repost', 'send', 'follow',
      'reaction button state: no reaction',
    ]);
    let bodyLines = start > 0 ? lines.slice(start) : lines.slice();
    // Drop the leading "Feed post" / author header duplicates.
    bodyLines = bodyLines.filter((l) => l !== 'Feed post' && l !== 'Promoted' && l !== author);
    const stopIdx = bodyLines.findIndex((l) => stopMarkers.has(l.toLowerCase()));
    if (stopIdx >= 0) bodyLines = bodyLines.slice(0, stopIdx);

    let text = bodyLines.join('\\n').trim();
    if (text.length < 20) continue;
    const key = text.slice(0, 120);
    if (seen.has(key)) continue;
    seen.add(key);

    results.push({
      author: author,
      author_url: authorUrl,
      text: text,
      meta: timestamp,
      datetime: '',
      post_url: permalink ? abs(permalink) : '',
    });
  }
  return results;
}
"""


def _has_auth_cookie(page: Any) -> bool:
    """A ``li_at`` cookie on linkedin.com means the session is authenticated."""
    try:
        for cookie in page.context.cookies():
            name = (cookie.get("name") or "").lower()
            domain = (cookie.get("domain") or "").lower()
            if name == "li_at" and "linkedin.com" in domain:
                return True
    except Exception:  # pragma: no cover - browser race
        return False
    return False


def _is_logged_in(page: Any) -> bool:
    url = (page.url or "").lower()
    if any(marker in url for marker in _AUTH_WALL_MARKERS):
        return False
    if _has_auth_cookie(page):
        return True
    try:
        return page.locator(_LOGGED_IN_SELECTORS).count() > 0
    except Exception:
        return False


def _wait_for_network(page: Any, timeout_ms: int = 8000) -> None:
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # LinkedIn keeps long-poll connections open; not fatal.
        pass


def _dismiss_dialogs(page: Any) -> None:
    """Close cookie/consent overlays that can cover the login form."""
    for selector in (
        "button[action-type='ACCEPT']",
        "button[aria-label='Accept']",
        "button[aria-label='Dismiss']",
        "button:has-text('Accept')",
        "button:has-text('Got it')",
        "button.modal__dismiss",
    ):
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=2000)
                page.wait_for_timeout(500)
        except Exception:
            continue


def _wait_for_authenticated(page: Any, timeout_ms: int = 30000) -> bool:
    """Poll until the li_at cookie appears or we land on the feed."""
    deadline = max(1, int(timeout_ms / 500))
    for _ in range(deadline):
        url = (page.url or "").lower()
        if "/checkpoint" in url or "/challenge" in url:
            return False
        if _has_auth_cookie(page):
            return True
        if "/feed" in url and _is_logged_in(page):
            return True
        page.wait_for_timeout(500)
    return False


def _submit_credentials(page: Any) -> None:
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        raise SocialAuthError(
            "LinkedIn credentials are missing. Set LINKEDIN_EMAIL / LINKEDIN_PASSWORD "
            "in backend/.env or add them to auth-access.txt."
        )

    # If LinkedIn already redirected to the feed (valid cookie), we're done.
    if _has_auth_cookie(page) or "/feed" in (page.url or "").lower():
        logger.info("LinkedIn already authenticated via saved session")
        return

    username = page.locator(_USERNAME_SELECTOR).first
    try:
        username.wait_for(state="visible", timeout=15000)
    except Exception as exc:
        if _has_auth_cookie(page):
            logger.info("LinkedIn authenticated without a login form")
            return
        raise SocialAuthError(
            "Could not find the LinkedIn login form (likely redirected or blocked). "
            "Run once with SOCIAL_HEADLESS=false and log in manually."
        ) from exc

    logger.info("Filling LinkedIn login form for %s", LINKEDIN_EMAIL)
    username.fill(LINKEDIN_EMAIL)

    password = page.locator(_PASSWORD_SELECTOR).first
    try:
        password.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        # LinkedIn sometimes shows the password step after submitting the email.
        try:
            page.keyboard.press("Enter")
            password.wait_for(state="visible", timeout=10000)
        except Exception:
            raise SocialAuthError(
                "LinkedIn did not show the password field. Complete the login "
                "manually once (SOCIAL_HEADLESS=false) and retry."
            ) from exc

    password.fill(LINKEDIN_PASSWORD)

    submit = page.locator(_SUBMIT_SELECTOR).first
    if submit.count() > 0:
        submit.click()
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(3000)

    url = (page.url or "").lower()
    if "/checkpoint" in url or "/challenge" in url:
        raise SocialAuthError(
            "LinkedIn requires additional verification (checkpoint/CAPTCHA). "
            "A browser window is open — complete the check there, then retry the scan."
        )
    if not _wait_for_authenticated(page, SOCIAL_NAV_TIMEOUT_MS):
        raise SocialAuthError(
            "LinkedIn login did not complete. Check the credentials in auth-access.txt "
            "or complete a one-time manual login with SOCIAL_HEADLESS=false."
        )
    logger.info("LinkedIn login succeeded")


def _ensure_session(page: Any) -> None:
    page.goto(_FEED_URL, wait_until="domcontentloaded")
    _wait_for_network(page)
    _dismiss_dialogs(page)

    if _is_logged_in(page):
        logger.info("LinkedIn session restored from saved profile")
        return

    logger.info("LinkedIn session missing — starting automated login")
    page.goto(_LOGIN_URL, wait_until="domcontentloaded")
    _wait_for_network(page)
    _dismiss_dialogs(page)
    _submit_credentials(page)

    page.goto(_FEED_URL, wait_until="domcontentloaded")
    _wait_for_network(page)
    if not _is_logged_in(page):
        raise SocialAuthError("LinkedIn login did not produce an authenticated session.")


def build_linkedin_queries(
    keywords: list[str],
    max_queries: int = 4,
) -> list[str]:
    """Build several content-search queries that reliably return hiring posts.

    LinkedIn returns "No results found" for a bare ``hiring`` query, so each
    query combines a hiring phrase with a concrete keyword.
    """
    phrases = ["hiring", '"we are hiring"', "job opening"]
    cleaned = [kw.strip() for kw in keywords if str(kw).strip()]

    queries: list[str] = []
    for keyword in cleaned[:2]:
        target = f'"{keyword}"' if " " in keyword else keyword
        for phrase in phrases:
            # Always include "remote" so the collected posts match the remote-only policy.
            queries.append(f"{phrase} {target} remote")

    if not queries:
        queries = [
            "hiring engineer remote",
            '"we are hiring" engineer remote',
            "job opening developer remote",
        ]

    # Deduplicate while preserving order, then cap the number of searches.
    unique: list[str] = []
    for query in queries:
        if query not in unique:
            unique.append(query)
    return unique[:max_queries]


def collect_linkedin_posts(
    keywords: list[str],
    max_posts: int | None = None,
    location: str | None = None,
) -> list[dict[str, Any]]:
    """Return raw hiring-post dicts from LinkedIn content search."""
    limit = max_posts or SOCIAL_MAX_POSTS_PER_PLATFORM
    queries = build_linkedin_queries(keywords)
    logger.info("LinkedIn queries: %s", queries)

    raw_items: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    with browser_context("linkedin") as page:
        _ensure_session(page)

        for query in queries:
            url = linkedin_search_url(query, location=location)
            logger.info("LinkedIn post search: %s", url)
            page.goto(url, wait_until="domcontentloaded")
            _wait_for_network(page, timeout_ms=10000)

            current_url = (page.url or "").lower()
            if any(marker in current_url for marker in ("/checkpoint", "/challenge")):
                raise SocialAuthError(
                    "LinkedIn checkpoint while searching. Complete it manually once."
                )
            if "/authwall" in current_url or "/login" in current_url:
                _ensure_session(page)
                page.goto(url, wait_until="domcontentloaded")
                _wait_for_network(page, timeout_ms=10000)
                if "/authwall" in (page.url or "").lower() or "/login" in (page.url or "").lower():
                    raise SocialAuthError(
                        "LinkedIn shows the auth wall for post search. Complete a manual "
                        "login once with SOCIAL_HEADLESS=false and retry."
                    )

            # Scroll to load more results.
            for _ in range(5):
                page.mouse.wheel(0, 2600)
                page.wait_for_timeout(1100)

            page_items = page.evaluate(_EXTRACT_JS) or []
            logger.info("Query %r extracted %d cards", query, len(page_items))

            for item in page_items:
                text = clean_text(item.get("text"))
                if not text:
                    continue
                key = text[:120].lower()
                if key in seen_texts:
                    continue
                seen_texts.add(key)
                item["text"] = text
                raw_items.append(item)

            if len(raw_items) >= limit:
                break

    posts: list[dict[str, Any]] = []
    for item in raw_items:
        posted_at = item.get("datetime") or normalize_relative_date(item.get("meta"))
        posts.append(
            {
                "platform": "linkedin",
                "author": clean_text(item.get("author"), 200),
                "author_url": item.get("author_url") or "",
                "text": item.get("text", ""),
                # New LinkedIn SDUI does not expose a permalink; fall back to the
                # author profile, then to the search page.
                "post_url": item.get("post_url") or item.get("author_url") or "",
                "posted_at": posted_at,
            }
        )
        if len(posts) >= limit:
            break

    logger.info(
        "LinkedIn collected %d raw posts (queries=%d, session=%s)",
        len(posts),
        len(queries),
        has_saved_profile("linkedin"),
    )
    return posts
