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
    # Professional services and Big Four
    "pwc", "kpmg", "ey", "ernstyoung", "deloitte", "deloittecoll", "grantthornton",
    "bdo", "rsmuk", "mazars", "pkf", "moorekingston", "crowe", "azets",
    # Banking and finance
    "hsbc", "barclays", "lloydsbanking", "lbg", "natwest", "rbs", "santander",
    "nationwide", "tsb", "metrobank", "virginmoney", "coop", "handelsbanken",
    "closebrothers", "investec", "rathbones", "schroders", "abrdn", "mandg",
    "jupiteram", "janushenderson", "fidelity", "blackrock", "statestreet",
    "northerntrust", "bnymellon", "jpmorgan", "morganstanley", "citi",
    # Insurance
    "aviva", "legalandgeneral", "phoenixgroup", "zurich", "axa", "allianz",
    "rsa", "admiralgroup", "directline", "hiscox", "beazley", "lloyds",
    "markel", "chubb", "aig", "willistowerswatson", "aon", "marsh", "gallagher",
    # Retail and consumer
    "tesco", "sainsburys", "asda", "morrisons", "marksandspencer", "mands",
    "johnlewis", "boots", "kingfisher", "next", "primark", "aldi", "lidl",
    "coopgroup", "waitrose", "iceland", "poundland", "bandm", "wilko",
    "dixons", "currys", "halfords", "screwfix", "travisperkins",
    # FMCG and pharma
    "unilever", "diageo", "gsk", "astrazeneca", "reckittbenckiser", "haleon",
    "pepsico", "cocacola", "ccep", "nestle", "mars", "mondelez", "kraftheinz",
    "danone", "kelloggs", "generalmills", "abinbev", "heineken", "carlsberg",
    "britvic", "premierfoods", "associatedbritishfoods", "tatelyle", "bat",
    "imperialbrands", "pg", "loreal", "estee", "jnj", "pfizer", "msd",
    "novartis", "roche", "sanofi", "bayer", "lilly", "abbvie", "amgen",
    # Telecoms, media, utilities
    "vodafone", "bt", "sky", "virginmedia", "telefonica", "threeuk",
    "nationalgrid", "sse", "centrica", "eonuk", "edfenergy", "octopusenergy",
    "unitedutilities", "severntrent", "thameswater", "anglianwater",
    "itv", "channel4", "bbc", "guardian", "informa", "relx", "pearson",
    # Industrials, engineering, transport
    "rollsroyce", "bae", "baesystems", "jaguarlandrover", "airbus", "leonardo",
    "babcock", "qinetiq", "thales", "gknaerospace", "meggitt", "smithsgroup",
    "weir", "spiraxsarco", "renishaw", "dyson", "jcb", "caterpillar",
    "networkrail", "nationalhighways", "tfl", "arriva", "firstgroup",
    "stagecoach", "dhl", "dpd", "royalmail", "maersk", "kuehnenagel",
    # Property, construction, professional
    "balfourbeatty", "kier", "morgansindall", "galliford", "willmottdixon",
    "laingorourke", "skanska", "mace", "turnerandtownsend", "arcadis",
    "aecom", "jacobs", "wsp", "atkins", "arup", "mottmacdonald", "stantec",
    "savills", "knightfrank", "jll", "cbre", "cushmanwakefield", "colliers",
    # Tech and consulting
    "accenture", "capgemini", "ibm", "cognizant", "infosys", "wipro", "tcs",
    "atos", "dxc", "fujitsu", "ncc", "softwire", "kainos", "sopra",
    "amazon", "microsoft", "salesforce", "workday", "oracle", "sap", "adobe",
    "dell", "hp", "hpe", "cisco", "intel", "nvidia", "vmware", "servicenow",
    # Research, data, marketing
    "nielseniq", "kantar", "ipsos", "yougov", "gartner", "mckinsey", "bain",
    "bcg", "oliverwyman", "lek", "alixpartners", "fticonsulting",
    "wpp", "publicisgroupe", "omnicom", "dentsu", "havas", "s4capital",
    # Public and third sector
    "nhs", "civilservice", "cabinetoffice", "hmrc", "dwp", "mod",
    "networkhomes", "peabody", "clarionhg", "l-and-q",
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
        # Merge, never overwrite: these probes hit rate limits, and a transient
        # failure must not silently delete a career site we already verified.
        if out.exists():
            kept = 0
            for line in out.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line.startswith("- "):
                    continue
                spec = line[2:].split("#")[0].strip()
                parts = spec.split("|")
                if len(parts) != 3:
                    continue
                tenant = parts[0]
                if tenant not in found:
                    found[tenant] = (tenant, parts[1], parts[2], 0)
                    kept += 1
            if kept:
                print(f"kept {kept} previously verified sites not seen this run",
                      file=sys.stderr)
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
