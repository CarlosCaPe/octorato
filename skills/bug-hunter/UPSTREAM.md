# Upstream

This skill is a vendored copy of [`codexstar69/bug-hunter`](https://github.com/codexstar69/bug-hunter) (MIT). Imported into this brain on 2026-05-22.

## Why vendored, not git-submodule

The brain itself is a git repo (`octorato`). Adding bug-hunter as a submodule complicates `ai-push` / `ai-pull` workflows. Vendoring keeps the brain self-contained.

## Sync from upstream

```bash
cd /tmp && rm -rf bug-hunter-upstream
git clone --depth=1 https://github.com/codexstar69/bug-hunter.git bug-hunter-upstream
rsync -a --delete \
  --exclude='.git/' \
  --exclude='docs/images/' \
  bug-hunter-upstream/ ~/.claude/skills/bug-hunter/
# review the diff, then commit + ai-push if good
```

## Local pruning

- `docs/images/` (~36MB) — stripped on import. Brain skills don't need marketing imagery.

## License

MIT — see `LICENSE` at the root of this skill.

## Brain integration

`pre-merge-qa-gate` skill now invokes `/bug-hunter --pr current --scan-only` as the default gate (replacing single-shot Reality Checker dispatch). See `~/.claude/skills/pre-merge-qa-gate/SKILL.md` for the full rationale.
