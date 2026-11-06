#!/usr/bin/env bash
# Start Mandi Core + all custom agents (macOS/Linux). Usage: ./scripts/run_all.sh [--no-ui] [--core-only]
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONUTF8=1
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/run_all.py" "$@"
