"""Keyless applicant-tracking-system boards.

These are the public JSON endpoints that power companies' own careers pages, so
they are first-party, complete, and far more stable than scraping an aggregator.
"""
from __future__ import annotations

import html as html_mod
from datetime import datetime, timezone

from ..http import FetchError, request_json
from ..models import RawJob, clean_title
from ..text import strip_html


def _iso(value) -> str | None:
    """Coerce the assorted date formats these APIs use into an ISO date."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return str(value)[:10] or None


def _pretty(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


# --------------------------------------------------------------------------
def greenhouse(slug: str) -> list[RawJob]:
    board = f"https://boards-api.greenhouse.io/v1/boards/{slug}"
    company = _pretty(slug)
    try:
        meta = request_json(board)
        company = meta.get("name") or company
    except FetchError:
        pass
    data = request_json(f"{board}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        content = html_mod.unescape(j.get("content") or "")
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=company,
            location=(j.get("location") or {}).get("name") or "",
            url=j.get("absolute_url") or "",
            source="greenhouse",
            description=strip_html(content),
            posted=_iso(j.get("updated_at") or j.get("first_published")),
        ))
    return out


def lever(slug: str) -> list[RawJob]:
    data = request_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        body = " ".join(filter(None, [
            j.get("descriptionPlain") or strip_html(j.get("description")),
            *[strip_html(sec.get("content")) for sec in (j.get("lists") or [])],
            j.get("additionalPlain") or "",
        ]))
        out.append(RawJob(
            title=clean_title(j.get("text") or ""),
            company=_pretty(slug),
            location=cats.get("location") or "",
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            source="lever",
            description=body,
            posted=_iso(j.get("createdAt")),
            extra={"team": cats.get("team") or "", "commitment": cats.get("commitment") or ""},
        ))
    return out


def ashby(slug: str) -> list[RawJob]:
    data = request_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [
            s.get("location") or "" for s in (j.get("secondaryLocations") or [])]
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=_pretty(slug),
            location=", ".join(filter(None, dict.fromkeys(locs))),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            source="ashby",
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            posted=_iso(j.get("publishedAt")),
            remote=bool(j.get("isRemote")),
            extra={"team": j.get("team") or j.get("department") or "",
                   "commitment": j.get("employmentType") or ""},
        ))
    return out


def workable(slug: str) -> list[RawJob]:
    data = request_json(
        f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    company = data.get("name") or _pretty(slug)
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        body = " ".join(filter(None, [
            strip_html(j.get("description")),
            strip_html(j.get("requirements")),
        ]))
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=company,
            location=loc,
            url=j.get("url") or j.get("application_url") or "",
            source="workable",
            description=body,
            posted=_iso(j.get("published_on") or j.get("created_at")),
            remote=bool(j.get("telecommuting")),
            extra={"team": j.get("department") or "",
                   "commitment": j.get("employment_type") or ""},
        ))
    return out


def smartrecruiters(slug: str, *, title_filter=None) -> list[RawJob]:
    """Listing has no description, so only the postings that pass `title_filter`
    get a second request for their full advert."""
    out: list[RawJob] = []
    offset, limit = 0, 100
    while True:
        page = request_json(
            "https://api.smartrecruiters.com/v1/companies/"
            f"{slug}/postings?limit={limit}&offset={offset}")
        items = page.get("content") or []
        for j in items:
            loc = j.get("location") or {}
            country = (loc.get("country") or "").upper()
            where = ", ".join(filter(None, [
                loc.get("city"), loc.get("region"),
                "United Kingdom" if country == "GB" else country]))
            title = clean_title(j.get("name") or "")
            if title_filter and not title_filter(title, where):
                continue
            body = ""
            try:
                detail = request_json(
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}")
                sections = ((detail.get("jobAd") or {}).get("sections") or {})
                body = " ".join(
                    strip_html((sections.get(part) or {}).get("text"))
                    for part in ("companyDescription", "jobDescription",
                                 "qualifications", "additionalInformation"))
            except (FetchError, KeyError):
                pass
            out.append(RawJob(
                title=title,
                company=((j.get("company") or {}).get("name")) or _pretty(slug),
                location=where,
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                source="smartrecruiters",
                description=body,
                posted=_iso(j.get("releasedDate")),
                remote=bool(loc.get("remote")),
                extra={"team": (j.get("department") or {}).get("label") or "",
                       "experience": (j.get("experienceLevel") or {}).get("id") or "",
                       "commitment": (j.get("typeOfEmployment") or {}).get("label") or ""},
            ))
        total = page.get("totalFound") or 0
        offset += limit
        if offset >= total or not items:
            break
    return out


def recruitee(slug: str) -> list[RawJob]:
    data = request_json(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        loc = ", ".join(filter(None, [j.get("city"), j.get("country")])) or j.get("location") or ""
        body = " ".join(filter(None, [
            strip_html(j.get("description")), strip_html(j.get("requirements"))]))
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=j.get("company_name") or _pretty(slug),
            location=loc,
            url=j.get("careers_url") or j.get("careers_apply_url") or "",
            source="recruitee",
            description=body,
            posted=_iso(j.get("published_at")),
            remote=str(j.get("remote") or "").lower() in ("true", "1", "yes"),
            extra={"team": j.get("department") or ""},
        ))
    return out


ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "recruitee": recruitee,
}


# ---------------------------------------------------------------------------
# Workable global search
#
# Unlike the per-company endpoints above, this searches across every employer
# using Workable at once - so it finds graduate schemes at companies that are
# not in config/employers.yml and that we would otherwise never know to ask for.
# ---------------------------------------------------------------------------
import urllib.parse  # noqa: E402  (kept beside the function that needs it)

WORKABLE_SEARCH = "https://jobs.workable.com/api/v1/jobs"
WORKABLE_MAX_PAGES = 8


def workable_search(term: str, *, location: str = "united kingdom",
                    max_pages: int = WORKABLE_MAX_PAGES) -> list[RawJob]:
    out: list[RawJob] = []
    token: str | None = None

    for _ in range(max_pages):
        query = urllib.parse.urlencode({"query": term, "location": location})
        url = f"{WORKABLE_SEARCH}?{query}"
        if token:
            url += "&pageToken=" + urllib.parse.quote(token)
        try:
            data = request_json(url)
        except FetchError:
            break

        jobs = data.get("jobs") or []
        for j in jobs:
            loc = j.get("location") or {}
            where = ", ".join(filter(None, [
                loc.get("city"), loc.get("subregion"), loc.get("countryName")]))
            if not where:
                locs = j.get("locations")
                where = locs[0] if isinstance(locs, list) and locs else ""
            company = j.get("company") or {}
            body = " ".join(filter(None, [
                strip_html(j.get("description")),
                strip_html(j.get("requirementsSection")),
                strip_html(j.get("benefitsSection")),
            ]))
            out.append(RawJob(
                title=clean_title(j.get("title") or ""),
                company=(company.get("title") or company.get("name") or "")
                        if isinstance(company, dict) else str(company),
                location=where,
                url=j.get("url") or "",
                source="workable-search",
                description=body,
                posted=_iso(j.get("created") or j.get("updated")),
                remote=str(j.get("workplace") or "").lower() == "remote",
                extra={"team": j.get("department") or "",
                       "commitment": j.get("employmentType") or "",
                       "query": term},
            ))
        token = data.get("nextPageToken")
        if not token or not jobs:
            break
    return out
