ARCHITECTURE.arming-surface — residuals, each with the command that reproduces it.

Every line here was RUN against the gate, not reasoned about. A residual is a
shape that passes on purpose: either it is the sanctioned development route, or
covering it would cost more real work than the disarm it prevents. The gate's
own header carries the same list; this file carries the commands.

1. AN INTERPRETED WRITE THROUGH A SCRIPT FILE.  PASSES.
     python3 ~/.claude/scripts/merge-hooks.py
   A hook sees the Bash command, never inside the subprocess. merge-hooks.py
   legitimately rewrites the live settings.json (it is the projector
   brain_doctor asserts against), so this route cannot be closed at PreToolUse
   without breaking the projection. Any script file that opens a protected path
   passes the same way.
   Partial cover: an INLINE `-c` body is read for a protected literal next to a
   write marker.  Denied:
     python3 -c "open('~/.claude/settings.json','w').write('{}')"
   Allowed, one edit away, and it must stay allowed (a frequent real command):
     python3 -c "import json;print(json.load(open('~/.claude/settings.json')))"
   Still passing, measured: a write idiom outside _WRITE_MARKERS, a path built
   from a variable, and a `-c` body nested deeper than the shared parser's 3.
   What IS inside _WRITE_MARKERS is now proven entry by entry: 14 markers, 14
   `violation_marker_<slug>.json` bodies carrying one marker each, 14 benign
   counterparts one edit away, and each deletion of a marker measured to turn
   exactly its own fixture red. Before that, 12 of the 14 could be deleted with
   the selftest still green.
   The `-c` layer matches LITERAL path spellings, so it knows the project-scope
   pair only at the brain root (`~/.claude/.claude/settings*.json`). A deeper
   project root inside the live tree is covered for Write/Edit and shell
   mutations by the path-shape classifier, not by this literal layer.

2. `git merge` / `git pull` / `git rebase` / `git apply` IN THE LIVE TREE.  PASSES.
     git -C ~/.claude merge feat/anything
   The shared parser classifies none of these as whole-tree, and they are the
   sanctioned route by which reviewed work reaches the live tree. Denying them
   would break `ai-sync`, which is the ONLY supported way to update the brain.

3. THE SHARED PARSER'S OWN RESIDUALS, INHERITED NOT RE-SOLVED.
     rsync --delete ... ~/.claude/scripts/
     shred ~/.claude/settings.json
     ln -sf /dev/null ~/.claude/hooks.json
     perl -pi -e 's/a/b/' ~/.claude/scripts/qa-merge-gate.py
     cat list | xargs rm            (targets never appear in the command)
     rm -rf $DIR                    (variable expansion, unknowable pre-shell)
   g__pretool-bash__tree-owner.py names these in its own header. This gate
   borrows that parser rather than growing a second one, so it inherits the
   list; closing them means fixing the one parser, which fixes both gates.

4. THE OPERATOR'S TERMINAL.  PASSES, BY DESIGN.
   No hook fires there. It is the intended and only writer of the live copies,
   and it is why this rule ships with no env unlock: an unlock variable would be
   writable from the settings.json `env` block this gate exists to protect.

5. A NON-GATE FILE IN THE LIVE TREE.  PASSES, BY DESIGN.
     (Write ~/.claude/scripts/README.md)      -> allowed, pinned by
     benign_live_non_gate.json
   The deny is scoped to the arming surface, not to the directory. A live script
   that is neither a gate, a gate's runtime import, nor the prover is out of the
   set; growing the set to "every live file" is the blanket deny that makes the
   brain undevelopable.

6. A NON-Bash, NON-Write TOOL THAT WRITES A FILE.  PASSES.
   Targets are read from Write/Edit/NotebookEdit/MultiEdit and from Bash. An
   MCP tool taking a path and writing it would not be tested. Measured against
   the servers registered on this runtime (gmail, whatsapp, bonsai, repomix,
   claude-in-chrome, Google Drive/Calendar, Microsoft Learn, Cloudflare): none
   writes an arbitrary local path, so this is a gap in shape rather than reach.
   Left open deliberately: testing every tool that carries a `file_path` would
   deny a READ of settings.json through such a tool, and an over-firing gate is
   the failure mode this boundary exists to avoid. The gate is registered on the
   PreToolUse `*` matcher, so closing it later is one condition here, not a new
   registration.
   Reproduction: send any PreToolUse payload with tool_name outside
   {Write, Edit, NotebookEdit, MultiEdit, Bash} and a protected path in
   tool_input; benign_foreign_tool.json pins the current behaviour.

7. A SETTINGS SCOPE OUTSIDE THE LIVE ROOT.  PASSES.
     (Write ~/.claude.json)                      -> allowed
     (Write /etc/claude-code/managed-settings.json) -> allowed
   Three scopes, all measured 2026-09-08. Enterprise/managed policy lives
   outside $HOME and is root-owned, so the OS is the gate there. `~/.claude.json`
   is a SIBLING of the brain root, not inside it, and it carries `mcpServers`
   (a command the next session runs), which makes it the strongest uncovered
   surface left; it is deliberately not taken here because the harness rewrites
   it on every session and hand-repairing it is real work with no worktree copy
   to do it in. A project root outside the live tree (an arm's own
   `.claude/settings.json`) is that arm's business, not this gate's.
   What IS covered, and was not before: PROJECT scope inside the live root.
   `<any dir>/.claude/settings*.json` under ~/.claude is denied by path shape,
   and so is a `.claude` DIRECTORY that holds one. A `.claude` directory that
   holds no settings stays removable, measured on the live tree:
     rm -rf ~/.claude/.claude                                  -> denied
     rm -rf ~/.claude/claude-mem-ref/.claude                   -> denied
     rm -rf ~/.claude/knowledge/repo-deep-learn/ECC/.claude    -> allowed
     rm -rf ~/.claude/registry/fixtures/FLOW.budget-halt/home/.claude -> allowed
   Nothing is lost by asking: creating an empty `.claude` is allowed, and the
   FILE rule denies putting settings into it.
   which is why the two files that were reachable one directory over
   (~/.claude/.claude/settings.json and settings.local.json) and the deeper
   root the live tree actually carries (claude-mem-ref/.claude/settings.json)
   are all denied without any of them being listed.
   A worktree's `hooks.json` is NOT this surface and stays allowed (6 of 6
   measured): it is octorato's tracked source, projected into the live
   settings.json by merge-hooks.py, never loaded by the harness.

8. AN ANCESTOR-DIRECTORY DELETE OF A DEEP PROJECT ROOT.  PASSES.
     rm -rf ~/.claude/claude-mem-ref        -> allowed
     rm -rf ~/.claude/.claude               -> denied
     rm -rf ~/.claude                       -> denied
   The classifier holds paths, so a target that conflicts with one it holds is
   denied in both directions; a directory that merely CONTAINS a `.claude`
   deeper down is not one of them. Closing it means listing the live tree on
   the hot path for every rm, which is the cost this gate refuses to pay.
