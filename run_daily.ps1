# Local daily runner (Windows). Schedule with Task Scheduler — see README.
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\pip install -q -r requirements.txt
}
if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim()) }
    }
}
New-Item -ItemType Directory -Force data | Out-Null
.\.venv\Scripts\python -m jobhunter *>> data\run.log
Start-Process digests\latest.md
