$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = "1"
& "$root\.venv\Scripts\python.exe" "$root\scripts\doctor.py" @args
