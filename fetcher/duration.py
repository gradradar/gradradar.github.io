"""How long is it?

"Internship" covers everything from a one-week spring insight to a 13-month
industrial placement. Someone hunting a year in industry needs to tell those
apart at a glance, so dig the length out of the title or advert.
"""
from __future__ import annotations

import re

# Titles usually say it outright: "12 Month Industrial Placement".
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "eighteen": 18,
}
_NUM = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"

SPAN_RE = re.compile(
    _NUM + r"\s*[-–]?\s*(month|week|year)s?\b", re.I)
RANGE_RE = re.compile(
    _NUM + r"\s*(?:-|–|to)\s*" + _NUM + r"\s*(month|week|year)s?\b", re.I)

# Phrases that imply a length without stating a number.
IMPLIED = [
    (re.compile(r"\b(year in industry|placement year|sandwich (year|placement)|"
                r"industrial placement|12[- ]month placement)\b", re.I), "~12 months"),
    (re.compile(r"\bspring (week|insight)\b", re.I), "1 week"),
    (re.compile(r"\binsight (day|programme|program)\b", re.I), "short insight"),
    (re.compile(r"\bsummer (internship|analyst|scheme|programme|program)\b", re.I),
     "summer (~8-12 weeks)"),
    (re.compile(r"\bvacation scheme\b", re.I), "~2-4 weeks"),
    (re.compile(r"\bgraduate (scheme|programme|program)\b", re.I), "scheme (1-3 years)"),
]

# Where a duration is plausibly described, to avoid matching "5 years experience".
CUES = re.compile(
    r"(duration|length|lasts?|lasting|runs? for|placement|internship|programme|"
    r"program|scheme|contract|fixed[- ]term|starting|commencing|over a period)", re.I)
EXPERIENCE = re.compile(r"\b(experience|track record|history|working in)\b", re.I)


def _value(token: str) -> int | None:
    token = token.lower()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _phrase(amount: int, unit: str) -> str | None:
    unit = unit.lower()
    if unit == "week" and 1 <= amount <= 60:
        return f"{amount} week{'s' if amount > 1 else ''}"
    if unit == "month" and 1 <= amount <= 24:
        return f"{amount} month{'s' if amount > 1 else ''}"
    if unit == "year" and 1 <= amount <= 3:
        return f"{amount} year{'s' if amount > 1 else ''}"
    return None


def find_duration(title: str, description: str = "") -> str:
    """A short human label like "12 months", "10 weeks" or "summer"."""
    # The title is the most trustworthy source.
    for text in (title or "", description[:1800] or ""):
        if not text:
            continue
        in_title = text is title

        match = RANGE_RE.search(text)
        if match:
            lo, hi = _value(match.group(1)), _value(match.group(2))
            unit = match.group(3).lower()
            if lo and hi and _phrase(hi, unit):
                return f"{lo}–{hi} {unit}{'s' if hi > 1 else ''}"

        for match in SPAN_RE.finditer(text):
            window = text[max(0, match.start() - 60): match.end() + 40]
            # "5 years experience" is a requirement, not a duration.
            if EXPERIENCE.search(window):
                continue
            if not in_title and not CUES.search(window):
                continue
            amount, unit = _value(match.group(1)), match.group(2)
            if amount is None:
                continue
            label = _phrase(amount, unit)
            if label:
                return label

    hay = f"{title} {description[:1200]}"
    for pattern, label in IMPLIED:
        if pattern.search(hay):
            return label
    return ""
