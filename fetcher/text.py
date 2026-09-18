"""Text cleaning and keyword extraction shared by every source."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3",
               "h4", "h5", "h6", "section", "article", "table"}


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def strip_html(raw: str | None) -> str:
    """Turn a job-description HTML blob into readable plain text."""
    if not raw:
        return ""
    if "<" not in raw:
        return normalise_ws(html.unescape(raw))
    parser = _Stripper()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return normalise_ws(re.sub(r"<[^>]+>", " ", raw))
    return normalise_ws(parser.text())


def normalise_ws(text: str) -> str:
    text = text.replace(" ", " ").replace("’", "'")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren as at be because
been before being below between both but by can cannot could couldn did didn do does
doesn doing don down during each few for from further had hadn has hasn have haven
having he her here hers herself him himself his how i if in into is isn it its itself
just ll me more most mustn my myself no nor not now of off on once only or other ought
our ours ourselves out over own re s same shan she should shouldn so some such t than
that the their theirs them themselves then there these they this those through to too
under until up ve very was wasn we were weren what when where which while who whom why
will with won would wouldn you your yours yourself yourselves
role job work working team teams company business please apply application applications
candidate candidates opportunity opportunities looking join joining new within across
help helping make making need needs including include includes well good great strong
ability able experience experienced year years month months day days time full part
you'll we're we'll it's don't role's etc via per plus using use used one two three
first second next best right well like want wants may might must shall
benefits benefit salary pension holiday hybrid office remote based location locations
uk london england wales scotland ireland manchester birmingham leeds bristol glasgow
edinburgh liverpool cardiff belfast nottingham sheffield newcastle brighton oxford
cambridge reading leicester coventry york bath norwich exeter southampton portsmouth
equal opportunity employer diversity inclusive inclusion regardless race religion
gender sexual orientation disability age background applicants welcome encourage
""".split())

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.&/-]{1,24}")

# Multi-word phrases worth keeping intact because they carry real signal.
PHRASES = [
    "graduate scheme", "graduate programme", "graduate program", "graduate trainee",
    "graduate analyst", "summer internship", "summer analyst", "vacation scheme",
    "industrial placement", "year in industry", "placement year", "entry level",
    "business development", "account management", "account executive",
    "financial analysis", "financial modelling", "financial modeling",
    "management accounting", "financial accounting", "investment banking",
    "private equity", "asset management", "wealth management", "equity research",
    "risk management", "credit risk", "market risk", "internal audit",
    "external audit", "corporate finance", "corporate tax", "management consulting",
    "strategy consulting", "data analysis", "data analytics", "business analysis",
    "business intelligence", "supply chain", "project management", "product management",
    "digital marketing", "performance marketing", "content marketing",
    "social media", "email marketing", "brand management", "market research",
    "customer success", "customer experience", "public relations",
    "search engine optimisation", "search engine optimization", "paid search",
    "paid social", "google analytics", "google ads", "power bi", "microsoft excel",
    "pivot tables", "vlookup", "sql", "python", "tableau", "salesforce", "hubspot",
    "problem solving", "stakeholder management", "communication skills",
    "attention to detail", "time management", "commercial awareness",
    "client facing", "presentation skills", "team player", "self starter",
    "chartered accountant", "acca", "aca", "cima", "cfa", "actuarial",
]
_PHRASE_RE = re.compile("|".join(re.escape(p) for p in sorted(PHRASES, key=len, reverse=True)))


def tokenise(text: str) -> list[str]:
    """Lower-cased content words plus any recognised multi-word phrases."""
    low = text.lower()
    found = [m.group(0).replace(" ", "_") for m in _PHRASE_RE.finditer(low)]
    words = []
    for raw in _WORD_RE.findall(low):
        w = raw.strip(".-/&+")
        if len(w) > 2 and w not in STOPWORDS and not w.isdigit():
            words.append(w)
    return found + words


def keywords(text: str, limit: int = 70) -> list[str]:
    """Most frequent distinct terms, frequency-ordered, for compact matching."""
    counts: dict[str, int] = {}
    for tok in tokenise(text):
        counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [term for term, _ in ranked[:limit]]


def summarise(text: str, limit: int = 420) -> str:
    """A short readable teaser for the results card."""
    flat = normalise_ws(text).replace("\n", " ")
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    tail = cut.rfind(". ")
    if tail > limit * 0.5:
        return cut[: tail + 1]
    return cut.rsplit(" ", 1)[0] + "…"
