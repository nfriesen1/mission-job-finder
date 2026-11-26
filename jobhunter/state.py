"""Remembers which jobs you've already been shown, and keeps an application tracker CSV."""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .models import Job

TRACKER_FIELDS = ["date_found", "tier", "score", "title", "company", "salary", "location",
                  "source", "url", "matched_skills", "status", "notes"]


class State:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.json"
        self.tracker_path = self.dir / "tracker.csv"
        self.seen: dict[str, dict] = json.loads(self.seen_path.read_text()) if self.seen_path.exists() else {}

    def is_seen(self, j: Job) -> bool:
        return j.key in self.seen or any(v.get("url") == j.url for v in self._recent_urls())

    def _recent_urls(self):
        return self.seen.values()

    def delivered_since(self, days: int, today: date) -> int:
        cutoff = (today - timedelta(days=days - 1)).isoformat()
        return sum(1 for v in self.seen.values() if v.get("date", "") >= cutoff and v.get("tier") == "match")

    def record(self, jobs: list[Job], tier: str, today: date):
        new = not self.tracker_path.exists()
        with self.tracker_path.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=TRACKER_FIELDS)
            if new:
                w.writeheader()
            for j in jobs:
                self.seen[j.key] = {"date": today.isoformat(), "url": j.url, "tier": tier}
                w.writerow({
                    "date_found": today.isoformat(), "tier": tier, "score": j.score, "title": j.title,
                    "company": j.company, "salary": j.salary_display(), "location": j.location,
                    "source": j.source, "url": j.url, "matched_skills": ", ".join(j.matched_skills),
                    "status": "to apply", "notes": "; ".join(j.soft_fails),
                })

    def save(self):
        self.seen_path.write_text(json.dumps(self.seen, indent=1, sort_keys=True))
