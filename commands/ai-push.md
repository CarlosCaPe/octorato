Commit and push all changes in ~/.claude/ (the AI brain) to GitHub, regenerate the neural connectome, and sync CLAUDE.md to all project arms.

## Steps — execute in order using Bash tool

### 1. Check for changes
```bash
cd ~/.claude && git status --short
```
If output is empty: run sync-ai-docs (step 4) and stop — nothing to commit.

### 2. Stage and commit
```bash
cd ~/.claude && git add -A
```
Commit message: use `$ARGUMENTS` if provided, otherwise auto-generate from changed files:
```bash
cd ~/.claude && git diff --cached --name-only | head -5 | tr '\n' ', ' | sed 's/,$//'
```
### 2b. Hooks drift-guard (FATAL — run before commit)
Block if the live `settings.json` hooks diverged from the tracked `hooks.json` (the recurring "brain never sticks" bug). Resolve before committing:
```bash
python3 ~/.claude/scripts/check-hooks-drift.py || { echo "Hook drift — run merge-hooks.py or check-hooks-drift.py --adopt, then retry"; exit 1; }
```

### 2c. README count + canon markers drift-guard (run before commit, fix if drifted)
The CI status check `README/FAQ counts are rendered (no stale floors)` blocks merges
when EITHER (a) the brain's README/FAQ skill + agent counts drift from the live
filesystem, OR (b) any `<!--canon:...-->` marker across the wider doc set
(`README.md`, `content/EXAMPLE.md`, `docs/wiki/Home.md`, `docs/wiki/_Sidebar.md`,
`docs/FAQ.md`) holds a stale value. **Two scripts must run together** —
`sync-readme-counts.py` covers the rendered floor numbers in README/FAQ,
`canon-render.py` covers every file with canon markers. Running only one leaves
the other surface stale and the CI check FAILS on a PR you thought was clean
(observed 2026-06-10: adding 1 skill crossed the 220 floor — `sync-readme-counts`
reported in-sync but 4 canon markers were stale → PR round-trip).

Pre-emptively re-render before committing — the `--floor` flag rounds the real
count DOWN to the nearest ten so the rendered figure stays TRUE across small
changes (operator stat convention; also enforced by `check-stats-drift.py`):

Bash / Git Bash / WSL:
```bash
python3 ~/.claude/scripts/sync-readme-counts.py --floor
python3 ~/.claude/scripts/canon-render.py
git add README.md docs/FAQ.md content/EXAMPLE.md docs/wiki/Home.md docs/wiki/_Sidebar.md 2>/dev/null
```

PowerShell (Windows):
```powershell
python3 $HOME/.claude/scripts/sync-readme-counts.py --floor
python3 $HOME/.claude/scripts/canon-render.py
git add README.md docs/FAQ.md content/EXAMPLE.md docs/wiki/Home.md docs/wiki/_Sidebar.md 2>$null
```

> **Shell-portability note**: PowerShell parses `2>/dev/null` as a literal file
> path and tries to write to `C:\dev\null` (which fails). Use `2>$null` (the
> automatic null variable) in any PowerShell snippet that wants to swallow stderr.

Modes:
- `--floor`  → renders `190+ skills · 180+ specialist agents` (stable, default for shipping README/FAQ)
- (no flag)  → renders exact integers (useful for debugging the counter; never commit this form)
- `--check`  → dry-run: exit 1 if drift exists, write nothing (used by CI)

If the rendered files changed, fold them into the commit you're about to make; do not
create a separate "chore: bump count" commit unless that's the only change.

Then commit:
```bash
cd ~/.claude && git commit -m "<message>"
```

### 3. Push to remote
```bash
cd ~/.claude && git push -u origin master
```
If push fails because remote doesn't exist:
```bash
cd ~/.claude && git remote add origin https://github.com/YOUR_USERNAME/octorato.git && git push -u origin master
```

### 3b. If push rejected by branch protection (GH006), auto-open PR
The brain's `master` is protected — direct push exits with
`remote rejected ... protected branch hook declined / GH006`. When that fires,
create a feature branch, push it, and open a PR using the GitHub token that
Git Credential Manager (Windows) or the system keyring already cached from the
successful push attempt. No `gh auth login` round-trip needed.

PowerShell (Windows):
```powershell
$branch = "auto/$(Get-Date -Format 'yyyyMMdd-HHmm')-$(git log -1 --pretty=format:%h)"
git checkout -b $branch
git push -u origin $branch

$cred = ("protocol=https`nhost=github.com`n`n" | git credential fill 2>$null)
$env:GH_TOKEN = ($cred | Select-String '^password=' | Select-Object -First 1).Line.Substring(9)

# Write the multi-line body to a temp file — passing it inline via --body
# causes PowerShell to split each line into a separate positional arg and
# gh pr create rejects it (observed 2026-06-10).
$bodyFile = "$env:TEMP/ai-push-pr-body.md"
git log -1 --pretty=format:%b | Set-Content -Path $bodyFile -Encoding UTF8
gh pr create --base master --head $branch `
  --title (git log -1 --pretty=format:%s) `
  --body-file $bodyFile

Remove-Item Env:\GH_TOKEN
Remove-Item $bodyFile -ErrorAction SilentlyContinue
```

Bash / Git Bash / WSL:
```bash
branch="auto/$(date +%Y%m%d-%H%M)-$(git log -1 --pretty=format:%h)"
git checkout -b "$branch"
git push -u origin "$branch"

token=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
GH_TOKEN="$token" gh pr create --base master --head "$branch" \
  --title "$(git log -1 --pretty=format:%s)" \
  --body  "$(git log -1 --pretty=format:%b)"
unset GH_TOKEN token
```

Notes:
- NEVER echo the token. Use the env-var pass-through pattern; don't `Write-Host $token` or `echo $token` anywhere.
- After PR merges: `git checkout master && git pull --ff-only && git branch -D "$branch"`.
- If multiple commits are queued, prefer one PR per logical concern; this fast path stacks them all on a single branch which is fine when they are a single coherent change.

### 4. Regenerate neural connectome

Bash / Git Bash / WSL:
```bash
python3 ~/.claude/scripts/generate_neural_map.py 2>/dev/null | tail -5
```

PowerShell (Windows):
```powershell
python3 $HOME/.claude/scripts/generate_neural_map.py 2>$null | Select-Object -Last 5
```

If `neural_map.json` is tracked AND changed after generation, amend the commit
(if `neural_map.json` is gitignored — current default — this step is a no-op):

Bash / Git Bash / WSL:
```bash
cd ~/.claude && git diff --quiet -- neural_map.json || (git add neural_map.json && git commit --amend --no-edit && git push --force-with-lease origin master)
```

PowerShell (Windows):
```powershell
cd $HOME/.claude
git diff --quiet -- neural_map.json
if ($LASTEXITCODE -ne 0) {
  git add neural_map.json
  git commit --amend --no-edit
  git push --force-with-lease origin master
}
```

> If you reached step 4 via the auto-PR fallback (step 3b), force-push to the
> auto branch instead of `master` — replace `origin master` with
> `origin <auto-branch-name>`.

### 5. Sync CLAUDE.md to all project arms
```bash
~/.local/bin/sync-ai-docs
```
If a specific project was passed in `$ARGUMENTS`, sync only that one:
```bash
~/.local/bin/sync-ai-docs $ARGUMENTS
```

### 6. Report
Show: what was committed, push result, connectome status, which projects were synced.
Tell user: "Run /ai-pull on other laptops to get these changes."
