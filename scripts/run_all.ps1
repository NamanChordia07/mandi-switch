# Start Mandi Core + all custom agents (Windows). Usage: .\scripts\run_all.ps1 [--no-ui] [--core-only]
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = "1"
& "$root\.venv\Scripts\python.exe" "$root\scripts\run_all.py" @args
