<#
.SYNOPSIS
  Commit + push ~/.claude changes, then sync all projects.

.DESCRIPTION
  Stages all changes in the brain repo (~/.claude), commits with the given
  message, pushes to origin, then runs sync-ai-docs to propagate.

.PARAMETER Message
  Required. Commit message (e.g., "added skill: playwright").

.EXAMPLE
  ai-push "added skill: playwright"
  ai-push "updated CLAUDE.md global rules"
#>
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Message
)

$ErrorActionPreference = 'Stop'
$BrainPath = Join-Path $env:USERPROFILE ".claude"
$SyncScript = Join-Path $BrainPath "scripts\sync-ai-docs.ps1"

Write-Host "ai-push" -ForegroundColor Cyan

# -- Validate --
if (-not (Test-Path (Join-Path $BrainPath ".git"))) {
    Write-Host ("  ERROR: {0} is not a git repo." -f $BrainPath) -ForegroundColor Red
    exit 1
}

# -- Stage + commit --
Push-Location $BrainPath
try {
    $status = git status --porcelain
    if (-not $status) {
        Write-Host "  Nothing to commit - working tree clean." -ForegroundColor DarkGray
    }
    else {
        git add -A
        git commit -m $Message
        Write-Host ("  Committed: {0}" -f $Message) -ForegroundColor Green
    }

    # -- Push --
    Write-Host "  Pushing to origin..." -ForegroundColor Yellow
    git push origin HEAD
    Write-Host "  Pushed." -ForegroundColor Green
}
finally {
    Pop-Location
}

# -- Regenerate neural map (connectome) --
$NeuralScript = Join-Path $BrainPath "scripts\generate_neural_map.py"
if (Test-Path $NeuralScript) {
    Write-Host "  🧠 Regenerating connectome..." -ForegroundColor Cyan
    python3 $NeuralScript 2>$null | Select-Object -Last 20
    Push-Location $BrainPath
    try {
        $mapStatus = git diff --name-only -- neural_map.json
        if ($mapStatus) {
            git add neural_map.json
            git commit --amend --no-edit
            Write-Host "  Connectome updated and amended to commit." -ForegroundColor Green
        }
    }
    finally {
        Pop-Location
    }
}

# -- Sync all projects --
if (Test-Path $SyncScript) {
    Write-Host "  Syncing projects..." -ForegroundColor Yellow
    & $SyncScript
}
else {
    Write-Host ("  WARN: sync-ai-docs.ps1 not found at {0}" -f $SyncScript) -ForegroundColor DarkYellow
}
