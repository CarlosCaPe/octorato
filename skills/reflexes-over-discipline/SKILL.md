---
name: reflexes-over-discipline
description: When a rule or gate is chronically ignored, when designing enforcement for a new policy, or when the operator says a rule keeps failing. Teaches how to convert a passive "mental check" into a mechanical hook (ganglion) that fires without the central brain invoking it.
metadata:
  type: pattern-reference
  status: active
  captured: 2026-06-05
  origin: session-learn-extractor (operator-explicit lesson, observed across multiple sessions)
---

# Reflexes Over Discipline

> The complement of [[octorato-harmony]]. That skill converges vocabulary.
> This one converts rules from "remembered" to "automatic."

## The one-line principle

**A rule the central brain has to remember is not a rule. It is a wish. Give it a ganglion.**

## The octopus neurology (why this is real, not metaphor)

A real octopus has ~500 million neurons. About 2/3 live in the arms, not the central brain. Each arm has a ganglion, a local nerve cluster that handles grip, texture sensing, and basic locomotion without asking the central brain first. The brain sends *intent*; the arm handles *execution* by reflex.

A Claude Code agent has the same failure mode as a vertebrate: if the central brain must remember to check something on every turn, it will fail under load. The checklist grows, the context fills, and the rule that needs "discipline" is the first to slip. The remedy is the same: move the enforcement to the arm (the hook) so the central brain never has to remember.

## Real evidence, cited

Two gates in CLAUDE.md's 2D Delegate section were "mental checks" with no mechanical enforcement:

- **Q2** ("¿tiene API? REST > MCP > SDK > scraping") had no hook. For several sessions the agent scraped Teams HTML and hand-rolled ADO REST calls instead of checking `claude mcp list` or registering an official MCP. Nothing blocked the bad path; nothing injected the prompt "did you check the API tier?" The rule existed in CLAUDE.md and was ignored.
- **Q3 / ACTIVATE+LOAD+SELF verdict** was also unforced. The 3-line summary that should appear at the start of every work turn was absent in the same sessions.

Meanwhile, the Human Cadence em-dash rule was followed. Why? A Stop hook fires, blocks the reply, and forces a rewrite before delivery. The agent cannot skip it because the hook runs in the harness, outside the agent's context. Same session, same model: the rule with a ganglion held; the rules without one evaporated.

That asymmetry is the entire lesson.

## Diagnostic: does this rule have a ganglion?

When you or the operator notice a rule is chronically skipped, do not add more prose to CLAUDE.md telling yourself to follow it. Ask one question:

> **Does this rule have a ganglion?** Is there a hook that fires on its own, without the central brain invoking it?

If no, that is the root cause. More prose is not the fix.

Signals that a rule lacks a ganglion:
- It appears in CLAUDE.md under "mandatory" but has no corresponding hook in `hooks.json`.
- The CLAUDE.md text says "always run X" or "mental check: Y" with no command or script.
- The Provenance footer in recent sessions does not show the gate firing.
- The operator has pointed out the same skip more than once.

## Taxonomy of ganglia in Claude Code

Three hook types cover the full space. Match the rule to the trigger.

| Rule is about... | Hook type | How it fires | Examples |
|---|---|---|---|
| An **action** the agent is about to take | `PreToolUse` | Fires before a Bash/tool call; can block it with `exit 1` | Block `git push --force`, block `DROP TABLE`, require env-var approval before merge |
| The **reply's content or shape** | `Stop` | Fires before the response is delivered; can block and force a rewrite | Em-dash rule, cadence-lint, provenance footer check, "did you add the 3-line verdict?" |
| **Context** that must be visible every turn | `UserPromptSubmit` | Fires on every user message; injects text into the conversation | Connectome heartbeat (Q1), current date injection, arm-specific reminders |

The mapping is not approximate. If you wire an action-gate as a Stop hook, you will block the reply after the damage is already done. Wire it as PreToolUse so the action never executes.

## Conversion recipe: passive rule to working ganglion

1. **Name the trigger.** What event in Claude Code immediately precedes the moment the rule must fire? A file write? A Bash command matching a pattern? The submission of a prompt? The delivery of a reply?

2. **Pick the hook type** from the table above.

3. **Write the hook script.** Rules for hook scripts:
   - Idempotent. Running it twice on the same input produces the same result.
   - Fast. The hooks.json schema caps hooks at ~5 seconds. If your check is slow, move the slow part to a background process and cache the result; the hook reads the cache.
   - Fail-open for context-injection hooks, fail-closed for true gates. An informational injector that crashes should not block work. A gate that crashes should block until a human investigates (see [[command-boundary-hook-matching]]).
   - Check the profile. Wrap with `should_run("<id>")` from `scripts/lib/hook_flags.py` so the hook respects `OCTO_HOOK_PROFILE` (see [[hook-profile-gating]]).

