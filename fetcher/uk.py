"""Is this posting actually in the UK? ATS boards are global."""
from __future__ import annotations

import re

UK_MARKERS = re.compile(
    r"\b(united kingdom|uk|u\.k\.|great britain|england|scotland|wales|"
    r"northern ireland|britain|gb)\b", re.I)

UK_PLACES = {
    "london", "manchester", "birmingham", "leeds", "bristol", "glasgow",
    "edinburgh", "liverpool", "cardiff", "belfast", "nottingham", "sheffield",
    "newcastle", "brighton", "oxford", "cambridge", "reading", "leicester",
    "coventry", "york", "bath", "norwich", "exeter", "southampton",
    "portsmouth", "plymouth", "derby", "stoke", "wolverhampton", "swansea",
    "aberdeen", "dundee", "inverness", "milton keynes", "luton", "slough",
    "watford", "croydon", "basingstoke", "swindon", "gloucester", "cheltenham",
    "bournemouth", "poole", "ipswich", "colchester", "chelmsford", "guildford",
    "woking", "maidenhead", "bracknell", "crawley", "chester", "preston",
    "blackburn", "bolton", "warrington", "wigan", "huddersfield", "bradford",
    "wakefield", "hull", "middlesbrough", "sunderland", "durham", "carlisle",
    "lancaster", "salford", "stockport", "solihull", "walsall", "dudley",
    "telford", "shrewsbury", "worcester", "hereford", "peterborough",
    "northampton", "bedford", "cambridgeshire", "surrey", "kent", "essex",
    "hertfordshire", "berkshire", "hampshire", "sussex", "yorkshire",
    "lancashire", "merseyside", "midlands", "canary wharf", "city of london",
    "staines", "uxbridge", "hemel hempstead", "st albans", "chiswick",
    "farnborough", "camberley", "newbury", "winchester", "salisbury",
}

NON_UK_TRAP = re.compile(
    r"\b(new york|san francisco|boston|chicago|austin|seattle|toronto|sydney|"
    r"melbourne|singapore|dublin|paris|berlin|munich|amsterdam|madrid|barcelona|"
    r"lisbon|milan|rome|warsaw|prague|stockholm|copenhagen|oslo|helsinki|zurich|"
    r"vienna|brussels|tokyo|hong kong|bangalore|mumbai|dubai|tel aviv|"
    r"united states|usa|canada|australia|germany|france|spain|italy|india|"
    r"netherlands|poland|portugal|ireland|new zealand)\b", re.I)

# "Cambridge, MA" / "Richmond, VA" - a trailing US state code settles it.
US_STATE = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|"
    r"MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|"
    r"VA|WA|WV|WI|WY)\b")

# Cities that exist in both places - only trust them with a UK signal nearby.
AMBIGUOUS = {"cambridge", "boston", "birmingham", "manchester", "newcastle",
             "richmond", "windsor", "hamilton", "perth", "york"}


def is_uk(location: str, *, allow_remote: bool = True) -> bool:
    """True when the location string looks like a UK-based posting."""
    if not location:
        return False
    low = location.lower()

    if US_STATE.search(location) or re.search(r"\b(US|USA|U\.S\.)\b", location):
        return False
    if UK_MARKERS.search(low):
        return True

    remote_only = bool(re.search(r"\b(remote|anywhere|worldwide|global)\b", low))

    for place in UK_PLACES:
        if re.search(rf"\b{re.escape(place)}\b", low):
            if place in AMBIGUOUS and NON_UK_TRAP.search(low):
                continue
            return True

    if NON_UK_TRAP.search(low):
        return False
    if remote_only and allow_remote:
        # "Remote" with nothing else - keep it, the user can filter.
        return True
    return False


def is_remote(location: str, description: str = "") -> bool:
    hay = f"{location} {description[:600]}".lower()
    return bool(re.search(r"\b(fully remote|remote[- ]first|work from home|wfh)\b", hay)) \
        or bool(re.search(r"\bremote\b", location.lower()))
