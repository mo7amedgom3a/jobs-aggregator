from datetime import datetime, timedelta, timezone

from services.filters import detect_hiring_phrases, has_hiring_intent, parse_posted_at
from services.scoring import (
    authenticity_score,
    relevance_score,
    score_hiring_post,
    score_job,
)


def _job(**overrides):
    base = {
        "title": "Senior Python Engineer",
        "company": "Acme",
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "description": (
            "Acme is hiring a Senior Python Engineer to build our platform. "
            "You will work with FastAPI, PostgreSQL and AWS. Salary is competitive "
            "and the role is fully remote within Europe. " * 3
        ),
        "location": "Remote",
        "tags": ["python", "fastapi", "aws"],
        "salary": "$120,000 - $150,000 / year",
        "source": "greenhouse",
        "posted_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def test_legit_job_scores_above_scam_job() -> None:
    legit = score_job(_job(), keywords=["python", "engineer"])
    scam = score_job(
        _job(
            title="URGENT HIRING!!! WORK FROM HOME AND EARN $500 PER DAY",
            company="Confidential",
            url="https://bit.ly/abc",
            description=(
                "No experience required. Pay a registration fee and contact me on "
                "WhatsApp or Telegram to start. Guaranteed income."
            ),
            salary="$500 per day",
            source="social",
        ),
        keywords=["python", "engineer"],
    )

    assert legit.authenticity >= 7.0
    assert legit.verdict == "legit"
    assert scam.authenticity <= 3.0
    assert scam.verdict == "likely_scam"
    assert scam.score < legit.score
    assert any("payment" in reason or "WhatsApp" in reason or "Telegram" in reason for reason in scam.reasons)


def test_relevance_prefers_title_and_freshness() -> None:
    fresh = _job(title="Kubernetes Platform Engineer")
    old = _job(
        title="Kubernetes Platform Engineer",
        posted_at=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
    )

    fresh_score, fresh_reasons = relevance_score(fresh, keywords=["kubernetes"])
    old_score, _ = relevance_score(old, keywords=["kubernetes"])

    assert fresh_score > old_score
    assert any("24h" in reason or "12h" in reason for reason in fresh_reasons)


def test_authenticity_penalises_shortener_and_placeholder() -> None:
    score, reasons = authenticity_score(
        _job(
            company="Confidential",
            url="https://bit.ly/xyz",
            description="DM me on WhatsApp.",
            source="social",
        )
    )
    assert score < 5.5
    assert any("shortener" in reason for reason in reasons)
    assert any("placeholder" in reason for reason in reasons)


def test_hiring_post_detection_and_scoring() -> None:
    text = "We are hiring a Senior Backend Engineer in Cairo! Send your CV. #jobs"
    assert has_hiring_intent(text)
    assert "we are hiring" in detect_hiring_phrases(text)

    post = {
        "platform": "linkedin",
        "author": "Jane Recruiter",
        "author_url": "https://linkedin.com/in/jane",
        "text": text,
        "post_url": "https://linkedin.com/posts/jane-123",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    }
    breakdown = score_hiring_post(post, keywords=["backend", "cairo"])
    assert breakdown.relevance >= 5
    assert breakdown.authenticity >= 5
    assert breakdown.verdict in {"legit", "suspicious"}
    assert any("hiring intent" in reason for reason in breakdown.reasons)


def test_spam_hiring_post_is_flagged() -> None:
    post = {
        "platform": "x",
        "author": "anon",
        "text": (
            "WORK FROM HOME AND EARN $500 per day! No interview required. "
            "Pay a registration fee via Western Union. DM me on WhatsApp now!"
        ),
        "post_url": "https://x.com/anon/status/1",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    breakdown = score_hiring_post(post, keywords=["engineer"])
    assert breakdown.verdict in {"suspicious", "likely_scam"}
    assert breakdown.authenticity < 4


def test_parse_posted_at_supports_social_labels() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    assert parse_posted_at("2h", now=now) == now - timedelta(hours=2)
    assert parse_posted_at("5m", now=now) == now - timedelta(minutes=5)
    assert parse_posted_at("1d", now=now) == now - timedelta(days=1)
