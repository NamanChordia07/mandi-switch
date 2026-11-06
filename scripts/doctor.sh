#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONUTF8=1
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/doctor.py" "$@"
