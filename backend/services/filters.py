"""Filtering helpers shared by routes and orchestration services."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# ─── Recency ─────────────────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_RELATIVE_UNITS = {
    "second": "seconds",
    "sec": "seconds",
    "s": "seconds",
    "minute": "minutes",
    "min": "minutes",
    "m": "minutes",
    "hour": "hours",
    "hr": "hours",
    "h": "hours",
    "day": "days",
    "d": "days",
    "week": "weeks",
    "wk": "weeks",
    "w": "weeks",
    "month": "months",
    "mo": "months",
    "year": "years",
    "yr": "years",
    "y": "years",
}

_RELATIVE_RE = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|wks?|months?|mos?|years?|yrs?|[smhdwy])\b",
    re.IGNORECASE,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_posted_at(date_str: str | None, now: datetime | None = None) -> datetime | None:
    """Best-effort parse of a posting date into a timezone-aware UTC datetime.

    Handles relative ("2 hours ago", "3d", "just now"), ISO/RFC dates,
    epoch seconds/milliseconds, and human dates ("May 31", "31 May 2026").
    Returns ``None`` when the value cannot be interpreted.
    """
    if not date_str:
        return None

    text = str(date_str).strip()
    if not text:
        return None

    now = _as_utc(now or datetime.now(timezone.utc))
    lowered = text.lower().strip()

    # Relative phrasing.
    if any(token in lowered for token in ("just now", "now", "today")):
        return now
    if "yesterday" in lowered:
        return now - timedelta(days=1)

    match = _RELATIVE_RE.search(lowered)
    if match and "ago" in lowered or (match and re.fullmatch(r"\d+\s*[smhdwy]", lowered)):
        unit = match.group("unit").lower()
        key = _RELATIVE_UNITS.get(unit, _RELATIVE_UNITS.get(unit.rstrip("s"), "days"))
        amount = int(match.group("num"))
        if key == "seconds":
            return now - timedelta(seconds=amount)
        if key == "minutes":
            return now - timedelta(minutes=amount)
        if key == "hours":
            return now - timedelta(hours=amount)
        if key == "days":
            return now - timedelta(days=amount)
        if key == "weeks":
            return now - timedelta(weeks=amount)
        if key == "months":
            return now - timedelta(days=amount * 30)
        if key == "years":
            return now - timedelta(days=amount * 365)

    # Epoch seconds / milliseconds.
    if re.fullmatch(r"\d{10,13}(?:\.\d+)?", text):
        try:
            stamp = float(text)
            if stamp > 1e12:
                stamp /= 1000.0
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        except (ValueError, OSError):
            pass

    # ISO 8601 and common date formats.
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return _as_utc(datetime.fromisoformat(iso_candidate))
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            return _as_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue

    # RFC 2822 (Google/SerpAPI sometimes returns it).
    try:
        return _as_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        pass

    # Month-name + day, with an inferred year (LinkedIn/Indeed style).
    month_match = re.search(
        r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?",
        lowered,
    )
    if month_match:
        month = _MONTHS[month_match.group(1)]
        day = int(month_match.group(2))
        year = int(month_match.group(3)) if month_match.group(3) else now.year
        try:
            parsed = datetime(year, month, day, tzinfo=timezone.utc)
            if parsed > now + timedelta(days=1):
                parsed = parsed.replace(year=year - 1)
            return parsed
        except ValueError:
            pass

    day_month_match = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b\.?(?:\s+(\d{4}))?",
        lowered,
    )
    if day_month_match:
        day = int(day_month_match.group(1))
        month = _MONTHS[day_month_match.group(2)]
        year = int(day_month_match.group(3)) if day_month_match.group(3) else now.year
        try:
            parsed = datetime(year, month, day, tzinfo=timezone.utc)
            if parsed > now + timedelta(days=1):
                parsed = parsed.replace(year=year - 1)
            return parsed
        except ValueError:
            pass

    return None


def is_within_window(
    date_str: str | None,
    hours: int = 24,
    strict: bool = True,
    now: datetime | None = None,
) -> bool:
    """Return True when ``date_str`` is within the last ``hours`` hours.

    In strict mode an unparseable/missing date returns False, which is what the
    freshest-24h pipeline requires. In non-strict mode unknown dates are kept.
    """
    parsed = parse_posted_at(date_str, now=now)
    if parsed is None:
        return not strict

    reference = _as_utc(now or datetime.now(timezone.utc))
    if parsed > reference + timedelta(minutes=5):
        # Tolerate small clock skew but reject clearly future dates beyond a day.
        return parsed <= reference + timedelta(days=1)
    # Small tolerance keeps values like "3 days ago" inside a 72h window.
    return reference - parsed <= timedelta(hours=hours) + timedelta(minutes=1)


def is_within_24_hours(date_str: str, snippet: str = "", strict: bool = False) -> bool:
    """Backward-compatible helper used by the Google dork service."""
    candidate = date_str or snippet or ""
    if not date_str and snippet:
        # Snippet text is noisy; only treat clear "X hours ago" mentions as dates.
        match = re.search(r"(\d+)\s+hours?\s+ago", snippet.lower())
        if match:
            return int(match.group(1)) <= 24
        if re.search(r"\b(yesterday|days? ago|weeks? ago|months? ago)\b", snippet.lower()):
            return False
        return not strict
    return is_within_window(candidate, hours=24, strict=strict)


def is_within_3_days(date_str: str | None) -> bool:
    """Legacy helper kept for compatibility; prefer ``is_within_window``."""
    return is_within_window(date_str, hours=72, strict=False)


# ─── Companies ───────────────────────────────────────────────────────────────

BLACKLISTED_COMPANIES = [
    "crossing hurdles",
    "turing",
    "confidential",
    "confidential careers",
    "micro1",
    "canonical",
    "naphora games group",
    "meridial marketplace",
    "by invisible",
    "invisible",
    "siira",
    "proxify",
    "dataannotation",
    "mindrift",
    "mercor",
    "jobgether",
    "jobright.ai",
    "hire feed",
    "Hire Feed",
    "revolut",
    "hired",
]


def is_blacklisted_company(company_name: str | None) -> bool:
    if not company_name:
        return False
    name_lower = company_name.lower().strip()
    return any(blocked in name_lower for blocked in BLACKLISTED_COMPANIES)


def is_blacklisted_title(title: str | None) -> bool:
    """Checks if a job title is not related to the software field (e.g. Waiter, Electrical, Sales)."""
    if not title:
        return False
    title_lower = title.lower().strip()

    patterns = [
        # Explicit user list
        r"\bwaiter\b", r"\bwaitress\b",
        r"\belectrical\b", r"\belectrician\b",
        r"\bdraftsman\b", r"\bdraftsmen\b",
        r"\bdraftsperson\b",
        r"\baluminium\b", r"\baluminum\b",
        r"\bdrainage\b",
        r"\bmarketing\b",
        r"\breal\s*estate\b",
        r"\bproperty\b",
        r"\bmetal\b",
        r"\blight\b",
        r"\bmaterials\b",
        r"\bconstruction\b",
        r"\bmep\b",
        r"\bland\b",
        r"\bland\s+sales\b",
        r"\bsales\b",
        r"\bcivil\b",

        # Common construction/non-software leaks
        r"\bplumbing\b", r"\bplumber\b",
        r"\bpiping\b",
        r"\bhvac\b",
        r"\bmechanical\b",
        r"\bquantity\s+surveyor\b",
        r"\bdriver\b", r"\bstorekeeper\b", r"\bwarehouse\b",
        r"\baccountant\b", r"\baccounting\b",
        r"\bhr\b", r"\bhuman\s+resources\b",
        r"\bnurse\b", r"\bdoctor\b", r"\bpharmacist\b",
        r"\bchef\b", r"\bcook\b",
    ]

    for pattern in patterns:
        if re.search(pattern, title_lower):
            return True

    return False


# ─── Remote-only filtering ───────────────────────────────────────────────────

#: Positive signals that a role is remote.
REMOTE_PATTERN = re.compile(
    r"\b("
    r"remote|work\s*from\s*home|wfh|telecommut\w*|telework|"
    r"anywhere|worldwide|remote[-\s]?first|fully\s+remote|"
    r"distributed\s+team|home[-\s]?based"
    r")\b",
    re.IGNORECASE,
)

#: Signals that override a remote mention (explicitly onsite/hybrid).
ONSITE_PATTERN = re.compile(
    r"\b("
    r"hybrid|on[-\s]?site|in[-\s]?office|office[-\s]?based|"
    r"in[-\s]?person|relocation|no\s+remote|non[-\s]?remote"
    r")\b",
    re.IGNORECASE,
)


def is_hybrid_or_onsite(text: str | None) -> bool:
    return bool(text and ONSITE_PATTERN.search(text))


def is_remote_text(text: str | None) -> bool:
    """True when text advertises a remote role and does not mention hybrid/onsite."""
    if not text:
        return False
    if ONSITE_PATTERN.search(text):
        return False
    return bool(REMOTE_PATTERN.search(text))


def _job_primary_text(job: dict) -> str:
    tags = job.get("tags") or []
    if isinstance(tags, (list, tuple)):
        tags = " ".join(str(tag) for tag in tags)
    return " ".join(
        str(job.get(key) or "") for key in ("location", "title", "salary", "company")
    ) + " " + str(tags)


def is_remote_only(job: dict) -> bool:
    """Strict remote check used by APIs, spiders, and scoring.

    - Rejects anything that mentions hybrid/onsite/in-office/relocation.
    - Accepts only jobs with an explicit remote signal in location/title/tags,
      or (when those are empty) in the description.
    """
    primary = _job_primary_text(job)
    if ONSITE_PATTERN.search(primary):
        return False
    if REMOTE_PATTERN.search(primary):
        return True

    description = str(job.get("description") or "")
    if description:
        # Only trust the description when it is explicit; still reject hybrid.
        if ONSITE_PATTERN.search(description):
            return False
        return bool(REMOTE_PATTERN.search(description))
    return False


# ─── Social hiring-post intent ───────────────────────────────────────────────

HIRING_PHRASES: list[str] = [
    "we are hiring",
    "we're hiring",
    "we are looking for",
    "we're looking for",
    "hiring now",
    "now hiring",
    "hiring!",
    "job opening",
    "job opportunity",
    "open role",
    "open position",
    "open vacancy",
    "join our team",
    "join my team",
    "looking to hire",
    "actively hiring",
    "immediately hiring",
    "immediate hiring",
    "dm me",
    "send your cv",
    "send your resume",
    "share your cv",
    "share your resume",
    "apply now",
]


#: Tech-role vocabulary used to keep social hiring posts relevant to this app.
TECH_ROLE_PATTERN = re.compile(
    r"\b("
    r"engineer|developer|devops|dev\s?ops|sre|platform|backend|front[-\s]?end|"
    r"full[-\s]?stack|data|analytics|ai|ml|machine\s+learning|llm|cloud|"
    r"security|qa|test\s+automation|architect|scientist|programmer|software|"
    r"technical|infrastructure|database|network|mobile|ios|android"
    r")\b",
    re.IGNORECASE,
)


def detect_hiring_phrases(text: str | None) -> list[str]:
    """Return the hiring-intent phrases found in a social post."""
    if not text:
        return []
    lowered = text.lower()
    matched = [phrase for phrase in HIRING_PHRASES if phrase in lowered]

    # Social posts frequently use bare "Hiring:", "I'm hiring", "is hiring".
    if not matched and re.search(r"\bhiring\b", lowered):
        matched.append("hiring")

    return matched


def has_hiring_intent(text: str | None) -> bool:
    return bool(detect_hiring_phrases(text))
