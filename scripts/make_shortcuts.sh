#!/usr/bin/env bash
# Creates double-click desktop launchers pointing at THIS install location.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESK="$HOME/Desktop"; mkdir -p "$DESK"
PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
TERM_CMD="lxterminal -e"; command -v lxterminal >/dev/null || TERM_CMD="x-terminal-emulator -e"

cat > "$DESK/MiniSim Dashboard.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=MiniSim Dashboard
Comment=Open the MiniSim dashboard
Exec=xdg-open http://localhost:8770/pi
Icon=utilities-system-monitor
Terminal=false
DESKTOP

cat > "$DESK/Start MiniSim.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Start MiniSim
Comment=Start the MiniSim engine + dashboard
Exec=$TERM_CMD "bash -c 'systemctl --user start minisim-engine minisim-dashboard 2>/dev/null || \"$DIR/run.sh\"; sleep 2; xdg-open http://localhost:8770/pi'"
Icon=media-playback-start
Terminal=false
DESKTOP

cat > "$DESK/Stop MiniSim.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Stop MiniSim
Comment=Stop MiniSim trading
Exec=$TERM_CMD "bash -c 'systemctl --user stop minisim-engine minisim-dashboard 2>/dev/null; pkill -f main.py; pkill -f dashboard.server; echo Stopped; sleep 1'"
Icon=media-playback-stop
Terminal=false
DESKTOP

chmod +x "$DESK"/*.desktop 2>/dev/null || true
# mark them trusted on Raspberry Pi OS so double-click runs without a prompt
for f in "$DESK"/MiniSim*.desktop "$DESK"/Start*.desktop "$DESK"/Stop*.desktop; do
  gio set "$f" metadata::trusted true 2>/dev/null || true
done
echo "Desktop shortcuts created in $DESK"
