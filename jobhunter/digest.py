"""Renders the daily digest as Markdown (for the repo / GitHub issue) and HTML (for email)."""
from __future__ import annotations

import html
from datetime import date

from .models import Job


def _md_job(j: Job, n: int) -> str:
    posted = j.posted.strftime("%b %d") if j.posted else "?"
    lines = [
        f"### {n}. [{j.title}]({j.url}) — {j.company}",
        f"**{j.salary_display()}** · {j.location or 'Remote'} · posted {posted} · via {j.source} · score {j.score}",
        "",
        f"- **Resume overlap:** {', '.join(j.matched_skills[:12]) or '—'}",
    ]
    if j.impact_hits:
        lines.append(f"- **Mission signals:** {', '.join(j.impact_hits[:6])}")
    extras = []
    if j.has_benefits:
        extras.append("benefits mentioned ✓")
    if j.min_years is not None:
        extras.append(f"asks {j.min_years}+ yrs")
    if extras:
        lines.append(f"- {' · '.join(extras)}")
    if j.soft_fails:
        lines.append(f"- ⚠️ {'; '.join(j.soft_fails)}")
    return "\n".join(lines) + "\n"


def render_markdown(today: date, matches: list[Job], near: list[Job], week_count: int,
                    target: int, health: dict[str, str], total_scanned: int) -> str:
    out = [f"# Job digest — {today:%A, %b %d %Y}", ""]
    status = "✅ on track" if week_count >= target else f"⏳ {target - week_count} short of your goal"
    out.append(f"**{len(matches)} new match{'es' if len(matches) != 1 else ''} today** · "
               f"{week_count} in the last 7 days (goal {target}/week — {status}) · {total_scanned} postings scanned")
    out.append("")
    if matches:
        out.append("## New matches")
        out += [_md_job(j, i + 1) for i, j in enumerate(matches)]
    else:
        out.append("_No brand-new full matches today._\n")
    if near:
        out.append("## Near misses (shown because the week is below your goal)")
        out.append("_Each fails exactly one soft rule — worth a quick look._\n")
        out += [_md_job(j, i + 1) for i, j in enumerate(near)]
    out.append("## Source health")
    for name, msg in health.items():
        out.append(f"- {name}: {msg}")
    return "\n".join(out) + "\n"


def render_html(md_matches: list[Job], near: list[Job], header: str) -> str:
    def card(j: Job) -> str:
        warn = f"<div style='color:#a15c00'>⚠️ {html.escape('; '.join(j.soft_fails))}</div>" if j.soft_fails else ""
        return (f"<div style='margin:0 0 18px;padding:12px 14px;border:1px solid #e3e3e3;border-radius:8px'>"
                f"<a href='{html.escape(j.url)}' style='font-size:16px;font-weight:600'>{html.escape(j.title)}</a>"
                f" — {html.escape(j.company)}<br>"
                f"<b>{j.salary_display()}</b> · {html.escape(j.location or 'Remote')} · {html.escape(j.source)}<br>"
                f"<span style='color:#555'>Overlap: {html.escape(', '.join(j.matched_skills[:10]))}</span>{warn}</div>")
    body = [f"<div style='font-family:-apple-system,Segoe UI,sans-serif;max-width:680px'>",
            f"<p>{html.escape(header)}</p>"]
    if md_matches:
        body.append("<h2>New matches</h2>" + "".join(card(j) for j in md_matches))
    if near:
        body.append("<h2>Near misses</h2>" + "".join(card(j) for j in near))
    body.append("</div>")
    return "".join(body)
