---
name: capture-ends-with-triage
description: A scheduled capture/scrape/monitor pipeline that only dumps raw data to files forces the operator to do the synthesis by hand, so the synthesis gets skipped and directed asks (review requests, red builds, @mentions) are missed for days. The fix is a mandatory last step that TRIAGES: it diagnoses each surfaced issue to a cause and a next action, not just lists it. Trigger when building or reviewing any daily/periodic capture job (Teams/Slack/email scrape, CI status pull, repo watch, metrics dump).
metadata:
  type: reference
---

# A capture pipeline must end with a triage, not a data dump

A daily job that captures Teams threads, CI runs, PRs, tickets, and calendar into files is only half a tool. The data is there, but nobody reads ten folders every morning. The operator still has to ask "what needs me today?" by hand, which means the answer arrives late or never. A review request sits unanswered, a red build looks like noise, an @mention scrolls away.

The capture is not the deliverable. The **action digest** is.

## The rule

Every periodic capture pipeline ends with a triage step that runs last, after capture, and produces a short operator digest: what changed, what is broken, what is waiting on the operator. Persist it (`output/triage/<date>.md`) and print it.

## Triage, not a second pile of data

The trap is a digest that just relists the raw data ("here are 16 pipelines, 40 PRs, 200 messages"). That is a second thing to triage. A real triage **resolves each item to a cause and a next action**:

- A red CI pipeline is diagnosed by reading its timeline: a failed *task* (needs a code fix, point at the stage) versus an expired/rejected *approval gate* (just re-run and approve, no code change). These look identical in a status list and demand opposite responses.
- A PR is surfaced only if the operator is a reviewer who has not voted yet (an actual pending review), not every open PR.
- An @mention is the line of text, with its source, filtered to "today", so it reads in seconds.
- A work item is surfaced if it is assigned and still open.

The test: can the operator act from the digest alone, without opening the raw files? If not, it is a dump, not a triage.

## Mechanics that keep it honest

- **Runs last, as its own step** in the orchestrator, so it sees the freshly captured data and can also hit live APIs (CI, PR, ticket) for current state.
- **Exit 0 on success even when there are action items.** Having todos is not a service failure. Conflating "you have work" with "the job broke" trains the operator to ignore the signal. Action items live in the digest, not the exit code.
- **Owner-parameterized** (`TRIAGE_OWNER`, org, project in config) so the same step serves whoever runs it.
- **Diagnosis is cheap and worth it**: one extra API call per red item (its timeline/detail) turns "something is red" into "this is why and this is what you do".

## Why it matters

The recurring failure is not a missing scraper, it is a missing synthesis. When the operator asks "why didn't you tell me about X, the data was right there", the data being there is exactly the problem. Captured-but-unsynthesized is invisible. The triage is what makes the capture pay off.

Related: [[do-not-ask-to-pause]] (surface the next action, do not wait to be asked), [[verify-root-cause-before-claiming]] (diagnose the real cause, here per red item), [[reflexes-over-discipline]] (wire it as a step, do not rely on remembering to synthesize).
