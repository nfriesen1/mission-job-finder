"""Offline tests. Fixture markup/JSON mirrors each source's real structure (captured Nov 2026);
all organizations and postings in the fixtures are fictional."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from jobhunter import __main__ as app
from jobhunter import sources as S
from jobhunter.filters import Evaluator
from jobhunter.models import Job
from jobhunter.textutil import min_years_required, parse_relative_date, parse_salary

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.example.yaml").read_text())
NOW = datetime.now(timezone.utc)


def card(id_, title, company, loc, sal, posted="Posted 1 week ago"):
    return f"""
<div class="content card-inner"><a class="content" href="/jobs/{id_}/?ref=homepage">
 <div class="header job-title" title="{title}">{title}</div>
 <div class="meta company-name"><span class="company_name">{company}</span></div>
 <div class="loc-and-sal"><span class="location">{loc}</span> - <span class="salary">{sal}</span></div>
 <div class="extra content"><div class="ui violet label">Software Engineering</div>
   <div class="ui label">Health &amp; Well-Being</div></div>
 <div class="description"><div class="content job-snippet">We build tools for public health.</div></div>
 <div class="extra content"><span class="date-posted">{posted}</span></div></a></div>
<a href="/jobs/{id_}/?ref=homepage" class="ui button job-card-view-button">View Job</a>"""


TJFG_LIST = "<html><body>" + "".join([
    card(37965, "Senior Software Development Engineer, Full Stack", "Brightpath Savings", "Remote (US)", "$170K - $200K"),
    card(37558, "Full Stack Engineer", "Northwind Civic", "Remote (US)", "$135K - $160K", "Posted 3 weeks ago"),
    card(37413, "Full Stack Software &amp; Data Engineer", "Fairshare Public Benefit Corp.", "Remote (US)", "$95K - $125K"),
    card(37000, "Software Engineer", "Some Org", "Washington, DC (Hybrid)", "$120K - $140K"),
]) + "</body></html>"

TJFG_DETAIL = """<html><body><div class="ui description"> Full Stack Engineer Northwind Civic · Remote (US)
 $135,000 - $159,996 Per Year Job type: Full-time. We build benefits-access software for state agencies.
 You have 3+ years of professional experience with TypeScript, Node.js, React, PostgreSQL and AWS. We practice
 test-driven development and CI/CD. Benefits: medical, dental, 401(k), generous PTO.</div></body></html>"""

CTJ_RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Christian Tech Jobs</title>
<item><title>Software Engineer II</title><description><![CDATA[<p>Hope Harbor Ministries — Remote</p>
<p>Tags: Software Development • Remote</p>Description<br/>Build .NET and C# microservices on AWS with React front ends.
Event-driven architecture with SQS and DynamoDB. 2+ years of experience. Salary: $110,000 - $130,000. Medical, dental, 401k.]]></description>
<link>https://www.christiantechjobs.io/christian-jobs/remote-software-engineer-ii-hope-harbor-1999</link>
<pubDate>{pub}</pubDate><category>Software Development</category></item>
<item><title>Graphic Designer</title><description><![CDATA[<p>Cornerstone Church — Matthews, NC</p><p>Tags: Design</p>]]></description>
<link>https://www.christiantechjobs.io/christian-jobs/graphic-designer-1903</link><pubDate>{pub}</pubDate></item>
</channel></rss>""".replace("{pub}", NOW.strftime("%a, %d %b %Y %H:%M:%S GMT"))

GH = {"jobs": [
    {"title": "Software Engineer, Full Stack", "absolute_url": "https://job-boards.greenhouse.io/secondchance/jobs/1",
     "location": {"name": "Remote (US)"}, "company_name": "Second Chance Data", "first_published": NOW.isoformat(),
     "content": "&lt;p&gt;Second Chance Data is a nonprofit reducing incarceration. 3+ years of experience building "
                "TypeScript, React, Python and PostgreSQL apps on GCP. Salary range: $139,000 - $160,000. "
                "Benefits include health, dental, vision.&lt;/p&gt;"},
    {"title": "Staff Software Engineer", "absolute_url": "https://job-boards.greenhouse.io/secondchance/jobs/2",
     "location": {"name": "Remote (US)"}, "company_name": "Second Chance Data", "first_published": NOW.isoformat(),
     "content": "8+ years of experience. TypeScript React Python"},
]}
LEVER = [{"text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/carewell/x",
          "categories": {"location": "Remote - US", "commitment": "Full-time"}, "workplaceType": "remote",
          "descriptionPlain": "Digital health company. Build event-driven microservices in Java and Spring Boot on AWS "
                              "with Kafka and PostgreSQL. 3+ years of experience.",
          "salaryRange": {"min": 128000, "max": 160000, "currency": "USD", "interval": "per-year-salary"},
          "createdAt": int(NOW.timestamp() * 1000), "lists": []}]
