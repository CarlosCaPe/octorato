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
   Partial cover, TWO channels, asking different questions on purpose.

   1a. AN INLINE `-c` BODY is read for a protected literal next to a write
   marker.  Denied:
     python3 -c "open('~/.claude/settings.json','w').write('{}')"
   Allowed, one edit away, and it must stay allowed (a frequent real command):
     python3 -c "import json;print(json.load(open('~/.claude/settings.json')))"
   Spellings that used to PASS and now deny, each with a fixture:
     python3.12 -c "..."     (the version strip left `python3.` with the dot)
     python3 -u -c "..."     (the host was read as tokens[i-1], so a flag hid it)
     python3 -I -c "..."
     sh -lc "..."            (a short-flag bundle ending in c)
     python3 -c"..."         (fused, one token to shlex)
   The `sh -lc` branch existed in the code before this and was DEAD, which is
   what a surviving mutant showed: the layer fast-outs on `"-c" not in command`
   and `sh -lc` carries no literal `-c`, so the body was never read. The
   fast-out is the bundle regex now, and the branch has a fixture.
   The host table is SEVEN, not ten. node/perl/ruby were dropped after mutation
   showed 8 of 10 surviving deletion: `node -c` is not a thing (node takes -e)
   and `perl -c` / `ruby -c` only CHECK syntax, so none could reach a write. All
   three stay covered where they are actually reachable, nested inside a shell
   host, which is what their four fixtures already use. Each of the seven that
   remain has a violation whose deny turns on that entry.

   1b. A HEREDOC BODY is read only for a protected literal that is the DIRECT
   OPERAND of a write, and only when the opening line feeds an interpreter.
   Denied:
     python3 - <<'PY'
     open('~/.claude/settings.json','w').write('{}')
     PY
     bash <<'EOF'
     echo '{}' > ~/.claude/settings.local.json
     EOF
   Allowed, one edit away:
     python3 - <<'PY'
     print(open('~/.claude/settings.json').read())
     PY
   Allowed and it MUST be, because it is what editing this repo looks like:
     python3 - <<'PY'
     open('README.md','w').write("see ~/.claude/settings.json")
     PY
   Why not the same loose test as 1a, measured rather than assumed: applying the
   marker test to heredoc bodies over 17,232 real Bash calls from this machine's
   transcripts flipped 23 commands to DENY. Two were genuine live writes. The
   other 21 were all one shape, a heredoc writing a DOCUMENT that quotes a
   protected path, which is exactly what editing this gate's header, these
   fixtures, this file and CLAUDE.md looks like. Precision 2/23 on a rule that
   ships no env unlock is a gate people route around. The narrow test measures
   2 of 3,296 real heredoc commands, down from 23, and still denies the direct
   attack. Those 2 are named rather than rounded away: each is one command
   writing a TEST HARNESS whose text carries the attack literal, which no text
   scan can separate from the attack, and both came from the adversarial lab.
   A `-c` body is a one-line ARGUMENT and a heredoc body is a DOCUMENT; that is
   the whole reason the two readers differ.

   Still passing on BOTH channels, measured: a write idiom outside
   _WRITE_MARKERS, a path built from a VARIABLE (both genuine live writes in the
   corpus were that shape), and a `-c` body nested deeper than the shared
   parser's 3.
   What IS inside _WRITE_MARKERS is proven entry by entry: 14 markers, 14
   `violation_marker_<slug>.json` bodies carrying one marker each, 14 benign
   counterparts one edit away, and each deletion of a marker measured to turn
   exactly its own fixture red. Before that, 12 of the 14 could be deleted with
   the selftest still green.
   The literal layers match path SPELLINGS, so they know the project-scope pair
   only at the brain root (`~/.claude/.claude/settings*.json`). A deeper project
   root inside the live tree is covered for Write/Edit and shell mutations by
   the path-shape classifier, not by these literal layers.

1c. A READ SPELLED AS A COPY.  DENIES, and it is an over-fire.
     python3 -c "import shutil;shutil.copy('~/.claude/settings.json','/tmp/x')"
   `shutil.copy` is a real write idiom and a literal scan cannot see which side
   of the call the needle sits on, so this reads and is denied. Kept in exchange
   for the write it catches, and named here because "reading through the same
   `-c` passes" is true of `open` and not of this one.

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

