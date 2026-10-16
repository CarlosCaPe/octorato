# Changelog

All notable changes to the Octopus Brain Framework are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project follows the **Site Semantic Versioning** scheme described in the
[Self-Growth wiki page](https://github.com/CarlosCaPe/octorato/wiki/Self-Growth#8-site-semantic-versioning)
, bot-identity commits bump PATCH, operator commits bump MINOR, and an
explicit `Octorato-Major:` commit trailer bumps MAJOR.

This log records human-meaningful framework changes. The complete
machine-generated growth ledger lives at
`knowledge/github-trending/HISTORY.md` (autonomous daily additions) and
`knowledge/repo-watch/<date>.md` (daily watchlist digests).

## [Unreleased]

### Fixes
- fix(reply-panel): cut the measured cost of the v11 reply panel without dropping a reviewer from a reply that carries claims. Measured since v11.0.0 (35 operator turns, 103 replies): the panel cost about 36% of weighted tokens. (1) The source class reads `Basis /path` (no colon), a `·` after the label and a lowercase `basis`, and reads `self` inside a path or file name as a source while a bare `self-*` word stays SELF: 17 of 35 final replies move from SELF (quorum 3) to SOURCED (quorum 1), none the other way. (2) `panel_digest.py --preflight` and a preflight inside `--panel-request --to operator` (`scripts/panel_preflight.py`) run every other reply-text Stop hook on the draft, so a later gate no longer forces an edit after the PASS (16 of 32 extra rounds). (3) A status line of at most 30 words passes while a subagent launched or messaged in this operator turn still runs (hand-back, task notification, TaskStop or kernel `exit` line read as the stop, 30-minute cap without one), at most 3 times per operator prompt; a claim-word check is a speed bump on top (11 of the 34 measured spin blocks would pass). (4) A reply that is only one `input-needed:` question for an operator-only fact, plus at most one 15-word context line, is INPUT, quorum 1, unless its footer names self; the no-menu gate reads past the label. What each change loosens is listed in `docs/architecture/v11-reply-panel.md`, "Cost controls (measured)". Selftest: 79 block and 39 allow. Tests: `test_reply_panel_source_class.py`, `test_reply_panel_status_line.py`, `test_panel_preflight.py`.
- fix(tracing): QA of the v11 tracing tasks T13 and T14. The Export_Guard now walks from the real path of the cwd (and of `CLAUDE_PROJECT_DIR`) up to and including its arm root, and any `arm.json` on the way that does not read `allow` (deny, absent field, invalid, unreadable, symlinked) denies: before, a client repo cloned into an allow arm's tree, not yet registered, exported under the outer arm's `allow`. Fixtures: that probe, a deny two levels down, an invalid `arm.json` in between, an absent field in between, and the benign twin of an allow nested in an allow (selftest 45 not spawned, 9 spawned). The Export_Flip_Gate now judges the file before and after the write with the guard's own strict reader (`policy_of_text`, imported, not copied), so an Edit that removes a repeated key the guard refuses is a flip and denies, and a Write whose repeated key the guard reads as deny passes; it also folds the Windows aliases `arm.json.` and `arm.json::$DATA` (selftest 19 block, 15 allow). The manifest schema allows `telemetry` only when `kind` is `arm`, with two negative fixtures (42 rules).
- fix(sync, security): `sync-ai-docs` never writes a mirror through a symlink. Before, every mirror, including the existing `.github/copilot-instructions.md` and `.cursorrules`, was written with a plain open that followed links: an arm whose mirror was a symlink to a file outside it (`~/.claude/hooks.json`, `~/.bashrc`) had that file overwritten with its `CLAUDE.md`, by a plain process the arming-surface gate never sees, and the arm controls both the link and the content. Now `scripts/ai_sync.py` refuses, with a warning, a mirror that is a symlink or sits under a symlinked directory (`.github`), even one pointing inside the arm, or whose path resolves outside the arm; it re-checks after creating parent directories, reads with `O_NOFOLLOW` where the OS has it, and writes a fresh `mkstemp` file in the same directory renamed over the target with `os.replace`, which never follows a link. The read side gets the same guard: when an arm's `.claude` or `.claude/CLAUDE.md` is a symlink or resolves outside the arm, sync skips that arm with a warning and writes no mirror, so a source linked to `~/.ssh/id_rsa` or a brain secret is never copied into files the arm commits; the source is read with `O_NOFOLLOW`, and one with more than one hard link (another name for a file outside the arm) is refused the same way. Named residual: a concurrent local process that swaps a parent such as `.github` for a symlink between the check and the `mkstemp` can still redirect a write; closing it needs a `dir_fd` walk with `O_NOFOLLOW|O_DIRECTORY`. A registry `instruction_file` must be a plain file name (no `/` or `\`, no leading dot, so `.git/config` and `./AGENTS.md` are refused). An instruction file of a harness that is no longer `supported` is left in the arm, never deleted, and both sync and `brain_doctor` sync-targets now WARN that it is a stale mirror; sync-targets also checks the supported harnesses' files and WARNs on a symlinked mirror. `brain_doctor` `runtime-registry` also fails a `gap` entry whose `tiers` is not null. Tests: `scripts/tests/test_ai_sync_instruction_files.py` (symlinked file for all four mirrors, symlinked `.github`, a link inside the arm, file-name rules, stale mirror; the three link cases fail with the guard removed) and `scripts/tests/test_doctor_sync_targets.py`.

### Features
- feat(pkg): kind `plugin` in `scripts/octo_pkg.py`, the package form of the Tracing_Wrapper, v11 tracing spec task T15 (AC-13, AC-17). `octo pkg wrap-plugin <upstream-dir> --out <dir>` builds the wrapper from a LOCAL upstream plugin directory (it never fetches): the upstream tree is copied unmodified except that its `plugin.json` and `hooks/hooks.json` move to `.claude-plugin/upstream-plugin.json` and `hooks/upstream-hooks.json` byte for byte, and the new `hooks/hooks.json` is the upstream list with every command replaced by exactly `python3 -I -S "${HOME}/.claude/scripts/g__wrap__export-guard.py" -- sh -c '<upstream command>'` (events, matchers, order and timeouts kept). `install --kind plugin` checks, in staging and before the signature, that the octo manifest says `kind: plugin`, that `plugin.json` declares no component path (`hooks`, `mcpServers` and the rest are refused), that there is no `.mcp.json`, and that `hooks/hooks.json` is exactly the guarded form of the upstream list, compared by re-rendering, never by parsing for intent; then tree hash and `ssh-keygen -Y` signature as for a skill. It lands at `plugins/octorato-local/<name>` with a `.claude-plugin/marketplace.json` generated from the lock and one lock row of kind `plugin`; it writes no settings file and enables nothing, so the plugin is disabled for every arm, and it prints the operator's next steps (`claude plugin marketplace add`, then a project-scope `claude plugin install` inside an allow arm). It refuses to run when `CLAUDECODE` is set and prints the command for the operator's terminal instead: a speed bump on the honest route, named as such; the boundary is the signature, the layout and the guard. `verify --all` (and so pre-push) adds the plugin ladder: tree hash, layout, signature and signer of the installed tree, every copy of it the harness makes under `plugins/` (its cache) hashed against the lock row, a plugin row with a tree under `skills/vendor` FAILs, an unlocked tree under `plugins/octorato-local` FAILs, a harness copy from this marketplace with no lock row FAILs, and the upstream `langsmith-tracing` installed outside the wrapper (a `plugin.json` naming it under `plugins/`, or an `installed_plugins.json` key) FAILs; catalogs under `plugins/marketplaces/` are listings and are not scanned. An absent plugin is a WARN whose fix is the operator's reinstall, since `sync` never installs a plugin. Upstream decision: the spec's upstream, LangSmith's `langsmith-tracing` Claude Code plugin, is not vendored and not available offline, so no third-party code was downloaded; `registry/fixtures/META.kernel-package/plugin-upstream/` is a STUB with the upstream's name, version `0.0.0-stub`, a five-event hook list and a tracer script that posts to `LANGSMITH_ENDPOINT` (default `127.0.0.1:9`). Wrapping the real upstream is the same `wrap-plugin` run on its directory. Not measured here: whether the harness installs a plugin from a local marketplace by copying it into `plugins/cache` unchanged; if it adds a file, the copy check FAILs and the spec returns to the operator (plan.md, Risks). The `plugins/` directory joins the arming surface (`known_marketplaces.json`, `installed_plugins.json`, `cache/`, `octorato-local/`) with three violation fixtures on the live copy and three benign twins writing the same relative path under the temporary HOME: selftest 299 block and 298 allow; removing the entry turns exactly the three violations red. `octo_pkg.py --selftest registry/fixtures/META.kernel-package` gains 20 plugin legs (each mutation of the in-session refusal, the layout check, the exact-list comparison, the copy hash, the upstream sweep and the plugin ladder turns its own leg red). Schema `kind` enum gains `plugin`. Tests: `scripts/tests/test_octo_pkg_plugin.py`, 23 cases under a temporary HOME.
- feat(tracing): `scripts/g__pretool__export-flip.py`, the Export_Flip_Gate of the v11 tracing spec, task T14 (AC-16). A fail-closed PreToolUse gate, wired in `hooks.json` on `Write|Edit|MultiEdit|NotebookEdit|Bash`, that denies an agent write setting an arm's `telemetry.export` to `allow`. Structural for Write, Edit and MultiEdit: when the target's name, or its real path's name, is `arm.json` or `arm.json.template` (case-folded), it computes the file as it would be after the call and parses it with the guard's strict JSON, counting repeated keys; it denies when the result says `allow` and the current file does not, so keeping an operator's `allow` (a version bump) passes. An Edit of a manifest it cannot read, and a NotebookEdit of one, deny. For Bash it is a speed bump for the honest accident: a command naming an arm manifest denies with the word `allow`, a redirect into the manifest, or a writer verb whose bytes it cannot see (cp, mv, install, ln, rsync, tee, dd, truncate); reads and `rm` pass. A payload that is not one JSON object, or an internal error, denies. No env unlock: the flip is the operator's, made outside the session. Named residuals in the header: interpreter writes without the path and value on the command line, obfuscated values or paths, git routes from history or a patch, renames by programs it does not parse. Selftest on `registry/fixtures/SECURITY.export-flip`: 17 block and 14 allow. Kernel journaling of its refusals (`_KERNEL_RULE`) lands with its registration in T18, since a journaled rule id must be registered. Tests: `scripts/tests/test_export_flip.py`, 6 cases in temp dirs. Not registered yet (T18), so `brain_doctor` `registry-orphans` FAILs on this hook until then.
- feat(tracing): `scripts/g__wrap__export-guard.py`, the Export_Guard of the v11 tracing spec, task T13 (AC-09, AC-10, AC-11, AC-17). Every Tracing_Wrapper hook command will call it with the upstream hook argv after `--`; it starts that process only when the session's arm reads `telemetry.export: allow`, and otherwise exits 0 with no output and spawns nothing. Arm_Resolution: the payload `cwd` (and `CLAUDE_PROJECT_DIR` when set) is resolved to its real path; a real path inside a brain (`$HOME/.claude` or the guard's own brain) is no arm, and a registered arm whose real root is inside a brain is dropped; arms come from `company/config/arms-paths.json` resolved as `load_arms()` does (first existing candidate), each to its real root; containment is by path component; the cwd and the project dir must resolve to the same arm, and that arm and every registered arm containing either must allow, so an allow arm nested in a deny arm stays deny. `arm.json` is opened with `O_NOFOLLOW` (a deny arm cannot borrow another arm's file through a symlink), must be a regular UTF-8 JSON object of at most 1 MiB with no repeated key, and anything but the exact string `allow` is deny. Every read or parse error is a silent deny. On allow the upstream gets the original stdin bytes and the unchanged environment (redaction untouched); its stdout is discarded and its exit code dropped, so a tracer can never block a turn. `--explain` prints the decision on stderr without spawning. Selftest on `registry/fixtures/SECURITY.export-guard`: 41 not spawned and 8 spawned, including 6 CLI legs through the real argv; mutation controls (no `O_NOFOLLOW`, no brain check, prefix containment, last-wins keys, deepest arm only) each turn a violation red. Named residuals in the script header: an `arm.json` flipped by a route the flip gate does not parse, an `env` block in an arm's own settings pointing HOME at a forged brain, and a session in an allow arm reading a deny arm's files by absolute path. The guard joins the arming surface as `g__wrap__*.py` with a violation and a benign fixture. Tests: `scripts/tests/test_export_guard.py`, 5 cases under a temporary HOME. Not registered yet (T18).
- feat(arm): `telemetry.export`, the per-arm Export_Policy of the v11 tracing spec, task T12 (AC-09). `templates/arm/arm.json.template` now ships `"telemetry": {"export": "deny"}`, so a new arm says no in writing. `schemas/skill-manifest.schema.json` accepts an optional `telemetry` object whose only key is `export`, with exactly the values `deny` and `allow`; without it, `additionalProperties: false` would have made `octo pkg install --kind arm` refuse every arm built from the new template. An absent field means `deny`. Documented in `schemas/skill-manifest.md`. Three new negative fixtures (not an object, unknown key, a value outside the two), each with its mutation control: `validate-skill-manifest.py --selftest` 40 rules exercised (was 37).
- feat(registry): phase 2 of the v11 harness spec registered, task T11 (AC-15). Four rules in `registry/rules.yaml`, each anchored in its own acceptance criterion so `CLAUDE.md` gains no prose: `ARCHITECTURE.hook-shim` (fail-closed gate, `g__shim__hook.py --selftest registry/fixtures/ARCHITECTURE.hook-shim`, which gate-liveness now runs: 65 block and 34 allow), `ARCHITECTURE.hook-projectors` (both projectors and `hook_projector.py`; `--check` exits 1 on registry drift), `ARCHITECTURE.runtime-census-gates` (the `--gates` evidence in both census records) and `ARCHITECTURE.instruction-sync` (T09). The shim's arming-surface pair joins `ARCHITECTURE.arming-surface` and the tier check (T10, AC-08) joins `ARCHITECTURE.runtime-registry`. `brain_doctor --fast`: 100 rules wired, CLAUDE.md coverage 100% (44 of 44). `docs/CAPABILITIES.md` regenerated.
- feat(harness): tier bindings per runtime, task T10 of the v11 harness spec (AC-08). `brain_doctor` `runtime-registry` now fails a `supported` entry of `registry/runtimes.yaml` whose `tiers` is not a mapping of exactly mechanical, bulk, build and judgment, each a non-empty slug; a `gap` entry stays `tiers: null`. `docs/architecture/multi-runtime.md` gains a "Tier bindings per runtime" table, one row per registry entry with its source: Claude Code `haiku`/`sonnet`/`opus`/`fable`, Cursor `composer-2.5-fast`/`gpt-5.5-medium`/`grok-4.5-fast-xhigh`/strongest independent engine (unchanged), and Gemini CLI and Codex CLI as gap rows naming what is unmeasured: Gemini's account-tier model list (the only slug in its census, `gemini-3.8-flash`, comes from the 429 of the live call) and Codex's session model (census `account_tier.model` null, plan `free`). No slug is bound without a source. The Runtimes table's hook cells and the census paragraph, stale since T06 to T08, now name the projectors and Codex's live blocking record. Tests: 4 new cases in `scripts/tests/test_runtime_registry.py`.
- feat(sync): `sync-ai-docs` writes each harness's instruction file, task T09 of the v11 harness spec (AC-07). `scripts/ai_sync.py` reads `registry/runtimes.yaml` and, beside `.github/copilot-instructions.md` and `.cursorrules`, writes the `instruction_file` of every harness whose status is `supported` into each arm from its `.claude/CLAUDE.md`: `AGENTS.md` for Codex CLI, `GEMINI.md` for Gemini CLI. A `gap` harness gets no file, so today, with both `gap`, no arm gains a file. A home path (Claude Code's `~/.claude/CLAUDE.md`), an absolute path or a `..` path is never written, and an unreadable registry falls back to the two base mirrors with a warning. Every mirror is now written only when its bytes differ, so a second run with no source change rewrites nothing (same bytes, same mtime). Like `.cursorrules`, the files are written, not committed; the arm commits them. Test: `scripts/tests/test_ai_sync_instruction_files.py`, 8 cases on a temp arm and a temp registry.
- feat(harness): `scripts/runtime_census.py --gates`, task T08 of the v11 harness spec (AC-02, AC-06). Offline leg: each fail-closed gate the projector would project (11 gates, 14 `--selftest` locators from `registry/rules.yaml`) runs its own selftest in process, with every spawn of the gate rendered as the harness's documented payload and decided by `g__shim__hook.decide()`; `supported` is supplied in process only, the shim's command line still refuses a `gap` harness. A tool the projected matcher misses is answered as the harness would (allow), so a projection gap fails the gate's violation leg; a Read or Agent leg, or a subagent (`agent_id`) leg of the three gates whose lane identity is `agent_id`, runs natively and is counted apart. Result, written to `registry/census/<harness>.json` `gates` with no timestamps (a rerun is byte-equal): a pass needs at least one deny and one allow through the shim, otherwise the selftest is `one_sided`. Codex: 11 of 14 pass, 2 one-sided (Write tree-owner: no shim deny; Bash tree-owner: no shim allow), 1 not routed (`FLOW.kernel-quota`, Read legs only), 563 denied and 402 allowed through the shim, 0 untranslatable. Gemini: 11 of 14 pass, 1 one-sided (Bash tree-owner: no shim allow), 2 not routed (`FLOW.kernel-quota`, and the Write tree-owner gate, whose only harness leg is a shell call Gemini's Write projection does not match), 563 denied and 401 allowed, 0 untranslatable. Live leg (`live_block`, `--offline` skips it), one session through the real binary from a temp directory, hook = the projected `g__pretool__arming-surface.py` entry run by a sandbox copy of `scripts/` whose `runtimes.yaml` marks only that harness supported, HOME = a sandbox whose `.claude/` is the protected tree, verdict from the files and the gate's deny journal (the precheck's own denies are cleared first). Every live-measured class now names that gate's pair as its Block_Fixture: the shell class moved from `SEC.prod-write-gate` (not in hooks.json, never projected) to `ARCHITECTURE.arming-surface` `violation_hooks_redirect.json` / `benign_hooks_redirect.json`, and a live verdict on another gate than a class's fixture gate is filed `unmeasured`. Codex CLI 0.159.3 (ChatGPT login, plan `free` from `codex app-server` account/read with only type and plan kept; the model is a named gap, the live leg did not keep it, `auth.json` read in place by codex, never copied; `--ignore-user-config --ephemeral`, hooks as `-c` session flags, no config file written; `--dangerously-bypass-hook-trust` for this run only, recorded): shell, file write and file edit violations blocked, benign twins allowed. Trust step, measured: an untrusted session-flag hook did not block the violation (0 journaled denies; the write landed: fail-open), a `-c hooks.state.<key>.trusted_hash` override is ignored, and `codex app-server` `hooks/list` exposes the key and hash, so persisting trust means writing `config.toml` (`/hooks` or `config/batchWrite`), not done here. Sandbox boundary, measured with `codex sandbox` (no model): a write outside the writable roots fails with "Read-only file system" while the same write in the workspace lands. Gemini CLI 0.62.0: unmeasured, `TerminalQuotaError` 429 ("Please retry in 4h25m"). `registry/runtimes.yaml`: codex-cli `classes_not_blocked` is now empty and its status stays `gap`; the flip is the operator's. Also fixed: an empty Write rendered as a Codex patch with an empty body line the shim refused, and a 429 dump containing `UNAVAILABLE` was recorded as 503. Tests: `scripts/tests/test_runtime_census_gates.py`, 22 cases in temp dirs.
- feat(harness): `scripts/merge-hooks-gemini.py` and `scripts/merge-hooks-codex.py`, the Hook_Projectors of the v11 harness spec (AC-04, T06 and T07), over a shared core `scripts/hook_projector.py`. They project the `PreToolUse` entries of `hooks.json` into a Gemini CLI settings.json `BeforeTool` block or a Codex CLI hooks.json `PreToolUse` block, every hook running a gate through `scripts/g__shim__hook.py`, never directly. Projected: only fail-closed gates of `registry/rules.yaml` the shim can serve (a bare `python3 <gate>.py` command): 13 hooks over 11 gates for each harness. Not projected, with the reason printed: `budget-check.py --json` (arguments), the `Agent`-only `tree-owner` entry, and 5 hooks that are not fail-closed gates. Every matcher is derived from the shim's own table `TOOL_YIELDS` (each harness tool the shim can translate into the gate's Claude tool), so a Codex Write|Edit gate projects as `^(Bash|apply_patch)$`: a `*** Begin Patch` span in a shell call is a write. Matchers are anchored regexes (Gemini tests `new RegExp(matcher)` as a substring search, bundle source), `*` is narrowed to the tools the shim translates because the fail-closed shim blocks any other, and every hook carries a 60 s timeout (60000 ms for Gemini, 60 s for Codex) above the shim's 45 s budget. Untranslatable tokens and events are written to `registry/runtimes.yaml` `unprojected` by `--update-registry`: for both harnesses the events PermissionDenied, PostToolUse, SessionStart, Stop, SubagentStart, SubagentStop, UserPromptSubmit and the matchers Agent, MultiEdit, NotebookEdit. Both harnesses are `gap`, so the default run refuses to write (exit 2) and `--check` prints the dry-run projection, exiting 1 on drift. Codex `--check` also prints the sandbox boundary, `sandbox_mode = "workspace-write"` with `[sandbox_workspace_write] writable_roots` excluding `~/.claude`; keys measured on codex-cli 0.159.3 with `codex sandbox` in a temp `CODEX_HOME` (a root outside the writable set refused with "Read-only file system", `test -w ~/.claude` false inside). Tests: `scripts/tests/test_hook_projectors.py`, 22 cases in temp dirs, including one that every projected matcher covers each harness tool the shim translates into that gate's tools and one that catches a reverted Codex matcher.
- feat(harness): `scripts/g__shim__hook.py`, the Hook_Shim of the v11 harness spec (AC-05, T05). It translates a Gemini CLI `BeforeTool` or Codex CLI `PreToolUse` payload into the Claude-shaped fields a gate reads, runs the gate, and turns its deny into exit 2 with the reason on stderr. Fail-closed: a payload it cannot read, a Gemini MCP call without an `mcp_context` that rebuilds its name, or an `apply_patch` with no readable file operation blocks; every path of a multi-file patch goes to the gate. A harness not `supported` in `registry/runtimes.yaml` is refused (both are `gap` today). Every relative tool path is joined to the payload cwd (a relative cwd blocks), every `*** Begin Patch` span in a Codex shell command is gated whatever runs it, an unpaired marker blocks, any relative path inside such a span blocks, and every path is also gated resolved through symlinks, a payload with a repeated key blocks, and a gate's `ask` or `continue: false` is read as a refusal. All gate runs of one hook call share a 45 s budget; the census records no harness hook timeout, so the projectors must write one of at least 60 s. Selftest on `registry/fixtures/ARCHITECTURE.hook-shim`: 65 block and 34 allow. Residual, by design: the shim is a speed bump for honest accidents; patch content not literally in the command (a file, xargs, shell-built markers) has no text to read and the shim inherits the target gate's own Bash residuals, so the Codex boundary is capability (sandbox writable roots excluding `~/.claude`), to be set by the T06 and T07 projectors and verified by T08 (spec addition request in `docs/architecture/v8-arming-surface.md`). The shim joins the arming surface as `g__shim__*.py`, with a violation and a benign fixture.

