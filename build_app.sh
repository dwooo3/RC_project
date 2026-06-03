#!/bin/bash
# Build RiskCalc.app for macOS

set -e
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

echo "==> Building RiskCalc.app ..."
echo "    Base dir: $BASE_DIR"

# Clean previous build
rm -rf build dist

# Run PyInstaller
python3 -m PyInstaller RiskCalc.spec \
    --clean \
    --noconfirm \
    --distpath "$BASE_DIR/dist"

echo ""
echo "✅  Build complete!"
echo "    App: $BASE_DIR/dist/RiskCalc.app"
echo ""
echo "==> Opening in Finder..."
open "$BASE_DIR/dist/"
