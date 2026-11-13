from config.settings import INDEED_KEYWORDS, KEYWORDS
from models.job import SearchRequest
from services.orchestrator import JobOrchestrator
from spiders.job_spiders import ALL_SPIDERS


def _orchestrator() -> JobOrchestrator:
    return JobOrchestrator.__new__(JobOrchestrator)


def test_indeed_query_uses_focused_keywords_by_default() -> None:
    env = _orchestrator()._build_env_overrides(
        SearchRequest(countries=["saudi arabia"]), KEYWORDS
    )
    query = env["INDEED_QUERY"]
    terms = [term.strip().strip('"') for term in query.split(" OR ")]

    assert "software engineer" in query
    assert "devops" in query
    # Indeed returns an empty page for quoted phrases / long OR chains.
    assert '"' not in query
    assert len(terms) <= 4
    # The bare terms that pulled in teachers/HSE/civil roles are gone.
    assert " OR Engineer" not in query
    assert " OR AI" not in query
    assert " OR API" not in query


def test_indeed_query_keeps_explicit_user_keywords() -> None:
    env = _orchestrator()._build_env_overrides(
        SearchRequest(countries=["egypt"], keywords=["devops", "python"]),
        ["devops", "python"],
    )

    assert env["INDEED_QUERY"] == "devops OR python"


def test_indeed_remote_spider_is_registered() -> None:
    spider = ALL_SPIDERS["indeed_remote"]
    assert spider.site_config.start_urls == ["https://www.indeed.com/jobs?l=Remote"]
    assert spider.site_config.fetcher == "stealth"
    assert spider.source_recent_filter is True


def test_indeed_remote_results_are_grouped_as_remote() -> None:
    from routes.search import resolve_country

    assert (
        resolve_country(
            {
                "source": "indeed_remote",
                "location": "Remote in Boston, MA",
                "tags": "Remote",
            }
        )
        == "Remote"
    )
