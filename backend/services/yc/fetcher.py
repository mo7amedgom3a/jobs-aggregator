"""Polite HTTP helpers for the YC pipeline.

The public YC directory API and the server-rendered company/founder pages are
fetched through Scrapling's HTTP fetcher so we inherit its browser
impersonation. Requests are throttled globally to keep the crawl polite, and
every request runs under a hard wall-clock timeout so a single hanging site
cannot stall the pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from config.settings import YC_REQUEST_DELAY, YC_REQUEST_TIMEOUT

logger = logging.getLogger("job_aggregator.services.yc.fetcher")

_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_FETCHER: Any = None


class YCRequestTimeout(RuntimeError):
    """Raised when a request exceeds its hard wall-clock timeout."""


def _fetcher() -> Any:
    global _FETCHER
    if _FETCHER is None:
        from scrapling.fetchers import Fetcher

        _FETCHER = Fetcher
    return _FETCHER


def _throttle() -> None:
    global _LAST_REQUEST_AT
    with _LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        wait = YC_REQUEST_DELAY - elapsed
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def response_text(response: Any) -> str:
    body = getattr(response, "body", b"")
    if isinstance(body, str):
        return body
    try:
        return body.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - defensive
        return str(body)


def fetch(url: str, *, headers: dict[str, str] | None = None, timeout: int | None = None) -> Any:
    """Fetch ``url`` with a hard timeout, through Scrapling's impersonated client."""
    effective = timeout or YC_REQUEST_TIMEOUT
    _throttle()

    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            kwargs: dict[str, Any] = {"timeout": effective}
            if headers:
                kwargs["headers"] = headers
            result["response"] = _fetcher().get(url, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - forwarded to the caller
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True, name="yc-fetch")
    thread.start()
    thread.join(effective + 5)
    if thread.is_alive():
        raise YCRequestTimeout(f"Request exceeded {effective}s: {url}")
    if "error" in result:
        raise result["error"]
    return result["response"]


def fetch_json(url: str) -> dict[str, Any]:
    import json

    response = fetch(url, headers={"Accept": "application/json"})
    text = response_text(response)
    status = getattr(response, "status", None)
    if status != 200:
        raise RuntimeError(f"YC API returned HTTP {status} for {url}")
    return json.loads(text)


def text_of(response: Any, selector: str, default: str = "") -> str:
    try:
        value = response.css(f"{selector}::text").get()
    except Exception:  # pragma: no cover - selector safety
        return default
    return " ".join(str(value).split()) if value else default
