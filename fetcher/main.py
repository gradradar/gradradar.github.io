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
from .salary import annual_equivalent, find_commission, find_salary, format_salary
from .sources import aggregators, ats, boards, workday
from .text import keywords, normalise_ws, summarise
from .uk import is_remote, is_uk

OUT_PATH = ROOT / "site" / "data" / "jobs.json"

# Calls held back from the graduate pass so the local/hourly stream still gets
# a share of a small Adzuna plan.
ADZUNA_LOCAL_RESERVE = 300

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


def local_prefilter(title: str, location: str) -> bool:
    """Gate for the local/hourly stream before paying for a detail request."""
    if not is_uk(location):
        return False
    keep, _, _ = classify.is_local_job(title, "")
    return keep


def collect_workday(specs: list[str], log) -> list[RawJob]:
    jobs: list[RawJob] = []
    futures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for spec in specs:
            fut = pool.submit(workday.fetch, spec, title_filter=title_prefilter)
            fut.label = spec.split("|")[0]  # type: ignore[attr-defined]
            futures.append(fut)
        for fut in as_completed(futures):
            label = getattr(fut, "label", "?")
            try:
                found = fut.result()
                jobs.extend(found)
                log(f"  workday/{label:<24} {len(found):>4} postings")
            except Exception as exc:
                log(f"  workday/{label:<24} error: {type(exc).__name__}: {exc}")
    return jobs


def collect_workable_search(searches: dict[str, list[str]], log) -> list[RawJob]:
    """Workable's cross-company search - finds employers we never listed."""
    jobs: list[RawJob] = []
    terms = searches.get("globalTerms") or searches.get("terms", [])[:12]
    for term in terms:
        try:
            found = ats.workable_search(term)
        except Exception as exc:
            log(f"  workable-search {term:<26} failed: {exc}")
            continue
        jobs.extend(found)
        if found:
            log(f"  workable-search {term:<26} {len(found):>4} postings")
    return jobs


def collect_aggregators(log) -> list[RawJob]:
    jobs: list[RawJob] = []
    for name, fn in aggregators.ADAPTERS.items():
        try:
            found = fn()
            jobs.extend(found)
            log(f"  {name:<32} {len(found):>4} postings")
        except Exception as exc:
            log(f"  {name:<32} failed: {type(exc).__name__}: {exc}")
    return jobs


def collect_local(searches: dict[str, list[str]], log) -> list[RawJob]:
    """Bar, retail, warehouse and care work. Adzuna and Reed only - employer
    ATS boards do not carry this kind of vacancy."""
    jobs: list[RawJob] = []
    terms = searches.get("terms", [])
    locations = [("" if loc.upper() == "ALL" else loc)
                 for loc in searches.get("locations", ["ALL"])]

    if not (boards.adzuna_enabled() or boards.reed_enabled()):
        log("  local stream: needs ADZUNA_* or REED_API_KEY - skipping")
        return jobs

    for term in terms:
        for loc in locations:
            if boards.adzuna_enabled():
                try:
                    found = boards.adzuna(term, where=loc, pages=1)
                    jobs.extend(found)
                except FetchError as exc:
                    log(f"    adzuna {term} @ {loc}: {exc}")
            if boards.reed_enabled():
                try:
                    found = boards.reed(term, location=loc, pages=1,
                                        title_filter=local_prefilter)
                    jobs.extend(found)
                except FetchError as exc:
                    log(f"    reed {term} @ {loc}: {exc}")
    log(f"  local stream: {len(jobs)} raw postings")
    return jobs


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
        log(f"  adzuna (budget {boards.ADZUNA_DAILY_BUDGET} calls):")
        # A UK-wide search already returns roles in every city, so do those
        # first and only spend what is left on per-city searches.
        passes = [("", 4)] + [(loc, 1) for loc in locations if loc]
        for where, pages in passes:
            for term in terms:
                if boards.adzuna_budget_left() <= ADZUNA_LOCAL_RESERVE:
                    log("    graduate share spent - saving the rest for local work")
                    break
                try:
                    found = boards.adzuna(term, where=where, pages=pages)
                except FetchError as exc:
                    log(f"    {term} @ {where or 'UK'}: {exc}")
                    continue
                jobs.extend(found)
                if found:
                    log(f"    {term:<24} @ {where or 'UK':<12} {len(found):>3}")
            if boards.adzuna_budget_left() <= ADZUNA_LOCAL_RESERVE:
                break
        log(f"  adzuna used {boards.adzuna_calls_used()} calls")
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


def resolve_salary(job: RawJob, body: str) -> tuple[str, int]:
    """Best available pay, as display text plus an annual figure for sorting.

    Structured fields from Adzuna/Reed win; otherwise dig it out of the advert.
    """
    lo, hi = job.salary_min, job.salary_max
    if lo or hi:
        period = "year"
        # Adzuna occasionally reports an hourly figure in the salary fields.
        if (lo or hi) and (lo or hi) < 200:
            period = "hour"
        return format_salary(lo, hi, period), annual_equivalent(lo, hi, period)
    if job.salary_text:
        return job.salary_text, 0
    lo, hi, period, display = find_salary(body)
    if display:
        return display, annual_equivalent(lo, hi, period)
    return "", 0


def to_record(job: RawJob, *, stream: str, role_type: str, cats: list[str]) -> dict:
    body = normalise_ws(job.description)
    closes, rolling = job.closes, False
    if not closes:
        closes, rolling = find_deadline(body, job.posted)
    salary, salary_annual = resolve_salary(job, body)

    return {
        "id": job.key(),
        "stream": stream,
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
        "salary": salary,
        "salaryAnnual": salary_annual,
        "commission": find_commission(body),
        "shift": classify.shift_pattern(job.title, body) if stream == "local" else "",
        "remote": 1 if (job.remote or is_remote(job.location, body)) else 0,
        "team": (job.extra.get("team") or "")[:60],
        # Pre-extracted so the browser does no heavy text processing.
        "kw": " ".join(keywords(f"{job.title} {job.title} {body}")),
        "summary": summarise(body),
    }


