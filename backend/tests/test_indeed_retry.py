import logging

import pytest

from config.settings import SiteConfig
from spiders.base import BaseJobSpider
from spiders.job_spiders import IndeedSpider, _with_fromage
from scrapling.spiders import Request


class _EmptySelector:
    def get(self, default=None):
        return default


class _FakeResponse:
    def __init__(self, url: str) -> None:
        self.url = url

    def css(self, selector: str):
        return _EmptySelector()


class _NoJobsSpider(IndeedSpider):
    async def extract_jobs(self, response):
        return
        yield  # pragma: no cover - makes this an async generator


def _prepare_spider() -> _NoJobsSpider:
    spider = _NoJobsSpider()
    spider.site_config = SiteConfig(
        name="indeed_test",
        start_urls=["https://sa.indeed.com/jobs"],
        max_pages=1,
        fetcher="stealth",
        extra_fetch_kwargs={},
    )
    spider._page_counts = {}
    spider._items_new = 0
    spider._items_dupe = 0
    spider.logger = logging.getLogger("test.indeed.retry")
    spider._expanded_retry_done = False
    return spider


def test_with_fromage_replaces_window_and_drops_vjk() -> None:
    url = "https://sa.indeed.com/jobs?q=devops&l=&fromage=1&limit=50&vjk=abc"
    retry = _with_fromage(url, 2)

    assert "fromage=2" in retry
    assert "fromage=1" not in retry
    assert "vjk" not in retry


@pytest.mark.asyncio
async def test_indeed_retries_with_48h_when_24h_pass_is_empty() -> None:
    spider = _prepare_spider()
    response = _FakeResponse("https://sa.indeed.com/jobs?q=devops&fromage=1&limit=50")

    results = [item async for item in spider.parse(response)]

    requests = [item for item in results if isinstance(item, Request)]
    assert len(requests) == 1
    assert "fromage=2" in requests[0].url


@pytest.mark.asyncio
async def test_indeed_does_not_retry_when_jobs_were_saved() -> None:
    spider = _prepare_spider()

    async def _fake_super_parse(self, response):
        # Simulate the base parser saving one job.
        spider._items_new += 1
        if False:
            yield None

    import spiders.job_spiders as job_spiders

    original = BaseJobSpider.parse
    try:
        BaseJobSpider.parse = _fake_super_parse  # type: ignore[assignment]
        response = _FakeResponse("https://sa.indeed.com/jobs?q=devops&fromage=1&limit=50")
        results = [item async for item in spider.parse(response)]
    finally:
        BaseJobSpider.parse = original  # type: ignore[assignment]

    assert not [item for item in results if isinstance(item, Request)]


@pytest.mark.asyncio
async def test_indeed_does_not_retry_on_a_48h_request() -> None:
    spider = _prepare_spider()
    response = _FakeResponse("https://sa.indeed.com/jobs?q=devops&fromage=2&limit=50")

    results = [item async for item in spider.parse(response)]

    assert not [item for item in results if isinstance(item, Request)]
