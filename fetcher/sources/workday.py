"""Workday career sites.

Workday runs most large UK graduate schemes (Big Four, banks, insurers, FTSE
corporates). There is no documented public API, but the career sites are driven
by a JSON endpoint that serves exactly what the page renders.

Two things make it worth the extra work: the volume of graduate schemes, and the
fact that the detail payload carries a real `endDate`, so these postings come
with genuine application deadlines rather than parsed-from-prose guesses.
"""
from __future__ import annotations

from ..http import FetchError, request_json
from ..models import RawJob, clean_title
from ..text import strip_html

# Workday rejects the default library user agent on some tenants.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SEARCH_TERMS = ["graduate", "intern", "placement", "trainee", "apprentice"]
PAGE = 20
MAX_PAGES = 5


def _headers(host: str, site: str) -> dict[str, str]:
    return {
        "User-Agent": BROWSER_UA,
        "Referer": f"https://{host}/en-US/{site}",
        "Origin": f"https://{host}",
    }


def fetch(spec: str, *, title_filter=None, terms: list[str] | None = None,
          max_pages: int = MAX_PAGES) -> list[RawJob]:
    """`spec` is "tenant|datacentre|site", as stored in config/workday.yml."""
    try:
        tenant, dc, site = spec.split("|")
    except ValueError:
        raise FetchError(f"bad workday spec {spec!r}, want tenant|datacentre|site")

    host = f"{tenant}.{dc}.myworkdayjobs.com"
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    headers = _headers(host, site)
    company = tenant.replace("-", " ").title()

    # Collect candidate postings across the search terms, de-duplicated by path.
    candidates: dict[str, dict] = {}
    for term in (terms or SEARCH_TERMS):
        for page in range(max_pages):
            payload = {"appliedFacets": {}, "limit": PAGE,
                       "offset": page * PAGE, "searchText": term}
            try:
                data = request_json(f"{base}/jobs", method="POST", body=payload,
                                    headers=headers)
            except FetchError:
                break
            postings = data.get("jobPostings") or []
            for post in postings:
                path = post.get("externalPath")
                if path:
                    candidates.setdefault(path, post)
            if len(postings) < PAGE:
                break

    out: list[RawJob] = []
    for path, post in candidates.items():
        title = clean_title(post.get("title") or "")
        where = post.get("locationsText") or ""
        # Filter before paying for the detail request - these boards are global.
        if title_filter and not title_filter(title, where):
            continue
        try:
            detail = request_json(f"{base}{path}", headers=headers)
        except FetchError:
            continue
        info = detail.get("jobPostingInfo") or {}
        body = strip_html(info.get("jobDescription"))
        location = info.get("location") or where
        country = info.get("country") or {}
        if isinstance(country, dict):
            country_name = country.get("descriptor") or ""
            if country_name and country_name.lower() not in location.lower():
                location = f"{location}, {country_name}".strip(", ")

        out.append(RawJob(
            title=title,
            company=company,
            location=location,
            url=info.get("externalUrl") or f"https://{host}/en-US/{site}{path}",
            source="workday",
            description=body,
            posted=(info.get("startDate") or "")[:10] or None,
            # Workday states a real closing date - rare and valuable.
            closes=(info.get("endDate") or "")[:10] or None,
            extra={"reqId": info.get("jobReqId") or "",
                   "commitment": post.get("timeType") or ""},
        ))
    return out