def process(raw: list[RawJob], *, stream: str, cutoff, rejected: dict) -> dict:
    """Filter, classify and de-duplicate one stream into {id: record}."""
    best: dict[str, tuple] = {}
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
        if stream == "graduate":
            keep, role_type, _ = classify.is_early_career(job.title, body)
            cats = classify.categories(job.title, body)
        else:
            keep, cats, _ = classify.is_local_job(job.title, body)
            role_type = "local"
        if not keep:
            rejected["filtered"] += 1
            continue

        record = to_record(job, stream=stream, role_type=role_type, cats=cats)
        rank = (SOURCE_RANK.get(job.source, 1), len(body))
        key = record["id"]
        if key not in best or rank > best[key][:2]:
            best[key] = (*rank, record)
    return {k: v[2] for k, v in best.items()}


def collapse_multi_location(records: list[dict]) -> list[dict]:
    """One card per role, not forty.

    Field sales and retail roles get posted separately for every town, which
    otherwise buries everything else. Group them and keep a list of locations so
    the location filter still works.
    """
    groups: dict[tuple, list[dict]] = {}
    for record in records:
        key = (record["title"].strip().lower(), record["company"].strip().lower(),
               record["stream"])
        groups.setdefault(key, []).append(record)

    out: list[dict] = []
    for members in groups.values():
        if len(members) < 3:
            for record in members:
                record["locs"] = [record["location"]]
                out.append(record)
            continue
        # Keep the newest, and fold every location into it.
        members.sort(key=lambda r: (r["posted"] or ""), reverse=True)
        lead = dict(members[0])
        places = list(dict.fromkeys(m["location"] for m in members if m["location"]))
        lead["locs"] = places
        lead["locationCount"] = len(places)
        shown = ", ".join(places[:2])
        lead["location"] = f"{shown} + {len(places) - 2} more locations" \
            if len(places) > 2 else shown
        # Prefer any member that actually states pay or a deadline.
        for m in members:
            if not lead["salary"] and m["salary"]:
                lead["salary"], lead["salaryAnnual"] = m["salary"], m["salaryAnnual"]
            if not lead["closes"] and m["closes"]:
                lead["closes"] = m["closes"]
            if not lead.get("commission") and m.get("commission"):
                lead["commission"] = m["commission"]
        out.append(lead)
    return out


def build(args) -> dict:
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))
    employers = load_lists("employers.yml")
    searches = load_lists("searches.yml")
    local_searches = load_lists("searches-local.yml")
    workday_sites = load_lists("workday.yml").get("workday", [])

    graduate_raw: list[RawJob] = []
    if not args.no_ats:
        log("employer ATS boards...")
        graduate_raw += collect_ats(employers, log)
    if not args.no_workday:
        log("workday career sites...")
        graduate_raw += collect_workday(workday_sites, log)
    if not args.no_aggregators:
        log("workable cross-company search...")
        graduate_raw += collect_workable_search(searches, log)
        log("keyless aggregators...")
        graduate_raw += collect_aggregators(log)
    if not args.no_boards:
        log("job boards (graduate searches)...")
        graduate_raw += collect_boards(searches, log)

    local_raw: list[RawJob] = []
    if not args.no_local:
        log("local and hourly work...")
        local_raw = collect_local(local_searches, log)

    log(f"\n{len(graduate_raw)} graduate + {len(local_raw)} local raw postings; filtering...")

    cutoff = date.today() - timedelta(days=args.max_age_days)
    rejected = {"not_uk": 0, "stale": 0, "no_url": 0, "filtered": 0}

    graduate = process(graduate_raw, stream="graduate", cutoff=cutoff, rejected=rejected)
    local = process(local_raw, stream="local", cutoff=cutoff, rejected=rejected)

    # A posting can legitimately appear in both streams (a retail job that also
    # reads as entry level). The graduate stream wins so nothing is duplicated.
    merged = dict(graduate)
    for key, record in local.items():
        merged.setdefault(key, record)
    records = collapse_multi_location(list(merged.values()))
    records.sort(key=lambda r: (r["posted"] or "", r["title"]), reverse=True)

    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_stream: dict[str, int] = {}
    for r in records:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        by_stream[r["stream"]] = by_stream.get(r["stream"], 0) + 1

    with_salary = sum(1 for r in records if r["salary"])
    with_closes = sum(1 for r in records if r["closes"])

    log(f"kept {len(records)} after dedupe")
    log(f"rejected: {rejected}")
    log(f"by stream: {by_stream}")
    log(f"by type:   {by_type}")
    log(f"by source: {by_source}")
    log(f"with salary: {with_salary} | with closing date: {with_closes}")

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "sources": by_source,
        "types": by_type,
        "streams": by_stream,
        "withSalary": with_salary,
        "withClosingDate": with_closes,
        "jobs": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the graduate job snapshot.")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--max-age-days", type=int, default=60)
    ap.add_argument("--no-ats", action="store_true", help="skip employer ATS boards")
    ap.add_argument("--no-boards", action="store_true", help="skip Adzuna/Reed")
    ap.add_argument("--no-workday", action="store_true", help="skip Workday sites")
    ap.add_argument("--no-aggregators", action="store_true", help="skip keyless aggregators")
    ap.add_argument("--no-local", action="store_true", help="skip the local/hourly stream")
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
