"""Spot schemes that are announced but not open yet.

Big graduate schemes often put a placeholder up months early: "applications
open in September", "register your interest", "join our talent community".
Those are worth knowing about - you can diarise them - but they are useless
mixed in with roles you can apply to today.

Note the limit: this only finds schemes with *some* posting live. A scheme with
no advert at all is invisible to every source we have.
"""
from __future__ import annotations

import re
from datetime import date

from .deadline import _parse_near  # same date parsing, different cue words

# "Applications open on 1 October", "opens September 2027"
OPEN_CUES = re.compile(
    r"(applications? (will )?opens?|registration opens?|opens? for applications|"
    r"applications? open on|we open applications|recruitment opens?|"
    r"applications? go live|live from|open from|opening on)", re.I)

# Placeholder adverts with no date attached.
NOT_OPEN_YET = re.compile(
    r"(register your interest|expression of interest|talent (pool|community|network)|"
    r"join our talent|not (yet )?(currently )?open|applications (are )?not yet open|"
    r"this (exact )?role may not be open|could open in the near future|"
    r"be the first to know|notify me when|check back (soon|later)|"
    r"coming soon|opening soon|we are not currently recruiting|"
    r"keep an eye out|sign up for (job )?alerts)", re.I)

# Intake wording: "September 2027 intake", "2027 programme"
INTAKE_RE = re.compile(
    r"\b(intake|cohort|start date|starting|commencing|programme starts?|"
    r"scheme starts?)\b[^.\n]{0,40}(20\d{2})", re.I)

WINDOW = 90


def find_opening(description: str, posted: str | None = None
                 ) -> tuple[str | None, bool]:
    """(ISO date applications open, or None; is it a not-yet-open placeholder?)"""
    if not description:
        return None, False

    reference = date.today()
    if posted:
        try:
            reference = date.fromisoformat(posted[:10])
        except ValueError:
            pass

    best: date | None = None
    for cue in OPEN_CUES.finditer(description):
        chunk = description[cue.end(): cue.end() + WINDOW]
        found = _parse_near(chunk, reference)
        if not found:
            continue
        # Only future openings are interesting; a past one just means it's open.
        if found <= date.today() or (found - date.today()).days > 550:
            continue
        if best is None or found < best:
            best = found

    placeholder = bool(NOT_OPEN_YET.search(description))
    return (best.isoformat() if best else None), placeholder


def intake_year(title: str, description: str = "") -> str:
    """The cohort year, where the advert names one."""
    hay = f"{title} {description[:1200]}"
    match = INTAKE_RE.search(hay)
    if match:
        return match.group(2)
    # Titles often just carry the year: "Graduate Scheme 2027".
    year = re.search(r"\b(20[2-3]\d)\b", title or "")
    if year and int(year.group(1)) >= date.today().year:
        return year.group(1)
    return ""
