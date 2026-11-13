"""Interactive browser sessions for social logins.

The LinkedIn/X collectors drive a persistent Playwright profile stored under
``backend/.sessions/<platform>_profile``. When a platform signs the session out
or asks for a security check (CAPTCHA, 2FA, "verify it's you"), the user can
open a visible browser that uses the *same* profile from the Hiring Posts page.
Completing the login there persists the cookies, so the next scan reuses them.

Only one browser window per platform can run at once (Chromium locks the
profile directory). A scan cannot start while a browser window is open.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from config.settings import SOCIAL_BROWSER_TIMEOUT
from services.social.browser import browser_context

logger = logging.getLogger("job_aggregator.services.social.session")

#: Where each platform lands when opened interactively.
PLATFORM_URLS: dict[str, str] = {
    "linkedin": "https://www.linkedin.com/feed/",
    "x": "https://x.com/home",
    "reddit": "https://www.reddit.com/",
}

_LOCK = threading.RLock()
_SESSIONS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set(platform: str, **values: Any) -> None:
    with _LOCK:
        current = _SESSIONS.setdefault(
            platform,
            {
                "platform": platform,
                "running": False,
                "started_at": None,
                "finished_at": None,
                "url": "",
                "error": None,
                "timed_out": False,
            },
        )
        current.update(values)


def session_state() -> dict[str, dict[str, Any]]:
    """Snapshot of every interactive browser session."""
    with _LOCK:
        return {name: dict(state) for name, state in _SESSIONS.items()}


def any_session_running() -> bool:
    with _LOCK:
        return any(state.get("running") for state in _SESSIONS.values())


def is_session_running(platform: str) -> bool:
    with _LOCK:
        return bool(_SESSIONS.get((platform or "").lower(), {}).get("running"))


def _run_session(platform: str, url: str) -> None:
    deadline = time.time() + max(5, SOCIAL_BROWSER_TIMEOUT)
    try:
        # Always headed: the whole point is letting the user interact.
        with browser_context(platform, headless=False) as page:
            _set(platform, running=True, started_at=_now(), url=url, error=None, timed_out=False)
            page.goto(url, wait_until="domcontentloaded")
            _set(platform, url=page.url or url)
            logger.info("Interactive %s browser opened at %s", platform, url)

            while time.time() < deadline:
                try:
                    if page.is_closed():
                        break
                except Exception:  # noqa: BLE001 - window/browser already gone
                    break
                try:
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001
                    break
            else:
                logger.info("Interactive %s browser hit the timeout", platform)
                _set(platform, timed_out=True)
    except Exception as exc:  # noqa: BLE001 - surface failure to the UI
        logger.error("Interactive %s browser failed: %s", platform, exc, exc_info=True)
        _set(platform, error=str(exc))
    finally:
        _set(platform, running=False, finished_at=_now())
        logger.info("Interactive %s browser closed", platform)


def open_session(platform: str, url: str | None = None) -> dict[str, Any]:
    """Launch a headed browser with the platform's persisted profile."""
    platform = (platform or "").strip().lower()
    if platform not in PLATFORM_URLS:
        raise ValueError(
            f"Unsupported platform '{platform}'. Choose one of: {', '.join(PLATFORM_URLS)}."
        )

    target = (url or "").strip() or PLATFORM_URLS[platform]

    from services.social.collector import run_state

    if run_state().get("running"):
        return {
            "status": "error",
            "platform": platform,
            "message": (
                "A social scan is running. Wait for it to finish before opening a "
                "login browser."
            ),
        }

    with _LOCK:
        if _SESSIONS.get(platform, {}).get("running"):
            return {
                "status": "already_running",
                "platform": platform,
                "message": (
                    f"A {platform} browser window is already open. Finish the login "
                    "and close the window before opening another one."
                ),
            }
        _SESSIONS[platform] = {
            "platform": platform,
            "running": True,
            "started_at": _now(),
            "finished_at": None,
            "url": target,
            "error": None,
            "timed_out": False,
        }

    thread = threading.Thread(
        target=_run_session,
        args=(platform, target),
        name=f"social-session-{platform}",
        daemon=True,
    )
    thread.start()

    return {
        "status": "opened",
        "platform": platform,
        "message": (
            f"Opening the {platform} browser. Complete any login/security check and "
            "close the window when you are done — the session is saved for the next scan."
        ),
    }
