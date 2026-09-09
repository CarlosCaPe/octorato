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
   The host table is SIX, not seven and not ten; this file said SEVEN while the
   code and the gate header said SIX, and the code is right. Four left, not
   three: node/perl/ruby went after mutation showed 8 of 10 surviving deletion
   (`node -c` is not a thing, node takes -e; `perl -c` / `ruby -c` only CHECK
   syntax, so none could reach a write), and `python3` went on a measurement,
   because `_is_c_host` strips a version suffix and it reduces to `python`,
   which is already in the table. All four stay covered where they are actually
   reachable, nested inside a shell host, which is what their fixtures use. Each
   of the six that remain has a violation whose deny turns on that entry.
   The COMMAND-level test for "is there a `-c` body at all" is a different
   regex from the token-level one and is host-anchored, after QA measured two
   costs of using the token regex on the whole string: `grep -c` over the size
   cap was denied as carrying an interpreter body, and any path containing
   `-<letters>c` shifted verdicts, so a sandbox under a directory spelled with
   one answered differently from a clean one.
   The write markers are 16, not 14: `'r+'` and `"r+"` joined after
   `open(<live settings>,'r+').truncate(0)` was measured as ALLOW. It empties
   the file and carried no marker.

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
   What IS inside _WRITE_MARKERS is proven entry by entry: 16 markers, 16
   `violation_marker_<slug>.json` bodies carrying one marker each, 14 benign
   counterparts one edit away, and each deletion of a marker measured to turn
   exactly its own fixture red. Before that, 12 of the first 14 could be deleted with
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
   The shared parser classifies none of these as whole-tree. A PULL brings the
   remote state through the reviewed path, and denying it would break `ai-sync`,
   the only supported way to update the brain. A MERGE is NOT that, and this
   file used to imply it was: `git -C ~/.claude merge <local-branch>` is allowed
   and lands UNREVIEWED local edits on every file in this set, because
   `qa-merge-gate` guards `gh pr merge` and nothing guards `git merge`. Stated
   plainly instead of rounded into "reviewed".

3. THE SHARED PARSER'S OWN RESIDUALS, INHERITED NOT RE-SOLVED.
     rsync --delete ... ~/.claude/scripts/
     ln -sf /dev/null ~/.claude/hooks.json
     perl -pi -e 's/a/b/' ~/.claude/scripts/qa-merge-gate.py
     cat list | xargs rm            (targets never appear in the command)
     rm -rf {pkg,x}                 (brace expansion, unknowable pre-shell)
     rm -rf $UNSET/pkg              (a variable NOBODY here can read; a DEFINED
                                     one now resolves, see entries 36 and 37)
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
   past the cap with no inline channel is left alone by the two INLINE READERS
   and by nothing else.
   That last sentence used to be false, and it was the merge blocker of this
   cycle. `main()` RETURNED at the cap when the command carried no `-c` and no
   heredoc, so one character of padding defeated every Bash deny:
     rm -rf ~/.claude/scripts + padding to 65,536 chars   -> denied
     rm -rf ~/.claude/scripts + padding to 65,537 chars   -> ALLOWED
     rm -rf ~/.claude/scripts (control)                   -> denied
   QA measured the same one-character bypass for `git checkout evil`, a `>`
   redirect into hooks.json, `tee` on settings and `sed -i` on a gate body, with
   a comment as the padding. An oversize command now falls THROUGH to the path
   and tree layers and only the two quadratic readers are skipped, which is what
   the cap was always about. It costs nothing in wall clock: the sibling Bash
   tree-owner gate already runs the same parser on the same command with no cap,
   and same-event hooks run in parallel.
   The channel test that decides "is this oversize command worth denying" is
   host-anchored now, so `grep -c foo file` over the cap is ALLOWED. It used to
   be denied as "carries an interpreter `-c` body".
   FALLING THROUGH NEEDS ITS OWN CEILING, because the shared parser shlexes too
   and the fall-through handed it an unbounded string. Measured, whole process:
   400 KB 14.2 s through this gate and 8.5 s through the sibling Bash tree-owner
   gate; 1 MB 67.2 s and 107.6 s. Past the harness's 60 s default a hook is
   KILLED, writes no stdout, and reads as ALLOW, which is the same failure a
   size lower down. So the PARSE is capped at 128 KB and the answer above it is
   exact rather than heuristic: the parser's own first line is
   `if not any(t in command for t in _TRIGGERS): return []`, so a command over
   the ceiling with NO trigger is allowed (that is what the parse would have
   said) and one WITH a trigger is denied (the ambiguity resolves closed). The
   trigger list is borrowed from the parser, never copied.
     rm -rf ~/.claude/scripts + 70 KB of padding    -> denied  (0.38 s)
     rm -rf ~/.claude/scripts + 300 KB of padding   -> denied  (0.21 s)
     rm -rf /tmp/x            + 300 KB of padding   -> denied  (0.13 s)
     echo "<300 KB>"                                -> allowed (0.10 s)
     echo "<1 MB>"                                  -> allowed (0.17 s)
     rm -rf /tmp/x + 127 KB (worst case PARSED)     -> allowed (1.79 s)
   THE CEILING MOVED WHEN A READER WAS ADDED, which is why it is measured and
   not picked. At 256 KB the worst case still parsed was 3.65 s; the indirection
   reader of residual 18 lexes the raw command a second time and took the same
   shape to 8.91 s. Both sit under the 60 s kill, but the loaded-machine
   timings in this file ran 3-4x the idle ones and 8.91 s idle is not a margin
   at that multiple. shlex is quadratic in one token, so halving the ceiling
   quarters the cost. Real traffic is unaffected: the largest command in the
   corpus is 32,359 bytes, still four times under the new ceiling.
   The sibling tree-owner gate has the same 1 MB exposure today. It is named
   here so the number is not read as new, and it is that gate's to fix.

10. WHAT FAILS CLOSED, so the list of what fails open is honest.
   THE GATE'S OWN FIRST IMPORT now denies too, and it was the hole the parser
   deny did not cover. `import kernel_proc` sat at module scope with nothing
   around it, so a missing or syntactically broken copy raised before `main()`
   existed: rc=1, empty stdout, which the harness reads as ALLOW. The
   `try/except` at the bottom of the file could never catch it, because the
   failure is earlier than `__main__`. `kernel_proc.py` is inside the set this
   gate protects, so the floor could be removed by removing one of the files it
   guards. Both legs are asserted in `--selftest` (module absent, module
   present and broken), in a child process holding a copy of the gate and no
   kernel_proc, which no payload can reach.
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

