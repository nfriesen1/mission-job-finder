"""Daily run:  python -m jobhunter [--config config.yaml] [--dry-run] [--explain]

Uses config.yaml if present, otherwise falls back to config.example.yaml."""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml

from . import sources as S
from .digest import render_html, render_markdown
from .filters import Evaluator
from .models import Job
from .state import State

log = logging.getLogger("jobhunter")
ROOT = Path(__file__).resolve().parent.parent


def collect(cfg: dict, http: S.Http) -> tuple[list[Job], dict[str, str]]:
    on = cfg.get("sources", {})
    jobs: list[Job] = []
    health: dict[str, str] = {}

    def run(name, fn):
        try:
            res = fn(http, cfg)
            got, errs = res if isinstance(res, tuple) else (res, [])
            jobs.extend(got)
            health[name] = f"{len(got)} postings" + (f" ({len(errs)} errors: {'; '.join(errs[:3])})" if errs else "")
        except Exception as e:  # noqa: BLE001
            health[name] = f"FAILED — {type(e).__name__}: {e}"
            log.exception("source %s failed", name)

    if on.get("techjobsforgood", True):
        run("Tech Jobs for Good", S.fetch_tjfg)
    if on.get("christiantechjobs", True):
        run("Christian Tech Jobs", S.fetch_ctj)
    if on.get("employers", True):
        run("Mission-driven employers", S.fetch_ats)
    if on.get("remotive", True):
        run("Remotive", S.fetch_remotive)
    if on.get("jobspy", True):
        run("LinkedIn/Indeed (JobSpy)", S.fetch_jobspy)
    return jobs, health


def dedupe(jobs: list[Job]) -> list[Job]:
    best: dict[str, Job] = {}
    for j in jobs:
        cur = best.get(j.key)
        # prefer impact boards / richer descriptions / salary info
        rank = (j.impact_board, j.salary_max is not None, len(j.description))
        if cur is None or rank > (cur.impact_board, cur.salary_max is not None, len(cur.description)):
            best[j.key] = j
    return list(best.values())


def send_email(subject: str, html_body: str, text_body: str) -> bool:
    host, to = os.getenv("SMTP_HOST"), os.getenv("EMAIL_TO")
    if not (host and to):
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, os.getenv("SMTP_USER", to), to
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS", ""))
        s.send_message(msg)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily mission-driven job finder")
    default_cfg = ROOT / "config.yaml"
    if not default_cfg.exists():
        default_cfg = ROOT / "config.example.yaml"
    ap.add_argument("--config", default=str(default_cfg))
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--digest-dir", default=str(ROOT / "digests"))
    ap.add_argument("--dry-run", action="store_true", help="don't save state or send email")
    ap.add_argument("--explain", action="store_true", help="print why each job was rejected")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if Path(args.config).name == "config.example.yaml":
        log.info("Using config.example.yaml — copy it to config.yaml and personalize it.")
    cfg = yaml.safe_load(Path(args.config).read_text())
    today = date.today()
    state = State(Path(args.data_dir))

    raw, health = collect(cfg, S.Http())
    jobs = dedupe(raw)
    ev = Evaluator(cfg)
    for j in jobs:
        ev.evaluate(j)

    fresh = [j for j in jobs if not state.is_seen(j)]
    matches = sorted([j for j in fresh if not j.hard_fails and not j.soft_fails],
                     key=lambda j: -j.score)[: cfg.get("max_per_day", 8)]
    week = state.delivered_since(7, today) + len(matches)
    target = cfg.get("weekly_target", 3)
    near: list[Job] = []
    if week < target:
        near = sorted([j for j in fresh if not j.hard_fails and len(j.soft_fails) == 1],
                      key=lambda j: -j.score)[: max(cfg.get("max_near_misses", 4), target - week)]

    if args.explain:
        for j in sorted(jobs, key=lambda j: -j.score):
            verdict = "MATCH" if not (j.hard_fails or j.soft_fails) else "; ".join(j.hard_fails + j.soft_fails)
            print(f"[{j.score:5.1f}] {j.title[:60]:60} | {j.company[:24]:24} | {verdict}")

    md = render_markdown(today, matches, near, week, target, health, len(jobs))
    digest_dir = Path(args.digest_dir)
    digest_dir.mkdir(parents=True, exist_ok=True)
    (digest_dir / f"{today.isoformat()}.md").write_text(md)
    (digest_dir / "latest.md").write_text(md)
    print(md)

    # signal to the GitHub workflow whether there's anything worth notifying about
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"new_count={len(matches) + len(near)}\n")
            fh.write(f"match_count={len(matches)}\n")

    if not args.dry_run:
        state.record(matches, "match", today)
        state.record(near, "near-miss", today)
        state.save()
        if matches or near:
            header = md.splitlines()[2]
            subj = f"{len(matches)} new job match{'es' if len(matches) != 1 else ''}" + \
                   (f" + {len(near)} near misses" if near else "") + f" — {today:%b %d}"
            try:
                if send_email(subj, render_html(matches, near, header), md):
                    log.info("emailed digest to %s", os.getenv("EMAIL_TO"))
            except Exception as e:  # noqa: BLE001
                log.error("email failed: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
