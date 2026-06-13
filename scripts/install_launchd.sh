#!/bin/bash
# Install (or reinstall) the daily EOD launchd agent (Stage II.1).
# Fills REPLACE_WITH_REPO_PATH in the plist template with this repo's absolute
# path, writes it to ~/Library/LaunchAgents, and (re)loads it.
#
#   ./scripts/install_launchd.sh          # install / reload
#   ./scripts/install_launchd.sh --uninstall
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.riskcalc.eod"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$REPO/scripts/$LABEL.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "Uninstalled $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data/logs"
# Substitute the repo path into the template (| delimiter: path has slashes).
sed "s|REPLACE_WITH_REPO_PATH|$REPO|g" "$TEMPLATE" > "$DEST"

# Reload cleanly (ignore "not loaded" on first install).
launchctl unload "$DEST" 2>/dev/null || true
launchctl load -w "$DEST"

echo "Installed $LABEL -> $DEST"
launchctl list | grep "$LABEL" || echo "(not yet listed — check 'launchctl list')"
echo "Runs weekdays 19:30 local. Logs: $REPO/data/logs/"
echo "Manual run now:  launchctl start $LABEL"
