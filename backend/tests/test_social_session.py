import time
from contextlib import contextmanager

import pytest

from services.social import collector, session


class _FakePage:
    def __init__(self) -> None:
        self.url = ""
        self.goto_calls: list[str] = []

    def goto(self, url: str, **kwargs) -> None:
        self.goto_calls.append(url)
        self.url = url

    def is_closed(self) -> bool:
        return True

    def wait_for_timeout(self, ms: int) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_sessions(monkeypatch):
    monkeypatch.setattr(session, "_SESSIONS", {})
    monkeypatch.setattr(session, "SOCIAL_BROWSER_TIMEOUT", 30)
    yield


def _wait_until_finished(platform: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = session.session_state().get(platform, {})
        if state and not state.get("running"):
            return state
        time.sleep(0.01)
    raise AssertionError(f"{platform} session did not finish in time")


def test_open_session_rejects_unknown_platform() -> None:
    with pytest.raises(ValueError):
        session.open_session("myspace")


def test_open_session_launches_headed_browser_and_saves_state(monkeypatch) -> None:
    launched: list[tuple[str, bool | None]] = []
    pages: list[_FakePage] = []

    @contextmanager
    def fake_browser_context(platform: str, headless: bool | None = None):
        launched.append((platform, headless))
        page = _FakePage()
        pages.append(page)
        yield page

    monkeypatch.setattr(session, "browser_context", fake_browser_context)
    monkeypatch.setattr(collector, "run_state", lambda: {"running": False})

    result = session.open_session("linkedin")

    assert result["status"] == "opened"
    assert launched == [("linkedin", False)]  # always headed
    state = _wait_until_finished("linkedin")
    assert state["running"] is False
    assert state["error"] is None
    assert state["finished_at"]
    assert pages[0].goto_calls == [session.PLATFORM_URLS["linkedin"]]


def test_open_session_respects_custom_url(monkeypatch) -> None:
    pages: list[_FakePage] = []

    @contextmanager
    def fake_browser_context(platform: str, headless: bool | None = None):
        page = _FakePage()
        pages.append(page)
        yield page

    monkeypatch.setattr(session, "browser_context", fake_browser_context)
    monkeypatch.setattr(collector, "run_state", lambda: {"running": False})

    session.open_session("x", "https://x.com/login")
    _wait_until_finished("x")

    assert pages[0].goto_calls == ["https://x.com/login"]


def test_open_session_refuses_when_platform_browser_is_open(monkeypatch) -> None:
    monkeypatch.setattr(collector, "run_state", lambda: {"running": False})
    session._SESSIONS["x"] = {"platform": "x", "running": True}

    result = session.open_session("x")

    assert result["status"] == "already_running"
    assert "already open" in result["message"]


def test_open_session_refuses_while_scan_is_running(monkeypatch) -> None:
    monkeypatch.setattr(collector, "run_state", lambda: {"running": True})

    result = session.open_session("linkedin")

    assert result["status"] == "error"
    assert "scan is running" in result["message"]


def test_is_session_running_reports_open_state(monkeypatch) -> None:
    monkeypatch.setattr(collector, "run_state", lambda: {"running": False})
    session._SESSIONS["reddit"] = {"platform": "reddit", "running": True}

    assert session.is_session_running("reddit") is True
    assert session.is_session_running("linkedin") is False
    assert session.any_session_running() is True
