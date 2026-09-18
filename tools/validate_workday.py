"""Discover working Workday career-site endpoints.

Workday powers most large UK graduate schemes (Big Four, banks, insurers,
FTSE corporates) but the API path needs an exact tenant + data-centre + site
triple, and none of those are published. Brute-force the plausible spellings
and keep whatever returns jobs.

Usage:
    python3 tools/validate_workday.py            # probe and report
    python3 tools/validate_workday.py --write    # write config/workday.yml
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Large UK graduate employers known to run Workday.
TENANTS = [
    "pwc", "kpmg", "ey", "deloitte", "deloittecoll", "hsbc", "barclays",
    "lloydsbanking", "natwest", "rbs", "santander", "nationwide", "aviva",
    "legalandgeneral", "lg", "schroders", "abrdn", "phoenixgroup", "zurich",
    "axa", "allianz", "rsa", "admiralgroup", "directline", "mandg",
    "unilever", "diageo", "gsk", "astrazeneca", "reckittbenckiser", "haleon",
    "tesco", "sainsburys", "asda", "morrisons", "marksandspencer", "mands",
    "johnlewis", "boots", "kingfisher", "next", "primark", "aldi", "lidl",
    "vodafone", "bt", "sky", "virginmedia", "telefonica",
    "rollsroyce", "bae", "baesystems", "jaguarlandrover", "airbus",
    "nationalgrid", "sse", "centrica", "shell", "bp",
    "accenture", "capgemini", "ibm", "cognizant", "infosys", "wipro",
    "amazon", "microsoft", "salesforce", "workday", "dell", "hp",
    "nielseniq", "kantar", "wpp", "publicisgroupe", "omnicom", "dentsu",
]

DATACENTRES = ["wd1", "wd2", "wd3", "wd5", "wd103", "wd12"]

def site_names(tenant: str) -> list[str]:
    cap = tenant.capitalize()
    return [
        "Careers", "careers", "External", "ExternalCareers", "External_Careers",
        "External_Career_Site", "Global_Careers", "GlobalCareers",
        "Global_Experienced_Careers", "Global_Campus_Careers", "Campus_Careers",
        "Early_Careers", "EarlyCareers", "Students", "Graduate", "Graduates",
        "jobs", "Jobs", "Search", "Professional_Careers",
        tenant, f"{tenant}careers", f"{cap}Careers", f"{cap}_Careers",
    ]

PAYLOAD = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0,
                      "searchText": ""}).encode()


def probe(args) -> tuple | None:
    tenant, dc, site = args
    host = f"{tenant}.{dc}.myworkdayjobs.com"
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    req = urllib.request.Request(url, data=PAYLOAD, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    req.add_header("Referer", f"https://{host}/en-US/{site}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8", "replace"))
            total = data.get("total") or 0
            if total:
                return (tenant, dc, site, int(total))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError,
            TimeoutError, ConnectionError, OSError):
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--tenants", nargs="*", default=None)
    args = ap.parse_args()

    tenants = args.tenants or TENANTS
    tasks = [(t, dc, s) for t in tenants for dc in DATACENTRES for s in site_names(t)]
    print(f"probing {len(tasks)} tenant/datacentre/site combinations...", file=sys.stderr)

    found: dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=32) as pool:
        for result in pool.map(probe, tasks):
            if not result:
                continue
            tenant, dc, site, total = result
            # Keep the site with the most postings per tenant.
            if tenant not in found or total > found[tenant][3]:
                found[tenant] = result
                print(f"  HIT {tenant:<20} {dc:<6} {site:<28} {total} jobs", file=sys.stderr)

    print(f"\nfound {len(found)} working Workday sites", file=sys.stderr)
    for tenant, (_, dc, site, total) in sorted(found.items(), key=lambda kv: -kv[1][3]):
        print(f"{tenant:<22} {dc:<7} {site:<30} {total}")

    if args.write:
        out = ROOT / "config" / "workday.yml"
        lines = ["# Verified Workday career sites: tenant|datacentre|site",
                 "# Regenerate with: python3 tools/validate_workday.py --write", "",
                 "workday:"]
        for tenant, (_, dc, site, total) in sorted(found.items(), key=lambda kv: -kv[1][3]):
            lines.append(f"  - {tenant}|{dc}|{site}   # {total} postings at last check")
        lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
