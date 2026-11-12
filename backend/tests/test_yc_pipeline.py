import json
import html

from services.yc import crawler
from services.yc.email_finder import (
    _matches_host,
    discover_company_email,
    extract_emails,
    guess_company_email,
)


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.body = body
        self.status = status

    def css(self, selector: str):
        return []


def test_extract_emails_filters_placeholders_and_assets() -> None:
    text = (
        "Contact founders@acme.io or hello@acme.io. "
        "Placeholder you@yourteam.com and noreply@acme.io should go. "
        "Asset logo@2x.png and sentry@o123.ingest.sentry.io too."
    )
    emails = extract_emails(text)
    assert "founders@acme.io" in emails
    assert "hello@acme.io" in emails
    assert "you@yourteam.com" not in emails
    assert "noreply@acme.io" not in emails
    assert "logo@2x.png" not in emails


def test_matches_host_requires_company_domain() -> None:
    assert _matches_host("founders@gbrain.io", "gbrain.io")
    assert _matches_host("team@mail.gbrain.io", "gbrain.io")
    assert not _matches_host("you@yourteam.com", "gbrain.io")


def test_discover_company_email_prefers_mailto_on_company_page() -> None:
    page = FakeResponse('<a href="mailto:founders@akkari.io">Email</a>')
    contact = discover_company_email(page, "https://akkari.io")
    assert contact == {
        "email": "founders@akkari.io",
        "source": "company_page",
        "confidence": "verified",
    }


def test_guess_company_email_from_website() -> None:
    assert guess_company_email("https://www.example-startup.com/") in {
        "founders@example-startup.com",
        "hello@example-startup.com",
        "team@example-startup.com",
    }
    assert guess_company_email("") is None


def test_public_avatar_url_strips_signed_query() -> None:
    from services.yc.media import public_avatar_url

    signed = (
        "https://bookface-images.s3.us-west-2.amazonaws.com/avatars/abc123.jpg"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef"
    )
    assert (
        public_avatar_url(signed)
        == "https://bookface-images.s3.amazonaws.com/avatars/abc123.jpg"
    )
    assert public_avatar_url(None) is None


def test_batch_label_normalizes_codes() -> None:
    assert crawler.batch_label("P26") == "Spring 2026"
    assert crawler.batch_label("W25") == "Winter 2025"
    assert crawler.batch_label("S27") == "Summer 2027"
    assert crawler.batch_label("F25") == "Fall 2025"
    assert crawler.batch_label("Spring 2026") == "Spring 2026"
    assert crawler.batch_label(None) is None


def test_inertia_props_decodes_escaped_payload() -> None:
    props = {"company": {"name": "Akkari", "founders": [{"full_name": "Jeffrey Byun"}]}}
    payload = html.escape(json.dumps({"component": "page", "props": props}))
    response = FakeResponse(f'<div data-page="{payload}"></div>')
    decoded = crawler.inertia_props(response)
    assert decoded["company"]["name"] == "Akkari"
    assert decoded["company"]["founders"][0]["full_name"] == "Jeffrey Byun"


def test_founders_from_props_skips_inactive_and_builds_slug() -> None:
    props = {
        "company": {
            "founders": [
                {"full_name": "Alex Musy", "title": "Founder/CEO", "is_active": True},
                {"full_name": "Inactive Person", "is_active": False},
            ]
        }
    }
    founders = crawler._founders_from_props(props, None, "huscarl")
    assert len(founders) == 1
    assert founders[0]["name"] == "Alex Musy"
    assert founders[0]["yc_slug"] == "alex-musy"
    assert founders[0]["profile_url"].endswith("/founders/alex-musy")


def test_jobs_from_props_maps_titles_and_urls() -> None:
    props = {
        "jobPostings": [
            {
                "id": 1,
                "title": "Founding AI engineer - Paris",
                "url": "/companies/huscarl/jobs/svTBnyf-founding-ai-engineer-paris",
                "location": "Paris, IDF, FR",
            }
        ]
    }
    jobs = crawler._jobs_from_props(props)
    assert jobs[0]["yc_job_slug"] == "svTBnyf-founding-ai-engineer-paris"
    assert jobs[0]["url"].startswith("https://www.ycombinator.com/companies/huscarl/jobs/")
    assert jobs[0]["location"] == "Paris, IDF, FR"
