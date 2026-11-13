from datetime import datetime, timedelta, timezone

from services.social import collector, reddit_posts

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>newest submissions : jobbit</title>
  <entry>
    <title>[HIRING] Senior DevOps Engineer - Remote - $150k</title>
    <updated>2026-11-12T11:31:07+00:00</updated>
    <author><name>/u/recruiter_jane</name></author>
    <link rel="alternate" href="https://www.reddit.com/r/jobbit/comments/abc/hiring_senior_devops/" />
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;We are hiring a &lt;strong&gt;Senior DevOps Engineer&lt;/strong&gt;. Fully remote, worldwide.&lt;/p&gt;&lt;/div&gt;</content>
  </entry>
  <entry>
    <title>[For Hire] Junior developer looking for remote work</title>
    <updated>2026-11-12T10:00:00+00:00</updated>
    <author><name>/u/candidate</name></author>
    <link rel="alternate" href="https://www.reddit.com/r/jobbit/comments/def/for_hire/" />
    <content type="html">&lt;p&gt;I am a developer available for hire.&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>[Hiring] Onsite backend engineer in Dubai</title>
    <updated>2026-11-12T09:00:00+00:00</updated>
    <author><name>/u/office_recruiter</name></author>
    <link rel="alternate" href="https://www.reddit.com/r/jobbit/comments/ghi/onsite/" />
    <content type="html">&lt;p&gt;Backend role, onsite only, no remote.&lt;/p&gt;</content>
  </entry>
</feed>
"""

_JSON_PAYLOAD = {
    "data": {
        "children": [
            {
                "data": {
                    "title": "[Hiring] Platform Engineer - Remote",
                    "selftext": "We are hiring a platform engineer. Fully remote.",
                    "author": "reddit_recruiter",
                    "permalink": "/r/forhire/comments/xyz/hiring_platform_engineer/",
                    "created_utc": 1762940000,
                    "subreddit": "forhire",
                    "stickied": False,
                    "over_18": False,
                }
            },
            {
                "data": {
                    "title": "Stickied announcement",
                    "selftext": "Read the rules",
                    "author": "mod",
                    "permalink": "/r/forhire/comments/sticky/",
                    "created_utc": 1762940000,
                    "subreddit": "forhire",
                    "stickied": True,
                    "over_18": False,
                }
            },
        ]
    }
}


def test_parse_reddit_rss_strips_html_and_skips_for_hire() -> None:
    posts = reddit_posts.parse_reddit_rss(_RSS, "jobbit")

    assert len(posts) == 2
    first = posts[0]
    assert first["platform"] == "reddit"
    assert first["author"] == "u/recruiter_jane · r/jobbit"
    assert first["post_url"] == "https://www.reddit.com/r/jobbit/comments/abc/hiring_senior_devops/"
    assert first["posted_at"] == "2026-11-12T11:31:07+00:00"
    assert "Senior DevOps Engineer" in first["text"]
    assert "<strong>" not in first["text"]
    assert "<!--" not in first["text"]

    titles = [post["text"].splitlines()[0] for post in posts]
    assert not any("For Hire" in title for title in titles)


def test_parse_reddit_json_skips_stickied_posts() -> None:
    posts = reddit_posts.parse_reddit_json(_JSON_PAYLOAD, "forhire")

    assert len(posts) == 1
    assert posts[0]["author"] == "u/reddit_recruiter · r/forhire"
    assert posts[0]["post_url"] == (
        "https://www.reddit.com/r/forhire/comments/xyz/hiring_platform_engineer/"
    )
    assert posts[0]["text"].startswith("[Hiring] Platform Engineer - Remote")


def test_collect_reddit_posts_uses_configured_feeds(monkeypatch) -> None:
    monkeypatch.setattr(reddit_posts, "REDDIT_SUBREDDITS", ["jobbit", "remotejobs"])
    monkeypatch.setattr(reddit_posts, "REDDIT_MAX_SUBREDDITS", 2)
    monkeypatch.setattr(reddit_posts, "REDDIT_REQUEST_DELAY", 0)

    calls: list[str] = []

    def fake_fetch(client, subreddit):
        calls.append(subreddit)
        return reddit_posts.parse_reddit_rss(_RSS, subreddit)

    monkeypatch.setattr(reddit_posts, "_fetch_subreddit", fake_fetch)

    posts = reddit_posts.collect_reddit_posts(["devops"], max_posts=10)

    assert calls == ["jobbit", "remotejobs"]
    # The same feed returned twice is deduplicated by post URL.
    assert len(posts) == 2
    assert all(post["platform"] == "reddit" for post in posts)


def test_reddit_posts_flow_through_the_social_collector(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fake_repo = _FakeRepository()
    monkeypatch.setattr(collector, "JobRepository", lambda: fake_repo)

    monkeypatch.setitem(
        collector.COLLECTORS,
        "reddit",
        lambda keywords, max_posts=None, countries=None: [
            {
                "platform": "reddit",
                "author": "u/recruiter · r/forhire",
                "author_url": "https://www.reddit.com/user/recruiter/",
                "text": (
                    "[Hiring] Senior Backend Engineer - Remote\n\n"
                    "We are hiring a Senior Backend Engineer. Fully remote, worldwide."
                ),
                "post_url": "https://www.reddit.com/r/forhire/comments/1/hiring_backend/",
                "posted_at": (now - timedelta(hours=1)).isoformat(),
            },
            {
                "platform": "reddit",
                "author": "u/office · r/jobbit",
                "text": "[Hiring] Backend Engineer - Onsite in Dubai. No remote.",
                "post_url": "https://www.reddit.com/r/jobbit/comments/2/onsite/",
                "posted_at": (now - timedelta(hours=1)).isoformat(),
            },
        ],
    )

    summary = collector.collect_social_posts(
        keywords=["backend"],
        platforms=["reddit"],
        strict_region=False,
    )

    assert summary["saved"] == 1
    assert summary["platforms"]["reddit"]["fetched"] == 2
    assert summary["platforms"]["reddit"]["skipped"] == 1
    assert fake_repo.saved[0]["post_url"].startswith("https://www.reddit.com/r/forhire/")


def test_reddit_platform_status(monkeypatch) -> None:
    monkeypatch.setattr(collector, "REDDIT_USERNAME", "someone")
    monkeypatch.setattr(collector, "REDDIT_PASSWORD", "secret")

    status = collector.platform_status()
    reddit = status["reddit"]

    assert reddit["credentials"] is True
    assert reddit["public_feed"] is True
    assert "forhire" in reddit["subreddits"]


def test_default_reddit_subreddits_are_not_mangled() -> None:
    from config import settings

    assert all(not sub.startswith("r/") for sub in settings.REDDIT_SUBREDDITS)
    # Regression guard: ``lstrip("r/")`` used to turn "remotejobs" into "emotejobs".
    assert "remotejobs" in settings.REDDIT_SUBREDDITS


class _FakeRepository:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def init_schema(self) -> None:
        return None

    def save_hiring_post(self, post: dict):
        self.saved.append(post)
        return True, "fp"