4. **Wire into hooks.json.** Add the hook entry. Run `merge-hooks` if the brain uses a merge step for arm propagation.

5. **Verify it fires.** Trigger the condition manually. Confirm the hook output appears. Confirm blocking hooks block. A hook you added but never tested has not moved the rule from "discipline" to "reflex."

### Minimal hook scaffold (Stop hook example)

```python
#!/usr/bin/env python3
"""
stop-hook-example.py
Stop hook: fires before reply delivery. Blocks if condition not met.
"""
import sys
import pathlib

# Profile gating
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts" / "lib"))
from hook_flags import should_run
if not should_run("stop:reply:example-gate"):
    sys.exit(0)

import json

data = json.load(sys.stdin)
reply = data.get("response", "")

# Check your condition
if "VIOLATION" in reply:
    print("[example-gate] BLOCKED: condition not met. Rewrite required.")
    sys.exit(1)   # non-zero = block the reply

sys.exit(0)       # zero = pass through
```

```json
// hooks.json entry
{
  "hooks": [
    {
      "event": "Stop",
      "script": "scripts/stop-hook-example.py",
      "timeout_ms": 4000
    }
  ]
}
```

### Minimal hook scaffold (PreToolUse gate)

```python
#!/usr/bin/env python3
"""
pre-tool-gate-example.py
PreToolUse hook: fires before a Bash command executes. Blocks if not approved.
"""
import sys, json, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts" / "lib"))
from hook_flags import should_run
if not should_run("pre:bash:example-gate", always_on=True):
    sys.exit(0)

data = json.load(sys.stdin)
tool = data.get("tool_name", "")
command = data.get("tool_input", {}).get("command", "")

if tool != "Bash":
    sys.exit(0)

# Match the real invocation (see [[command-boundary-hook-matching]])
import re
if re.search(r'\bdangerous-command\b', command):
    approved = __import__('os').environ.get("OCTO_DANGEROUS_APPROVE", "")
    if not approved:
        print("[example-gate] BLOCKED: export OCTO_DANGEROUS_APPROVE=1 to proceed.")
        sys.exit(1)

sys.exit(0)
```

## Anti-patterns to avoid

**Adding more CLAUDE.md prose.** A rule that was ignored will keep being ignored if the only change is more text explaining why it matters. Prose informs; a hook enforces. They are not substitutes.

**Over-centralizing.** Running every check in the Opus main loop is the vertebrate failure. Delegating mechanical gate-work to a Haiku sub-agent (see [[model-routing-by-complexity]]) IS itself a ganglion: the arm acts locally, the central brain does not pay for it. A gate run in the main context is slow, expensive, and subject to the same load-driven forgetting. Move it to a hook or a sub-agent.

**Building a Stop hook for an action gate.** A Stop hook fires after the action has already been taken. If you need to prevent a `DROP TABLE`, the PreToolUse hook is the only correct choice. A Stop hook that checks for damage in the reply is a post-mortem, not a gate.

**Wiring a hook and not verifying it.** An untested hook has no empirical status. It may not fire. It may fire on the wrong event. Trigger the condition manually in a clean session before declaring the rule "enforced."

## Provenance / proprioception tie-in

A gate you cannot see yourself skip will be skipped. The Provenance footer's `Touched` field makes gate-firing visible: if Q2 and Q3 fired, the footer records it. If they do not appear, they did not fire. That is the feedback loop. The footers are not bureaucracy; they are the proprioception that closes the 4D loop (see [[4d-paradigm-protocol]]).

The 4D WHILE exits only when `Touched = intent`. That reconciliation is impossible if the gate is a mental check with no trace. Convert the gate to a hook, then the trace is automatic.

## When a ganglion is genuinely not possible

Some rules cannot be wired as hooks today: they require a tool that does not exist, an event type not yet supported, or a context only a human has. In those cases:

1. Document the gap explicitly in the Disclose footer as a `Unlock-suggestion`.
2. Make the rule as visible as possible in the human's terminal output (a loud print statement at session start, not a buried CLAUDE.md paragraph).
3. Schedule a review to build the hook when the capability exists.

Do not accept "can't be a hook" without checking all three hook types first. Most rules that feel un-hookable just need the trigger identified correctly.

## See also

- [[hook-profile-gating]]: per-session hook activation (minimal/standard/strict) so the growing hook stack stays manageable
- [[command-boundary-hook-matching]]: how to match what a Bash command actually does without false-firing
- [[agent-proof-approval-gate]]: the authorization layer for consequential PreToolUse gates
- [[model-routing-by-complexity]]: delegating mechanical work to Haiku sub-agents is also a ganglion
- [[octorato-symbolism]]: the 8 -> infinity and octopus-arm architecture this principle lives in
- [[octorato-harmony]]: converging vocabulary across cells; this skill converges rules to reflexes
