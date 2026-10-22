---
description: Like /next, but it does not stop at the table. It executes every pending item that belongs to the agent, re-checks the live state, and repeats until only operator steps or measured blocks remain. Then it reports in the /next format.
---

# /next-continue: work the agent's rows until none are left

The operator asks this when they want the agent to finish its own part without being driven turn by turn. It starts exactly like `/next` (read `commands/next.md` and follow its sources, live re-check, rules and report format), and changes only what happens after the pending table is built.

## The loop

1. **Build the table.** Do everything `/next` does before writing a word: take the context, re-check every item live, read results whole, and build the pending table with its "Whose step" column.
2. **Pick the agent's rows.** A row is the agent's only when `/next` would let the agent close it: local and reversible work such as a read, a check, a test run, a draft, a review panel, or a file change through the Change Manifest. Every item `/next` marks as the operator's step stays the operator's: anything that leaves the machine or cannot be undone (a message, a comment, a push, a merge, a release, a deploy, a restart of a live service, a deletion), plus money, consent, a login, a version cut and a commercial decision.
3. **Execute them.** Do each agent row now, through every gate that already applies. Drafts go through their panel. Nothing here waives a gate.
4. **Re-check and repeat.** After the batch, re-check the live state of every row (a finished row can open a new one, a reply can arrive) and rebuild the table. Go back to step 2.
5. **Stop** when the table holds no agent row. Then write the report.

## Guards

- **Two failures, then a measured block.** If the same row fails twice, stop retrying it. Mark it as a measured block with the literal error and move on to the others.
- **Loop cap of 10.** The command is meant to keep going until the agent's rows are done; the cap keeps it from spinning without progress. When the cap is reached, every agent row still open goes into the table with the reason "loop cap of 10 reached".
- **No new scope.** Execute the rows the table holds. A new idea that is not a pending item goes into the report as a suggestion, not into the loop.

## Sends and deletions

This command never sends, revokes or deletes a message. Those stay operator rows, as in `/next`.

The agent's part of a send is to have it ready: the exact payload with its panel PASS. The report then lists it with the step "write `send-ok` as a plain message". That plain message, not this command, releases it. A `send-ok` written as an argument of this slash command does NOT count: the send gate reads the operator's words only from a plain message, and the expanded command is not one (measured: the gate's prompt reader returns empty for a slash-command turn and returns `send-ok` for a plain `send-ok` message).

Revoking or deleting a sent message is always an operator row. When a replacement exists, the report lists the replacement send first and the revoke after it, so the counterpart is never left without the correct message.

## The report

Use the `/next` answer format unchanged (What happened, What was done, What is not done and why, What will come back, the one decision, the command block). In "What was done", list every row executed in this run with its check. In "What is not done", only operator steps and measured blocks may remain, each with the exact command or step.
