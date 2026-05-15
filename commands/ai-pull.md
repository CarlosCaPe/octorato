Pull latest AI brain changes from GitHub into ~/.claude/, update external reference repos, and sync CLAUDE.md to all project arms.

## Arguments
- No argument → pull + sync all projects
- `--status` → show if updates are available without pulling
- Project name (e.g. `client-a`, `client-b`) → pull + sync only that project

## Steps — execute in order using Bash tool

### 1. Handle --status mode
If `$ARGUMENTS` is `--status`:
```bash
cd ~/.claude && git fetch --quiet 2>/dev/null; git rev-parse HEAD; git rev-parse @{u} 2>/dev/null || echo "no-remote"
```
If hashes match: report "Up to date". If behind: show `git log --oneline HEAD..@{u}`. Then stop.

### 2. Pull ~/.claude/
```bash
cd ~/.claude && git pull
```
Capture pre and post hash to detect what changed:
```bash
cd ~/.claude && pre=$(git rev-parse HEAD) && git pull && post=$(git rev-parse HEAD) && git log --oneline "$pre..$post" 2>/dev/null || echo "already up to date"
```

### 3. Update external reference repos
Check and pull `claude-mem-ref`:
```bash
ref_dir=~/.claude/claude-mem-ref
if [ -d "$ref_dir/.git" ]; then
  cd "$ref_dir" && git pull --quiet && echo "claude-mem-ref: updated" || echo "claude-mem-ref: pull failed"
else
  git clone --depth 1 https://github.com/thedotmack/claude-mem.git "$ref_dir" && echo "claude-mem-ref: cloned"
fi
```

### 4. Sync CLAUDE.md to project arms
If `$ARGUMENTS` is a project name:
```bash
~/.local/bin/sync-ai-docs $ARGUMENTS
```
Otherwise sync all:
```bash
~/.local/bin/sync-ai-docs
```

### 5. Report
Show: commits pulled (if any), external refs status, which projects were synced.
If changes were pulled, remind user to commit the updated `copilot-instructions.md` in each affected project.
