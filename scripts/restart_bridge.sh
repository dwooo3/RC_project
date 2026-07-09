#!/bin/zsh
# Restart the RiskCalc FastAPI bridge with the current code.
set -e
cd "$(dirname "$0")/.."
PIDS=$(lsof -ti :8765 || true)
[ -n "$PIDS" ] && { echo "stopping old bridge: $PIDS"; kill $PIDS; sleep 1; }
nohup /usr/local/bin/python3.14 -m api.server > /tmp/rc_bridge.log 2>&1 &
echo "starting…"
for i in {1..30}; do
  sleep 1
  if curl -sf http://127.0.0.1:8765/health > /dev/null; then
    curl -s http://127.0.0.1:8765/health
    echo "\nbridge is up (log: /tmp/rc_bridge.log)"
    exit 0
  fi
done
echo "bridge failed to start — see /tmp/rc_bridge.log" >&2
exit 1
