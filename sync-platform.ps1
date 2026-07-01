param(
  [switch]$SkipDocker,
  [switch]$NoPush
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo

Write-Host "Checking repository state..."
$branch = git branch --show-current
if ($branch -ne "main") {
  git checkout main
}

$dirty = git status --porcelain
if ($dirty) {
  Write-Error "Working tree is not clean. Commit, stash, or discard local changes before syncing."
}

Write-Host "Fetching upstream (Alejandro) and origin (mgarci7 fork)..."
git fetch upstream main
git fetch origin main

Write-Host "Merging origin/main into local main..."
git merge origin/main

Write-Host "Merging upstream/main into local main..."
git merge upstream/main

if (-not $NoPush) {
  Write-Host "Pushing synced main to origin..."
  git push origin main
}

if (-not $SkipDocker) {
  Write-Host "Rebuilding and restarting Docker services..."
  docker compose build app frontend
  docker compose up -d app frontend
}

Write-Host "Done. Local platform is synced with upstream and available through the current Docker project."
