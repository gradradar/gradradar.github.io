"""Turn a job advert into a short, readable digest.

Adverts open with paragraphs of company mission statement and close with
diversity boilerplate. The useful part - what the job is, what you'd do, what
they want - sits in the middle. This pulls that out so the card can show
something worth reading instead of the first 400 characters.
"""
from __future__ import annotations

import re

# Section headings adverts actually use, mapped to what we want them for.
ROLE_HEADINGS = re.compile(
    r"^\s*(about the (role|job|opportunity|position)|the (role|job|opportunity)|"
    r"role (overview|summary|purpose)|job (description|purpose|summary)|"
    r"purpose of the role|what (is )?the (role|job) involves|overview)\s*[:\-]?\s*$",
    re.I)
DO_HEADINGS = re.compile(
    r"^\s*(what you.{0,3}ll (be )?(do|doing)|responsibilities|key responsibilities|"
    r"your responsibilities|duties|the day to day|day[- ]to[- ]day|"
    r"what you will do|main duties|accountabilities|your role)\s*[:\-]?\s*$", re.I)
WANT_HEADINGS = re.compile(
    r"^\s*(what we.{0,3}re looking for|requirements|about you|who you are|"
    r"skills( and experience)?|qualifications|essential|you.{0,3}ll (have|need)|"
    r"what you.{0,3}ll bring|experience required|candidate profile)\s*[:\-]?\s*$",
    re.I)

# Whole lines never worth showing.
JUNK = re.compile(
    r"(equal opportunit|diversity and inclusion|regardless of race|"
    r"we celebrate diversity|reasonable adjustment|right to work|"
    r"privacy (policy|notice)|cookie|gdpr|no agencies|recruitment agencies|"
    r"click (here|apply)|apply now|follow us on|^\s*$)", re.I)

# Openings that are company blurb, not the job.
BLURB_START = re.compile(
    r"^(about (us|the company|our client)|who we are|our story|company overview|"
    r"hello|hi there|welcome|we are|we.{0,3}re a|founded in|established in|"
    r"our mission|at [A-Z])", re.I)

BULLET = re.compile(r"^\s*[•‣▪●\*\-–—·]\s*")


def _lines(text: str) -> list[str]:
    out = []
    for raw in (text or "").splitlines():
        line = BULLET.sub("", raw).strip()
        if line and not JUNK.search(line):
            out.append(line)
    return out


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip() for p in parts if p.strip()]


# Sentences that talk to the applicant about the job, rather than about the
# company's mission, are what we want.
ROLE_VOICE = re.compile(
    r"\b(you.{0,3}ll|you will|you.{0,3}d be|your role|this role|the role|"
    r"this position|we.{0,3}re looking for|reporting to|responsible for|"
    r"join (our|the|us)|as (a|an|our) |in this (role|position)|"
    r"the successful (candidate|applicant)|day[- ]to[- ]day)\b", re.I)

COMPANY_VOICE = re.compile(
    r"\b(we are a|we.{0,3}re a|is a leading|is a next[- ]generation|our mission|"
    r"our vision|our values|our strategic priorit|founded in|established in|"
    r"great place to work|we believe|our culture|our story|we started|"
    r"headquartered|we have over|customers worldwide|market leader)\b", re.I)


def _score_sentence(sentence: str, title: str) -> int:
    score = 0
    if ROLE_VOICE.search(sentence):
        score += 4
    if COMPANY_VOICE.search(sentence):
        score -= 5
    if BLURB_START.match(sentence):
        score -= 3
    # Naming the job itself is a strong signal.
    words = [w for w in re.findall(r"[a-z]{4,}", (title or "").lower())][:4]
    if words and any(w in sentence.lower() for w in words):
        score += 2
    if 70 <= len(sentence) <= 260:
        score += 1
    return score


def role_gist(text: str, title: str = "", limit: int = 260) -> str:
    """One or two sentences describing the job, skipping company blurb."""
    lines = _lines(text)

    # Prefer whatever follows an "About the role" style heading.
    for i, line in enumerate(lines):
        if ROLE_HEADINGS.match(line):
            for follow in lines[i + 1: i + 5]:
                if len(follow) > 60 and not BLURB_START.match(follow):
                    return _trim(follow, limit)

    # Otherwise score every early sentence and take the most role-like one.
    candidates: list[tuple[int, int, str]] = []
    for order, line in enumerate(lines[:40]):
        if len(line) < 50:
            continue
        for sentence in _sentences(line):
            if len(sentence) < 45:
                continue
            score = _score_sentence(sentence, title)
            if score > 0:
                candidates.append((score, -order, sentence))
    if candidates:
        candidates.sort(reverse=True)
        return _trim(candidates[0][2], limit)

    for line in lines:
        if len(line) > 40:
            return _trim(line, limit)
    return ""


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = cut.rfind(". ")
    if stop > limit * 0.5:
        return cut[: stop + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def _section_items(lines: list[str], heading: re.Pattern, cap: int = 4) -> list[str]:
    """Short list items following a heading - these are usually the real detail."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if not heading.match(line):
            continue
        for follow in lines[i + 1: i + 14]:
            if ROLE_HEADINGS.match(follow) or DO_HEADINGS.match(follow) \
                    or WANT_HEADINGS.match(follow):
                break
            item = _trim(follow, 150)
            if 25 <= len(item) <= 150 and item not in out:
                out.append(item)
            if len(out) >= cap:
                return out
        if out:
            return out
    return out


def highlights(text: str) -> dict[str, list[str]]:
    """{'does': [...], 'wants': [...]} - what the job involves and asks for."""
    lines = _lines(text)
    return {
        "does": _section_items(lines, DO_HEADINGS, 4),
        "wants": _section_items(lines, WANT_HEADINGS, 4),
    }