ASHBY = {"jobs": [{"title": "Software Engineer II, Platform", "jobUrl": "https://jobs.ashbyhq.com/greenleaf/y",
                   "location": "Remote", "isRemote": True, "workplaceType": "Remote", "employmentType": "FullTime",
                   "publishedAt": NOW.isoformat(), "isListed": True,
                   "compensation": {"scrapeableCompensationSalarySummary": "$140K - $165K"},
                   "descriptionPlain": "Greenleaf reverses type 2 diabetes for patients. TypeScript, Node.js, AWS Lambda, "
                                       "DynamoDB, Terraform, event-driven systems. 2+ years of experience."}]}
REMOTIVE = {"jobs": [
    {"title": "Full Stack Developer", "company_name": "AdTech Co", "url": "https://remotive.com/1",
     "candidate_required_location": "USA", "job_type": "full_time", "publication_date": NOW.isoformat(),
     "salary": "$120k - $150k", "description": "<p>TypeScript, React, Node.js, AWS, PostgreSQL. Ads optimization.</p>"},
    {"title": "Backend Engineer", "company_name": "EdTech Nonprofit", "url": "https://remotive.com/2",
     "candidate_required_location": "Europe", "job_type": "full_time", "publication_date": NOW.isoformat(),
     "salary": "", "description": "<p>Education nonprofit. Python, AWS, PostgreSQL, Docker.</p>"},
]}


class FakeResp:
    def __init__(self, text="", data=None):
        self.text, self._d = text, data

    def json(self):
        return self._d


def fake_get(self, url, **kw):
    if "techjobsforgood.com/jobs/?" in url:
        return FakeResp(TJFG_LIST)
    if "techjobsforgood.com/jobs/" in url:
        return FakeResp(TJFG_DETAIL)
    if "christiantechjobs" in url:
        return FakeResp(CTJ_RSS)
    if "greenhouse" in url:
        return FakeResp(data=GH)
    if "lever.co" in url:
        return FakeResp(data=LEVER)
    if "ashbyhq" in url:
        return FakeResp(data=ASHBY)
    if "remotive" in url:
        return FakeResp(data=REMOTIVE)
    raise AssertionError(url)


@pytest.fixture
def cfg():
    c = json.loads(json.dumps(CFG))
    c["sources"]["jobspy"] = False
    c["employers"] = {"greenhouse": {"secondchance": "Second Chance Data"}, "lever": ["carewell"], "ashby": {"greenleaf": "Greenleaf Health"}}
    return c


# ---------------------------------------------------------------- unit tests
@pytest.mark.parametrize("text,lo,hi", [
    ("$170K - $200K", 170000, 200000),
    ("$135,000 - $159,996 Per Year", 135000, 159996),
    ("$125,710.00 - $147,702.20.", 125710, 147702.2),
    ("$40 to $95 per hour", 83200, 197600),
    ("Base salary: $120,000", 120000, 120000),
    ("We raised $5M in 2024", None, None),
])
def test_parse_salary(text, lo, hi):
    a, b = parse_salary(text)
    if lo is None:
        assert (a, b) == (None, None)
    else:
        assert a == pytest.approx(lo) and b == pytest.approx(hi)


def test_years_and_dates():
    assert min_years_required("You have 3+ years of professional experience and 5 years with AWS experience") == 3
    assert min_years_required("we were founded 10 years ago") is None
    assert (NOW - parse_relative_date("Posted 3 weeks ago", NOW)).days == 21
    assert (NOW - parse_relative_date("2d ago", NOW)).days == 2


