#!/usr/bin/env bash
# Installs two user services so MiniSim starts on boot: engine + dashboard.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_SYSTEMD="$HOME/.config/systemd/user"
mkdir -p "$USER_SYSTEMD"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

cat > "$USER_SYSTEMD/minisim-engine.service" << UNIT
[Unit]
Description=MiniSim v5 trading engine
After=network-online.target
[Service]
WorkingDirectory=$DIR
ExecStart=$PY $DIR/main.py
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
UNIT

cat > "$USER_SYSTEMD/minisim-dashboard.service" << UNIT
[Unit]
Description=MiniSim v5 dashboards (Pi + mobile)
After=network-online.target
[Service]
WorkingDirectory=$DIR
ExecStart=$PY -m dashboard.server
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now minisim-engine.service minisim-dashboard.service
loginctl enable-linger "$USER" 2>/dev/null || true
echo "Installed. Engine + dashboard will now start on boot."
echo "Status: systemctl --user status minisim-engine minisim-dashboard"
