"""Filtering and scoring.

Each job collects `hard_fails` (never shown) and `soft_fails` (may be shown as a
"near miss" when the week is running below your target)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Job
from .textutil import min_years_required


def _rx(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


class Evaluator:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        f = cfg["filters"]
        self.f = f
        self.role_rx = _rx(f["title_must_match"])
        self.title_exclude_rx = _rx(f["title_exclude"])
        self.senior_rx = _rx(f["senior_title"])
        self.junior_rx = _rx(f["junior_title"])
        self.non_ft_rx = _rx(f["not_full_time"])
        self.non_us_rx = _rx(f["non_us_locations"])
        self.us_rx = _rx(f["us_locations"])
        self.benefits_rx = _rx(f["benefits_keywords"])
        self.skills = {k.lower(): (v, re.compile(rf"(?<![a-z0-9]){_skill_pattern(k)}(?![a-z0-9])", re.I))
                       for k, v in cfg["resume"]["skills"].items()}
        self.impact = [(k, re.compile(rf"\b{re.escape(k)}", re.I)) for k in cfg["impact_keywords"]]
        self.now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ checks
    def evaluate(self, j: Job) -> Job:
        f, hard, soft = self.f, j.hard_fails, j.soft_fails
        title = j.title
        text = f"{j.title} {j.description}"
        loc = f"{j.location}".lower()

        # role
        if not self.role_rx.search(title):
            hard.append("not a software role")
        if self.title_exclude_rx.search(title):
            hard.append("excluded title")
        if self.junior_rx.search(title):
            hard.append("junior/entry title")

        # remote + US
        loc_text = f"{j.location} {' '.join(j.tags)}"
        is_remote = j.remote is True or "remote" in loc_text.lower()
        if not is_remote:
            hard.append("not remote")
        elif re.search(r"hybrid|on-?site|in[- ]office", loc) and "remote" not in loc:
            hard.append("hybrid/onsite")
        if self.non_us_rx.search(loc_text) and not self.us_rx.search(loc_text):
            hard.append("non-US remote")

        # employment type (benefits come with full-time roles)
        if self.non_ft_rx.search(f"{j.employment_type} {title}"):
            hard.append("not full-time")
        j.has_benefits = bool(self.benefits_rx.search(j.description))

        # freshness
        if j.posted and j.posted.tzinfo is None:
            j.posted = j.posted.replace(tzinfo=timezone.utc)
        if j.posted and self.now - j.posted > timedelta(days=f["max_age_days"]):
            hard.append("too old")

        # seniority
        j.min_years = min_years_required(j.description)
        if j.min_years is not None and j.min_years >= f["max_years_required_hard"]:
            hard.append(f"needs {j.min_years}+ yrs")
        elif j.min_years is not None and j.min_years > f["max_years_required"]:
            soft.append(f"asks {j.min_years}+ yrs")
        if self.senior_rx.search(title):
            # a "Senior" title asking ≤ N years is often mid-level in practice (small nonprofits)
            if j.min_years is not None and j.min_years <= f["senior_ok_if_years_at_most"]:
                soft.append("senior title (but asks only %d yrs)" % j.min_years)
            else:
                hard.append("senior+ title")
        if j.min_years is not None and j.min_years < f["min_years_required"] and not j.hard_fails:
            soft.append(f"may be junior ({j.min_years} yr)")

        # salary
        mid = j.salary_mid
        floor = f["min_salary"]
        if mid is None:
            soft.append("salary not listed")
        elif mid < floor:
            if mid >= floor * f["near_miss_salary_ratio"]:
                soft.append(f"salary {j.salary_display()} slightly under")
            else:
                hard.append(f"salary {j.salary_display()}")

        # resume match
        score, hits = 0.0, []
        for name, (w, rx) in self.skills.items():
            if rx.search(text):
                score += w
                hits.append(name)
        j.matched_skills = hits
        if len(hits) < f["min_skills_matched"] or score < f["min_skill_score"]:
            if len(hits) >= f["min_skills_matched"] - 1 and score >= f["min_skill_score"] * 0.7:
                soft.append("weaker resume match")
            else:
                hard.append("poor resume match")

        # impact / "for good"
        j.impact_hits = sorted({k for k, rx in self.impact if rx.search(f"{text} {j.company} {' '.join(j.tags)}")})
        if not j.impact_board and f["general_boards_require_impact"] and not j.impact_hits:
            soft.append("no clear social-impact mission")

        # ranking score
        rank = score
        rank += 6 if j.impact_board else 2 * min(len(j.impact_hits), 3)
        if mid:
            rank += min(max((mid - floor) / 10_000, 0), 8)
        if j.has_benefits:
            rank += 1
        if j.posted:
            age = (self.now - j.posted).days
            rank += max(0, 5 - age / 3)
        rank -= 4 * len(soft)
        j.score = round(rank, 1)
        return j


def _skill_pattern(k: str) -> str:
    alias = {
        "c#": r"c#|c-sharp|csharp",
        ".net": r"\.net|dotnet|asp\.net",
        "node.js": r"node\.?js|node",
        "typescript": r"typescript|\bts\b",
        "javascript": r"javascript|\bjs\b",
        "postgresql": r"postgres(?:ql)?",
        "aws": r"aws|amazon web services",
        "event-driven": r"event[- ]driven|event sourcing|pub/?sub|message queue|kafka|eventbridge",
        "ci/cd": r"ci/cd|continuous integration|continuous delivery|continuous deployment",
        "tdd": r"tdd|test[- ]driven",
        "full stack": r"full[- ]?stack",
        "backend": r"back[- ]?end",
        "rest": r"restful|rest apis?|rest services|rest endpoints",
        "microservices": r"micro-?services?",
        "github actions": r"github actions",
        "healthcare": r"health ?care|digital health|patients?|clinical|hipaa|phi\b|ehr",
        "opensearch": r"opensearch|elastic ?search",
        "spring boot": r"spring boot|spring framework",
        "ai tools": r"copilot|claude code|cursor|llm|ai[- ]assisted|ai coding",
        "react": r"react(?:\.js|js)?",
    }
    return alias.get(k.lower(), re.escape(k))
