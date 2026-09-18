"""Adzuna and Reed: UK-wide job boards with free official APIs.

Both need a key (free, self-serve). Without one the source simply yields
nothing, so the ATS boards still work out of the box.
"""
from __future__ import annotations

import base64
import os

from ..http import FetchError, qs, request_json
from ..models import RawJob, clean_title
from ..text import strip_html

# Adzuna's free/trial plan is capped per day. Blowing through it mid-run gives
# silent partial data, so spend the budget deliberately instead.
ADZUNA_DAILY_BUDGET = int(os.environ.get("ADZUNA_DAILY_BUDGET", "1500"))
_adzuna_calls = 0


def adzuna_calls_used() -> int:
    return _adzuna_calls


def adzuna_budget_left() -> int:
    return max(0, ADZUNA_DAILY_BUDGET - _adzuna_calls)


ADZUNA_ID = os.environ.get("ADZUNA_APP_ID", "").strip()
ADZUNA_KEY = os.environ.get("ADZUNA_APP_KEY", "").strip()
REED_KEY = os.environ.get("REED_API_KEY", "").strip()

# Titles we never want back from a broad keyword search.
EXCLUDE_WORDS = ("senior", "head", "director", "principal", "lead", "manager")


def adzuna_enabled() -> bool:
    return bool(ADZUNA_ID and ADZUNA_KEY)


def reed_enabled() -> bool:
    return bool(REED_KEY)


def adzuna(term: str, *, pages: int = 2, max_days_old: int = 45,
           where: str = "") -> list[RawJob]:
    if not adzuna_enabled():
        return []
    global _adzuna_calls
    out: list[RawJob] = []
    for page in range(1, pages + 1):
        if _adzuna_calls >= ADZUNA_DAILY_BUDGET:
            break
        _adzuna_calls += 1
        url = qs(f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}", {
            "app_id": ADZUNA_ID,
            "app_key": ADZUNA_KEY,
            "results_per_page": 50,
            "what": term,
            "what_exclude": " ".join(EXCLUDE_WORDS),
            "where": where,
            "max_days_old": max_days_old,
            "sort_by": "date",
            "content-type": "application/json",
        })
        try:
            data = request_json(url)
        except FetchError:
            break
        results = data.get("results") or []
        for j in results:
            out.append(RawJob(
                title=clean_title(j.get("title") or ""),
                company=(j.get("company") or {}).get("display_name") or "",
                location=(j.get("location") or {}).get("display_name") or "",
                url=j.get("redirect_url") or "",
                source="adzuna",
                # Adzuna only returns a teaser, not the full advert.
                description=strip_html(j.get("description") or ""),
                posted=(j.get("created") or "")[:10] or None,
                salary_min=j.get("salary_min"),
                salary_max=j.get("salary_max"),
                extra={"team": (j.get("category") or {}).get("label") or "",
                       "commitment": j.get("contract_time") or j.get("contract_type") or "",
                       "query": term},
            ))
        if len(results) < 50:
            break
    return out


def _reed_headers() -> dict[str, str]:
    token = base64.b64encode(f"{REED_KEY}:".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def reed(term: str, *, pages: int = 2, location: str = "",
         title_filter=None) -> list[RawJob]:
    """Search results carry only a snippet; full adverts are fetched one by one
    for the postings that survive `title_filter`."""
    if not reed_enabled():
        return []
    out: list[RawJob] = []
    per_page = 100
    for page in range(pages):
        url = qs("https://www.reed.co.uk/api/1.0/search", {
            "keywords": term,
            "locationName": location,
            "distanceFromLocation": 15 if location else None,
            "resultsToTake": per_page,
            "resultsToSkip": page * per_page,
        })
        try:
            data = request_json(url, headers=_reed_headers())
        except FetchError:
            break
        results = data.get("results") or []
        for j in results:
            title = clean_title(j.get("jobTitle") or "")
            where = j.get("locationName") or ""
            if title_filter and not title_filter(title, where):
                continue
            body = strip_html(j.get("jobDescription") or "")
            job_id = j.get("jobId")
            if job_id:
                try:
                    detail = request_json(
                        f"https://www.reed.co.uk/api/1.0/jobs/{job_id}",
                        headers=_reed_headers())
                    full = strip_html(detail.get("jobDescription") or "")
                    if len(full) > len(body):
                        body = full
                except FetchError:
                    pass
            out.append(RawJob(
                title=title,
                company=j.get("employerName") or "",
                location=where,
                url=j.get("jobUrl") or f"https://www.reed.co.uk/jobs/{job_id}",
                source="reed",
                description=body,
                posted=_reed_date(j.get("date")),
                salary_min=j.get("minimumSalary"),
                salary_max=j.get("maximumSalary"),
                closes=_reed_date(j.get("expirationDate")),
                extra={"query": term},
            ))
        if len(results) < per_page:
            break
    return out


def _reed_date(value: str | None) -> str | None:
    """Reed sends dd/mm/yyyy."""
    if not value:
        return None
    parts = value.split("/")
    if len(parts) == 3:
        day, month, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return value[:10]
