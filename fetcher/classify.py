"""Decide whether a posting is genuinely early-career, and what field it sits in.

Job boards are full of traps: "Graduate Recruitment Manager" is a senior HR job,
and in the UK "Marketing Executive" is a junior role while "Chief Executive" is
not. The rules below encode those quirks explicitly.
"""
from __future__ import annotations

import re

# --- role type -------------------------------------------------------------
# Checked in order; the first match wins.
ROLE_PATTERNS: list[tuple[str, list[str]]] = [
    ("internship", [
        r"\binterns?(hip)?\b", r"\bsummer analyst\b", r"\bsummer (scheme|programme|program)\b",
        r"\bvacation scheme\b", r"\bwork experience\b", r"\bspring (week|insight)\b",
        r"\binsight (week|programme|program)\b",
    ]),
    ("placement", [
        r"\bplacement\b", r"\byear in industry\b", r"\bindustrial placement\b",
        r"\bsandwich (year|placement)\b", r"\bindustrial year\b",
    ]),
    ("graduate-scheme", [
        r"\bgraduate (scheme|programme|program)\b", r"\bgrad (scheme|programme|program)\b",
        r"\brotational (scheme|programme|program)\b", r"\bgraduate traineeship\b",
        r"\b(scheme|programme|program) for graduates\b",
    ]),
    ("graduate", [
        r"\bgraduates?\b", r"\btrainee\b", r"\bapprentice(ship)?\b",
    ]),
    ("entry-level", [
        r"\bentry[- ]level\b", r"\bjunior\b", r"\bassistant\b", r"\bcoordinator\b",
        r"\bexecutive\b", r"\banalyst\b", r"\bassociate\b", r"\bno experience\b",
        r"\bschool leaver\b", r"\bearly careers?\b",
    ]),
]

EARLY_CAREER = {"internship", "placement", "graduate-scheme", "graduate"}

# A title is the only reliable signal. Job adverts casually say things like
# "we hire graduates" in boilerplate, so body text only counts when it names an
# actual scheme.
BODY_PATTERNS: list[tuple[str, list[str]]] = [
    ("internship", [r"\bsummer internship\b", r"\binternship (programme|program|scheme)\b",
                    r"\bthis internship\b"]),
    ("placement", [r"\bindustrial placement\b", r"\byear in industry\b",
                   r"\bplacement year\b"]),
    ("graduate-scheme", [r"\bgraduate (scheme|programme|program)\b",
                         r"\brotational (scheme|programme|program)\b"]),
]

# Titles that are senior no matter what else they say.
SENIOR_TITLE = re.compile(
    r"\b(senior|snr|lead|principal|staff|head of|director|vp|vice president|chief|"
    r"c-level|cto|ceo|cfo|cmo|coo|partner|manager|management|supervisor|"
    r"architect|specialist|expert|consultant iii|controller)\b", re.I)

# ...except these, which are junior despite containing a "senior" word.
SENIOR_EXEMPT = re.compile(
    r"\b(graduate|trainee|intern|internship|placement|apprentice|junior|"
    r"entry[- ]level|assistant manager|management trainee|early careers?|"
    r"school leaver|future leaders?)\b", re.I)

# Jobs *about* graduates (campus recruiting) rather than *for* them. When one of
# these is paired with a senior head-noun it is a senior hire, not a grad role.
ABOUT_GRADUATES = re.compile(
    r"\b(graduate|campus|early careers?|student|emerging talent|apprentice(ship)?)\s+"
    r"(recruit\w*|talent|hiring|resourc\w*|attraction|outreach|scheme|programme|program)\b",
    re.I)

YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus|or more)?\s*(?:-\s*\d{1,2}\s*)?year[s]?['’]?\s*"
    r"(?:of\s+)?(?:relevant\s+|proven\s+|professional\s+|commercial\s+)?experience", re.I)

