<#
.SYNOPSIS
  Sync .claude/CLAUDE.md to .github/copilot-instructions.md for registered projects.

.DESCRIPTION
  Copies each project's .claude/CLAUDE.md to .github/copilot-instructions.md.
  Run without arguments to sync ALL projects, or pass a project name to sync one.

.PARAMETER Project
  Optional. Sync only this project (e.g., client-a, client-b). Omit to sync all.

.EXAMPLE
  sync-ai-docs           # Sync all registered projects
  sync-ai-docs client-a       # Sync only client-a
#>
param(
    [string]$Project
)

$ErrorActionPreference = 'Stop'

# -- Project registry --
# Format: @{ Name = "absolute path to repo root" }
# Default convention: ~/Documents/github/<CLIENT>
# Add overrides here for non-standard locations.
$DefaultBase = Join-Path $env:USERPROFILE "Documents\github"

# Resolve a project path against a list of candidate locations relative to $env:USERPROFILE.
# Returns the first one that exists, or the first candidate (for a clean SKIP message) if none do.
function Resolve-ProjectPath {
    param([string[]]$Candidates)
    $resolved = $Candidates | ForEach-Object { Join-Path $env:USERPROFILE $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($resolved) { return $resolved }
    return (Join-Path $env:USERPROFILE $Candidates[0])
}

# Project map — loaded from company config if available, empty by default.
# To register your projects, create company/config/arms-paths.json with:
#   { "project-name": "relative/path/from/USERPROFILE" }
$ProjectMap = @{}
# PS 5.1 compatibility: chain 2-arg Join-Path calls (PS 7+ accepts variadic Join-Path).
$ArmsPathConfig = Join-Path (Join-Path (Join-Path (Split-Path $PSScriptRoot) "company") "config") "arms-paths.json"
if (Test-Path $ArmsPathConfig) {
    $raw = Get-Content $ArmsPathConfig -Raw | ConvertFrom-Json
    foreach ($prop in $raw.PSObject.Properties) {
        if ($prop.Value -is [array]) {
            $ProjectMap[$prop.Name] = Resolve-ProjectPath $prop.Value
        } else {
            $ProjectMap[$prop.Name] = Join-Path $env:USERPROFILE $prop.Value
        }
    }
}

# -- Sync logic --
function Sync-ProjectDocs {
    param([string]$Name, [string]$RepoPath)

    if (-not (Test-Path $RepoPath)) {
        Write-Host ("  SKIP {0} - repo not found at {1}" -f $Name, $RepoPath) -ForegroundColor DarkGray
        return $false
    }

    $source = Join-Path $RepoPath ".claude\CLAUDE.md"
    if (-not (Test-Path $source)) {
        Write-Host ("  SKIP {0} - no .claude/CLAUDE.md" -f $Name) -ForegroundColor DarkGray
        return $false
    }

    $targetDir = Join-Path $RepoPath ".github"
    $target    = Join-Path $targetDir "copilot-instructions.md"

    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    Copy-Item -Path $source -Destination $target -Force
    Write-Host ("  OK   {0} - synced" -f $Name) -ForegroundColor Green
    return $true
}

# -- Main --
Write-Host "sync-ai-docs" -ForegroundColor Cyan

if ($Project) {
    if (-not $ProjectMap.ContainsKey($Project)) {
        $keys = $ProjectMap.Keys -join ', '
        Write-Host ("  ERROR: Unknown project '{0}'. Registered: {1}" -f $Project, $keys) -ForegroundColor Red
        exit 1
    }
    Sync-ProjectDocs -Name $Project -RepoPath $ProjectMap[$Project]
}
else {
    $synced = 0
    foreach ($entry in $ProjectMap.GetEnumerator()) {
        if (Sync-ProjectDocs -Name $entry.Key -RepoPath $entry.Value) {
            $synced++
        }
    }
    $total = $ProjectMap.Count
    Write-Host ("  {0}/{1} projects synced." -f $synced, $total) -ForegroundColor Cyan
}
