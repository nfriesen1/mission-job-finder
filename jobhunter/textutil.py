"""Parsing helpers: salaries, relative dates, years of experience, HTML to text."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def html_to_text(s: str) -> str:
    if not s:
        return ""
    if "<" not in s and "&lt;" in s:          # Greenhouse returns escaped HTML
        s = html.unescape(s)
    text = BeautifulSoup(s, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?([kK])?"
_RANGE = re.compile(_AMT + r"\s*(?:-|–|—|to)\s*(?:USD\s*)?\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?([kK])?"
                    r"(?P<tail>[^.\n]{0,40})", re.I)
_SINGLE = re.compile(_AMT + r"(?P<tail>[^.\n]{0,40})", re.I)


def _to_num(v: str, k: str | None) -> float:
    n = float(v.replace(",", ""))
    return n * 1000 if k else n


def _annualize(lo: float, hi: float, context: str) -> tuple[float, float] | None:
    c = context.lower()
    if re.search(r"(?:/|\bper\b|\ban?\b)\s*(?:hr|hour)\b|\bhourly\b", c) or hi < 300:
        lo, hi = lo * 2080, hi * 2080
    elif re.search(r"(?:/|\bper\b|\ba\b)\s*(?:mo|month)\b|\bmonthly\b", c):
        lo, hi = lo * 12, hi * 12
    if hi < 20_000 or hi > 1_500_000:
        return None
    return lo, hi


def parse_salary(text: str) -> tuple[float | None, float | None]:
    """Return an annualized (min, max) USD salary from free text, or (None, None)."""
    if not text:
        return None, None
    for m in _RANGE.finditer(text):
        lo, hi = _to_num(m.group(1), m.group(2)), _to_num(m.group(3), m.group(4) or m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        before = text[max(0, m.start() - 40):m.start()]
        res = _annualize(lo, hi, m.group("tail") + " " + before)
        if res:
            return res
    for m in _SINGLE.finditer(text):
        before = text[max(0, m.start() - 60):m.start()].lower()
        if not re.search(r"salary|compensation|pay|base|range|wage", before + m.group("tail").lower()):
            continue
        v = _to_num(m.group(1), m.group(2))
        res = _annualize(v, v, m.group("tail") + " " + before)
        if res:
            return res
    return None, None


def parse_relative_date(s: str, now: datetime | None = None) -> datetime | None:
    """'Posted 3 weeks ago', '2d ago', 'today', 'yesterday' -> datetime."""
    now = now or datetime.now(timezone.utc)
    s = (s or "").lower()
    if "today" in s or "just" in s or "hour" in s or "minute" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r"(\d+|a|an)\s*(d|day|days|w|week|weeks|mo|month|months|y|year|years)\b", s)
    if not m:
        return None
    n = 1 if m.group(1) in ("a", "an") else int(m.group(1))
    unit = m.group(2)
    days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit[0] if not unit.startswith("mo") else "m"]
    return now - timedelta(days=n * days)


_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*years?"
                    r"(?P<tail>[^.;\n]{0,60})", re.I)


def min_years_required(text: str) -> int | None:
    """Smallest 'N+ years of experience' requirement found in text."""
    found = []
    for m in _YEARS.finditer(text or ""):
        tail = m.group("tail").lower()
        if "experience" in tail or "professional" in tail or "industry" in tail or "working" in tail:
            n = int(m.group(1))
            if 0 < n <= 20:
                found.append(n)
    return min(found) if found else None


# Query parameters that only track where a click came from. Some carry per-click
# tokens (e.g. Indeed's indeed-apply-token) that secret scanners flag, and all of
# them make one job look like several. Parameters that identify the job itself
# (Indeed's jk=, Greenhouse's gh_jid=, LinkedIn's currentJobId=) are kept.
_TRACKING_PARAMS = {
    "iis", "iisn", "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "mc_cid", "mc_eid",
    "trk", "trkinfo", "trackingid", "refid", "ref", "_hsenc", "_hsmi", "src", "source",
}


def clean_url(url: str) -> str:
    """Strip tracking parameters (utm_*, *token*, click ids, ...) and the fragment from a URL."""
    if not url or "?" not in url and "#" not in url:
        return url
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not (k.lower().startswith("utm_") or "token" in k.lower() or k.lower() in _TRACKING_PARAMS)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
