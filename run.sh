#!/usr/bin/env bash
# Start engine + dashboard together; Ctrl+C stops both.
DIR="$(cd "$(dirname "$0")" && pwd)"; cd "$DIR"
[ -d .venv ] && source .venv/bin/activate
python -m dashboard.server & DASH=$!
trap "kill $DASH 2>/dev/null" EXIT
python main.py
