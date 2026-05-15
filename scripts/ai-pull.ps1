<#
.SYNOPSIS
  Pull latest ~/.claude from remote, then sync all projects.

.DESCRIPTION
  Pulls the brain repo, then runs sync-ai-docs to propagate CLAUDE.md
  changes to all registered project repos.

.PARAMETER Project
  Optional. After pulling, sync only this project instead of all.

.PARAMETER Status
  Check if remote has updates without pulling.

.EXAMPLE
  ai-pull                # Pull brain + sync all projects
  ai-pull client-a            # Pull brain + sync only client-a
  ai-pull -Status        # Check if updates are available
#>
param(
    [Parameter(Position=0)]
    [string]$Project,

    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$BrainPath = Join-Path $env:USERPROFILE ".claude"
$SyncScript = Join-Path $BrainPath "scripts\sync-ai-docs.ps1"

Write-Host "ai-pull" -ForegroundColor Cyan

# -- Validate --
if (-not (Test-Path (Join-Path $BrainPath ".git"))) {
    Write-Host ("  ERROR: {0} is not a git repo." -f $BrainPath) -ForegroundColor Red
    exit 1
}

Push-Location $BrainPath
try {
    # -- Status check only --
    if ($Status) {
        git fetch origin --quiet
        $local  = git rev-parse HEAD
        $branch = git rev-parse --abbrev-ref HEAD
        $remote = git rev-parse "origin/$branch"
        if ($local -eq $remote) {
            Write-Host "  Up to date." -ForegroundColor Green
        }
        else {
            $behind = git rev-list --count "HEAD..$remote"
            Write-Host ("  {0} commit(s) behind remote." -f $behind) -ForegroundColor Yellow
        }
        return
    }

    # -- Pull --
    Write-Host "  Pulling from origin..." -ForegroundColor Yellow
    git pull origin HEAD
    Write-Host "  Done." -ForegroundColor Green
}
finally {
    Pop-Location
}

# -- Sync projects --
if (Test-Path $SyncScript) {
    Write-Host "  Syncing projects..." -ForegroundColor Yellow
    if ($Project) {
        & $SyncScript -Project $Project
    }
    else {
        & $SyncScript
    }
}
else {
    Write-Host ("  WARN: sync-ai-docs.ps1 not found at {0}" -f $SyncScript) -ForegroundColor DarkYellow
}
