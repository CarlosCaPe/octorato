---
name: ownership-by-authorship
description: Determine code/file ownership by git authorship (log/blame), never by which repo it lives in. Load before assigning work, escalating a fix to "another team", or routing a problem by repo location — the author may be on your own team. Repo location is not ownership.
---

# Ownership by Authorship, Not Repo Location

**The trap:** a file lives in repo X (which "belongs to" team B), so you conclude the
work or the fix is team B's and you escalate there. But a file's *location* and its
*authorship* are different things. Team A often writes and maintains a file that sits in
team B's repo (shared scripts, seeds, cross-cutting migrations, generated artifacts).
Routing the work by location alone sends it to the wrong owner and reads as passing the
buck — exactly the friction that erodes trust between teams.

## The rule

Before you assign ownership, escalate a fix to "another team", route a problem by repo,
or write a message that says "that's X team's, they should do it" — **verify who actually
wrote and maintains the file with git history.** Location is not ownership. Authorship is.

## How (cheap, deterministic, do it first)

- `git log --format='%an  %ad' --date=short -- <path>` — who authored and last touched it.
- `git blame -L <start>,<end> <path>` — line-level authorship of the exact lines in question.
- Hosted APIs when you can't clone: ADO `…/commits?searchCriteria.itemPath=<path>`,
  GitHub `…/commits?path=<path>` — both return author per commit.
- Read the file header: shared scripts frequently name their source/owner in a comment
  (e.g. "Seed source: <repo>/<path>"). Treat that as a lead, then confirm with the log.

A file in the "backend" repo authored by a data-team engineer is a data-team artifact
that happens to live there. The owner is the author, not the repo.

## Authorship owner vs operational owner

If a script exists and is current but the *problem* is that it isn't being run or applied
(the data is missing because nothing seeds it, the migration is written but not deployed),
then there are two distinct owners:

- **Authorship owner** — who wrote/maintains the artifact (from git).
- **Operational owner** — whatever pipeline/process is supposed to apply it.

Name both precisely. Lumping them into one vague "team" is how an escalation lands on the
wrong desk. "The script is current (authored by <person>); the gap is that nothing applies
it to <env> — who owns that step?" is a routable message; "that's the backend's problem"
is not.

## Trigger

Fires whenever you are about to: assign a task by repo, escalate to "the X team", draft a
message that routes a fix, or say "that's not ours / that's theirs". Run the authorship
check first, then write the message. This is a special case of verify-before-claiming
applied to ownership: do not assert who owns something you have not checked.