11. SHELL SPELLINGS THAT NEED A SHELL, NOT A TABLE.  PASS.
     rm -rf ~/.claude/{scripts,hooks.json}     (brace expansion)
     eval "rm -rf ~/.claude/scripts"
     f() { rm -rf ~/.claude/scripts; }; f      (a shell function)
     rm -rf $'\x7e/.claude/scripts'
     rm -rf ~/.claude/$(echo scripts)
     ln -s ~/.claude/settings.json /tmp/s && echo x > /tmp/s   (same command)
   Each of these produces its target only after the shell runs, and a table that
   guessed at them would be a second parser with its own drift. `$HOME` and
   `$(…)` are being closed in the SHARED parser on another branch, which is
   where they belong; this gate borrows that parser rather than racing it.

12. WRITERS THAT ARE NOT MUTATION VERBS.  NOW COVERED, listed so the count is
   honest about what changed.
     cp -t ~/.claude /tmp/settings.json                 -> denied (was allowed)
     cp --target-directory=~/.claude/scripts /tmp/x.py  -> denied (was allowed)
     mv -t ~/.claude/scripts /tmp/x.py                  -> denied
     cp -r /stage/.claude ~/.claude/knowledge-ref/      -> denied (was allowed)
     mv    /stage/.claude ~/.claude/knowledge-ref/      -> denied (was allowed)
     install -t ~/.claude/scripts /tmp/x.py             -> denied (was allowed)
     ln -f /tmp/x.py ~/.claude/scripts/qa-merge-gate.py -> denied (was allowed)
     rsync -a /tmp/src/ ~/.claude/scripts/              -> denied (was allowed)
     curl -o ~/.claude/settings.json https://x          -> denied (was allowed)
     wget -O ~/.claude/settings.json https://x          -> denied (was allowed)
     tar -x -C ~/.claude -f /tmp/a.tar                  -> denied (was allowed)
     tar -t -C ~/.claude -f /tmp/a.tar                  -> allowed (lists only)
     patch -o ~/.claude/settings.json /tmp/a.diff       -> denied (was allowed)
     gawk -i inplace '{print}' ~/.claude/scripts/qa-merge-gate.py -> denied
     gawk '{print}' ~/.claude/scripts/qa-merge-gate.py  -> allowed
     echo x >| ~/.claude/settings.json                  -> denied (was allowed)
     echo x &> ~/.claude/hooks.json                     -> denied (was allowed)
     cp -r /tmp/stage/docs ~/.claude/knowledge-ref/     -> allowed (control)
   `-t` INVERTS the argument order, so the shared parser's `positional[-1:]`
   was handing back the SOURCE; QA has a real bash receipt of the file landing
   in the live tree. A directory destination receives the source's BASENAME,
   which is `os.path.join(dest, basename(src))` and not, as the old residual
   claimed, "walking an arbitrary source tree". Cost, replayed over 18,154
   distinct real Bash calls from this machine's transcripts: ONE flip, and it is
   a `cp` whose destination was an unexpanded `$SB` inside
   registry/fixtures/, denied because that directory is now in the set.

13. `find` WITH AN `-exec` THAT PUTS.  NOW COVERED.
     find ~/.claude/<any>/.claude -maxdepth 0 -exec cp /tmp/settings.json {} +
   The shared parser labels every find it reports `find -delete`, but it also
   fires on `-exec <mutator>`, and a mutator can PUT as easily as take. The
   label was read as "removing", the empty listing answered "nothing to take",
   and the settings landed in the drop box (QA has the receipt). The label is
   re-derived from what the command carries: an `-exec` program outside
   {rm, unlink, shred} means this find is not a removal.
     find ~/.claude/knowledge-ref/.claude -maxdepth 0 -delete -> allowed (empty)
     find ~/.claude/.claude -maxdepth 0 -delete               -> denied

14. THE SET GAINED THREE MEMBERS, each an arming surface by the same criterion.
     (Write ~/.claude/.git/config)                  -> denied (was allowed)
     git -C ~/.claude config core.hooksPath /tmp/x  -> denied (was allowed)
     git -C ~/.claude config --unset core.hooksPath -> denied
     git -C ~/.claude config core.hooksPath         -> allowed (a READ)
     git -C ~/.claude config --get core.hooksPath   -> allowed (a READ)
     git -C ~/.claude push --no-verify              -> denied (was allowed)
     git -C ~/.claude push                          -> allowed
     (Write ~/.claude/registry/fixtures/<rule>/violation_x.json) -> denied
     (Edit  ~/.claude/scripts/merge-hooks.py)       -> denied (was allowed)
   `core.hooksPath=.githooks` is what the live tree really carries, so that one
   key names the directory .githooks/pre-push runs from. A violation fixture
   edited to stop violating leaves gate-liveness green while the gate guards
   nothing. merge-hooks.py is the sanctioned writer of settings.json, which is
   an argument for protecting the program, not for leaving it writable. The
   READ shapes stay allowed on a measurement: the version that treated one
   positional as a set denied two real commands, both reading `core.hooksPath`
   to check it is still `.githooks`.

15. THE HEREDOC READER, WIDENED, AND WHAT IT COST.
   The host no longer has to precede the `<<` on the same line, and node/perl/
   ruby/deno/bun/php are hosts, because they were not and that made the
   `writeFileSync` and `os.replace`/`shutil` entries of the pattern table
   UNREACHABLE from a heredoc: dead entries no fixture could exercise, which is
   the same class this gate killed in the host table one commit earlier.
     cat <<'PY' | python3 / open('~/.claude/settings.json','w') / PY -> denied
     node - <<JS / writeFileSync('~/.claude/settings.json','x') / JS -> denied
     python3 - <<PY / os.replace('/tmp/x','~/.claude/settings.json') / PY -> denied
     python3 - <<PY / os.replace('~/.claude/settings.json','/tmp/x') / PY -> allowed
   The host is looked for in the SHELL half of the command only, never inside a
   body. That distinction is not theory: with the host read out of the whole
   string, `cat > README-residuals.txt <<'EOF' … EOF` denied, because THIS FILE
   quotes `open('~/.claude/settings.json','w')` as an example. The gate was
   denying its own documentation.
   Idioms added, each measured as ALLOW before:
     open(os.path.expanduser('~/.claude/settings.json'),'w')
     Path('~/.claude/settings.json').expanduser().write_text(...)
     open(f'~/.claude/settings.json','w')          (an f-string literal)
     open('~/.claude/settings.json', mode='w')     (mode as a keyword)
     open('~/.claude/settings.json','r+').truncate(0)
   AN UNTERMINATED OPENER RUNS TO END OF INPUT, which is what bash does. The
   previous version skipped it, on the reasoning that a `<<` in prose cannot
   swallow the rest of the command; bash warns and runs the body anyway, so
   omitting the terminator was a one-line way to hide a body from this reader
   while still executing it.
   Cost, replayed over 18,154 distinct real Bash calls (3,816 carrying a
   heredoc): the reader fires on 10, up from 6. All four new ones are commands
   from the adversarial lab of this cycle, writing a probe script or a fixture
   generator whose TEXT carries the attack literal. That is the residual class
   already named above, now with a number.