## [2026-10-15]: v11.1.2
### Octorato v11: no reply unreviewed
v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator now needs a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back (#417).
- **Reply gate**: `scripts/g__stop__reply-panel.py`, rule `FLOW.panel-before-reply`, fail-closed, selftest of 65 block and 23 allow cases plus 2 unit checks.
- **Quorum by source**: a reply whose Basis is SELF, or that names no source, needs 3 distinct reviewers; a sourced reply needs 1.
- **Operator-only hatches**: `panel-skip` in the operator's own prompt waives one turn; `OCTO_REPLY_PANEL=off` in the launching shell waives the session.
- **Shared receipt reader**: `receipt_ledger.panel_receipts_for` returns every validated receipt; the send gate's behaviour is unchanged (96 block and 34 allow cases on `registry/fixtures/FLOW.panel-before-send`; its default selftest, against `registry/fixtures/COMMS.outward-send-gate`, prints 90 block and 61 allow).
- **Windows test suite**: 50 tests that failed on a Windows host are fixed at the root cause, with no deleted tests and every skip a measured probe.
- **Hook stdin as UTF-8**: Claude Code writes the hook payload as UTF-8 JSON, but on Windows Python reads stdin in the ANSI code page, so the reply gate digested any reply with an accent or a middle dot to a hash no panel receipt could match. 53 of the 54 hook scripts that read the payload with `sys.stdin.read()` or `json.load(sys.stdin)` now reconfigure stdin to UTF-8 at module level. `scripts/tests/test_hook_stdin_utf8.py` pipes UTF-8 bytes into the reply gate with `PYTHONUTF8` and `PYTHONIOENCODING` unset and checks the reported digest against `panel_digest`, and checks every stdin reader for the reconfigure. Known gap: `g__pretool__arming-surface.py`, left for the operator's own edit and listed in the test so it cannot pass silently.
- Contract and residuals R-01 to R-13: `docs/architecture/v11-reply-panel.md`. Spec: `docs/specs/202610141340-v11-reply-panel/`, CONVERGED on converge pass 9 with 22 of 22 acceptance criteria met.

### Fixes
- fix(sync): `ai-sync` (`cycle`) now re-projects what it pulls. A cycle that integrated a hooks.json change exited 0 without running `merge-hooks.py`, so the harness kept the old hook set and `brain_doctor --fast` failed `hooks-runtime-sync`. The post-integrate steps of `pull` (merge hooks, Cursor projection, leak-guard, stale connectome and memory index, package sync, fast doctor and gate receipt) live in one `post_integrate()` shared by both verbs; cycle runs it when the integrate moved HEAD, before push so the hooks-drift guard sees a reconciled tree, and runs the doctor after push. Arm sync stays with `push()`. Before integrating, cycle runs push's FATAL hooks-drift guard (now the shared `hooks_drift_ok()`) against the pre-pull hooks.json and refuses to overwrite settings.json hooks nobody adopted yet, with the same adopt/discard message; the `pull` verb is unchanged. Test: `scripts/tests/test_ai_sync_cycle_post_integrate.py`.

### Features
- feat(gates): `COMMS.no-menu-question`: fail-closed Stop gate against closing a reply on a choice question; `/choice` decides, only the irreducible operator step remains, as a step with its command. Config in `registry/no-menu-question.yaml`, hatch `menu-ok`.

## [2026-10-15]: v11.1.1
### Octorato v11: no reply unreviewed
v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator now needs a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back (#417).
- **Reply gate**: `scripts/g__stop__reply-panel.py`, rule `FLOW.panel-before-reply`, fail-closed, selftest of 65 block and 23 allow cases plus 2 unit checks.
- **Quorum by source**: a reply whose Basis is SELF, or that names no source, needs 3 distinct reviewers; a sourced reply needs 1.
- **Operator-only hatches**: `panel-skip` in the operator's own prompt waives one turn; `OCTO_REPLY_PANEL=off` in the launching shell waives the session.
- **Shared receipt reader**: `receipt_ledger.panel_receipts_for` returns every validated receipt; the send gate's behaviour is unchanged (96 block and 34 allow cases on `registry/fixtures/FLOW.panel-before-send`; its default selftest, against `registry/fixtures/COMMS.outward-send-gate`, prints 90 block and 61 allow).
- **Windows test suite**: 50 tests that failed on a Windows host are fixed at the root cause, with no deleted tests and every skip a measured probe.
- **Hook stdin as UTF-8**: Claude Code writes the hook payload as UTF-8 JSON, but on Windows Python reads stdin in the ANSI code page, so the reply gate digested any reply with an accent or a middle dot to a hash no panel receipt could match. 53 of the 54 hook scripts that read the payload with `sys.stdin.read()` or `json.load(sys.stdin)` now reconfigure stdin to UTF-8 at module level. `scripts/tests/test_hook_stdin_utf8.py` pipes UTF-8 bytes into the reply gate with `PYTHONUTF8` and `PYTHONIOENCODING` unset and checks the reported digest against `panel_digest`, and checks every stdin reader for the reconfigure. Known gap: `g__pretool__arming-surface.py`, left for the operator's own edit and listed in the test so it cannot pass silently.
- Contract and residuals R-01 to R-13: `docs/architecture/v11-reply-panel.md`. Spec: `docs/specs/202610141340-v11-reply-panel/`, CONVERGED on converge pass 9 with 22 of 22 acceptance criteria met.

### Features
- feat(gates): `COMMS.no-menu-question`: fail-closed Stop gate against closing a reply on a choice question; `/choice` decides, only the irreducible operator step remains, as a step with its command. Config in `registry/no-menu-question.yaml`, hatch `menu-ok`.

---

### Other
- chore(gitignore): ignore skills/.trash, the harness parking dir for removed skills (#425)

## [2026-10-15]: v11.1.0
### Octorato v11: no reply unreviewed
v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator now needs a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back (#417).
- **Reply gate**: `scripts/g__stop__reply-panel.py`, rule `FLOW.panel-before-reply`, fail-closed, selftest of 65 block and 23 allow cases plus 2 unit checks.
- **Quorum by source**: a reply whose Basis is SELF, or that names no source, needs 3 distinct reviewers; a sourced reply needs 1.
- **Operator-only hatches**: `panel-skip` in the operator's own prompt waives one turn; `OCTO_REPLY_PANEL=off` in the launching shell waives the session.
- **Shared receipt reader**: `receipt_ledger.panel_receipts_for` returns every validated receipt; the send gate's behaviour is unchanged (96 block and 34 allow cases on `registry/fixtures/FLOW.panel-before-send`; its default selftest, against `registry/fixtures/COMMS.outward-send-gate`, prints 90 block and 61 allow).
- **Windows test suite**: 50 tests that failed on a Windows host are fixed at the root cause, with no deleted tests and every skip a measured probe.
- **Hook stdin as UTF-8**: Claude Code writes the hook payload as UTF-8 JSON, but on Windows Python reads stdin in the ANSI code page, so the reply gate digested any reply with an accent or a middle dot to a hash no panel receipt could match. 53 of the 54 hook scripts that read the payload with `sys.stdin.read()` or `json.load(sys.stdin)` now reconfigure stdin to UTF-8 at module level. `scripts/tests/test_hook_stdin_utf8.py` pipes UTF-8 bytes into the reply gate with `PYTHONUTF8` and `PYTHONIOENCODING` unset and checks the reported digest against `panel_digest`, and checks every stdin reader for the reconfigure. Known gap: `g__pretool__arming-surface.py`, left for the operator's own edit and listed in the test so it cannot pass silently.
- Contract and residuals R-01 to R-13: `docs/architecture/v11-reply-panel.md`. Spec: `docs/specs/202610141340-v11-reply-panel/`, CONVERGED on converge pass 9 with 22 of 22 acceptance criteria met.

### Features
- feat(gates): `COMMS.no-menu-question`: fail-closed Stop gate against closing a reply on a choice question; `/choice` decides, only the irreducible operator step remains, as a step with its command. Config in `registry/no-menu-question.yaml`, hatch `menu-ok`.

---

### Features
- feat(gates): no-menu-question, decide with /choice instead of asking (#422)

## [2026-10-15]: v11.0.1
### Octorato v11: no reply unreviewed
v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator now needs a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back (#417).
- **Reply gate**: `scripts/g__stop__reply-panel.py`, rule `FLOW.panel-before-reply`, fail-closed, selftest of 65 block and 23 allow cases plus 2 unit checks.
- **Quorum by source**: a reply whose Basis is SELF, or that names no source, needs 3 distinct reviewers; a sourced reply needs 1.
- **Operator-only hatches**: `panel-skip` in the operator's own prompt waives one turn; `OCTO_REPLY_PANEL=off` in the launching shell waives the session.
- **Shared receipt reader**: `receipt_ledger.panel_receipts_for` returns every validated receipt; the send gate's behaviour is unchanged (96 block and 34 allow cases on `registry/fixtures/FLOW.panel-before-send`; its default selftest, against `registry/fixtures/COMMS.outward-send-gate`, prints 90 block and 61 allow).
- **Windows test suite**: 50 tests that failed on a Windows host are fixed at the root cause, with no deleted tests and every skip a measured probe.
- **Hook stdin as UTF-8**: Claude Code writes the hook payload as UTF-8 JSON, but on Windows Python reads stdin in the ANSI code page, so the reply gate digested any reply with an accent or a middle dot to a hash no panel receipt could match. 53 of the 54 hook scripts that read the payload with `sys.stdin.read()` or `json.load(sys.stdin)` now reconfigure stdin to UTF-8 at module level. `scripts/tests/test_hook_stdin_utf8.py` pipes UTF-8 bytes into the reply gate with `PYTHONUTF8` and `PYTHONIOENCODING` unset and checks the reported digest against `panel_digest`, and checks every stdin reader for the reconfigure. Known gap: `g__pretool__arming-surface.py`, left for the operator's own edit and listed in the test so it cannot pass silently.
- Contract and residuals R-01 to R-13: `docs/architecture/v11-reply-panel.md`. Spec: `docs/specs/202610141340-v11-reply-panel/`, CONVERGED on converge pass 9 with 22 of 22 acceptance criteria met.

---

### Other
- docs(spec): harness independence and opt-in tracing (next v11 minor) (#418)

## [2026-10-15]: v11.0.0
### Octorato v11: no reply unreviewed
v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator now needs a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back (#417).
- **Reply gate**: `scripts/g__stop__reply-panel.py`, rule `FLOW.panel-before-reply`, fail-closed, selftest of 65 block and 23 allow cases plus 2 unit checks.
- **Quorum by source**: a reply whose Basis is SELF, or that names no source, needs 3 distinct reviewers; a sourced reply needs 1.
- **Operator-only hatches**: `panel-skip` in the operator's own prompt waives one turn; `OCTO_REPLY_PANEL=off` in the launching shell waives the session.
- **Shared receipt reader**: `receipt_ledger.panel_receipts_for` returns every validated receipt; the send gate's behaviour is unchanged (96 block and 34 allow cases on `registry/fixtures/FLOW.panel-before-send`; its default selftest, against `registry/fixtures/COMMS.outward-send-gate`, prints 90 block and 61 allow).
- **Windows test suite**: 50 tests that failed on a Windows host are fixed at the root cause, with no deleted tests and every skip a measured probe.
- **Hook stdin as UTF-8**: Claude Code writes the hook payload as UTF-8 JSON, but on Windows Python reads stdin in the ANSI code page, so the reply gate digested any reply with an accent or a middle dot to a hash no panel receipt could match. 53 of the 54 hook scripts that read the payload with `sys.stdin.read()` or `json.load(sys.stdin)` now reconfigure stdin to UTF-8 at module level. `scripts/tests/test_hook_stdin_utf8.py` pipes UTF-8 bytes into the reply gate with `PYTHONUTF8` and `PYTHONIOENCODING` unset and checks the reported digest against `panel_digest`, and checks every stdin reader for the reconfigure. Known gap: `g__pretool__arming-surface.py`, left for the operator's own edit and listed in the test so it cannot pass silently.
- Contract and residuals R-01 to R-13: `docs/architecture/v11-reply-panel.md`. Spec: `docs/specs/202610141340-v11-reply-panel/`, CONVERGED on converge pass 9 with 22 of 22 acceptance criteria met.

---

### Other
- release(v11): cut Octorato v11.0.0, no reply unreviewed (#419)

## [2026-10-15]: v10.1.0
### Features
- feat(v11): no reply unreviewed, panel quorum by source; Windows test-suite fixes (#417)
### Other
- docs(changelog): backfill v10.0.0 (#416)

## [2026-10-13]: v10.0.0
### Octorato v10: low friction, easy entry
Every check from v7 to v9 stays; v10 makes them cheaper to live with and easier to start.
- **One-command install**: `python3 ~/.claude/scripts/quickstart.py` after the clone wires the Claude Code hooks, sets `core.hooksPath`, runs the fast doctor and writes a first spec; a fresh-clone CI job fails the run past 5 minutes (#379).
- **Friction ledger and replay**: every refusal is counted from the transcript and `octo friction` reports it per check with median and p95 latency; a private replay corpus of 1,841 real cases (2026-09-06 to 2026-10-13) blocks a change that drops a refusal that was right (#380, #397, #401, #414).
- **Send check reads the ask**: "send it" counts in English or Spanish, a task notification after an ask still carries it, and a plain read of the support script is not a send (#382, #389, #412).
- **Fewer false Stop blocks**: goal-anchor retires a closed root, never anchors a steer, an ack or an obstacle report, and counts a mention by whole words. Like for like on the same 2,974 Stops of 35 recorded sessions, its blocks went from 220 to 38 (17.3%, target at most 25%); the gate writes a read receipt per Stop and the replay reproduces 145 of the 146 receipt-era decisions (99.3%), so the figure is rated on what the gate recorded, not on history no replay can rebuild (#385, #398, #411, #414).
- **Faster budget check**: a spend cache answers in 85 to 254 ms at the median instead of 7.2 s per spawn; a cache up to 15 minutes old is fresh, one from this month up to 24 hours old answers at once and refreshes in the background (#383, #408).
- **A visible brain**: `octo dash` writes one offline HTML page of specs, reviews and live runs; a status line shows the gate receipt, live processes and the active spec (#378).
- **Shorter constitution**: `CLAUDE.md` went from 25,506 to 11,551 tokens by the doctor's own estimator, English only, failing above 12,000 (#392, #395, #400).
- **Re-review after a base update**: `/requa <pr>` confirms a pull request changed only by merging master and records a QA receipt for the new head (#391, #395, #401).
- **A SELF verdict demands the live source**: `delegate-check` and the heartbeat print, on every SELF lean, the line that asks for the live source before answering (#406).
- Read after the cut, not before: over the first 7 days of friction data after release the send check's false-positive rate on its labelled sample must stay under 15%; `octo friction` prints it per check.

## [2026-10-13]: v9.15.0
### Features
- feat(replay): rate goal-anchor fidelity on receipt-era Stops and close T28 (AC-10 amended) (#414)

## [2026-10-13]: v9.14.7
### Other
- docs(v10): release docs for v10.0.0 across README, FAQ, roadmap, tour and wiki (#399)
- docs(changelog): backfill v9.14.6 (#413)

## [2026-10-12]: v9.14.6
### Other
- v10 Convergence 3: T24 Stop digest lookback, T25-T27 send-gate fixtures (#412)

## [2026-10-12]: v9.14.5
### Fixes
- fix(goal-anchor): T20, blocks to 14.7% of the d5d609e baseline on a like-for-like replay (#411)

## [2026-10-12]: v9.14.4
### Other
- docs(claude-md): cut 976 tokens and bound the budget estimator above cl100k (#400)

## [2026-10-12]: v9.14.3
### Fixes
- fix: close the minor v10 QA follow-ups (requa textconv, budget fixtures, replay dedup) (#401)

## [2026-10-12]: v9.14.2
### Other
- v10 Convergence 2: plan section and goal-anchor read receipt (T19) (#398)
- docs(changelog): backfill v9.14.1 (#410)

## [2026-10-09]: v9.14.1
### Fixes
- fix(budget): a stale cache of this month answers at once (v10 AC-22 amended, T23) (#408)

## [2026-10-09]: v9.14.0
### Features
- feat(delegate): a SELF verdict demands the live source (v10 FR-09, AC-23) (#406)

## [2026-10-09]: v9.13.3
### Fixes
- fix(silence-watcher): leave Trash and Spam out of the mail sensor (#407)
### Other
- docs(changelog): backfill v9.13.2 (#404)

## [2026-10-08]: v9.13.2
### Fixes
- fix(octo): sandbox USERPROFILE in the octo dash selftest and tests (#403)
### Other
- docs(changelog): backfill v9.13.1 (#402)

## [2026-10-07]: v9.13.1
### Other
- v10 Convergence 1: executable /requa verifier (T17) and claude-md-budget (T18) (#395)

## [2026-10-07]: v9.13.0
### Features
- feat(replay): stateful replay for Stop gates that keep session state (v10 T16) (#397)
### Other
- chore(brain): sync after daily reflection (#396)

## [2026-10-07]: v9.12.1
### Other
- test(arming-surface): pin Write and Edit to the live hooks.json (#394)

## [2026-10-07]: v9.12.0
### Features
- feat: ai-pull runs the fast doctor; /requa re-QA after a base update (v10 T08) (#391)

## [2026-10-07]: v9.11.3
### Other
- docs(spec): v10, low friction and easy entry (#376)

## [2026-10-07]: v9.11.2
### Other
- docs(claude-md): cut the constitution to 11.8k tokens, English-only (#392)

## [2026-10-07]: v9.11.1
### Fixes
- fix(send-gate): one reader for the support script's arguments, mentions in the digest (#368)

## [2026-10-07]: v9.11.0
### Features
- feat(octo): octo dash and the status line (v10 phase 4, visible) (#378)

## [2026-10-07]: v9.10.4
### Other
- perf(v10): phase 2 friction, fast budget-check from a spend cache (T07) (#383)

## [2026-10-07]: v9.10.3
### Fixes
- fix(stop-gates): v10 phase 2, cut Stop-gate friction (T05, T06) (#385)

## [2026-10-07]: v9.10.2
### Other
- ci(version-bump): heal CHANGELOG daily instead of after every merge (#388)
- docs(changelog): backfill v9.10.1 (#390)

## [2026-10-07]: v9.10.1
### Fixes
- fix(send-gate): a command naming the support script is a send unless it is one plain read (#389)
### Other
- docs(changelog): backfill v9.10.0 (#386)

## [2026-10-06]: v9.10.0
### Features
- feat(send-gate): read the send ask the way the operator writes it (v10 T04) (#382)
### Other
- docs(changelog): backfill v9.9.0 (#384)

## [2026-10-06]: v9.9.0
### Features
- feat(v10): phase 3 entry, one-command install that wires hooks and writes a first spec (#379)
### Other
- docs(changelog): backfill v9.8.0 (#381)

## [2026-10-06]: v9.8.0
### Features
- feat(friction): v10 phase 1, measure gate friction (T01-T03) (#380)
### Other
- docs(changelog): backfill v9.7.0 (#377)

## [2026-10-06]: v9.7.0
### Features
- feat(wa-latido): detect a rejected client version and relay bridge auto-update results (#375)
### Other
- docs(changelog): backfill v9.6.1 (#374)

## [2026-10-06]: v9.6.1
### Fixes
- fix(gates): close three Windows path spellings the arming-surface gate allowed (#372)
### Other
- docs(changelog): backfill v9.6.0 (#373)

## [2026-10-06]: v9.6.0
### Features
- feat(skills): add eleven role skills for everyday assistant jobs (#369)
### Other
- docs(changelog): backfill v9.5.1 (#371)

## [2026-10-06]: v9.5.1
### Fixes
- fix(gates): Windows portability of three gate selftests and two live holes (#370)
### Other
- docs(changelog): backfill v9.5.0 (#367)

## [2026-10-06]: v9.5.0
### Features
- feat(commands): add /choice, carry one idea to a decision (#365)
### Other
- docs(changelog): backfill v9.4.0 (#366)

## [2026-10-06]: v9.4.0
### Features
- feat(commands): add /next, a plain-language status of the session (#364)
### Other
- docs(changelog): backfill v9.3.0 (#362)

## [2026-10-03]: v9.3.0
### Features
- feat(wa-watch): optional all-chats coverage for the silence watcher (#360)
### Other
- docs(changelog): backfill v9.2.0 (#359)

## [2026-10-03]: v9.2.0
### Features
- feat(gates): require a panel receipt for every outward message send (#358)
### Other
- docs(changelog): backfill v9.1.2 (#357)

## [2026-10-02]: v9.1.2
### Fixes
- fix(qa-gate): any GH_REPO, PR URL or API path naming a protected repo gates (#354)
### Other
- docs(changelog): backfill v9.1.1 (#355)

## [2026-10-02]: v9.1.1
### Fixes
- fix(receipts): read a converge receipt from its anchored entry (#353)
### Other
- docs(changelog): backfill v9.1.0 (#352)

## [2026-10-02]: v9.1.0
### Features
- feat(qa-gate): a QA PASS approves the commit it reviewed (#350)
### Other
- docs(changelog): backfill v9.0.4 (#348)

## [2026-10-01]: v9.0.4
### Fixes
- fix(doctor): python-deps reads module lists, markers and includes correctly (#347)
### Other
- docs(changelog): backfill v9.0.3 (#346)

## [2026-10-01]: v9.0.3
### Fixes
- fix(scripts): move curation gates off the decommissioned Groq llama-3.3 model (#344)
### Other
- docs(changelog): backfill v9.0.2 (#345)

## [2026-10-01]: v9.0.2
### Fixes
- fix(doctor): python-deps probes distributions, not import names (#343)
### Other
- docs(changelog): backfill v9.0.1 (#342)

## [2026-10-01]: v9.0.1
### Other
- ci: run scripts/tests on every pull request, and record two v9 residuals (#341)
- docs(changelog): backfill v9.0.0 (#340)

## [2026-10-01]: v9.0.0
### Octorato v9: done is a verdict
On a LARGE task the builder no longer grades its own work. "Done" is a verdict an independent pass computes against the spec, in three layers:
- **A spec a script can read**: a spec declares `Spec-Format: ears-1`, writes its acceptance criteria in EARS with a Glossary subject, keeps at most 3 open markers, and its plan uses the task grammar `T## [AC-##] <path>: <action>`. `scripts/spec_lint.py` checks all of it with the standard library only, so coverage of criteria by tasks is computed, not judged (rule `FLOW.spec-contract`).
- **Verdict skills**: `sdd-analyze` checks the plan against the spec before any code is written, and `sdd-converge` judges every criterion against the code and tests afterwards. It appends the missing work to `plan.md`, or leaves the file byte-identical and returns `CONVERGE-VERDICT: CONVERGED`. Both run as verifier subagents on the judgment tier; `sdd-implement` and `sdd-review` no longer tick or pass criteria.
- **Receipt and gate**: a SubagentStop reflex records the verifier's verdict as a `converge` receipt, and this repository's `.githooks/pre-push` runs `spec_lint.py --push-range` on every pushed ref. A spec cannot become `Status: converged` in a push unless the latest anchored receipt for that exact directory says CONVERGED and is newer than the newest code commit on the branch (rule `FLOW.done-is-a-verdict`). The doctor check `spec-contract` re-lints every spec on disk.

Every ears-1 spec lives in `docs/specs/<yyyymmddHHMM>-<feature-name>/` from creation and never moves, because the verdict, the receipt and the gate are keyed on that path. What v9 does not do, stated plainly: the gate is this repository's own pre-push hook, so a spec in another repository gets the linter and the skills but no gate; the push stanza can be skipped or disarmed from a worktree; receipts are local to one machine; and the verifier persona is chosen by the main loop. These are among the residuals measured, each with its bound, in `docs/architecture/v9-done-is-a-verdict.md`.

## [2026-10-01]: v8.5.1
### Fixes
- fix(v9): close the push-gate bypasses found by the phase 3 QA (#337)
### Other
- docs(changelog): backfill v8.5.0 (#336)

## [2026-09-30]: v8.5.0
### Features
- feat(v9): the converge receipt and the push gate (phase 3) (#335)
### Other
- docs(changelog): backfill v8.4.0 (#334)

## [2026-09-30]: v8.4.0
### Features
- feat(sdd): v9 phase 2, done is a verdict (sdd-analyze + sdd-converge) (#333)
### Other
- docs(changelog): backfill v8.3.1 (#332)

## [2026-09-30]: v8.3.1
### Fixes
- fix(receipts): skip refused handbacks; stamp handback runs by their report (#330)
### Other
- docs(changelog): backfill v8.3.0 (#331)

## [2026-09-30]: v8.3.0
### Features
- feat(sdd): v9 phase 1, a spec a script can read (ears-1 + spec_lint) (#327)
### Other
- docs(changelog): backfill v8.2.3 (#329)

## [2026-09-30]: v8.2.3
### Fixes
- fix(receipts): read a QA verdict delivered through SubagentHandback (#328)
### Other
- docs(changelog): backfill v8.2.2 (#325)

## [2026-09-29]: v8.2.2
### Other
- chore(registry): record reflex-triage decisions for two recurrent lessons (#324)
- docs(changelog): backfill v8.2.1 (#323)

## [2026-09-28]: v8.2.1
### Other
- docs(changelog): backfill v8.0.2 through v8.2.0; record three reflex-triage decisions (#322)

## [2026-09-24]: v8.2.0
- feat(outward-send): send-ok typed in an autonomous chat releases a third-party send (#321)

## [2026-09-24]: v8.1.0
- feat(outward-send): autonomous chats waive the send ask, by private allowlist (#319)

## [2026-09-22]: v8.0.3
- docs: plain-words front door, long tour to docs/ANATOMY.md, kernel explained everywhere (#317)

## [2026-09-22]: v8.0.2
- docs(reflection): log the session's hours to the company time ledger before the memory step (#318)
- docs(changelog): backfill v8.0.1 (#315)

## [2026-09-17]: v8.0.1
- docs(v8-kernel): state the release criterion as brain_doctor prints it (#314)
- docs(changelog): backfill v8.0.0 (#313)

## [2026-09-17]: v8.0.0
### Octorato v8: the kernel
Every run now passes through four primitives, enforced by hooks, scripts and git, not by prose:
- **PROCESS**: every session and every subagent has a pid, a parent, a worktree, a quota and an exit status (`scripts/kernel_proc.py`, `octo ps|top`). Quotas are enforced at the tool boundary in the one hot-path gate; a breached process is starved, not killed.
- **ISOLATION**: one writer per tree and per file lane, denied not advised (`g__pretool-write__tree-owner.py`, `g__pretool-bash__tree-owner.py`); a whole-tree git verb or a Bash mutation aimed at another live process's file names that process, its type and its age. The arming surface (settings, hooks, gates, registry, fixtures, pre-push) is not writable by a hooked process.
- **JOURNAL**: an append-only, hash-chained record per process, refusals and receipts included, replayable and verifiable (`octo replay --verify`).
- **PACKAGE**: skills carry a signed semver manifest with a tree hash and a tracked lockfile, verified by the doctor and by pre-push; arms are validated and installed, not signed (`octo pkg install|verify|lock|sync`). Every one of the brain's own 233 skills now carries a `skill.json`, and the coverage is a live ladder (`skill-manifests`), not a state.
Release criterion, read off the six doctor checks it names: `kernel-process-live`, `kernel-isolation-gate`, `kernel-quota-live` and `kernel-replay` PASS, `packages-verified` proven by its fixture at an empty lock, and `skill-manifests 233/233`. What v8 does not do, stated plainly: it cannot kill or suspend a running agent and it does not schedule; both stay out of scope (`docs/architecture/v8-kernel.md`).

## [2026-09-17]: v7.9.2
- chore(skills): a skill.json manifest for every existing skill (v8 packages) (#287)

## [2026-09-15]: v7.9.1
- fix(doctor): resolve a deny to the checkout that fired it (#307)

## [2026-09-15]: v7.9.0
- feat(kernel): phase 5, packages installable like services (v8) (#282)

## [2026-09-15]: v7.8.0
- feat(gate): the arming surface is not writable by a hooked process (#299)

## [2026-09-15]: v7.7.4
- fix(scripts): make the brain read text as UTF-8 on Windows (#306)

## [2026-09-09]: v7.7.3
- fix(kernel): make the v8 isolation gates and the journal work on Windows (#302)

## [2026-09-09]: v7.7.2
### Other
- fix(scripts)+feat(comms): windows-proof gate selftests; outward-send gate requires an explicit send ask (#277)
- docs(changelog): backfill v7.7.1 (#298)

## [2026-09-07]: v7.7.1
- fix(kernel): an ending must not be able to create a process (#294)

## [2026-09-07]: v7.7.0
- feat(kernel): phase 3, per-process quotas in the hot-path gate (v8) (#291)

## [2026-09-07]: v7.6.0
- feat(kernel): phase 4, every refusal and every receipt in the journal, replay proven (v8) (#293)

## [2026-09-07]: v7.5.0
- feat(kernel): phase 2, one writer per tree and per lane, enforced (v8) (#292)

## [2026-09-07]: v7.4.0
- feat(kernel): phase 1b, the octo CLI (ps, top, replay, journal, bench) (v8) (#290)
- docs(changelog): backfill v7.3.0 (#289)

## [2026-09-07]: v7.3.0
- feat(kernel): phase 1a, process table and hash-chained journal (v8) (#280)
- docs(changelog): backfill v7.2.5 (#279)

## [2026-09-07]: v7.2.5
- docs(architecture): v8 kernel plan, panel-reviewed (process, isolation, journal, package) (#278)
- docs(changelog): backfill v7.2.4 (#276)

## [2026-09-07]: v7.2.4
- fix(wa-soporte): bridge identity from private config, fail-closed without it (#275)
- docs(changelog): backfill v7.2.3 (#274)

## [2026-09-07]: v7.2.3
- docs(i18n): English descriptions for 71 skills and 10 script headers (#273)
- docs(changelog): backfill v7.2.2 (#272)

## [2026-09-06]: v7.2.2
- docs(changelog): backfill v7.2.1 + triage decision for the session-isolation lesson (#271)

## [2026-09-06]: v7.2.1
- docs: long-document revision pass (changelog, README, capability manifest, architecture) (#270)

## [2026-09-06]: v7.2.0
### Features
- feat(ci): version-bump heals CHANGELOG.md through an auto-merged bot PR (#268)
### Other
- docs(changelog): backfill v7.1.0 (#267)

## [2026-09-06]: v7.1.0
### Features
- feat(doctor): stale-merged-branches audit (#266)
### Other
- docs(changelog): promote the v7.0.0 notes from Unreleased to the dated entry (#265)

## [2026-09-06]: v7.0.0
**v7.0.0 "Nothing Ships Unverified"**

### The contract
An outward action (mail, chat, PR merge, deploy, release) leaves the brain only with machine receipts that a hook wrote in the harness process and a consumer re-verified against something the model does not own. v4 made an unwired rule a corruption; v6 made every gate prove it blocks; v7 makes a send without receipts impossible at the tool boundary, and states the residual plainly: the transcripts are files under HOME, so an anchor is a bar and a trail, never a proof. The only unforgeable boundary is the harness environment.
### Receipts (accumulated, v6.25.0 to v6.26.0)
- Receipt ledger (`scripts/receipt_ledger.py`, `~/.claude/.cache/receipts/`): seek receipts written by `r__posttool__receipt-seek.py` with the harness `tool_use_id`, honored only when that id names a real seek tool_use in the current turn; gate receipts written by `brain_doctor` on a clean tree, keyed on the git tree hash of `scripts/`, `registry/` and `hooks.json`; QA receipts written by `r__subagent-stop__qa-receipt.py` from a subagent's `QA-VERDICT` / `QA-SCOPE`, honored only from this session's subagent transcript with harness fields, last verdict, whole-token scope, QA persona.
- One outward-send gate (`g__pretool-mcp__outward-send.py`, PreToolUse on mail send/reply/forward, WhatsApp send, and Bash sends found by argv token): denies without a gate receipt, on an absence claim without a seek, on an unsourced attribute in a consent context, on a first-person promise, and on a Re:/Fwd: mail send without its thread. 35 violation and 14 benign fixtures, one per bypass five adversarial QA cycles demonstrated.
- `qa-merge-gate` requires a QA receipt for the PR on top of the operator's `OCTO_MERGE_APPROVE`; `.githooks/pre-push` runs `brain_doctor --gate-receipt`, so a push and a receipt are one event.
### Floor and triage
- Enforcement floor FORCED 27/27 gateable (100%), waivers 0: five formerly waived rules recorded as detector or reflex by design (`v7_decision`), `FLOW.budget-halt` promoted to fail-closed with path-scoped caps and a `spend_json` source; `waiver-age` voids any waiver undated or older than 90 days.
- `incident-fixture-coverage`: a memory naming a brain mechanism must resolve to a live script and, for a gate, a fixture pair. `fixture-seeds-tracked`: a fixture file git would not ship fails the doctor. `reflex-triage`: every recurrent lesson carries a decision in `registry/reflex-triage.yaml` (10 gate, 21 demote), zero pending.
- Hardening found on the way: git exports `GIT_DIR`/`GIT_INDEX_FILE` to hooks, so every doctor and selftest subprocess now scrubs them; `git update-index --assume-unchanged` no longer hides a gate edit.
### Release criterion (printed by brain_doctor at this tag)
Floor 100%, waived 0, 29 gate selftests live, incident-fixture coverage 100%, reflex-triage 0 pending, 41 checks passed.

## [2026-09-06]: v6.26.0
### Features
- feat(v7): reflex-triage decisions for every recurrent lesson (phase 5 to zero) (#263)
### Other
- docs(changelog): backfill v6.25.0 and v6.25.1 (#262)

## [2026-09-05]: v6.25.1
### Fixes
- fix(v7): ship the fixture seeds git was ignoring; doctor asserts every seed is tracked (#261)

## [2026-09-05]: v6.25.0
### Features
- feat(v7): receipt ledger, outward-send gate, QA receipt, waiver retirement, incident-fixture coverage (#260)
### Other
- docs(changelog): backfill v6.24.0 and v6.24.1 (#259)

## [2026-09-05]: v6.24.1
### Other
- docs(architecture): v7 plan, nothing ships unverified (#258)

## [2026-09-05]: v6.24.0
### Features
- feat(gate): block unsourced absence claims in outward drafts without a seek receipt (#257)
### Other
- docs(changelog): backfill v6.23.1 (#256)

## [2026-09-04]: v6.23.1
### Fixes
- fix(registry): single anchor line for Do-it-today; backfill CHANGELOG v6.23.0 (#255)
### Other
- docs(changelog): backfill v6.21.4 through v6.21.6 (#254)

## [2026-09-03]: v6.23.0
### Features
- feat(gate): block unsourced classifying attributes in outward drafts (#250)

## [2026-09-03]: v6.22.0
### Features
- feat(connectome): index life-memories as a third seekable graph (#248)

## [2026-09-03]: v6.21.6
### Fixes
- fix(connectome): fold accents in the tokenizer, on both sides (#249)

## [2026-09-03]: v6.21.5
### Fixes
- fix(security): resolve the leak blocklist from the main checkout, not the worktree (#252)

## [2026-09-02]: v6.21.4
### Fixes
- fix(memory): parse hookless compacted index entries (recall + corpus-coverage) (#247)

## [2026-09-01]: v6.21.3
### Fixes
- fix(fixtures): stop tracking derived wa-guardia selftest DBs (#245)

## [2026-09-01]: v6.21.2
### Fixes
- fix(gate): make the merge gate agent-proof (close self-approval hole) (#244)

## [2026-08-26]: v6.21.1
### Other
- brain-sync: per-chat bridge declaration + memory body-scoring recall (#243)

## [2026-08-26]: v6.21.0
### Features
- feat(gate): commit-msg English-only gate for the public octorato repo (#220)

## [2026-08-26]: v6.20.6
### Fixes
- fix(runners): install the extensionless bash twin on Windows (#240)

## [2026-08-26]: v6.20.5
### Fixes
- fix(release): changelog-only merges cut no tag; ai-sync heals drift (#239)

## [2026-08-26]: v6.20.4
Nothing yet: the next release harvests this section.

---

### Other
- chore(brain): ignore the local wrapper of the Chrome native host (#222)

## [2026-08-25]: v6.20.3
Nothing yet: the next release harvests this section.

---

### Other
- chore(brain): daily reflection (#242)

## [2026-08-24]: v6.20.2
Nothing yet: the next release harvests this section.

---

### Other
- reflection 24-Aug: absence proven by label, not by shape (#241)

## [2026-08-21]: v6.20.1
### Fixes
- fix(changelog): backfill releases v6.14.0 through v6.20.0 (#237)

## [2026-08-21]: v6.20.0
### Features
- feat(readme): hero terminal demo, real footage of doctor plus leak gate (#236)

## [2026-08-21]: v6.19.0
### Features
- feat(skill): gate lessons from the OpenBot runtime gateway (#235)

## [2026-08-21]: v6.18.0
### Features
- feat(skill): cross-link AstrBot sandbox and MCP client patterns (#234)

## [2026-08-21]: v6.17.7
### Other
- chore(brain): session reflection (#233)

## [2026-08-19]: v6.17.6
### Fixes
- fix(gate): goal anchor with a filter and regression fixtures (#232)

## [2026-08-19]: v6.17.5
### Fixes
- fix(impact-radius): filter worktrees, collapse directories, reject patterns as a concept (#231)

## [2026-08-19]: v6.17.4
### Other
- chore(brain): session close 2026-08-19 (#230)

## [2026-08-19]: v6.17.3
### Fixes
- fix(gates+doctor): three mechanisms that reported themselves live while blind (#227)

## [2026-08-18]: v6.17.2
### Other
- update: registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/con-espera.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/humano-desde-el-telefono.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/puente-sin-api-sends.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/sin-espera.db (#229)

## [2026-08-18]: v6.17.1
### Fixed
- fix(ai-sync): co-tenancy is counted per **working tree and host**, not per session.
  Counting it per session punished exactly the sessions that had already isolated
  themselves, and its message told them to fork a worktree they were already in.
  `_is_repo()` now uses `git rev-parse --is-inside-work-tree`: ai-sync had refused to
  run inside a worktree, where `.git` is a file rather than a directory.
- fix(ai-sync): the semver tag **only moves on the trunk**. From a dimension branch it
  tagged a commit that the squash left orphaned, which is how tag v6.15.3 was cut and
  later withdrawn. Pushing from a branch now opens the PR instead of ending in silence.
- fix(check-generic): scans the **current tree**, not always `$HOME/.claude`. From a
  worktree it read an empty index and printed "clean, scanned 0 staged file(s)" with
  twelve files left unexamined.
- fix(wa-latido): measures and heals the bridge **where it lives**. After the cutover it
  kept reading the local replica, refreshed every 5 minutes, so the stamp never appeared
  inside the 40s window, and its healing started the local binary, cloning the WhatsApp
  session.
### Features
- feat(gate): `FLOW.do-it-today`: fail-closed Stop gate against deferring my own work.
  A pending item counts only when it is an irreducible operator step or a measured
  blocker, and in both cases it travels with its exact command.
- feat(wa-soporte): `--archivo` sends attachments through the support channel; the file
  travels to the bridge's own disk and both intermediate copies are always deleted,
  including when the send fails.
### Other
- docs(changelog): record the fixes made during the session (#228)

## [2026-08-18]: v6.17.0
### Features
- feat(wa-soporte): send attachments with --archivo (#226)

## [2026-08-18]: v6.16.0
### Features
- feat(gate): wire do-it-today as a fail-closed Stop gate (#225)

## [2026-08-18]: v6.15.4
### Fixes
- fix(ai-sync): co-tenancy per tree and host, and running inside a worktree (#224)

## [2026-08-18]: v6.15.2
### Fixes
- fix(wa-latido): measure and heal the bridge where it lives, not where it used to (#223)

## [2026-08-14]: v6.15.1
### Other
- reflection 14-Aug: access-is-not-attention, wire the trigger (#221)

## [2026-08-14]: v6.15.0
### Features
- feat(vigia): add whatsapp alert sink to wa-sin-respuesta (WA_VIGIA_CANAL=whatsapp) (#219)

## [2026-08-14]: v6.14.3
### Other
- reflection 14-Aug: confirmed-input-is-not-closure lesson (#218)

## [2026-08-12]: v6.14.2
### Fixes
- fix(memoria): read ALL entries in a compacted index line (#217)

## [2026-08-12]: v6.14.1
### Other
- brain: smaller resident index, silence watcher, and three new gates (#215)

## [2026-08-12]: v6.14.0
### Features
- feat(4d): Provenance footer paths must be absolute and openable (#210)

## [2026-08-04]: v6.13.0
### Features
- feat(brain): session chat guard, the complement of the silence watcher
- feat(brain): silence watcher, so a client left without a reply is not overlooked

## [2026-08-04]: v6.12.6
### Other
- Track the bridge heartbeat and catch an unlinked account (#213)

## [2026-07-28]: v6.12.5
### Other
- brain: skill index diet + connectome walks the cold subtrees (#212)

## [2026-07-28]: v6.12.4
### Other
- reflection 2026-07-28: state the blind scope of a verification (#211)

## [2026-07-26]: v6.12.3
### Fixes
- fix(connectome): name cross-layer gaps for what they measure (#209)

## [2026-07-24]: v6.12.2
### Other
- reflect: send-ack-is-not-delivery lesson (#208)

## [2026-07-23]: v6.12.1
### Fixes
- fix(brain): stable manifest sort + backfill CHANGELOG v6.0.1..v6.3.0 (#192)

## [2026-07-23]: v6.12.0
### Features
- feat(brain): bulk-fetch delegation gate (turn ledger + Stop audit) (#207)

## [2026-07-23]: v6.11.0
### Features
- feat(brain): inject today's weekday as data in the 4D reminder (#206)

## [2026-07-20]: v6.10.0
### Features
- feat(brain): chat-context block-once gate on outbound chat sends (#205)

## [2026-07-20]: v6.9.0
### Features
- feat(brain): link /ai-sync and daily-reflection as one ritual (#204)

## [2026-07-17]: v6.8.1
### Other
- chore: session sync (hannon, mudanza, mascotas, responsivas) (#203)

## [2026-07-16]: v6.8.0
### Features
- feat: graphify deep-learn: code-graph skill + connectome shrink-guard (#202)

## [2026-07-13]: v6.7.3
### Other
- chore(brain): refresh connectome + CAPABILITIES after multi-runtime (#201)

## [2026-07-10]: v6.7.2
### Other
- sync (#200)

## [2026-07-10]: v6.7.1
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md: MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Fixes
- fix(multi-runtime): Grok cache_r + Cursor MCP census + Q2 parity (#198)

## [2026-07-10]: v6.7.0
### Features
- feat(skills): agent-browser real-mouse protocol for React-class widgets; whatsapp-bridge outbound anti-spam discipline (#199)

## [2026-07-10]: v6.6.0
### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md`: brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor first-class;
  Q2 MCP census is runtime-aware; identity = engine, OS = Octorato.
- feat(routing): model ladder is **tier-first, vendor-second** (mechanical · bulk ·
  build · judgment). Claude Code bindings unchanged (Haiku/Sonnet/Opus/Fable);
  Cursor+xAI bindings added (`composer-2.5-fast` / mid-Grok / `grok-4.5*` /
  strongest independent ≥ builder). Skill `model-routing-by-complexity` rewritten.
- feat(finops): `_pricing.py` meters xAI Grok list prices (grok-4.5, grok-4.3,
  grok-4.20-*, grok-build-0.1) alongside Anthropic; family heuristics for unknown
  Grok slugs.

### Changed
- docs(Getting-Started): prerequisites accept Claude Code **or** Cursor; Step 1
  documents `merge-hooks-cursor.py` for Cursor operators.
- docs(4D): Q2 no longer hard-requires `claude mcp list` inside Cursor sessions.
- chore(delegate-gate): nudge text uses vendor-agnostic tier names.

---

### Features
- feat(multi-runtime): wire Cursor+Grok as first-class peers (tier-first ladder, xAI pricing, runtime-aware Q2)

## [2026-07-10]: v6.5.0
### Features
- feat(client-doc-lint): fiscal-note (IVA) check + tax clause in cotizacion-legal-baseline (#196)

## [2026-07-07]: v6.4.1
### Fixes
- fix(ai-sync): empty-cycle guard + tree-always-returns-to-target invariant (#195)

## [2026-07-07]: v6.4.0
### Features
- feat(commands): add missing /ai-sync command (canonical sync had no invocable skill) (#194)

## [2026-07-07]: v6.3.1
### Other
- docs(skill): whatsapp bridge send-dial + liveness/verification gotchas (#193)

## [2026-07-06]: v6.3.0
### Features
- feat(brain): wire the deliverable-complete-before-send stop gate (no future-tense
  self-promises in paste-ready drafts) via `scripts/g__stop__draft-promise.py` (#191).

## [2026-07-06]: v6.2.0
### Features
- feat(brain): deliverable-complete-before-send stop gate for draft promises (initial wiring).

## [2026-07-02]: v6.1.0
### Features
- feat(templates): brand-neutral quote DOCX/PDF generator.

## [2026-07-02]: v6.0.1
### Other
- docs(changelog): backfill v5.9.1, v5.10.0, v6.0.0 via changelog-sync.

## [2026-07-02]: v6.0.0
- No user-facing change beyond the version bump.

## [2026-07-02]: v5.10.0
### Features
- feat(v6): "from coverage to enforcement": the gate-liveness harness. Every fail-closed
  gate now ships a `--selftest` that feeds it a `registry/fixtures/<rule-id>/violation.json`
  (must block) and `benign.json` (must allow) through its real main path; a shared
  `scripts/gate_selftest.py` runs both legs and the mandatory benign leg makes a
  block-everything gate FAIL, so gaming the harness is impossible.
- feat(doctor): new `gate-liveness` check runs every gate's selftest and a computed
  `enforcement-floor` ledger line (`FORCED N/M gateable (P%, selftest-proven) | detect-tier |
  waived | coverage`), never hand-edited, FAILing on a false fail-closed label. Floor moved
  from 11/19 (58%) to 14/20 (70%).
- feat(schema): `rules.schema.json` requires an `EXIT_CODE --selftest` proof for any
  fail-closed rule whose gate blocks a PreToolUse/Stop tool-call (wired-or-corrupt §8 risk 1).
- feat(G1): `CODE.cite-sources` promoted to a Stop block-once gate (provenance footer);
  waiver closed.
- feat(G2): `GIT.version-control` partial fail-closed gate (`g__pretool-bash__git-discipline.py`):
  deny force-push to main/master and `_old/_backup/_final/_copy` filenames.
- feat(G3): `FLOW.graph-before-grep` narrow fail-closed gate (deny recursive brain-content
  grep with no seek this turn; the 3 legit grep classes pass); waiver closed.
### Refactors
- refactor(relabel): `canon-heal`, `drift-self-heal`, `impact-radius` are DETECTORs not
  REFLEXes (they self-execute), each with a firing `--selftest`.
### Notes
- Deferred to a follow-up behind a telemetry week (false-positive risk): D1 injection-scan,
  D2 machine-register greeting detector, D5 no-pause proposal detector. The STAYS-REFLEX list
  (4D obedience, delegate verdicts, tool choice, identity, mood-inference) stays un-forced by
  design; coverage remains 100% and is never conflated with the 70% enforcement floor.

---

### Features
- feat(doctor+schema): gate-liveness check, enforcement-floor ledger, schema teeth
- feat(G3): FLOW.graph-before-grep narrow fail-closed gate
- feat(G2): GIT.version-control partial fail-closed gate
- feat(G1): CODE.cite-sources is now a fail-closed block-once gate
- feat(harness): gate-liveness fixtures + --selftest on the existing fail-closed gates
### Fixes
- fix(gates): strip env/command wrapper tokens before the git/gh anchor (QA HIGH)
### Other
- chore(manifest): regenerate docs/CAPABILITIES.md for v6 rules and scripts
- docs(v6): record the coverage-to-enforcement shift; close wired-or-corrupt risk 1
- test(harness): prove the prover: broken gate must FAIL the doctor
- refactor(relabel): canon-heal, drift-self-heal, impact-radius are DETECTORs not REFLEXes
- audit(registry): D4 dry-run-first is ask-on-narrow-trigger, residual documented

## [2026-07-02]: v5.9.1
### Other
- docs(changelog): backfill v5.8.0 and v5.9.0 from tags and releases
- docs(coverage): reconcile corpus-coverage prose to honest FAIL-armed 100%

## [2026-07-02]: v5.9.0
### Features
- feat(doctor): arm corpus-coverage teeth, FAIL on any uncovered rule
- feat(registry+doctor): wire skills canon + memory-directive class, honest corpus coverage
### Fixes
- fix(review): detector asserts full security canon + runs in doctor; preserve never-gives-up stance

## [2026-07-02]: v5.8.0
### Features
- feat(routing): model ladder v2, Opus build default, Fable pinned for all judgment
### Fixes
- fix(review): ladder coherence pass from QA findings
### Other
- docs(changelog): self-heal v5.7.0 entry via changelog-sync

## [2026-07-01]: v5.7.0
### Features
- feat(sync): publish-wiki mechanism, docs/wiki to the GitHub wiki on push
### Fixes
- fix(review): wiki publish fires only from master/main
- fix(docs): reconcile stale claims across README, wiki, hooks doc, roadmap
### Other
- docs(changelog): self-heal v5.6.0 entry via changelog-sync

## [2026-07-01]: v5.6.0
### Release self-heal
- New `scripts/changelog-sync.py`: reconciles missing CHANGELOG entries from semver tags, promoting the curated `[Unreleased]` body into the newest missing version and pulling GitHub Release notes (commit-subject fallback) for the rest. Dry-run by default, `--check` for CI, `--apply` idempotent.
- `brain_doctor --fix` repairs `release-drift` locally by running changelog-sync; the entry still lands through the normal PR flow.
- `brain-version-bump` prepends a non-empty `[Unreleased]` body to the GitHub Release notes, so the curated summary reaches the Release even when the CHANGELOG commit lags behind the tag.

## [2026-07-01]: v5.5.0
### Doctor teeth
- Waiver expiry enforced: a gateable fail-open rule whose `waiver.expires` is missing, unparseable, or past now counts as UNWAIVED and fails the meta-gate.
- `release-drift` is bidirectional: the newest semver tag ahead of the CHANGELOG top now WARNs (releases cut without entries), with tags sorted by semver.
- New `registry-anchor-ambiguity` check: a rule anchor that substring-covers another rule's anchor line, or covers 2+ anchor lines, WARNs with the ambiguous pairs.
- New `corpus-coverage` WARN-only Coverage Ledger: skills canon (ULTRA RULE / MANDATORY / NON-NEGOTIABLE) and memory feedback directives join the denominator, so coverage can no longer read 100% from CLAUDE.md headings alone.

### Gates fail closed
- `.githooks/pre-push`: missing gate inputs (lineage doctor, registry, capability manifest, Python interpreter) now block the push instead of silently skipping. A constitutional gate must never vanish silently.
- `qa-merge-gate.py`: a crash after a merge/publish path is identified exits 2 (fail-closed) instead of silently opening the gate.
- `secrets-grep-guard.py`: a bare pipe to jq/python/awk no longer counts as a redactor; only visible masking passes (sed/awk substitution, cut field selection, grep -o, an explicit redact script).

### Registry honesty
- check-generic.py rows remodeled: the PrePush mechanism is `.githooks/pre-push` (it inlines its own scan); check-generic.py fires via the ai-push runner.
- FLOW.budget-halt waiver reason corrected: budgets.yaml is active, every `action_on_breach` is `alert` by operator choice, so HARD_STOP is unreachable by config.
- COMMS.no-pause got its own distinct anchor; duplicate grafo-gate hook removed from hooks.json.

### Docs
- CHANGELOG backfilled v4.1.0 through v5.4.0; README badge and narration updated to the v4 registry + v5 manifest state; wired-or-corrupt.md phases marked shipped.

## [2026-06-29]: v5.4.0
- Waived the 7 known fail-open gateable rules with operator-signed, expiry-dated waivers so the meta-gate could arm.
- Armed the meta-gate teeth: any NEW gateable rule left fail-open and unwaived now FAILs and blocks the push.
- Propagated v5 manifest + gate + real budget-halt/digest across wiki, FAQ, whitepaper, and README.

## [2026-06-29]: v5.3.0
- Fail-closed meta-gate: `gateable: true` demands `enforcement: fail-closed` or an operator-signed waiver (#180).
- Classified the full rule corpus with explicit `gateable` flags; gate-shape is derived from the mechanism so omission cannot evade the gate.

## [2026-06-26]: v5.2.1
- Reflected v5 (capability manifest + gate) across README, wiki, FAQ, and whitepaper (#179).

## [2026-06-26]: v5.2.0
- Flipped capability-manifest freshness to a pre-push hard block, after cross-machine determinism was verified.

## [2026-06-26]: v5.1.0
- Scheduled the daily brain digest (slos / watchdog / finops) via a local systemd timer; it reads local session data, so no dataless CI cron.

## [2026-06-26]: v5.0.0
Release name: "Capability Manifest".

- One generated manifest: `docs/CAPABILITIES.md` is produced from the live capability set by `scripts/capability_manifest.py` and regenerated on every push; hand narration retired.
- Anti-regression gate: `brain_doctor` asserts the manifest is fresh, extending Wired or Corrupt from the rule corpus to every capability.
- FinOps budget halt wired for real: `budget-check.py` runs as a PreToolUse[Agent] gate, registered as `FLOW.budget-halt`.
- Counts reconciled to the brain's own rules (231 skills, 167 agents, 13 divisions); inflated counts were caught during review.
- Honest deferrals recorded: local-data digest needs a local schedule, and the pre-push hard block waited for determinism proof (landed in v5.2.0).

## [2026-06-25]: v4.3.1
- Declared the jsonschema dependency in requirements.txt and propagated it via ai-push (#175).

## [2026-06-25]: v4.3.0
- Cursor support: hooks.json is projected into the native `~/.cursor/hooks.json` (#174).

## [2026-06-25]: v4.2.1
- 4d-reminder fires last with the verdict ask at string end; dropped the duplicate grafo-turn-reset hook (#173).

## [2026-06-23]: v4.2.0
- `brain_doctor` closes the create-to-register loop (RULE #1 Phase 5): a new hook script lands together with its registry row (#172).

## [2026-06-23]: v4.1.1
- Documented the Wired or Corrupt (RULE #1) architecture everywhere (#171).

## [2026-06-23]: v4.1.0
- Phase 4b: bidirectional 100% anchor coverage (D4), drift self-heal, remaining gaps closed (#170).

## [2026-06-23]: v4.0.0
Release name: "Wired or Corrupt".

The brain stopped trusting its own prose. Most of CLAUDE.md was discipline the model could skip; only a small fraction had a real reflex. RULE #1 inverts that. Every rule must be wired, an unwired rule means the brain is CORRUPT, and brain_doctor enforces it. A missing mechanism blocks the push. No exceptions.

### Added: the registry

- **RULE #1 (constitutional keystone)**: every CLAUDE.md rule maps to a live mechanism in `registry/rules.yaml`, or the brain is CORRUPT. Self-wired: its own mechanism is `brain_doctor`, invoked from `.githooks/pre-push`. (`CLAUDE.md` §"RULE #1", `docs/architecture/wired-or-corrupt.md`)
- **The rule registry**: `registry/rules.yaml` (42 rules, 100% of CLAUDE.md anchors covered) + `registry/rules.schema.json`, validated like skill manifests.
- **brain_doctor enforcement**: D0 bootstrap self-check, D1 schema, D2 anchors (both directions, fail-closed), D3 per-rule wiring, a printed Coverage Ledger, and a `--registry` gate the pre-push runs. Kills the phantom-script class: a documented-but-absent hook can no longer ship.
- **OO mechanism hierarchy**: `Gate`/`Reflex`/`Detector`/`Presence` with polymorphic `verify()`; the Presence-escape-hatch closed in the schema so a model-behavior label cannot dodge a real gate.
- **Hook-naming policy**: `registry/naming-policy.yaml`. New hook scripts must follow `<prefix>__<event>__<slug>.py` (prefix agrees with kind); the 18 existing scripts are grandfathered, zero churn.

### Fixed

- **The drift defect**: `brain-memory-recall.py`, the brain's life-memory reflex, was documented as wired but never fired because the live `settings.json` had drifted from the tracked `hooks.json`. Reconciled via `merge-hooks.py`. The reflex is live and surfacing memories again.

## [2026-06-23]: v3.24.0
### Features
- feat(brain): Phase 3: hook-naming convention + grandfather (rename dropped) (#168)

## [2026-06-23]: v3.23.0
### Features
- feat(brain): Phase 2: OO mechanism hierarchy + schema hardening (#167)

## [2026-06-23]: v3.22.0
### Features
- feat(brain): Phase 1: Wired or Corrupt 100% coverage + fail-closed (#166)

## [2026-06-23]: v3.21.0
### Features
- feat(brain): Phase 0: Wired or Corrupt (RULE #1 registry + brain_doctor gate) (#165)

## [2026-06-20]: v3.20.0
### Features
- feat(brain): track brain-memory-recall + arm-recall hooks in hooks.json; compress MEMORY.md index (#164)

## [2026-06-20]: v3.19.0
### Features
- feat(brain): add brain-memory-recall UserPromptSubmit hook (#163)

## [2026-06-19]: v3.18.0
### Features
- feat(brain): add ownership-by-authorship skill (ownership = git authorship, not repo location) (#162)

## [2026-06-18]: v3.17.1
### Fixes
- fix(hook): inbox-sweep uses in:all (includes Spam and Trash) (#161)

## [2026-06-18]: v3.17.0
### Features
- feat(brain): arm-recall UserPromptSubmit hook (arm-side twin of connectome-heartbeat) (#158)

## [2026-06-18]: v3.16.0
### Features
- feat(brain): no-pause hook also catches ask-permission-to-continue endings (#159)

## [2026-06-18]: v3.15.0
### Features
- feat(brain): ULTRA RULE: adversarially verify the operator, never accept a claim on his word (#160)

## [2026-06-17]: v3.14.1
### Fixes
- fix(cadence): rule 6 flattery openers (good/great question, thanks all, good news) + rule 12 happy-to closings (#157)

## [2026-06-16]: v3.14.0
### Features
- feat(hooks): add inbox-sweep-reflex UserPromptSubmit hook (#155)
### Fixes
- fix(brain): harden core from Opus self-review (leak, secrets-guard, drift, dupe) (#156)

## [2026-06-14]: v3.12.0
### Features
- feat(brain): 4 reflex hooks: secrets guard, config-ship verify, claim-verify stop, cadence machine-register rules (#154)

## [2026-06-14]: v3.11.0
### Features
- feat(brain): capability-census UserPromptSubmit hook (#153)

## [2026-06-13]: v3.10.1
### Other
- chore(canon): re-render stale skill/agent counts (220+ -> 230+) (#151)

## [2026-06-13]: v3.10.0
### Features
- feat(brain): ULTRA RULE: machine register, no human-social filler (#152)

## [2026-06-13]: v3.9.1
### Other
- chore(funding): add GitHub Sponsors handle to FUNDING.yml (#150)

## [2026-06-13]: v3.9.0
### Features
- feat(brain): daily-reflection skill: honest session retro that becomes a reflex (#149)

## [2026-06-12]: v3.8.4
### Other
- docs(memory): complete the bio-trio: immune system (learning) + ant stigmergy (coordination) (#145)

## [2026-06-12]: v3.8.3
### Other
- docs(brain): add capture-ends-with-triage skill (#148)

## [2026-06-12]: v3.8.2
### Other
- Feat/skills batch 2026 06 12 (#147)

## [2026-06-12]: v3.8.1
### Other
- docs: broaden "arm" to any sealed world + wire the first-user funnel (#146)

## [2026-06-11]: v3.8.0
### Features
- feat(brain): first-user quickstart: zero-to-alive in one command + broaden the arm framing (#143)

## [2026-06-11]: v3.7.1
### Other
- docs(readme): reposition the top to the broad-but-sharp pitch (an *octorato*, the brain layer) (#144)

## [2026-06-11]: v3.7.0
### Features
- feat(brain): ai-sync: canonical race-safe reconcile (pull --rebase then push) (#142)

## [2026-06-11]: v3.6.1
### Other
- docs(brain): add verify-generated-config-identifiers skill (#140)

## [2026-06-11]: v3.6.0
### Features
- feat(brain): two stakeholder-comms skills (teams-ready-message + verify-root-cause) (#127)

## [2026-06-11]: v3.5.1
### Other
- chore(brain): repo-watch +aitmpl, social-video-mining TikTok gotcha (#141)

## [2026-06-11]: v3.5.0
### Features
- feat(skills): snowflake-dbt-pitfalls + tramite-mx-assistant (#139)

## [2026-06-10]: v3.4.1
### Other
- ci(brain): bump semver autolabel on every merge to master (#138)

## [2026-06-10]: v3.4.0
### Features
- feat(brain): whatsapp-mcp bridge gotchas (403 directpath fix + install lessons) (#135)
- feat(brain): ULTRA RULE: do it right, not fast (root cause over palliative) (#134)
- feat(brain): extend dimension isolation to arms (broad-stage gate + worktree-init --repo) (#133)
- feat(brain): client-doc-lint reflex + cotizacion-legal-baseline (#132)
- feat(brain): emit GitHub Release + queued news draft on version bump (#130)
### Other
- docs(learn): correct stale gitignore note in /learn command (#131)

## [2026-06-09]: v3.3.0
### Features
- feat(brain): auto semver label + 3 upward-learning skills (#128)
- feat(brain): news-article-curation skill + /news-promote (inbound learning loop); fix connectome dedup parsing agents instead of skills (#126)
### Other
- docs(skill): harmonize model-routing rubric with Anthropic Claude model family table (#129)

## [2026-06-06]: v3.2.0
### Features
- feat(brain): submission-checklist-gate skill, completeness audit for outbound formal submissions (#125)
- feat(brain): octopus ganglia: reflexes-over-discipline skill + Q2 MCP-first actionable + restore Windows graph seek (#124)
- feat(brain): canary-symbiont skill, the cross-plane sentinel pattern (#121)
- feat(brain): adopt session-isolation + cadence hook wiring into hooks.json canon (#118)
- feat(brain): wiki anatomy F1-F5, skill promotions, memory-sync mechanism, dead-cell detection (#116)
- feat(brain): cadence stop-hook: the 10 no-rules enforced on CHAT replies (#117)
- feat(brain): structural session isolation + cadence lint (#115)
- feat(brain): unlock-suggestion ULTRA rule (Disclose-time twin of ☠ Prune) (#114)
- feat(brain): lane enforcement: first-writer claims, agent-proof deny on cross-dimension writes (#112)
- feat(graph): arm-level lineage graphs: every arm carries its own sealed seek (#110)
- feat(brain): 1+N two-tier memory + graph dead-cell detection + stat-floor fixes (#109)
- feat(brain): promote 3 learned skills (agent-proof-gate · command-boundary-matching · stacked-pr-gotcha) (#106)
- feat(brain): light the session-isolation lineage edge (seek > grep) (#107)
- feat(brain): inc-2b: live graph-before-grep teeth: PreToolUse grafo-gat (#94)
- feat(brain): ai-push co-tenancy guard, abort when another live session shares the tree (#104)
### Fixes
- fix(brain): teach install-runners to drop a Windows python3 shim (closes B3) + doc --floor (closes B2) (#123)
- fix(brain): Windows-portability of pre-push lineage check (sparse-checkout + python3 stub) + ask-with-recommendation skill (#122)
- fix(brain): repo-scope the qa-merge-gate: only protected repos are gated (#120)
- fix(brain): hooks.json timeouts within schema max (5s) (#119)
- fix(brain): harden ai-push co-tenancy guard with a conservative grace window (#108)
### Other
- ci(brain): counts-render drift guard + brain-ci lineage edge (#113)
- docs(brain): re-render stat floors after today's PR-merged work (209 skills live) (#111)

## [2026-06-02]: v3.1.0
Release name: "Reflexes".

Major step: the brain moved from **sensing** itself (3.0 Proprioception) to **enforcing** itself: principles became involuntary reflexes wired as hooks, not advisory prose the model can skip. And it learned to run as **one self across many parallel dimensions**.

### Added: reflexes
- **Connector verdict, enforced**: the 2D Delegate verdict is inverted: **SELF is the rare exception, the default is CONNECT** (LOAD/ACTIVATE). The agent is a connector to real sources, not an encyclopedia; SELF fires only when the operator explicitly asks for an opinion. (`scripts/delegate-check`, `scripts/query_connectome.py`, `CLAUDE.md` §2D)
- **Delegation reflex**: `scripts/delegate-gate.py` (PreToolUse, fail-open): nudges substantive/batchable work toward the cheapest sufficient model (Haiku/Sonnet/Opus) instead of the main loop.
- **QA merge gate**: `scripts/qa-merge-gate.py` (PreToolUse, fail-closed): no publish-to-main without an operator approval the **agent provably cannot self-grant** (PR-scoped `OCTO_MERGE_APPROVE` env: an inline env never reaches the harness-run hook: or `octo-dim approve-merge`). Detection is **command-boundary-anchored** so it gates real invocations, not mentions in quoted args.
- **Dimension awareness**: `scripts/dimension-awareness-hook.py` (PreToolUse, fail-open): warns when other live sessions share the working tree.

### Added: 4D session dimensions
- **One tentacle, N parallel dimensions**: `scripts/octo-dim.py` (register / heartbeat / list / prune / worktree-init / approve-merge) + a blackboard registry (`connectome/sessions.json`, gitignored): the same session-id runs in isolated git worktrees, reconciled into one `.git`. Isolation is the enabler of the 4D superpower, not a constraint. (`skills/session-isolation`)
- **Human-cadence delivery rules**: `skills/human-cadence`.

### Added: architecture
- **Hook orchestration, formalized + cited**: `docs/architecture/hook-orchestration.md`: a **Reactive Control Architecture with Adaptive Recall** (ECA atoms · Behavior-Tree priority · Statechart 4D · Spreading-Activation recall · Marr–Albus control loop · contextual-bandit tier-routing). L4 bandit router + activation-decay connectome are specified as the next build, not yet implemented.
- **Release/news cadence sense**: `brain_doctor` check `release-drift`: flags a top CHANGELOG version with no matching git tag (the gap that left v3.0.0 documented-but-unreleased). News is the brain's top-of-funnel reflex: a bump with no news = lost reach.

### Changed
- `brain_doctor` assertion count converged (`CLAUDE.md`) and the doctor grew to 15 checks (lineage-sound, release-drift).
- The qa-merge-gate enforces a hard rule now in `CLAUDE.md` §2D: the agent cannot self-approve its own merge gate.

## [2026-06-01]: v3.0.0
Release name: "Proprioception".

Major: the brain grew new **organs**: cross-cutting faculties that govern *how* every arm acts: not just arms (skills). It moved from **reactive to reflexive**: it now senses and coordinates itself.

### Added: organs
- **Proprioception**: the one-line **Provenance footer** (Basis · Engine · Touched · Verified) ends every response: the brain sensing its own action. (`scripts/4d-reminder.py`, `scripts/source-attribution-check.py`)
- **The reflective WHILE**: 4D codified as a loop, not a one-shot: `while (open / remnants / Touched≠intent): 4D()`; exit on reconciliation, never on "looks done". (`skills/4d-paradigm-protocol`)
- **The cerebellum**: precision without tremor: feedforward Manifest (enumerated target) ⇄ binary `Touched` reconcile ⇄ involuntary firing. `scripts/impact-radius.py` (tool) + `scripts/impact-radius-hook.py` (PostToolUse `Write|Edit` reflex). Closes the #1 recurrent failure: codify-in-one-place / leave-refs-stale ("pixelation") and its twin, touching or creating more than needed.
- **Metabolic sense (FinOps)**: `scripts/finops-digest.py` (per-arm $, routing KPI vs all-Opus, est-vs-billed), `scripts/cost-vs-change.py` (marginal cost of each new capability), folded into `brain-digest.py`; `skills/finops-observability`; `budgets.yaml.example` + brain_doctor enforcement-status check.
- **Gap sense**: `scripts/gap-capture.py`: 2D `SELF` ("nobody does it") misses logged; recurrence ≥3× graduates to a skill-creator candidate.
- **Model routing**: `skills/model-routing-by-complexity` (Opus brain, Haiku arms); the engine is disclosed in the Provenance footer.

### Changed
- **ULTRA rule**: every concept change runs an Impact Radius scan and reconciles `Touched`; a concept codified with stale references is a coherence bug. (`CLAUDE.md` §4D + `skills/4d-paradigm-protocol`)
- "Source line" → "Provenance footer" across `CLAUDE.md` / `README.md` / the 4D skill.
- `skills/octorato-symbolism`: the tesseract's operator-facing meaning (Octorato as the vehicle into the 4D a single human can't inhabit) + the arm-is-an-octopus recursion.

## [2026-05-29]: v2.1.0
Release name: "Contributor-Ready".

### Added
- `scripts/capability_inventory.py` + `docs/capability-inventory.md`: read-only census of which tools each agent declares and each skill references; flags unscoped agents. Input to the M1 Kernel-ABI RFC. (closes #28)
- `schemas/skill-manifest.schema.json` + `scripts/validate-skill-manifest.py`: `skill.json` manifest schema (name/semver/license + capabilities/dependencies) and validator with `--selftest`. On-ramp for M5. (closes #31)
- `schemas/tests/test_trace_event_schema.py`: validation test for `trace-event.schema.json` against real samples. (closes #29)
- `scripts/tests/test_check_generic.py`: message-scan unit test for `check-generic.py` using a temp blocklist via `CLAUDE_DIR` (never the private one). (closes #15)
- `tests/isolation/`: cross-arm red-team corpus (16 cases: 12 must-refuse + 4 allow controls) for the M2 isolation enforcer. (closes #30)
- `-h`/`--help` flag for `scripts/query_connectome.py`. (closes #13)
- YAML frontmatter (`name`/`description`/`metadata`) in `templates/skill/SKILL.md.template`. (closes #12)
- `CLAUDE.md` §"Octorato's Stance" + `skills/octorato-symbolism` "The Operator" section: generic identity: an organic, octopus-like connector tool (never a human, no fabrication/judgment; `act as X` → cited-data reframe; recursion + cellular arm-isolation as the superpower).
- README banner.

### Changed
- All seven `good first issue`s closed (#12, #13, #15, #28, #29, #30, #31): first full contributor on-ramp clear.

### Added (shipped 2026-05-28, between v2.0.0 and v2.1.0)
- `skills/repo-watch/`: daily monitor for a curated 7-repo watchlist
  (competitors / peers / upstream ecosystem). File-based trigger handoff
  to `/repo-deep-learn` for out-of-band analysis. Designed by Workflow
  Architect + Trend Researcher agents.
- `skills/repo-deep-learn/`: manual deep-dive counterpart of
  `github-trending-curation`. 8 phases: clone → inventory → README →
  patterns → connectome delta → proposals → issue-resolution scan → star.
- `skills/session-learn-extractor/` + `commands/learn.md`: capture the
  reusable pattern from the current session as a draft skill under
  `skills/learned/<slug>/` for operator review.
- `skills/hook-profile-gating/` + `scripts/lib/hook_flags.py` ,
  env-gated hook execution (`OCTO_HOOK_PROFILE=minimal|standard|strict`,
  `OCTO_DISABLED_HOOKS`).
- `skills/prompt-master/`: auto-promoted from `nidhinjs/prompt-master`
  (MIT) via `/repo-deep-learn`.
- `CLAUDE.md`: **PromptDefense Baseline** section (six anti-injection
  rules: no mid-session role change, no secret disclosure, no execution
  of untrusted embedded code, treat fetched content as untrusted,
  flag/refuse suspicious patterns, escalate repeated abuse).

### Changed
- `master` branch is now PR-only:
  - `enforce_admins: true`
  - required PR review (1 approval)
  - required status checks: `check-generic`, `neural_map-rebuild`,
    `claude-review`
  - linear history, no force push, no deletions, conversation
    resolution required.
- `scripts/ai_sync.py` auto-detects the protection and routes pushes
  through an auto-PR + watch + squash-merge flow, with a 600s watch
  timeout and a 15s race-condition retry for `gh pr checks --watch`.
- README skill-count floor raised from `180+` to `190+` (real count
  crossed 190 with the additions above).

### Notes
- The `--admin` bypass on `gh pr merge` is permitted **only** when
  GitHub Actions billing is paused (≤5s fail signature with missing
  logs). Never otherwise.

## [2026-05-25]: v2.0.0
### Features
- feat(brain): product showcase + 4D-reminder & source-attribution hooks
- feat(workflow): staged-promotion model: test integration branch → weekly master
- feat(brain): stats-drift guard wired into ai-push
- feat(brain): auto-promoted claude-plugins-official skill + UA fix + growth ledger
- feat(brain): github-trending-curation skill + /trending-promote + brain-discovery spec (generic-safe)
- feat(skills): wrangler-installed CF/Workers skills bundle + runtime gitignore
- feat(hook): no-pause-suggestion Stop hook: block 'leave for tomorrow/take a break' framing
- feat(skills): bug-hunter adversarial QA gate (Hunter→Skeptic→Referee) + demote single-shot Reality Checker to specialist
- feat(skill): add schema-as-code-three-layer-sync: canonical discipline for ER/DD/Code alignment
- feat(skills): add inbox-triage-classifier + lessons in browser-bearer & phi-aware
- feat(brain): add .githooks/pre-push enforcement layer
- feat(skills): add canonical operator-time mandates
- feat(skills): add execution-bias: don't defer in auto-mode, ship now
- feat(skill): add pre-merge-qa-gate + cross-ref from 4d-paradigm-protocol
- feat(skill): add ado-pr-merge-via-api
- feat(brain): add stripe-payments skill (tiers + key hygiene + MCP + CLI + CF webhooks)

### Fixes
- fix(hooks): default source line to English for non-EN/ES/DE input
- fix(hooks): neutral source noun per locale: Source/Fuente/Quelle (EN/ES/DE)
- fix(hooks): source line must match input language (EN/ES), not hardcoded Spanish
- fix(hooks): make source-attribution Stop check advisory-only (no false blocks)
- fix(hooks): tolerate transcript flush race in source-attribution Stop check
- fix(trending-promote): enforce content quality bar; stop dumping raw GitHub taglines

### Docs
- docs(brain): add dataqbs Facebook page link to README
- docs(brain): add README badges, launch-article link, demo placeholder
- docs: align wiki/registry layer to exact 152/189/13
- docs(readme): round ALL count references to floors (full alignment)
- docs(readme): round headline figures to stable floors (180+/150+)
- docs(wiki): custom footer: product + CV + sponsor/donate on every page
- docs(wiki): comprehensive Octorato wiki: 14 pages, 10 specialists + 2 reviews
- docs(community): SECURITY, CODE_OF_CONDUCT, PR + issue templates
- docs(brain): README self-growth section + connectome regen + traffic-title fix

### Other
- metrics: traffic snapshot 2026-05-24
- metrics: traffic snapshot 2026-05-23
- metrics: traffic snapshot 2026-05-22
- sync-ai-docs.ps1: PS 5.1 compat: chain 2-arg Join-Path (variadic is PS7+)
- chore(funding): point GitHub Sponsor button to dataqbs.com/donate
- metrics: traffic snapshot 2026-05-21
- chore(funding): point GitHub Sponsor button to Stripe PL directly

## [2026-05-20]: v1.0.0
Initial public release of the brain.

### Features
- feat(brain): add repomix-codebase-packer skill + FUNDING.yml (v1.0.0 prep)
- feat(brain): add octorato symbolic layer (#7)
- feat(brain): ship Claude Cowork integration shape as quarantined pseudo-arm (#6)
- feat(finops): Anthropic Enterprise Analytics API ingest (Feature 4/4) (#4)
- feat(finops): budget caps + PreToolUse halt mechanism (Feature 3/4) (#3)
- feat(finops): cost-spike watchdog (Feature 2/4) (#2)
- feat(finops): per-arm cost rollup + USD conversion (1/4) (#1)
- feat(positioning): pivot README to FinOps for AI agents + brain-pr-checks workflow
- feat(skills): batch-import-relative-paths: sed batch-imports w/ variable depth hide silently in Vite/esbuild
- feat(skills): 4 new skills from operational lessons (sentinel-blocks-rerun, horizontal-scroll-html-vs-body, fb-carousel-cap-4, pr-first-on-auto-deploy-main)
- feat(skill): sentinel-blocks-rerun: diagnose daily-idempotent no-op
- feat(skills): pages-function-checkpoint-debug + tiered-rotation extension
- feat(brain): Phase D Ports 6 + 7: Incident Capture & Brain Synthetics (closes Datadog spec 8/8)
- feat(brain): Phase C Port 8: Brain Charts on Demand (closes Phase C)
- feat(brain): Phase C Port 5: Brain Digest (daily markdown dashboard)
- feat(brain): Phase B Port 3: Brain SLOs (closes Phase B)
- feat(brain): Phase B Port 2: Skill Cost Profiler (turn-level attribution)
- feat(brain): Phase B Port 4: Watchdog MVP (cliff + quality drops from traces)
- feat(brain): add cache-bust-deploy-validation skill
- feat(skills): 2 new skills from real_estate session
- feat(brain): Phase A task #7: Hebbian update from traces (Phase A done)
- feat(brain): Phase A task #6: trace.py CLI query helper (read-only)
- feat(obs): scripts/trace.py: Datadog Port 1 query helper
- feat(brain): Phase A task #5: phase_boundary heuristic via lifecycle proxy
- feat(hooks): trace-hook extracts token usage from tool_response when exposed
- feat(brain): Phase A task #3: skill_fire capture hook (Port 1 first telemetry)
- feat(brain): add Phase A trace event schema + validating samples
- feat(hooks): add readme-sync soft-block to pre-commit
- feat(brain): social-video digest worker + .gitignore for worker outputs
- feat(brain): add Universal reflexes (Tier A) to Skill-First Behavior
- feat(skills): add 8 OSS-replacement and technique skills
- feat(metrics): daily octorato traffic watcher with spike alerts
- feat(brain): add summarize-100 skill
- feat(skills): add claude-usage-report: token/cost aggregator over local JSONL logs
- feat(migration): self-heal origin dotclaude→octorato + migration script + README section
- feat(skill): schema-row-counts: exact row counts per table for PostgreSQL/MSSQL/Databricks

### Fixes
- fix(traffic-watch): use OCTORATO_PAT: Traffic API needs Administration scope

### Docs
- docs(readme): flip FinOps roadmap: all 4 in-flight items shipped (#5)
- docs(brain): scrub inspiration-source references from README + observability layer
- docs(brain): add Self-Awareness block: ~/.claude/ IS octorato
- docs(brain): Datadog spec 8/8 shipped: flip README roadmap to "all shipped"
- docs(brain): add Observability section + update Repository Structure for Datadog Port 1
- docs(brain): Phase A task #2: trace storage layout + gitignore traces/
- docs(readme): add Synapses, Memory, Reflexes sections + glia/afferent framing
- docs: bump skill count 142 → 153 in README

### Other
- chore(brain): add FUNDING.yml: custom donate link dataqbs.com/donate
- metrics: traffic snapshot 2026-05-20
- refactor(brain): slim CLAUDE.md from 557 to 226 lines (60% reduction) (#8)
- security(brain): enforce no SDD artifacts at brain root
- metrics: traffic snapshot 2026-05-19
- metrics: traffic snapshot 2026-05-19
- refactor(brain): extract _brain_obs.py + rename trace→brain-trace, chart→brain-chart
- chore: drop tracked policy-limits.json (machine-local state, not source of truth)
- chore(brain): ignore paste-cache/ runtime dir
- Octopus Brain Framework v0.1.1

---

## How to read this file
- Each released date section follows **Added / Changed / Deprecated /
  Removed / Fixed / Security** as applicable.
- Unreleased work-in-progress accumulates under `[Unreleased]`.
- Autonomous daily skill auto-promotions are **not** mirrored here: they
  live in `knowledge/github-trending/HISTORY.md` so this file stays
  scannable for human-meaningful changes.

See also:
- [ROADMAP.md](ROADMAP.md): where we're headed.
- [SECURITY.md](SECURITY.md): how to report a vulnerability.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to add an agent, skill, or fix.
- [SUPPORT.md](SUPPORT.md): where to ask questions.
