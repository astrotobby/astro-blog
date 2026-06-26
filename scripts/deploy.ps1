# One-command deploy for astrotobby.site (Windows / PowerShell).
# Cleans content, commits, and pushes to main — Cloudflare's git integration then
# builds & deploys automatically. A failed CF build leaves the live site untouched.
#
# Usage:
#   npm run ship                 # auto commit message (timestamp)
#   npm run ship -- "your message"
#   powershell -File scripts/deploy.ps1 "your message"
param([string]$Message = "")

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root (astro-blog)

Write-Host "==> Normalizing content (descriptions, tags, titles)..." -ForegroundColor Cyan
node scripts/normalize-content.mjs

# Confirm we're on main and have a remote.
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") { Write-Host "Not on main (on '$branch'). Aborting." -ForegroundColor Yellow; exit 1 }

git add -A
$staged = git diff --cached --name-only
if (-not $staged) { Write-Host "Nothing to deploy — working tree clean." -ForegroundColor Green; exit 0 }

Write-Host "==> Files to deploy:" -ForegroundColor Cyan
$staged | ForEach-Object { Write-Host "   $_" }

if ([string]::IsNullOrWhiteSpace($Message)) {
  $Message = "Deploy: content + SEO/conversion update " + (Get-Date -Format "yyyy-MM-dd HH:mm")
}

git commit -m $Message | Out-Null
Write-Host "==> Pushing to origin/main (triggers Cloudflare build)..." -ForegroundColor Cyan
git push origin main

Write-Host ""
Write-Host "Deployed. Cloudflare is now building." -ForegroundColor Green
Write-Host "Watch the build: Cloudflare dashboard -> Workers & Pages -> astro-blog -> Deployments" -ForegroundColor Green
Write-Host "Live in ~1-3 min at https://astrotobby.site" -ForegroundColor Green
