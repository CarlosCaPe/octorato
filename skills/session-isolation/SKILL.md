---
name: session-isolation
description: "MANDATORY: every concurrent session on a repo needs its own git worktree and session id. NEVER two live sessions on the same working tree. Load before opening a second session, or when investigating 'mis cambios se fueron en el commit de otra sesion'."
metadata:
  short-description: "Each concurrent session gets its own git worktree. Period."
  type: reference
  source: "https://code.claude.com/docs/en/common-workflows#run-parallel-sessions-with-worktrees + lived 2026-06-02 collision"
---

# Session / Instance Isolation

## The rule (one line)

**Each concurrent session must run in its own git worktree. Period.** Two live sessions on one shared working tree is forbidden, even when both are "yours".

## Why: the octopus morphology

The brain is one organism with many semi-autonomous arms. `Arm Isolation (MANDATORY)` already says an arm never knows another arm exists and they never share state. Session isolation is that **same rule applied to time**: the same tentacle can run in two dimensions at once (two parallel sessions), and two instances of one arm are *still two arms*. So they never share an index, a working tree, or a HEAD.

This is not a limit to route around. It's the superpower. A serial human is one thread; they can't truly edit the same file from two minds at once. The octopus can run many isolated instances of itself in parallel, because each instance is sealed in its own checkout. We have the two primitives that make it safe: **session id** (who am I) + **working tree** (where my hands are). The 4D magic is parallelism *with* isolation, never parallelism *instead of* it.

## The collision (what actually happens without it)

Lived on 2026-06-02 in `~/.claude` itself. Two sessions shared ONE worktree (`git worktree list` showed a single checkout). The sequence:

1. Session A creates files (a new skill, edits to `CLAUDE.md`) but hasn't committed yet: they sit **uncommitted in the shared working tree**.
2. Session B runs its own commit flow (`ai-push` / a broad `git add`). The broad stage captures *everything* dirty in the tree, including Session A's uncommitted files.
3. B commits. A's work is now inside **B's commit, under B's unrelated message**.
4. B does `git reset HEAD~1` and re-commits to amend its own work. That churn **splits A's changeset**: some hunks ride into the new commit, some fall back to uncommitted. A's change is now fragmented across the index, on a branch A never chose, none of it pushed.