7. A SETTINGS SCOPE OUTSIDE THE LIVE ROOT.  PARTLY CLOSED.
     (Write /etc/claude-code/managed-settings.json) -> allowed
     (Write ~/Documents/github/<arm>/.claude/settings.json) -> allowed
     (Write ~/.claude.json)                      -> DENIED, no longer a residual
   `~/.claude.json` stood here as "the strongest uncovered surface left", on
   the reasoning that the harness rewrites it every session so a deny would
   leave no development path. That reasoning was wrong, and it is written down
   so it does not come back: a PreToolUse hook only ever sees the AGENT's tool
   calls, never the harness writing its own state file, so there was nothing to
   fight. It carries `mcpServers` (three entries, each with `command`, `args`,
   `env`, `type`), which makes a write there a program the next session runs at
   startup, and it is now covered by NAME, the one member of the set outside
   the live root. Measured after: Write, Edit, `sed -i`, `>` redirect, `cp`,
   `mv`, `rm` and an interpreter write all deny; `cat`, a `-c` read,
   `~/.claude.json.bak` and a worktree `.claude.json` all allow.
   What remains: enterprise/managed policy lives outside $HOME and is
   root-owned, so the OS is the gate there. A project root outside the live
   tree (an arm's own `.claude/settings.json`) is that arm's business.
   What IS covered, and was not before: PROJECT scope inside the live root.
   `<any dir>/.claude/settings*.json` under ~/.claude is denied by path shape,
   and so is a `.claude` DIRECTORY. One that holds no settings stays REMOVABLE,
   measured on the live tree (it is only writes into it that are denied):
     rm -rf ~/.claude/.claude                                  -> denied
     rm -rf ~/.claude/claude-mem-ref/.claude                   -> denied
     rm -rf ~/.claude/knowledge/repo-deep-learn/ECC/.claude    -> allowed
     rm -rf ~/.claude/registry/fixtures/FLOW.budget-halt/home/.claude -> allowed
   "HOLDS ONE" IS ONLY A QUESTION FOR A VERB THAT TAKES, and asking it of every
   verb cost a merge blocker plus a second door found while fixing it.
   This file used to say "Nothing is lost by asking: creating an empty `.claude`
   is allowed, and the FILE rule denies putting settings into it." That is FALSE
   for a directory MOVE, because the file rule only ever sees file targets and a
   move names no file. Reproduced, positive control denying first:
     Write ~/.claude/settings.json                             -> denied (control)
     Write ~/.claude/stage/settings.json  {"env":{...}}        -> allowed
     mv ~/.claude/stage ~/.claude/x/.claude                    -> allowed
   Two allowed steps, project-scope settings with a forged approval inside the
   live root. The fix was first written as "an ABSENT `.claude` is protected",
   and re-testing THAT against the real tree found the second door: an EXISTING
   EMPTY one is a drop box, so all eight of them were open.
     cp /tmp/settings.json ~/.claude/knowledge/repo-deep-learn/ECC/.claude/
   So the listing is consulted ONLY for a REMOVING verb (rm, unlink,
   find -delete, git rm); for every other verb the `.claude` directory itself is
   the target, whatever it holds today. Measured after:
     mv <anything> ~/.claude/x/.claude                         -> denied
     cp -r <anything> ~/.claude/x/.claude                      -> denied
     mv /tmp/stage ~/.claude/x/.claude                         -> denied
     mv ~/.claude/stage ~/.octorato/wt/<wt>/x/.claude          -> allowed
     cp /tmp/settings.json ~/.claude/<any>/.claude/  (empty)   -> denied
     mv ~/.claude/knowledge-ref/.claude /tmp/parked  (empty)   -> denied
     rm -rf ~/.claude/x/.claude   (absent)                     -> allowed
     rm -rf ~/.claude/knowledge/repo-deep-learn/ECC/.claude    -> allowed
     mkdir -p ~/.claude/x/.claude                              -> allowed
   `mkdir` is not a mutator and never reaches this gate, so creating one stays
   free. Cost, measured: of 17,232 real Bash calls, ONE aims mv/cp/tee/install/
   ln at a nested `.claude` under the live root, and it is a line testing this
   gate. What is newly denied that a person might do: moving an empty `.claude`
   elsewhere, which `rm -rf` still does.

   CASE, closed at the same time. All four of these were ALLOW before:
     Write ~/.claude/.Claude/settings.json
     Write ~/.claude/.claude/SETTINGS.JSON
     Write ~/.claude/Settings.local.json
     Write ~/.CLAUDE.JSON
   Not reachable on this ext4 host, but a clean bypass on Windows (where
   install-runners.py ships the .cmd thunks) and on default macOS APFS, where
   each pair is the SAME file. Every comparison is case-folded now, and the fold
   is unconditional rather than normcase, because normcase is identity on macOS.
   The Linux price is that a directory literally named `.CLAUDE` would be
   protected while arming nothing; nothing carries one.
   which is why the two files that were reachable one directory over
   (~/.claude/.claude/settings.json and settings.local.json) and the deeper
   root the live tree actually carries (claude-mem-ref/.claude/settings.json)
   are all denied without any of them being listed.
   A worktree's `hooks.json` is NOT this surface and stays allowed (6 of 6
   measured): it is octorato's tracked source, projected into the live
   settings.json by merge-hooks.py, never loaded by the harness.