def test_parsers():
    tj = S.parse_tjfg_list(TJFG_LIST)
    assert [j.company for j in tj][:2] == ["Brightpath Savings", "Northwind Civic"]
    assert tj[1].url == "https://techjobsforgood.com/jobs/37558/" and tj[1].salary_max == 160000
    ctj = S.parse_ctj_rss(CTJ_RSS)
    assert ctj[0].company == "Hope Harbor Ministries" and ctj[0].remote and ctj[0].salary_min == 110000


# ---------------------------------------------------------------- end to end
def test_end_to_end(tmp_path, cfg, monkeypatch, capsys):
    monkeypatch.setattr(S.Http, "get", fake_get)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    args = ["--config", str(cfg_path), "--data-dir", str(tmp_path / "data"), "--digest-dir", str(tmp_path / "d"), "--explain"]
    assert app.main(args) == 0
    out = capsys.readouterr().out
    md = (tmp_path / "d" / "latest.md").read_text()
    matched = md.split("## New matches")[1].split("\n## ")[0]
    for good in ["Northwind", "Second Chance Data", "Greenleaf Health", "Hope Harbor", "carewell"]:
        assert good.lower() in matched.lower(), (good, out)
    for bad in ["Brightpath", "Staff Software", "Some Org", "AdTech", "Graphic Designer", "EdTech"]:
        assert bad.lower() not in matched.lower(), (bad, out)
    # second run on the same day: everything already seen → no repeats
    assert app.main(args) == 0
    md2 = (tmp_path / "d" / "latest.md").read_text()
    assert "No brand-new full matches today" in md2
    tracker = (tmp_path / "data" / "tracker.csv").read_text()
    assert "Northwind" in tracker and "to apply" in tracker


def test_near_miss_when_below_target(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(S.Http, "get", fake_get)
    cfg["weekly_target"] = 50
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    app.main(["--config", str(cfg_path), "--data-dir", str(tmp_path / "data"), "--digest-dir", str(tmp_path / "d")])
    md = (tmp_path / "d" / "latest.md").read_text()
    near = md.split("## Near misses")[1].split("## Source health")[0]
    assert "AdTech Co" in near and "no clear social-impact mission" in near


def test_jobspy_mapping(monkeypatch):
    import datetime as dt
    import pandas as pd
    import jobspy
    calls = []

    def fake(**kw):
        calls.append(kw)
        return pd.DataFrame([{
            "site": kw["site_name"][0], "job_url": "https://www.linkedin.com/jobs/view/1", "job_url_direct": None,
            "title": "Software Engineer II", "company": "Open Benefits Lab", "location": "United States",
            "date_posted": dt.date.today(), "job_type": "fulltime", "interval": "yearly",
            "min_amount": 115000.0, "max_amount": 135000.0, "is_remote": True,
            "description": "Nonprofit. TypeScript, React, Node.js, AWS, PostgreSQL. 2+ years of experience. Health insurance.",
        }, {"site": "x", "job_url": "u2", "job_url_direct": float("nan"), "title": "Dev", "company": "c",
            "location": float("nan"), "date_posted": None, "job_type": None, "interval": None,
            "min_amount": float("nan"), "max_amount": float("nan"), "is_remote": float("nan"), "description": None}])

    monkeypatch.setattr(jobspy, "scrape_jobs", fake)
    jobs, errs = S.fetch_jobspy(None, {"jobspy": {"sites": ["linkedin", "indeed"], "search_terms": ["swe"], "seconds_between_searches": 0}})
    assert not errs and len(jobs) == 4 and jobs[0].salary_max == 135000 and jobs[0].remote is True
    assert jobs[1].location == "" and jobs[1].remote is None
    assert "is_remote" not in calls[1] and calls[1]["hours_old"] == 72   # indeed call
    j = Evaluator(CFG).evaluate(jobs[0])
    assert not j.hard_fails and not j.soft_fails, (j.hard_fails, j.soft_fails)


def test_jobspy_stops_when_blocked(monkeypatch):
    import jobspy
    calls = []

    def blocked(**kw):
        calls.append(kw["site_name"][0])
        raise Exception("response status code 429 (blocked: use a proxy)")

    monkeypatch.setattr(jobspy, "scrape_jobs", blocked)
    jobs, errs = S.fetch_jobspy(None, {"jobspy": {"sites": ["linkedin", "indeed"],
                                                 "search_terms": ["a", "b", "c"], "seconds_between_searches": 0}})
    assert calls == ["linkedin", "indeed"] and len(errs) == 2 and "rate-limited" in errs[0]
