"""Pull pay out of advert text.

Only Adzuna and Reed expose structured salary fields, and Ashby a compensation
block. Everywhere else the pay is stated in prose if at all, so this digs it out
and normalises it - including hourly rates, which is what matters for bar and
retail work.
"""
from __future__ import annotations

import re

MONEY = r"£\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d{1,2})?)\s*([kK])?"

RANGE_RE = re.compile(
    MONEY + r"\s*(?:-|–|—|to|and)\s*" + MONEY, re.I)
SINGLE_RE = re.compile(MONEY)

PER_HOUR = re.compile(
    r"\b(per hour|an hour|/\s?h(ou)?r|p\.?h\b|hourly|per hr)\b", re.I)
PER_DAY = re.compile(r"\b(per day|a day|daily rate|/\s?day|per diem)\b", re.I)
PER_YEAR = re.compile(
    r"\b(per annum|pa\b|p\.a\.|a year|per year|annually|annual salary|salary)\b", re.I)

# Where pay is usually mentioned; searching the whole advert produces nonsense
# like "£2 billion in revenue".
CUES = re.compile(
    r"(salary|salaries|pay|paying|compensation|remuneration|rate of pay|"
    r"hourly rate|wage|wages|package|earn|earning|starting at|up to|"
    r"we offer|offering|£)", re.I)

NOISE = re.compile(
    r"\b(revenue|turnover|raised|funding|valuation|market cap|billion|"
    r"assets under management|investment of|worth over|donated|budget of|"
    r"portfolio of|saving|savings of)\b", re.I)

# Commission and bonus figures are not pay you can count on, and quoting them as
# salary makes a £24k sales job outrank a £45k analyst role.
COMMISSION = re.compile(
    r"\b(ote\b|on[- ]target earnings|commission|uncapped|bonus|incentive|"
    r"tips|realistic earnings|earning potential|earn up to|take home up to)\b", re.I)

HOURS_PER_YEAR = 37.5 * 52   # a standard UK full-time year
DAYS_PER_YEAR = 260


def _num(value: str, kilo: str | None) -> float:
    n = float(value.replace(",", ""))
    if kilo:
        n *= 1000
    return n


def _period(window: str, amount: float) -> str:
    if PER_HOUR.search(window):
        return "hour"
    if PER_DAY.search(window):
        return "day"
    if PER_YEAR.search(window):
        return "year"
    # Fall back on magnitude: nobody earns £12 a year or £45,000 an hour.
    if amount <= 100:
        return "hour"
    if amount < 1000:
        return "day"
    return "year"


def _annualise(amount: float, period: str) -> float:
    if period == "hour":
        return amount * HOURS_PER_YEAR
    if period == "day":
        return amount * DAYS_PER_YEAR
    return amount


def _plausible(amount: float, period: str) -> bool:
    if period == "hour":
        return 8 <= amount <= 150        # below NMW or above £150/h is a misread
    if period == "day":
        return 50 <= amount <= 2000
    return 10_000 <= amount <= 400_000


def find_salary(text: str) -> tuple[float | None, float | None, str, str]:
    """Return (min, max, period, display text). All None/empty if not found."""
    if not text or "£" not in text:
        return None, None, "", ""

    best: tuple[float, float, str] | None = None
    for match in re.finditer(r"£", text):
        start = max(0, match.start() - 90)
        window = text[start: match.start() + 120]
        # Only the words immediately BEFORE the figure decide what it is:
        # "OTE £40,000" is commission, but "salary £24,000 plus OTE" is pay.
        preceding = text[max(0, match.start() - 45): match.start()]
        if NOISE.search(window) or COMMISSION.search(preceding):
            continue
        if not CUES.search(window):
            continue

        chunk = text[match.start(): match.start() + 60]
        pair = RANGE_RE.match(chunk)
        if pair:
            lo = _num(pair.group(1), pair.group(2))
            hi = _num(pair.group(3), pair.group(4))
            if hi < lo:
                lo, hi = hi, lo
            period = _period(window, lo)
            if _plausible(lo, period) and _plausible(hi, period):
                if best is None or lo < best[0]:
                    best = (lo, hi, period)
            continue

        one = SINGLE_RE.match(chunk)
        if one:
            amount = _num(one.group(1), one.group(2))
            period = _period(window, amount)
            if _plausible(amount, period):
                if best is None or amount < best[0]:
                    best = (amount, amount, period)

    if not best:
        return None, None, "", ""
    lo, hi, period = best
    return lo, hi, period, format_salary(lo, hi, period)


