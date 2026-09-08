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
