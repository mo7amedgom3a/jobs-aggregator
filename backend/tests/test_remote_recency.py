from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from config.settings import SiteConfig
from services.filters import (
    is_within_3_days,
    is_within_window,
    parse_posted_at,
)
from spiders.base import BaseJobSpider


def test_is_within_3_days_relative() -> None:
    # 1. Relative checks (should keep)
    assert is_within_3_days("3 hours ago") is True
    assert is_within_3_days("yesterday") is True
    assert is_within_3_days("2d") is True
    assert is_within_3_days("3 days ago") is True
    assert is_within_3_days("1 minute ago") is True
    assert is_within_3_days("today") is True
    assert is_within_3_days(None) is True  # fail-safe

    # 2. Relative checks (should discard)
    assert is_within_3_days("4 days ago") is False
    assert is_within_3_days("4d") is False
    assert is_within_3_days("2 weeks ago") is False
    assert is_within_3_days("1 month ago") is False
    assert is_within_3_days("1 year ago") is False


def test_is_within_3_days_absolute() -> None:
    now = datetime.now(timezone.utc)

    date_ok = (now - timedelta(days=1, hours=12)).isoformat()
    assert is_within_3_days(date_ok) is True

    date_old = (now - timedelta(days=4)).isoformat()
    assert is_within_3_days(date_old) is False

    ts_ok = str((now - timedelta(days=2)).timestamp())
    assert is_within_3_days(ts_ok) is True

    ts_old = str((now - timedelta(days=5)).timestamp())
    assert is_within_3_days(ts_old) is False


def test_parse_posted_at_variants() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)

    assert parse_posted_at("2 hours ago", now=now) == now - timedelta(hours=2)
    assert parse_posted_at("45m", now=now) == now - timedelta(minutes=45)
    assert parse_posted_at("3d", now=now) == now - timedelta(days=3)
    assert parse_posted_at("2026-11-11T10:00:00Z", now=now) == datetime(
        2026, 11, 11, 10, 0, tzinfo=timezone.utc
    )
    assert parse_posted_at("Nov 11, 2026", now=now) == datetime(
        2026, 11, 11, tzinfo=timezone.utc
    )
    assert parse_posted_at("not a date", now=now) is None
    assert parse_posted_at(None, now=now) is None


def test_hard_24h_window_is_strict_for_unknown_dates() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)

    assert is_within_window("3 hours ago", hours=24, strict=True, now=now) is True
    assert is_within_window("2 days ago", hours=24, strict=True, now=now) is False
    assert is_within_window("", hours=24, strict=True, now=now) is False
    assert is_within_window(None, hours=24, strict=False, now=now) is True


@pytest.mark.asyncio
async def test_base_spider_enforces_24h_window(mocker: Any) -> None:
    cfg = SiteConfig(name="remoteok", start_urls=["http://example.com"])
    mock_save = mocker.patch("spiders.base.save_job", return_value=(True, "fingerprint_123"))

    class DummySpider(BaseJobSpider):
        site_config = cfg

        async def extract_jobs(self, response: Any):
            yield {}

    spider = DummySpider()
    spider._run_id = 1
    spider._items_new = 0
    spider._items_dupe = 0
    spider.logger = mocker.MagicMock()

    # Fresh job (2 hours ago) is kept and saved.
    job_fresh = {"title": "Python Dev", "url": "http://ok.com/1", "location": "Remote", "date_posted": "2 hours ago"}
    assert await spider.on_scraped_item(job_fresh) is not None
    assert mock_save.call_count == 1

    # 2 days old is dropped under the hard 24h policy.
    mock_save.reset_mock()
    job_old = {"title": "Go Dev", "url": "http://ok.com/2", "location": "Remote", "date_posted": "2 days ago"}
    assert await spider.on_scraped_item(job_old) is None
    assert mock_save.call_count == 0

    # Missing date is dropped in strict mode (the default).
    mock_save.reset_mock()
    job_missing = {"title": "React Dev", "url": "http://ok.com/3", "location": "Remote"}
    assert await spider.on_scraped_item(job_missing) is None
    assert mock_save.call_count == 0


@pytest.mark.asyncio
async def test_base_spider_drops_onsite_and_hybrid(mocker: Any) -> None:
    cfg = SiteConfig(name="linkedin", start_urls=["http://example.com"])
    mock_save = mocker.patch("spiders.base.save_job", return_value=(True, "fingerprint_123"))

    class DummySpider(BaseJobSpider):
        site_config = cfg

        async def extract_jobs(self, response: Any):
            yield {}

    spider = DummySpider()
    spider._run_id = 1
    spider._items_new = 0
    spider._items_dupe = 0
    spider.logger = mocker.MagicMock()

    onsite = {
        "title": "Backend Engineer",
        "url": "http://example.com/onsite",
        "location": "Onsite - Berlin",
        "date_posted": "1 hour ago",
    }
    hybrid = {
        "title": "Backend Engineer",
        "url": "http://example.com/hybrid",
        "location": "Hybrid / Remote",
        "date_posted": "1 hour ago",
    }
    remote = {
        "title": "Backend Engineer",
        "url": "http://example.com/remote",
        "location": "Fully Remote",
        "date_posted": "1 hour ago",
    }

    assert await spider.on_scraped_item(onsite) is None
    assert await spider.on_scraped_item(hybrid) is None
    assert await spider.on_scraped_item(remote) is not None
    assert mock_save.call_count == 1


@pytest.mark.asyncio
async def test_base_spider_accepts_strict_override(monkeypatch: Any, mocker: Any) -> None:
    monkeypatch.setattr("config.settings.STRICT_RECENT", False)
    cfg = SiteConfig(name="linkedin", start_urls=["http://example.com"])
    mock_save = mocker.patch("spiders.base.save_job", return_value=(True, "fingerprint_123"))

    class DummySpider(BaseJobSpider):
        site_config = cfg

        async def extract_jobs(self, response: Any):
            yield {}

    spider = DummySpider()
    spider._run_id = 1
    spider._items_new = 0
    spider._items_dupe = 0
    spider.logger = mocker.MagicMock()

    job_missing = {"title": "Staff Engineer", "url": "http://li.com/1", "location": "Remote"}
    assert await spider.on_scraped_item(job_missing) is not None
    assert mock_save.call_count == 1
