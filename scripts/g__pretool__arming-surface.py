#!/usr/bin/env python3
"""g__pretool__arming-surface.py: the LIVE files that decide whether gates run.

RULE #1 says a rule is wired only when its mechanism is verifiably live. Every
mechanism in this brain is live because ONE file registers it and ONE file is
its body. Those files are the arming surface, and until now nothing watched
them. Measured, twice, on 2026-09-08:

  - ~/.claude/settings.json carries `permissions` and, when present, an `env`
    block that Claude Code injects into the session, HOOKS INCLUDED. The merge
    gate's whole agent-proofness rests on OCTO_MERGE_APPROVE being unreachable
    from the model's process; it is. It is NOT unreachable from the NEXT
    session, because a process that writes an `env` block here exports that
    variable into every hook the harness spawns afterwards.
  - No PreToolUse hook watched settings.json, and none watched the gate scripts
    either: `grep settings.json scripts/g__pretool*.py` returned nothing.

So the claim "the agent cannot self-approve its own gate" was true of the env
and false of the REGISTRATION that invokes the reader of that env. A gate whose
registration and whose body an agent can rewrite is not a gate; it is a note.

THE BOUNDARY, and why it is drawn here.

A blanket deny on the gate scripts would make this brain undevelopable by its
own agent: editing `qa-merge-gate.py` or a tree-owner gate is this operator's
normal work, and it happened in the same session that measured the hole. A gate
that blocks real work gets turned off, which is how the over-firing merge gate
ended up being routed around with base64 payloads an hour earlier.

What separates the two is not the file, it is the COPY. Measured here:

  $ git worktree list
  /home/…/.claude                  [master]        <- the MAIN tree
  /home/…/.octorato/wt/qa-gate     [fix/qa-gate…]  <- a secondary worktree
  … 12 more

`~/.claude` is the main worktree of the octorato repo, and it is the tree the
harness actually reads: `hooks.json` commands are literal `~/.claude/scripts/…`
paths, and settings.json has no other copy at all. Every `wt/*` and `dim/*`
checkout is a sibling directory holding SOURCE. So:

    editing scripts/qa-merge-gate.py in a worktree  = development, reviewed,
                                                      merged through the PR path
    editing ~/.claude/scripts/qa-merge-gate.py      = disarming what is loaded

This gate denies only the second. The PR path stays fully open, and so does the
route by which a merged change reaches the live tree: `ai-sync` / `ai-pull` /
`git pull` run the update inside a subprocess of a thunk, so no protected path
is ever a Bash TARGET and nothing here fires. That is deliberate for a PULL, which brings the
remote state through the reviewed path. It is NOT a claim about `git merge`:
`git -C ~/.claude merge <local-branch>` is allowed too and lands UNREVIEWED
local edits on every file in this set, because `qa-merge-gate` guards
`gh pr merge` and nothing guards `git merge`. Stated plainly rather than
implied, and listed again in the residuals below.

Two paths reach the live copy without naming a worktree, and both are covered:
a symlink (every candidate is tested a second time through os.path.realpath),
and a `git -C ~/.claude checkout -- <path>` from anywhere (the shared parser
resolves `-C` before the target is tested).

THE FILE SET, and why each one is an arming surface.

  settings.json, settings.local.json
      The registration surface AND the injected `env`. Both are GITIGNORED
      (measured: `git check-ignore -v` hits .gitignore:42 and :89), so they
      exist ONLY in the live tree. There is no development copy of these two
      and therefore no development case to protect: every write to them is a
      write to the arming surface. This is the file that makes the merge gate's
      OCTO_MERGE_APPROVE forgeable for the next session.
  <any dir>/.claude/settings*.json inside the live root
      The same surface at PROJECT scope, which OUTRANKS user scope. The two
      files above are the USER-scope pair; Claude Code also loads
      `<project root>/.claude/settings.json` and `settings.local.json`, and the
      brain root is itself a project root (`cd ~/.claude` is how this repo is
      developed, and it is literally what the `ai-push` thunk does). Measured
      2026-09-08, before this was covered:

        DENY   Write ~/.claude/settings.json
        ALLOW  Write ~/.claude/.claude/settings.json         (9705 B, 109 allow)
        ALLOW  Write ~/.claude/.claude/settings.local.json  (14756 B, 182 allow)

      The exact disarm this gate exists to prevent was reachable one directory
      over, because the set was named by FILENAME while the effect is "settings
      the next session loads". The test is now a path SHAPE, not a list, so the
      next subdirectory does not reopen it: any `settings*.json` under any
      `.claude/` directory anywhere inside the live root, plus a `.claude`
      directory THAT HOLDS ONE (taking the directory takes the file without
      naming it). That covers deeper project roots without enumerating them,
      and the live tree really carries one: claude-mem-ref/.claude/settings.json.

      "HOLDS ONE" IS ONLY A QUESTION FOR A VERB THAT TAKES, and asking it of
      every verb cost a merge blocker plus a second door found while fixing it.
      A `.claude` that holds no settings disarms nothing by being DELETED, so
      the eight empty ones on the live tree stay removable, all eight measured.
      But the same "it holds nothing" was answered for verbs that PUT something
      there, where what it holds now says nothing about what it will hold:

        ALLOW  Write <live>/stage/settings.json  {"env":{"OCTO_MERGE_APPROVE":"*"}}
        ALLOW  mv <live>/stage <live>/x/.claude          <- absent destination
        ALLOW  cp /tmp/settings.json <live>/knowledge/…/ECC/.claude/
                                                        <- existing empty one

      Two allowed steps to a project-scope settings file with a forged approval
      inside the live root; and every one of the eight "harmless" empty
      directories was a drop box. This header used to say "creating an empty
      `.claude` is allowed, and the FILE rule denies putting settings into it,
      so the line is held by the file test either way". That is FALSE for both:
      the file rule only ever sees file targets and neither command names a
      file. So the listing is consulted ONLY for a REMOVING verb (`rm`,
      `unlink`, `find -delete`, `git rm`); for every other verb the `.claude`
      directory itself is the target, whatever it holds today. `mkdir` is not a
      mutator and never reaches this gate, so creating one stays free. Cost,
      measured: of 17,232 real Bash calls, ONE aims mv/cp/tee/install/ln at a
      nested `.claude` under the live root, and it is a line testing this gate.
      What is newly denied that a person might do: moving an empty `.claude`
      elsewhere, which `rm -rf` still does.
      CASE. All four of `.Claude/settings.json`, `.claude/SETTINGS.JSON`,
      `Settings.local.json` and `.CLAUDE.JSON` were ALLOW before, which is a
      clean bypass on Windows (where install-runners.py ships the `.cmd`
      thunks) and on default macOS APFS, where those spellings are the SAME
      file. Every comparison here is case-folded now; see `_fold`.

      SCOPES COVERED: user (`<brain>/settings*.json`), project, for every
      project root INSIDE the live tree, and the harness user config
      `~/.claude.json` (next entry, covered by name because it is the one
      member outside the root).
      SCOPES THIS GATE CANNOT SEE, both measured, both a residual below:
      enterprise/managed policy outside $HOME, and any project root outside the
      live root (an arm's own `.claude/settings.json` is that arm's business,
      not this gate's).
      NOT an arming surface, checked rather than assumed: a worktree's
      `hooks.json`. It is octorato's tracked source, projected into the live
      settings.json by merge-hooks.py and guarded by check-hooks-drift.py; the
      harness never loads `<repo>/hooks.json`. Every `wt/*` and `dim/*` copy
      stays writable (measured: 6 of 6 ALLOW).
  ~/.claude.json
      The harness's USER CONFIG, and the one member of this set that lives
      outside the live root: a sibling of the brain directory, not a file
      inside it. It carries `mcpServers`, measured 2026-09-08 as three entries,
      each an object with `command`, `args`, `env` and `type`. Writing it names
      a PROGRAM the next session executes at startup with an environment of the
      writer's choosing, which is the same disarm class as an `env` block in
      settings and a worse one, since it is a direct command rather than a
      variable. The rule is "the surfaces that arm the next session", so this
      one is covered by NAME while everything under the root stays covered by
      shape. There is nothing to fight for a development path, checked rather
      than assumed: a PreToolUse hook only ever sees the AGENT's tool calls,
      never the harness writing its own state file, so denying the agent's
      write costs the harness nothing, exactly like the live settings.json
      whose only legitimate writer is also not a hooked process. Measured
      after: Write, Edit, `sed -i`, a `>` redirect, `cp`, `mv`, `rm` and an
      interpreter write all deny; `cat`, a `-c` READ, `~/.claude.json.bak` and
      a worktree copy all allow.
  hooks.json
      The tracked source of the registrations; settings.json's hook block is
      its projection (brain_doctor: "settings.json hooks == validated hooks.json
      projection"). Deleting a line here unregisters a gate without touching
      the gate.
  scripts/g__pretool*.py, scripts/g__stop__*.py, scripts/qa-merge-gate.py
      The bodies of the fail-closed gates. This gate is inside its own pattern,
      on purpose: a floor that exempts itself is not a floor.
  scripts/gate_selftest.py
      The harness whose verdict brain_doctor reads to declare a gate live. A
      selftest that always passes turns the whole gate-liveness check into a
      rubber stamp, so it arms every gate at once.
  scripts/receipt_ledger.py
      The receipt reader: it decides whether a seek receipt, a gate receipt or
      a QA receipt is real. Every v7 boundary consults it.
  scripts/kernel_proc.py, scripts/dimension-awareness-hook.py
      The modules the gates IMPORT at run time, measured rather than guessed:
      `grep -hE "spec_from_file_location|^import" scripts/g__*.py` names
      exactly kernel_proc, receipt_ledger, dimension-awareness-hook and the two
      tree-owners. Protecting a gate and leaving the library it executes
      writable protects nothing, so the closure is in the set, not just the
      entry points.
  scripts/brain_doctor.py
      The prover. RULE #1 is wired BY brain_doctor: it runs every gate's
      --selftest and .githooks/pre-push blocks on its exit code. A doctored
      doctor reports a corrupt brain as healthy and lets the push through, the
      same failure class as a doctored gate_selftest.py.
  registry/rules.yaml
      The Registry RULE #1 loads. A rule deleted here stops being asserted.
  .githooks/pre-push
      The push-time leak guard and the invoker of brain_doctor's fail-closed
      wiring assertion. `git push --no-verify` at the live root is the same
      disarm in one flag instead of one file, so the FLAG is denied too. `-n` is
      not it: for `push` that means `--dry-run`.
  .git/config
      Measured on the live tree: `core.hooksPath=.githooks`. That one key NAMES
      the directory the entry above is run from, so repointing it disarms
      .githooks/pre-push without touching the hook. `git config <name> <value>`
      and `git config --unset <name>` in the live root are denied as writes of
      this file; `git config <name>` and `--get` are READS and stay allowed,
      which is not a nicety: over 18,154 distinct real Bash calls, the version
      that treated one positional as a set denied two commands, both of them
      reading `core.hooksPath` to check it is still `.githooks`.
  registry/fixtures, FOR A WRITE ONLY
      The corpus every `--selftest` is judged against, and gate-liveness is what
      brain_doctor reads to declare a gate live. A violation fixture rewritten so
      it still BLOCKS but tests nothing leaves the gate green while it guards
      nothing, the same rubber stamp as a doctored gate_selftest.py.
      A RESTORE and a REMOVAL are not that, and the number that forced the
      distinction was mine. This entry was reported last cycle as costing ONE
      real command, from a replay that only exercised the put, redirect and
      git-config layers and so never saw the route those commands use. Replayed
      properly over 18,154 distinct real Bash calls it cost ELEVEN, and every one
      was this brain's own fixture maintenance: `git checkout -- registry/
      fixtures/<rule>/home/...` putting back state a selftest had mutated, an
      `rm -rf` of a fixture home, a `cp -r` out of one. A SAME-BRANCH `git checkout --` with no ref
      restores the COMMITTED bytes, which are the ones review approved. A
      restore that NAMES A REF does not, and the sentence used to say "a restore
      puts back the reviewed bytes" without that qualifier: `checkout <ref> --
      <fixture>`, `checkout HEAD~40 -- <fixture>` and `restore --source=<ref>
      <fixture>` all put UNREVIEWED bytes into a violation fixture, which is
      exactly the doctored-fixture-into-green-gate-liveness threat this
      narrowing exists to stop. All three were measured ALLOW and all three now
      deny. A missing fixture makes `--selftest` fail LOUDLY rather than
      silently, so a removal still passes. Measured cost after: THREE, one of
      them the rule working (a heredoc writing fixture files in the live tree)
      and two over-fires of classes already named here, a `mv` OUT of the
      directory (the parser reports both ends of a move under one verb, so
      source and destination cannot be told apart at this layer) and a `cp`
      whose destination was an unexpanded variable.
      The first "zero" for this narrowing was a HARNESS bug and is recorded
      because it looked like evidence: the replay called `hit()` without the
      `verb` argument the narrowing reads, so it measured the un-narrowed path
      and reported eleven flips for code that no longer produced them.
  scripts/merge-hooks.py
      The SANCTIONED writer of settings.json, and that is the argument for
      protecting it rather than against. The interpreter residual below concedes
      that a hook never sees inside a subprocess, so `python3 scripts/
      merge-hooks.py` writes the live settings and always will; edit the program
      and the next legitimate run of it writes whatever you put there.

Plus one WHOLE-TREE class: `git checkout <branch>`, `git switch`,
`git reset --hard|--merge|--keep`, `git stash`, `git clean -f`,
`git read-tree -u|--reset` and `git checkout-index -a -f`, aimed at the live
root. They rewrite every file in the set at once, so a file-by-file deny that
ignored them would be trivially walked around with one branch switch. The last
two were reproduced as ALLOW and are named here rather than in the shared
parser, which carries the lane rule and is under edit elsewhere; the borrowed
`git_parse` still resolves their `-C`, so this is a verb table and not a second
parser. `git worktree remove` is deliberately NOT one of them: it deletes a
sibling checkout and rewrites nothing here. Neither is a checkout or switch that
CREATES a branch AND NAMES NO START POINT (`checkout -b tmp`, `checkout -qb tmp`,
`switch -c tmp`, `checkout -B tmp`, `--orphan tmp`): that makes a ref at HEAD and
rewrites no file, the deny copy that fired on it said "rewrites the whole working
tree" and that was simply false, and about ten of them appear in real traffic.
THE START POINT IS PART OF THE EXEMPTION, not a detail: git takes an optional
start point after the new name, and with one the command checks that commit out.
The first version of the exemption looked only at the create FLAG, so
`checkout -b tmp evil`, `switch -c tmp evil` and `checkout -B tmp evil` were all
exempted by their harmless half, and QA took a real git receipt of a file reading
`good` before and `EVIL` after. The exemption now requires the verb to be
followed by exactly ONE positional, the new branch name, which also separates
`-B tmp` (moves a ref to HEAD, touches nothing) from `-B tmp evil` (rewrites the
tree) without a second rule. It still needs the command to carry exactly ONE
checkout/switch, so `checkout -b tmp && checkout evil` is judged as before.

Plus one PUT class, all of it measured as ALLOW before, and all of it about the
same question: WHERE does this command leave a file?

  `cp -t <dir> <src>` and `--target-directory=` INVERT the argument order, so
  the shared parser's `positional[-1:]` handed back the SOURCE. That is the one
  rule guarding `cp` reading the wrong end of the command, with a real bash
  receipt of the file landing in the live tree. `install -t` and `ln -t` share
  that rule and share the bug. `mv -t` does NOT, measured rather than assumed
  when a reverted-fix anchor refused to turn its fixture red: the shared parser
  returns EVERY positional for `mv`, so the destination was already among them
  and `mv -t` was denied before this reader and after it. Its fixture stays as a
  control on that behaviour, not as evidence for this fix.
  A DIRECTORY DESTINATION RECEIVES THE SOURCE'S BASENAME.
  `cp -r /stage/.claude <live>/knowledge-ref/` never spells a protected path and
  creates a project-scope settings directory one command later. The residual
  that called this "walking an arbitrary source tree" was wrong: it is
  `os.path.join(dest, os.path.basename(src))`, a string, and the classifier
  already answers that path.
  SOME WRITERS ARE NOT MUTATION VERBS AT ALL: `install`, `ln -f`, `rsync`,
  `curl -o`, `wget -O`, `tar -x -C`, `patch -o|-d` and `awk -i inplace`. The
  traffic count below used to name `install` and `ln` as if they were covered.
  They were not.
  THREE REDIRECT SPELLINGS the shared parser cannot see, because it tests
  `startswith(">")` after stripping digits: `&>`, `&>>` (they start with `&`)
  and `>|` (it yields the literal `|file`). All three write the file.
  `find` IS NOT ALWAYS A REMOVING VERB. The shared parser labels every find it
  reports `find -delete`, but it also fires on `-exec <mutator>`, and a mutator
  can PUT: `find <live>/…/.claude -maxdepth 0 -exec cp /tmp/settings.json {} +`
  was read as removing, the empty listing answered "nothing to take", and the
  settings landed in the drop box. The per-verb split was right; the LABEL lied,
  and it is re-derived here from what the command actually carries.

These live in a local table for the same reason the two extra git verbs do: the
shared parser is under edit on another branch, where `_copy_targets` already
carries the `-t` rule for `cp`/`install`/`ln`. Borrowing it today would mean
borrowing a function the LIVE parser does not have. When that lands, this table
goes.

INDIRECTION: A PROGRAM THAT REACHES A PATH THROUGH ANOTHER PROGRAM. Every row
below was run against the LIVE brain as cwd, with `rm -rf ~/.claude/scripts` as
the positive control (denies) and `ls ~/.claude` as the benign one (allows).
The list is here rather than in a commit message because an open member nobody
named is what turns into the next failure.

  CLOSED, each with a fixture pair:
    find -exec / -execdir / -ok / -okdir running rm, unlink or shred, with any
      terminator (an escaped `;`, a bare one, or `+`); a pipe into a removing verb, through xargs
      (`-0`, `-n1`, `-I{}`) or parallel or bare; the wrapper prefixes setsid,
      setsid -w, flock, ionice, chrt, taskset -c, doas, busybox, toybox,
      parallel; and a BUNDLED `-c` on a shell host (`bash -ec`, `sh -lc`).
    Already closed before this cycle and re-checked here: sh -c, bash -c, env,
      nice, timeout, sudo.

  OPEN, measured as ALLOW, and why each is left:
    eval 'rm -rf ~/.claude/scripts'          the body is a string until the
    echo `rm -rf ~/.claude/scripts`          shell runs; a table cannot read it
    echo $(rm -rf ~/.claude/scripts)         (`$(…)` is being closed in the
    rm -rf ~/.claude/{scripts,hooks.json}     SHARED parser on another branch)
    D=~/.claude/scripts; rm -rf $D
    find … -exec sh -c 'rm "$1"' _ {} +      indirection two levels deep: the
                                             -exec program is a shell, and this
                                             reader judges the program it is
                                             handed, not the program that one
                                             runs
    find … -exec dd of={} …                  `dd` is not in the shared parser's
                                             `_EXEC_MUTATORS`; that table is
                                             where the row belongs
    xargs -a /tmp/list rm                    the targets are in a FILE, the same
    cat /tmp/list | xargs rm                 class the shared parser already
                                             names, and neither command carries
                                             a path to test
    find <live> -name '.claude' -exec cp     a GLOB that reaches only a
      /tmp/settings.json {} +                protected DIRECTORY: `glob_hit`
                                             matches patterns against concrete
                                             protected FILES, so a filter that
                                             names a `.claude` directory hits
                                             none of them. The direct spelling
                                             (`cp /tmp/settings.json
                                             <live>/x/.claude/`) is denied
    taskset 0x3 rm -rf ~/.claude/scripts     the bare-mask form; see the wrapper
                                             table for why `arg` cannot be both
    shred ~/.claude/settings.json            `shred` and `perl -pi` are the
    perl -pi -e … ~/.claude/scripts/…        shared parser's own named residuals
                                             (`_MUTATORS` carries neither), and
                                             this gate inherits that list rather
                                             than growing a second one

NO ENV UNLOCK, deliberately. Every other gate here prints one, and an env
unlock for THIS rule would be self-serve: the variable that lifts it is exactly
the kind of thing an agent would write into the settings.json `env` block this
gate exists to protect. Same stance and same words as the kernel's own state
floor, which denies every hooked process including itself: the operator's
terminal is not hooked and stays the only writer.

THE POLARITY, because it decides how every list below should be read: this gate
has NO ALLOW-LIST. It is a DENY-LIST of recognised writer and remover verbs, so
a program neither the shared parser nor the tables here recognise passes
SILENTLY. The residual list is therefore not a footnote; it is the only thing
between a reader and a false sense of coverage, and it was missing six members
that exist on this machine (the compressors, `tar --remove-files`, `zip -m`,
`sort -o`, `uniq`), all now covered and all found by QA rather than by this
list. Read what follows as "what is known to pass", never as "what can pass".

NAMED RESIDUALS, measured, deliberately not covered:
  - An INTERPRETED write. `python3 scripts/merge-hooks.py` legitimately writes
    settings.json, and a hook never sees inside a subprocess. Only Write/Edit
    and shell mutations are targets here. Two best-effort layers read INLINE
    programs, and they ask DIFFERENT questions on purpose:
      * a `-c` body is read for a protected literal next to a write marker
        (open(…,'w'), write_text, json.dump, writeFileSync); a read of the same
        file through the same `-c` passes, which is why the layer needs the
        marker. Every one of the 16 markers is individually load-bearing, one
        fixture each, every deletion run. The host table is SIX, down from
        ten: `node -c` is not a thing and `perl -c` / `ruby -c` only check
        syntax, so those three could never reach a write, and `python3` was a
        second name for `python` once the version suffix is stripped. Each of
        the six that remain now has its own violation, proven by deletion. Spellings that used to slip and now deny: `python3.12 -c`
        (the version strip kept the dot), `python3 -u -c` and `python3 -I -c`
        (the host was read as tokens[i-1]), a bundled `sh -lc`, and a fused
        `-c"…"`.
      * a HEREDOC body is read only for a protected literal that is the DIRECT
        OPERAND of a write (`open(<literal>,'w')`, `Path(<literal>).write_text`,
        `writeFileSync(<literal>`, a `> <literal>` redirect), and only when the
        opening line feeds an interpreter. The loose marker test was tried first
        and measured on 17,232 real Bash calls: it flipped 23 to DENY, of which
        2 were genuine live writes and 21 were a heredoc writing a DOCUMENT that
        QUOTES a protected path, which is what editing this gate's header, its
        fixtures, its README and CLAUDE.md looks like. Precision 2/23 on a rule
        with no env unlock is a gate that gets routed around, so the narrow test
        ships: 2 of 3,296 real heredoc commands, down from 23, and the direct
        attack still denies. Those 2 are stated rather than rounded away: both
        are one command writing a TEST HARNESS whose text carries the attack
        literal, which no text scan separates from the attack itself.
    Anything that reaches the file through a script file, a VARIABLE, or an
    unlisted write idiom passes on both channels. Both genuine live writes in
    the corpus were the variable shape, which is the honest price of the narrow
    heredoc test and is stated rather than hidden.
    Reproduction: see registry/fixtures/…/README-residuals.txt.
  - A READ SPELLED AS A COPY. `python3 -c "shutil.copy(<live settings>, /tmp/x)"`
    DENIES, although it only reads. `shutil.copy` is a real write idiom and the
    literal scan cannot see which side of the call the needle is on, so the
    over-fire is kept in exchange for the write it catches. Named because the
    README's "reading through the same `-c` passes" is true of `open` and not of
    this one.
  - A SETTINGS SCOPE OUTSIDE THE LIVE ROOT, minus the one that was taken.
    `~/.claude.json` used to be listed here as "the strongest uncovered surface
    left", on the reasoning that the harness rewrites it every session and a
    deny would leave no development path. That reasoning was wrong and is
    recorded here so it does not come back: a PreToolUse hook never sees the
    harness write its own state file, only the agent's tool calls, so there was
    nothing to fight. It is now covered by name (see the file set above).
    What remains: enterprise/managed policy
    (`/etc/claude-code/managed-settings.json` on Linux) is outside $HOME and
    root-owned, so the OS is the gate there and this one never sees it; a
    project root outside the live tree (an arm's `.claude/settings.json`) is
    that arm's business. Reproduction: `Write /etc/claude-code/
    managed-settings.json` and a write to an arm's own settings are allowed.
  - AN ANCESTOR DIRECTORY OF A DEEP PROJECT ROOT, in BOTH directions. `rm -rf
    ~/.claude/claude-mem-ref` takes that root's `.claude/settings.json` without
    naming it or its `.claude` directory, and `mv /tmp/s ~/.claude/x` where
    `/tmp/s/.claude/settings.json` exists plants one the same way. One class,
    one reason: the classifier tests the PATH IT IS GIVEN, and neither command
    gives it a `.claude`. Covering the delete means listing the live tree on the
    hot path for every rm; covering the create means walking an arbitrary source
    tree. Both are costs this gate refuses to pay, and both are strictly weaker
    than the interpreter residual above, which already concedes that an
    adversary running a script file writes anything. `rm -rf ~/.claude` and
    `rm -rf ~/.claude/.claude` stay denied, because they conflict with a path
    the classifier already holds. Reproduction: `rm -rf ~/.claude/claude-mem-ref`
    and `mv /tmp/s ~/.claude/x` are allowed; `mv /tmp/s ~/.claude/x/.claude` is
    not.
  - `git merge`, `git pull`, `git rebase`, `git apply` in the live tree: the
    shared parser classifies none of them as whole-tree. A PULL brings the
    remote state, which is the sanctioned route. A MERGE does not: `git -C
    ~/.claude merge <local-branch>` is ALLOWED and lands unreviewed local edits
    on every file in this set, because `qa-merge-gate` guards `gh pr merge` and
    nothing guards `git merge`. That is the honest sentence, and it replaces
    "a pull brings the REVIEWED remote state", which was true of pull and was
    being read as if it covered all four. Reproduction: `git -C ~/.claude merge
    feat/anything` is allowed.
  - A NON-Bash, NON-Write tool that writes a file. The gate reads targets from
    Write/Edit/NotebookEdit/MultiEdit and from Bash; an MCP tool that takes a
    path and writes it would pass. Measured against the servers registered on
    this runtime today (gmail, whatsapp, bonsai, repomix, claude-in-chrome,
    Google Drive/Calendar, Microsoft Learn, Cloudflare), none writes an
    arbitrary local path, so this is a gap in shape, not in reach. It is left
    open rather than closed by testing every tool that carries a `file_path`,
    because that would deny a READ of settings.json through such a tool, and an
    over-firing gate is the failure mode this whole boundary was drawn to
    avoid. Registering on the `*` matcher is what makes closing it later a
    one-line change here rather than a new registration.
  - A DESTINATION THAT ONLY EXISTS AFTER THE SHELL EXPANDS SOMETHING. Brace
    expansion (`rm -rf ~/.claude/{scripts,hooks.json}`), `$(cmd)`, a backtick,
    `${VAR:-x}` and every other parameter-expansion operator, `$1`, `$'…'`,
    `eval`, a shell function, and a symlink created and USED in the same
    command. Each needs a shell, not a table, and a table that guessed at them
    would be a second parser with its own drift. Reproduction: every one of
    those spellings is allowed today.
    A BARE `$VAR` IS NO LONGER ON THIS LIST, and leaving it here was the
    over-broad half of the claim. `$HOME` is not unknowable: this process holds
    it, it names the very tree being protected, and `~` was already expanded, so
    the two spellings of one file disagreed. `kernel_proc.expand_env` resolves
    every variable this process can READ, called from the SHARED parser's
    `resolve` where it belongs, so both gates got it at once. What stays open is
    a variable NOBODY here can read: absent from `os.environ` and not assigned
    by the command from anything evaluable (`export HOME=$OTHER && rm -rf
    $HOME/.claude`). See residual entries 36 and 37.
  - Everything the shared parser already names as its own residual (rsync
    --delete, shred, ln -sf, perl -pi, brace expansion, an unreadable variable,
    a `-c` body nested deeper than 3, xargs fed from stdin). This gate inherits
    that list rather than growing a second parser.
  - A COMMAND OVER 64 KB IS NOT READ BY THE TWO INLINE LAYERS, and that is the
    ONLY thing the cap skips. It used to skip everything: `main()` returned at
    the cap when the command carried no `-c` and no heredoc, so
    `rm -rf ~/.claude/scripts` DENIED at 65,536 bytes and ALLOWED at 65,537 with
    a comment as the padding, and QA measured the same one-character bypass for
    `git checkout evil`, a `>` redirect into hooks.json, `tee` on settings and
    `sed -i` on a gate body. This text used to claim "the path and tree layers
    still run on it", which was simply false. They run now: an oversize command
    with no inline channel falls THROUGH to them and only the two readers that
    are quadratic in one token are skipped. Nothing new is paid for in wall
    clock, because the sibling Bash tree-owner gate already runs this same
    parser on this same command with no cap at all, and same-event hooks run in
    parallel.

NET EFFECT ON REAL TRAFFIC, replayed rather than argued, and re-replayed for
every layer this cycle added. 18,154 DISTINCT Bash commands from this machine's
transcripts (19,171 calls), each layer run against the previous version of
itself:

    the two INLINE readers
      heredoc_write      fires on 10, was 6.  4 newly denied, and all four are
                         commands from THIS cycle's adversarial lab writing a
                         probe script or a fixture generator whose TEXT carries
                         the attack literal. That is the residual class already
                         named, now with a number rather than a promise.
      interpreter_write  fires on 1, was 1.   0 newly denied, although its
                         needle list grew from four files to every protected
                         file: no real command writes a gate body inline.
    the three PATH layers added this cycle
      put destinations   1 newly denied, and it is not the `-t` rule: a `cp`
                         whose destination was an unexpanded `$SB` inside
                         registry/fixtures/, denied because that DIRECTORY is
                         now in the set.
      exotic redirects   0 newly denied.
      git config / push  0 newly denied, after two intermediate false denies
                         were measured and fixed rather than shipped: treating
                         one positional as a `config` SET denied
                         `git config core.hooksPath` READING the key, and
                         counting `2>&1` as a positional made a read look like a
                         two-argument set.

Two over-fires this cycle were found by replay and removed before shipping, both
worth naming because both were the gate denying its own maintenance: reading the
heredoc host out of the whole command string (rather than the SHELL half) made
`cat > README-residuals.txt <<'EOF'` deny, because that document quotes
`open('~/.claude/settings.json','w')` as an example; and the `config` read above.
The previous cycle's numbers stand for the layers it changed: 11 flipped
DENY -> ALLOW (7 `checkout -b`, 2 glob-collapse diagnostics, 2 heredocs read as
interpreter bodies they are not) and 2 flipped ALLOW -> DENY.

Hot path: the size cap is tested on the raw string first, then one
`paths_conflict` against the brain root rejects everything outside ~/.claude
before any listing or realpath happens, and the shared parser's own trigger test
returns [] before it PARSES anything. It does not return before it LOADS
anything, which is what this used to say: QA straced a plain `ls` and the parser
module is opened on every Bash call, because `bash_targets` reaches `_parser()`
to get `scan` before `scan` gets to decide there is nothing to do. The timing
numbers below are unaffected and were always measured through the whole process,
import included; only the sentence was wrong. Measured warm on this
machine: ~65 ms for `import kernel_proc` on every call (the same import
g__pretool__kernel.py already pays on the same `*` matcher), ~1 ms for a
command with no mutation token, and ~90-190 ms more for one that has a token
(the shared parser loading dimension-awareness-hook.py, which the Bash
tree-owner gate is already paying in parallel for the same command). Same-event
hooks run in parallel, so the wall-clock addition is bounded by the slowest
hook, not the sum. Measured again with everything in place, best of
three to five per shape, whole process including interpreter start: `ls -la`
0.10 s, `pytest -q` 0.11 s, an `rm` on a protected path 0.14 s, a 63 KB `-c`
body (the worst case still SCANNED) 0.41 s, a 70 KB one 0.10 s because it is
refused instead of read, a `find -exec rm` 0.25 s and a `find | xargs rm`
0.27 s.

THE WORST CASE IS NOT THE LONGEST COMMAND, and quoting it as if it were is the
mistake this paragraph used to make. "127 KB, the worst case still PARSED,
1.79 s" was ONE LONG WORD, which is shlex-quadratic and cheap. The expensive
shape at the same byte count is MANY SHORT TOKENS, because the work in the
target loop grows with TOKEN COUNT and the byte caps cannot see that axis:

    rm -f <one 131 KB word> ~/.claude/settings.json        1.8 s
    rm -f <65,512 short tokens> ~/.claude/settings.json    18.5 s   (before)

Profiled, the 18.5 s is not shlex: it is 65,512 passes through
`hit` -> `classify` -> `realpath`, one per target. QA measured that shape x8
concurrent on a loaded box at 38.8-50.9 s against the harness's 60 s default,
and a killed hook writes empty stdout, which is ALLOW. The command that would
be killed and therefore allowed is a real disarm.

Two fixes, on the two axes that were actually growing: the invariants are
computed once per process instead of once per target (`brain_root` was called
131,023 times, `scripts_dir` 65,511, and `classify` rebuilt the `_EXACT` table
every time), and `_MAX_TARGETS` bounds the number of DISTINCT targets with
`hit` memoised so repeats are free.

MEASURED AFTER, AND LABELLED, because a single-run best-of-five and a figure
taken under concurrency differ by about 4x for the same shape, and quoting only
the first costs a reader their calibration. Left column is best of five runs
alone; the two right ones are eight of the same command at once on a box idling
near load 20 on 4 cores.

    shape                            best5     x8 worst   x8 mean   verdict
    65,512 identical short tokens     1.99 s     8.85 s    7.50 s    deny
    distinct short tokens             1.45 s     5.56 s    4.20 s    deny
    511 distinct DEEP paths           0.47 s     1.86 s    1.51 s    deny
    131 KB grep, fully parsed         1.11 s     4.30 s    3.81 s    ALLOW
    131 KB echo, no trigger           1.08 s     4.22 s    3.34 s    ALLOW
    over the parse ceiling            0.25 s     1.06 s    0.74 s    deny
    ls -la                            0.12 s     0.67 s    0.50 s    ALLOW
    2,427 `find … -delete;` segments  1.44 s     4.39 s    3.67 s    ALLOW
      in 64 KB                                             (was 4.94 / 13.55)

THE SEGMENT SHAPE IS A THIRD AXIS, and neither byte cap nor the target budget
could see it: 2,427 segments whose glob is the SAME string deduped to ONE entry
in the target budget while the cost stayed per HIT, and each hit walked every
protected pair. That pair count is a LIVE quantity, 31 on this tree today, and
it grows with every gate script added under `scripts/`, so the shape gets more
expensive on its own over time. `glob_hit` is memoised on (pattern, icase) now,
which is the difference between the two numbers in the last row.

The worst measured anything is 8.85 s against the harness's 60 s default, so no
input in this table reaches the kill-to-allow window.

Past 128 KB nothing is parsed: 300 KB and 1 MB both answer in 0.1-0.2 s, denied
when a mutation token is present and allowed when there is none.
Everything except a real hit fails OPEN, with TWO exceptions,
both of them silent holes before this: the borrowed parser failing to LOAD now
denies, and so does this gate failing to import its OWN `kernel_proc`. The second
was the one the first did not cover: that import sat at module scope with nothing
around it, so a missing or broken copy raised BEFORE `main()` existed, the process
exited rc=1 with empty stdout, and the harness read the silence as ALLOW. The
`try/except` at the bottom of this file could never catch it. `kernel_proc.py` is
inside the set this gate protects, so that was a gate whose own floor could be
removed by removing one of the files it guards. Both legs (absent and
syntactically broken) are asserted in `--selftest`.
A blanket `except` around the import turned this into an all-ALLOW with no
output whenever `receipt_ledger.py` or `kernel_proc.py` was missing, and both
are inside the set this gate protects, so the failure was invisible at runtime
and QA's positive control was the only thing that saw it. A load failure is
structural and cannot be provoked by any command an agent writes, so denying on
it costs no legitimate work; a command the parser cannot READ still allows,
because denying on that would hand anyone a session-wide DoS for the price of
one unbalanced quote. Asserted in `--selftest`, which cannot express it as a
fixture: making the load fail needs the loader repointed, and any payload or env
that could repoint it would itself be the disarm.

NO `timeout` IN THE REGISTRATION, and that is NOT what bounds the cost. The
sibling PreToolUse gates carry `timeout: 5`; this one carries none and takes the
harness default of 60 s, because a timeout is a KILL, a killed hook writes
nothing to stdout, and empty stdout reads as ALLOW. That reasoning is still
right and it was being asked to do a job it cannot do. Whatever the timeout is,
an adversary who can make the gate slow needs a BIGGER payload, never a
different technique, so the number only sets the size of the payload. Measured
through main() on this machine before the cap: 24 KB 0.19 s, 97 KB 0.79 s,
195 KB 3.13 s, 390 KB 9.72 s, four times the time for twice the size, entered by
the two characters `-c` ANYWHERE in the command and before any host or needle
test. What bounds it is `_MAX_SCANNED`: past 64 KB a command carrying an
interpreter body or a heredoc is DENIED rather than scanned, which turns the
kill into a refusal. Worst case under the cap is now 0.49 s. The cap is measured
against real traffic, not picked: 17,232 Bash tool calls in this machine's
transcripts, largest 32,359 bytes, p99 5,145, none over the cap. The 60 s
default stays for the honest reason it was chosen (a genuinely hung stat should
make the user wait, not be skipped), and it is no longer load-bearing.

Stdin:  PreToolUse payload {"tool_name", "tool_input", "cwd", …}
Stdout: deny JSON on a hit, else nothing. Exit always 0.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# THE FIRST IMPORT IS ITSELF A FAIL-OPEN SURFACE, and it was the one hole the
# borrowed-parser deny did not cover. `kernel_proc.py` is INSIDE the set this
# gate protects, and it was imported at module scope with nothing around it: a
# missing or syntactically broken copy raised before `main()` existed, so the
# process exited rc=1 with empty stdout and the harness read that as ALLOW. Same
# shape as the borrowed parser's silent all-ALLOW, one import earlier, and the
# `try/except` at the bottom of this file could never see it because the failure
# happens before `__main__` is reached.
#
# Answered the same way and for the same reason: a load failure is STRUCTURAL,
# never provoked by any command an agent can write, so denying on it costs no
# legitimate work. The deny copy is built from `os.environ` alone, because the
# module that resolves the brain root is exactly the one that is missing.
try:
    import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)
except Exception as _exc:               # pragma: no cover - asserted in selftest
    kernel_proc = None
    KERNEL_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    KERNEL_IMPORT_ERROR = ""

_HERE = os.path.dirname(os.path.abspath(__file__))
RULE_ID = "ARCHITECTURE.arming-surface"
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")


# CASE. Every test below compares path COMPONENTS, and this brain runs on two
# platforms where the file system does not: Windows, which is where
# install-runners.py ships the `.cmd` thunks, and default macOS APFS. On both,
# `.Claude/SETTINGS.JSON` and `.claude/settings.json` are the SAME file, and
# measured on this ext4 host before the fold, all four of `.Claude/settings.json`,
# `.claude/SETTINGS.JSON`, `Settings.local.json` and `.CLAUDE.JSON` were ALLOW.
# `os.path.normcase` would close Windows and leave macOS open (it is identity on
# every POSIX host), so the fold is unconditional. The price on Linux, where the
# two really are different files, is that a directory literally named `.CLAUDE`
# would be protected while arming nothing; nothing on this tree carries one, and
# denying a write to a path that does not exist costs nothing. That is the
# cheaper side of the trade, and it is the whole reason this is a fold and not a
# platform test.
_FOLD_CACHE = {}


def _fold(text: str) -> str:
    text = text or ""
    got = _FOLD_CACHE.get(text)
    if got is None:
        if len(_FOLD_CACHE) > 4096:
            _FOLD_CACHE.clear()      # bounded: a hostile command cannot grow it
        got = _FOLD_CACHE[text] = text.casefold()
    return got


def _conflict(a: str, b: str) -> bool:
    """`kernel_proc.paths_conflict`, case-folded. That helper is a pure prefix
    and equality test on normalized strings, so folding BOTH operands keeps the
    containment relationship it measures; both sides here are derived from the
    same brain root, so neither can fold into the other by accident."""
    return kernel_proc.paths_conflict(a, b) or \
        kernel_proc.paths_conflict(_fold(a), _fold(b))

# Files with exactly one copy that matters: the live one. Relative to the brain
# root so a sandboxed HOME (every selftest leg) resolves its own.
_EXACT = {
    "settings.json":
        "the harness's registration surface: `permissions` and the `env` block "
        "Claude Code injects into every hook it spawns next session, which is "
        "where OCTO_MERGE_APPROVE would become forgeable",
    "settings.local.json":
        "the per-machine half of the same registration surface, injected the "
        "same way",
    "hooks.json":
        "the registration source every gate is projected from: unregister a "
        "line here and the gate stops being invoked without being touched",
    "registry/rules.yaml":
        "the Registry that RULE #1 loads: a rule deleted here stops being "
        "asserted at all",
    ".githooks/pre-push":
        "the push-time gate that runs brain_doctor's wiring assertion",
    ".git/config":
        "the repo config the live tree reads, and `core.hooksPath` inside it "
        "NAMES the directory the push-time gate is run from (measured on the "
        "live tree: core.hooksPath=.githooks). Repointing that one key disarms "
        ".githooks/pre-push without touching the hook",
    "registry/fixtures":
        "the fixture corpus every `--selftest` is judged against, which is what "
        "brain_doctor's gate-liveness check reads to declare a gate live. A "
        "violation fixture edited to stop violating leaves the gate green while "
        "it guards nothing, the same rubber stamp as a doctored gate_selftest",
}

# Gate bodies under scripts/. Patterns, not a list, so a NEW g__pretool*.py
# dropped into the live tree is covered the moment it is created.
# `merge-hooks.py` is here for the reason the residual list already gave and
# then did not act on: it is the SANCTIONED writer of settings.json, the one
# program whose job is to project hooks.json into the file this gate protects.
# The interpreter residual concedes that a hook never sees inside a subprocess,
# so `python3 scripts/merge-hooks.py` writes settings.json and always will. That
# is an argument for protecting the program, not for leaving it writable: edit
# it and the next legitimate run of it writes whatever you put there. By this
# gate's own criterion (the surfaces that arm the next session) it is one.
_SCRIPT_PATTERNS = ("g__pretool*.py", "g__stop__*.py", "qa-merge-gate.py",
                    "gate_selftest.py", "brain_doctor.py", "receipt_ledger.py",
                    "kernel_proc.py", "dimension-awareness-hook.py",
                    "merge-hooks.py")
_SCRIPT_WHY = ("the body of a fail-closed gate (or the harness and libraries "
               "every gate is proven and read by)")

# PROJECT-scope settings, which outrank the user-scope pair above. A session
# whose cwd is a project root loads `<root>/.claude/settings.json` and
# `settings.local.json` ON TOP of `~/.claude/settings.json`, and the brain root
# IS such a project root: `cd ~/.claude` is how this repo is developed and what
# the `ai-push` thunk does. Measured 2026-09-08 on the live tree, before this
# was covered: ~/.claude/.claude/settings.json (9705 bytes, 109 allow entries)
# and settings.local.json (14756 bytes, 182) both existed and both were
# WRITABLE while ~/.claude/settings.json was denied. Same loaded effect, one
# directory over, which is a set named by FILENAME instead of by EFFECT.
#
# So the test is a path SHAPE, not a list: `<anything>/.claude/settings*.json`
# under the live root. That covers every project root inside the live tree
# without enumerating them, including the vendored reference checkouts measured
# today (claude-mem-ref/.claude/settings.json). A `.claude` directory itself is
# in the set too, because deleting or moving it rewrites the settings it holds
# without ever naming them.
_PROJECT_DIRNAME = ".claude"
_PROJECT_SETTINGS_GLOB = "settings*.json"
_PROJECT_WHY = (
    "a PROJECT-scope settings file, which the harness loads ON TOP of the "
    "user-scope one and which OUTRANKS it: same `permissions` and same `env` "
    "block injected into every hook the next session spawns, one directory "
    "over from the file this gate already denied"
)
_PROJECT_DIR_WHY = (
    "the PROJECT-scope settings directory the harness reads when a session "
    "starts in this root: taking the directory takes settings*.json inside it "
    "without ever naming the file"
)

# The ONE member of the set that lives outside the live root. `~/.claude.json`
# is the harness's user config, a sibling of the brain directory rather than a
# file inside it, and it carries `mcpServers`: measured 2026-09-08, three
# entries, each an object with `command`, `args`, `env` and `type`. Writing it
# names a PROGRAM the next session executes at startup with an environment of
# the writer's choosing, which is the same disarm class as an `env` block in
# settings and a worse one, since it is a direct command rather than a
# variable. The rule this gate enforces is "the surfaces that arm the next
# session"; most of them sit under the live root, this one does not, so it is
# covered by NAME while everything under the root stays covered by shape.
#
# There is no development case to protect, checked rather than assumed: a
# PreToolUse hook only ever sees the AGENT's tool calls, never the harness
# writing its own state file, so denying the agent's write costs the harness
# nothing. Same position as the live settings.json, whose only legitimate
# writer is also not a hooked process.
_USER_CONFIG_NAME = ".claude.json"
_USER_CONFIG_WHY = (
    "the harness's user config, which carries `mcpServers`: each entry names a "
    "`command` plus its `args` and `env`, so a write here hands the NEXT "
    "session a program to run at startup in an environment of the writer's "
    "choosing. It is the one arming surface outside the live root, covered by "
    "name because it has no copy anywhere else"
)

# Whole-tree git verbs, as the shared parser labels them: they rewrite every
# file in the set at once. `git worktree remove` is the one the shared parser
# calls whole-tree that is NOT one here, measured: it deletes a SIBLING
# checkout and never rewrites a file in the live tree, so denying it would cost
# real housekeeping (removing a merged worktree from ~/.claude) to prevent
# nothing. The collision it does cause, taking a tree another process is
# working in, stays denied by the tree-owner gate that owns that rule.
_TREE_KINDS = ("tree",)
_TREE_EXEMPT = ("git worktree remove",)

# Interpreter `-c` bodies: best-effort only, and only with a write marker, so a
# `python3 -c` that READS settings.json (a real, frequent shape) still passes.
#
# Every marker below is PROVEN, one fixture each. The list used to be a claim:
# only `'w'` and `.write(` appeared in any fixture, and they appeared in the
# SAME body, so deleting the other 12 left the selftest green and the list said
# nothing about what the gate catches. Each entry now has
# `violation_marker_<slug>.json` whose `-c` body carries THAT marker and no
# other (checked mechanically), a `benign_marker_<slug>.json` one edit away
# that reads the same file through the same idiom, and the violation's
# expectation names the marker in the deny text, so a fixture cannot pass on
# some other entry's behalf. Deleting any one marker turns exactly its own
# fixture red; every deletion was run. There are 16 now, not 14: `'r+'` and
# `"r+"` joined on a measurement, see the list itself.
# `writeFileSync`/`appendFileSync` are Node idioms and node takes `-e`, not
# `-c`, so their reachable shape is a nested one (`sh -c "node -e …"`) and that
# is what their fixtures use.
#
# THE HOST TABLE IS SIX, not ten, and the four that left were dead weight of
# exactly the kind the marker list carried a commit ago. QA mutated all ten:
# eight survived deletion and only `sh` was load-bearing, so "every host is
# independently load-bearing" was a claim, not a measurement.
#
# Three left on reasoning about what the programs DO: `node -c` is not a thing
# (node takes `-e` / `--check`), and `perl -c` / `ruby -c` are syntax-check-only
# flags that never execute the body, so none of the three could reach a write
# through a `-c`. They stay covered where they ARE reachable, nested inside a
# shell host, which is the shape their four fixtures already use.
#
# The fourth left on a MEASUREMENT, after the rewrite: deleting `python3` still
# left every fixture green, because `_is_c_host` strips a version suffix and
# `python3` reduces to `python`, which is in the table. An entry that another
# entry already answers for is not a second guard, it is a second name, and this
# gate spent a commit learning that about the markers. `py` is not that (it
# strips to itself), so it stays.
#
# Each of the six now has a violation whose deny turns on THAT entry, verified
# by deleting each one and watching exactly its own fixtures go red, with a
# no-op control green in the same run.
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "py")
# `'r+'` joined the list on a measurement, not a hunch: `open(<live settings>,
# 'r+').truncate(0)` empties the file and carried NO marker, so the `-c` channel
# read it and allowed it. It is a write handle by definition (the `+`), and the
# read spelling one edit away (`'r'`) still passes, which is the pair every
# entry here is proven by.
_WRITE_MARKERS = ("'w'", '"w"', "'w+'", '"w+"', "'a'", '"a"',
                  "'r+'", '"r+"',
                  "write_text", ".write(", "writelines", "json.dump(",
                  "writeFileSync", "appendFileSync", "os.replace(", "shutil.copy")

# The length at which a command stops being SCANNED and starts being DENIED.
#
# `interpreter_write` runs shlex over the command, and shlex is quadratic in the
# length of a single token. Measured end to end through main() on this machine:
# 24 KB 0.19 s, 97 KB 0.79 s, 195 KB 3.13 s, 390 KB 9.72 s. Four times the time
# for twice the size, so the 60 s harness default is reachable near 1 MB, and
# the path is entered by the two characters `-c` anywhere in the command,
# before any host or needle test. The header used to argue that no `timeout` is
# safer than `timeout: 5` because a KILLED hook writes no stdout and empty
# stdout reads as ALLOW. That is true, and it is NOT what bounds this: with any
# timeout the adversary needs a BIGGER payload, never a different technique, so
# the timeout only sets the size. The honest fix turns the kill into a deny.
#
# 64 KB, measured against real traffic rather than picked: 17,232 Bash tool
# calls from this machine's transcripts, largest 32,359 bytes, p99 5,145,
# p99.9 13,845, and ZERO over 64 KB. Past the cap, a command carrying an
# interpreter body or a heredoc is denied and told why; a command past the cap
# carrying neither is left alone, because this layer would not have read it.
#
# LEXING ONLY THE `-c` SEGMENT WAS TRIED AND DOES NOT HELP, measured rather than
# assumed, which is why the cap is the whole fix and not half of it. shlex is
# quadratic in the length of ONE TOKEN, and in this attack the payload IS that
# token, so pulling a single token from an offset costs the same as splitting
# the command: at 195 KB, shlex.split 1.56 s against one-token-from-offset
# 1.83 s. Narrowing the entry (a real fix, kept: the host is checked before the
# body is read) changes which commands reach the lexer, never what the lexer
# costs once one does.
_MAX_SCANNED = 64 * 1024

# THE SECOND CEILING, and it exists because the first fix was half of one.
#
# Letting an oversize command fall through to the path and tree layers closed
# the one-character bypass, and it handed the parser an unbounded string. The
# shared parser shlexes too, and shlex is quadratic in one token there as well.
# Measured on this machine, whole process, worst of the shapes, under load:
#
#     command size   this gate    the sibling Bash tree-owner gate
#     400 KB          14.2 s        8.5 s
#       1 MB          67.2 s      107.6 s
#
# Past the harness's 60 s default both are KILLED, a killed hook writes no
# stdout, and empty stdout reads as ALLOW. That is the exact failure the first
# cap was invented to remove, moved one layer down: a bigger payload, never a
# different technique. (The sibling gate has the same exposure today and it is
# not this branch's to fix; it is named so the number is not read as new.)
#
# So the parse is bounded too, and above the bound the answer is EXACT rather
# than heuristic. The shared parser's first line is `if not any(t in command for
# t in _TRIGGERS): return []`, and every local layer here has the same kind of
# substring fast-out. So above the ceiling:
#   - no trigger anywhere in the string -> every layer would have returned [],
#     so ALLOW is what the parse would have said, computed in one pass;
#   - a trigger present -> there MIGHT be a target and the string is too long to
#     find out, and this gate resolves ambiguity closed, so DENY.
# The trigger list is BORROWED from the parser rather than copied, so it cannot
# drift away from the fast-out it is standing in for.
#
# 128 KB, picked against the same corpus as the first cap: 18,154 distinct real
# Bash commands, largest 32,359 bytes, so the ceiling is four times the largest
# thing this machine has ever run.
#
# It was 256 KB for one commit and the number had to MOVE when a layer was added
# to the fall-through, which is the point of measuring it rather than picking it.
# At 256 KB the worst case still parsed measured 3.65 s; adding the indirection
# reader, which lexes the raw command a second time, took the same shape to
# 8.91 s. Both are under the 60 s kill, but the earlier timings on a LOADED
# machine ran 3-4x the idle ones, and 8.91 s idle is not a margin at that
# multiple. Halving the ceiling quarters the cost (shlex is quadratic in one
# token), which puts the worst case back near 2 s idle. A cap whose cost is not
# re-measured when a reader is added is a cap that expires quietly.
_MAX_PARSED = 128 * 1024

# THE SECOND AXIS, and the one the byte caps above cannot see.
#
# Both caps measure LENGTH. The work in the target loop grows with TOKEN COUNT,
# and a byte budget buys very different amounts of it depending on shape.
# Measured through main() on this machine, both commands a few bytes under the
# 128 KB cap and both ending in the same protected path:
#
#     rm -f <one 131 KB word> ~/.claude/settings.json        1.8 s
#     rm -f <65,512 short tokens> ~/.claude/settings.json    18.5 s
#
# The header used to quote the first number as "the worst case still PARSED".
# It is the cheap shape. Profiled, the expensive one is not shlex at all: it is
# 65,512 passes through `hit` -> `classify` -> `realpath`, one per target, each
# walking lstat calls. A byte cap cannot bound that, so this one counts the
# thing that grows: DISTINCT resolvable targets.
#
# Overflow denies, for the same reason the parse ceiling denies: the alternative
# is a hook that runs past the harness's 60 s default, gets killed, writes empty
# stdout, and is read as ALLOW. QA measured that concurrently at x8 on a loaded
# box: 38.8 to 50.9 s for a single command, against a 60 s kill, on a machine
# that idles at load 20 on 4 cores. The command that gets killed and therefore
# allowed is a real disarm (`rm -f <junk> ~/.claude/settings.json`).
#
# 512, measured against real traffic rather than picked: see the corpus figure
# in the header. Repeats are free (`hit` is memoised), so this is a ceiling on
# how many DIFFERENT paths one command may name, not on how many arguments it
# carries.
_MAX_TARGETS = 512
_LOCAL_TRIGGERS = ("&>", ">|", "config", "--no-verify")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def journal_deny(pid, fields: dict) -> None:
    try:
        rec = {"kind": "deny", "rule": RULE_ID, "gate": "arming-surface"}
        rec.update(fields)
        kernel_proc.append(pid, rec)
    except Exception:
        pass


# THE INVARIANTS ARE COMPUTED ONCE PER PROCESS, and that is a correctness fix
# dressed as a performance one. `brain_root()` walks `kernel_proc.brain_dir()`
# plus `norm_path` (expanduser + abspath + normpath) and it was called TWICE PER
# TARGET; `scripts_dir()` once more; `classify` rebuilt the whole `_EXACT` table
# with `os.path.join` for every target. Profiled on the shape that QA measured
# (`rm -f <65,512 junk targets> ~/.claude/settings.json`, 131 KB): 131,023 calls
# to brain_root, 65,511 to scripts_dir, 982,672 joins, 25.7 M function calls and
# 98 s under cProfile. None of it depends on the target. HOME cannot change
# inside a hook process, so all of it is resolved once.
_CACHE = {}


def brain_root() -> str:
    got = _CACHE.get("brain")
    if got is None:
        got = _CACHE["brain"] = kernel_proc.norm_path(kernel_proc.brain_dir())
    return got


def scripts_dir() -> str:
    got = _CACHE.get("scripts")
    if got is None:
        got = _CACHE["scripts"] = os.path.join(brain_root(), "scripts")
    return got


def exact_live() -> list:
    """[(live path, why)] for `_EXACT`, joined once instead of per target."""
    got = _CACHE.get("exact")
    if got is None:
        brain = brain_root()
        got = _CACHE["exact"] = [
            (rel, os.path.join(brain, *rel.split("/")), why)
            for rel, why in _EXACT.items()]
    return got


def user_config_path(brain: str) -> str:
    """`~/.claude.json`, derived from the brain root so a sandboxed HOME (every
    selftest leg) resolves its own instead of the real one."""
    return os.path.join(os.path.dirname(brain), _USER_CONFIG_NAME)


def _is_gate_script(basename: str) -> bool:
    return any(fnmatch.fnmatchcase(_fold(basename), p) for p in _SCRIPT_PATTERNS)


def project_scope(target: str, brain: str, removing: bool) -> tuple:
    """(live_path, why) when `target` is project-scope settings INSIDE the live
    root, else (None, None). Pure string work for the FILE shape, no stat and no
    listing, so it costs nothing on the hot path.

    Only paths strictly under the live root are tested here. The root itself
    and any ancestor of it are already a hit through _EXACT (a target that
    contains ~/.claude contains ~/.claude/settings.json), so they never reach
    this and never need a second answer.
    """
    if not _fold(target).startswith(_fold(brain) + os.sep):
        return None, None
    parts = [_fold(p) for p in target[len(brain) + 1:].split(os.sep)]
    if not parts or not parts[0]:
        return None, None
    if len(parts) >= 2 and parts[-2] == _PROJECT_DIRNAME and \
            fnmatch.fnmatchcase(parts[-1], _PROJECT_SETTINGS_GLOB):
        return target, _PROJECT_WHY
    if parts[-1] == _PROJECT_DIRNAME and _holds_settings(target, removing):
        return target, _PROJECT_DIR_WHY
    return None, None


# ONE list of PROGRAMS that make a path go away, and every other place that
# needs to know "does this remove?" is derived from it. There were two: this
# tuple, and a second literal `("rm", "unlink", "shred")` inside the `find`
# label check. Two lists of the same fact is one list too many, and it showed:
# `shred` was in one and not the other, so a hit labelled `shred` and a
# `find -exec shred` disagreed about the same program.
_REMOVING_PROGRAMS = ("rm", "unlink", "shred")

# Verbs that only ever make a path GO AWAY. Everything else names, at its
# destination, the file that will EXIST once the command has run, which is the
# distinction `_holds_settings` turns on below. The program names come from the
# list above; `find -delete` and `git rm` are LABELS the parser emits for the
# same effect, not programs, which is why they are added rather than listed.
_REMOVING_VERBS = _REMOVING_PROGRAMS + ("find -delete", "git rm")


def _holds_settings(directory: str, removing: bool) -> bool:
    """True when a `.claude` directory is worth protecting from THIS verb.

    ONE QUESTION PER VERB, because "what does it hold?" is only the right
    question for a verb that TAKES something.

    A REMOVING verb (rm, unlink, find -delete, git rm) takes what is there, so
    the listing answers it exactly. The live tree carries eight `.claude`
    directories that hold no settings at all (vendored reference checkouts under
    knowledge/, the `home/.claude` fixture roots), and denying housekeeping on
    those buys nothing: a directory with no settings disarms nothing by being
    deleted. They stay removable, measured, all eight.

    EVERY OTHER VERB puts something there, so what the directory holds NOW says
    nothing about what it will hold, and the whole question is wrong. Two doors
    were open because it was asked anyway, and both are closed by not asking:

      the ABSENT one, the merge blocker, reproduced five ways by QA:
        ALLOW  Write <live>/stage/settings.json  {"env":{"OCTO_MERGE_APPROVE":"*"}}
        ALLOW  mv <live>/stage <live>/x/.claude
      the EXISTING-BUT-EMPTY one, found by re-testing the fix against the real
      tree, and the reason this is a verb rule rather than an absence rule:
        ALLOW  cp /tmp/settings.json <live>/knowledge/…/ECC/.claude/
      the eight empty directories were a drop box, and the deny that fires on
      the file (`…/.claude/settings.json`) never sees a command that only names
      the directory.

    The header sentence that used to cover all of this, "creating an empty
    `.claude` is allowed, and the FILE rule denies putting settings into it, so
    the line is held by the file test either way", is FALSE for both: the file
    rule only ever sees file targets, and neither command names a file.

    Cost, measured rather than argued: 17,232 real Bash calls from this
    machine's transcripts contain ONE that aims mv/cp/tee/install/ln at a nested
    `.claude` under the live root, and it is a line testing this gate. `mkdir`
    is not a mutator and never reaches here, so creating one stays free, and
    `rm -rf` on an empty one stays allowed. What is now denied that was not:
    moving an empty `.claude` somewhere else, which `rm` still does.

    Unreadable counts as TRUE. A directory of exactly this shape that cannot be
    listed is the ambiguous case, and this gate resolves ambiguity closed. One
    listdir, reached only for a REMOVING verb and only after the fast-out has
    proven the path is inside the live root, so an ordinary command never pays
    it.
    """
    if not removing:
        return True               # the verb writes: the directory IS the target
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return False              # nothing there to take
    except OSError:
        return True
    return any(fnmatch.fnmatchcase(_fold(n), _PROJECT_SETTINGS_GLOB) for n in names)


# A FIXTURE IS PROTECTED FROM A WRITE, NOT FROM A RESTORE OR A REMOVAL, and the
# number that forced the distinction was mine. Adding `registry/fixtures` to the
# set was reported last cycle as costing ONE real command, from a replay that
# only exercised the put, redirect and git-config layers and therefore never saw
# the route those commands actually use. Replayed properly over 18,154 distinct
# real Bash calls it costs ELEVEN, and every one of them is this brain's own
# fixture maintenance: `cd ~/.claude && git checkout -- registry/fixtures/<rule>/
# home/...` restoring fixture state that a selftest mutated, `rm -rf` of a
# fixture's home directory, and a `cp -r` out of one. A gate that blocks its own
# maintenance is the failure this whole boundary was drawn around.
#
# The threat is narrower than the file: a violation fixture rewritten so it still
# BLOCKS but tests nothing leaves gate-liveness green while the gate guards
# nothing. That needs new content. It cannot be done by
#   - a RESTORE (`git checkout -- <fixture>` puts back the committed bytes, which
#     are the ones review approved, but only with NO REF named; a
#     `checkout <ref> --` or `restore --source=<ref>` is relabelled and denied),
#     nor by
#   - a REMOVAL (a missing fixture makes `--selftest` fail LOUDLY: the run reports
#     "did NOT block" or "fixture dir missing" and the doctor goes red).
# So those two verbs pass and every write is denied.
#
# Residual, measured and named rather than left implied: `git checkout
# <other-branch> -- registry/fixtures/<rule>/violation_x.json` restores from a
# ref that is NOT the committed state of this branch and is allowed by this test.
# Closing it means reading the ref out of the command, which is the shared
# parser's job, not a second reader here.
_RESTORE_VERBS = ("git checkout", "git restore")


def _fixture_write(verb: str) -> bool:
    """True when *verb* puts NEW content into a fixture.

    Matched EXACTLY, not by prefix: main() relabels a restore that names a ref
    as `git checkout <ref>`, and a prefix test would have exempted it."""
    if verb in _REMOVING_VERBS:
        return False
    return verb not in _RESTORE_VERBS


# A PATH THE SHELL HAS TO EXPAND IS UNKNOWABLE, and it has to read that way in
# BOTH directions or it is not a rule, it is a coin flip. The residual list has
# always said `$VAR` is unknowable, and that was honoured for the BYPASS
# (`rm -rf "$HOME/.claude/scripts"` allows, because the token resolves to
# `<cwd>/$HOME/...` and matches nothing) and NOT for the over-fire: the same
# unexpanded token resolved against a live cwd produced a deny, so
# `cd "$SP/demo" && git checkout -q master` was denied inside ~/.claude. Six
# false denies in a 21,653-row sweep came from exactly that. One reading was
# imposed: a resolved path still carrying a `$` was never a real path, so it is
# not a hit.
#
# THAT ONE READING CLOSED THE WRONG MEMBER OF THE CLASS, and the member it left
# open is the most common one. `$HOME` is not unknowable: it is defined in this
# hook's own `os.environ`, it names the very tree this gate protects, and `~` is
# ALREADY expanded on the way to a path, so the two spellings of one file
# disagreed. Measured on the live gate, `rm -f ~/.claude/settings.json` denied
# and all four of `rm -f $HOME/.claude/settings.json`,
# `rm -f ${HOME}/.claude/settings.json`, `cd $HOME/.claude && rm -f
# settings.json` and `cp /tmp/x $HOME/.claude/hooks.json` allowed. `$HOME/...`
# is how a person or an agent writes that path in a script.
#
# So the resolution moved one layer down, to `kernel_proc.expand_env`, which
# every path layer here already reaches through the shared parser's `resolve`:
# a variable this process can READ resolves, a variable it cannot keeps its `$`
# and keeps the unknowable reading below. No list of variable names, anywhere:
# `os.environ` is the list, and it is the same one the shell will use.
# `$SOMEDIR`, `$(cmd)` and a backtick still abstain, which is why the over-fire
# this test was added for (`cd "$SP/demo" && git checkout -q master`) stays
# allowed. The two readers below take raw TOKENS, never resolved paths, so they
# expand for themselves before asking.
_UNEXPANDED = ("$", "`")


def cwd_unknowable(command: str) -> bool:
    """True when the command `cd`s somewhere the shell has to expand.

    The path test above is not enough for the TREE layer, and the reason is
    worth stating: `cd "$SP/demo"` resolves to `<live>/$SP/demo`, whose
    components do not exist, so `enclosing_worktree_root` CLIMBS OUT of them and
    reports the live root. The command was then judged as a whole-tree verb
    inside ~/.claude when nobody knows where it ran. An explicit literal `-C` or
    `--git-dir` still names the repo, so those keep deciding."""
    tokens = _lex(command)
    for i, tok in enumerate(tokens):
        if tok in ("cd", "pushd") and i + 1 < len(tokens):
            # the same expansion `resolve` does, so this reader and the path
            # readers cannot disagree about whether the destination is known
            if any(ch in kernel_proc.expand_env(tokens[i + 1])
                   for ch in _UNEXPANDED):
                return True
    return False


def names_literal_repo(command: str) -> bool:
    tokens = _lex(command)
    for i, tok in enumerate(tokens):
        name, eq, val = tok.partition("=")
        if name in ("-C", "--git-dir", "--work-tree"):
            val = val if eq else (tokens[i + 1] if i + 1 < len(tokens) else "")
            val = kernel_proc.expand_env(val)
            if val and not any(ch in val for ch in _UNEXPANDED):
                return True
    return False


def classify(target: str, removing: bool = False, verb: str = "") -> tuple:
    if target and any(ch in target for ch in _UNEXPANDED):
        return None, None
    """(live_path, why) when `target` reaches a live arming surface, else
    (None, None). Containment counts in BOTH directions: `rm -rf
    ~/.claude/scripts` never names a gate and takes every one of them."""
    if not target:
        return None, None
    brain = brain_root()
    cfg = user_config_path(brain)
    if _conflict(target, cfg):
        return cfg, _USER_CONFIG_WHY           # the one member outside the root
    if not _conflict(target, brain):
        return None, None                      # fast out: not in the brain
    for rel, live, why in exact_live():
        if _conflict(target, live):
            if rel == "registry/fixtures" and not _fixture_write(verb):
                continue          # a restore or a removal is not a doctored fixture
            return live, why
    live, why = project_scope(target, brain, removing)
    if live:
        return live, why
    sdir = scripts_dir()
    if _conflict(target, sdir):
        if _fold(target) == _fold(sdir) or _fold(sdir).startswith(_fold(target) + os.sep):
            # the target IS scripts/ or an ancestor of it: it takes every gate
            return sdir, _SCRIPT_WHY + ", all of them at once"
        if _is_gate_script(os.path.basename(target)):
            return target, _SCRIPT_WHY
    return None, None


def candidates(target: str) -> list:
    """The path as written and the path the file system actually reaches. A
    symlink under a worktree pointing at the live file is a path that LOOKS
    like development, so both spellings are tested."""
    out = []
    norm = kernel_proc.norm_path(target)
    if norm:
        out.append(norm)
        try:
            real = kernel_proc.norm_path(os.path.realpath(norm))
        except Exception:
            real = ""
        if real and real != norm:
            out.append(real)
    return out


_HIT_CACHE = {}
_GLOB_CACHE = {}


def hit(target: str, removing: bool = False, verb: str = "") -> tuple:
    """Memoised on the exact question asked.

    The same target appears many times in one command far more often than it
    appears once (`rm -f a a a … `, a glob the shell already expanded, a loop
    body), and each miss costs a `realpath`, which is a walk of lstat calls.
    The key carries `removing` and `verb` because both change the answer.

    WHAT NO FIXTURE CAN SEE: this changes cost, never a verdict, because the
    target budget in main() already counts DISTINCT targets. A reverted-fix
    anchor for it was written and then removed rather than left passing on
    another mechanism's behalf: it is verified by measurement instead (65,512
    identical targets, 18.5 s before and 2.42 s after)."""
    key = (target, removing, verb)
    got = _HIT_CACHE.get(key)
    if got is not None:
        return got
    out = (None, None)
    for cand in candidates(target):
        live, why = classify(cand, removing, verb)
        if live:
            out = (live, why)
            break
    if len(_HIT_CACHE) > 8192:
        _HIT_CACHE.clear()
    _HIT_CACHE[key] = out
    return out


# ── Bash side: one parser for the whole brain, borrowed not copied ───────────

class ParserUnavailable(Exception):
    """The shared command parser could not be LOADED. Distinct from a command
    it cannot read, and answered the opposite way; see `bash_targets`."""


_PARSER_PATH = os.path.join(_HERE, "g__pretool-bash__tree-owner.py")
_PARSER_MOD = None


def _parser():
    """Borrow the command scanner the Bash tree-owner gate already proves
    (g__pretool-bash__tree-owner.py:553). It resolves `cd`, `git -C`,
    `--work-tree`, redirects, subshells, wrappers and `-c` bodies, and it is
    boundary-aware, so `git commit -m "edit settings.json"` is one token to
    shlex and never becomes a target. A second copy would drift, and the drift
    would be invisible until a deny failed to fire. The whole module is kept,
    not just `scan`, because `glob_hits` and `git_parse` are borrowed too."""
    global _PARSER_MOD
    if _PARSER_MOD is None:
        import importlib.util
        try:
            spec = importlib.util.spec_from_file_location(
                "tree_owner_bash_borrow", _PARSER_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise ParserUnavailable(f"{type(exc).__name__}: {exc}") from exc
        _add_wrapper_rows(mod)
        _PARSER_MOD = mod
    return _PARSER_MOD


# Prefixes that run another program without changing what it does to the file
# system. The shared parser already owns THE list of them (`_WRAPPERS`) and
# already peels env, sudo, nice, timeout, xargs and the rest; these are the rows
# it does not carry yet, measured live against `rm -rf ~/.claude/scripts`:
#
#     env / nice / timeout / sudo / sh -c  -> already denied
#     setsid, setsid -w, flock, ionice, chrt, taskset, doas, busybox, parallel
#                                         -> ALLOWED, every one of them
#
# They are ADDED TO the shared dict with `setdefault`, not copied into a second
# table here. That matters for the reason this whole file borrows the parser
# instead of forking it: when the shared table grows its own row for `busybox`
# (it already has on `fix/kernel-corrupt-row`), `setdefault` keeps the parser's
# row and this one becomes a no-op, so the two can never drift into disagreeing.
# The mutation is per PROCESS: every hook is its own interpreter, so nothing
# else in the session sees it.
#
# A wrong spec here costs a MISS, never a false deny: peeling too little leaves
# the wrapper name as the program, peeling too much leaves a path, and neither
# is a mutation verb. `taskset 0x3 rm` is exactly that miss (the bare mask form
# is a positional and `arg: 0` does not skip it), kept over `arg: 1` because
# `taskset -c 0 rm` is the spelling that appears and the two cannot both work.
_EXTRA_WRAPPERS = {
    "setsid": {"valued": (), "cd": (), "arg": 0},
    "ionice": {"valued": ("-c", "--class", "-n", "--classdata", "-p", "--pid"),
               "cd": (), "arg": 0},
    "flock": {"valued": ("-w", "--wait", "--timeout", "-E",
                         "--conflict-exit-code"), "cd": (), "arg": 1},
    "chrt": {"valued": ("-p", "--pid"), "cd": (), "arg": 1},
    "taskset": {"valued": ("-c", "--cpu-list", "-p", "--pid"), "cd": (), "arg": 0},
    "doas": {"valued": ("-u", "-C"), "cd": (), "arg": 0},
    "parallel": {"valued": ("-j", "--jobs", "-N", "--delimiter", "-d",
                            "--colsep", "-S", "--sshlogin", "-a", "--arg-file"),
                 "cd": (), "arg": 0},
    "busybox": {"valued": (), "cd": (), "arg": 0},
    "toybox": {"valued": (), "cd": (), "arg": 0},
    "strace": {"valued": ("-o", "-e", "-p", "-s", "-E", "-u", "-P", "-a", "-b",
                          "-I", "-O", "-S"), "cd": (), "arg": 0},
    "ltrace": {"valued": ("-o", "-e", "-p", "-s", "-l", "-u", "-a", "-n"),
               "cd": (), "arg": 0},
    "systemd-run": {"valued": ("--unit", "-u", "--property", "-p", "--slice",
                               "--description", "--on-calendar", "--uid",
                               "--gid", "--setenv", "-E", "-M", "--machine",
                               "--working-directory", "-d"),
                    "cd": ("--working-directory",), "arg": 0},
}

# `flock <lockfile> -c '<cmd>'` and `script -c '<cmd>' <file>` hand a SHELL
# COMMAND LINE to `-c`, exactly as `sh -c` does, and both were measured ALLOW
# against `rm -rf ~/.claude/scripts`. They are read here rather than added to
# `_C_HOSTS` because `_host_of` walks back from the `-c` to the first non-flag
# token, and flock puts its LOCK FILE there, so the host it finds is a path.
_CMD_STRING_HOSTS = ("flock", "script")


def _cmd_string_bodies(stage: list) -> list:
    if not stage or os.path.basename(stage[0]) not in _CMD_STRING_HOSTS:
        return []
    out = []
    for i, tok in enumerate(stage):
        if tok == "-c" and i + 1 < len(stage):
            out.append(stage[i + 1])
    return out


def _add_wrapper_rows(mod) -> None:
    for name, spec in _EXTRA_WRAPPERS.items():
        mod._WRAPPERS.setdefault(name, spec)


# `~/.claude/./settings.json` is the same file as `~/.claude/settings.json` and
# was a clean bypass of every literal test below, because a needle is a STRING
# and that string is one character longer. `/./` and `//` are the only two
# spellings that survive a shell verbatim and still name the same path, so the
# body is normalized once before any needle is looked for. It runs over the
# BODY, not the command, so it never changes what the shared parser sees.
_PATH_NOISE = re.compile(r"/(?:\.?/)+")
_PATH_UP = re.compile(r"/[^/]+/\.\./")


def _normalize_paths(text: str) -> str:
    """Collapse the spellings that name the same file without a variable.

    `/./` and `//` were folded; `/../` was NOT, so
    `open('~/.claude/scripts/../settings.json','w')` was a literal bypass of
    every needle with no variable and no unusual idiom in it, which put it
    outside the stated variable-expansion residual. The up-level pass runs to a
    fixed point (bounded), because `a/b/../../c` needs two rounds."""
    text = _PATH_NOISE.sub("/", text or "")
    for _ in range(8):
        folded = _PATH_UP.sub("/", text)
        if folded == text:
            break
        text = folded
    return text


def _needles() -> list:
    """Literal spellings of a protected path an interpreter body could carry.

    EVERY protected file, not four of them. This used to be built from `_EXACT`
    plus the project-scope pair, which left the GATE BODIES out entirely: QA
    measured `python3 -c "open('<live>/scripts/qa-merge-gate.py','w')"` and its
    heredoc twin as ALLOW, and the same for `brain_doctor.py`. The
    concrete-path list the glob test already uses (`_protected_pairs`) holds
    every one of them, so the two layers now read the same set instead of two
    different ones, and a gate script added to the live tree is a needle the
    moment it exists.

    The project-scope pair is named at the one root that is always there (the
    brain root itself, the root `cd ~/.claude` opens); a deeper project root
    inside the live tree is covered by the classifier for Write/Edit and shell
    mutations, and stays a named residual for these best-effort literal layers.
    """
    brain = brain_root()
    out = []
    for path, _why in _protected_pairs(brain):
        out.append(path)
        if _fold(path).startswith(_fold(brain) + os.sep):
            rel = os.path.relpath(path, brain).replace(os.sep, "/")
            out.append("~/.claude/" + rel)
    out.append("~/" + _USER_CONFIG_NAME)
    return out


def _needle_marker(body: str, needles: list):
    """(literal, marker) when a `-c` body writes a protected path.

    This is the LOOSE test and it belongs to the `-c` channel alone. It was
    tried on heredoc bodies and measured unshippable there; `heredoc_write`
    carries the narrow one, with the measurement that separated them."""
    marker = next((m for m in _WRITE_MARKERS if m in body), None)
    if not marker:
        return None
    flat = _normalize_paths(body)
    for needle in needles:
        if needle in flat:
            return needle, marker
    return None


def _is_c_host(base: str) -> bool:
    """`python3.12 -c` used to pass: `rstrip("0123456789")` leaves `python3.`,
    with the dot, and no entry in the table carries one. A version suffix is
    digits AND dots."""
    if not base:
        return False
    return base in _C_HOSTS or base.rstrip("0123456789.") in _C_HOSTS


def _host_of(tokens: list, i: int) -> str:
    """The program a `-c` at index *i* belongs to, walking BACK past its own
    flags. `tokens[i - 1]` alone missed `python3 -u -c` and `python3 -I -c`,
    both ordinary spellings and both measured ALLOW before this."""
    j = i - 1
    while j >= 0 and tokens[j].startswith("-") and tokens[j] != "--":
        j -= 1
    return os.path.basename(tokens[j]) if j >= 0 else ""


# TOKEN-level `-c`, used only once a token list exists.
_BUNDLED_C = re.compile(r"-[A-Za-z]*c")

# COMMAND-level "does this string carry an interpreter body at all?", which is a
# different question and was being answered with the token regex above matched
# anywhere in the string. Two costs, both measured by QA:
#   * `grep -c foo file` over the size cap was DENIED as "carries an interpreter
#     `-c` body". It carries a count flag.
#   * any path in the command containing `-<letters>c` shifted the verdict, so a
#     sandbox under `/tmp/x-carloscarrillo/...` answered differently from a
#     clean one. A fixture whose verdict depends on where the sandbox lives is
#     not a fixture.
# The fast test now asks the same question `_c_bodies` asks precisely: is there
# an INTERPRETER, then a run of its own flags, then a flag ending in `c`? That
# mirrors `_host_of`, which walks back past flags and stops at the first
# non-flag token, so the cheap test and the exact test cannot disagree about
# which commands have a body. The flag run is BOUNDED (at most 8 of at most 20
# characters) so the nested quantifier cannot backtrack quadratically on the
# 64 KB strings this is deliberately run against.
_C_CHANNEL = re.compile(
    r"""(?:^|[\s;&|(`"'])(?:[\w./-]*/)?"""
    r"""(?:bash|sh|zsh|dash|python[0-9.]*|py)"""
    r"""(?:\s+-[A-Za-z-]{1,20}){0,8}\s+-[A-Za-z]*c""")


def _c_bodies(tokens: list) -> list:
    """Every `-c` PROGRAM argument in a token list.

    Three spellings, all reachable and the last two measured ALLOW before this:
    `-c <body>`, a short-flag bundle ending in c (`sh -lc <body>`), and a FUSED
    `-c<body>` (`python3 -c'open(...)'`, which shlex hands back as one token).

    The bundle branch was written first and was DEAD, which is what a surviving
    mutant showed: `interpreter_write` fast-outs on `"-c" not in command`, and
    `sh -lc "…"` carries no literal `-c`, so the body was never reached. The
    fast-out is the same `_BUNDLED_C` regex now. A branch with no fixture is a
    claim; this one was a claim that was also false."""
    out = []
    for i, tok in enumerate(tokens):
        if tok == "-c" or _BUNDLED_C.fullmatch(tok):
            body = tokens[i + 1] if i + 1 < len(tokens) else None
        elif tok.startswith("-c") and len(tok) > 2 and not tok.startswith("--"):
            body = tok[2:]
        else:
            continue
        if body and _is_c_host(_host_of(tokens, i)):
            out.append(body)
    return out


def interpreter_write(command: str):
    """(literal, marker) when a `<interp> -c <body>` writes a protected path.

    Best-effort by construction and gated on a write marker: the same shape
    reading the same file is a real, frequent command (`python3 -c "json.load
    (open('~/.claude/hooks.json'))"`) and must pass."""
    import shlex
    # The fast-out has to know the bundle too: `sh -lc "…"` carries no literal
    # "-c", so the old substring test returned before the body was ever read.
    # It also has to know the HOST, or `grep -c` and any path spelled with a
    # `-…c` enter the lexer and change verdicts; `_C_CHANNEL` asks both.
    if not _C_CHANNEL.search(command):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    needles = _needles()
    for body in _c_bodies(tokens):
        found = _needle_marker(body, needles)
        if found:
            return found
    return None


# ── heredoc bodies: the dominant real idiom, and it was uncovered ────────────
#
# The residual said "an inline `-c` body is read; a script file passes". A
# heredoc body is INLINE, sits in the command string exactly as a `-c` argument
# does, and was read by nothing. Measured on this machine's own transcripts,
# 17,232 Bash tool calls: 2,424 feed a heredoc to an interpreter against 2,221
# carrying a host `-c`, so the uncovered channel was the MORE common one, and
# two real transcript commands rewrote a live settings file through it.
#
# MINIMAL, AND MARKED FOR REMOVAL. Checked rather than assumed before writing
# it: `grep -rn heredoc scripts/*.py` returns nothing on this branch, and
# `git grep _split_heredocs` across every ref hits only
# `fix/qa-gate-blanket-override`, which has not landed. So there is nothing to
# inherit yet and this is the SECOND reader, not a third. When that logic
# reaches the shared `scan()`, heredoc bodies arrive as ordinary segments and
# this block goes; nothing else here depends on it.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def heredoc_bodies(command: str) -> list:
    """Every heredoc BODY in the command.

    AN UNTERMINATED OPENER RUNS TO END OF INPUT, which is what bash does and
    what the previous version got backwards. It skipped such an opener entirely,
    on the reasoning that "a `<<` inside ordinary prose can never swallow the
    rest of the command". bash disagrees: it warns `here-document delimited by
    end-of-file` and RUNS the body anyway, so omitting the terminator line was a
    one-line way to hide a body from this reader while still executing it. The
    claim also had no fixture that could tell the two apart, which is what
    QA's surviving mutant M36 was pointing at: the benign fixture for it was a
    single line with no body at all, so it passed whatever this function did.

    The over-fire that reasoning was protecting against does not appear, because
    the reader downstream is the NARROW one: a body only matters when a
    protected path is the direct operand of a write in it. Prose that merely
    mentions `<< EOF` yields a body of whatever followed it, and the write test
    then finds nothing.

    Terminator positions are indexed once instead of rescanned per opener, so a
    line carrying many openers stays linear."""
    return heredoc_split(command)[1]


def heredoc_split(command: str) -> tuple:
    """(the SHELL text, the heredoc bodies).

    The two halves are separated because they answer different questions and
    mixing them cost a measured false positive. The shell text is what the
    machine RUNS: it is where an interpreter host counts. A body is DATA until
    an interpreter is handed it, so a `python3` that appears only inside a
    document proves nothing about the command. Measured on 18,154 distinct real
    Bash calls: reading the host out of the whole string made
    `cat > README-residuals.txt <<'EOF' … EOF` deny, because that document
    quotes `open('~/.claude/settings.json','w')` as an EXAMPLE and mentions
    `python3` in the same breath. That file is this gate's own residual list, so
    the widened test denied the gate's own documentation."""
    if "<<" not in command:
        return command, []
    lines = command.split("\n")
    at = {}
    for j, ln in enumerate(lines):
        at.setdefault(ln.strip(), []).append(j)
    bodies, shell, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        shell.append(line)
        i += 1
        for _quote, term in _HEREDOC_RE.findall(line):
            end = next((j for j in at.get(term, ()) if j >= i), None)
            if end is None:
                bodies.append("\n".join(lines[i:]))    # bash: runs to EOF
                i = len(lines)
                break
            bodies.append("\n".join(lines[i:end]))
            i = end + 1
    return "\n".join(shell), bodies


def _protected_pairs(brain: str) -> list:
    got = _CACHE.get("pairs")
    if got is None:
        got = _CACHE["pairs"] = _protected_pairs_uncached(brain)
    return got


def _protected_pairs_uncached(brain: str) -> list:
    """(path, why) for every CONCRETE protected file, for tests that need a
    path instead of a shape (the glob test below). The project-scope pair is
    named at the one root that is always there, the brain root itself, exactly
    as the interpreter needles are; a deeper project root stays covered by the
    shape classifier for literal targets."""
    pairs = [(user_config_path(brain), _USER_CONFIG_WHY)]
    for rel, why in _EXACT.items():
        pairs.append((os.path.join(brain, *rel.split("/")), why))
    for name in ("settings.json", "settings.local.json"):
        pairs.append((os.path.join(brain, _PROJECT_DIRNAME, name), _PROJECT_WHY))
    sdir = scripts_dir()
    try:
        names = os.listdir(sdir)
    except OSError:
        names = []
    for name in names:
        if _is_gate_script(name):
            pairs.append((os.path.join(sdir, name), _SCRIPT_WHY))
    return pairs


def glob_hit(pattern: str, icase: bool) -> tuple:
    """(live_path, why) when a GLOB reaches a protected path.

    The glob used to be collapsed to its literal directory (`os.path.dirname`),
    which threw the filter away and answered with the root alone. Measured, that
    was inconsistent in both directions: `find <live> -name '*.pyc' -delete`
    DENIED, and so would any `find <live> -name X -delete` whatever X was, while
    the `-path` spelling of the same command ALLOWED, because its pattern kept a
    leading `*` and the dirname landed outside the root. Worse, the collapse
    fired on commands that were not globs at all: `[` is a glob character, so
    `cd ~/.claude/scripts && python3 -c "... cp = bd._run_selftest_locator(
    mine[0][1]) ..."` reduced to the scripts directory and denied a READ-ONLY
    diagnostic, twice in the real corpus. The filter is the whole point of the
    command, so the filter is what decides: the pattern is matched
    against the protected paths with the shared parser's own `glob_hits`, the
    same helper the lane rule uses for the same question."""
    if not pattern:
        return None, None
    # MEMOISED, for the shape QA found that neither byte cap nor the target
    # budget could see: 64 KB of `find /tmp -name x -delete;` is 2,427 SEGMENTS
    # whose glob is the SAME string, and the budget counts distinct TARGETS, so
    # it deduped to one while the cost stayed per HIT. Each hit walked all 31
    # protected pairs, and that pair count is a LIVE quantity: it grows with
    # every gate script added under scripts/.
    key = (pattern, icase)
    got = _GLOB_CACHE.get(key)
    if got is not None:
        return got
    try:
        hits = _parser().glob_hits
    except ParserUnavailable:
        raise
    brain = brain_root()
    out = (None, None)
    for path, why in _protected_pairs(brain):
        try:
            if hits(pattern, path, icase):
                out = (path, why)
                break
        except Exception:
            continue
    if len(_GLOB_CACHE) > 4096:
        _GLOB_CACHE.clear()
    _GLOB_CACHE[key] = out
    return out


# Two whole-tree rewrites the shared parser does not name, both reproduced here
# as ALLOW before this: `git read-tree -u --reset <tree>` and
# `git checkout-index -a -f` overwrite every file in the working tree exactly as
# a branch switch does, so a file-by-file deny that let them through protects
# nothing. They are recognised HERE rather than in the shared parser because
# that parser carries the LANE rule and is under edit on another branch; the
# borrowed `git_parse` still does the `-C` / `--work-tree` resolution, so this
# is a verb table, not a second parser. When they land upstream this goes.
def _has_flag(rest: list, letter: str, long_name: str) -> bool:
    """A short letter, alone or bundled (`-af`), or its exact long spelling.
    The long names are matched EXACTLY rather than against a shared list, so
    `--all` cannot answer for `--force` the way a shared list let it."""
    for tok in rest:
        if tok.startswith("--"):
            if tok.split("=", 1)[0] == "--" + long_name:
                return True
            continue
        if tok.startswith("-") and letter in tok[1:]:
            return True
    return False


def _extra_tree_verb(sub: str, rest: list):
    # `read-tree` writes the WORKING TREE only with -u; without it the index
    # alone moves and no file here changes, so `git read-tree -m HEAD` passes.
    if sub == "read-tree" and _has_flag(rest, "u", "update"):
        return "git read-tree -u --reset" if "--reset" in rest else "git read-tree -u"
    # `checkout-index -a` writes every file in the index; `-f` lets it overwrite
    # the ones already there. `-a` alone still creates whatever is missing, so
    # the deny turns on -a and -f only sharpens it.
    if sub == "checkout-index" and _has_flag(rest, "a", "all"):
        return "git checkout-index -a"
    return None


# `git checkout -` is `@{-1}`, the previous branch, and it rewrites the working
# tree exactly as a named branch does. Measured: `checkout @{-1}` denied and
# `checkout -` allowed, because the shared parser's branch test does not read a
# bare dash as a ref.
def _dash_checkout(sub_cmd: str, rest: list) -> bool:
    if sub_cmd not in ("checkout", "switch"):
        return False
    for tok in rest:
        if tok == "--":
            return False
        if tok == "-":
            return True
    return False


# `git apply` was named as a residual and `am`, `cherry-pick` and `revert` were
# not, although all four write the working tree from content that is not in it.
_APPLYING_VERBS = ("am", "cherry-pick", "revert")

_EXTRA_TREE_NAMES = ("read-tree", "checkout-index", "am", "cherry-pick",
                     "revert")


def extra_tree_hits(command: str, cwd: str) -> list:
    """(root, verb) for the whole-tree git verbs the shared parser misses.

    A substring test comes first so this costs nothing on the hot path: without
    it every Bash command would pay a second shlex pass for two rare verbs."""
    import shlex
    if not any(name in command for name in _EXTRA_TREE_NAMES) and \
            not any(v in command for v in _BRANCH_VERBS):
        return []
    mod = _parser()
    out = []
    try:
        segments = mod._dim_helpers()[0](command or "")
    except Exception:
        segments = [command or ""]
    here = cwd
    for seg in segments:
        try:
            tokens = shlex.split(seg.strip().rstrip(";"))
        except ValueError:
            continue
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd") and len(tokens) > 1:
            here = mod.resolve(tokens[1], here)   # `cd ~/.claude && git read-tree`
            continue
        if os.path.basename(tokens[0]) != "git":
            continue
        parsed = mod.git_parse(tokens)
        if not parsed:
            continue
        repo, sub, rest = parsed
        verb = _extra_tree_verb(sub, rest)
        if not verb and sub in _APPLYING_VERBS:
            verb = f"git {sub}"
        if not verb and _dash_checkout(sub, rest):
            verb = f"git {sub} -"
        if not verb:
            continue
        base_dir = mod.resolve(repo, here) if repo else here
        root = kernel_proc.enclosing_worktree_root(base_dir) or base_dir
        out.append((root, verb))
    return out


# ── verbs that PUT a file where the last positional does not say ────────────
#
# MARKED FOR REMOVAL, exactly like `extra_tree_hits` above. The shared parser on
# `fix/kernel-corrupt-row` already carries `_copy_targets`, which reads
# `-t`/`--target-directory` for `cp`/`install`/`ln` under one destination rule.
# That branch has not landed, and this gate loads the parser that is IN THE LIVE
# TREE, so borrowing it today would mean borrowing a function that is not there.
# When it lands, the `-t` half of this block goes and the basename half moves
# with it; nothing else here depends on it.
#
# THREE THINGS THE DESTINATION RULE HAS TO KNOW, all three measured as ALLOW:
#
#   1. `-t` INVERTS the argument order. `cp -t <live> /tmp/settings.json` puts
#      the file in `<live>`, and the shared parser's `positional[-1:]` hands
#      back `/tmp/settings.json`, which is the SOURCE. So the one rule that
#      guards `cp` was reading the wrong end of the command, and QA has a real
#      bash receipt of the file landing in the live tree.
#   2. A DIRECTORY DESTINATION RECEIVES THE SOURCE'S BASENAME.
#      `cp -r /stage/.claude <live>/knowledge-ref/` never spells a protected
#      path and creates `<live>/knowledge-ref/.claude`, a project-scope settings
#      directory, one command later. The gate's own residual called covering
#      this "walking an arbitrary source tree"; it is not. It is
#      `os.path.join(dest, os.path.basename(src))`, a string, and the classifier
#      already answers that path.
#   3. SOME WRITERS ARE NOT MUTATION VERBS AT ALL. `install`, `ln -f`, `rsync`,
#      `curl -o`, `wget -O`, `tar -x -C`, `patch -o/-d` and `awk -i inplace`
#      each put a file somewhere the shared parser's `_MUTATORS` table never
#      looks. The header's traffic count already listed `install` and `ln` as
#      if they were covered; they were not, and now they are.
#
# ADDITIVE BY CONSTRUCTION. This yields EXTRA targets only; every path the
# shared parser already returns is still returned by it, so no verdict that was
# a deny becomes an allow here. What is newly denied is what the three cases
# above describe.
#
# NOT COVERED, and named rather than half-covered: `rsync --delete` (the shared
# parser's own residual), and any destination that only exists after the shell
# expands something (`{a,b}`, `$VAR`, `$(cmd)`, `eval`, a shell function, `$'…'`
# and a symlink created and used inside the same command). Those need a shell,
# not a table, which is the same line this gate already draws at the interpreter
# residual.
_PUT_INTO = ("-t", "--target-directory")

# Flags that take a SEPARATE value. Getting one wrong costs a MISS (a value read
# as a path that is not protected), never a false deny, because every candidate
# is still run through the classifier. Only `=`-form is assumed for flags whose
# argument is optional (`--backup`, `--reflink`, `--sparse`), which the
# `partition("=")` below already skips as a single token.
_PUT_VALUED = {
    "cp": ("-t", "--target-directory", "-S", "--suffix"),
    "mv": ("-t", "--target-directory", "-S", "--suffix"),
    "install": ("-t", "--target-directory", "-m", "--mode", "-o", "--owner",
                "-g", "--group", "-S", "--suffix", "-Z", "--context",
                "--strip-program"),
    "ln": ("-t", "--target-directory", "-S", "--suffix"),
    "awk": ("-i", "--include", "-f", "--file", "-v", "--assign",
            "-F", "--field-separator"),
    "rsync": ("-e", "--rsh", "--exclude", "--include", "--exclude-from",
              "--include-from", "--files-from", "--filter", "-f", "--chmod",
              "--chown", "--out-format", "--log-file", "--temp-dir", "-T",
              "--partial-dir", "--compare-dest", "--copy-dest", "--link-dest",
              "--backup-dir", "--suffix", "--port", "--timeout", "--bwlimit",
              "--max-size", "--min-size", "--block-size", "-B", "--modify-window"),
}
_COPY_VERBS = ("cp", "mv", "install", "ln", "rsync")


def _put_positional(base: str, args: list) -> list:
    valued = _PUT_VALUED.get(base, ())
    out, i = [], 0
    while i < len(args):
        tok = args[i]
        name, eq, _val = tok.partition("=")
        if name in valued:
            i += 1 if eq else 2
            continue
        if tok.startswith("-") and tok != "-":
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _flag_value(args: list, names: tuple):
    """The value of the first of *names* present, in either `-x v` or
    `--name=v` spelling."""
    for i, tok in enumerate(args):
        name, eq, val = tok.partition("=")
        if name in names:
            if eq:
                return val
            if i + 1 < len(args):
                return args[i + 1]
    return None


def _copy_destinations(base: str, args: list, here: str) -> list:
    """Every path this copy-shaped command WRITES, beyond the one the shared
    parser already names."""
    positional = _put_positional(base, args)
    if base == "install" and any(
            a == "--directory" or (a.startswith("-") and not a.startswith("--")
                                   and "d" in a[1:]) for a in args):
        # `install -d a b c` CREATES all three; none of them is a source
        return [_parser().resolve(a, here) for a in positional]
    into = _flag_value(args, _PUT_INTO)
    if into:
        dest, sources = into, positional
    elif len(positional) >= 2:
        dest, sources = positional[-1], positional[:-1]
    else:
        return []
    dest_abs = _parser().resolve(dest, here)
    out = [dest_abs]
    # A destination is a DIRECTORY when the command says so (`-t`), when it is
    # spelled with a trailing separator, when more than one source is being put
    # there, or when it simply is one on disk.
    is_dir = bool(into) or dest.endswith(("/", os.sep)) or len(sources) > 1 or \
        os.path.isdir(dest_abs)
    if is_dir:
        for src in sources:
            leaf = os.path.basename(src.rstrip("/").rstrip(os.sep))
            if leaf and leaf not in (".", ".."):
                out.append(os.path.join(dest_abs, leaf))
    return out


# One entry per verb: (name, the flags whose value is a destination, whether the
# verb needs another flag present before it writes anywhere).
_WRITER_FLAGS = (
    ("curl", ("-o", "--output"), None),
    ("wget", ("-O", "--output-document", "-P", "--directory-prefix"), None),
    ("tar", ("-C", "--directory"), ("x", "extract", "get")),
    ("patch", ("-o", "--output", "-d", "--directory"), None),
    ("unzip", ("-d",), None),
    ("cpio", ("-D", "--directory"), None),
)
# THE POLARITY, stated because it decides how to read every list in this file:
# this gate has NO ALLOW-LIST. It is a DENY-LIST of recognised writer and remover
# verbs, so anything the shared parser and these tables do not recognise passes
# SILENTLY. The residuals list is therefore not a footnote, it is the only thing
# standing between a reader and a false sense of coverage, and it was missing
# these six, every one of them present on this machine and measured as ALLOW
# against a live protected file:
#
#   gzip ~/.claude/settings.json                 deletes its input
#   bzip2 / xz / lzma ~/.claude/settings.json    the same
#   zstd --rm ~/.claude/settings.json            the same, opt-in
#   tar --remove-files -cf /tmp/x.tar <file>     the same, opt-in
#   zip -qm /tmp/x.zip <file>                    the same, opt-in
#   sort -o <file> /tmp/evil                     writes its target
#   uniq /tmp/evil <file>                        writes its second positional
#
# The compressors are the sharp ones: they need no flag at all. `gzip
# ~/.claude/settings.json` leaves a `.gz` and removes the original, which is a
# removal of an arming surface spelled as a housekeeping command.
_CONSUMING = {
    # program: (flags that KEEP the input, whether removal is opt-in)
    "gzip": (("-c", "--stdout", "--to-stdout", "-k", "--keep", "-l", "--list",
              "-t", "--test", "-d", "--decompress"), False),
    "bzip2": (("-c", "--stdout", "-k", "--keep", "-t", "--test",
               "-d", "--decompress"), False),
    "xz": (("-c", "--stdout", "-k", "--keep", "-l", "--list", "-t", "--test",
            "-d", "--decompress"), False),
    "lzma": (("-c", "--stdout", "-k", "--keep", "-d", "--decompress"), False),
    "compress": (("-c", "--stdout"), False),
    "zstd": (("--rm",), True),
}
_CONSUMING_VALUED = ("-S", "--suffix", "-b", "--blocksize", "-T", "--threads",
                     "-o", "--output", "-M", "--memory")


def _consuming_targets(base: str, args: list, here: str) -> list:
    spec = _CONSUMING.get(base)
    if spec is None:
        return []
    keep_flags, opt_in = spec
    flags = {a.split("=", 1)[0] for a in args if a.startswith("-")}
    short = "".join(a[1:] for a in args
                    if a.startswith("-") and not a.startswith("--"))
    def present(f):
        return f in flags or (len(f) == 2 and f.startswith("-") and f[1] in short)
    if opt_in:
        if not any(present(f) for f in keep_flags):
            return []
    elif any(present(f) for f in keep_flags):
        return []
    out = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.split("=", 1)[0] in _CONSUMING_VALUED:
            i += 2 if "=" not in tok else 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        out.append(_parser().resolve(tok, here))
        i += 1
    return out


# `tar --remove-files` and `zip -m` delete what they archived; `sort -o` and
# `uniq <in> <out>` overwrite their target.
_ARCHIVE_VALUED = ("-f", "--file", "-C", "--directory", "-b", "--blocking-factor",
                   "-T", "--files-from", "-X", "--exclude-from")


_ARCHIVE_REMOVERS = ("tar", "zip", "rsync")
_OVERWRITERS = ("sort", "uniq")
_PERMISSION_VERBS = ("chmod", "setfacl", "chown", "chgrp")


def _archive_removes(base: str, args: list, here: str) -> list:
    if base not in _ARCHIVE_REMOVERS:
        return []
    if base == "rsync":
        if not any(a == "--remove-source-files" for a in args):
            return []
        pos = _put_positional("rsync", args)
        return [_parser().resolve(a, here) for a in pos[:-1]]
    if base == "tar":
        if not any(a == "--remove-files" for a in args):
            return []
        skip_first = False
    elif base == "zip":
        short = "".join(a[1:] for a in args
                        if a.startswith("-") and not a.startswith("--"))
        if "m" not in short and "--move" not in args:
            return []
        skip_first = True            # the first positional is the archive
    else:
        return []
    out, i, seen = [], 0, 0
    while i < len(args):
        tok = args[i]
        if tok.split("=", 1)[0] in _ARCHIVE_VALUED:
            i += 2 if "=" not in tok else 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        seen += 1
        if not (skip_first and seen == 1):
            out.append(_parser().resolve(tok, here))
        i += 1
    return out


def _overwriting_targets(base: str, args: list, here: str) -> list:
    if base not in _OVERWRITERS:
        return []
    if base == "sort":
        val = _flag_value(args, ("-o", "--output"))
        return [_parser().resolve(val, here)] if val else []
    if base == "uniq":
        val = _flag_value(args, ("-o", "--output"))   # some builds accept it
        if val:
            return [_parser().resolve(val, here)]
        pos = [a for a in args if not a.startswith("-")]
        # `uniq [INPUT [OUTPUT]]`: the SECOND positional is written
        return [_parser().resolve(pos[1], here)] if len(pos) >= 2 else []
    return []


# `chmod -x <file>` clears the execute bit, which is enough for git to skip a
# hook: it is a one-command kill of .githooks/pre-push. The shared parser reads
# `chmod`'s MODE as the first positional and drops it (`positional[1:]`), so a
# symbolic mode that starts with `-` was consumed as a FLAG and the file became
# the mode. Measured, and the split matters because it is what the fixtures can
# prove: `chmod 000 <pre-push>` and `chmod a-x <pre-push>` were ALREADY denied
# (their mode is a positional, so the shared parser handles them); `chmod -x`
# and `chmod -R -x` were ALLOWED and are what this reader adds.
_CHMOD_MODE = re.compile(r"^[-+=][rwxXstugoa]+$|^[ugoa]*[-+=][rwxXstugoa]*$")
_CHMOD_FLAGS = ("-R", "--recursive", "-v", "--verbose", "-c", "--changes",
                "-f", "--silent", "--quiet", "--no-preserve-root",
                "--preserve-root", "-H", "-L", "-P")


def _chmod_targets(args: list, here: str) -> list:
    out, mode_seen = [], False
    i = 0
    while i < len(args):
        tok = args[i]
        i += 1
        if tok.split("=", 1)[0] == "--reference":
            if "=" not in tok:
                i += 1
            mode_seen = True
            continue
        if tok in _CHMOD_FLAGS:
            continue
        if not mode_seen and (_CHMOD_MODE.match(tok) or tok.isdigit()):
            mode_seen = True
            continue
        if tok.startswith("-"):
            continue
        out.append(_parser().resolve(tok, here))
    return out


# ONE TABLE for the simple shapes, so the next member is a row and not a new
# function. Every entry answers the same three questions: which flags take a
# VALUE, where the target is (the positionals, or the value of a DEST flag), and
# whether the program writes unconditionally or only with an opt-in flag.
#
# QA named seven of these; probing the same class found three more (`chown`,
# `chgrp`, `split`), which is the point of the row shape: the twelfth member
# cost a line instead of a function. Every one was measured ALLOW against a live
# protected file before this table.
#
#   fallocate -z -l 4096 <settings>     zeroes the content in place
#   ex -sc wq <settings> / ed -s / vim -c wq    scriptable editor rewrite
#   openssl enc -out <settings> ...     writes its -out
#   gpg -o <settings> ...               writes its -o
#   unzip -o evil.zip -d <scripts>      overwrites gate bodies wholesale
#   cpio -id -D <claude dir>            the same, other archiver
#   setfacl -m u:nobody:0 <pre-push>    the chmod class, other syscall
#   chown / chgrp <pre-push>            the same class again
#   split -b1 /tmp/e <scripts>/qa-merge-gate.py   writes its output prefix
#
# EDITORS ARE OPT-IN, deliberately: a bare `vim <file>` is an interactive
# session a hook has no business denying, so only a SCRIPTED one counts
# (`-c`, `--cmd`, `-S`, `-s`, or a `+cmd` token). That is a residual with a
# reason, not an omission.
_SIMPLE_WRITERS = {
    "fallocate": {"valued": ("-l", "--length", "-o", "--offset"), "dest": (),
                  "require": (), "skip_first": 0, "last_only": False},
    # EDITORS ARE ALWAYS WRITERS NOW, a reversal recorded rather than quietly
    # made. The opt-in ("only a SCRIPTED editor counts, an interactive session is
    # not a hook's business") left `ed <file> < script.ed` open, because the
    # script arrives on STDIN with no flag to see. The reasoning behind the
    # opt-in was also weak on its own terms: a PreToolUse hook only ever sees an
    # AGENT's tool call, never the operator's terminal, so there is no
    # interactive session to protect here, exactly as with `~/.claude.json`.
    "ex":   {"valued": ("-c", "--cmd", "-S"), "dest": (), "require": (),
             "skip_first": 0, "last_only": False},
    "ed":   {"valued": (), "dest": (), "require": (),
             "skip_first": 0, "last_only": False},
    "vim":  {"valued": ("-c", "--cmd", "-S", "-s", "-u", "-i"), "dest": (),
             "require": (), "skip_first": 0, "last_only": False},
    "vi":   {"valued": ("-c", "--cmd", "-S", "-s"), "dest": (),
             "require": (), "skip_first": 0, "last_only": False},
    "nvim": {"valued": ("-c", "--cmd", "-S", "-s", "-u", "-i"), "dest": (),
             "require": (), "skip_first": 0, "last_only": False},
    "openssl": {"valued": ("-in", "-kfile", "-k", "-K", "-iv", "-pass",
                           "-md", "-S", "-p"),
                "dest": ("-out", "-keyout"), "require": (), "skip_first": 0,
                "last_only": False},
    "gpg":  {"valued": ("-r", "--recipient", "-u", "--local-user",
                        "--passphrase", "--homedir"),
             "dest": ("-o", "--output"), "require": (), "skip_first": 0,
             "last_only": False},
    # `unzip` and `cpio` keep their dest flag here AND fall back to the CWD in
    # `_writer_destinations`, so both spellings are read.
    "unzip": {"valued": ("-P", "-x"), "dest": ("-d",), "require": (),
              "skip_first": 0, "last_only": False},
    "cpio": {"valued": ("-F", "--file", "-H", "--format", "-R", "--owner"),
             "dest": ("-D", "--directory"), "require": (), "skip_first": 0,
             "last_only": False},
    "setfacl": {"valued": ("-m", "--modify", "-x", "--remove", "-M", "-X",
                           "--set", "--set-file", "--restore"),
                "dest": (), "require": (), "skip_first": 0, "last_only": False},
    "chown": {"valued": ("--reference", "--from"), "dest": (), "require": (),
              "skip_first": 1, "last_only": False},
    "chgrp": {"valued": ("--reference",), "dest": (), "require": (),
              "skip_first": 1, "last_only": False},
    # `shred` was IN `_REMOVING_PROGRAMS`, which the coverage block reads, and
    # NOTHING dispatched it: the shared parser's `_TRIGGERS` has no `shred` so
    # `scan` fast-outs, and no local reader named it. A verb PRESENT in the
    # block passed silently, which made the block's own sentence false in the
    # dangerous direction. That is the finding that turned the block from a
    # claim into a measured one; see `_assert_covered_verbs_deny`.
    "shred": {"valued": ("-n", "--iterations", "-s", "--size", "--random-source"),
              "dest": (), "require": (), "skip_first": 0, "last_only": False},
    "scp": {"valued": ("-P", "-i", "-o", "-l", "-c", "-F", "-S", "-J"),
            "dest": (), "require": (), "skip_first": 0, "last_only": True},
    "rename.ul": {"valued": (), "dest": (), "require": (), "skip_first": 2,
                  "last_only": False},
    "rename": {"valued": (), "dest": (), "require": (), "skip_first": 2,
               "last_only": False},
    "split": {"valued": ("-b", "--bytes", "-l", "--lines", "-n",
                         "--number", "-a", "--suffix-length",
                         "--additional-suffix", "--filter"),
              "dest": (), "require": (), "skip_first": 0, "last_only": True},
}
_EDITOR_SCRIPT_FLAGS = ("-c", "--cmd", "-S", "-s")


def _is_scripted(args: list) -> bool:
    for tok in args:
        if tok.startswith("+"):
            return True
        name = tok.split("=", 1)[0]
        if name in _EDITOR_SCRIPT_FLAGS:
            return True
        if tok.startswith("-") and not tok.startswith("--") and \
                any(c in tok[1:] for c in "csS"):
            return True          # a bundle such as `ex -sc`
    return False


def _simple_writer_targets(base: str, args: list, here: str) -> list:
    spec = _SIMPLE_WRITERS.get(base)
    if spec is None:
        return []
    if spec["require"] == "script" and not _is_scripted(args):
        return []
    if spec["dest"]:
        val = _flag_value(args, spec["dest"])
        return [_parser().resolve(val, here)] if val else []
    out, i, seen = [], 0, 0
    while i < len(args):
        tok = args[i]
        name = tok.split("=", 1)[0]
        if name in spec["valued"]:
            i += 1 if "=" in tok else 2
            continue
        if tok.startswith("-") and tok != "-":
            i += 1
            continue
        seen += 1
        if seen > spec["skip_first"]:
            out.append(_parser().resolve(tok, here))
        i += 1
    if spec["last_only"]:
        out = out[-1:]
    return out


_AWK_NAMES = ("awk", "gawk", "mawk", "busybox-awk")


def _tar_extracts(args: list) -> bool:
    for tok in args:
        if tok.startswith("--"):
            if tok.split("=", 1)[0] in ("--extract", "--get"):
                return True
            continue
        if tok.startswith("-") and "x" in tok[1:]:
            return True
        # tar's ancient flagless spelling: `tar xf a.tar -C dir`
        if tok and not tok.startswith("-") and set(tok) <= set("xcrtuvfzjJavhpP") \
                and "x" in tok:
            return True
    return False


# An extractor with NO destination flag writes into the CWD, and only the
# explicit form was read: `cd ~/.claude && tar xf /tmp/e.tar` allowed while
# `tar -x -C ~/.claude` denied. Same for `unzip -o` without `-d`, `cpio -id`
# without `-D` and `patch -p0` without `-d`.
_CWD_EXTRACTORS = {"tar": None, "unzip": None, "cpio": None, "patch": None}


def _writer_destinations(base: str, args: list, here: str) -> list:
    for name, flags, needs in _WRITER_FLAGS:
        if base != name:
            continue
        if name == "tar" and not _tar_extracts(args):
            return []
        val = _flag_value(args, flags)
        if val:
            return [_parser().resolve(val, here)]
        return [_parser().resolve(".", here)] if name in _CWD_EXTRACTORS else []
    if base in _AWK_NAMES:
        inplace = any(
            (a == "-i" and i + 1 < len(args) and args[i + 1] == "inplace") or
            a in ("-iinplace", "--include=inplace")
            for i, a in enumerate(args))
        if not inplace:
            return []
        positional = _put_positional("awk", args)
        # the awk PROGRAM is the first positional unless it came from -f
        scripted = any(a in ("-f", "--file") or a.startswith("--file=")
                       for a in args)
        files = positional if scripted else positional[1:]
        return [_parser().resolve(f, here) for f in files]
    return []


# Redirect spellings the shared parser's `redirect_targets` does not read: it
# tests `core.startswith(">")` after stripping leading digits, so `&>file`
# (starts with `&`) is invisible and `>|file` yields the literal `|file`. Both
# write the file. Reproduced as ALLOW against the live settings before this.
_EXOTIC_REDIRECT = ("&>>", "&>", ">|")


def exotic_redirect_hits(command: str, cwd: str) -> list:
    """(kind, target, verb) for `&>`, `&>>` and `>|`.

    Run over the WHOLE command rather than per segment, because the segment
    splitter cuts on `|` and `>| path` arrives as two segments with the path
    orphaned in the second one. shlex over the whole string is still
    boundary-aware, which is the property that matters: `git commit -m "a >| b"`
    is one token and never becomes a target. `cd` is tracked here too, so
    `cd ~/.claude && echo x >| settings.json` resolves the same as the absolute
    spelling."""
    import shlex
    if not any(op in command for op in _EXOTIC_REDIRECT):
        return []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    mod = _parser()
    here, out, i = cwd, [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("cd", "pushd") and i + 1 < len(tokens):
            here = mod.resolve(tokens[i + 1], here)
            i += 2
            continue
        for op in _EXOTIC_REDIRECT:
            if tok == op:
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("&"):
                    out.append(("path", mod.resolve(tokens[i + 1], here), op))
                i += 1
                break
            if tok.startswith(op) and len(tok) > len(op):
                out.append(("path", mod.resolve(tok[len(op):], here), op))
                break
        i += 1
    return out


def extra_put_hits(command: str, cwd: str) -> list:
    """(kind, target, verb) for the destinations above.

    A substring fast-out keeps this off the hot path: without it every Bash
    command would pay a second shlex pass for verbs that are rare in the corpus.
    """
    import shlex
    if not any(t in command for t in _PUT_TRIGGERS):
        return []
    mod = _parser()
    try:
        segments = mod._dim_helpers()[0](command or "")
    except Exception:
        segments = [command or ""]
    here = cwd
    out = []
    for seg in segments:
        try:
            tokens = shlex.split(seg.strip().rstrip(";"))
        except ValueError:
            continue
        _redirs, tokens = mod.redirect_targets(tokens)   # `cp a b > log`
        if not tokens:
            continue
        try:
            tokens, here = mod.peel_wrappers(mod.peel_env(tokens), here)
        except Exception:
            pass
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd") and len(tokens) > 1:
            here = mod.resolve(tokens[1], here)
            continue
        base = os.path.basename(tokens[0])
        if base in _COPY_VERBS:
            for target in _copy_destinations(base, tokens[1:], here):
                out.append(("path", target, base))
            # `rsync --remove-source-files` REMOVES what it sent, so the
            # destination rule alone missed it: the program was in a table and
            # the flag was unread.
            for target in _archive_removes(base, tokens[1:], here):
                out.append(("path", target, base))
            continue
        for target in _writer_destinations(base, tokens[1:], here):
            out.append(("path", target, base))
        for target in _consuming_targets(base, tokens[1:], here):
            out.append(("path", target, base))       # removes what it reads
        for target in _archive_removes(base, tokens[1:], here):
            out.append(("path", target, base))
        for target in _overwriting_targets(base, tokens[1:], here):
            out.append(("path", target, base))
        if base == "chmod":
            for target in _chmod_targets(tokens[1:], here):
                out.append(("state", target, "chmod"))
        for target in _simple_writer_targets(base, tokens[1:], here):
            out.append(("state" if base in ("setfacl", "chown", "chgrp")
                        else "path", target, base))
    return out


# THE TRIGGER LIST IS DERIVED FROM THE TABLES IT GATES, because a second
# hand-kept list decided whether the reader ran at all. Measured: adding a row
# to `_CONSUMING` and regenerating the coverage block left the block assertion
# GREEN while the verb still ALLOWED, because `_PUT_TRIGGERS` never learned the
# name. A row could be covered by the block, pass the assertion, and never reach
# its reader. Now every table that `extra_put_hits` dispatches contributes its
# own keys, so a new row gates itself in.
_PUT_TRIGGERS = tuple(sorted(set(
    _COPY_VERBS
    + tuple(n for n, _f, _r in _WRITER_FLAGS)
    + tuple(_CONSUMING)
    + tuple(_SIMPLE_WRITERS)
    + _AWK_NAMES
    + ("tar", "zip", "sort", "uniq", "chmod", "&>", ">|")
)))


# `find` IS NOT ALWAYS A REMOVING VERB, and the label said it was.
#
# The shared parser tags every find it reports as `find -delete`, because that
# is the only reason it reports one. But its own `find_targets` also fires on
# `-exec <mutator>`, and a mutator can PUT as easily as it can take:
#
#   find <live>/…/.claude -maxdepth 0 -exec cp /tmp/settings.json {} \;
#
# was read as removing, so `_holds_settings` listed the directory, found no
# settings, answered "nothing to take" and ALLOWED. QA has the receipt: the
# settings file lands in the drop box. The per-verb split is right; the label
# was what lied. So the label is re-derived here from what the command actually
# carries.
# ── a program that reaches a path THROUGH another program ───────────────────
#
# Read the first two rows of what QA measured together, because they name the
# bug better than any description of it:
#
#     find <live>/scripts -name '*.py' -exec rm {} \;    ALLOWED
#     find <live>/scripts -name '*.py' -exec rm {} ;      denied
#
# `\;` is the form that RUNS in a shell; a bare `;` is a syntax error there. So
# the gate denied the spelling that cannot execute and allowed the spelling
# everyone types. Isolated rather than guessed, and it is not the terminator:
#
#     the shared splitter cuts sub-commands on `;` and does not honour the
#     backslash, so the segment it hands back ENDS IN A LONE `\`. shlex then
#     raises on the dangling escape, the parser falls back to `seg.split()`, and
#     a whitespace split KEEPS THE QUOTES: `-name '*.py'` yields the pattern
#     `'*.py'` with its literal quotes, so the glob becomes
#     `<live>/scripts/*'*.py'`, which matches no file that exists. The `-exec rm`
#     was recognised, the root was right, and the deny was lost to a corrupted
#     PATTERN.
#
# That generalises past `find`: any segment whose lex fails produces quoted
# tokens, and every path or glob derived from it is wrong. Both halves live in
# files this branch does not own (the splitter in dimension-awareness-hook.py,
# the fallback in the shared parser), so this reader does not depend on either:
# it lexes the RAW command, where `\;` is an ordinary escaped `;` and shlex
# reads it correctly.
#
# The other direction of the same tuple was open too. The F4 fix covered the
# label OVER-claiming (a non-deleter wearing `find -delete`) and left it
# UNDER-claiming: a real deleter with no `-delete` on the line. And `-ok` /
# `-okdir` were in neither, because the shared `find_targets` only looks for
# `-exec` / `-execdir`.
#
# WHAT THIS READER DOES NOT RE-IMPLEMENT: the roots, the `-name` filter and the
# case flag all still come from the shared `find_targets`. `-ok` / `-okdir` are
# NORMALISED to `-exec` / `-execdir` before it is called, which is why there is
# no second copy of `_FIND_FILTERS` here. What is local is only the JUDGMENT:
# which program the `-exec` runs, and therefore which verb label the hit carries.
_CMD_BREAKS = (";", "&&", "||", "|", "&", "(", ")", "{", "}", "|&")
_FIND_EXEC_FLAGS = {"-ok": "-exec", "-okdir": "-execdir"}


def _lex(command: str) -> list:
    """The WHOLE command as tokens, quote- and escape-aware.

    Lexing the raw string is the point: the shared splitter cuts on a bare `;`
    before anything sees the backslash that escapes it."""
    import shlex
    try:
        return shlex.split(command)
    except ValueError:
        return []          # a command that cannot be read denies nothing


def _command_starts(tokens: list) -> list:
    """Index of every token that begins a command in the stream."""
    starts = [0] if tokens else []
    for i, tok in enumerate(tokens):
        if tok in _CMD_BREAKS and i + 1 < len(tokens):
            starts.append(i + 1)
    return starts


def _stage_end(tokens: list, start: int) -> int:
    j = start
    while j < len(tokens) and tokens[j] not in _CMD_BREAKS:
        j += 1
    return j


def _exec_program(args: list):
    """The program a find's `-exec` / `-execdir` runs, or None."""
    for i, tok in enumerate(args):
        if tok in ("-exec", "-execdir") and i + 1 < len(args):
            return os.path.basename(args[i + 1])
    return None


def _find_hits(args: list, here: str, assume_delete: bool = False) -> list:
    """(kind, target, verb) for ONE find invocation's arguments.

    The verb is the PROGRAM that acts, so a removing one lands in
    `_REMOVING_VERBS` and keeps the per-verb `.claude` rule intact: an empty
    drop-box directory stays deletable, and a find that PUTS keeps being judged
    as a put."""
    args = [_FIND_EXEC_FLAGS.get(a, a) for a in args]
    mod = _parser()
    probe = args + ["-delete"] if assume_delete else args
    # `assume_delete` is how the LEFT side of a pipe is read. The shared
    # `find_targets` extracts roots and the `-name` filter only for a find it
    # already believes deletes, and a find feeding `xargs rm` deletes nothing by
    # itself: it PRINTS. The paths it prints are the paths it would delete, so
    # the extraction is asked the question it can answer and the verb comes from
    # the stage that actually removes.
    try:
        roots, pattern, icase = mod.find_targets(probe)
    except Exception:
        return []
    if not roots:
        return []
    prog = _exec_program(args)
    if prog in _REMOVING_PROGRAMS:
        verb = prog
    elif prog:
        verb = f"find -exec {prog}"          # a put: judged as one
    else:
        verb = "find -delete"
    out = []
    for root in roots:
        base = mod.resolve(root, here)
        if pattern:
            out.append(("iglob" if icase else "glob",
                        os.path.join(base, "*" + pattern), verb))
        else:
            out.append(("path", base, verb))
    return out


def _stdin_source_hits(tokens: list, here: str, verb: str) -> list:
    """(kind, target, verb) for the paths a pipeline stage FEEDS to the next one.

    `find <live>/scripts -name '*.py' | xargs rm` reaches every file the find
    matches, and the shared parser sees two segments: a `find` that deletes
    nothing and an `xargs rm` whose target list is on stdin. Its own residual
    calls that "xargs fed from STDIN, where the targets never appear in the
    command", which is true of `cat list | xargs rm` and false here: the paths
    are in the command, one stage to the left."""
    if not tokens:
        return []
    mod = _parser()
    base = os.path.basename(tokens[0])
    if base == "find":
        return [(kind, target, verb)
                for kind, target, _v in _find_hits(tokens[1:], here,
                                                   assume_delete=True)]
    out = []
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        if "/" not in tok and "*" not in tok:
            continue                    # a bare word is not a path we can test
        target = mod.resolve(tok, here)
        out.append(("glob" if any(c in tok for c in "*?[") else "path",
                    target, verb))
    return out


def indirect_removal_hits(command: str, cwd: str) -> list:
    """(kind, target, verb) for a removal that reaches its paths through
    another program on the same line: `find -exec`, and a pipe into a removing
    verb.

    A substring fast-out keeps it off the hot path."""
    if "find" not in command and "|" not in command and \
            not _C_CHANNEL.search(command) and \
            not any(h in command for h in _CMD_STRING_HOSTS):
        return []
    tokens = _lex(command)
    if not tokens:
        return []
    mod = _parser()
    here = cwd
    out = []
    starts = _command_starts(tokens)
    for n, start in enumerate(starts):
        end = _stage_end(tokens, start)
        stage = tokens[start:end]
        if not stage:
            continue
        if stage[0] in ("cd", "pushd") and len(stage) > 1:
            here = mod.resolve(stage[1], here)
            continue
        if os.path.basename(stage[0]) == "find":
            out.extend(_find_hits(stage[1:], here))
            continue
        # A BUNDLED `-c` on a shell host. `sh -c 'rm -rf <live>/scripts'` and
        # `bash -c` are denied by the shared parser, which recurses on a LITERAL
        # `-c` token; `bash -ec` carries no such token and was measured ALLOW.
        # This is the same blind spot the interpreter layer of this file already
        # fixed for its own fast-out, so it reuses that reader (`_c_bodies`,
        # host-checked) rather than growing a second one, and it fires only
        # where the parser is blind: a bundle with no literal `-c` beside it.
        bodies = _cmd_string_bodies(stage)
        if not bodies and "-c" not in stage:
            bodies = _c_bodies(stage)
        if bodies:
            for body in bodies:
                out.extend(bash_targets(body, here))
            continue
        # a stage whose program REMOVES and whose paths come from stdin
        if start == 0 or tokens[start - 1] not in ("|", "|&"):
            continue
        try:
            prog, _here = mod.peel_wrappers(mod.peel_env(list(stage)), here)
        except Exception:
            prog = stage
        if not prog:
            continue
        verb = os.path.basename(prog[0])
        if verb not in _REMOVING_PROGRAMS:
            continue
        prev_start = starts[n - 1] if n else 0
        prev = tokens[prev_start:_stage_end(tokens, prev_start)]
        out.extend(_stdin_source_hits(prev, here, verb))
    return out


# ONE PLACE DECIDES WHETHER A `find` REMOVES, and it is `_find_hits` above,
# which labels every hit with the PROGRAM that acts. A second mechanism lived
# here for one cycle: a helper that re-read the command and flipped the shared
# parser's label at consumption time. It is gone rather than kept as a safety
# net. Measured by reverting it: with the label correct at the source it no
# longer changes any verdict, and the case it was written for
# (`find <dir>/.claude -exec cp settings.json {} +`) still denies without it.
# A redundant mechanism that never fires is the same trap as a second list of
# what removes: it drifts, and nobody notices because nothing depends on it.


# Two git verbs that reach an arming surface without naming a file, both
# measured as ALLOW and both an arming surface by this gate's own criterion.
#
#   `git -C ~/.claude config core.hooksPath <dir>` writes `.git/config`, and
#   that key names the directory `.githooks/pre-push` is run from. The live tree
#   really carries `core.hooksPath=.githooks`, so one `config` call repoints the
#   very push gate this file protects BY NAME. The deny covers every SET, not
#   just that key: `.git/config` is now a protected file and a set is what
#   writes it. Reads (`--get`, `--list`, `--get-all`, `--get-regexp`) stay
#   allowed, which is the shape that appears in real traffic. The over-fire is
#   stated rather than hidden: `git config user.email` inside the live root is
#   denied too, and the development path is the same one every other deny here
#   points at, a worktree or the operator's own terminal.
#
#   `git push --no-verify` skips `.githooks/pre-push` entirely, which is the
#   push-time half of RULE #1's wiring assertion. It is not a file write, so it
#   gets its own kind and its own copy. `-n` is NOT it: for `push`, `-n` means
#   `--dry-run`, so only the long spelling is matched.
# A SET is what writes `.git/config`, and `git config <name>` with ONE
# positional is a READ that prints the value. Requiring a name AND a value (or
# an explicit mutating flag) is not a nicety: measured over 18,154 distinct real
# Bash calls, the "one positional is a set" version denied two commands, both of
# them `git config core.hooksPath` READING the key to check it is still
# `.githooks`, which is the diagnostic this very rule exists to protect.
# EVERY ROUTE TO THE SAME DISARM, not just the flag. `git push --no-verify`
# skips .githooks/pre-push, and so does each of these, all measured as ALLOW
# against the live tree while the header claimed the surface was covered:
#
#   git -C ~/.claude -c core.hooksPath=/dev/null push origin HEAD
#   git -C ~/.claude -ccore.hooksPath=/tmp/none push            (fused)
#   GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath \
#     GIT_CONFIG_VALUE_0=/tmp git -C ~/.claude push             (env config)
#
# The numbered block is caught by scanning every `GIT_CONFIG_KEY_n` /
# `GIT_CONFIG_VALUE_n` for the key, whatever `n` is. A branch that denied on the
# bare presence of `GIT_CONFIG_COUNT` was written first and removed: it was
# redundant with that scan and its only distinct effect was to deny a legitimate
# env-config push. A reverted-fix anchor is what surfaced it, by refusing to
# turn any fixture red.
#   GIT_CONFIG_PARAMETERS="'core.hooksPath=/tmp'" git -C ~/.claude push
#   GIT_DIR=~/.claude/.git git push --no-verify                 (repo from env)
#
# The first two are git's own per-invocation config; the next two are the env
# spellings of the same thing; the last one names the repo without `-C`, which
# is why the segment's env assignments are read for `GIT_DIR` before they are
# peeled away. `-n` is still NOT included: for `push` that means `--dry-run`.
_HOOKS_PATH_KEY = "hookspath"
_GIT_CONFIG_ENV = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def _env_assignments(tokens: list) -> tuple:
    """({NAME: value}, the tokens after them). `peel_env` drops the values."""
    env, i = {}, 0
    while i < len(tokens):
        tok = tokens[i]
        name, eq, val = tok.partition("=")
        if not eq or not name or not name.replace("_", "").isalnum() or \
                not (name[0].isalpha() or name[0] == "_"):
            break
        env[name] = val
        i += 1
    return env, tokens[i:]


def _disables_hooks(rest: list, env: dict) -> bool:
    """True when this git invocation turns `core.hooksPath` into something
    other than the repo's own hooks, by flag or by environment."""
    for tok in rest:
        low = _fold(tok)
        if low == "--no-verify":
            return True
    for name, val in env.items():
        if name.startswith(_GIT_CONFIG_ENV) or name in _GIT_CONFIG_ENV:
            if _HOOKS_PATH_KEY in _fold(val) or _HOOKS_PATH_KEY in _fold(name):
                return True
    return False


def _global_sets_hookspath(tokens: list) -> bool:
    """`git -c core.hooksPath=X` and its fused `-cX` spelling, before the
    subcommand. `git_parse` skips `-c` as a valued global, which is right for
    finding the subcommand and blind for this."""
    for i, tok in enumerate(tokens):
        if tok == "-c" and i + 1 < len(tokens):
            if _HOOKS_PATH_KEY in _fold(tokens[i + 1]):
                return True
        elif tok.startswith("-c") and len(tok) > 2 and not tok.startswith("--"):
            if _HOOKS_PATH_KEY in _fold(tok[2:]):
                return True
        elif tok.startswith("--config-env"):
            if _HOOKS_PATH_KEY in _fold(tok):
                return True
    return False


# A RESTORE THAT NAMES A REF IS NOT A RESTORE OF THE REVIEWED BYTES, which is
# the sentence the fixtures narrowing rested on and it was true only of a
# same-branch `checkout --`. Measured as ALLOW before this:
#   git -C ~/.claude checkout evil -- <fixture>
#   git -C ~/.claude checkout HEAD~40 -- <fixture>
#   git -C ~/.claude restore --source=evil <fixture>
# Each puts UNREVIEWED bytes into a violation fixture, which is exactly the
# doctored-fixture-into-green-gate-liveness threat the narrowing exists to stop.
def restore_names_ref(command: str) -> bool:
    """True when a checkout/restore in this command restores from a named ref
    rather than from the index of the current branch."""
    tokens = _lex(command)
    if not tokens:
        return False
    for start in _command_starts(tokens):
        stage = tokens[start:_stage_end(tokens, start)]
        _env, stage = _env_assignments(stage)
        if not stage or os.path.basename(stage[0]) != "git":
            continue
        parsed = _parser().git_parse(stage)
        if not parsed:
            continue
        _repo, sub_cmd, rest = parsed
        if sub_cmd == "restore":
            if any(a == "-s" or a.split("=", 1)[0] in ("--source",) for a in rest):
                return True
            continue
        if sub_cmd != "checkout":
            continue
        # anything before `--` that is not a flag is a ref
        for tok in rest:
            if tok == "--":
                break
            if not tok.startswith("-"):
                return True
    return False


_CONFIG_READS = ("--get", "--get-all", "--get-regexp", "--get-urlmatch",
                 "--list", "-l", "--get-color", "--get-colorbool")
_CONFIG_WRITES = ("--unset", "--unset-all", "--add", "--replace-all", "--edit",
                  "-e", "--rename-section", "--remove-section")


def extra_git_hits(command: str, cwd: str) -> list:
    """(kind, target, verb) for git verbs that disarm without naming a file."""
    import shlex
    if "git" not in command:
        return []
    if not any(t in command for t in
               ("config", "--no-verify", "hooksPath", "hookspath", "GIT_DIR")):
        return []
    mod = _parser()
    try:
        segments = mod._dim_helpers()[0](command or "")
    except Exception:
        segments = [command or ""]
    here, out = cwd, []
    for seg in segments:
        try:
            tokens = shlex.split(seg.strip().rstrip(";"))
        except ValueError:
            continue
        # `2>&1` is a redirect, not an argument, and counting it as one made
        # `git -C <repo> config core.hooksPath 2>&1` look like a two-positional
        # SET. Measured: that was the last false deny left in the corpus replay.
        _redirs, tokens = mod.redirect_targets(tokens)
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd") and len(tokens) > 1:
            here = mod.resolve(tokens[1], here)
            continue
        env, tokens = _env_assignments(tokens)
        if not tokens or os.path.basename(tokens[0]) != "git":
            continue
        parsed = mod.git_parse(tokens)
        if not parsed:
            continue
        repo, sub_cmd, rest = parsed
        # GIT_DIR names the repo when `-C` does not: `GIT_DIR=~/.claude/.git
        # git push --no-verify` carries no `-C` and reaches the live tree.
        if not repo and env.get("GIT_DIR"):
            repo = os.path.dirname(mod.resolve(env["GIT_DIR"], here)) or None
        base_dir = mod.resolve(repo, here) if repo else here
        root = kernel_proc.enclosing_worktree_root(base_dir) or base_dir
        if sub_cmd == "config":
            if any(a.split("=", 1)[0] in _CONFIG_READS for a in rest):
                continue
            positional = [a for a in rest if not a.startswith("-")]
            writes = any(a.split("=", 1)[0] in _CONFIG_WRITES for a in rest)
            if len(positional) < 2 and not writes:
                continue                       # a read, not a set
            out.append(("path", os.path.join(root, ".git", "config"),
                        "git config"))
        elif sub_cmd == "push" and (
                _disables_hooks(rest, env) or _global_sets_hookspath(tokens)):
            out.append(("push", root, "git push with the hook disabled"))
    return out


_BRANCH_VERBS = ("checkout", "switch")


# Flags of checkout/switch whose argument is definitely NOT a start point, kept
# deliberately SHORT. `--track origin/x` is the counter-example that sets the
# rule: its argument IS the commit checked out, so listing it here would exempt
# `checkout -b tmp --track origin/x`, which rewrites the tree. Anything not
# named here that carries a space-separated value has that value counted as a
# positional, which REFUSES the exemption. Conservative is the right direction:
# a missed exemption costs one deny on a legitimate command, a wrong one
# reopens the whole-tree rewrite.
_BRANCH_VALUED = ("--conflict", "--pathspec-from-file")


def branch_creation_only(command: str) -> bool:
    """True when the ONE checkout/switch in this command creates a branch AT
    HEAD and names no start point.

    THE START POINT IS THE WHOLE RULE, and leaving it out reopened exactly the
    whole-tree rewrite this exemption was carved out of. `git checkout -b`,
    `checkout -qb` and `switch -c` make a new ref at HEAD and rewrite no file,
    which is why the deny copy that fired on them ("rewrites the whole working
    tree") was false and why about ten of them appear in real traffic. But git
    takes an OPTIONAL START POINT after the new name, and with one the command
    checks that commit out: QA took a real git receipt, a file reading `good`
    before `git checkout -b tmp evil` and `EVIL` after it. The first version of
    this function returned True the moment it saw a flag carrying the create
    letter and never looked at what followed, so all four of

        git -C <live> checkout -b tmp evil
        git -C <live> switch   -c tmp evil
        git -C <live> checkout -B tmp evil
        git -C <live> checkout -C tmp evil

    were exempted by their harmless half, one token before the harmful one.

    So the test is POSITIONAL, not flag-shaped: exempt only when the create flag
    is present AND the verb is followed by exactly ONE positional, the new
    branch name. `-b tmp` exempts; `-b tmp <anything>` does not, whatever the
    anything is (a branch, a tag, a SHA), because every spelling of a second
    positional is a start point and every start point rewrites the tree. That
    also answers the upper-case pair without a second rule: `-B tmp` and
    `-C tmp` force-move a ref to HEAD and touch no file, `-B tmp evil` moves it
    to `evil` and checks that out, and the positional count separates them.

    A `--` pathspec separator is never a branch creation (`git checkout -b x --
    file` is not a thing, and `checkout -- <path>` is the file-restore shape the
    path layer owns), so it refuses the exemption too.

    THE REDIRECT IS NOT AN ARGUMENT, and counting it as one made this deny the
    command the operator types every day: `git checkout -b feat/x 2>&1` DENIED
    while the bare form allowed, because `2>&1` was read as a start point. So
    were `>/tmp/log`, a pipe stage and anything after `&&`. The corpus carries
    seven real instances of exactly this on the live tree. It is the same
    `2>&1`-is-not-a-positional bug that was found and fixed in `extra_git_hits`
    one cycle earlier and not carried across: one member of a class closed, the
    other left open. Positionals are counted over the checkout/switch STAGE
    only now, with `redirect_targets` applied to it first. An over-fire here is
    not a small cost, by this gate's own doctrine: a gate that blocks normal
    work gets turned off, and branch creation is normal work.

    Still scoped to a command carrying exactly ONE such verb, unchanged and for
    the same reason: `git -C ~/.claude checkout -b tmp && git -C ~/.claude
    checkout evil` would otherwise be exempted by its harmless half."""
    tokens = _lex(command)
    if not tokens:
        return False
    seen = [i for i, t in enumerate(tokens) if t in _BRANCH_VERBS]
    if len(seen) != 1:
        return False
    i = seen[0]
    letter = "b" if tokens[i] == "checkout" else "c"
    # THE STAGE, NOT THE COMMAND, and with its redirects removed. This counted
    # positionals over the whole token list, so `2>&1` was read as a start point
    # and `git checkout -b feat/x 2>&1` DENIED while the bare form allowed. It
    # is the same `2>&1`-is-not-an-argument bug that was found and fixed in
    # `extra_git_hits` one cycle earlier and not carried across to here: one
    # member of the class closed, the other left open. The corpus carries seven
    # real instances of this exact shape on the live tree, and a gate that
    # denies the operator's normal branch creation is a gate he turns off.
    end = _stage_end(tokens, i)
    rest = tokens[i + 1:end]
    try:
        _redirs, rest = _parser().redirect_targets(rest)
    except Exception:
        pass
    creates, positionals = False, 0
    j = 0
    while j < len(rest):
        tok = rest[j]
        j += 1
        if tok == "--":
            return False                  # a pathspec, never a branch creation
        if tok.startswith("-") and tok != "-":
            name = tok.split("=", 1)[0]
            if name in ("--orphan",):
                creates = True
                continue
            if name in _BRANCH_VALUED:
                if "=" not in tok:
                    j += 1                # its value is not the start point
                continue
            if not tok.startswith("--") and \
                    (letter in tok[1:] or letter.upper() in tok[1:]):
                creates = True
            continue
        positionals += 1
    return creates and positionals == 1


# The heredoc reader is NOT the `-c` reader, and the difference is measured.
#
# The first version applied the `-c` layer's needle-plus-marker test to heredoc
# bodies unchanged. Replayed against 17,232 real Bash calls from this machine's
# transcripts (3,296 of them carrying a heredoc), that flipped 23 commands from
# ALLOW to DENY and exactly 2 of them were genuine live writes. Precision 2/23.
# The other 21 were the same shape every time: a heredoc that writes a DOCUMENT
# whose CONTENT quotes a protected path, which is what editing this gate's own
# header, its fixtures, its README-residuals and CLAUDE.md looks like. A gate
# that denies its own development, with no env unlock, is the failure the whole
# boundary was drawn around, so that version is not shippable at any price.
#
# A `-c` body is a one-line ARGUMENT; a heredoc body is a DOCUMENT. The loose
# test survives on the first because there is no room in it for prose. On the
# second it cannot tell code from data, so the heredoc reader asks a narrower
# question: is the protected path the DIRECT OPERAND of a write? Measured on the
# same corpus that fires on 2 of 3,296, down from 23, and the direct attack
# shape (`python3 - <<PY` then open(literal,'w')) still denies. The 2 are
# stated rather than rounded to zero: both are one command writing a TEST
# HARNESS whose text carries the attack literal, which no text scan separates
# from the attack, and both came from the adversarial lab, not from the work.
#
# The price is stated rather than hidden: a heredoc that reaches the file
# through a VARIABLE escapes this reader, and both genuine live writes in the
# corpus were that shape. It is the same residual the `-c` layer already names
# ("a path built from a variable"), now true of both channels instead of one.
# THE HOST DOES NOT HAVE TO PRECEDE THE `<<`, and requiring it on the same line
# left the two most ordinary spellings uncovered, both measured as ALLOW:
#
#     cat <<'PY' | python3            <- the host is downstream of the heredoc
#     node - <<JS                     <- `node` and `perl` were not hosts at all
#
# The second one is worse than a miss: with no `node` and no `perl` in the
# table, the `writeFileSync` and `os.replace`/`shutil` entries of `_DIRECT_WRITE`
# below were UNREACHABLE from a heredoc, so two of them were dead code that no
# fixture could exercise (QA's surviving mutants M11 and M13). That is exactly
# the dead-entry class this file killed in the host table one commit ago,
# reappearing in the pattern table, and it is why the fix is to make the entries
# reachable rather than to delete them.
#
# So the test is now "does this command run an interpreter at all", anywhere,
# with the interpreter list widened to the ones whose write idioms are already
# in `_DIRECT_WRITE`. That is safe HERE and would not be safe on the `-c`
# channel, for the reason spelled out above: this reader asks the NARROW
# question (is the protected path the direct operand of a write?), so a wider
# entry admits more bodies to a test that still refuses prose.
_HEREDOC_HOST = re.compile(
    r"""(?:^|[\s;&|(`"'])(?:[\w./-]*/)?"""
    r"""(?:bash|sh|zsh|dash|python[0-9.]*|py|node|nodejs|deno|bun|perl|ruby|php)\b""")

# A write whose DESTINATION is the literal itself. `{q}` is the escaped needle.
#
# The `>` entry looked redundant and is not, measured both ways: a PLAIN
# `> <path>` on a heredoc line is already caught, because the shared parser
# splits the command on newlines and reads each body line as a sub-command, so
# the redirect becomes an ordinary path hit. QUOTING it hides it from that
# parser, and then this pattern is the only cover:
#     bash <<'EOF'
#     eval "echo x > ~/.claude/settings.json"
#     EOF
# denies with the entry and allows without it, which is what its fixture pins.
# The accident that covers the plain form also goes away when the shared
# `_split_heredocs` lands and bodies stop being sub-commands.
# A WRITING MODE: anything starting w/a/x, plus `r+`, which truncates nothing on
# open and is a write handle all the same (`open(p,'r+').truncate(0)` was
# measured as ALLOW). `{p}` is the optional string PREFIX, so an f-string
# literal (`open(f'~/.claude/settings.json','w')`) is the same pattern.
_MODE = r"""['"](?:[waxWAX]|[rR]\+)"""
_PRE = r"""[fFrRbBuU]{0,2}"""
_DIRECT_WRITE = (
    # open(<lit>, 'w') / open(<lit>, mode='w') / open(os.path.expanduser(<lit>), 'w')
    r"""open\s*\(\s*(?:(?:os\.path\.)?expanduser\s*\(\s*)?""" + _PRE +
    r"""['"]{q}['"]\s*\)?\s*,\s*(?:[^)]*?,\s*)?(?:mode\s*=\s*)?""" + _MODE,
    # Path(<lit>)[.expanduser()].write_text / .write_bytes / .open('w')
    r"""(?:pathlib\.)?Path\s*\(\s*""" + _PRE + r"""['"]{q}['"]\s*\)"""
    r"""(?:\s*\.\s*(?:expanduser|resolve|absolute)\s*\(\s*\))*\s*\."""
    r"""(?:write_text|write_bytes|open\s*\(\s*""" + _PRE + _MODE + r""")""",
    r"""(?:writeFileSync|appendFileSync)\s*\(\s*['"`]{q}['"`]""",
    r""">>?\s*['"]?{q}""",
    r"""(?:os\.replace|os\.rename|shutil\.copy2?|shutil\.copyfile|shutil\.move)"""
    r"""\s*\([^)]*,\s*""" + _PRE + r"""['"]{q}['"]""",
)


def heredoc_write(command: str):
    """(literal, "direct write") when a heredoc body writes a protected path as
    the direct operand of a write call or a shell redirect.

    The host is looked for in the SHELL half only; see `heredoc_split` for the
    measurement that put it there."""
    shell, bodies = heredoc_split(command)
    if not bodies or not _HEREDOC_HOST.search(shell):
        return None
    needles = _needles()
    for body in bodies:
        flat = _normalize_paths(body)
        for needle in needles:
            if needle not in flat:
                continue          # cheap string test before any regex compile
            quoted = re.escape(needle)
            for pat in _DIRECT_WRITE:
                # `.replace`, never `.format`: these patterns carry regex
                # repetition braces (`{0,2}`), and str.format read one as a
                # field name, raised KeyError, and the module-level fail-open
                # swallowed it. A whole layer was silently off. The selftest
                # compiles every pattern against a sample needle so a brace
                # cannot do that again.
                if re.search(pat.replace("{q}", quoted), flat):
                    return needle, "direct write"
    return None


# THREE MORE INLINE BODIES, none of them a `-c` and none of them a heredoc.
# `sed -n 'w <path>'`, `awk '{print > "<path>"}'` and `node -e "<js>"` each
# carry a PROGRAM as an ordinary argument, and each was measured ALLOW against
# a live protected file. They are read with the SAME narrow direct-write test
# the heredoc reader uses (`_DIRECT_WRITE`), not with a second one: the question
# is identical, is a protected path the direct operand of a write.
_PROGRAM_ARG_HOSTS = {
    "sed": None,          # every non-flag argument may be the script
    "awk": None,
    "gawk": None,
    "mawk": None,
    "node": ("-e", "--eval", "-p", "--print"),
    "nodejs": ("-e", "--eval", "-p", "--print"),
    "perl": ("-e", "-E"),
    "ruby": ("-e",),
    "php": ("-r",),
}


def program_arg_write(command: str):
    """(literal, "program argument") when an inline program argument writes a
    protected path as the direct operand of a write."""
    if not any(h in command for h in _PROGRAM_ARG_HOSTS):
        return None
    tokens = _lex(command)
    if not tokens:
        return None
    bodies = []
    for start in _command_starts(tokens):
        stage = tokens[start:_stage_end(tokens, start)]
        if not stage:
            continue
        base = os.path.basename(stage[0])
        if base not in _PROGRAM_ARG_HOSTS:
            continue
        flags = _PROGRAM_ARG_HOSTS[base]
        if flags is None:
            bodies.extend(t for t in stage[1:] if not t.startswith("-"))
        else:
            for i, tok in enumerate(stage):
                if tok in flags and i + 1 < len(stage):
                    bodies.append(stage[i + 1])
    needles = _needles()
    # sed's own write command is `w <path>`, which carries no `>` and no
    # `open(`, so the shared direct-write patterns cannot see it.
    pats = _DIRECT_WRITE + (r"""(?:^|[;\s{}])[wW]\s+{q}""",)
    for body in bodies:
        flat = _normalize_paths(body)
        for needle in needles:
            if needle not in flat:
                continue
            quoted = re.escape(needle)
            for pat in pats:
                if re.search(pat.replace("{q}", quoted), flat):
                    return needle, "program argument"
    return None


def bash_targets(command: str, cwd: str) -> list:
    """(kind, target, verb) triples worth testing, from the shared parser.

    TWO failures, answered opposite ways, and conflating them was a fail-OPEN
    that no runtime signal showed. QA's whole batch on a minimal sandbox came
    back all-ALLOW and only its positive control caught why: the borrowed parser
    imports `receipt_ledger.py` and `kernel_proc.py`, so with either one missing
    the import raised, the blanket `except` returned [], and every Bash command
    was allowed with no output at all. In a fail-CLOSED gate that is the worst
    possible shape: silent, total, and invisible.

      - The module cannot LOAD. Structural, never input-dependent: no command an
        agent can write makes an import fail, so denying costs no legitimate
        work and cannot be triggered on purpose. It propagates and main() DENIES.
      - The module cannot READ this command. Input-dependent by definition, so
        denying on it hands anyone a DoS: write one unparseable command and the
        gate blocks the session. It still returns [], as before.

    The protected set already holds every file the load needs, so a load failure
    means the brain is broken, not that a command is odd. Loud is the point.

    Measured at scale, by accident and then on purpose: with the parser one
    directory away from where the module looks for it, the previous version
    allowed 17,232 of 17,232 real Bash commands from this machine's transcripts,
    including every one of the 39 disarms it denies when the parser is there.
    Not one line of output, not one non-zero exit, nothing to notice.
    """
    scan = _parser().scan                 # ParserUnavailable propagates: DENY
    try:
        return scan(command, cwd)
    except Exception:
        return []            # a parser that cannot read the command denies nothing


# ── deny copy ───────────────────────────────────────────────────────────────

_ONLY_WRITER = (
    "No hooked process edits the live copy, this gate included. The operator's "
    "terminal is not hooked and stays the only writer. There is no env unlock "
    "for this rule on purpose: the variable that lifted it would be writable "
    "from the very file this protects."
)
_DEV_PATH = (
    "Editing this file is normal development and stays allowed IN A WORKTREE "
    "(`git worktree list`; every ~/.octorato/wt/* checkout is source). Make the "
    "change there, open a PR, and let `ai-sync` / `git pull` land it here."
)


def deny_file(verb: str, target: str, live: str, why: str) -> None:
    deny(
        f"ARMING SURFACE: `{verb}` targets {target}, which reaches {live} in the "
        f"LIVE brain tree ({brain_root()}). That file is {why}. It is not source "
        f"here, it is what the harness loads, so writing it disarms the gates for "
        f"the next session without ever running a gated command. {_DEV_PATH} "
        f"{_ONLY_WRITER}"
    )


def deny_tree(verb: str, root: str) -> None:
    deny(
        f"ARMING SURFACE: `{verb}` rewrites every tracked file at {root}, "
        f"which is the LIVE brain the harness loads. One branch switch swaps "
        f"settings.json's projection, hooks.json and every gate script at once, "
        f"so a file-by-file deny that let this through would protect nothing. "
        f"{_DEV_PATH} {_ONLY_WRITER}"
    )


def deny_push(root: str) -> None:
    deny(
        f"ARMING SURFACE: `git push --no-verify` at {root} skips "
        f".githooks/pre-push, which is where RULE #1's wiring assertion runs "
        f"(brain_doctor --gate-receipt) and where the leak guard scans every "
        f"commit being pushed. Skipping the hook is the same disarm as deleting "
        f"it, one flag instead of one file, and it is the LIVE brain tree. Push "
        f"without the flag, or run the push in the operator's own terminal, "
        f"which is not hooked. {_ONLY_WRITER}"
    )


def deny_own_import(detail: str) -> None:
    deny(
        f"ARMING SURFACE: this gate could not import its own `kernel_proc` "
        f"({detail}), the module that resolves the live brain root, so it can "
        f"decide nothing about any path. That module is INSIDE the set this gate "
        f"protects, and the import sat at module scope with nothing around it: "
        f"the process exited before `main()` existed, wrote no stdout, and the "
        f"harness read the silence as ALLOW. Same silent all-ALLOW as a missing "
        f"shared parser, one import earlier. A load failure is structural and no "
        f"command can provoke it, so it denies. Restore scripts/kernel_proc.py "
        f"from a worktree, or run the restore in the operator's own terminal, "
        f"which is not hooked. {_ONLY_WRITER}"
    )


def deny_parser(detail: str) -> None:
    deny(
        f"ARMING SURFACE: the shared command parser could not be loaded "
        f"({_PARSER_PATH}: {detail}), so this gate cannot read Bash commands at "
        f"all. That is a fail-OPEN with no runtime signal: the parser imports "
        f"receipt_ledger.py and kernel_proc.py, both inside the set this gate "
        f"protects, and with either one missing every Bash command was allowed "
        f"and nothing was printed. A floor that cannot read denies instead. "
        f"Restore the file from a worktree, or run the restore in the "
        f"operator's own terminal, which is not hooked. {_ONLY_WRITER}"
    )


# THE COVERAGE BLOCK IS A MEASUREMENT, NOT A LIST, and the version before this
# was neither. It was a dict literal naming the tables I remembered, three of
# whose entries were LITERALS mirroring `if base == …` conditions in code
# ("archive-removing", "overwriting", the `chmod` in "in-place-edit"), so a
# recogniser added next to them changed nothing: QA added `elif base == "7z"`
# to `_archive_removes` and `--verbs` reported the block UNCHANGED. A derivation
# that reads a hand-kept list of lists is the same hole one level up.
#
# It also OVER-REPORTED, which is the dangerous direction: the block said
# `removing: rm shred unlink` while `shred ~/.claude/settings.json` ALLOWED,
# because `shred` sat in `_REMOVING_PROGRAMS` (which the block read) and nothing
# DISPATCHED it. A verb present in the block passed silently, which makes the
# sentence "anything absent passes" false in the worst way.
#
# Two assertions now hold the block down, one per direction, and neither is a
# list:
#   * `_assert_no_undeclared_dispatch` parses THIS MODULE'S SOURCE and collects
#     every string literal compared against `base` or `sub_cmd`. Each one must
#     appear in the block, so `elif base == "7z"` turns the selftest red.
#   * `_assert_covered_verbs_deny` RUNS each claimed writer through the real
#     gate against a protected path in a sandbox and requires a deny. A verb
#     with no probe is reported as unproven and fails. That is what makes the
#     block a measurement; it is what would have caught `shred` on the day it
#     was written.
#
# THE CLAIM IS NARROWED TO WHAT THE MECHANISM CAN SUPPORT, because the block
# enumerates PROGRAM NAMES and the gate recognises more than program names. What
# it CANNOT enumerate is listed in the block itself, by name, so a reader is
# never told it is complete: git subcommands, `find`'s predicates, redirect
# spellings, the inline write markers, the protected path SHAPES, and the
# version-suffixed interpreter spellings.
def covered_verbs() -> dict:
    """{category: sorted programs}. Raises ParserUnavailable if the shared
    parser cannot be read, because a SHORTER block generated from a broken
    checkout used to pass the assertion in silence."""
    mod = _parser()          # deliberately NOT wrapped: fail loud, not short
    return {
        "removing": sorted(_REMOVING_PROGRAMS),
        "copy/move": sorted(_COPY_VERBS),
        "flag-destination": sorted(n for n, _f, _r in _WRITER_FLAGS),
        "consuming": sorted(_CONSUMING),
        "archive-removing": sorted(_ARCHIVE_REMOVERS),
        "overwriting": sorted(_OVERWRITERS),
        "in-place-edit": sorted(set(_AWK_NAMES) | set(_PERMISSION_VERBS)),
        "simple-writers": sorted(_SIMPLE_WRITERS),
        "program-argument-hosts": sorted(_PROGRAM_ARG_HOSTS),
        "cwd-extractors": sorted(_CWD_EXTRACTORS),
        "wrappers-local": sorted(_EXTRA_WRAPPERS),
        "command-string-hosts": sorted(_CMD_STRING_HOSTS),
        "interpreter-hosts": sorted(_C_HOSTS),
        "shared-parser-mutators": sorted(mod._MUTATORS),
        "shared-parser-state": sorted(mod._STATE_VERBS),
        "shared-parser-exec": sorted(mod._EXEC_MUTATORS),
        "wrappers-shared": sorted(mod._WRAPPERS),
    }


# What the block CANNOT enumerate, stated inside the block so the reader gets it
# with the list rather than three files away.
_NOT_ENUMERATED = (
    "git subcommands (checkout, switch, restore, rm, reset, stash, clean, "
    "read-tree, checkout-index, config, push, am, cherry-pick, revert)",
    "find predicates (-delete, -exec, -execdir, -ok, -okdir)",
    "redirect spellings (>, >>, &>, &>>, >|)",
    "inline write markers and the direct-write patterns",
    "protected path SHAPES (<dir>/.claude/settings*.json, scripts/g__*.py)",
    "version-suffixed interpreter spellings (python3.12 reduces to python)",
)

_VERB_BLOCK_START = "=== COVERED VERBS (generated by --verbs) ==="
_VERB_BLOCK_END = "=== END COVERED VERBS ==="


def verb_block() -> str:
    lines = [_VERB_BLOCK_START]
    for name, verbs in covered_verbs().items():
        lines.append(f"  {name}: " + " ".join(verbs))
    lines.append("  NOT ENUMERATED BY THIS BLOCK (recognised, but not by "
                 "program name):")
    for item in _NOT_ENUMERATED:
        lines.append(f"    - {item}")
    lines.append(_VERB_BLOCK_END)
    return "\n".join(lines)


def deny_target_flood(count: int) -> None:
    deny(
        f"ARMING SURFACE: this command names more than {_MAX_TARGETS} DISTINCT "
        f"paths, so this gate cannot finish testing them inside the time the "
        f"harness allows. Each distinct target costs a `realpath`, which is a "
        f"walk of lstat calls, and the cost grows with the NUMBER of targets, "
        f"not with the length of the command: measured, `rm -f <65,512 short "
        f"tokens> ~/.claude/settings.json` takes 18.5 s against 1.8 s for the "
        f"same byte count as one long word, and x8 concurrent on a loaded box "
        f"it runs 39-51 s against a 60 s kill. A killed hook writes no stdout "
        f"and empty stdout reads as ALLOW, so the ambiguity is resolved closed "
        f"instead. Repeats are free, so this is a ceiling on how many DIFFERENT "
        f"paths one command may name. Split the command, or run it against a "
        f"directory instead of listing its files."
    )


def deny_unparsed(size: int) -> None:
    deny(
        f"ARMING SURFACE: this command is {size} bytes, past the {_MAX_PARSED} "
        f"byte parse ceiling, and it carries a mutation token, so this gate "
        f"cannot tell whether it names a protected path without a parse that "
        f"would outlast the hook. Measured on this machine: 400 KB takes 14 s "
        f"through this gate and 1 MB takes 67 s, past the harness's 60 s "
        f"default, and a KILLED hook writes no stdout, which reads as ALLOW. So "
        f"the ambiguity is resolved closed rather than timed out. A command that "
        f"carries no mutation token at all is still allowed at any size, because "
        f"the parser's own first line would return nothing for it. The ceiling "
        f"costs nothing real: of 18,154 distinct Bash commands in this machine's "
        f"transcripts the largest is 32,359 bytes. Split the payload into a file "
        f"and run that instead."
    )


def deny_oversize(size: int, channel: str) -> None:
    deny(
        f"ARMING SURFACE: this command is {size} bytes and carries {channel}, "
        f"which this gate reads with shlex, and shlex is quadratic in the length "
        f"of one token (measured through this gate: 24 KB 0.19 s, 97 KB 0.79 s, "
        f"195 KB 3.13 s, 390 KB 9.72 s). Past {_MAX_SCANNED} bytes the scan is a "
        f"stall, and a stalled hook is KILLED, which writes no stdout, which the "
        f"harness reads as ALLOW. So oversize is denied rather than timed out. "
        f"The cap costs nothing real: 17,232 Bash calls in this machine's "
        f"transcripts, largest 32,359 bytes, p99 5,145, none over the cap. Split "
        f"the body into a script file and run that instead."
    )


def deny_heredoc(literal: str, _marker: str) -> None:
    deny(
        f"ARMING SURFACE: this heredoc body writes {literal} as the direct "
        f"target of a write, in the LIVE brain tree. A heredoc body is an "
        f"interpreter program inside the command string, exactly like a `-c` "
        f"argument, and it is the more common of the two here: 2,424 heredocs "
        f"fed to an interpreter against 2,221 host `-c` across 17,232 real Bash "
        f"calls, and the residual text used to claim only a `-c` body was read. "
        f"Reading the same file through the same heredoc is allowed, and so is "
        f"a heredoc that merely QUOTES this path in the document it writes; "
        f"only the path as the write's own destination is denied. {_DEV_PATH} "
        f"{_ONLY_WRITER}"
    )


def deny_interp(literal: str, marker: str) -> None:
    deny(
        f"ARMING SURFACE: this interpreter body writes {literal} (write marker "
        f"`{marker}`) in the LIVE brain tree. Reading that file through the same "
        f"`-c` is allowed; writing it is not, because it is what the harness "
        f"loads. {_DEV_PATH} {_ONLY_WRITER}"
    )


# ── main ────────────────────────────────────────────────────────────────────

def write_targets(tool_input: dict) -> list:
    out = []
    for key in ("file_path", "notebook_path", "path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            out.append(val)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                out.append(e["file_path"])
    return out


def main() -> int:
    if KERNEL_IMPORT_ERROR:
        # Before anything is parsed: every test below goes through kernel_proc,
        # and this gate is the floor, so it answers a broken floor with a deny
        # instead of the silent exit the harness reads as ALLOW.
        deny_own_import(KERNEL_IMPORT_ERROR)
        return 0
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    pid = kernel_proc.resolve_pid(payload)

    if tool in WRITE_TOOLS:
        for target in write_targets(tool_input):
            # a Write CREATES its target, so an absent `.claude` is protected
            live, why = hit(target, removing=False, verb=tool)
            if live:
                journal_deny(pid, {"target": target, "live": live, "verb": tool})
                deny_file(tool, kernel_proc.norm_path(target), live, why)
                return 0
        return 0

    if tool != "Bash":
        return 0
    command = str(tool_input.get("command") or "")
    if not command.strip():
        return 0
    brain = brain_root()
    here = kernel_proc.norm_path(str(payload.get("cwd") or "") or os.getcwd())

    # THE CAP, tested before anything reads the command, because every reader
    # below (this gate's shlex and the shared parser's) grows superlinearly with
    # one long token. Denying here is also strictly safer than denying later: an
    # oversize command that ALSO names a protected path was going to be denied
    # anyway, so nothing legitimate is lost by answering earlier.
    oversize = len(command) > _MAX_SCANNED
    if oversize:
        channel = "an interpreter `-c` body" if _C_CHANNEL.search(command) else ""
        if "<<" in command and heredoc_bodies(command):
            channel = (channel + " and a heredoc") if channel else "a heredoc body"
        if channel:
            journal_deny(pid, {"why": "oversize", "bytes": len(command),
                               "channel": channel, "command": command[:200]})
            deny_oversize(len(command), channel)
            return 0
        # NO CHANNEL: fall THROUGH to the path and tree layers rather than
        # returning. The previous version returned here, and the header claimed
        # "the path and tree layers still run on it", which was simply false:
        # `rm -rf ~/.claude/scripts` DENIED at 65,536 bytes and ALLOWED at
        # 65,537 with a comment as the padding, and QA measured the same
        # one-character bypass for `git checkout evil`, a `>` redirect into
        # hooks.json, `tee` on settings and `sed -i` on a gate body. The cap
        # exists to bound the INTERPRETER scan, which is quadratic in one token;
        # the path and tree layers are the cheap ones and there was never a
        # reason to skip them. The two inline readers are skipped below instead,
        # which is what the cap was always about, and the sibling Bash
        # tree-owner gate already runs this same parser on this same command
        # with no cap at all, so nothing new is being paid for in wall clock.

    if len(command) > _MAX_PARSED:
        try:
            triggers = tuple(_parser()._TRIGGERS) + _LOCAL_TRIGGERS
        except ParserUnavailable as exc:
            journal_deny(pid, {"why": "parser-unavailable", "detail": str(exc),
                               "command": command[:200]})
            deny_parser(str(exc))
            return 0
        if not any(t in command for t in triggers):
            return 0          # the parse would have returned [] for this too
        journal_deny(pid, {"why": "over-parse-ceiling", "bytes": len(command),
                           "command": command[:200]})
        deny_unparsed(len(command))
        return 0

    # ONLY `heredoc_write` MAY READ A HEREDOC BODY. The borrowed `scan` splits
    # on newlines and reads every body line as a sub-command, so writing a
    # DOCUMENT that quotes a dangerous command was denied:
    #
    #     cat > /tmp/notes.txt <<'EOF'
    #     rm ~/.claude/settings.json
    #     EOF
    #
    # A sweep of 21,653 real tool_use rows found 78 denies and about 25 of them
    # were this, all of them people DOCUMENTING this gate: the sections appended
    # to README-residuals and QA's own matrices. The header claimed this class
    # was fixed; only the HOST half was (which body counts as a program), never
    # the half that hands bodies to the shell parser. By this file's own
    # doctrine that is the failure that gets a gate turned off, and it was
    # firing on the people writing the gate down.
    #
    # So every path layer now sees the SHELL half only. The bodies still reach
    # `heredoc_write`, which asks the narrow question (is a protected path the
    # direct operand of a write?), and that test covers the `> <literal>` case
    # the shell parser used to catch by accident.
    shell_only = heredoc_split(command)[0]
    # BEFORE ANY PATH IS READ, and off the SHELL half only. Every layer below
    # resolves `$VAR` from this process's environment, and a command that sets
    # the variable itself makes that environment stale for that one name (see
    # kernel_proc._CMD_ASSIGNED). Reading the whole command instead would let a
    # `FOO=bar` sitting inside a heredoc DOCUMENT shadow a real variable, which
    # is the same mistake the body/shell split was made to end.
    try:
        kernel_proc.set_command_assignments(
            _parser().command_assignments(shell_only))
    except ParserUnavailable as exc:
        journal_deny(pid, {"why": "parser-unavailable", "detail": str(exc),
                           "command": command[:200]})
        deny_parser(str(exc))
        return 0
    try:
        hits = bash_targets(shell_only, str(payload.get("cwd") or ""))
        for root, verb in extra_tree_hits(shell_only, here):
            hits.append(("tree", root, verb))
        hits.extend(extra_git_hits(shell_only, here))
        hits.extend(extra_put_hits(shell_only, here))
        hits.extend(exotic_redirect_hits(shell_only, here))
        hits.extend(indirect_removal_hits(shell_only, here))
    except ParserUnavailable as exc:
        journal_deny(pid, {"why": "parser-unavailable", "detail": str(exc),
                           "command": command[:200]})
        deny_parser(str(exc))
        return 0

    ref_restore = restore_names_ref(shell_only)
    blind_cwd = cwd_unknowable(shell_only) and not names_literal_repo(shell_only)
    tested = set()
    for kind, target, verb in hits:
        if kind in ("path", "state", "glob", "iglob") and target not in tested:
            if len(tested) >= _MAX_TARGETS:
                journal_deny(pid, {"why": "target-flood", "targets": len(hits),
                                   "command": command[:200]})
                deny_target_flood(len(tested))
                return 0
            tested.add(target)
        if kind == "push":
            if target and _fold(kernel_proc.norm_path(target)) == _fold(brain):
                journal_deny(pid, {"root": target, "verb": verb,
                                   "why": "push-no-verify"})
                deny_push(brain)
                return 0
            continue
        if kind in _TREE_KINDS:
            if verb in _TREE_EXEMPT:
                continue
            if blind_cwd:
                continue          # nobody knows which tree this ran in
            if verb.startswith(("git checkout", "git switch")) and \
                    branch_creation_only(shell_only):
                continue                  # a new branch at HEAD rewrites nothing
            if target and _fold(kernel_proc.norm_path(target)) == _fold(brain):
                journal_deny(pid, {"root": target, "verb": verb, "why": "live-tree"})
                deny_tree(verb, brain)
                return 0
            continue
        if kind in ("glob", "iglob"):
            try:
                live, why = glob_hit(target, kind == "iglob")
            except ParserUnavailable as exc:
                deny_parser(str(exc))
                return 0
        elif kind in ("path", "state"):
            v = verb
            if ref_restore and v in _RESTORE_VERBS:
                v = v + " <ref>"     # not a restore of THIS branch's bytes
            live, why = hit(target, removing=verb in _REMOVING_VERBS, verb=v)
        else:
            continue                      # 'stage' stages, it does not rewrite
        if live:
            journal_deny(pid, {"target": target, "live": live, "verb": verb,
                               "command": command[:200]})
            deny_file(verb, kernel_proc.norm_path(target), live, why)
            return 0

    if oversize:
        return 0        # the two inline readers are what the cap actually bounds

    found = interpreter_write(shell_only)
    if found:
        journal_deny(pid, {"literal": found[0], "marker": found[1],
                           "why": "interpreter-write", "command": command[:200]})
        deny_interp(found[0], found[1])
        return 0

    found = program_arg_write(shell_only)
    if found:
        journal_deny(pid, {"literal": found[0], "marker": found[1],
                           "why": "program-arg-write", "command": command[:200]})
        deny_heredoc(found[0], found[1])
        return 0

    found = heredoc_write(command)
    if found:
        journal_deny(pid, {"literal": found[0], "marker": found[1],
                           "why": "heredoc-write", "command": command[:200]})
        deny_heredoc(found[0], found[1])
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _selftest(fdir: str = None) -> int:
    """Every leg through the real main(), each in its own sandbox HOME.

    The sandbox is what makes this testable at all: kernel_proc.brain_dir() is
    HOME-relative and lazy, so `$HOME/.claude` inside the sandbox IS the live
    tree for the leg, and `$HOME/wt/<name>` is a worktree of it. The benign
    legs are the point of the pair: the SAME edit one directory over must be
    allowed, or this gate makes the brain undevelopable.
    """
    import glob as _glob
    import shutil
    import subprocess
    import tempfile

    root = os.path.dirname(_HERE)
    fdir = fdir or os.path.join("registry", "fixtures", RULE_ID)
    if not os.path.isabs(fdir):
        fdir = os.path.join(root, fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1
    fixtures = sorted(_glob.glob(os.path.join(fdir, "violation*.json"))) + \
        sorted(_glob.glob(os.path.join(fdir, "benign*.json")))
    if not any(os.path.basename(f).startswith("violation") for f in fixtures) or \
       not any(os.path.basename(f).startswith("benign") for f in fixtures):
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    import gate_selftest
    failures, blocked, allowed = [], 0, 0
    for path in fixtures:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        setup = payload.pop("_setup", {}) or {}
        sandbox = tempfile.mkdtemp(prefix="arming-selftest-")
        try:
            _build_sandbox(sandbox, setup)
            body = json.dumps(payload).replace("{{SANDBOX}}", sandbox)
            # {{PAD}} keeps an oversize fixture SMALL on disk: the cap is 64 KB
            # and a literal payload would be a 64 KB file in the repo for every
            # leg that needs one.
            body = body.replace("{{PAD}}", "x" * int(setup.get("pad_bytes") or 0))
            # {{TARGETS}} expands to N DISTINCT paths. The budget this pins
            # counts distinct targets, not bytes, so a run of one repeated
            # character cannot express it: `{{PAD}}` would be one target.
            count = int(setup.get("target_count") or 0)
            if count:
                body = body.replace(
                    "{{TARGETS}}",
                    " ".join(f"/tmp/t{i}" for i in range(count)))
            env = dict(os.environ)
            for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
                      "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE",
                      "OCTO_KERNEL_OPEN", "GIT_DIR", "GIT_WORK_TREE",
                      "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR",
                      "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH",
                      # THE ONE RESERVED NAME. Since a DEFINED variable now
                      # resolves, a benign fixture that means "this variable is
                      # unknowable" is only benign while the name really is
                      # undefined, and the operator's own shell decides that.
                      # The corpus uses exactly this name for that, and the leg
                      # unsets it, so the premise is the leg's and not the
                      # shell's. One name, not a list of them.
                      "OCTO_FIXTURE_UNDEFINED"):
                env.pop(k, None)
            env["HOME"] = sandbox
            env["USERPROFILE"] = sandbox
            env["CLAUDE_SESSION_ID"] = "__selftest__"
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)],
                                input=body, capture_output=True, text=True,
                                cwd=sandbox, env=env, timeout=30)
            did_block = gate_selftest.emits_block(cp.returncode, cp.stdout)
        finally:
            for rel, _mode in (setup.get("chmod") or []):
                try:
                    os.chmod(os.path.join(sandbox, *rel.split("/")), 0o755)
                except OSError:
                    pass
            shutil.rmtree(sandbox, ignore_errors=True)

        if name.startswith("violation"):
            if not did_block:
                failures.append(f"{name} did NOT block (rc={cp.returncode})")
                continue
            blocked += 1
            want = setup.get("expect_names")
            if want and want not in cp.stdout:
                failures.append(f"{name} blocked without naming {want}")
        else:
            if did_block:
                failures.append(f"{name} WAS blocked (must allow): "
                                f"{(cp.stdout or '').strip()[:160]}")
                continue
            allowed += 1

    for assertion in (_assert_parser_load_denies,
                      _assert_own_import_denies,
                      _assert_heredoc_reader_live,
                      _assert_verb_block_current,
                      _assert_no_undeclared_dispatch,
                      _assert_covered_verbs_deny):
        ok, why = assertion()
        if not ok:
            failures.append(why)
        else:
            blocked += 1

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {blocked} block + {allowed} allow "
          f"(g__pretool__arming-surface.py vs {os.path.basename(fdir)}); "
          f"every deny names its live file, the same edit in a worktree allows, "
          f"and a gate that cannot import kernel_proc, cannot load its parser, or "
          f"cannot run its heredoc reader denies instead of allowing")
    return 0


# Probes. `{P}` is a protected FILE in the sandbox, `{D}` a protected DIRECTORY.
# A writer with no probe here is REPORTED, not skipped, which is the difference
# between a list and a measurement.
_VERB_PROBES = {
    "rm": "rm -f {P}", "unlink": "unlink {P}", "shred": "shred -u {P}",
    "cp": "cp /tmp/e {P}", "mv": "mv /tmp/e {P}",
    "install": "install /tmp/e {P}", "ln": "ln -f /tmp/e {P}",
    "rsync": "rsync -a --remove-source-files {D}/ /tmp/x/",
    "curl": "curl -o {P} https://example.invalid/x",
    "wget": "wget -O {P} https://example.invalid/x",
    "tar": "tar -x -C {D} -f /tmp/a.tar",
    "patch": "patch -o {P} /tmp/a.diff",
    "unzip": "unzip -o /tmp/e.zip -d {D}",
    "cpio": "cpio -id -D {D}",
    "gzip": "gzip {P}", "bzip2": "bzip2 {P}", "xz": "xz {P}",
    "lzma": "lzma {P}", "compress": "compress {P}", "zstd": "zstd --rm {P}",
    "zip": "zip -qm /tmp/x.zip {P}",
    "sort": "sort -o {P} /tmp/e", "uniq": "uniq /tmp/e {P}",
    "awk": "awk -i inplace '{{print}}' {P}",
    "gawk": "gawk -i inplace '{{print}}' {P}",
    "mawk": "mawk -i inplace '{{print}}' {P}",
    "busybox-awk": None,          # not a real program name on this host
    "chmod": "chmod -x {P}", "setfacl": "setfacl -m u:nobody:0 {P}",
    "chown": "chown nobody {P}", "chgrp": "chgrp nogroup {P}",
    "fallocate": "fallocate -z -l 4096 {P}",
    "ex": "ex -sc wq {P}", "ed": "ed -s {P}", "vim": "vim -c wq {P}",
    "vi": "vi -c wq {P}", "nvim": "nvim -c wq {P}",
    "openssl": "openssl enc -in /tmp/e -out {P}",
    "gpg": "gpg -o {P} -d /tmp/e.gpg",
    "split": "split -b1 /tmp/e {P}",
    "scp": "scp /tmp/e {P}", "rename.ul": "rename.ul a b {P}",
    "rename": "rename a b {P}",
    "sed": "sed -n 'w {P}' /tmp/in",
    "node": "node -e \"require('fs').writeFileSync('{P}','x')\"",
    "nodejs": "nodejs -e \"require('fs').writeFileSync('{P}','x')\"",
    "perl": "perl -e \"open(F,'>','{P}')\"",
    "ruby": "ruby -e \"open('{P}','w')\"",
    "php": "php -r \"file_put_contents('{P}','x');\"",
    "truncate": "truncate -s0 {P}", "tee": "echo x | tee {P}",
    "dd": "dd of={P} if=/dev/null", "touch": "touch {P}",
    "chattr": "chattr +i {P}",
}
# Categories that are NOT writers on their own: a wrapper or an interpreter host
# is proven through the verb it wraps, and the shared-parser tables repeat names
# already probed above.
_UNPROBED_CATEGORIES = ("wrappers-local", "wrappers-shared",
                        "command-string-hosts", "interpreter-hosts",
                        "cwd-extractors", "program-argument-hosts",
                        "shared-parser-mutators", "shared-parser-state",
                        "shared-parser-exec")


def _assert_covered_verbs_deny() -> tuple:
    """Every program the block claims as a writer must actually DENY.

    This is what turns the block from a claim into a measurement, and it is the
    assertion that would have caught `shred`: present in `_REMOVING_PROGRAMS`,
    printed in the block, dispatched by nothing, allowed in practice."""
    import shutil
    import subprocess
    import tempfile
    try:
        cats = covered_verbs()
    except ParserUnavailable as exc:
        return False, f"covered_verbs could not read the shared parser: {exc}"
    claimed = set()
    for name, verbs in cats.items():
        if name in _UNPROBED_CATEGORIES:
            continue
        claimed.update(verbs)
    missing = sorted(v for v in claimed
                     if v not in _VERB_PROBES)
    if missing:
        return False, ("no probe for claimed writer(s): " + ", ".join(missing) +
                       " (add one to _VERB_PROBES or drop the verb)")
    sandbox = tempfile.mkdtemp(prefix="arming-probe-")
    failed = []
    try:
        _build_sandbox(sandbox, {})
        prot = os.path.join(sandbox, ".claude", "settings.json")
        pdir = os.path.join(sandbox, ".claude", "scripts")
        env = dict(os.environ)
        env["HOME"] = sandbox
        env["USERPROFILE"] = sandbox
        env["CLAUDE_SESSION_ID"] = "__selftest__"
        for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "GIT_DIR",
                  "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(k, None)
        import gate_selftest
        for verb in sorted(claimed):
            tmpl = _VERB_PROBES[verb]
            if tmpl is None:
                continue
            cmd = tmpl.replace("{P}", prot).replace("{D}", pdir)
            payload = json.dumps({"tool_name": "Bash", "cwd": sandbox,
                                  "tool_input": {"command": cmd}})
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)],
                                input=payload, capture_output=True, text=True,
                                cwd=sandbox, env=env, timeout=60)
            if not gate_selftest.emits_block(cp.returncode, cp.stdout):
                failed.append(f"{verb} ({cmd[:60]})")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    if failed:
        return False, ("the block CLAIMS these and the gate ALLOWS them: " +
                       "; ".join(failed))
    return True, ""


