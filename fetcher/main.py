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
from .duration import find_duration
from .opening import find_opening, intake_year
from .http import FetchError
from .models import RawJob
from .salary import annual_equivalent, find_commission, find_salary, format_salary
from .summarise import highlights, role_gist
from .sources import aggregators, ats, boards, workday
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
        # Every term runs nationally and goes deep, because a UK-wide search
        # already returns roles in every city. Only the core terms get an extra
        # per-city pass, for roles that rank too low to surface nationally.
        city_terms = searches.get("cityTerms") or terms[:12]
        passes: list[tuple[str, int, list[str]]] = [("", 5, terms)]
        passes += [(loc, 1, city_terms) for loc in locations if loc]
        for where, pages, pass_terms in passes:
            for term in pass_terms:
                if boards.adzuna_budget_left() <= 0:
                    log("    call budget spent - stopping adzuna here")
                    break
                try:
                    found = boards.adzuna(term, where=where, pages=pages)
                except FetchError as exc:
                    log(f"    {term} @ {where or 'UK'}: {exc}")
                    continue
                jobs.extend(found)
                if found:
                    log(f"    {term:<24} @ {where or 'UK':<12} {len(found):>3}")
            if boards.adzuna_budget_left() <= 0:
                break
        log(f"  adzuna used {boards.adzuna_calls_used()} calls")
    else:
        log("  adzuna: skipped (set ADZUNA_APP_ID / ADZUNA_APP_KEY)")

    if boards.reed_enabled():
        log("  reed:")
        for term in terms:
            try:
                found = boards.reed(term, pages=1, title_filter=title_prefilter)
            except FetchError as exc:
                log(f"    {term}: {exc}")
                continue
            jobs.extend(found)
            if found:
                log(f"    {term:<24} {len(found):>3}")
        log(f"  reed used {boards.reed_details_used()} detail requests")
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


def to_record(job: RawJob, *, role_type: str, cats: list[str]) -> dict:
    body = normalise_ws(job.description)
    closes, rolling = job.closes, False
    if not closes:
        closes, rolling = find_deadline(body, job.posted)
    opens, not_open_yet = find_opening(body, job.posted)
    salary, salary_annual = resolve_salary(job, body)

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
        "opens": opens,
        "soon": 1 if (opens or not_open_yet) else 0,
        "intake": intake_year(job.title, body),
        "type": role_type,
        "duration": find_duration(job.title, body),
        "cats": cats,
        "salary": salary,
        "salaryAnnual": salary_annual,
        "commission": find_commission(body),
        "remote": 1 if (job.remote or is_remote(job.location, body)) else 0,
        "team": (job.extra.get("team") or "")[:60],
        # Pre-extracted so the browser does no heavy text processing.
        "kw": " ".join(keywords(f"{job.title} {job.title} {body}")),
        # A readable digest instead of the first 400 characters of blurb.
        "summary": role_gist(body, job.title) or summarise(body, 240),
        "does": highlights(body)["does"],
        "wants": highlights(body)["wants"],
    }


def process(raw: list[RawJob], *, cutoff, rejected: dict) -> dict:
    """Filter, classify and de-duplicate postings into {id: record}."""
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
        keep, role_type, _ = classify.is_early_career(job.title, body)
        cats = classify.categories(job.title, body)
        if not keep:
            rejected["filtered"] += 1
            continue

        record = to_record(job, role_type=role_type, cats=cats)
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
        key = (record["title"].strip().lower(), record["company"].strip().lower())
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
            if not lead.get("duration") and m.get("duration"):
                lead["duration"] = m["duration"]
        out.append(lead)
    return out


def build(args) -> dict:
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))
    employers = load_lists("employers.yml")
    searches = load_lists("searches.yml")
    workday_sites = load_lists("workday.yml").get("workday", [])

    raw: list[RawJob] = []
    if not args.no_ats:
        log("employer ATS boards...")
        raw += collect_ats(employers, log)
    if not args.no_workday:
        log("workday career sites...")
        raw += collect_workday(workday_sites, log)
    if not args.no_aggregators:
        log("workable cross-company search...")
        raw += collect_workable_search(searches, log)
        log("keyless aggregators...")
        raw += collect_aggregators(log)
    if not args.no_boards:
        log("job boards...")
        raw += collect_boards(searches, log)

    log(f"\n{len(raw)} raw postings; filtering...")

    cutoff = date.today() - timedelta(days=args.max_age_days)
    rejected = {"not_uk": 0, "stale": 0, "no_url": 0, "filtered": 0}

    records = collapse_multi_location(
        list(process(raw, cutoff=cutoff, rejected=rejected).values()))
    records.sort(key=lambda r: (r["posted"] or "", r["title"]), reverse=True)

    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for r in records:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1

    with_salary = sum(1 for r in records if r["salary"])
    with_closes = sum(1 for r in records if r["closes"])
    coming_soon = sum(1 for r in records if r.get("soon"))

    log(f"kept {len(records)} after dedupe")
    log(f"rejected: {rejected}")
    log(f"by type:   {by_type}")
    log(f"by source: {by_source}")
    log(f"with salary: {with_salary} | closing date: {with_closes} "
        f"| coming soon: {coming_soon}")

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "sources": by_source,
        "types": by_type,
        "withSalary": with_salary,
        "withClosingDate": with_closes,
        "comingSoon": coming_soon,
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
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    payload = build(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                        encoding="utf-8")
    print(f"wrote {args.out} - {payload['count']} jobs, "
          f"{args.out.stat().st_size / 1024:.0f} KB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
