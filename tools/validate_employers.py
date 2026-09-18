"""Probe candidate company slugs against keyless ATS job-board APIs.

Most grad employers publish their vacancies through an applicant tracking
system that exposes a public JSON endpoint. The slug is rarely documented, so
we brute-force a handful of plausible spellings per company and keep whatever
answers with real jobs.

Usage:
    python3 tools/validate_employers.py                 # probe + print report
    python3 tools/validate_employers.py --write         # also update config/employers.yml
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "grad-job-finder/1.0 (+https://github.com/)"
TIMEOUT = 15

# Companies that hire UK graduates into business, marketing, finance and
# commercial roles. Slugs get derived from the name below.
CANDIDATES = [
    "Monzo", "Starling Bank", "Wise", "Revolut", "GoCardless", "Checkout.com",
    "Deliveroo", "Trainline", "Depop", "Octopus Energy", "Marshmallow", "Zopa",
    "Cleo", "Tide", "ClearScore", "Moneybox", "Freetrade", "Curve", "Onfido",
    "Paddle", "Wayve", "Babylon", "Bulb", "Farfetch", "ASOS", "Boohoo",
    "Just Eat", "Skyscanner", "Babbel", "Duolingo", "Stripe", "Airbnb",
    "Klarna", "N26", "SumUp", "Payhawk", "Pleo", "Qonto", "Spendesk",
    "Soldo", "Modulr", "Thought Machine", "Form3", "Rapyd", "Ebury",
    "Lendable", "Zilch", "Plum", "Nutmeg", "PensionBee", "Wealthify",
    "Multiverse", "Beamery", "Personio", "HiBob", "Deel", "Remote",
    "Attest", "Permutive", "Peak", "Quantexa", "Featurespace", "Signal AI",
    "Mention Me", "Brandwatch", "Hootsuite", "Sprout Social", "Semrush",
    "Similarweb", "AppsFlyer", "Braze", "Klaviyo", "Iterable", "Amplitude",
    "Mixpanel", "Segment", "Contentful", "Contentsquare", "Dept", "MediaMonks",
    "S4 Capital", "The Trade Desk", "Teads", "Taboola", "Outbrain",
    "Bloom and Wild", "Gousto", "HelloFresh", "Huel", "Graze", "Innocent",
    "Gymshark", "Castore", "Represent", "Papier", "Mous", "Wild",
    "Vinterior", "Olio", "Too Good To Go", "Beauty Pie", "Cult Beauty",
    "Charlotte Tilbury", "Trouva", "Thriva", "Zoe", "Second Nature",
    "Elvie", "Flo Health", "Bought By Many", "Many Pets", "Urban Jungle",
    "Cuvva", "By Miles", "Habito", "Nested", "Goodlord", "Coadjute",
    "Yoti", "Snyk", "Darktrace", "Tessian", "Immersive Labs", "Mimecast",
]

# Extra hand-written slugs worth probing that name-mangling would not produce.
EXTRA_SLUGS = [
    "transferwise", "checkoutcom", "justeattakeaway", "bloomandwild",
    "toogoodtogo", "boughtbymany", "manypets", "thoughtmachine",
    "octopusenergy", "starlingbank", "signalai", "mentionme", "thetradedesk",
    "s4capital", "flohealth", "secondnature", "immersivelabs", "beautypie",
    "cultbeauty", "charlottetilbury", "sproutsocial", "similarweb",
    "appsflyer", "pensionbee", "byMiles", "bymiles",
]


def slug_variants(name: str) -> list[str]:
    """Plausible ATS slugs for a company name."""
    base = name.lower().strip()
    base = re.sub(r"[.'&]", "", base)
    compact = re.sub(r"[^a-z0-9]", "", base)
    hyphen = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    first = compact_first_word(base)
    out = [compact, hyphen]
    if first and first != compact:
        out.append(first)
    return [s for s in dict.fromkeys(out) if s]


def compact_first_word(base: str) -> str:
    head = base.split()[0] if base.split() else ""
    return re.sub(r"[^a-z0-9]", "", head)


def get_json(url: str, method: str = "GET", body: bytes | None = None) -> object | None:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            TimeoutError, ConnectionError, OSError):
        return None


# Each prober returns the number of live postings, or None if the slug is wrong.
def probe_greenhouse(slug: str) -> int | None:
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(data["jobs"])
    return None


def probe_lever(slug: str) -> int | None:
    data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if isinstance(data, list):
        return len(data)
    return None


def probe_ashby(slug: str) -> int | None:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(data["jobs"])
    return None


def probe_workable(slug: str) -> int | None:
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if isinstance(data, dict) and isinstance(data.get("jobs"), list):
        return len(data["jobs"])
    return None


def probe_smartrecruiters(slug: str) -> int | None:
    data = get_json(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    )
    if isinstance(data, dict) and isinstance(data.get("content"), list):
        return int(data.get("totalFound") or len(data["content"]))
    return None


def probe_recruitee(slug: str) -> int | None:
    data = get_json(f"https://{slug}.recruitee.com/api/offers/")
    if isinstance(data, dict) and isinstance(data.get("offers"), list):
        return len(data["offers"])
    return None


PROBES = {
    "greenhouse": probe_greenhouse,
    "lever": probe_lever,
    "ashby": probe_ashby,
    "workable": probe_workable,
    "smartrecruiters": probe_smartrecruiters,
    "recruitee": probe_recruitee,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write verified slugs to config/employers.yml")
    ap.add_argument("--min-jobs", type=int, default=1,
                    help="ignore boards with fewer than this many live postings")
    args = ap.parse_args()

    slugs: set[str] = set(EXTRA_SLUGS)
    for name in CANDIDATES:
        slugs.update(slug_variants(name))

    tasks = list(itertools.product(sorted(slugs), PROBES.items()))
    print(f"probing {len(slugs)} slugs across {len(PROBES)} ATS platforms "
          f"({len(tasks)} requests)...", file=sys.stderr)

    hits: dict[str, list[tuple[str, int]]] = {ats: [] for ats in PROBES}

    def run(task):
        slug, (ats, fn) = task
        return ats, slug, fn(slug)

    with ThreadPoolExecutor(max_workers=24) as pool:
        for ats, slug, count in pool.map(run, tasks):
            if count is not None and count >= args.min_jobs:
                hits[ats].append((slug, count))

    total = 0
    for ats in sorted(hits):
        found = sorted(hits[ats], key=lambda x: -x[1])
        total += len(found)
        print(f"\n## {ats} ({len(found)})")
        for slug, count in found:
            print(f"  {slug:<28} {count} jobs")
    print(f"\nverified {total} boards", file=sys.stderr)

    if args.write:
        out = ROOT / "config" / "employers.yml"
        lines = [
            "# Verified keyless ATS job boards.",
            "# Regenerate with: python3 tools/validate_employers.py --write",
            "",
        ]
        for ats in sorted(hits):
            found = sorted(hits[ats], key=lambda x: -x[1])
            lines.append(f"{ats}:")
            if not found:
                lines.append("  []")
            for slug, count in found:
                lines.append(f"  - {slug}   # {count} live postings at last check")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