def _assert_no_undeclared_dispatch() -> tuple:
    """Every literal this module dispatches on must appear in the block.

    Parses THIS FILE and collects every string compared against `base` or
    `sub_cmd`, whether by `==`, `!=` or `in`. QA's mutant (`elif base == "7z"`
    inside `_archive_removes`) turns this red, which the previous dict literal
    could not do because it MIRRORED those conditions instead of reading them."""
    import ast as _ast
    try:
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            tree = _ast.parse(fh.read())
    except Exception as exc:
        return False, f"cannot parse own source: {exc}"
    names = set()
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, _ast.Name) and left.id in ("base", "sub_cmd")):
            continue
        for comp in node.comparators:
            if isinstance(comp, _ast.Constant) and isinstance(comp.value, str):
                names.add(comp.value)
            elif isinstance(comp, (_ast.Tuple, _ast.List, _ast.Set)):
                for elt in comp.elts:
                    if isinstance(elt, _ast.Constant) and \
                            isinstance(elt.value, str):
                        names.add(elt.value)
    try:
        block = verb_block()
    except ParserUnavailable as exc:
        return False, f"covered_verbs could not read the shared parser: {exc}"
    undeclared = sorted(n for n in names
                        if n and f" {n}" not in block and
                        not block.endswith(" " + n))
    if undeclared:
        return False, ("this module dispatches on names the coverage block does "
                       "not carry: " + ", ".join(undeclared) +
                       " (regenerate with --verbs, or add the table)")
    return True, ""


