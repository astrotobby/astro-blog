#!/usr/bin/env bash
# Installs the HyperFrames CLI (HTML -> MP4 via headless Chrome + FFmpeg) into
# .hyperframes/ for the animated stat / key-point scenes (scripts/motion_cards.py).
# Needs Node 22+. Runs as a continue-on-error workflow step: if it fails, the render
# keeps the stock clips for those scenes.
set -euo pipefail

mkdir -p .hyperframes
cd .hyperframes
[ -f package.json ] || echo '{"name": "hf-cards", "private": true}' > package.json
echo "[hyperframes] installing CLI..."
npm install --no-audit --no-fund --save-exact hyperframes@0.9.65
npx hyperframes --version
npx hyperframes browser ensure
npx hyperframes doctor
npx hyperframes render --help
echo "[hyperframes] setup complete"
