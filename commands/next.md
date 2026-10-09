---
description: Plain-language status of the work in this session. What happened, what was done, what is not done, why not, and what comes next.
---

# /next: where are we, in plain words

The operator asks this when a session got long or technical and they need the state without reading the scrollback. Answer for someone who was not watching. Load `skills/eli5/SKILL.md` for the register, and answer in the language the operator writes in.

## Where the context comes from

`/next` takes no arguments. Its subject is whatever work is already in context:

1. **The conversation in this session**, including any summary left by compaction. This is the main source.
2. **Stored memory, when the session is new or was summarized thin.** Seek it, do not scan it, in this order and stopping at the first that answers: `python3 ~/.claude/scripts/query_connectome.py memory "<the work in question>"`, then the memory index loaded at session start, then the arm's own memory when working inside an arm. Say in one line that the account comes from memory and from which entry, because a memory records what was true when it was written.

Context tells you WHAT to report on. It never tells you the current state: that comes from the checks below.

## Before writing a word

1. **Re-check the live state now.** Do not answer from what earlier turns said. A service that was down may be up, a PR that was open may be merged, a background task may have finished. Run the check for every item you are about to report (service status, PR state, the log since the last change, test run) and report what it returns. One check per item is enough; this is a status, not an audit.
2. **Read results whole.** No `tail`, `head` or `LIMIT` on a result you are about to draw a conclusion from. If you had to cut something, say what was cut.
3. **Close what you can close, when it is local and reversible.** A check, a test run, a read: do it first and report it as done. Anything that leaves this machine or cannot be undone (a message, a comment, a push, a merge, a release, a deploy, a restart of a live service, a deletion) is always the operator's step: it goes in the table with its command, and this command never performs it. File changes still go through the Change Manifest. A pending item stays on the list only when it is the operator's step or a measured block.

## The answer, in this order

**What happened.** The problem in two or three sentences, with an everyday comparison if it helps. Say the cause, not the symptom. If there were several causes, say which one produced what the operator saw.

**What was done.** A short numbered list. Each item is one finished thing and how it is known to work (the check and its result). Include your own mistakes along the way, in one plain sentence each: what went wrong, what it cost, how it was fixed.

**What is not done, and why.** One row per pending item:

| Pending | Whose step | Why it is not done |
|---|---|---|
| the thing, in plain words | operator or agent | the real reason: a permission only the operator holds, a gate that denied it (name it), a scheduled check that has not run yet (say when), or a decision that is the operator's |

"Not done yet" with no reason is not allowed. Neither is a reason you assumed and did not measure.

**What will come back.** If the fix stops today's symptom and leaves the cause able to return, say so in its own short paragraph. This is the part the operator most needs and the part most often left out.

**The one decision, if there is one.** End the prose with at most one question, the one the next step depends on.

## Commands

Every step that is the operator's travels with its exact command, ready to paste, no placeholders. Put them in one fenced block as the last thing in the reply. If there is nothing for the operator to run, there is no block.

**Close with a compact when the session is long.** `/compact` is a built-in the operator types; the agent cannot run it. When the session was already compacted once or holds many turns of work, the last line of the block is `/compact <focus>`, where the focus is one line naming what the summary must keep: the open work, the identifiers it needs (ids, URLs, commits) and the next step. In a short session, leave it out. If there was no other command, the block holds only this line.

## Rules

- Plain words. Name a tool or a file only when the operator needs it to act.
- Numbers are measured in this turn or carry where they came from.
- A check that only shows the process is alive does not prove the thing works. Say which check proves it, and whether that check has run.
- Do not call something fixed because a restart went well. Say what was observed.
- If neither the session nor memory holds any open work, say so in one line and stop.
