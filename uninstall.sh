#!/usr/bin/env bash
# Stop Kairo services. Data in ~/kairo-data is kept.
set -u
if [ "$(uname -s)" = Darwin ]; then
  for l in server desk intensif ai caffeinate cloudflared; do
    launchctl bootout "gui/$(id -u)/com.kairo.$l" 2>/dev/null && echo "arrêté : com.kairo.$l"
    rm -f "$HOME/Library/LaunchAgents/com.kairo.$l.plist"
  done
else
  sudo systemctl disable --now kairo 2>/dev/null || true
  sudo rm -f /etc/systemd/system/kairo.service
  sudo systemctl daemon-reload || true
fi
echo "Services retirés. Données conservées dans ${DATA_DIR:-$HOME/kairo-data}."
