#!/usr/bin/env bash
# Creates double-click desktop launchers and installs them for the taskbar panel.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESK="$HOME/Desktop"; mkdir -p "$DESK"
APPS="$HOME/.local/share/applications"; mkdir -p "$APPS"
TERM_CMD="lxterminal -e"; command -v lxterminal >/dev/null || TERM_CMD="x-terminal-emulator -e"

write_desktop() {
  local name="$1"; shift
  printf '%s' "$@" > "$DESK/$name"
  cp "$DESK/$name" "$APPS/$name"
  chmod +x "$DESK/$name" "$APPS/$name"
  gio set "$DESK/$name" metadata::trusted true 2>/dev/null || true
}

write_desktop "minisim-dashboard.desktop" "[Desktop Entry]
Type=Application
Name=MiniSim Dashboard
Comment=Open the MiniSim Pi dashboard
Exec=bash -c 'chromium-browser --new-window http://localhost:8770/pi 2>/dev/null || xdg-open http://localhost:8770/pi'
Icon=utilities-system-monitor
Terminal=false
Categories=Finance;
"

write_desktop "minisim-start.desktop" "[Desktop Entry]
Type=Application
Name=Start MiniSim
Comment=Start the MiniSim trading engine and dashboard
Exec=$TERM_CMD \"bash -c 'sudo systemctl start minisim minisim-dashboard 2>/dev/null; sleep 2; chromium-browser --new-window http://localhost:8770/pi 2>/dev/null || xdg-open http://localhost:8770/pi'\"
Icon=media-playback-start
Terminal=false
Categories=Finance;
"

write_desktop "minisim-stop.desktop" "[Desktop Entry]
Type=Application
Name=Stop MiniSim
Comment=Stop MiniSim trading engine and dashboard
Exec=$TERM_CMD \"bash -c 'sudo systemctl stop minisim minisim-dashboard 2>/dev/null; echo Stopped.; sleep 1'\"
Icon=media-playback-stop
Terminal=false
Categories=Finance;
"

echo "Desktop shortcuts created in $DESK and $APPS"
