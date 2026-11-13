from datetime import datetime, timedelta, timezone

from services.social import collector


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def init_schema(self) -> None:
        return None

    def save_hiring_post(self, post: dict):
        self.saved.append(post)
        return True, "fp"


def test_collector_filters_hiring_intent_and_recency(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fake_repo = FakeRepository()
    monkeypatch.setattr(collector, "JobRepository", lambda: fake_repo)

    fresh_hiring = {
        "platform": "linkedin",
        "author": "Jane Recruiter",
        "text": "We are hiring a Senior Backend Engineer for a fully remote role. Send your CV.",
        "post_url": "https://linkedin.com/posts/jane-1",
        "posted_at": (now - timedelta(hours=2)).isoformat(),
    }
    stale_hiring = {
        "platform": "linkedin",
        "author": "Old Poster",
        "text": "We are hiring a DevOps Engineer. Remote position.",
        "post_url": "https://linkedin.com/posts/old-1",
        "posted_at": (now - timedelta(days=3)).isoformat(),
    }
    not_hiring = {
        "platform": "linkedin",
        "author": "Chatty",
        "text": "Had a great coffee this morning, sharing some thoughts about life.",
        "post_url": "https://linkedin.com/posts/chatty-1",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    no_date = {
        "platform": "linkedin",
        "author": "No Date",
        "text": "We are hiring a Frontend Engineer. Remote.",
        "post_url": "https://linkedin.com/posts/nodate-1",
        "posted_at": "",
    }
    onsite_hiring = {
        "platform": "linkedin",
        "author": "Office Recruiter",
        "text": "We are hiring a Backend Engineer. Onsite in Dubai, no remote.",
        "post_url": "https://linkedin.com/posts/onsite-1",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }

    monkeypatch.setitem(
        collector.COLLECTORS,
        "linkedin",
        lambda keywords, max_posts=None, location=None, countries=None: [
            fresh_hiring,
            stale_hiring,
            not_hiring,
            no_date,
            onsite_hiring,
        ],
    )

    summary = collector.collect_social_posts(keywords=["backend"], platforms=["linkedin"], strict_region=False)

    assert summary["saved"] == 1
    assert summary["platforms"]["linkedin"]["fetched"] == 5
    assert summary["platforms"]["linkedin"]["skipped"] == 4
    assert len(fake_repo.saved) == 1
    saved = fake_repo.saved[0]
    assert saved["post_url"] == "https://linkedin.com/posts/jane-1"
    assert "we are hiring" in saved["keywords_matched"]
    assert saved["_breakdown"].verdict in {"legit", "suspicious"}
    assert collector.run_state()["running"] is False
    assert collector.run_state()["last_result"]["saved"] == 1


def test_collector_reports_platform_errors(monkeypatch) -> None:
    fake_repo = FakeRepository()
    monkeypatch.setattr(collector, "JobRepository", lambda: fake_repo)

    def boom(keywords, max_posts=None, location=None, countries=None):
        raise RuntimeError("login required")

    monkeypatch.setitem(collector.COLLECTORS, "linkedin", boom)

    summary = collector.collect_social_posts(keywords=["python"], platforms=["linkedin"], strict_region=False)

    assert "linkedin" in summary["errors"]
    assert "login required" in summary["errors"]["linkedin"]
    assert summary["saved"] == 0


def test_collector_skips_non_tech_hiring_posts(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fake_repo = FakeRepository()
    monkeypatch.setattr(collector, "JobRepository", lambda: fake_repo)

    sales_post = {
        "platform": "x",
        "author": "Sales Bot",
        "text": "We are hiring a Sales Executive. Remote role. Apply now!",
        "post_url": "https://x.com/sales/status/1",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    manager_post = {
        "platform": "x",
        "author": "Chatty",
        "text": "Ask the hiring manager for the salary range. Remote work is common.",
        "post_url": "https://x.com/chatty/status/2",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setitem(
        collector.COLLECTORS,
        "x",
        lambda keywords, max_posts=None, countries=None: [sales_post, manager_post],
    )

    summary = collector.collect_social_posts(keywords=["engineer"], platforms=["x"], strict_region=False)

    assert summary["saved"] == 0
    assert summary["platforms"]["x"]["skipped"] == 2


def test_x_query_builder_includes_remote_and_recency() -> None:
    from services.social.x_posts import build_x_queries

    queries = build_x_queries(["devops", "backend"])
    assert queries
    assert any("remote" in query.lower() for query in queries)
    assert all("since:" in query for query in queries)
    assert any("devops" in query.lower() for query in queries)


def test_collector_filters_posts_by_selected_region(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fake_repo = FakeRepository()
    monkeypatch.setattr(collector, "JobRepository", lambda: fake_repo)

    egypt_post = {
        "platform": "linkedin",
        "author": "Cairo Recruiter",
        "text": "We are hiring a DevOps Engineer. Fully remote, Egypt only.",
        "post_url": "https://linkedin.com/posts/eg-1",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    global_post = {
        "platform": "linkedin",
        "author": "Global Recruiter",
        "text": "We are hiring a DevOps Engineer. Fully remote worldwide.",
        "post_url": "https://linkedin.com/posts/global-1",
        "posted_at": (now - timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setitem(
        collector.COLLECTORS,
        "linkedin",
        lambda keywords, max_posts=None, location=None, countries=None: [
            egypt_post,
            global_post,
        ],
    )

    summary = collector.collect_social_posts(
        keywords=["devops"],
        platforms=["linkedin"],
        countries=["egypt"],
        strict_region=True,
    )

    assert summary["saved"] == 1
    assert fake_repo.saved[0]["post_url"] == "https://linkedin.com/posts/eg-1"
    assert summary["countries"] == ["egypt"]
