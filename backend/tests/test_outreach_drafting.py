from services.outreach.drafting import build_message


FOUNDER = {"name": "Alex Musy", "title": "Founder/CEO"}
COMPANY = {"name": "Huscarl", "one_liner": "Autonomous AI actuary for corporate insurance"}
JOBS = [
    {"title": "Founding AI engineer - Paris"},
    {"title": "Actuary - US"},
    {"title": "Founding Business Lead - Paris"},
]


def test_email_message_mentions_relevant_role_only() -> None:
    message = build_message(FOUNDER, COMPANY, JOBS, "email", keywords=["ai", "backend"])
    assert message["subject"].startswith("Quick intro")
    assert "Founding AI engineer" in message["body"]
    assert "Actuary" not in message["body"]
    assert "Hi Alex," in message["body"]


def test_short_channel_message_has_no_subject() -> None:
    message = build_message(FOUNDER, COMPANY, JOBS, "linkedin", keywords=["ai"])
    assert message["subject"] is None
    assert "Hi Alex" in message["body"]
    assert "LinkedIn" in message["body"]


def test_message_falls_back_when_no_role_matches_keywords() -> None:
    message = build_message(FOUNDER, COMPANY, JOBS, "x", keywords=["golang"])
    assert message["subject"] is None
    assert "came across Huscarl" in message["body"]
    assert "Actuary" not in message["body"]
