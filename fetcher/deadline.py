"""Find the application closing date.

Almost no ATS exposes a deadline field, but graduate adverts nearly always
state one in prose ("applications close on 30 November"). Grad schemes in
particular run to hard deadlines, so this is worth digging out.
"""
from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

# "30 November 2026" / "30th Nov"
_DMY = re.compile(rf"\b{_DAY}\s+(?:of\s+)?({_MONTH_ALT})\b\.?(?:\s*,?\s*(\d{{4}}))?", re.I)
# "November 30, 2026"
_MDY = re.compile(rf"\b({_MONTH_ALT})\b\.?\s+{_DAY}(?:\s*,?\s*(\d{{4}}))?", re.I)
# "30/11/2026" or "30-11-26" (UK day-first)
_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
# "2026-11-30"
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Phrases that introduce a deadline. The date must appear soon after one.
CUES = re.compile(
    r"(closing date|closes? on|closes\b|close on|application deadline|"
    r"deadline for applications?|deadline is|deadline:|applications? close|"
    r"apply by|applications? must be (?:received|submitted) by|"
    r"last date for applications?|final date|cut[- ]off date|"
    r"submit your application by|applications? will close)", re.I)

ROLLING = re.compile(
    r"(rolling basis|on a rolling|reviewed on a rolling|until the (?:role|position)s? (?:is|are) filled|"
    r"until filled|no (?:fixed|set) (?:closing|deadline)|as soon as (?:we find|possible)|"
    r"we assess applications as they (?:arrive|come))", re.I)

WINDOW = 90  # characters after the cue to look for a date


def _year_for(day: int, month: int, reference: date, explicit: int | None) -> int | None:
    if explicit:
        return explicit + 2000 if explicit < 100 else explicit
    # No year given: choose the next occurrence on or after the posting date.
    for year in (reference.year, reference.year + 1):
        try:
            if date(year, month, day) >= reference:
                return year
        except ValueError:
            return None
    return None


def _parse_near(chunk: str, reference: date) -> date | None:
    for match in _ISO.finditer(chunk):
        y, m, d = (int(g) for g in match.groups())
        try:
            return date(y, m, d)
        except ValueError:
            continue
    for match in _DMY.finditer(chunk):
        day, mon, yr = match.group(1), match.group(2).lower(), match.group(3)
        month = MONTHS.get(mon)
        if not month:
            continue
        year = _year_for(int(day), month, reference, int(yr) if yr else None)
        try:
            if year:
                return date(year, month, int(day))
        except ValueError:
            continue
    for match in _MDY.finditer(chunk):
        mon, day, yr = match.group(1).lower(), match.group(2), match.group(3)
        month = MONTHS.get(mon)
        if not month:
            continue
        year = _year_for(int(day), month, reference, int(yr) if yr else None)
        try:
            if year:
                return date(year, month, int(day))
        except ValueError:
            continue
    for match in _NUM.finditer(chunk):
        d, m, y = (int(g) for g in match.groups())
        if m > 12:
            d, m = m, d
        y = y + 2000 if y < 100 else y
        try:
            return date(y, m, d)
        except ValueError:
            continue
    return None


def find_deadline(description: str, posted: str | None = None
                  ) -> tuple[str | None, bool]:
    """Return (ISO closing date or None, is_rolling)."""
    if not description:
        return None, False

    reference = date.today()
    if posted:
        try:
            reference = date.fromisoformat(posted[:10])
        except ValueError:
            pass

    best: date | None = None
    for cue in CUES.finditer(description):
        chunk = description[cue.end(): cue.end() + WINDOW]
        found = _parse_near(chunk, reference)
        if not found:
            continue
        # Sanity: a deadline in the distant past or 2 years out is a misparse.
        if found < reference or (found - reference).days > 550:
            continue
        if best is None or found < best:
            best = found

    if best:
        return best.isoformat(), False
    return None, bool(ROLLING.search(description))
