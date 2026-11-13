"""Manual X (Twitter) hiring-post collector.

X requires an authenticated session for search. Credentials come from
``backend/.env`` / ``auth-access.txt``. The collector is triggered manually
from the frontend, never by the scheduler.

X now uses a new two-step onboarding login
(``x.com/i/jf/onboarding/web?mode=login``): email/username first, then the
password field becomes visible. Both steps are automated here; a persistent
browser profile keeps the ``auth_token``/``ct0`` cookies between runs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from config.settings import (
    SOCIAL_MAX_POSTS_PER_PLATFORM,
    X_PASSWORD,
    X_USERNAME,
)
from services.social.browser import (
    SocialAuthError,
    browser_context,
    clean_text,
    has_saved_profile,
)

logger = logging.getLogger("job_aggregator.services.social.x")

_HOME_URL = "https://x.com/home"
_LOGIN_URL = "https://x.com/i/flow/login"

_USERNAME_SELECTOR = "input[name='username_or_email'], input[name='text'], input[autocomplete='username']"
_PASSWORD_SELECTOR = "input[name='password'], input[type='password']"
_VERIFY_SELECTOR = "input[data-testid='ocfEnterTextTextInput'], input[name='text']"

_LOGGED_IN_SELECTORS = (
    "[data-testid='AppTabBar_Home_Link'], "
    "[data-testid='SideNav_AccountSwitcher_Button'], "
    "[data-testid='primaryColumn']"
)

_EXTRACT_JS = """
() => {
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('article[data-testid="tweet"]')) {
    const textEl = el.querySelector('[data-testid="tweetText"]');
    const text = textEl ? textEl.innerText : '';
    if (!text || text.length < 20) continue;
    const userName = el.querySelector('[data-testid="User-Name"]');
    let author = '';
    if (userName) {
      const spans = Array.from(new Set(
        Array.from(userName.querySelectorAll('span'))
          .map(s => s.innerText.trim())
          .filter(Boolean)
      )).filter(s => s !== '·' && s !== '•' && s !== '.');
      author = spans.slice(0, 3).join(' ');
    }
    const authorLink = el.querySelector('[data-testid="User-Name"] a[href^="/"]');
    const timeEl = el.querySelector('time');
    const statusLink = el.querySelector('a[href*="/status/"]');
    const key = text.slice(0, 120);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      text: text,
      author: author,
      author_url: authorLink ? new URL(authorLink.getAttribute('href'), location.origin).href : '',
      datetime: timeEl ? timeEl.getAttribute('datetime') : '',
      post_url: statusLink ? new URL(statusLink.getAttribute('href'), location.origin).href : '',
    });
  }
  return out;
}
"""


def _has_auth_cookie(page: Any) -> bool:
    """X uses ``auth_token`` and ``ct0`` cookies for an authenticated session."""
    try:
        names = {
            (cookie.get("name") or "").lower()
            for cookie in page.context.cookies()
            if "x.com" in (cookie.get("domain") or "") or "twitter.com" in (cookie.get("domain") or "")
        }
    except Exception:  # pragma: no cover - browser race
        return False
    return "auth_token" in names


def _is_logged_in(page: Any) -> bool:
    url = (page.url or "").lower()
    if any(marker in url for marker in ("/i/flow/login", "/i/jf/onboarding", "/login")):
        return False
    if _has_auth_cookie(page):
        return True
    try:
        return page.locator(_LOGGED_IN_SELECTORS).count() > 0
    except Exception:
        return False


def _wait_for_authenticated(page: Any, timeout_ms: int = 45000) -> bool:
    for _ in range(max(1, int(timeout_ms / 500))):
        if _has_auth_cookie(page):
            return True
        url = (page.url or "").lower()
        if "/home" in url and _is_logged_in(page):
            return True
        page.wait_for_timeout(500)
    return False


def _handle_verification(page: Any) -> None:
    """X sometimes asks for a phone/email confirmation after the password."""
    verify = page.locator(_VERIFY_SELECTOR)
    if verify.count() == 0:
        return
    field = verify.first
    try:
        if not field.is_visible():
            return
    except Exception:
        return

    logger.warning("X requested an extra verification step")
    if not X_USERNAME:
        raise SocialAuthError("X asked for verification but no username is configured.")

    field.fill(X_USERNAME)
    page.keyboard.press("Enter")
    page.wait_for_timeout(4000)
    # If X still shows a challenge/CAPTCHA, surface a clear error.
    if page.locator(_VERIFY_SELECTOR).count() > 0 and page.locator("iframe[id*='arkose'], iframe[title*='captcha']").count() > 0:
        raise SocialAuthError(
            "X requires CAPTCHA/verification. Run once with SOCIAL_HEADLESS=false and "
            "complete it in the browser window, then retry."
        )


def _login(page: Any) -> None:
    if not X_USERNAME or not X_PASSWORD:
        raise SocialAuthError(
            "X credentials are missing. Add X_USERNAME / X_PASSWORD to backend/.env "
            "or add an `x` section to auth-access.txt."
        )

    page.goto(_LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    # Already redirected to the app because a cookie exists.
    if _has_auth_cookie(page):
        logger.info("X already authenticated via saved session")
        return

    username = page.locator(_USERNAME_SELECTOR).first
    try:
        username.wait_for(state="visible", timeout=20000)
    except Exception as exc:
        raise SocialAuthError(
            "Could not find the X login field. Run once with SOCIAL_HEADLESS=false "
            "and log in manually, then retry."
        ) from exc

    logger.info("Filling X login form for %s", X_USERNAME)
    username.fill(X_USERNAME)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)

    password = page.locator(_PASSWORD_SELECTOR).first
    try:
        password.wait_for(state="visible", timeout=15000)
    except Exception as exc:
        # X sometimes asks for phone/email verification before the password.
        _handle_verification(page)
        try:
            password.wait_for(state="visible", timeout=10000)
        except Exception:
            raise SocialAuthError(
                "X did not show the password field (possible verification/CAPTCHA). "
                "Run once with SOCIAL_HEADLESS=false and log in manually."
            ) from exc

    password.fill(X_PASSWORD)
    page.keyboard.press("Enter")
    page.wait_for_timeout(5000)

    _handle_verification(page)

    if not _wait_for_authenticated(page, timeout_ms=60000):
        raise SocialAuthError(
            "X login did not complete. Verify X_USERNAME/X_PASSWORD, or log in once "
            "manually with SOCIAL_HEADLESS=false (the session is then reused)."
        )
    logger.info("X login succeeded")


def _ensure_session(page: Any) -> None:
    page.goto(_HOME_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    if _is_logged_in(page):
        return
    logger.info("X session missing — logging in")
    _login(page)
    page.goto(_HOME_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    if not _is_logged_in(page):
        raise SocialAuthError("X login did not produce an authenticated session.")


def build_x_queries(
    keywords: list[str],
    countries: list[str] | None = None,
    days_back: int = 1,
    max_queries: int = 6,
) -> list[str]:
    """Build X live-search queries for remote MENA hiring posts.

    X is aggressive about rate-limiting search, so a scan uses a small,
    rotating set of queries: one English hashtag query, one keyword query, and
    a few per-country Arabic hashtag queries (countries rotate daily so every
    MENA country is covered across the week).
    """
    from services.regions import DEFAULT_REGIONS, resolve_regions

    regions = resolve_regions(countries)
    if "middle east" in regions:
        regions = list(DEFAULT_REGIONS)

    english_terms = [
        "Saudi", "Riyadh", "UAE", "Dubai", "Egypt", "Cairo",
        "Qatar", "Doha", "Kuwait", "Bahrain", "Oman", "Jordan", "MENA", "Gulf",
    ]
    english_region = "(" + " OR ".join(english_terms) + ")"

    arabic_by_region = {
        "egypt": "(مصر OR القاهرة)",
        "saudi arabia": "(السعودية OR الرياض OR جدة)",
        "united arab emirates": "(الإمارات OR دبي OR \"أبو ظبي\")",
        "qatar": "(قطر OR الدوحة)",
        "kuwait": "(الكويت)",
        "bahrain": "(البحرين)",
        "oman": "(عمان OR مسقط)",
        "jordan": "(الأردن OR عمان)",
    }

    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    until = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    suffix = f"since:{since} until:{until} -filter:retweets"

    cleaned = [kw.strip() for kw in keywords if str(kw).strip()]

    queries: list[str] = [
        f"(#hiring OR #remotejobs OR #jobs OR hiring) {english_region} {suffix} lang:en",
    ]

    keyword_group = "(" + " OR ".join(
        f'"{kw}"' if " " in kw else kw for kw in (cleaned[:3] or ["engineer", "developer"])
    ) + ")"
    # Global remote hiring posts (useful for MENA candidates; filtered when
    # strict_region=true because they may not mention a MENA country).
    queries.append(
        f"(#remotejobs OR #hiring OR \"work from home\") {keyword_group} "
        f"(remote OR worldwide) {suffix} lang:en"
    )

    if cleaned:
        queries.append(
            f"(#hiring OR #remotejobs OR hiring OR \"job opening\") {keyword_group} "
            f"{english_region} {suffix} lang:en"
        )

    # Arabic remote-job hashtags across MENA.
    queries.append(
        "(#وظائف_عن_بعد OR #عمل_عن_بعد OR \"وظائف عن بعد\" OR \"عمل عن بعد\") "
        "(مصر OR السعودية OR الإمارات OR قطر OR الكويت OR البحرين OR عمان OR الأردن) "
        f"{suffix}"
    )

    # Rotate the per-country queries daily so the small budget covers every MENA
    # country over several scans without tripping X's search limits.
    start = now.timetuple().tm_yday % max(1, len(regions))
    ordered = regions[start:] + regions[:start]
    for region in ordered:
        clause = arabic_by_region.get(region)
        if not clause:
            continue
        queries.append(
            f"(#وظائف OR #توظيف OR وظائف OR توظيف) {clause} {suffix}"
        )
        if len(queries) >= max_queries:
            break

    unique: list[str] = []
    for query in queries:
        if query not in unique:
            unique.append(query)
    return unique[:max_queries]


def build_x_query(keywords: list[str], days_back: int = 1) -> str:
    """Backward-compatible single-query builder."""
    return build_x_queries(keywords, days_back=days_back, max_queries=1)[0]


def collect_x_posts(
    keywords: list[str],
    max_posts: int | None = None,
    countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return raw hiring-post dicts from X live search."""
    limit = max_posts or SOCIAL_MAX_POSTS_PER_PLATFORM
    queries = build_x_queries(keywords, countries)
    logger.info("X queries: %s", queries)

    raw_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    with browser_context("x") as page:
        _ensure_session(page)

        for query in queries:
            url = f"https://x.com/search?q={quote(query, safe='')}&f=live"
            logger.info("X post search: %s", url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            if "/i/flow/login" in page.url or "/i/jf/onboarding" in page.url:
                _ensure_session(page)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                if "/i/flow/login" in page.url or "/i/jf/onboarding" in page.url:
                    raise SocialAuthError("X redirected to login while searching.")

            for _ in range(4):
                page.mouse.wheel(0, 2600)
                page.wait_for_timeout(1300)

            page_items = page.evaluate(_EXTRACT_JS) or []
            logger.info("Query %r extracted %d tweets", query[:60], len(page_items))

            for item in page_items:
                text = clean_text(item.get("text"))
                if not text:
                    continue
                key = (item.get("post_url") or text[:120]).lower()
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                item["text"] = text
                raw_items.append(item)

            if len(raw_items) >= limit:
                break

    posts: list[dict[str, Any]] = []
    for item in raw_items:
        posts.append(
            {
                "platform": "x",
                "author": clean_text(item.get("author"), 200),
                "author_url": item.get("author_url") or "",
                "text": item.get("text", ""),
                "post_url": item.get("post_url") or "",
                "posted_at": item.get("datetime") or "",
            }
        )
        if len(posts) >= limit:
            break

    logger.info(
        "X collected %d raw posts (queries=%d, session=%s)",
        len(posts),
        len(queries),
        has_saved_profile("x"),
    )
    return posts