Nothing is "lost" (it's all on disk), but the changeset is shredded and the shared HEAD is unstable while B iterates. Root cause: **no isolation boundary** + **broad `git add`** + **two live writers on one index**.

## The protocol

### Auto-fork (default since 2026-06-04, fires without you choosing to)

The protocol is no longer discipline. Two reflexes make it structural:

1. **`scripts/session-isolation-hook.py` (SessionStart)** — when a session starts while other live dimensions exist, it auto-runs `octo-dim worktree-init` with the session's stable id and tells the session: all brain work goes through *your* worktree at `~/.octorato/dim/<short>`, the shared `~/.claude` stays read-only for you.
2. **The dimension gate in `scripts/dimension-awareness-hook.py` (PreToolUse, fail-closed)**: while other dimensions are live, a broad `git add -A|--all|.` or `git commit -a` whose target resolves inside the SHARED MAIN checkout of ANY repo (the brain OR an arm) is **denied**, not warned. Explicit pathspec passes; broad staging inside your own dimension worktree passes (linked worktree, `.git` is a pointer file, or any path under `~/.octorato/`, isolated, that's the point). Generalized from brain-only to all repos on 2026-06-09, after a shared arm tree (`<ARM>` on another session's branch, dirty) showed the brain-only gate left arms unprotected.

3. **The two kernel gates in `scripts/g__pretool-write__tree-owner.py` and `scripts/g__pretool-bash__tree-owner.py` (PreToolUse, fail-closed)** cover the half the first two cannot see: two SUBAGENTS of one session. The dimension gate keys its lanes by `session_id`, so those two are one dimension to it and neither is stopped from overwriting the other. Since v8 Phase 2 a lane is keyed by PROCESS (`agent_id`, else `session_id`), claimed on the first write together with the enclosing worktree root, and kept in the kernel process table. A write to a path a different LIVE process holds is denied. So is a whole-tree verb (`git checkout <branch>`, `switch`, `reset --hard|--merge|--keep`, `stash` other than `list`/`show`, `clean -f`, `worktree remove`) in a root where anyone else holds a lane, a pathspec verb (`git checkout -- <paths>`, `git restore`), and a Bash mutation (`rm`, `mv`, `cp` destination, `sed -i`, `tee`, `>`/`>>`) on someone else's lane, matched by equality OR path prefix so `rm -rf <dir>` cannot take a lane sitting under it. The parent is not privileged: owning the tree does not license it to overwrite a child's file. Broad staging (`git add -A|--all|.`, `git commit -a`) is denied on a root where anyone else holds a lane, which is the same shape the dimension gate denies per session and the reason both exist: to that gate, two subagents of one session are ONE dimension, so B's `git add -A` swallowing A's uncommitted files was never stopped. A `-c` body is unwrapped and re-scanned up to three levels, so `bash -c "rm -rf <lane>"` is denied while the same words inside an ordinary quoted argument stay text. Cross-arm writes are denied too, when `company/config/arms-paths.json` declares the boundary, and the residual there is deliberate: the deny needs an arm on BOTH sides, so a brain session writing into an arm passes (that is `sync-ai-docs`) and only arm-to-arm is denied. The kernel's own state is a floor rather than a lane: a write or a shell mutation targeting `~/.claude/.cache/kernel` is denied for every hooked process, since one that can rewrite the table can grant itself any lane and erase the record; the operator's terminal is not hooked and stays the only writer. Every deny names the holding pid, its type and its age, carries its rule id, and lands as a `deny` line in the denied process's journal, so `octo replay` shows the refusal.

**When a lane is stuck:** it is not, usually. A lane frees the moment its holder writes its `exit` line (SubagentStop), when the holder DELEGATES (a `PreToolUse[Agent]` call releases the spawning process's own lanes and journals a `release` line, so a parent never holds its own children hostage to paths it claimed before spawning them; the sibling rule is untouched, child A still cannot take child B's lane), and otherwise after 900s of silence, so a killed or hung builder releases what it holds in 15 minutes. A genuinely stuck one is freed by the OPERATOR with `octo ps --release <pid>` (Phase 1b; on a brain without it, edit the ptable row from the terminal), from a terminal, where no hook fires. An agent cannot do it: the Bash gate denies any command whose boundary-split tokens invoke `octo` or `octo.py` with `--release`, `env -u` wrappers peeled, because an agent that can release the lane denying it has no gate at all.

**Isolating an ARM (not just the brain):** the session does not *start* in an arm, so there is no SessionStart auto-fork for it. When you go to develop in an arm with other sessions live, fork it explicitly: `python3 ~/.claude/scripts/octo-dim.py --session-id <id> worktree-init --repo <arm-path>` → creates a `dim/<id>` worktree at `~/.octorato/arm/<name>/<id>` (out of the arm tree, no gitignore dependency). Same branch carries the session id, so arm commits are isolated AND attributable to the session that made them.

Three historical failure modes these close (all lived 2026-06-02/04):
- isolation was opt-in → nobody forked → everyone wrote on the shared tree;
- `worktree-init` derived the name from the hostname-pid fallback, so `[:8]` collapsed to the hostname prefix and **every "fork" landed in the same worktree** (de-isolation disguised as isolation) — it now refuses to run without a stable session id;
- an argparse subparser default silently clobbered `--session-id` passed before the subcommand, re-triggering the fallback (fixed with `default=SUPPRESS`).

### Starting a parallel session (the Anthropic-native way)
```bash
claude --worktree <name>      # separate checkout on its own branch; run a 2nd with a different <name>
```
Anthropic docs, verbatim: *"Work on a feature in one terminal while Claude fixes a bug in another, without the edits colliding. Each worktree is a separate checkout on its own branch."* (`code.claude.com/docs/en/common-workflows#run-parallel-sessions-with-worktrees`)

### Doing it by hand (e.g. inside an agent that must isolate itself)
```bash
git fetch origin
git worktree add /path/outside/repo/<lane> -b auto/<lane> origin/<default-branch>   # master here, not main
# ... do all edits, commits, push, PR from inside that worktree ...
git worktree remove /path/outside/repo/<lane>                                       # cleanup when merged
```
The Agent tool exposes this as `isolation: "worktree"`: prefer it for any sub-agent that mutates files in parallel.

### Rules inside the protocol
- **One worktree per live lane.** If a second session is already live in the shared tree, the newcomer isolates; it does not join.
- **`git fetch` + branch off the published default** (`origin/master`) so the isolated lane starts clean and its PR diff is minimal. Don't branch off another lane's unpushed WIP.
- **Never a repo-wide `git add -A` while another lane may be dirty.** Stage explicit paths. `ai-push`'s broad allowlist stage is exactly the foot-gun, as in a shared tree it bundles a neighbor's files.
- **Land via PR, not direct push** (operator default on auto-deploy repos). One isolated branch → one PR.
- **Cleanup:** `git worktree remove` (or `git worktree prune`) once merged, so stale checkouts don't accumulate.

## Recovery: if the collision already happened
1. Don't add/commit/reset/push into the shared tree while the other lane is live; you'll just race it again.
2. Back up your created files outside git first (e.g. `cp` to `/tmp`), so a neighbor's `reset --hard` can't take them.
3. Forensics: `git reflog`, `git worktree list`, `git branch --contains <sha>`, `git show --stat <sha>` to find where your hunks landed.
4. Create your own worktree off `origin/<default>`, re-apply your changes there cleanly, commit, push, PR. Leave the other lane's tree untouched.

## Related
- CLAUDE.md `Core Principles` #1 `Arm Isolation` (#7 `Session/Instance Isolation` points here): same rule, space vs time.
- `arm-onboarding`: isolation across *clients* (per-repo arms); this is isolation across *concurrent runs*.
- The Agent tool `isolation: worktree` mode: the in-harness operationalization.
- Memory: the 2026-06-02 lived collision lesson.
