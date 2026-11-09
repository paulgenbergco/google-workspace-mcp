#!/usr/bin/env bash
# Install (or reinstall) the remote MCP server as a launchd agent on macOS.
# Runs `python server.py --http` at login and restarts it if it exits.
#
#   bash deploy/install-launchd.sh            # install / restart
#   bash deploy/install-launchd.sh uninstall  # stop and remove
set -euo pipefail

LABEL="co.genberg.gworkspace-mcp"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/gworkspace-mcp"
DOMAIN="gui/$(id -u)"

# bootout returns before the old process has exited; bootstrapping the same
# label while it is still tearing down fails with "Bootstrap failed: 5:
# Input/output error". Wait (up to ~15s) until launchd has forgotten it.
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  for _ in $(seq 1 30); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 0.5
  done
fi

if [[ "${1:-}" == "uninstall" ]]; then
  rm -f "$PLIST"
  echo "Removed $LABEL."
  exit 0
fi

[[ -x "$REPO/.venv/bin/python" ]] || { echo "No .venv in $REPO. Run: bash setup.sh"; exit 1; }
"$REPO/.venv/bin/python" -c "import uvicorn" 2>/dev/null \
  || { echo "uvicorn missing. Run: $REPO/.venv/bin/pip install -r $REPO/requirements.txt"; exit 1; }

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/python</string>
    <string>$REPO/server.py</string>
    <string>--http</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
PLIST

for attempt in 1 2 3; do
  launchctl bootstrap "$DOMAIN" "$PLIST" && break
  [[ $attempt == 3 ]] && { echo "launchctl bootstrap failed 3 times; see above."; exit 1; }
  echo "Retrying in 2s..."; sleep 2
done
echo "Started $LABEL."
echo "Logs:   tail -f $LOG_DIR/server.log"
PORT="$("$REPO/.venv/bin/python" -c 'import json;print(json.load(open("config.json")).get("remote",{}).get("port",8765))')"
echo "Health: curl -s http://127.0.0.1:$PORT/healthz"
