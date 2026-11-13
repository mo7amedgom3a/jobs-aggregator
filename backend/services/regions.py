"""MENA region targeting shared by job and social-post searches.

The aggregator is focused on remote roles connected to Saudi Arabia, the UAE,
Egypt, Qatar, Kuwait, Bahrain, Oman, Jordan, and the wider Middle East.
"""

from __future__ import annotations

from typing import Iterable

#: Canonical region keys with the search terms used by LinkedIn/X queries.
MENA_COUNTRY_TERMS: dict[str, list[str]] = {
    "egypt": ["Egypt", "Cairo", "Alexandria", "مصر"],
    "saudi arabia": ["Saudi Arabia", "Riyadh", "Jeddah", "Dammam", "السعودية"],
    "united arab emirates": ["UAE", "Dubai", "Abu Dhabi", "United Arab Emirates", "الإمارات"],
    "qatar": ["Qatar", "Doha", "قطر"],
    "kuwait": ["Kuwait", "Kuwait City", "الكويت"],
    "bahrain": ["Bahrain", "Manama", "البحرين"],
    "oman": ["Oman", "Muscat", "عمان"],
    "jordan": ["Jordan", "Amman", "الأردن"],
    # Umbrella region: used when the caller passes "middle east", "mena", etc.
    "middle east": [
        "Middle East",
        "MENA",
        "GCC",
        "Gulf",
        "EMEA",
        "Saudi Arabia",
        "UAE",
        "Dubai",
        "Egypt",
        "Qatar",
        "Doha",
        "Kuwait",
        "Bahrain",
        "Oman",
        "Jordan",
    ],
}

#: Common spellings/short codes -> canonical region key.
MENA_ALIASES: dict[str, str] = {
    "eg": "egypt",
    "egyptian": "egypt",
    "sa": "saudi arabia",
    "saudi": "saudi arabia",
    "ksa": "saudi arabia",
    "ae": "united arab emirates",
    "uae": "united arab emirates",
    "emirates": "united arab emirates",
    "emarties": "united arab emirates",
    "dubai": "united arab emirates",
    "abu dhabi": "united arab emirates",
    "qa": "qatar",
    "doha": "qatar",
    "kw": "kuwait",
    "bh": "bahrain",
    "om": "oman",
    "jo": "jordan",
    "mena": "middle east",
    "middle-east": "middle east",
    "gulf": "middle east",
    "gcc": "middle east",
    "arab": "middle east",
}

REGION_DISPLAY_NAMES: dict[str, str] = {
    "egypt": "Egypt",
    "saudi arabia": "Saudi Arabia",
    "united arab emirates": "United Arab Emirates",
    "qatar": "Qatar",
    "kuwait": "Kuwait",
    "bahrain": "Bahrain",
    "oman": "Oman",
    "jordan": "Jordan",
    "middle east": "Middle East / MENA",
}

#: Default target for social scans and MENA-wide searches.
DEFAULT_REGIONS: list[str] = [
    "egypt",
    "saudi arabia",
    "united arab emirates",
    "qatar",
    "kuwait",
    "bahrain",
    "oman",
    "jordan",
]


def canonical_region(name: str | None) -> str | None:
    """Normalize aliases (EG, KSA, UAE, Dubai, MENA...) to a canonical key."""
    if not name:
        return None
    key = str(name).strip().lower().replace("_", " ")
    key = MENA_ALIASES.get(key, key)
    if key in MENA_COUNTRY_TERMS:
        return key
    if key in REGION_DISPLAY_NAMES:
        return key
    return None


def resolve_regions(countries: Iterable[str] | None) -> list[str]:
    """Return canonical MENA keys for the requested countries.

    Unknown names are kept as their lowercased value so custom locations still
    work; empty/None falls back to the MENA default list.
    """
    if not countries:
        return list(DEFAULT_REGIONS)

    resolved: list[str] = []
    for raw in countries:
        canonical = canonical_region(raw)
        value = canonical or str(raw).strip().lower()
        if value and value not in resolved:
            resolved.append(value)
    return resolved or list(DEFAULT_REGIONS)


def region_terms(countries: Iterable[str] | None) -> list[str]:
    """Expand countries/aliases into de-duplicated search terms."""
    terms: list[str] = []
    for region in resolve_regions(countries):
        candidates = MENA_COUNTRY_TERMS.get(region, [region])
        for term in candidates:
            if term not in terms:
                terms.append(term)
    return terms


def region_display_name(name: str | None) -> str:
    canonical = canonical_region(name)
    if canonical:
        return REGION_DISPLAY_NAMES.get(canonical, canonical.title())
    return str(name or "").strip().title()


#: Umbrella terms accepted in addition to individual country/city names.
REGION_UMBRELLA_TERMS: list[str] = ["Middle East", "MENA", "GCC", "Gulf", "EMEA", "Arab"]


def region_match_terms(countries: Iterable[str] | None) -> list[str]:
    """Terms used to verify that a post actually belongs to the selected region."""
    terms = region_terms(countries)
    for term in REGION_UMBRELLA_TERMS:
        if term not in terms:
            terms.append(term)
    return terms


def matches_region(text: str | None, countries: Iterable[str] | None) -> bool:
    """True when the text mentions one of the selected countries/cities/region."""
    if not text:
        return False
    lowered = text.lower()
    return any(term.lower() in lowered for term in region_match_terms(countries))
