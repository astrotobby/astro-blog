#!/usr/bin/env bash
# Installs the HyperFrames CLI (HTML -> MP4 via headless Chrome + FFmpeg) into
# .hyperframes/ for the animated stat / key-point scenes (scripts/motion_cards.py).
# Needs Node 22+. Runs as a continue-on-error workflow step: if it fails, the render
# keeps the stock clips for those scenes.
set -euo pipefail

mkdir -p .hyperframes
cd .hyperframes
[ -f package.json ] || npm init -y >/dev/null
echo "[hyperframes] installing CLI..."
npm install --no-audit --no-fund hyperframes@0.8.198
npx hyperframes --version || true
npx hyperframes render --help || true
echo "[hyperframes] setup complete"