8. AN ANCESTOR DIRECTORY OF A DEEP PROJECT ROOT, BOTH DIRECTIONS.  PASSES.
     rm -rf ~/.claude/claude-mem-ref        -> allowed   (takes one)
     mv /tmp/s ~/.claude/x                  -> allowed   (plants one, when
                                                          /tmp/s/.claude/
                                                          settings.json exists)
     rm -rf ~/.claude/.claude               -> denied
     rm -rf ~/.claude                       -> denied
     mv /tmp/s ~/.claude/x/.claude          -> denied    (names the shape)
   One class, one reason: the classifier tests the PATH IT IS GIVEN, and neither
   passing command gives it a `.claude`. Closing the delete means listing the
   live tree on the hot path for every rm; closing the create means walking an
   arbitrary source tree. Both are costs this gate refuses to pay, and both are
   strictly weaker than residual 1, which already concedes that anyone running a
   script file writes what they like.

9. A COMMAND OVER 64 KB CARRYING NEITHER `-c` NOR A HEREDOC.  NOT SCANNED.
     echo "<70 KB of text>"                 -> allowed
     echo -c "<70 KB of text>"              -> DENIED (oversize, `-c` channel)
     python3 - <<PY / <70 KB> / PY          -> DENIED (oversize, heredoc)
   shlex is quadratic in one long token, so the inline layers are capped rather
   than timed out: a killed hook writes no stdout and empty stdout reads as
   ALLOW, which makes a timeout the cheapest disarm available. Measured through
   the gate before the cap: 24 KB 0.19 s, 97 KB 0.79 s, 195 KB 3.13 s, 390 KB
   9.72 s. The cap costs nothing real, measured on 17,232 Bash tool calls from
   this machine: largest 32,359 bytes, p99 5,145, none over 64 KB. A command
   past the cap with no inline channel is left alone because nothing here would
   have read it; the path and tree layers still run on it.

10. WHAT FAILS CLOSED, so the list of what fails open is honest.
   A command the borrowed parser cannot READ still allows: denying on that would
   hand anyone a session-wide DoS for one unbalanced quote. A parser that cannot
   LOAD now DENIES. It used to return [] under a blanket `except`, so a missing
   receipt_ledger.py or kernel_proc.py, both inside the protected set, turned
   the Bash half into an all-ALLOW with no output at all. It has no fixture and
   cannot have one: making the load fail needs the loader repointed, and any
   payload or env that could repoint it would itself be the disarm. It is
   asserted inside `--selftest` instead, in a child process with the path
   rebound in memory, and the assertion fails if the gate allows.
   Measured at scale: with the parser one directory away from where the module
   looks for it, the previous version allowed 17,232 of 17,232 real Bash
   commands from this machine's transcripts, the 39 disarms it normally denies
   included, with no output and a zero exit. That is what "invisible" means.
