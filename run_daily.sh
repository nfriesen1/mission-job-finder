#!/usr/bin/env bash
# Local daily runner (macOS / Linux). Schedule with cron or launchd — see README.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] && set -a && . ./.env && set +a      # optional SMTP settings for email
mkdir -p data
.venv/bin/python -m jobhunter "$@" >> data/run.log 2>&1
# macOS: pop a notification and open today's digest
if command -v osascript >/dev/null; then
  osascript -e 'display notification "Today'"'"'s job digest is ready" with title "Job Hunter"'
  open digests/latest.md
fi
