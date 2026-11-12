"""Deterministic relevance + authenticity scoring for jobs and hiring posts.

The goal is two-fold:

1. **Ranking** — surface the jobs that best match the requested keywords while
   preferring fresher, higher-quality listings.
2. **Authenticity** — flag postings that look fake, spammy, or like lead-gen
   traps so they can be ranked down and labelled in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from config.settings import (
    AUTHENTICITY_WEIGHT,
    KEYWORDS,
    POSTED_HOURS,
    RELEVANCE_WEIGHT,
)
from services.filters import (
    BLACKLISTED_COMPANIES,
    detect_hiring_phrases,
    is_blacklisted_company,
    parse_posted_at,
)

# ═════════════════════════════════════════════════════════════════════════════
#  Signal definitions
# ═════════════════════════════════════════════════════════════════════════════

#: Strong indicators of a scam / lead-generation posting.
SCAM_PATTERNS: list[tuple[str, str]] = [
    (r"\bpay\s*(?:a\s*)?(?:fee|to apply|for training|registration)\b", "asks for payment"),
    (r"\btraining\s+fee\b", "asks for payment"),
    (r"\bregistration\s+fee\b", "asks for payment"),
    (r"\bsecurity\s+deposit\b", "asks for payment"),
    (r"\bwestern\s+union\b", "payment via wire transfer"),
    (r"\bbitcoin\b|\bcrypto(?:currency)?\s+payment\b|\busdt\b", "crypto payment"),
    (r"\b(?:whats\s*app|whatsapp)\b", "contact via WhatsApp"),
    (r"\btelegram\b", "contact via Telegram"),
    (r"\bdm\s+(?:me|us)\b", "DM-only contact"),
    (r"\bno\s+(?:experience|interview)\s+(?:required|needed)\b", "no interview/experience required"),
    (r"\bearn\s+(?:up\s+to\s+)?\$?\d+\s*(?:k|dollars?)?\s*(?:per|/)\s*(?:day|week)\b", "unrealistic daily pay"),
    (r"\bguaranteed\s+(?:income|salary|job)\b", "guaranteed income"),
    (r"\bclick\s+(?:here|this\s+link)\s+to\s+(?:apply|register|start)\b", "click-link apply flow"),
    (r"\bwork\s+from\s+home\s+and\s+earn\b", "work-from-home scheme"),
    (r"\b100%\s+(?:remote|guaranteed|free)\b", "absolute claim"),
    (r"\b(?:copy|paste)\s+(?:this|the)\s+message\b", "chain-message spam"),
]

#: Short-link / redirect hosts that hide the real destination.
SHORTENER_HOSTS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly", "is.gd",
    "cutt.ly", "shorturl.at", "rb.gy", "rebrand.ly", "lnkd.in", "t.ly",
}

#: Sources that are inherently more trustworthy (structured ATS pages).
HIGH_TRUST_SOURCES = {
    "greenhouse", "lever", "workable", "ashby", "ashbyhq", "smartrecruiters",
    "workday", "jobvite", "bamboohr", "recruitee", "teamtailor",
}

#: Job boards that aggregate third-party listings (moderate trust).
MEDIUM_TRUST_SOURCES = {
    "linkedin", "indeed", "weworkremotely", "remotive", "jobicy", "remoteok",
    "himalayas", "trueup", "wellfound", "glassdoor", "zip_recruiter",
    "google", "simplyhired", "stackoverflow", "github-jobs",
}

PLACEHOLDER_COMPANIES = {
    "", "n/a", "na", "none", "unknown", "confidential", "confidential company",
    "private", "a company", "our client", "client of ours", "undisclosed",
    "company name", "hiring company", "employer",
}

ALLOWED_CONTACT_PATTERNS = re.compile(
    r"(?:https?://)?(?:www\.)?(?:linkedin\.com|indeed\.com|greenhouse\.io|lever\.co|workable\.com|ashbyhq\.com|workday\.com)",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════════════════
#  Data structures
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class ScoreBreakdown:
    relevance: float
    authenticity: float
    score: float
    verdict: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 2),
            "authenticity": round(self.authenticity, 2),
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "reasons": self.reasons,
        }


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def _normalize_keywords(keywords: Iterable[str] | None) -> list[str]:
    if not keywords:
        return [kw.lower() for kw in KEYWORDS]
    return [kw.lower().strip() for kw in keywords if str(kw).strip()]


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlsplit(url if "://" in url else f"https://{url}").hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def _company_tokens(company: str | None) -> list[str]:
    if not company:
        return []
    cleaned = re.sub(r"\b(inc|ltd|llc|gmbh|corp|corporation|company|co|plc|sa|eg)\b", " ", company.lower())
    return [token for token in re.split(r"[^a-z0-9]+", cleaned) if len(token) >= 3]


# ═════════════════════════════════════════════════════════════════════════════
#  Relevance
# ═════════════════════════════════════════════════════════════════════════════


def relevance_score(
    job: dict[str, Any],
    keywords: Iterable[str] | None = None,
    now: datetime | None = None,
) -> tuple[float, list[str]]:
    """Score keyword fit (0-10) with a recency and quality boost."""
    reasons: list[str] = []
    kws = _normalize_keywords(keywords)
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    tags_value = job.get("tags") or []
    tags = " ".join(tags_value).lower() if isinstance(tags_value, list) else str(tags_value).lower()
    company = (job.get("company") or "").lower()

    score = 0.0
    matched: list[str] = []
    for keyword in kws:
        if not keyword:
            continue
        hit = False
        if keyword in title:
            score += 3.0
            hit = True
        if keyword in tags:
            score += 1.5
            hit = True
        if keyword in description:
            score += 1.0
            hit = True
        if keyword in company:
            score += 0.5
            hit = True
        if hit:
            matched.append(keyword)

    # Cap the keyword component so a keyword-stuffed description cannot win alone.
    keyword_component = min(score, 7.0)
    reasons.append(f"{len(matched)} keyword match(es)")
    score = keyword_component

    # Recency: fresher postings score higher.
    posted = parse_posted_at(job.get("posted_at") or job.get("date_posted"), now=now)
    if posted is not None:
        reference = now or datetime.now(timezone.utc)
        age = reference - posted
        if age <= timedelta(hours=max(1, POSTED_HOURS // 2)):
            score += 1.5
            reasons.append("posted in the last 12h")
        elif age <= timedelta(hours=POSTED_HOURS):
            score += 0.8
            reasons.append("posted in the last 24h")
        elif age > timedelta(days=7):
            score -= 1.0
            reasons.append("older than a week")

    # Quality signals.
    if (job.get("salary") or "").strip() and job.get("salary", "").strip().upper() != "N/A":
        score += 0.6
        reasons.append("salary disclosed")
    if len(description) >= 300:
        score += 0.4
        reasons.append("detailed description")
    if job.get("easy_apply"):
        score += 0.2

    return _clamp(score), reasons


# ═════════════════════════════════════════════════════════════════════════════
#  Authenticity
# ═════════════════════════════════════════════════════════════════════════════


def authenticity_score(job: dict[str, Any]) -> tuple[float, list[str]]:
    """Estimate whether a posting is a real, legitimate job (0-10)."""
    reasons: list[str] = []
    score = 6.0  # neutral baseline

    title = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    description = (job.get("description") or "").strip()
    url = (job.get("url") or "").strip()
    source = (job.get("source") or job.get("site") or "").strip().lower()
    salary = (job.get("salary") or "").strip()
    haystack = f"{title}\n{company}\n{description}\n{salary}".lower()

    # 1. Source trust.
    if source in HIGH_TRUST_SOURCES:
        score += 2.0
        reasons.append("posted on a trusted ATS")
    elif source in MEDIUM_TRUST_SOURCES:
        score += 0.8
    elif source:
        score += 0.2

    # 2. Company legitimacy.
    company_lower = company.lower().strip()
    if company_lower in PLACEHOLDER_COMPANIES:
        score -= 2.0
        reasons.append("company name is missing/placeholder")
    elif is_blacklisted_company(company):
        score -= 3.0
        reasons.append("company is on the spam list")

    if company:
        tokens = _company_tokens(company)
        domain = _domain(url)
        if domain and any(token in domain for token in tokens):
            score += 1.5
            reasons.append("company name matches posting domain")

    # 3. URL quality.
    domain = _domain(url)
    if not domain:
        score -= 1.5
        reasons.append("missing posting URL")
    elif domain in SHORTENER_HOSTS:
        score -= 2.0
        reasons.append("URL uses a link shortener")
    elif any(host in domain for host in ("t.me", "wa.me", "telegram.me")):
        score -= 2.5
        reasons.append("URL points to a chat app")

    # 4. Scam phrasing.
    hits = [reason for pattern, reason in SCAM_PATTERNS if re.search(pattern, haystack)]
    if hits:
        unique_hits = sorted(set(hits))
        penalty = min(4.5, 1.5 * len(unique_hits))
        score -= penalty
        reasons.extend(unique_hits[:3])

    # 5. Description quality.
    if not description:
        score -= 0.8
        reasons.append("no description")
    elif len(description) < 120:
        score -= 1.0
        reasons.append("very short description")
    elif len(description) > 1200:
        score += 0.4

    if title and title.isupper() and len(title) > 12:
        score -= 0.8
        reasons.append("all-caps title")

    # 6. Salary sanity.
    if salary and re.search(r"\$\s*\d{6,}\s*(?:per\s+day|/day)", salary.lower()):
        score -= 1.5
        reasons.append("implausible daily salary")

    if not reasons:
        reasons.append("no red flags detected")

    return _clamp(score), reasons


# ═════════════════════════════════════════════════════════════════════════════
#  Composite
# ═════════════════════════════════════════════════════════════════════════════


def _verdict(authenticity: float, scam_hits: int) -> str:
    if scam_hits >= 2 or authenticity <= 3.0:
        return "likely_scam"
    if authenticity < 5.5:
        return "suspicious"
    return "legit"


def score_job(
    job: dict[str, Any],
    keywords: Iterable[str] | None = None,
    now: datetime | None = None,
) -> ScoreBreakdown:
    """Return the full score breakdown for a normalized job dict."""
    relevance, relevance_reasons = relevance_score(job, keywords=keywords, now=now)
    authenticity, authenticity_reasons = authenticity_score(job)

    haystack = " ".join(
        str(job.get(key) or "") for key in ("title", "description", "salary")
    ).lower()
    scam_hits = sum(1 for pattern, _ in SCAM_PATTERNS if re.search(pattern, haystack))

    composite = (
        AUTHENTICITY_WEIGHT * authenticity + RELEVANCE_WEIGHT * relevance
    )
    if scam_hits >= 2:
        composite -= min(2.5, scam_hits * 0.6)

    verdict = _verdict(authenticity, scam_hits)
    reasons = list(dict.fromkeys(relevance_reasons + authenticity_reasons))[:6]
    return ScoreBreakdown(
        relevance=relevance,
        authenticity=authenticity,
        score=_clamp(composite),
        verdict=verdict,
        reasons=reasons,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Social hiring posts
# ═════════════════════════════════════════════════════════════════════════════


def score_hiring_post(
    post: dict[str, Any],
    keywords: Iterable[str] | None = None,
    now: datetime | None = None,
) -> ScoreBreakdown:
    """Score a social hiring post (LinkedIn/X) for relevance and legitimacy."""
    text = (post.get("text") or "").strip()
    author = (post.get("author") or "").strip()
    url = (post.get("post_url") or post.get("url") or "").strip()
    platform = (post.get("platform") or "").strip().lower()

    lowered = text.lower()
    kws = _normalize_keywords(keywords)
    matched_keywords = [kw for kw in kws if kw and kw in lowered]
    matched_phrases = detect_hiring_phrases(text)

    relevance = 2.0
    relevance += min(3.0, 1.0 * len(matched_phrases))
    relevance += min(3.0, 0.75 * len(matched_keywords))
    if "http" in lowered:
        relevance += 0.5

    posted = parse_posted_at(post.get("posted_at"), now=now)
    if posted is not None:
        reference = now or datetime.now(timezone.utc)
        age = reference - posted
        if age <= timedelta(hours=6):
            relevance += 1.0
        elif age <= timedelta(hours=POSTED_HOURS):
            relevance += 0.5

    # Authenticity: posts are informal, so start lower and reward specifics.
    authenticity = 4.0
    if author:
        authenticity += 0.8
    if re.search(r"https?://", text):
        authenticity += 0.6
    if re.search(r"\b(?:engineer|developer|designer|analyst|manager|scientist|devops|data)\b", lowered):
        authenticity += 0.8
    if re.search(r"\b(?:remote|hybrid|onsite|full[-\s]?time|contract)\b", lowered):
        authenticity += 0.5
    if re.search(r"\b(?:cairo|egypt|dubai|riyadh|berlin|london|remote)\b", lowered):
        authenticity += 0.3
    if platform in {"linkedin", "x"}:
        authenticity += 0.3

    scam_hits = 0
    for pattern, reason in SCAM_PATTERNS:
        if re.search(pattern, lowered):
            authenticity -= 1.6
            scam_hits += 1
        if reason == "DM-only contact" and "dm me" in lowered and matched_keywords:
            # "DM me with your CV" is normal recruiting language on social.
            authenticity += 0.6

    if len(text) < 60:
        authenticity -= 1.0
    if len(text) > 240:
        authenticity += 0.4

    relevance = _clamp(relevance)
    authenticity = _clamp(authenticity)
    composite = AUTHENTICITY_WEIGHT * authenticity + RELEVANCE_WEIGHT * relevance
    if scam_hits >= 2:
        composite -= min(2.0, scam_hits * 0.6)

    verdict = _verdict(authenticity, scam_hits)
    reasons: list[str] = []
    if matched_phrases:
        reasons.append(f"hiring intent: {matched_phrases[0]}")
    if matched_keywords:
        reasons.append(f"matched keywords: {', '.join(matched_keywords[:3])}")
    if scam_hits:
        reasons.append("contains scam-style phrasing")
    if not reasons:
        reasons.append("low hiring signal")

    return ScoreBreakdown(
        relevance=relevance,
        authenticity=authenticity,
        score=_clamp(composite),
        verdict=verdict,
        reasons=reasons[:5],
    )


def score_and_annotate(
    job: dict[str, Any],
    keywords: Iterable[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a copy of ``job`` with score fields attached."""
    breakdown = score_job(job, keywords=keywords, now=now)
    enriched = dict(job)
    enriched.update(breakdown.as_dict())
    return enriched
