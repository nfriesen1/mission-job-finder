# Mission Job Finder

![tests](https://github.com/nfriesen1/mission-job-finder/actions/workflows/tests.yml/badge.svg)

A daily job scout for software engineers who want their work to matter. Each morning it pulls postings from mission-driven job boards and employers, filters them down to roles that are actually worth applying to, ranks them by how well they match your resume, and delivers a short digest. It never shows the same job twice.

**[See a sample digest →](docs/sample-digest.md)**

## Why I built this

I'm a full-stack engineer looking for my next role at a mission-driven organization: health, civic tech, education, climate, justice or faith-based work. The postings I want are scattered across niche boards and individual company career pages. General job sites bury them under thousands of unrelated listings. Checking all of them every day by hand wasn't sustainable, so I automated it. I set a goal of three strong applications a week, and the tool is built around that number.

## What it does

```
 sources ──► normalize ──► dedupe ──► evaluate ──► rank ──► digest + tracker
```

1. **Collects** postings from several sources (below) and normalizes them into one `Job` model. Each source fails on its own: if one site is down, the source-health section of the digest says so and the rest of the run continues.
2. **Dedupes** the same role posted in several places, keeping the copy with the richest data.
3. **Evaluates** each job with two kinds of rules:
   - **Hard rules** reject a job outright. Examples: not remote, not US, contract or part-time, a junior title, asking for 6+ years, or a resume match that's too weak.
   - **Soft rules** flag a job as a near miss. Examples: salary not listed, a salary slightly under the floor, or a "Senior" title on a posting that asks for only about 3 years.
4. **Scores** jobs by weighted skill overlap with your resume, plus a mission signal, salary, benefits and how recently they were posted.
5. **Keeps a weekly goal.** If fewer than `weekly_target` full matches have come in over the past 7 days, the digest adds the best near misses, so you always have something to apply to.
6. **Delivers** a Markdown digest and appends each pick to a CSV application tracker. It can also send the digest by email (SMTP) or open a GitHub issue.

## Sources

| Source | Method |
|---|---|
| [Tech Jobs for Good](https://techjobsforgood.com) | HTML parsing, using the site's own Mid Level and Remote filters |
| [Christian Tech Jobs](https://www.christiantechjobs.io) | The site's RSS feed |
| About 60 mission-driven employers | Public **Greenhouse, Lever and Ashby** job-board APIs |
| [Remotive](https://remotive.com) | Public API |
| LinkedIn and Indeed *(off by default)* | [JobSpy](https://github.com/speedyapply/JobSpy) |

LinkedIn's and Indeed's terms prohibit automated scraping, and both sites rate-limit it heavily, so that source is **disabled by default**. The tool backs off after the first block instead of retrying. The niche boards and employer APIs turn up most of the mission-driven roles anyway.

## Quick start

```bash
git clone https://github.com/nfriesen1/mission-job-finder.git
cd mission-job-finder
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp config.example.yaml config.yaml          # then edit: your skills, salary floor, sources
.venv/bin/python -m jobhunter --dry-run --explain
```

`--explain` prints every posting with its score and the reasons it passed or failed, which helps when tuning `config.yaml`. Drop `--dry-run` to save state and the tracker.

### Run it daily

- **Locally:** `run_daily.sh` (cron/launchd) or `run_daily.ps1` (Windows Task Scheduler).
- **GitHub Actions:** use [`docs/daily-workflow.yml`](docs/daily-workflow.yml) in a **private** copy of this repo. It commits your job-search state, which you don't want public.

For email, copy `.env.example` to `.env` (or set the same values as Actions secrets).

## Configuration highlights (`config.yaml`)

| Key | Purpose |
|---|---|
| `resume.skills` | Skill → weight map used for matching. Put your own stack here. |
| `filters.min_salary` | Salary floor, compared against the midpoint of the posted range |
| `filters.max_years_required_hard` | Postings asking for this many years or more are rejected |
| `filters.senior_ok_if_years_at_most` | Lets "Senior" titles that ask for few years through as near misses |
| `filters.general_boards_require_impact` | General boards must show a mission keyword |
| `employers` | `token: Name` for any company on Greenhouse, Lever or Ashby |
| `weekly_target` | The weekly goal that turns on near misses |

## Project layout

```
jobhunter/
  sources.py    # one fetcher per source + a shared HTTP client (retries, backoff, circuit breaker)
  filters.py    # hard/soft rule evaluation and scoring
  textutil.py   # salary, relative-date and years-of-experience parsing
  state.py      # seen-jobs memory and the CSV tracker
  digest.py     # Markdown and HTML rendering
  __main__.py   # CLI + orchestration
tests/          # offline tests; fixtures mirror each source's real markup and JSON
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests run fully offline. The fixtures copy each source's real structure (HTML classes, RSS layout, API fields), but every organization and posting in them is fictional.

## License

MIT