def format_salary(lo: float | None, hi: float | None, period: str = "year") -> str:
    def fmt(v: float) -> str:
        if period == "hour":
            return f"£{v:,.2f}"      # always 2dp: "£11.50/hr", not "£11.5/hr"
        return f"£{int(round(v)):,}"

    if lo is None and hi is None:
        return ""
    suffix = {"hour": "/hr", "day": "/day"}.get(period, "")
    if lo and hi and abs(lo - hi) > 0.01:
        return f"{fmt(lo)} – {fmt(hi)}{suffix}"
    return f"{fmt(lo or hi)}{suffix}"


def annual_equivalent(lo: float | None, hi: float | None, period: str) -> int:
    """A single comparable number, so hourly and salaried roles can be sorted."""
    if lo is None and hi is None:
        return 0
    mid = ((lo or hi) + (hi or lo)) / 2
    return int(_annualise(mid, period or "year"))


# ---------------------------------------------------------------------------
# Commission and bonus, kept separate from base pay
#
# Deliberately a second field rather than part of the salary: quoting OTE as
# salary makes a £24k sales job outrank a £45k analyst role. Shown alongside so
# the upside is still visible.
# ---------------------------------------------------------------------------
OTE_RE = re.compile(
    r"\b(?:ote|on[- ]target earnings|earning potential|realistic earnings)\b"
    r"[^£\n]{0,40}" + MONEY, re.I)
COMMISSION_AMOUNT_RE = re.compile(
    r"\b(?:commission|bonus)\b[^£\n]{0,45}" + MONEY, re.I)
MONEY_THEN_OTE = re.compile(
    MONEY + r"[^£\n]{0,25}\b(?:ote|on[- ]target earnings)\b", re.I)
UNCAPPED_RE = re.compile(r"\buncapped\s+(commission|bonus|earnings)\b", re.I)
TIPS_RE = re.compile(r"\b(plus tips|tips on top|share of tips|tronc)\b", re.I)
BONUS_SCHEME_RE = re.compile(
    r"\b(performance[- ]related bonus|annual bonus|discretionary bonus|"
    r"bonus scheme|commission structure|commission scheme)\b", re.I)


def find_commission(text: str) -> str:
    """A short description of any commission, OTE, bonus or tips on offer."""
    if not text:
        return ""

    for pattern in (OTE_RE, MONEY_THEN_OTE, COMMISSION_AMOUNT_RE):
        match = pattern.search(text)
        if not match:
            continue
        groups = [g for g in match.groups() if g is not None]
        # The money capture is the last numeric group in every pattern above.
        digits = next((g for g in reversed(groups) if g and g[0].isdigit()), None)
        if not digits:
            continue
        kilo = match.group(match.lastindex) if match.lastindex else None
        amount = _num(digits, kilo if kilo in ("k", "K") else None)
        if _plausible(amount, "year"):
            label = "OTE" if pattern is not COMMISSION_AMOUNT_RE else "commission"
            return f"+ £{int(round(amount)):,} {label}"

    if UNCAPPED_RE.search(text):
        return "+ uncapped commission"
    if TIPS_RE.search(text):
        return "+ tips"
    if BONUS_SCHEME_RE.search(text):
        return "+ bonus"
    return ""
