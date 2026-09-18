"""Keyless job aggregators.

These need no API key at all, so they work out of the box. They skew towards
remote and tech roles, so the UK filter discards most of what they return - but
they cost nothing to include and occasionally surface something the employer
boards miss.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..http import request_json
from ..models import RawJob, clean_title
from ..text import strip_html


def _iso(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return str(value)[:10]


def arbeitnow() -> list[RawJob]:
    data = request_json("https://www.arbeitnow.com/api/job-board-api")
    out = []
    for j in data.get("data", []):
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=j.get("company_name") or "",
            location=j.get("location") or "",
            url=j.get("url") or "",
            source="arbeitnow",
            description=strip_html(j.get("description")),
            posted=_iso(j.get("created_at")),
            remote=bool(j.get("remote")),
            extra={"commitment": ", ".join(j.get("job_types") or [])},
        ))
    return out


def remotive() -> list[RawJob]:
    data = request_json("https://remotive.com/api/remote-jobs?limit=200")
    out = []
    for j in data.get("jobs", []):
        out.append(RawJob(
            title=clean_title(j.get("title") or ""),
            company=j.get("company_name") or "",
            location=j.get("candidate_required_location") or "Remote",
            url=j.get("url") or "",
            source="remotive",
            description=strip_html(j.get("description")),
            posted=_iso(j.get("publication_date")),
            remote=True,
            extra={"team": j.get("category") or "",
                   "commitment": j.get("job_type") or ""},
        ))
    return out


def jobicy() -> list[RawJob]:
    data = request_json("https://jobicy.com/api/v2/remote-jobs?count=50")
    out = []
    for j in data.get("jobs", []):
        out.append(RawJob(
            title=clean_title(j.get("jobTitle") or ""),
            company=j.get("companyName") or "",
            location=j.get("jobGeo") or "Remote",
            url=j.get("url") or "",
            source="jobicy",
            description=strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
            posted=_iso(j.get("pubDate")),
            remote=True,
            extra={"team": ", ".join(j.get("jobIndustry") or []),
                   "commitment": ", ".join(j.get("jobType") or [])},
        ))
    return out


ADAPTERS = {"arbeitnow": arbeitnow, "remotive": remotive, "jobicy": jobicy}
