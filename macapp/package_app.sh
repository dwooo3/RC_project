#!/bin/bash
# Build a release binary and assemble a double-clickable RiskCalc.app bundle.
# Usage: ./package_app.sh   (run from macapp/)
set -euo pipefail
cd "$(dirname "$0")"

CONFIG=${1:-release}
echo "▸ swift build -c $CONFIG"
swift build -c "$CONFIG"

BIN=".build/$CONFIG/RiskCalc"
APP="build/RiskCalc.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/RiskCalc"
cp Info.plist "$APP/Contents/Info.plist"

# Ad-hoc codesign so macOS will run/grant it locally.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true

echo "▸ built $APP"
