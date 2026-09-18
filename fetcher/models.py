"""The normalised shape every source converts into."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field


@dataclass
class RawJob:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    posted: str | None = None          # ISO-8601 date string
    salary_min: float | None = None
    salary_max: float | None = None
    salary_text: str = ""
    closes: str | None = None          # ISO date, when the source states one
    lat: float | None = None           # where the source gives coordinates
    lon: float | None = None
    remote: bool = False
    extra: dict = field(default_factory=dict)

    def key(self) -> str:
        """Stable id from the things that actually identify a posting."""
        norm = f"{_slim(self.title)}|{_slim(self.company)}|{slim_location(self.location)}"
        return hashlib.sha1(norm.encode()).hexdigest()[:14]


def _slim(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\(.*?\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


# Boards spell the same place a dozen ways: "London", "London, England",
# "London, England, United Kingdom", "UK - London".
_GEO_NOISE = re.compile(
    r"\b(england|scotland|wales|northern ireland|united kingdom|uk|gb|"
    r"great britain|remote|hybrid|on[- ]site)\b", re.I)


def slim_location(location: str) -> str:
    """Reduce a location string to the town, for comparison purposes."""
    value = _GEO_NOISE.sub(" ", location or "")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).strip().lower()
    # Multi-site postings list several towns; the first is enough to compare.
    return value.split(" and ")[0].strip()


def clean_title(title: str) -> str:
    """Strip the ref numbers and location suffixes boards bolt onto titles."""
    # Some boards hand back titles already HTML-escaped; escaping again in the
    # browser would render a literal "&amp;".
    title = html.unescape(title or "")
    t = re.sub(r"\s*[\[(]?(job\s*)?(ref|req|id)[.:# ]\s*[a-z0-9-]+[\])]?\s*$", "", title, flags=re.I)
    t = re.sub(r"\s*[-–|]\s*(london|uk|united kingdom|remote|hybrid)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -–|,")
    return t or title.strip()
