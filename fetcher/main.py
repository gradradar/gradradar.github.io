"""Build site/data/jobs.json: the daily snapshot the static site reads.

Run locally with:  python3 -m fetcher.main
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import classify
from .config import ROOT, load_lists
from .deadline import find_deadline
from .http import FetchError
from .models import RawJob
from .sources import ats, boards
from .text import keywords, normalise_ws, summarise
from .uk import is_remote, is_uk

OUT_PATH = ROOT / "site" / "data" / "jobs.json"

# Prefer the employer's own board over an aggregator's copy of the same advert.
SOURCE_RANK = {
    "greenhouse": 5, "lever": 5, "ashby": 5, "workable": 5,
    "smartrecruiters": 5, "recruitee": 5,
    "reed": 3, "adzuna": 2,
}


def title_prefilter(title: str, location: str) -> bool:
    """Cheap gate used before paying for a per-job detail request."""
    if not is_uk(location):
        return False
    keep, _, _ = classify.is_early_career(title, "")
    return keep


def collect_ats(employers: dict[str, list[str]], log) -> list[RawJob]:
    jobs: list[RawJob] = []
    tasks = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for platform, slugs in employers.items():
            adapter = ats.ADAPTERS.get(platform)
            if not adapter:
                log(f"  ! unknown platform '{platform}' in employers.yml")
                continue
            for slug in slugs:
                if platform == "smartrecruiters":
                    tasks.append(pool.submit(adapter, slug, title_filter=title_prefilter))
                else:
                    tasks.append(pool.submit(adapter, slug))
                tasks[-1].label = f"{platform}/{slug}"  # type: ignore[attr-defined]

        for fut in as_completed(tasks):
            label = getattr(fut, "label", "?")
            try:
                found = fut.result()
                jobs.extend(found)
                log(f"  {label:<34} {len(found):>4} postings")
            except FetchError as exc:
                log(f"  {label:<34} failed: {exc}")
            except Exception as exc:  # a single bad board must not kill the run
                log(f"  {label:<34} error: {type(exc).__name__}: {exc}")
    return jobs


def collect_boards(searches: dict[str, list[str]], log) -> list[RawJob]:
    jobs: list[RawJob] = []
    terms = searches.get("terms", [])
    locations = [("" if loc.upper() == "ALL" else loc)
                 for loc in searches.get("locations", ["ALL"])]

    if boards.adzuna_enabled():
        log("  adzuna:")
        for term in terms:
            for loc in locations:
                try:
                    found = boards.adzuna(term, where=loc)
                except FetchError as exc:
                    log(f"    {term} @ {loc or 'UK'}: {exc}")
                    continue
                jobs.extend(found)
                if found:
                    log(f"    {term:<24} @ {loc or 'UK':<12} {len(found):>3}")
    else:
        log("  adzuna: skipped (set ADZUNA_APP_ID / ADZUNA_APP_KEY)")

    if boards.reed_enabled():
        log("  reed:")
        for term in terms:
            try:
                found = boards.reed(term, title_filter=title_prefilter)
            except FetchError as exc:
                log(f"    {term}: {exc}")
                continue
            jobs.extend(found)
            if found:
                log(f"    {term:<24} {len(found):>3}")
    else:
        log("  reed: skipped (set REED_API_KEY)")
    return jobs


def money(job: RawJob) -> str:
    lo, hi = job.salary_min, job.salary_max
    def fmt(v):
        return f"£{int(v):,}"
    if lo and hi and int(lo) != int(hi):
        return f"{fmt(lo)} – {fmt(hi)}"
    if lo or hi:
        return fmt(lo or hi)
    return job.salary_text or ""


def to_record(job: RawJob, role_type: str, cats: list[str]) -> dict:
    body = normalise_ws(job.description)
    closes, rolling = job.closes, False
    if not closes:
        closes, rolling = find_deadline(body, job.posted)
    return {
        "id": job.key(),
        "title": job.title,
        "company": job.company.strip(),
        "location": job.location.strip(),
        "url": job.url,
        "source": job.source,
        "posted": job.posted,
        "closes": closes,
        "rolling": 1 if rolling else 0,
        "type": role_type,
        "cats": cats,
        "salary": money(job),
        "remote": 1 if (job.remote or is_remote(job.location, body)) else 0,
        "team": (job.extra.get("team") or "")[:60],
        # Pre-extracted so the browser does no heavy text processing.
        "kw": " ".join(keywords(f"{job.title} {job.title} {body}")),
        "summary": summarise(body),
    }


def build(args) -> dict:
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))
    employers = load_lists("employers.yml")
    searches = load_lists("searches.yml")

    raw: list[RawJob] = []
    if not args.no_ats:
        log("fetching employer ATS boards...")
        raw += collect_ats(employers, log)
    if not args.no_boards:
        log("fetching job boards...")
        raw += collect_boards(searches, log)

    log(f"\n{len(raw)} raw postings; filtering...")

    cutoff = date.today() - timedelta(days=args.max_age_days)
    best: dict[str, tuple[int, int, dict]] = {}
    rejected = {"not_uk": 0, "stale": 0, "no_url": 0, "career": 0}

    for job in raw:
        if not job.url or not job.title:
            rejected["no_url"] += 1
            continue
        if not is_uk(job.location):
            rejected["not_uk"] += 1
            continue
        if job.posted:
            try:
                if date.fromisoformat(job.posted[:10]) < cutoff:
                    rejected["stale"] += 1
                    continue
            except ValueError:
                pass
        body = normalise_ws(job.description)
        keep, role_type, _ = classify.is_early_career(job.title, body)
        if not keep:
            rejected["career"] += 1
            continue

        record = to_record(job, role_type, classify.categories(job.title, body))
        rank = (SOURCE_RANK.get(job.source, 1), len(body))
        key = record["id"]
        if key not in best or rank > best[key][:2]:
            best[key] = (*rank, record)

    records = [entry[2] for entry in best.values()]
    records.sort(key=lambda r: (r["posted"] or "", r["title"]), reverse=True)

    counts: dict[str, int] = {}
    for r in records:
        counts[r["source"]] = counts.get(r["source"], 0) + 1

    log(f"kept {len(records)} after dedupe")
    log(f"rejected: {rejected}")
    log(f"by source: {counts}")

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "sources": counts,
        "jobs": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the graduate job snapshot.")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--max-age-days", type=int, default=60)
    ap.add_argument("--no-ats", action="store_true", help="skip employer boards")
    ap.add_argument("--no-boards", action="store_true", help="skip Adzuna/Reed")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    payload = build(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                        encoding="utf-8")
    size = args.out.stat().st_size / 1024
    print(f"wrote {args.out} - {payload['count']} jobs, {size:.0f} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
