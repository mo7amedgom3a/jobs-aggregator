from routes.search import flatten_results


def _core(job: dict) -> dict:
    return {k: job[k] for k in ("url", "title", "site") if k in job}


def test_legacy_jobspy_flatten_uses_backend_results() -> None:
    results = {
        "linkedin": [
            {"url": "https://linkedin.com/jobs/view/1", "title": "Backend Engineer"},
            {"url": "https://linkedin.com/jobs/view/1", "title": "Duplicate"},
        ],
        "indeed": [
            {"url": "https://indeed.com/viewjob?jk=2", "title": "Platform Engineer"},
        ],
        "google": [
            {"url": "https://jobs.example.com/3", "title": "Ignored for jobspy route"},
        ],
    }

    flattened = flatten_results(results, max_results=10, sources=["linkedin", "indeed"])

    assert [_core(job) for job in flattened] == [
        {"url": "https://linkedin.com/jobs/view/1", "title": "Backend Engineer", "site": "linkedin"},
        {"url": "https://indeed.com/viewjob?jk=2", "title": "Platform Engineer", "site": "indeed"},
    ]
    # Every job now carries scoring metadata for ranking.
    assert all("score" in job and "verdict" in job for job in flattened)


def test_legacy_jobspy_flatten_respects_limit() -> None:
    results = {
        "linkedin": [{"url": "https://linkedin.com/jobs/view/1", "title": "Backend Engineer"}],
        "indeed": [{"url": "https://indeed.com/viewjob?jk=2", "title": "Platform Engineer"}],
        "google": [],
    }

    flattened = flatten_results(results, max_results=1, sources=["linkedin", "indeed"])

    assert len(flattened) == 1
    assert flattened[0]["url"] == "https://linkedin.com/jobs/view/1"
    assert flattened[0]["site"] == "linkedin"
