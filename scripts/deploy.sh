#!/usr/bin/env bash
# One-command deploy for astrotobby.site (bash / Git Bash / CI).
# Cleans content, commits, and pushes to main — Cloudflare's git integration then
# builds & deploys automatically. A failed CF build leaves the live site untouched.
#
# Usage:  ./scripts/deploy.sh ["commit message"]
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "==> Normalizing content (descriptions, tags, titles)..."
node scripts/normalize-content.mjs

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" != "main" ]; then echo "Not on main (on '$branch'). Aborting."; exit 1; fi

git add -A
if git diff --cached --quiet; then echo "Nothing to deploy — working tree clean."; exit 0; fi

echo "==> Files to deploy:"; git diff --cached --name-only | sed 's/^/   /'

msg="${1:-Deploy: content + SEO/conversion update $(date '+%Y-%m-%d %H:%M')}"
git commit -m "$msg" >/dev/null
echo "==> Pushing to origin/main (triggers Cloudflare build)..."
git push origin main

echo
echo "Deployed. Cloudflare is now building."
echo "Watch: Cloudflare dashboard -> Workers & Pages -> astro-blog -> Deployments"
echo "Live in ~1-3 min at https://astrotobby.site"