16. NEEDLES: EVERY PROTECTED FILE, and a path spelled with `/./`.
     python3 -c "open('~/.claude/scripts/qa-merge-gate.py','w')"  -> denied
     python3 -c "open('~/.claude/scripts/brain_doctor.py','w')"   -> denied
     python3 -c "open('~/.claude/./settings.json','w').write('x')" -> denied
     python3 -c "print(open('~/.claude/scripts/qa-merge-gate.py').read())" -> allowed
   The literal layers used to build their needle list from `_EXACT` plus the
   project-scope pair, which left every GATE BODY out: the file set protected
   them and the two inline channels did not know their names. Both layers now
   read the same concrete list the glob test already used, so a gate script
   added to the live tree is a needle the moment it exists. Bodies are
   normalized for `/./` and `//` before any needle is looked for.

17. MultiEdit's `edits` LIST. Covered, and now pinned.
   Targets were already read from `edits[].file_path`; nothing measured it, so
   the branch could be deleted with the selftest green (QA's surviving mutant
   M32). `violation_multiedit_edits_settings.json` puts the live path ONLY
   inside `edits`, with the top-level `file_path` in a worktree, and its benign
   twin puts both in the worktree.

18. A REMOVAL THAT REACHES ITS PATHS THROUGH ANOTHER PROGRAM.
   Read the first two rows together; they name the bug better than any
   description of it. Measured against the LIVE brain as cwd, with
   `rm -rf ~/.claude/scripts` denying as the positive control and
   `ls ~/.claude` allowing as the benign one:
     find ~/.claude/scripts -name '*.py' -exec rm {} \;      was ALLOWED
     find ~/.claude/scripts -name '*.py' -exec rm {} ;        was denied
   The escaped `;` is the form that RUNS in a shell; a bare one is a syntax
   error there. So the gate denied the spelling that cannot execute and allowed
   the spelling everyone types.
   MECHANISM, isolated rather than guessed, and it is not the terminator: the
   shared splitter cuts sub-commands on `;` without honouring the backslash, so
   the segment it returns ENDS IN A LONE BACKSLASH; shlex raises on the dangling
   escape; the parser falls back to a whitespace split; and a whitespace split
   KEEPS THE QUOTES, so `-name '*.py'` yields the pattern `'*.py'` with its
   literal quotes and the glob becomes `~/.claude/scripts/*'*.py'`, which
   matches no file that exists. The `-exec rm` was recognised and the root was
   right; the deny was lost to a corrupted PATTERN. That generalises past find:
   any segment whose lex fails yields quoted tokens, and every path or glob
   derived from it is wrong.
   Both halves live in files this branch does not own, so the reader added here
   does not depend on either: it lexes the RAW command, where the escape is
   ordinary and shlex reads it correctly.
   The other direction of the same tuple was open too. The earlier fix covered
   the label OVER-claiming (a non-deleter wearing `find -delete`, residual 13)
   and left it UNDER-claiming: a real deleter with no `-delete` on the line.
   Now denied, each with a fixture pair whose benign twin is ONE edit away (the
   live root becomes the worktree root, or the removing program becomes a
   reading one):
     find ~/.claude/scripts -name '*.py' -exec rm {} \;      escaped
     find ~/.claude/scripts -name '*.py' -exec rm {} ;        bare
     find ~/.claude/scripts -type f -exec rm {} +             plus
     find ~/.claude/scripts -name '*.py' -execdir rm {} \;
     find ~/.claude/scripts -name '*.py' -ok rm {} \;        -ok was in no table
     find ~/.claude/scripts -name '*.py' -exec unlink {} \;
     find ~/.claude/scripts -name '*.py' -exec shred {} \;
     find ~/.claude/scripts -name '*.py' | xargs rm
     find ~/.claude/scripts -name '*.py' -print0 | xargs -0 rm
     find ~/.claude/scripts -name '*.py' | xargs -n1 rm
     find ~/.claude/scripts -name '*.py' | xargs -I{} rm {}
     find ~/.claude/scripts -name '*.py' | xargs shred
     find ~/.claude/scripts -name '*.py' | parallel rm
     ls ~/.claude/scripts/*.py | xargs rm
     echo ~/.claude/settings.json | xargs rm
   Still allowed, and each is a control in the fixture set:
     find ~/.claude/scripts -name '*.py'                      lists only
     find ~/.claude/scripts -name '*.py' | wc -l
     find ~/.claude/scripts -name '*.py' -exec grep x {} ;
     find <worktree>/scripts -name '*.py' -exec rm {} \;
     find <worktree>/scripts -name '*.py' | xargs rm
     cat /tmp/list | xargs rm                                 paths not present
   ONE LIST OF WHAT REMOVES. There were two, this file's `_REMOVING_VERBS` and a
   second literal tuple inside the find-label check, and they disagreed: `shred`
   was in one and not the other. `_REMOVING_PROGRAMS` is now the only literal
   list of program names and the verb labels are derived from it, which the
   mutation anchor proves: deleting `shred` from that one place turns both the
   `find -exec shred` fixture and the `xargs shred` fixture red.
   THE HIT CARRIES THE PROGRAM AS ITS VERB (`rm`, not `find -delete`), which is
   what keeps the per-verb `.claude` rule of residual 7 intact: an empty drop-box
   directory stays deletable and a find that PUTS keeps being judged as a put.
   The `find -exec cp` row of residual 13 was re-run and still denies.

19. WRAPPER PREFIXES, and a BUNDLED `-c`.
   Measured live against `rm -rf ~/.claude/scripts`, all ALLOWED before:
     setsid, setsid -w, flock /tmp/l, ionice -c2, chrt -f 1, taskset -c 0,
     doas, busybox, parallel, and `bash -ec 'rm ...'` / `sh -lc 'rm ...'`
   Already denied and re-checked: sh -c, bash -c, env, nice, timeout, sudo.
   The wrapper rows are ADDED to the shared parser's `_WRAPPERS` with
   `setdefault`, not copied into a second table here: when the shared table
   grows its own row (it already has for busybox on another branch) the parser's
   row wins and this one is a no-op, so the two cannot drift. A wrong spec costs
   a MISS, never a false deny, because peeling too little leaves the wrapper
   name as the program and peeling too much leaves a path, and neither is a
   mutation verb.
   `bash -ec` is the same blind spot this gate already fixed for its own `-c`
   fast-out (the shared parser recurses on a LITERAL `-c` token and a bundle
   carries none), so it reuses that reader rather than growing a second one.

20. THE INDIRECTION FAMILY, ENUMERATED. What is still open, measured, so that no
   member of it is unnamed:
     eval 'rm -rf ~/.claude/scripts'                  the body is a string until
     echo `rm -rf ~/.claude/scripts`                  the shell runs
     echo $(rm -rf ~/.claude/scripts)                 (being closed in the
     rm -rf ~/.claude/{scripts,hooks.json}             SHARED parser elsewhere)
     D=~/.claude/scripts; rm -rf $D
     find ... -exec sh -c 'rm "$1"' _ {} +            two levels deep: the -exec
                                                     program is a shell
     find ... -exec dd of={} if=/dev/null +           `dd` is not in the shared
                                                     `_EXEC_MUTATORS`
     xargs -a /tmp/list rm                            targets live in a FILE
     cat /tmp/list | xargs rm
     taskset 0x3 rm -rf ~/.claude/scripts             the bare-mask form
     perl -pi -e ... ~/.claude/scripts/...            the shared parser's own
                                                      named residual
   `shred` USED TO BE LISTED HERE AND IN THE COVERAGE BLOCK AT THE SAME TIME,
   stating both verdicts for the same command. It was in `_REMOVING_PROGRAMS`,
   which the block read, and nothing DISPATCHED it: the shared parser's
   `_TRIGGERS` has no `shred` so `scan` fast-outs, and no local reader named it.
   A verb PRESENT in the block passed silently, which is the block's own
   sentence false in the dangerous direction. It now has a dispatch row and a
   probe, and `_assert_covered_verbs_deny` runs that probe on every claimed
   writer, so the next one cannot be claimed without being measured.
   Each open member is either an evaluator (needs a shell, not a table) or a row
   that belongs in the shared parser rather than in a second list here.

21. A CORRECTION TO RESIDUAL 14: registry/fixtures is protected FROM A WRITE.
   The cost of putting `registry/fixtures` in the set was reported here as ONE
   real command. That number came from a replay that exercised the put, redirect
   and git-config layers only, so it never saw the route the real commands use.
   Replayed properly over 18,154 distinct Bash calls from this machine, it was
   ELEVEN, and all eleven were this brain's own fixture maintenance:
     cd ~/.claude && git checkout -- registry/fixtures/<rule>/home/
     cd ~/.claude && git checkout -- registry/fixtures/<rule>/home/*.db
     rm -rf ~/.claude/registry/fixtures/<rule>/home/
     cp -r home/. "$SB"/   (run from inside a fixture directory)
   A gate that blocks its own maintenance is the failure this boundary exists to
   avoid, so the entry is narrowed to what the threat actually needs: NEW
   CONTENT. A `git checkout --` restore puts back the committed bytes, which are
   the ones review approved, and a removal makes `--selftest` fail loudly ("did
   NOT block", "fixture dir missing") rather than silently. Both pass now:
     git -C ~/.claude checkout -- registry/fixtures/<rule>/violation_x.json  allowed
     rm -rf ~/.claude/registry/fixtures/<rule>/home                          allowed
     sed -i s/a/b/ ~/.claude/registry/fixtures/<rule>/violation_x.json       denied
     echo x > ~/.claude/registry/fixtures/<rule>/violation_x.json            denied
     (Write ~/.claude/registry/fixtures/<rule>/violation_x.json)             denied
   Measured cost after the narrowing: THREE flips in the same corpus, down from
   eleven, and each one is named rather than rounded to zero:
     cd ~/.claude/registry/fixtures/<rule> && python3 - <<PY ... PY   denied,
       and correctly: that command WRITES fixture files in the live tree, which
       is the whole rule. The development path is the same one every other deny
       here points at, a worktree.
     mv ~/.claude/registry/fixtures/tmp/x.json /tmp/rescued/            an
       over-fire. The move only TAKES the file away, but the shared parser
       reports both ends of a move under the single verb `mv`, so the source and
       the destination cannot be told apart at this layer.
     cd ~/.claude/registry/fixtures/<rule> && cp -r home/. "$SB"/       an
       over-fire from the variable residual: `$SB` is unexpanded, so the
       destination resolves back inside the fixtures directory.
   AN EARLIER "ZERO" WAS A HARNESS BUG, and it is written down because the
   number looked like evidence. The replay called `hit(target, removing=...)`
   without the `verb` argument the narrowing reads, so `_fixture_write("")`
   answered True for every command and the replay measured the UNNARROWED code
   path: it reported ELEVEN flips against a gate that no longer produced them.
   A replay only measures the layers it calls with the arguments the gate uses;
   this one reached the right function through the wrong signature.
   Residual, named rather than implied: `git checkout <other-branch> --
   <fixture>` restores from a ref that is not this branch's committed state and
   is allowed. Reading the ref out of the command is the shared parser's job.
   METHOD NOTE, because the wrong number is the lesson: a replay only measures
   the layers it calls. The first one called three of them and was reported as
   if it had measured the gate.

22. HOW THE ANCHORS ARE JUDGED, because a verdict is not a mechanism.
   Three mechanisms answer an oversize command and they sit in ONE code path:
   the interpreter-channel deny, the fall-through to the path and tree layers,
   and the parse ceiling. A test that only asks "did it deny?" cannot tell which
   of them answered, so a half-reverted fix keeps passing. Measured, by printing
   the deny each one produces:
     rm -rf ~/.claude/scripts + 70 KB   -> denied by the PATH LAYER
     python3 -c "<70 KB>"               -> denied by the OVERSIZE CHANNEL
     rm -rf /tmp/x + 300 KB             -> denied by the PARSE CEILING
     echo "<300 KB>"                    -> allowed (no trigger over the ceiling)
   Each fixture's `expect_names` pins the wording of ITS mechanism, and the
   reverted-fix harness requires the failing set to equal EXACTLY the fixtures
   that name the reverted mechanism, with the other two carried in the same run
   as controls that must stay green.
   That requirement caught two things a pass/fail harness had hidden:
     - the F1a reversion (the fall-through) was written as an early `return`
       that also skipped the parse ceiling, so it reverted TWO mechanisms and
       turned the ceiling's fixture red as well. It now returns AFTER the
       ceiling, and reverts only the fall-through.
     - `violation_mv_target_directory.json` never went red when the `-t` reader
       was reverted. `mv -t` was not broken: the shared parser returns EVERY
       positional for `mv`, so the destination was already among them. The
       fixture stays as a control on that behaviour; it is not evidence for the
       `-t` fix, and the header no longer claims it is.

23. THE WORST CASE IS TOKEN COUNT, NOT BYTE COUNT, and the number in this file
   was the cheap shape. Both commands a few bytes under the 128 KB cap, both
   ending in the same protected path, measured through main():
     rm -f <one 131 KB word> ~/.claude/settings.json        1.8 s
     rm -f <65,512 short tokens> ~/.claude/settings.json    18.5 s
   The header quoted the first as "the worst case still PARSED". QA measured the
   second x8 concurrent on a loaded box at 38.8-50.9 s against the harness's
   60 s default; a killed hook writes empty stdout and empty stdout is ALLOW, so
   the command that gets killed is a real disarm.
   The cause is not shlex, which is why no byte cap could fix it. Profiled:
   65,512 passes through hit -> classify -> realpath, one per target, plus
   131,023 calls to `brain_root()`, 65,511 to `scripts_dir()` and 982,672
   `os.path.join`s rebuilding the `_EXACT` table, none of which depend on the
   target. 25.7 M function calls, 98 s under cProfile.
   Two fixes on the two axes that were growing: the invariants are resolved once
   per process, and `_MAX_TARGETS` (512) bounds DISTINCT targets with `hit`
   memoised so repeats are free. Overflow DENIES, same reason as the parse
   ceiling. Measured after, best of five through main():
     65,512 identical short tokens        2.42 s   (was 18.5 s)
     18,717 distinct short tokens         2.15 s
     511 distinct DEEP paths              0.59 s   worst shape still PROCESSED
     511 distinct shallow paths           0.37 s
     ls -la                               0.14 s
     rm on a protected path               0.23 s
   512 is measured, not picked: over the corpus the largest real command names
   20 distinct targets, p99.9 is 12, the median is 1. The budget is 25x the
   largest thing this machine has run.
     rm -f <600 distinct junk targets>                  -> denied
     rm -f <600 distinct junk> ~/.claude/settings.json  -> denied
     rm -f <400 distinct junk targets>                  -> allowed
     rm -f <900 REPEATED targets> /tmp/other            -> allowed (repeats free)
   WHAT NO FIXTURE CAN SEE: the `hit` memo changes cost, never a verdict,
   because the budget already counts DISTINCT targets. An anchor for it was
   written and then REMOVED rather than left passing on another mechanism's
   behalf; it is verified by the timing above instead.

24. THE CAP VALUES ARE PINNED NOW, both of them. Reverting `_MAX_PARSED` from
   128 KB to 256 KB used to leave the whole suite green: the number claim 23
   rests on had zero coverage, which is the same finding QA made on a sibling
   PR's cap.
     rm -rf /tmp/x + 200 KB of padding  -> denied ONLY because the ceiling
       refuses to parse it; raise the ceiling and it is parsed, found harmless
       and ALLOWED. That is violation_parse_ceiling_value.json.
     rm -rf /tmp/x + 100 KB of padding  -> allowed, the benign side of the pair.
   `_MAX_TARGETS` is pinned from BOTH sides: raising it to 65,536 turns the two
   flood fixtures red, lowering it to 128 turns the under-budget fixture red.
   `_MAX_SCANNED` (64 KB) was already pinned by violation_oversize_interp.json.

25. THE PUSH DISARM WAS ONE FLAG WIDE AND THE CLAIM WAS THE WHOLE SURFACE.
   `push --no-verify` was denied; every other route to skipping
   .githooks/pre-push was ALLOWED while the header said the surface was covered:
     git -C ~/.claude -c core.hooksPath=/dev/null push origin HEAD
     git -C ~/.claude -ccore.hooksPath=/tmp/none push                (fused)
     GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath \
       GIT_CONFIG_VALUE_0=/tmp git -C ~/.claude push
     GIT_CONFIG_PARAMETERS="'core.hooksPath=/tmp'" git -C ~/.claude push
     GIT_DIR=~/.claude/.git git push --no-verify
     chmod -x ~/.claude/.githooks/pre-push
   All six deny now. `chmod 000` and `chmod a-x` were ALREADY denied (their mode
   is a positional, so the shared parser sees it); `chmod -x` and `chmod -R -x`
   are what the local reader adds, and the fixtures are split accordingly so
   each proves the mechanism it names.
   Still allowed and named: an unrelated `GIT_CONFIG_COUNT` push, a plain push,
   and any of these aimed at a worktree.
   A branch that denied on the bare presence of `GIT_CONFIG_COUNT` was written
   and REMOVED: it was redundant with the per-key scan and its only distinct
   effect was a false deny. A reverted-fix anchor surfaced it by refusing to
   turn any fixture red.

26. SIX DIRECT WRITERS AND REMOVERS THAT WERE IN NO LIST. The polarity first,
   because it is the point: this gate has NO ALLOW-LIST. It is a DENY-LIST of
   recognised verbs, so anything unrecognised passes SILENTLY, and the residual
   list is the only thing between a reader and a false sense of coverage. These
   exist on this machine and were ALLOWED against a live protected file:
     gzip ~/.claude/settings.json                      deletes its input
     bzip2 / xz / lzma ~/.claude/settings.json         the same, no flag needed
     zstd --rm ~/.claude/settings.json                 the same, opt-in
     tar --remove-files -cf /tmp/x.tar <file>          the same, opt-in
     zip -qm /tmp/x.zip <file>                         the same, opt-in
     sort -o <file> /tmp/evil                          writes its target
     uniq /tmp/evil <file>                             writes its second operand
   The compressors are the sharp ones: no flag at all, and the command reads as
   housekeeping. Each has a benign twin one edit away that still allows
   (`gzip -k`, `gzip -c`, `zstd` without `--rm`, `tar` without `--remove-files`,
   `zip` without `-m`, `sort` with no `-o`, `uniq` with one operand).

27. THREE SMALLER ONES.
     python3 -c "open('~/.claude/scripts/../settings.json','w')"   was ALLOWED.
       `_normalize_paths` folded `/./` and `//` and not `/../`, so this was a
       clean literal bypass with no variable and no unusual idiom, which put it
       OUTSIDE the stated variable-expansion residual. The up-level fold now
       runs to a fixed point.
     git -C ~/.claude checkout with a bare dash was ALLOWED while the `@{-1}`
       spelling denied, and they are the same whole-tree rewrite.
     strace -f rm, ltrace rm, systemd-run --wait rm, flock -c 'rm ...' and
       script -c 'rm ...' were ALLOWED. The first three are wrapper rows; the
       last two hand a shell COMMAND LINE to `-c` and are read separately,
       because `_host_of` walks back to the first non-flag token and flock puts
       its LOCK FILE there, so the host it finds is a path.

28. THE CORPUS FIGURES ARE DATED, not timeless. Measured 2026-09-08: 19,171
   Bash calls, 18,154 distinct, largest 32,359 bytes, p99 5,145. QA recounted
   recursively on 2026-09-09 and got 20,714 / 19,562 / 33,098 / 5,817, higher
   and directionally consistent with a corpus that keeps growing. The
   load-bearing part is unchanged: the largest real command is 33,098 bytes
   against a 128 KB ceiling, and the largest names 20 distinct targets against a
   512 budget.

29. WHAT IS COVERED IS DERIVED; WHAT IS NOT IS ITS COMPLEMENT.
   This gate is a DENY-LIST, so the honest statement is not "here are the
   residuals" (a list that has been wrong two cycles running: six missing
   compressors, then twelve more writers and editors) but "here is every verb
   the gate recognises, generated from the dispatch tables, and ANYTHING ABSENT
   FROM IT PASSES SILENTLY".
   The block below is generated by `g__pretool__arming-surface.py --verbs` and
   `--selftest` asserts it still equals the tables, so adding a row without
   regenerating turns the suite red. The list is a mechanism now, not a claim.
   Twelve members joined this cycle, seven named by QA and three found by
   probing the same class (`chown`, `chgrp`, `split`), which is the point of the
   row shape: the twelfth cost a line instead of a function.
     fallocate -z -l 4096 <settings>            zeroes content in place
     ex -sc wq / ed -s / vim -c wq <settings>   scripted editor rewrite
     openssl enc -out <settings>                writes its -out
     gpg -o <settings>                          writes its -o
     unzip -o evil.zip -d <scripts>             overwrites gate bodies
     cpio -id -D <claude dir>                   the same, other archiver
     setfacl -m u:nobody:0 <pre-push>           the chmod class
     chown / chgrp <pre-push>                   the same class
     split -b1 /tmp/e <scripts>/qa-merge-gate.py  writes its output prefix
   Each has a benign twin one edit away that still allows: an INTERACTIVE
   `vim <file>` (only a scripted editor counts, deliberately), `openssl` with
   the protected path as `-in`, `gpg -o /tmp/x`, `unzip -d /tmp/out`,
   `split` writing into /tmp, and every one of them aimed at a worktree.

30. THE BRANCH EXEMPTION DENIED THE COMMAND THE OPERATOR TYPES EVERY DAY.
     git checkout -b feat/x                ALLOW  (correct)
     git checkout -b feat/x 2>&1           DENY   (over-fire)
     git checkout -b feat/x >/tmp/l        DENY   (over-fire)
     git switch -c feat/x 2>&1 | tail      DENY   (over-fire)
   `branch_creation_only` lexed the WHOLE command and counted `2>&1`, a pipe
   token and anything after `&&` as positionals, read the count as a start point
   and refused the exemption. The corpus carries seven real instances of this
   shape on the live tree.
   It is the SAME `2>&1`-is-not-a-positional bug found and fixed in
   `extra_git_hits` one cycle earlier and not carried across: one member of the
   class closed, the other left open. Positionals are now counted over the
   checkout/switch STAGE with `redirect_targets` applied first.
   WHY 189 ALLOWS COULD NOT SEE IT: every benign branch-creation fixture used a
   BARE command (`checkout -b feat/x`, `-qb feat/x`, `-B tmp`, `-b tmp -q`,
   `switch -c feat/x`). Not one carried a redirect, a pipe or a trailing token,
   so the benign control avoided the exact shape that broke the mechanism. That
   is the house rule inverted: a benign fixture derived from its violation by
   ONE edit would have carried the redirect, because the violation does. The new
   pairs differ by the start point alone and keep the redirect on both sides.
     git -C <live> checkout -b tmp 2>&1              -> allowed
     git -C <live> checkout -b tmp evil 2>&1        -> denied
     git -C <live> switch -c tmp 2>&1 | tail -1     -> allowed
     git -C <live> switch -c tmp evil 2>&1 | tail   -> denied
     cd <live> && git switch -c tmp 2>&1 && git push -u origin tmp -> allowed

31. COST, LABELLED. A best-of-five single run and a figure taken under
   concurrency differ by about 4x, and the header used to quote only the first.
   Left column alone, right two with eight of the same command at once on a box
   idling near load 20 on 4 cores:
     shape                            best5     x8 worst   x8 mean   verdict
     65,512 identical short tokens     1.99 s     8.85 s    7.50 s    deny
     distinct short tokens             1.45 s     5.56 s    4.20 s    deny
     511 distinct DEEP paths           0.47 s     1.86 s    1.51 s    deny
     131 KB grep, fully parsed         1.11 s     4.30 s    3.81 s    ALLOW
     131 KB echo, no trigger           1.08 s     4.22 s    3.34 s    ALLOW
     over the parse ceiling            0.25 s     1.06 s    0.74 s    deny
     ls -la                            0.12 s     0.67 s    0.50 s    ALLOW
   The worst measured anything is 8.85 s against a 60 s kill, so no input here
   reaches the kill-to-allow window.

32. THE DERIVATION WAS NOT DERIVED, and the block over-reported.
   `covered_verbs()` was a dict literal naming the tables I remembered, and
   three of its entries were LITERALS MIRRORING `if base == ...` conditions in
   code. QA proved it: adding `elif base == "7z"` to `_archive_removes` left
   `--verbs` reporting the block UNCHANGED. A derivation that reads a hand-kept
   list of lists is the same hole one level up.
   Worse, it over-reported, which is the dangerous direction. The block said
   `removing: rm shred unlink` while:
     shred -u ~/.claude/settings.json    ALLOWED
     shred ~/.claude/settings.json       ALLOWED
     unlink ~/.claude/settings.json      denied
   `shred` sat in `_REMOVING_PROGRAMS`, which the block read, and NOTHING
   dispatched it (the shared parser's `_TRIGGERS` has no `shred`, so `scan`
   fast-outs, and no local reader named it). A verb PRESENT in the block passed
   silently, and this file stated both verdicts for the same command.
   TWO ASSERTIONS NOW HOLD IT DOWN, one per direction, and neither is a list:
     _assert_no_undeclared_dispatch parses THIS MODULE'S SOURCE and collects
       every string compared against `base` or `sub_cmd`; each must appear in
       the block. QA's `elif base == "7z"` mutant turns it red.
     _assert_covered_verbs_deny RUNS every claimed writer through the real gate
       against a protected path in a sandbox and requires a deny. A writer with
       no probe is REPORTED, not skipped. Removing shred's dispatch row turns it
       red naming shred and the exact command.
   A THIRD hand-kept list was gating the reader itself: `_PUT_TRIGGERS` decided
   whether `extra_put_hits` ran at all, so a row could be covered by the block,
   pass the assertion, and never reach its reader (QA proved it with a `foo`
   row). It is derived from the tables it dispatches now.
   AND THE DERIVATION FAILED SILENT: `covered_verbs` wrapped the parser read in
   `except Exception: pass`, so a broken checkout printed a SHORTER block, exit
   0, and the assertion accepted it. It raises now, and `--verbs` exits 2.
   THE CLAIM IS NARROWED TO WHAT THE MECHANISM SUPPORTS. The block enumerates
   PROGRAM NAMES; the gate recognises more than program names. What it cannot
   enumerate is printed inside the block itself: git subcommands, find
   predicates, redirect spellings, the inline write markers, the protected path
   shapes, and the version-suffixed interpreter spellings.

33. THE GATE WAS DENYING ITS OWN DOCUMENTATION.
   A sweep of 21,653 real tool_use rows found 78 denies, and about 25 were this:
     cat > /tmp/notes.txt <<EOF
     rm ~/.claude/settings.json
     EOF
   The borrowed scan splits on newlines and reads each heredoc BODY line as a
   sub-command, so writing a DOCUMENT that quotes a dangerous command denied. I
   hit it appending sections 23 and 26 to this file; the previous QA hit it
   writing its matrices. The header claimed this class was fixed and only the
   HOST half was (which body counts as a program), never the half that hands
   bodies to the shell parser. By this file's own doctrine that is the failure
   that gets a gate turned off, and it was firing on the people writing the gate
   down.
   Every path layer sees the SHELL half only now. Bodies still reach
   heredoc_write, whose narrow test covers the redirect case the shell parser
   used to catch by accident, and a heredoc body that really redirects into
   settings.json still denies.
   SIX MORE false denies were the mirror of a bypass: a cd into an unexpanded
   path followed by a checkout denied, because the unexpanded path resolves under
   the live root and enclosing_worktree_root CLIMBS OUT of its non-existent
   components back to ~/.claude, while the same variable used absolutely
   (rm -rf "$HOME/.claude/scripts") allowed. $VAR was unknowable for a deny and
   a literal directory for an over-fire. One reading now: a resolved path still
   carrying $ or a backtick is not a hit, and a cd into one makes the TREE layer
   abstain unless a literal -C names the repo. This closes nothing that was
   open, since the bypass direction already allowed.

34. ELEVEN MORE WRITERS, and a reversal.
     shred <settings>                        was in the block and dispatched by
                                             nothing (section 32)
     rsync --remove-source-files <scripts>/  program in a table, flag unread
     scp /tmp/evil <settings>                local scp is a copy
     rename.ul a b <settings>
     git am / cherry-pick / revert           apply was named, these were not
     cd ~/.claude && tar xf                  the destination is the CWD, and
     cd <scripts> && unzip -o                only the explicit -C / -d / -D
     cd ~/.claude && cpio -id                form was read
     cd ~/.claude && patch -p0
     ed <settings> < script.ed               the script arrives on STDIN
     sed -n w <settings>                     sed's own write command
     awk print-redirect into <settings>
     node -e writeFileSync into <settings>
   The last three are PROGRAM ARGUMENTS, a third kind of inline body after the
   -c and the heredoc, read with the SAME narrow direct-write test rather than
   a new one (plus one pattern for sed's w, which carries no redirect and no
   open call).
   THE REVERSAL: editors are always writers now. The opt-in ("only a SCRIPTED
   editor counts, an interactive session is not a hook's business") left the
   stdin form open, and its reasoning was weak on its own terms: a PreToolUse
   hook only ever sees an AGENT's tool call, never the operator's terminal, so
   there is no interactive session here to protect, exactly as with
   ~/.claude.json. benign_write_vim_interactive.json became a violation.

35. COST, THE THIRD AXIS. QA found a shape absent from the table: 64 KB of
   find-delete SEGMENTS, 2,427 of them, at 4.94 s best-of-five and 13.55 s at
   x8. Neither byte cap nor the target budget could see it, because the segments
   share ONE glob string (so the budget deduped them to a single target) while
   the cost stayed per HIT, and every hit walked all the protected pairs.
   THE PAIR COUNT IS A LIVE QUANTITY: 31 on this tree today, and it grows with
   every gate script added under scripts/, so the shape gets more expensive on
   its own over time. glob_hit is memoised on (pattern, icase) now: 1.44 s
   best-of-five and 4.39 s at x8.
   The full labelled table lives in the gate header. Worst measured anything is
   8.85 s against a 60 s kill.

36. $HOME WAS UNKNOWABLE AND `~` WAS NOT, SO ONE PATH HAD TWO ANSWERS.
   Entry 33 gave an unexpanded `$VAR` ONE reading in both directions and called
   the class closed. It closed the wrong member. Measured against the live gate:
     rm -f /home/<user>/.claude/settings.json     DENY   (literal control)
     rm -f ~/.claude/settings.json                DENY   (tilde control)
     rm -f $HOME/.claude/settings.json            ALLOW
     rm -f ${HOME}/.claude/settings.json          ALLOW
     cd $HOME/.claude && rm -f settings.json      ALLOW
     cp /tmp/x $HOME/.claude/hooks.json           ALLOW
     echo x > ${HOME}/.claude/settings.json       ALLOW
     git -C $HOME/.claude checkout main           ALLOW
     rm -rf "$HOME/.claude/scripts"               ALLOW
   `$HOME` is not unknowable. It is defined in the hook's own os.environ, it
   names the very tree this gate protects, and `~` was ALREADY expanded on the
   way to a path, so the two spellings of one file disagreed. `$HOME/...` is
   also how a person or an agent writes that path in a script, so the abstain
   was covering the most common spelling of the whole protected set.
   THE FIX IS ONE FUNCTION AT THE ONE FUNNEL, not a special case for the string
   "HOME": kernel_proc.expand_env resolves any `$VAR` / `${VAR}` this process
   can READ and leaves every other one verbatim, and the shared parser's
   `resolve` calls it BEFORE the isabs test, which is the only place it can go
   (after the join the leading `/` is gone and no later reader can put it back).
   Every path layer in this gate already reaches paths through that one call,
   so the target reader, the cd tracker and the redirect reader are all covered
   by it; the two readers that take raw TOKENS (cwd_unknowable,
   names_literal_repo) expand for themselves so they cannot disagree with it.
   NO LIST OF VARIABLE NAMES, anywhere: a list of knowable variables is the same
   hand-kept-list disease entry 32 cured one level up. os.environ IS the list.
   `$SOMEDIR`, `$(cmd)`, a backtick, `${VAR:-x}` and `$1` still abstain, so the
   over-fire entry 33 was added for (`cd "$SP/demo" && git checkout -q master`)
   stays allowed.
   All eight verdicts above flip to DENY except the two that were already right,
   and `rm -f $SOMEDIR/settings.json` stays ALLOW.

37. AND THE FIRST VERSION OF IT PRODUCED A FALSE DENY, measured, not guessed.
   The whole 21,241-row real-command corpus was replayed through the gate before
   and after. One command changed the wrong way:
     export HOME=<sandbox> && mkdir -p $HOME/.claude && cp hooks.json $HOME/.claude/
   a rehearsal that deliberately points HOME AWAY from the live tree. Resolving
   `$HOME` from the hook's environment aimed all three steps back at the brain.
   A variable the command itself assigns is not the variable this process holds,
   so the command is read for its own assignments first and they win
   (g__pretool-bash__tree-owner.command_assignments ->
   kernel_proc.set_command_assignments). LAST assignment wins, which is a
   security property and not a detail: taking the first would read
   `HOME=/tmp/x; HOME=<live>; rm -f $HOME/.claude/settings.json` as a sandbox
   while the shell aims at the brain. A value this process cannot evaluate
   (`export HOME=$REAL`) maps to unknowable rather than to a guess.
   THE PREFIX FORM IS NOT THE STATEMENT FORM, and reading them alike was a
   fail-OPEN this PR introduced and then closed. Measured in bash, not assumed:
     HOME=/tmp/x printf '%s' "$HOME"     -> /home/<user>   (prefix)
     HOME=/tmp/x; printf '%s' "$HOME"    -> /tmp/x         (statement)
   A prefix assignment lands in the environment of the command it prefixes,
   whose own words the shell has ALREADY expanded, so one space in front of `rm`
   would otherwise have disarmed the gate. A segment holding anything but
   assignments now contributes nothing. Boundaries come from the brain's one
   splitter, borrowed not copied, because a raw-text scan matches `HOME=/tmp`
   inside `git commit -m "HOME=/tmp"` and shadows the real variable from inside
   a quoted argument.
   CORPUS COST, both directions, 21,241 unique (command, cwd) rows from 932
   transcripts, replayed against the live brain root:
     before   54 deny / 21,187 allow
     after    53 deny / 21,188 allow
     ALLOW -> DENY   1     DENY -> ALLOW   2
   The one gain is a real disarm that used to pass, not an over-fire:
   `R=/home/<user>/.claude; ... cp -v $W/scripts/g__stop__goal-anchor.py
   $R/scripts/` copies gate BODIES into the live tree through a variable the
   command defines itself. That is the shape this gate exists to deny, and it
   shows the fix reaches any variable, not just $HOME. It also means hand-
   installing scripts into the live brain now denies: the sanctioned path is a
   worktree, a PR and ai-sync, which is what the deny copy already says.
   Both losses are false denies removed. Both are
   `... SP=/tmp/...; cd "$SP/base" && git init -q && git config user.email ...`
   run from a cwd of ~/.claude: the cd was unknowable, so the tree layer
   abstained while `git config` still resolved against the LIVE cwd and denied
   ~/.claude/.git/config. The command configures a throwaway repo in /tmp and
   never touches the brain.
   FIXTURE CONSEQUENCE: benign_unexpanded_rm_absolute.json asserted
   `rm -rf "$HOME/.claude/scripts"` must ALLOW. Inside a selftest leg HOME is
   the sandbox, so that IS the protected tree; the fixture encoded the rule this
   entry corrects and became violation_defined_var_rm_absolute.json. Its benign
   twin is that file minus exactly one edit, the variable name.
   ONE RESERVED NAME, $OCTO_FIXTURE_UNDEFINED: a benign fixture meaning "this
   variable is unknowable" is only benign while the name really is undefined,
   and the operator's shell decides that, so every leg unsets exactly that name.
   benign_unexpanded_cd_then_checkout.json used $SP, whose premise depended on
   the shell, and now uses the reserved name; the shape is unchanged.
   THE EXPANSION CARRIES A CAP AND THE ANSWER ABOVE IT IS EXACT, not a
   truncation and not a timeout: expand_env returns its INPUT unchanged past
   4096 characters (PATH_MAX), so the caller sees a string still carrying `$`
   and applies the unknowable reading it already had. A string longer than
   PATH_MAX cannot be opened, removed or written by any verb these gates read,
   so that is the right answer and not a shortcut. The bound also caps MEMORY on
   the hot path, which is the real reason it is a cap: one long variable
   repeated across a 64 KB body could otherwise expand into hundreds of
   megabytes and get the hook killed, and a killed hook writes no stdout while
   empty stdout reads as ALLOW.
   MEASURED RESIDUAL: with a >4096-character variable already in the hook
   process's environment, `rm -f $BIG/../.claude/settings.json` allows (4,220
   characters, measured). Reaching it needs that variable in the HARNESS
   process's environment, which is the same boundary the merge gate's
   OCTO_MERGE_APPROVE already rests on: a Bash tool call gets a fresh shell and
   its exports never reach the next hook. That boundary is inherited here, not
   re-measured.
   COST, best-of-five, one process per run: `rm -rf ~/.claude/scripts` 0.13 s
   and its `$HOME` spelling 0.14 s, against 0.09 s for a plain `ls -la`.


=== COVERED VERBS (generated by --verbs) ===
  removing: rm shred unlink
  copy/move: cp install ln mv rsync
  flag-destination: cpio curl patch tar unzip wget
  consuming: bzip2 compress gzip lzma xz zstd
  archive-removing: rsync tar zip
  overwriting: sort uniq
  in-place-edit: awk busybox-awk chgrp chmod chown gawk mawk setfacl
  simple-writers: chgrp chown cpio ed ex fallocate gpg nvim openssl rename rename.ul scp setfacl shred split unzip vi vim
  program-argument-hosts: awk gawk mawk node nodejs perl php ruby sed
  cwd-extractors: cpio patch tar unzip
  wrappers-local: busybox chrt doas flock ionice ltrace parallel setsid strace systemd-run taskset toybox
  command-string-hosts: flock script
  interpreter-hosts: bash dash py python sh zsh
  shared-parser-mutators: cp mv rm sed tee truncate unlink
  shared-parser-state: chattr chmod dd touch
  shared-parser-exec: cp mv rm sed shred tee truncate unlink
  wrappers-shared: busybox chrt command doas env exec flock ionice ltrace nice nohup parallel setsid stdbuf strace sudo systemd-run taskset time timeout toybox xargs
  NOT ENUMERATED BY THIS BLOCK (recognised, but not by program name):
    - git subcommands (checkout, switch, restore, rm, reset, stash, clean, read-tree, checkout-index, config, push, am, cherry-pick, revert)
    - find predicates (-delete, -exec, -execdir, -ok, -okdir)
    - redirect spellings (>, >>, &>, &>>, >|)
    - inline write markers and the direct-write patterns
    - protected path SHAPES (<dir>/.claude/settings*.json, scripts/g__*.py)
    - version-suffixed interpreter spellings (python3.12 reduces to python)
=== END COVERED VERBS ===
