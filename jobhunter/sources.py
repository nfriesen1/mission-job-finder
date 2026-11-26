"""Job sources. Each fetcher returns a list[Job] and raises on hard failure;
the runner catches errors per source so one broken site never stops the run."""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from .models import Job
from .textutil import html_to_text, parse_relative_date, parse_salary

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class Http:
    def __init__(self, delay: float = 0.6, timeout: int = 20):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        self.delay, self.timeout = delay, timeout
        self.consecutive_failures = 0

    def get(self, url: str, **kw) -> requests.Response:
        try:
            r = self._get(url, **kw)
            self.consecutive_failures = 0
            return r
        except requests.HTTPError:
            raise                                        # site answered (e.g. 404) — network is fine
        except Exception:
            self.consecutive_failures += 1
            raise

    def _get(self, url: str, **kw) -> requests.Response:
        if self.consecutive_failures >= 5:
            raise ConnectionError("network unreachable (5 consecutive failures)")
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
                if r.status_code in (429, 502, 503) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                time.sleep(self.delay)
                return r
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2 or self.consecutive_failures:
                    raise
                time.sleep(2)
        raise RuntimeError(f"failed: {url}")


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- Tech Jobs for Good
TJFG_BASE = "https://techjobsforgood.com"


def parse_tjfg_list(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for a in soup.select("a.content[href*='/jobs/']"):
        title = a.select_one(".job-title")
        if not title:
            continue
        company = a.select_one(".company_name")
        loc = a.select_one(".location")
        sal = a.select_one(".salary")
        date = a.select_one(".date-posted")
        tags = [t.get_text(" ", strip=True) for t in a.select(".ui.label")]
        snippet = a.select_one(".job-snippet")
        sal_text = sal.get_text(" ", strip=True) if sal else ""
        lo, hi = parse_salary(sal_text)
        href = a["href"].split("?")[0]
        location = loc.get_text(" ", strip=True) if loc else ""
        jobs.append(Job(
            source="Tech Jobs for Good",
            title=title.get_text(" ", strip=True),
            company=company.get_text(" ", strip=True).title() if company else "",
            url=urljoin(TJFG_BASE, href),
            location=location,
            remote="remote" in location.lower(),
            description=snippet.get_text(" ", strip=True) if snippet else "",
            salary_text=sal_text, salary_min=lo, salary_max=hi,
            posted=parse_relative_date(date.get_text(" ", strip=True)) if date else None,
            impact_board=True, tags=tags,
        ))
    return jobs


def parse_tjfg_detail(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".ui.description")
    return el.get_text(" ", strip=True) if el else ""


def fetch_tjfg(http: Http, cfg: dict) -> list[Job]:
    base = {"job_function": "Software Engineering", "remote_jobs": "on"}
    variants = [dict(base, seniority="Mid Level"), base]   # mid-level first, then all remote (some are untagged)
    seen, out = set(), []
    for params in variants:
        html = http.get(f"{TJFG_BASE}/jobs/?{urlencode(params)}").text
        for j in parse_tjfg_list(html):
            if j.url not in seen:
                seen.add(j.url)
                out.append(j)
    for j in out:   # full description for resume matching
        try:
            detail = parse_tjfg_detail(http.get(j.url).text)
            if detail:
                j.description = detail
                if not j.salary_max:
                    j.salary_min, j.salary_max = parse_salary(detail)
                if "full-time" in detail.lower() or "full time" in detail.lower():
                    j.employment_type = "Full-time"
        except Exception as e:  # noqa: BLE001
            log.warning("TJFG detail failed %s: %s", j.url, e)
    return out


# --------------------------------------------------------------------------- Christian Tech Jobs (RSS)
def parse_ctj_rss(xml_text: str) -> list[Job]:
    root = ET.fromstring(xml_text)
    jobs = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc_html = item.findtext("description") or ""
        soup = BeautifulSoup(desc_html, "html.parser")
        ps = soup.find_all("p")
        company, location = "", ""
        if ps:
            head = ps[0].get_text(" ", strip=True)
            if "—" in head:
                company, location = [x.strip() for x in head.split("—", 1)]
            else:
                company = head
        tags_line = next((p.get_text(" ", strip=True) for p in ps if p.get_text().startswith("Tags:")), "")
        tags = [t.strip() for t in tags_line.replace("Tags:", "").split("•") if t.strip()]
        text = html_to_text(desc_html)
        lo, hi = parse_salary(text)
        posted = None
        if item.findtext("pubDate"):
            try:
                posted = parsedate_to_datetime(item.findtext("pubDate"))
            except (TypeError, ValueError):
                pass
        jobs.append(Job(
            source="Christian Tech Jobs", title=title, company=company,
            url=(item.findtext("link") or "").strip(), location=location,
            remote="remote" in (location + " " + tags_line).lower(),
            description=text, salary_min=lo, salary_max=hi, posted=posted,
            impact_board=True, tags=tags,
        ))
    return jobs


def fetch_ctj(http: Http, cfg: dict) -> list[Job]:
    return parse_ctj_rss(http.get("https://www.christiantechjobs.io/api/rss").text)


# --------------------------------------------------------------------------- Applicant-tracking-system APIs
def _greenhouse(http: Http, token: str, name: str) -> list[Job]:
    data = http.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true").json()
    company = data.get("meta", {}).get("name") if isinstance(data.get("meta"), dict) else None
    out = []
    for j in data.get("jobs", []):
        desc = html_to_text(j.get("content", ""))
        loc = (j.get("location") or {}).get("name", "")
        lo, hi = parse_salary(desc)
        out.append(Job(
            source=f"Greenhouse · {token}", title=j.get("title", ""),
            company=name or j.get("company_name") or company or token,
            url=j.get("absolute_url", ""), location=loc,
            remote=True if "remote" in loc.lower() else None,
            description=desc, salary_min=lo, salary_max=hi,
            posted=_iso(j.get("first_published") or j.get("updated_at")), impact_board=True,
        ))
    return out


def _lever(http: Http, token: str, name: str) -> list[Job]:
    data = http.get(f"https://api.lever.co/v0/postings/{token}?mode=json").json()
    out = []
    for j in data:
        cats = j.get("categories") or {}
        desc = " ".join(filter(None, [j.get("descriptionPlain"), j.get("additionalPlain"),
                                      " ".join(html_to_text(l.get("content", "")) for l in j.get("lists", []))]))
        sr = j.get("salaryRange") or {}
        lo, hi = sr.get("min"), sr.get("max")
        if lo and hi and (sr.get("interval") or "").startswith("per-hour"):
            lo, hi = lo * 2080, hi * 2080
        if not hi:
            lo, hi = parse_salary(desc)
        loc = cats.get("location", "") or ", ".join(cats.get("allLocations", []) or [])
        created = j.get("createdAt")
        out.append(Job(
            source=f"Lever · {token}", title=j.get("text", ""), company=name or token,
            url=j.get("hostedUrl", ""), location=loc,
            remote={"remote": True, "onsite": False, "on-site": False, "hybrid": False}.get(
                (j.get("workplaceType") or "").lower(), True if "remote" in loc.lower() else None),
            description=desc, salary_min=lo, salary_max=hi,
            employment_type=cats.get("commitment", ""),
            posted=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
            impact_board=True,
        ))
    return out


def _ashby(http: Http, token: str, name: str) -> list[Job]:
    data = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true").json()
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary") or \
               (j.get("compensation") or {}).get("compensationTierSummary") or ""
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
        lo, hi = parse_salary(comp)
        if not hi:
            lo, hi = parse_salary(desc)
        loc = j.get("location", "")
        out.append(Job(
            source=f"Ashby · {token}", title=j.get("title", ""), company=name or token,
            url=j.get("jobUrl", ""), location=loc,
            remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote" or "remote" in loc.lower(),
            description=desc, salary_text=comp, salary_min=lo, salary_max=hi,
            employment_type=j.get("employmentType", ""), posted=_iso(j.get("publishedAt")),
            impact_board=True,
        ))
    return out


ATS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def fetch_ats(http: Http, cfg: dict) -> tuple[list[Job], list[str]]:
    jobs, errors = [], []
    for kind, tokens in (cfg.get("employers") or {}).items():
        fn = ATS[kind]
        items = tokens.items() if isinstance(tokens, dict) else [(t, None) for t in tokens or []]
        for token, name in items:
            if http.consecutive_failures >= 5:          # network is down — don't burn the whole run
                errors.append(f"{kind}/{token}: skipped (network unreachable)")
                continue
            try:
                jobs.extend(fn(http, token, name))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{kind}/{token}: {type(e).__name__}")
    return jobs, errors


# --------------------------------------------------------------------------- Remotive (public API)
def fetch_remotive(http: Http, cfg: dict) -> list[Job]:
    data = http.get("https://remotive.com/api/remote-jobs?category=software-dev&limit=300").json()
    out = []
    for j in data.get("jobs", []):
        desc = html_to_text(j.get("description", ""))
        lo, hi = parse_salary(j.get("salary", "") or "")
        if not hi:
            lo, hi = parse_salary(desc)
        out.append(Job(
            source="Remotive", title=j.get("title", ""), company=j.get("company_name", ""),
            url=j.get("url", ""), location=j.get("candidate_required_location", ""), remote=True,
            description=desc, salary_text=j.get("salary", ""), salary_min=lo, salary_max=hi,
            employment_type=j.get("job_type", ""), posted=_iso(j.get("publication_date")),
        ))
    return out


# --------------------------------------------------------------------------- LinkedIn / Indeed / etc. via JobSpy
def fetch_jobspy(http: Http, cfg: dict) -> tuple[list[Job], list[str]]:
    from jobspy import scrape_jobs   # imported lazily: heavy dependency
    import math

    # JobSpy logs every blocked request at ERROR level; keep the terminal quiet and report in the digest instead
    for name in list(logging.root.manager.loggerDict):
        if name.lower().startswith("jobspy"):
            logging.getLogger(name).setLevel(logging.CRITICAL)

    sc = cfg.get("jobspy") or {}
    sites = sc.get("sites", ["linkedin", "indeed"])
    terms = sc.get("search_terms", ["software engineer"])
    hours_old = sc.get("hours_old", 72)
    pause = sc.get("seconds_between_searches", 8)
    out, errors = [], []
    for site in sites:
        empty_streak = 0
        for i, term in enumerate(terms):
            if i:
                time.sleep(pause)                     # spacing searches out avoids most 429 blocks
            kw = dict(site_name=[site], search_term=term, location=sc.get("location", "United States"),
                      results_wanted=sc.get("results_per_search", 30), country_indeed="USA",
                      description_format="markdown", enforce_annual_salary=True, verbose=0)
            if site == "indeed":
                kw.update(hours_old=hours_old)           # Indeed allows hours_old OR remote/job_type, not both
            else:
                kw.update(is_remote=True, job_type="fulltime", hours_old=hours_old,
                          linkedin_fetch_description=site == "linkedin")
            try:
                df = scrape_jobs(**kw)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "429" in msg or "block" in msg.lower():
                    errors.append(f"{site}: rate-limited (429) — skipped its remaining searches today")
                    break
                errors.append(f"{site} '{term}': {msg[:120]}")
                continue
            # JobSpy often swallows a 429 and just returns nothing; two empties in a row = blocked
            empty_streak = empty_streak + 1 if df is None or df.empty else 0
            if empty_streak >= 2:
                errors.append(f"{site}: no results twice in a row (likely rate-limited) — skipped the rest")
                break
            if df is None or df.empty:
                continue
            for r in df.to_dict("records"):
                def g(k):
                    v = r.get(k)
                    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v
                posted = g("date_posted")
                if posted is not None and not isinstance(posted, datetime):
                    posted = datetime(posted.year, posted.month, posted.day, tzinfo=timezone.utc)
                desc = str(g("description") or "")
                lo, hi = g("min_amount"), g("max_amount")
                if not hi:
                    lo, hi = parse_salary(desc)
                out.append(Job(
                    source=site.title(), title=str(g("title") or ""), company=str(g("company") or ""),
                    url=str(g("job_url_direct") or g("job_url") or ""), location=str(g("location") or ""),
                    remote=bool(g("is_remote")) if g("is_remote") is not None else None,
                    description=desc, salary_min=lo, salary_max=hi,
                    employment_type=str(g("job_type") or ""), posted=posted,
                ))
    return out, errors
