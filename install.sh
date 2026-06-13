#!/usr/bin/env bash
# =============================================================================
#  MiniSim v5 — ONE-CLICK SETUP for Raspberry Pi
#  Double-click this file and choose "Execute in Terminal", or run:  bash install.sh
#  Safe to re-run any time. Does NOT trade or touch money — sets things up only.
# =============================================================================
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say(){ echo -e "${GREEN}==>${NC} $1"; }
warn(){ echo -e "${YELLOW}!! ${NC} $1"; }

echo "============================================================"
echo "   MiniSim v5  —  one-click setup"
echo "============================================================"

# --- 1. system packages (needed to build the local AI + run the app) ----------
if command -v apt-get >/dev/null 2>&1; then
  say "Installing system packages (you may be asked for your password)…"
  sudo apt-get update -y -qq || warn "apt update had warnings (continuing)"
  sudo apt-get install -y -qq python3-venv python3-pip python3-dev \
       build-essential cmake git libopenblas-dev curl \
    || warn "Some system packages failed (continuing — may still work)."
else
  warn "Not a Debian/Raspberry Pi OS system — skipping system packages."
fi

# --- 2. python virtual environment -------------------------------------------
say "Creating the Python environment…"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel -q

# --- 3. python dependencies ---------------------------------------------------
say "Installing dependencies (this can take several minutes on a Pi)…"
if ! pip install -r requirements.txt -q; then
  warn "Full install failed. Retrying without the heavy AI library…"
  grep -v '^llama-cpp-python' requirements.txt > /tmp/req_lite.txt
  pip install -r /tmp/req_lite.txt -q
  warn "Installed WITHOUT llama-cpp-python. The system will run with the safe"
  warn "neutral fallback until you install it later:  pip install llama-cpp-python"
fi

# --- 4. config files ----------------------------------------------------------
if [ ! -f config/secrets.py ]; then
  cp config/secrets.example.py config/secrets.py
  say "Created config/secrets.py (blank — fine for paper mode)."
fi

# --- 5. quantized AI model ----------------------------------------------------
say "Downloading the on-device AI model (~2GB, one time, to your SSD)…"
if ! bash scripts/download_model.sh; then
  warn "Model download skipped/failed. The system still runs (safe fallback)."
  warn "Re-run later with:  bash scripts/download_model.sh"
fi

# --- 6. run a quick self-test -------------------------------------------------
say "Running the built-in tests…"
python tests/run_tests.py | tail -3 || warn "Some tests failed — see output above."

# --- 7. auto-start services + desktop shortcuts -------------------------------
say "Setting up auto-start on boot…"
bash scripts/install_services.sh || warn "Service install skipped (you can run manually with ./run.sh)."

say "Creating desktop shortcuts…"
bash scripts/make_shortcuts.sh || warn "Could not create desktop shortcuts."

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "============================================================"
echo -e "${GREEN}  Setup complete!${NC}"
echo "  • On this Pi's screen:  http://localhost:8770/pi"
echo "  • On your phone:        http://${IP:-<pi-ip>}:8770"
echo "  • Desktop now has: 'MiniSim Dashboard', 'Start MiniSim', 'Stop MiniSim'."
echo "  Running in PAPER mode (pretend money). Nothing real is traded."
echo "============================================================"
