# Octorato v8: The Arming Surface

<!-- moved-from-claude-md v10-T13 -->
The files that decide whether the gates run at all, and the PreToolUse gate that keeps an agent from rewriting them. Rule `ARCHITECTURE.arming-surface`, gate `scripts/g__pretool__arming-surface.py`, fixtures `registry/fixtures/ARCHITECTURE.arming-surface`. These paragraphs were the constitution's own text until v10 (T13), moved here so `CLAUDE.md` keeps only what every session needs. They are kept as written, with em-dashes normalised; `CLAUDE.md` now carries a short paragraph pointing here.

## The gate

Every rule here is live because ONE file registers its mechanism and ONE file is its body. Those files are the
arming surface, and until v8 nothing watched them: `~/.claude/settings.json` carries the `env` block Claude Code
injects into every hook it spawns, no PreToolUse hook watched it, and none watched the gate scripts either. The
merge gate's env was unreachable; its registration was not. `scripts/g__pretool__arming-surface.py` (PreToolUse
`*`, fail-closed) closes that: a Write/Edit or a Bash mutation (`rm`, `mv`, `sed -i`, `tee`, a `>` redirect, a
`git checkout -- <path>`) aimed at the LIVE copy of `settings.json`, `settings.local.json`, any
`<dir>/.claude/settings*.json` inside the live root (PROJECT scope, which OUTRANKS user scope: a session whose cwd
is the brain, which is what `ai-push` does, loads `~/.claude/.claude/settings.json` on top of the user-scope pair,
and that file was writable while the user-scope one was denied), `hooks.json`,
`~/.claude.json` (the harness user config, the one member of the set outside the live root: it carries
`mcpServers`, so a write there hands the next session a `command` to run at startup, and a PreToolUse hook never
sees the harness write its own state file, only the agent's), `registry/rules.yaml`, `.githooks/pre-push`, any
`scripts/g__pretool*.py` or `scripts/g__stop__*.py`,
`qa-merge-gate.py`, `gate_selftest.py`, `brain_doctor.py`, `receipt_ledger.py`, `kernel_proc.py`,
`merge-hooks.py` (the sanctioned writer of settings.json: edit it and the next legitimate run writes what you put
there) or `dimension-awareness-hook.py` is DENIED, and so is `.git/config` (it carries `core.hooksPath`, measured
`.githooks` on the live tree, so one key repoints the very pre-push this gate protects) and `registry/fixtures` FOR A WRITE
(a violation fixture rewritten so it still blocks but tests nothing leaves gate-liveness green while the gate
guards nothing; a `git checkout --` restore puts back the reviewed bytes and a removal fails the selftest loudly,
so both of those pass, after the first cost estimate for this entry turned out to be 1 when the real number was
11 and all eleven were the brain's own fixture maintenance), and so is
a whole-tree `git checkout|switch|reset --hard|stash|clean -f|read-tree -u|checkout-index -a -f` at the live root,
which would swap all of them in one move, plus `git config <name> <value>` there and EVERY route to skipping the pre-push hook, not just the flag:
`--no-verify`, `-c core.hooksPath=` and its fused spelling, the `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` and
`GIT_CONFIG_PARAMETERS` environment spellings, `GIT_DIR=` naming the repo when `-C` does not, and `chmod -x` on
the hook (clearing the execute bit is enough for git to skip it, and the shared parser was reading a dash-leading
symbolic mode as a flag). All six were measured ALLOW while the header claimed the surface was covered. The READ
shapes `git config <name>` and `--get` stay allowed.
A `checkout -b`/`-B` or `switch -c`/`-C` that names NO START POINT is NOT one of those: it makes a ref at HEAD and
rewrites no file. The start point is part of the rule, not a detail: `checkout -b tmp evil` checks `evil` out, and
an exemption that looked only at the create flag reopened the whole-tree rewrite it was carved out of, with a real
git receipt of a file reading `good` before and `EVIL` after. The exemption now needs exactly one positional after
the verb, the new branch name.
THE GATE HAS NO ALLOW-LIST. It is a DENY-LIST of recognised writer and remover verbs, so a program none of the
tables name passes SILENTLY. A hand-kept list of what is covered was wrong three cycles
running, and the first attempt at a DERIVATION was itself a hand-kept list of lists: three of its entries mirrored
`if base == …` conditions, so a recogniser added there changed nothing, and it OVER-reported (`shred` was printed
as covered while nothing dispatched it and the command allowed). Two assertions hold it down now, one per
direction and neither a list: `_assert_no_undeclared_dispatch` parses this module's own source for every string
compared against `base`/`sub_cmd` and requires it in the block, and `_assert_covered_verbs_deny` RUNS every
claimed writer through the real gate against a protected path and requires a deny, reporting any writer with no
probe. The claim is narrowed to what that supports: the block enumerates PROGRAM NAMES, and what it cannot
enumerate (git subcommands, find predicates, redirect spellings, inline write markers, path shapes) is printed
inside the block itself. Covered since: the compressors
(`gzip`/`bzip2`/`xz`/`lzma` delete their input with no flag at all), `zstd --rm`, `tar --remove-files`, `zip -m`,
`sort -o`, `uniq`, and `fallocate`, scripted editors (`ex`/`ed`/`vim` with `-c`/`-s`; an interactive `vim` is
deliberately left alone), `openssl -out`, `gpg -o`, `unzip -d`, `cpio -D`, `setfacl`, `chown`, `chgrp`, `split`.
THE BRANCH-CREATION EXEMPTION COUNTS THE STAGE, NOT THE COMMAND: `git checkout -b feat/x 2>&1` was DENIED while
the bare form allowed, because `2>&1` was read as a start point, and the corpus carries seven real instances of
the operator doing exactly that on the live tree. Same bug as the one fixed in the `config` reader a cycle
earlier, one member of the class closed and the other left open. A gate that blocks normal work gets turned off,
which is the failure this whole boundary was drawn around, and the same failure was firing on the people
DOCUMENTING this gate: the borrowed parser read every heredoc BODY line as a sub-command, so writing a document
that quotes a dangerous command denied. About 25 of 78 denies in a 21,653-row sweep were that. Every path layer
sees the SHELL half of a command now; bodies reach only the narrow heredoc reader. A `$VAR` gets ONE reading in both
directions, and the reading is whether THIS PROCESS CAN READ IT. `$HOME` was treated as unknowable while `~` was
already expanded, so the two spellings of one file disagreed and `rm -f $HOME/.claude/settings.json`, its
`${HOME}` twin, `cd $HOME/.claude && rm -f settings.json`, `cp /tmp/x $HOME/.claude/hooks.json`, a `>` redirect
into it and `git -C $HOME/.claude checkout` were all measured ALLOW against a literal and a tilde that both
denied. `kernel_proc.expand_env` resolves any variable the hook's own `os.environ` holds and leaves every other
one verbatim, called from the shared parser's `resolve` BEFORE the isabs test, which is the only place it fits:
after the join the leading `/` is gone. There is no list of variable names, because a list of knowable variables
is the same hand-kept-list disease one level up; `os.environ` is the list, and it is the one the shell will use.
`$SOMEDIR`, `$(cmd)`, a backtick and `${VAR:-x}` still abstain, so `cd "$SP/demo" && git checkout -q master`
stays allowed. A variable THE COMMAND ITSELF assigns wins over the environment, last assignment first, because
`export HOME=<sandbox> && cp hooks.json $HOME/.claude/` is a real rehearsal and resolving it from the hook aimed
it back at the brain (one false deny in a 21,241-row replay). A PREFIX assignment is not a statement and does not
shadow: bash expands `$HOME` before `HOME=/x rm -f $HOME/...` takes effect, so reading the two alike would have
been a one-space disarm. Replayed over the whole corpus the change is 1 ALLOW to DENY (a real disarm: gate bodies
copied into the live tree through `$R`) and 2 DENY to ALLOW (both false denies on a `cd "$SP/base"` into /tmp).
COST IS BOUNDED ON TWO AXES, because the byte caps could only see one. The work in the target loop grows with
TOKEN COUNT: `rm -f <65,512 short tokens> ~/.claude/settings.json` took 18.5 s against 1.8 s for the same byte
count as one long word, and x8 concurrent on a loaded box that is 39-51 s against the harness's 60 s kill, where
a killed hook writes no stdout and the silence reads as ALLOW. The invariants are now resolved once per process
(`brain_root()` was called 131,023 times for one command) and `_MAX_TARGETS` (512, against a real-traffic maximum
of 20 distinct targets) bounds the rest, with repeats free. Same shape after: 1.99 s alone, 8.85 s with eight at once on a loaded box, against the 60 s kill. Cost figures
carry their measurement mode, because a single-run best-of-five and an x8-concurrent figure for the same shape
differ by about 4x.
A command over 64 KB is capped for the two INLINE readers only. It used to return before every layer, so one
character of padding defeated every Bash deny (`rm -rf ~/.claude/scripts` denied at 65,536 bytes and allowed at
65,537); it now falls through to the path and tree layers. The fall-through carries its own 128 KB PARSE ceiling,
because the shared parser shlexes too and 1 MB measured 67 s, past the harness's 60 s kill, where a hook writes no
stdout and the silence reads as ALLOW. Above that ceiling the answer is exact rather than heuristic: no mutation
token means the parser would have returned nothing anyway, so allow; a token present means deny.
Destinations are read where the command actually puts a file, not where the last positional sits: `cp -t`,
`mv -t`, `install -t` and `--target-directory=` INVERT the order, a directory destination receives the source's
basename (`cp -r /stage/.claude <live>/x/` plants a project-scope settings directory without naming one), and
`install`, `ln -f`, `rsync`, `curl -o`, `wget -O`, `tar -x -C`, `patch -o|-d`, `awk -i inplace` and the `&>`,
`&>>`, `>|` redirects are writers the shared parser never looked at. A `find` is only treated as REMOVING when it
carries `-delete` or an `-exec rm`: labelled `find -delete` unconditionally, `find <dir>/.claude -exec cp
settings.json {} +` read as a removal, answered "nothing to take" and planted the file. The same tuple was open
in the OTHER direction, a real deleter with no `-delete` on the line, and the escaping is what hid it: the shared
splitter cuts on `;` without honouring the backslash, so `find <live>/scripts -name '*.py' -exec rm {} \;` handed
back a segment ending in a lone backslash, shlex raised, the whitespace fallback KEPT THE QUOTES, and the glob
became `<live>/scripts/*'*.py'`, matching nothing. The gate denied the spelling that cannot run in a shell and
allowed the one everyone types. A removal that reaches its paths through another program is now read off the RAW
command: `-exec`/`-execdir`/`-ok`/`-okdir` running any of ONE list of removing programs with any terminator, and a
pipe into a removing verb (`| xargs rm`, `-print0 | xargs -0`, `-I{}`, `| parallel rm`, `ls glob | xargs rm`).
The wrapper prefixes `setsid`, `flock`, `ionice`, `chrt`, `taskset -c`, `doas`, `busybox`, `parallel` and a
bundled `bash -ec` / `sh -lc` were all measured walking straight through with a plain `rm -rf ~/.claude/scripts`
and are closed; the wrapper rows are ADDED to the shared parser's own table with `setdefault`, never copied into a
second one. Still open and named in the gate header rather than left silent: `eval`, backticks, `$(…)`, brace
expansion, a variable NOBODY can read (`$UNSET`, `export HOME=$OTHER`), `find -exec sh -c`, `find -exec dd`,
`xargs -a <file>`, `taskset` with a bare mask, and the shared parser's own `shred` / `perl -pi` residuals. The set is a path shape, and it
covers the `.claude` DIRECTORY for every verb that writes: "what does it hold?" is only a question for a verb that
TAKES. Asking it of everything left two doors open, an absent destination (`mv <staged dir> <live>/x/.claude`, two
allowed steps to a project-scope settings file carrying a forged approval) and an existing empty one (`cp
settings.json <live>/knowledge/.../.claude/`, which made all eight of the empty directories a drop box). The
listing is consulted only for `rm`, `unlink`, `find -delete` and `git rm`, so those eight stay removable, and
`mkdir` never reaches the gate.
Every comparison is case-folded, because `.Claude/SETTINGS.JSON` is the same file on Windows and on macOS.

**The boundary is the COPY, not the file, and that is what keeps the brain developable by its own agent.**
`~/.claude` is the MAIN worktree of this repo and the tree the harness actually loads; every `~/.octorato/wt/*`
checkout is a sibling holding SOURCE. Editing `scripts/qa-merge-gate.py` in a worktree is normal development and
stays allowed; editing `~/.claude/scripts/qa-merge-gate.py` is a disarm and is denied. Measured against the real
commands of the session that found the hole: editing a gate script in a worktree, `ai-sync`, `brain_doctor.py
--fix` and `git checkout` in a worktree were allowed before and are allowed after; five disarm shapes flipped from
allowed to denied. A symlink whose path looks like a worktree is caught (every candidate is retested through
`realpath`), and so is `git -C ~/.claude` from anywhere. There is NO env unlock, deliberately: the variable that
lifted this rule would be writable from the very file it protects. Same stance as the kernel's state floor, the
operator's terminal is not hooked and stays the only writer. The protected set is a path SHAPE, not a list, so a
new subdirectory does not reopen it, and the 16 interpreter write markers are proven one fixture each rather than
claimed. Two INLINE channels are read, and they ask different questions because they are different things: a `-c`
argument is matched on a write marker next to a protected literal, while a heredoc DOCUMENT is matched only when
the literal is the write's own destination. Measured on 17,232 real Bash calls, the loose test on heredocs flipped
23 to deny at a precision of 2/23, and the 21 false ones were this repo editing its own header, fixtures and
CLAUDE.md; the narrow one fires on 2 of 3,296, both a command writing a test harness whose text carries the
attack literal. Commands over 64 KB carrying an inline channel are DENIED rather
than scanned, because shlex is quadratic in one token and a killed hook reads as allow (largest real command
measured: 32,359 bytes). A parser that cannot LOAD denies too, after a blanket `except` was found turning the
whole Bash half into a silent all-allow, and so does this gate failing to import its OWN `kernel_proc`: that
import sat at module scope, so a missing copy of a file the gate PROTECTS raised before `main()` existed and the
empty stdout read as ALLOW. Residuals, each with its reproduction, live in the gate's own header:
enterprise policy outside `$HOME` (root-owned, the OS is the gate there), another repo's project settings, an
ancestor directory of a deep project root in both directions, and an inline write that reaches the path through a
variable, and a destination the shell has to expand first (`{a,b}`, `$(cmd)`, `${VAR:-x}`, an
UNREADABLE variable, `eval`, a shell function, a symlink created and used in one command). A LOCAL `git merge` in the live tree is allowed and lands unreviewed
edits on every file in the set, because `qa-merge-gate` guards `gh pr merge` and nothing guards `git merge`; only
a PULL brings the reviewed remote state. The fixture pair is
`registry/fixtures/ARCHITECTURE.arming-surface`; the live count is whatever `g__pretool__arming-surface.py --selftest` prints, never a number copied into prose, because this one was stale twice before it was noticed.

## Why the merge approval is agent-proof (moved from the 2D Delegate Gate)

- **ACTIVATE** (agent + skills + persona) when an agent fits, and pair non-trivial developer work with an independent **coworking QA** counterpart (Reality Checker / Evidence Collector / Code Reviewer), always on the **judgment** tier (Claude Code → Fable; Cursor → strongest independent engine ≥ builder, see ladder bindings). The QA verdict is the merge gate, not green CI. Merges are **fail-closed** (`qa-merge-gate`): the operator approves a specific PR via `OCTO_MERGE_APPROVE=<pr>` (agent-proof env, an inline env never reaches the hook), exported in the terminal that launched Claude Code. That env is unreachable from the model's own process, and since v8 the REGISTRATION that invokes the reader of that env is protected too (`g__pretool__arming-surface.py`, see *Arming surface* above): before that gate, an agent could write an `env` block into the live `~/.claude/settings.json`, which Claude Code injects into every hook it spawns NEXT session, and self-approve without ever typing a merge command. So the honest claim is scoped: **the agent cannot self-approve through the env, and cannot rewrite the live registration or the gate body through Write/Edit or a shell mutation**; the residual is an interpreted write (a script the hook never sees inside), named with its reproduction in that gate's header. The `octo-dim approve-merge` file channel (`scripts/octo-dim.py`, no bin thunk) is an audit log only, not a gate pass: the agent owns its own process env and can forge that file, so only the harness env authorizes.
