---
description: Like /next, but it does not stop at the table. It executes every pending item that belongs to the agent, re-checks the live state, and repeats until only operator steps or measured blocks remain. Then it reports in the /next format.
---

# /next-continue: work the agent's rows until none are left

The operator asks this when they want the agent to finish its own part without being driven turn by turn. It starts exactly like `/next` (read `commands/next.md` and follow its sources, live re-check and report format), and changes only what happens after the pending table is built.

## The loop

1. **Build the table.** Do everything `/next` does before writing a word: take the context, re-check every item live, read results whole, and build the pending table with its "Whose step" column.
2. **Pick the agent's rows.** A row is the agent's when it is local work the agent can execute: a read, a check, a test run, a draft, a review panel, a file change. A row is the operator's when it needs something only the operator holds: money, consent, a login, a merge approval, a version cut, a commercial decision, or an outward send (see "Sends" below).
3. **Execute them.** Do each agent row now, through every gate that already applies. File changes go through the Change Manifest. Drafts go through their panel. Nothing here waives a gate.
4. **Re-check and repeat.** After the batch, re-check the live state of every row (a finished row can open a new one, a reply can arrive) and rebuild the table. Go back to step 2.
5. **Stop** when the table holds no agent row. Then write the report.

## Guards

- **Two failures, then a measured block.** If the same row fails twice, stop retrying it. Mark it as a measured block with the literal error and move on to the others.
- **Turn cap of 10 loops.** This is a deliberate departure from "never stop": it keeps the command from spinning without progress. When the cap is reached, every agent row still open goes into the table with the reason "loop cap of 10 reached".
- **No new scope.** Execute the rows the table holds. A new idea that is not a pending item goes into the report as a suggestion, not into the loop.

## Sends

A send (message, mail, comment, post) always needs its panel PASS for the exact payload. `/next` treats every send as the operator's step, and so does this command by default.

When the operator writes `/next-continue send-ok`, sends whose panel PASS is recorded after that message become agent rows and go out. That `send-ok` waives the absence, attribute and promise checks only in the turn the operator's message opens; it never waives the panel. In turns opened by a reviewer hand-back it counts only as the send request. Before relying on it, verify that the argument of the slash command is read as the operator's own prompt by the send gate. If it is not, say so in the report and keep sends as operator rows.

Never revoke or delete a sent message in a turn that cannot also send its replacement.

## The report

Use the `/next` answer format unchanged (What happened, What was done, What is not done and why, What will come back, the one decision, the command block). In "What was done", list every row executed in this run with its check. In "What is not done", only operator steps and measured blocks may remain, each with the exact command or step.
