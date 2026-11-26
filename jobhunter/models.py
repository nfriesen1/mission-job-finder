from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@dataclass
class Job:
    source: str
    title: str
    company: str
    url: str
    location: str = ""
    remote: bool | None = None          # True/False if the source says so, None if unknown
    description: str = ""
    salary_text: str = ""
    salary_min: float | None = None     # annualized USD
    salary_max: float | None = None
    employment_type: str = ""
    posted: datetime | None = None
    impact_board: bool = False          # came from a mission-driven board / curated employer
    tags: list[str] = field(default_factory=list)

    # filled in by the pipeline
    score: float = 0.0
    matched_skills: list[str] = field(default_factory=list)
    impact_hits: list[str] = field(default_factory=list)
    has_benefits: bool = False
    min_years: int | None = None
    soft_fails: list[str] = field(default_factory=list)
    hard_fails: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        company = re.sub(r"\b(inc|llc|pbc|corp|corporation|co|the|ltd)\b", "", norm(self.company))
        return f"{' '.join(company.split())}|{norm(self.title)}"

    @property
    def salary_mid(self) -> float | None:
        if self.salary_min and self.salary_max:
            return (self.salary_min + self.salary_max) / 2
        return self.salary_max or self.salary_min

    def salary_display(self) -> str:
        if self.salary_min and self.salary_max and self.salary_min != self.salary_max:
            return f"${self.salary_min/1000:.0f}K–${self.salary_max/1000:.0f}K"
        if self.salary_mid:
            return f"${self.salary_mid/1000:.0f}K"
        return "Not listed"