# --- field -----------------------------------------------------------------
CATEGORY_TERMS: dict[str, list[str]] = {
    "finance": [
        "finance", "financial", "accounting", "accountant", "accounts", "audit",
        "auditor", "tax", "actuarial", "actuary", "investment", "banking", "bank",
        "treasury", "fp&a", "equity", "equities", "trading", "trader", "credit",
        "underwriting", "insurance", "fund", "asset management", "wealth",
        "aca", "acca", "cima", "cfa", "payroll", "bookkeeping", "valuation",
    ],
    "consulting": [
        "consulting", "consultant", "advisory", "strategy", "strategic",
        "transformation", "management consulting", "corporate development",
    ],
    "marketing": [
        "marketing", "brand", "branding", "content", "social media", "seo",
        "ppc", "crm", "growth", "communications", "comms", "public relations",
        "copywriter", "copywriting", "campaign", "advertising", "media",
        "digital marketing", "paid search", "paid social", "influencer",
        "email marketing", "creative", "affiliate",
    ],
    "sales": [
        "sales", "business development", "bdr", "sdr", "account executive",
        "account manager", "account management", "partnerships", "commercial",
        "revenue", "client relationship", "customer success",
    ],
    "operations": [
        "operations", "supply chain", "logistics", "procurement", "purchasing",
        "project management", "project manager", "programme", "business analyst",
        "business analysis", "process improvement", "planning", "merchandising",
        "category", "buying", "product manager", "product management",
    ],
    "people": [
        "human resources", "hr ", "people team", "talent", "recruitment",
        "recruiter", "learning and development", "l&d", "people operations",
    ],
    "data-tech": [
        "data analyst", "data analytics", "analytics", "data science", "software",
        "engineer", "developer", "python", "sql", "power bi", "tableau",
        "business intelligence", "technology", "technical",
    ],
}


def role_type(title: str, description: str = "") -> str:
    """Bucket the posting: internship, placement, graduate-scheme, graduate, ..."""
    hay = f"{title}\n{description[:1500]}".lower()
    title_low = title.lower()
    # Title evidence beats body evidence - bodies mention "graduate" loosely.
    for bucket, patterns in ROLE_PATTERNS:
        if any(re.search(p, title_low) for p in patterns):
            return bucket
    for bucket, patterns in BODY_PATTERNS:
        if any(re.search(p, hay) for p in patterns):
            return bucket
    return "other"


def is_senior(title: str) -> bool:
    senior = bool(SENIOR_TITLE.search(title))
    if senior and ABOUT_GRADUATES.search(title):
        return True  # e.g. "Graduate Recruitment Manager" - hires grads, isn't one
    if SENIOR_EXEMPT.search(title):
        return False
    return senior


def min_years_required(description: str) -> int:
    """Largest 'N years experience' figure stated in the description."""
    if not description:
        return 0
    return max((int(m.group(1)) for m in YEARS_RE.finditer(description)), default=0)


def categories(title: str, description: str = "") -> list[str]:
    """Fields this posting belongs to, title-weighted.

    Descriptions are full of incidental words ("commercial", "media",
    "technology"), so body matches are capped and a category only survives if it
    scores near the leader.
    """
    title_low = title.lower()
    body_low = description[:2500].lower()
    scores: dict[str, int] = {}
    for name, terms in CATEGORY_TERMS.items():
        in_title = sum(1 for t in terms if t in title_low)
        in_body = min(sum(body_low.count(t) for t in terms), 6)
        score = in_title * 6 + in_body
        if score:
            scores[name] = score
    if not scores:
        return []
    top = max(scores.values())
    threshold = max(4, top * 0.55)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [name for name, score in ranked if score >= threshold][:3]


def is_early_career(title: str, description: str = "") -> tuple[bool, str, str]:
    """(keep?, role_type, reason-if-rejected)"""
    rt = role_type(title, description)
    if rt in EARLY_CAREER:
        # An explicit grad/intern title wins even if the body waffles about years.
        if is_senior(title):
            return False, rt, "senior title"
        return True, rt, ""
    if rt == "entry-level":
        if is_senior(title):
            return False, rt, "senior title"
        years = min_years_required(description)
        if years >= 3:
            return False, rt, f"requires {years}y experience"
        return True, rt, ""
    return False, rt, "not early career"


