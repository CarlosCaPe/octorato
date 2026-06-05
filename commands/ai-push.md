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
$env:GH_TOKEN = ($cred | Select-String '^password=' | ForEach-Object { $_.Line.Substring(9) })
gh pr create --base master --head $branch `
  --title (git log -1 --pretty=format:%s) `
  --body (git log -1 --pretty=format:%b)
Remove-Item Env:\GH_TOKEN
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
```bash
python3 ~/.claude/scripts/generate_neural_map.py 2>/dev/null | tail -5
```
If neural_map.json changed after generation, amend the commit:
```bash
cd ~/.claude && git diff --quiet -- neural_map.json || (git add neural_map.json && git commit --amend --no-edit && git push --force-with-lease origin master)
```

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