def _assert_verb_block_current() -> tuple:
    """The generated coverage block in README-residuals must equal the tables.

    This is the mechanism behind "the list is derived": add a program to any
    dispatch table and forget to regenerate, and this fails. Without it the
    prose is a claim, and it has been a wrong claim twice."""
    readme = os.path.join(os.path.dirname(_HERE), "registry", "fixtures",
                          RULE_ID, "README-residuals.txt")
    try:
        with open(readme, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return False, f"cannot read README-residuals.txt: {exc}"
    if _VERB_BLOCK_START not in text:
        return False, ("README-residuals.txt carries no generated verb block; "
                       "run `g__pretool__arming-surface.py --verbs`")
    start = text.index(_VERB_BLOCK_START)
    end = text.index(_VERB_BLOCK_END) + len(_VERB_BLOCK_END)
    if text[start:end].strip() != verb_block().strip():
        return False, ("the coverage block in README-residuals.txt is stale: a "
                       "dispatch table changed. Regenerate with `--verbs`")
    return True, ""


def _assert_heredoc_reader_live() -> tuple:
    """The heredoc reader must still ANSWER, driven through the real function.

    Not decoration, and not a re-implementation on purpose. `_DIRECT_WRITE`
    carries regex repetition braces (`{0,2}`); they were substituted with
    `str.format` for one commit, `{0,2}` read as a format FIELD, KeyError rose
    out of `heredoc_write`, and the module-level fail-open swallowed it. The
    whole heredoc layer was off and every fixture stayed green, because an
    exception allows. A check that re-did the substitution itself would have
    stayed green too, which is why this one calls `heredoc_write` and asserts on
    what it returns: the canonical attack must come back a hit, and the same
    file READ through the same heredoc must come back None."""
    target = os.path.join(brain_root(), "settings.json")
    attack = f"python3 - <<PY\nopen('{target}','w').write('x')\nPY"
    benign = f"python3 - <<PY\nprint(open('{target}').read())\nPY"
    try:
        hit_ = heredoc_write(attack)
        miss = heredoc_write(benign)
    except Exception as exc:
        return False, (f"heredoc_write raised on the canonical shapes "
                       f"({type(exc).__name__}: {exc}); the module-level "
                       f"fail-open would turn that into an all-ALLOW")
    if not hit_:
        return False, "heredoc_write missed the canonical direct write"
    if miss:
        return False, "heredoc_write fired on a read through the same heredoc"
    return True, ""


def _assert_own_import_denies() -> tuple:
    """The gate's OWN first import, asserted the same way as the borrowed one.

    `kernel_proc.py` is inside the set this gate protects and was imported at
    module scope with nothing around it. Missing or syntactically broken, the
    process raised before `main()` existed: rc=1, empty stdout, which the
    harness reads as ALLOW. The `try/except` at the bottom of this file could
    never catch it, because the failure happens before `__main__` is reached.

    Both legs are run, because they fail at different points of the import
    machinery: a module that is NOT THERE (ModuleNotFoundError) and one that is
    there and BROKEN (SyntaxError). The gate is copied into a directory holding
    only itself, so `sys.path[0]` finds no kernel_proc; no payload and no env
    can reach this, which is the point."""
    import shutil
    import subprocess
    import tempfile
    payload = json.dumps({"tool_name": "Bash", "cwd": "/tmp",
                          "tool_input": {"command": "rm -rf ~/.claude/scripts"}})
    for leg, body in (("absent", None), ("broken", "import nosuchmodule_zzz\n")):
        sandbox = tempfile.mkdtemp(prefix="arming-ownimport-")
        try:
            copy = os.path.join(sandbox, "gate.py")
            shutil.copyfile(os.path.abspath(__file__), copy)
            if body is not None:
                with open(os.path.join(sandbox, "kernel_proc.py"), "w",
                          encoding="utf-8") as fh:
                    fh.write(body)
            env = dict(os.environ)
            env["HOME"] = sandbox
            env["USERPROFILE"] = sandbox
            env["PYTHONPATH"] = ""
            env["CLAUDE_SESSION_ID"] = "__selftest__"
            cp = subprocess.run([sys.executable, copy], input=payload,
                                capture_output=True, text=True, cwd=sandbox,
                                env=env, timeout=30)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        import gate_selftest
        if not gate_selftest.emits_block(cp.returncode, cp.stdout):
            return False, (f"own-import failure ({leg}) did NOT block "
                           f"(fail-open): rc={cp.returncode} "
                           f"out={(cp.stdout or '')[:120]!r}")
        if "kernel_proc" not in (cp.stdout or ""):
            return False, (f"own-import deny ({leg}) did not name the module it "
                           f"could not import")
    return True, ""


def _assert_parser_load_denies() -> tuple:
    """The fail-OPEN leg, asserted here because it CANNOT be a fixture.

    A fixture drives the gate through stdin, and nothing an agent can put in a
    payload makes the borrowed parser fail to import. Making it fail needs the
    loader pointed at a path that is not there, and doing that from a fixture
    would mean an env var or a setup key that redirects the parser, which is a
    disarm: point it at a module whose `scan` returns [] and the gate allows
    everything. So the assertion runs the real `main()` in a child with
    `_PARSER_PATH` rebound in memory, which no payload can reach.

    Without it the regression is invisible: QA's whole batch on a minimal
    sandbox came back all-ALLOW, and only its positive control showed that the
    parser's import of receipt_ledger.py had failed and every Bash command had
    been let through in silence."""
    import subprocess
    import tempfile
    boot = (
        "import importlib.util,sys;"
        "spec=importlib.util.spec_from_file_location('g',%r);"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "m._PARSER_PATH='/nonexistent/parser-that-is-not-there.py';"
        "sys.exit(m.main())" % os.path.abspath(__file__)
    )
    payload = json.dumps({"tool_name": "Bash", "cwd": "/tmp",
                          "tool_input": {"command": "echo hi > /tmp/x"}})
    sandbox = tempfile.mkdtemp(prefix="arming-parserfail-")
    try:
        env = dict(os.environ)
        env["HOME"] = sandbox
        env["USERPROFILE"] = sandbox
        env["CLAUDE_SESSION_ID"] = "__selftest__"
        cp = subprocess.run([sys.executable, "-c", boot], input=payload,
                            capture_output=True, text=True, cwd=sandbox,
                            env=env, timeout=30)
    finally:
        import shutil as _sh
        _sh.rmtree(sandbox, ignore_errors=True)
    import gate_selftest
    if not gate_selftest.emits_block(cp.returncode, cp.stdout):
        return False, ("parser-load failure did NOT block (fail-open): "
                       f"rc={cp.returncode} out={(cp.stdout or '')[:120]!r}")
    if "parser-that-is-not-there.py" not in (cp.stdout or ""):
        return False, "parser-load deny did not name the parser it could not load"
    return True, ""


def _build_sandbox(sandbox: str, setup: dict) -> None:
    """A live brain and a worktree of it, one directory apart. The worktree's
    `.git` is a FILE, exactly as `git worktree add` writes it, so the shared
    parser's `enclosing_worktree_root` finds the same roots it finds live."""
    live = os.path.join(sandbox, ".claude")
    for rel in ("scripts", "registry", ".githooks", ".git"):
        os.makedirs(os.path.join(live, rel), exist_ok=True)
    for rel in ("settings.json", "settings.local.json", "hooks.json"):
        _touch(os.path.join(live, rel), "{}\n")
    # the harness user config, a SIBLING of the live root, plus a neighbour one
    # character away from it that must stay writable.
    _touch(os.path.join(sandbox, ".claude.json"), '{"mcpServers": {}}\n')
    _touch(os.path.join(sandbox, ".claude.json.bak"), "{}\n")
    # PROJECT scope, the second surface. `<live>/.claude/settings*.json` is what
    # a session whose cwd is the live root loads ON TOP of the user-scope pair,
    # `<live>/.claude/commands/` is a neighbour inside the same directory that
    # must stay writable, and `<live>/vendor-ref/.claude/` is a DEEPER project
    # root of the same shape (the live tree really carries one).
    for rel in ("settings.json", "settings.local.json"):
        _touch(os.path.join(live, ".claude", rel), "{}\n")
    _touch(os.path.join(live, ".claude", "commands", "note.md"), "# stub\n")
    _touch(os.path.join(live, "vendor-ref", ".claude", "settings.json"), "{}\n")
    # a `.claude` directory of the same shape holding NO settings: the live tree
    # carries several, and they must stay removable.
    _touch(os.path.join(live, "knowledge-ref", ".claude", "commands", "x.md"), "#\n")
    # a `.claude` holding ONLY settings.local.json: the glob is `settings*.json`
    # and the local half is the per-machine registration surface, so the
    # directory is just as much a take as one holding settings.json.
    _touch(os.path.join(live, "local-only-ref", ".claude", "settings.local.json"), "{}\n")
    # a `.claude` of the same shape whose listing FAILS. `_holds_settings`
    # resolves that ambiguity CLOSED, and nothing proved it until now.
    os.makedirs(os.path.join(live, "sealed-ref", ".claude"), exist_ok=True)
    _touch(os.path.join(live, "registry", "rules.yaml"), "rules: []\n")
    _touch(os.path.join(live, ".githooks", "pre-push"), "#!/bin/sh\n")
    for name in ("qa-merge-gate.py", "g__pretool__kernel.py",
                 "g__stop__goal-anchor.py", "gate_selftest.py",
                 "receipt_ledger.py", "kernel_proc.py", "brain_doctor.py",
                 "dimension-awareness-hook.py", "merge-hooks.py", "README.md"):
        _touch(os.path.join(live, "scripts", name), "# stub\n")
    wt = os.path.join(sandbox, "wt", "state-gate")
    for rel in ("scripts", "registry", ".githooks"):
        os.makedirs(os.path.join(wt, rel), exist_ok=True)
    _touch(os.path.join(wt, ".git"), "gitdir: " + os.path.join(live, ".git") + "\n")
    _touch(os.path.join(wt, "hooks.json"), "{}\n")
    # the SAME project-scope shape one directory over: source, not loaded, and
    # the over-fire control for the whole project-scope rule.
    _touch(os.path.join(wt, ".claude", "settings.json"), "{}\n")
    _touch(os.path.join(wt, ".claude.json"), "{}\n")
    _touch(os.path.join(wt, "registry", "rules.yaml"), "rules: []\n")
    _touch(os.path.join(wt, ".githooks", "pre-push"), "#!/bin/sh\n")
    for name in ("qa-merge-gate.py", "g__pretool__kernel.py",
                 "g__stop__goal-anchor.py", "gate_selftest.py",
                 "receipt_ledger.py", "kernel_proc.py"):
        _touch(os.path.join(wt, "scripts", name), "# stub\n")
    for rel, mode in (setup.get("chmod") or []):
        try:
            os.chmod(os.path.join(sandbox, *rel.split("/")), int(mode, 8))
        except OSError:
            pass
    if setup.get("symlink"):
        src, dst = setup["symlink"]
        src = src.replace("{{SANDBOX}}", sandbox)
        dst = dst.replace("{{SANDBOX}}", sandbox)
        try:
            os.symlink(dst, src)
        except (OSError, NotImplementedError):
            pass


def _touch(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)


if __name__ == "__main__":
    if "--verbs" in sys.argv:
        try:
            print(verb_block())
        except ParserUnavailable as exc:
            # A SHORTER block generated from a broken checkout used to pass the
            # assertion in silence. Coverage that fails quiet is the thing this
            # mechanism exists to end.
            print(f"cannot generate: {exc}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    if "--selftest" in sys.argv:
        _i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's tool call
