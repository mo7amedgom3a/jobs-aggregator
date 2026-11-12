import pytest

from services.filters import is_hybrid_or_onsite, is_remote_only, is_remote_text


@pytest.mark.parametrize(
    "location",
    ["Remote", "Fully Remote", "Remote - Worldwide", "Work from home", "Anywhere", "WFH"],
)
def test_remote_locations_are_accepted(location: str) -> None:
    job = {"title": "Backend Engineer", "location": location, "tags": []}
    assert is_remote_only(job) is True


@pytest.mark.parametrize(
    "location",
    ["Berlin, Germany", "Cairo, Egypt", "Onsite", "Hybrid - London", "In-office, Dubai"],
)
def test_onsite_and_hybrid_locations_are_rejected(location: str) -> None:
    job = {"title": "Backend Engineer", "location": location, "tags": []}
    assert is_remote_only(job) is False


def test_hybrid_overrides_remote_mention() -> None:
    job = {
        "title": "Backend Engineer",
        "location": "Remote / Hybrid",
        "tags": ["remote"],
    }
    assert is_hybrid_or_onsite("Remote / Hybrid") is True
    assert is_remote_only(job) is False


def test_description_fallback_requires_explicit_remote() -> None:
    assert is_remote_only({"title": "Engineer", "location": "", "description": "This is a fully remote role."}) is True
    assert is_remote_only({"title": "Engineer", "location": "", "description": "Hybrid role in Cairo."}) is False
    assert is_remote_only({"title": "Engineer", "location": "", "description": "Great benefits."}) is False


def test_remote_text_for_hiring_posts() -> None:
    assert is_remote_text("We are hiring a backend engineer. Fully remote role!") is True
    assert is_remote_text("We are hiring a backend engineer. Onsite in Dubai.") is False
    assert is_remote_text("We are hiring a backend engineer. Remote or hybrid.") is False
