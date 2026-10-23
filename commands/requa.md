---
description: Re-review a pull request whose head moved only because its base moved. Proves the patch is the one that already passed QA and records a QA receipt for the new head; any other change means a full QA.
---

# /requa <pr>: re-QA after a base update

A QA PASS approves the commit it names, and `qa-merge-gate` merges only that commit. When master moves and the pull request is updated from it ("Update branch", a merge of master into the branch), the head changes and the old PASS no longer applies, although the patch the reviewer read may be the same. `/requa` checks that claim against the remote and, only when it holds, writes the receipt lines for the new head. It is spec v10 task T08 (AC-12, AC-13).

## Who runs it

Dispatch it as a subagent with a verifier persona (Reality Checker, Code Reviewer or Evidence Collector) on the judgment tier: Claude Code binds that to Fable, other runtimes to the strongest independent engine at least as strong as the builder. The SubagentStop reflex records a receipt only for a QA persona, so a main-loop run of these steps writes nothing the gate reads. Default verdict is NEEDS-WORK: every step below must produce its evidence or the run ends there.

`/requa` never edits `scripts/qa-merge-gate.py`, never sets or exports `OCTO_MERGE_APPROVE`, and never merges. The merge gate keeps deciding on the newest receipt for the pinned head (AC-13). This command only produces that receipt, the same way a full review does.

## Steps

Set `PR` to the argument and `R` to the repository it belongs to (`R=$(gh repo view --json nameWithOwner --jq .nameWithOwner)` from inside the clone). Work in a fresh clone or a worktree of your own, never in the live brain.

Steps 3 and 4 run `scripts/requa.py`, the brain's Base_Update_Verifier helper, from the installed brain and never from the clone under review, because a pull request can edit its own copy: `REQUA="$HOME/.claude/scripts/requa.py"`. The helper takes every remote answer (parents, compare status, merge bases) as an argument, so it never reads master or the network itself, and its git diffs accept only full commit SHAs. `scripts/tests/test_requa_protocol.py` pins its behaviour over a fixture repo.

### 1. Read remote master and the new head through `gh`

```bash
MASTER=$(gh api "repos/$R/commits/master" --jq .sha)
NEW=$(gh pr view "$PR" --repo "$R" --json headRefOid --jq .headRefOid)
```

Never read master from a local ref (`master`, `origin/master`, `FETCH_HEAD`): any of them can be moved by one local command, and a merge base taken from a moved ref can hide unreviewed code. Commit SHAs are content-addressed, so fetching objects by SHA is safe: `git fetch origin "$MASTER" "$NEW"`.

### 2. Find the head that holds the newest QA PASS

Read the receipt ledger through its own lookup, not by grepping it:

```bash
OLD=$(python3 - "$PR" <<'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
import receipt_ledger as rl
pr = sys.argv[1]
heads = {r.get("head") for r in rl.read_global()
         if r.get("kind") == "qa" and r.get("verdict") == "PASS"
         and rl.scope_names(str(r.get("scope") or ""), pr) and r.get("head")}
live = [d for d in (rl.qa_latest_for(pr, h) for h in heads) if d and d.get("verdict") == "PASS"]
best = max(live, key=lambda d: d["verdict_ts"], default=None)  # ISO harness timestamp
print(best["head"] if best else "NONE")
EOF
)
echo "$OLD"
```

`qa_latest_for` re-reads each receipt from its anchored transcript entry and drops a PASS that a later FAIL or NEEDS-WORK revoked, so `OLD` is a head whose own newest verdict is PASS. `NONE` ends the run: there is no PASS to carry, and the PR needs a full QA.

### 3. Prove the head moved only by its base

```bash
PARENTS=$(gh api "repos/$R/commits/$NEW" --jq '.parents[].sha'); echo "$PARENTS"
P2=$(python3 "$REQUA" parents --old "$OLD" $PARENTS) || { echo "$P2"; exit 1; }
python3 "$REQUA" on-master "$(gh api "repos/$R/compare/$P2...$MASTER" --jq .status)" || exit 1
```

The new head must have exactly two parents: `OLD` and a second parent `P2`. The compare of `P2` against remote master must return `identical` or `ahead`, which means `P2` is a commit of remote master. Any other shape (one parent, a rebase that rewrote `OLD`, a parent that is neither, a `P2` off master) is a head that did not move only by its base: verdict NEEDS-WORK, full QA. `/requa` covers a merge of master into the branch only. A rebase rewrites every commit of the branch, so there is no reviewed parent to anchor to, and it always goes to a full QA.

### 4. Compare the two patches

Take each merge base from the remote, not from local git:

```bash
MB_OLD=$(gh api "repos/$R/compare/$MASTER...$OLD" --jq .merge_base_commit.sha)
MB_NEW=$(gh api "repos/$R/compare/$MASTER...$NEW" --jq .merge_base_commit.sha)
python3 "$REQUA" compare --repo . "$MB_OLD" "$OLD" "$MB_NEW" "$NEW"
```

The normalization removes only what a base update changes by itself: the blob hashes on `index` lines and the line numbers in hunk headers. The function-context text after the second `@@` stays, because it names the function a hunk lands in: a merge that moves the PR's change into another function with identical surrounding lines reads as a difference (`@@ def a():` against `@@ def b():`). The cost is a false difference when master edits the line git picks as that context; that is a NEEDS-WORK and a full QA, never a silent pass. Every changed line and every context line inside a hunk must also match byte for byte, so a master edit right next to the PR's change reads as a difference too, since the reviewer never saw the patch against that context. Residual, not caught: a move WITHIN one function whose context lines and function-context text both stay the same, because the normalized patch is then identical. When the helper prints `DIFFERS` above the diff of the two normalized patches, name each difference and say where it comes from (a conflict resolved in the merge commit, a hunk that changed size, a file only one side touches). Any content difference is NEEDS-WORK and a full QA, however small it looks.

### 5. Run the integrated tree's selftests for the overlapping files

The overlap is every file the pull request changes that master also changed since `MB_OLD`:

```bash
comm -12 <(git diff --name-only "$MB_OLD..$OLD" | sort) <(git diff --name-only "$MB_OLD..$P2" | sort)
```

Check out `NEW` and run, for each overlapping file, the proof that covers it: `python3 <file> --selftest` for a script that takes the flag (a gate takes its fixture directory, as `brain_doctor.py` gate-liveness calls it), and the matching `scripts/tests/test_*.py` through the Python 3.11 suite command in the repo's CI. An empty overlap is stated as such. A failing or missing proof for an overlapping gate is NEEDS-WORK.

### 6. Poll the checks

```bash
gh pr checks "$PR" --repo "$R" --watch --interval 30
```

Every check must finish green on `NEW`. A failing check is NEEDS-WORK. A check still pending when you stop waiting is named in the report and the verdict is NEEDS-WORK.

## The report

Lead with one line per step and its evidence (the SHAs, the parents, the compare status, the `diff` result, each selftest and its exit code, the checks table). Then end with exactly these three lines, for the NEW head:

```
QA-VERDICT: PASS
QA-SCOPE: PR #<pr>
QA-HEAD: <NEW, all 40 hex digits>
```

PASS only when steps 2 to 6 all hold and step 4 printed `IDENTICAL`. Otherwise the first line is `QA-VERDICT: NEEDS-WORK`, the reason sits above it, and the pull request goes through a full QA (`skills/pre-merge-qa-gate/SKILL.md`). Never write `QA-HEAD` for `OLD` or for any head other than the one this run checked.