# ---------------------------------------------------------------------------
# Local and hourly work
#
# A separate stream from the graduate one: bar, retail, warehouse, care and
# admin jobs. These are not "early career" in the graduate-scheme sense, so they
# bypass that filter entirely and are judged on trade instead.
# ---------------------------------------------------------------------------
LOCAL_CATEGORY_TERMS: dict[str, list[str]] = {
    "hospitality": [
        "bar staff", "bartender", "bar team", "barback", "barista", "waiter",
        "waitress", "waiting staff", "front of house", "kitchen porter",
        "kitchen assistant", "kitchen team", "chef", "commis", "server",
        "pub", "restaurant", "cafe", "coffee shop", "hotel", "housekeeping",
        "catering", "hospitality", "food and beverage", "glass collector",
        "bar", "mixologist", "sommelier", "receptionist hotel",
    ],
    "retail": [
        "retail", "sales assistant", "shop assistant", "store assistant",
        "customer assistant", "cashier", "checkout", "till", "merchandiser",
        "stock assistant", "shop floor", "supermarket", "store colleague",
        "retail assistant", "keyholder", "visual merchandiser",
    ],
    "warehouse": [
        "warehouse", "picker", "packer", "picking", "packing", "fulfilment",
        "fulfillment", "loader", "forklift", "delivery driver", "courier",
        "driver", "van driver", "logistics operative", "operative",
    ],
    "care": [
        "care assistant", "carer", "support worker", "healthcare assistant",
        "care home", "domiciliary", "care worker", "personal assistant care",
    ],
    "admin": [
        "receptionist", "administrator", "admin assistant", "data entry",
        "call centre", "call center", "customer service", "customer support",
        "contact centre", "office assistant", "clerical",
    ],
    "cleaning": ["cleaner", "cleaning", "housekeeper", "janitor", "domestic assistant"],
    "security": ["security officer", "door supervisor", "steward", "security guard"],
    "childcare": [
        "nursery", "childcare", "teaching assistant", "nanny", "playworker",
        "nursery assistant", "learning support assistant",
    ],
    "events": [
        "event staff", "events assistant", "promotional", "brand ambassador",
        "festival", "stewarding", "hospitality assistant",
    ],
}

# Senior enough that it is not the casual work this stream is for.
LOCAL_TOO_SENIOR = re.compile(
    r"\b(head of|director|regional|area manager|general manager|"
    r"operations manager|national|senior manager|chief|franchise owner)\b", re.I)

SHIFT_SIGNALS = re.compile(
    r"\b(part[- ]time|full[- ]time|shift|shifts|hourly|per hour|zero hours|"
    r"flexible hours|weekend|evenings|casual|temporary|seasonal|bank staff)\b", re.I)


def local_categories(title: str, description: str = "") -> list[str]:
    """Which kinds of local work this posting is, title-weighted."""
    title_low = title.lower()
    body_low = description[:2000].lower()
    scores: dict[str, int] = {}
    for name, terms in LOCAL_CATEGORY_TERMS.items():
        in_title = sum(1 for t in terms if t in title_low)
        in_body = min(sum(body_low.count(t) for t in terms), 4)
        score = in_title * 6 + in_body
        if score:
            scores[name] = score
    if not scores:
        return []
    top = max(scores.values())
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [n for n, s in ranked if s >= max(4, top * 0.55)][:2]


def is_local_job(title: str, description: str = "") -> tuple[bool, list[str], str]:
    """(keep?, categories, reason-if-rejected) for the local/hourly stream."""
    if LOCAL_TOO_SENIOR.search(title):
        return False, [], "too senior"
    cats = local_categories(title, description)
    if not cats:
        return False, [], "not local work"
    return True, cats, ""


def shift_pattern(title: str, description: str = "") -> str:
    """Part-time / weekend / seasonal, pulled out for display and filtering."""
    hay = f"{title} {description[:900]}".lower()
    found = []
    for label, pattern in (
        ("part-time", r"\bpart[- ]time\b"),
        ("full-time", r"\bfull[- ]time\b"),
        ("weekend", r"\bweekend"),
        ("evenings", r"\bevening"),
        ("flexible", r"\b(flexible hours|zero hours|casual)\b"),
        ("temporary", r"\b(temporary|seasonal|fixed[- ]term|bank staff)\b"),
    ):
        if re.search(pattern, hay):
            found.append(label)
    return ", ".join(found[:3])
