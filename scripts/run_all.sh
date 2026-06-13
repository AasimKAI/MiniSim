#!/usr/bin/env bash
# Convenience: start engine + dashboard together in one window (Ctrl+C stops both).
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"; cd "$DIR"
[ -d .venv ] && source .venv/bin/activate
python -m dashboard.server &
DASH=$!
trap "kill $DASH 2>/dev/null" EXIT
python main.py
