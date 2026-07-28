---
name: ado-pr-merge-via-api
description: "Completa merges de Pull Request en Azure DevOps por REST API cuando la UI no sirve o hay que scriptear en lote. Cubre los 403 por threads sin resolver, voto en 'waiting for author' y CI gate rancio."
---

# ADO Pull Request Merge via REST API

Workflow for completing a PR on Azure DevOps via the REST API instead of
the web UI. Covers the three common 403s and how to clear each.

## When to use

- Scripting PR completion as part of a delivery pipeline.
- The UI is slow / sessions are flaky / SSO loop.
- Bulk-merging multiple ready PRs.
- An agent acting on behalf of the operator with an ADO PAT.

## What this skill does NOT do

Does not bypass content review. The operator is expected to have already
done the review (or approved the changes consciously). This is a procedural
workflow for the *merge action* — not for replacing human judgment on the
diff.

## The core sequence (happy path)

```text
1. GET   /git/repositories/{repoId}/pullRequests/{prId}
   → confirm mergeStatus="succeeded" and lastMergeSourceCommit.commitId
2. PUT   /git/repositories/{repoId}/pullRequests/{prId}/reviewers/{userId}
   → body { vote: 10, id: userId }     (10 = approved)
3. PATCH /git/repositories/{repoId}/pullRequests/{prId}/threads/{threadId}
   → body { status: "fixed" | "closed" }   for each open thread you own
4. PATCH /git/repositories/{repoId}/pullRequests/{prId}
   → body {
       status: "completed",
       lastMergeSourceCommit: { commitId: <from step 1> },
       completionOptions: {
         mergeStrategy: "noFastForward",      // or "squash" / "rebase"
         deleteSourceBranch: false,
         bypassPolicy: false,
       }
     }
   → on 200: completion succeeded; new commit at lastMergeCommit.commitId
```

All requests use Basic auth with empty username and a PAT as password:
`Authorization: Basic ` + base64(`:` + PAT).

## The three failure modes

### Failure 1 — `All comments in this pull request have to be addressed`

HTTP 403. Branch policy requires every open thread closed before merge.

**Resolution:**
- List threads: `GET /pullRequests/{id}/threads`.
- For each `status:"active"` thread with `commentType:"text"` comments:
  - If you own the thread (it's your concern) and the underlying issue is
    actually resolved: `PATCH .../threads/{id}` with `{status:"fixed"}`.
  - If the thread is a design discussion you accept as-is: `{status:"closed"}`.
  - If the thread belongs to another reviewer: do not touch — escalate to
    the operator.

**Do NOT** post an editorial follow-up comment ("Accepted as-is", etc.)
under the operator's identity. Quietly updating status is fine; posting
new content on someone else's thread is impersonation.

### Failure 2 — `Pull requests to main cannot be completed if any reviewers reject`

HTTP 403. One required reviewer has voted `-5` (waiting for author) or
`-10` (rejected).

**Resolution:**
- `GET /pullRequests/{id}` and inspect `reviewers`.
- If you are the reviewer and you intended to approve: `PUT .../reviewers/{userId}`
  with `{vote:10, id:userId}`.
- If another required reviewer is at `-5` or `-10`: stop and ask the operator
  whether to wait, ask the reviewer in chat, or proceed without their vote
  (only if policy allows non-required reviewers).

### Failure 3 — `Continuous Integration (CI) must succeed to update main`

HTTP 403. Branch policy needs a successful build, even when CI did pass.

This is the trickiest because the build genuinely is green but the policy
gate has not registered it. Two reasons it stays red:

(a) The policy is configured to track a *policy-queued* build. Builds
triggered by push or manually-queued via API don't always update the
policy's tracked state, even on the same commit.

(b) The published PR statuses only contain `codecoverage notApplicable` —
no explicit build-success status object. The policy is waiting for one.

**Resolution paths, in order of preference:**

1. **Re-queue the policy build from the UI.** PR page → Overview → "Re-queue"
   on the failing/missing build entry. This is what the policy wants.

2. **Bypass policy via API.** Requires *both*:
   - PAT scope = `Code: read, write, and manage`. The `manage` part is
     mandatory; without it the bypass silently fails.
   - Repo-level account permission `Bypass policies when completing pull
     requests` = Allow on the target branch. Granted in repo Security
     settings; usually requires a Project Administrator to set.

   If both are in place: same PATCH as the core sequence but with
   `completionOptions.bypassPolicy: true` and a `bypassReason` string
   describing why (always include the green build IDs so the audit log
   has context).

3. **Operator merges via UI.** UI sessions often have different permission
   elevation than PAT-based API calls (SSO group membership vs PAT scope).
   Falling back to "operator clicks Complete" is sometimes the only path.

**Detection check** before calling bypass:

```text
GET /pullRequests/{id}/statuses?api-version=7.1
```

If the only context returned is `codecoverage` with state `notApplicable`
and no `build/status` context, the policy gate is stale. That signal
strongly suggests path (1) or (3) — try those before assuming you have
bypass permission.

## Comment thread status codes

ADO thread `status` field accepts these strings via the REST API:

| Value | Meaning | When to use |
|---|---|---|
| `active` | Open / unresolved | Initial state |
| `fixed` | Code change resolved the concern | After the underlying issue is committed |
| `closed` | Won't be addressed in this PR | Design discussion accepted as-is |
| `wontFix` | Concern noted, deliberately not fixing | Rare; explicit reject of the suggestion |
| `byDesign` | Behavior is intentional | When the reviewer misunderstood the design |
| `pending` | Needs further discussion | Holding state |

## Reviewer vote values

| Value | Meaning |
|---|---|
| `10` | Approved |
| `5` | Approved with suggestions |
| `0` | No vote |
| `-5` | Waiting for author |
| `-10` | Rejected |

## Reference implementation

`merge-pr.js` next to this SKILL.md is an executable that ties the full
workflow together with diagnostic output. It uses the Node `https` module
(no SDK dependency) and reads the PAT from an env var of your choice.

Companion patterns useful alongside this skill:
- A `post-ado-pr-comment.js` style helper for posting `@mention` threads.
- A `push-ado-commit.js` style helper for committing files into a branch
  via the Pushes API (no local clone needed for simple text changes).
Both follow the same auth + error pattern as `merge-pr.js`.

## Authentication

- Header: `Authorization: Basic ` + base64(`:` + PAT)
- The leading colon (empty username) is mandatory.
- PAT scopes needed:
  - Always: `Code: read & write`
  - For bypass: `Code: read, write, and manage`
  - For policy queries: `Project and Team: read` (often inherited)

## API version

All examples use `api-version=7.1`. ADO supports backward compat to 6.0 in
most endpoints; thread `status` as string keyword (`"fixed"`, `"closed"`)
requires 7.0+.

## Audit trail

Every action via API is logged in the PR's activity feed with the PAT
owner's identity. There is no hidden mode. When using `bypassPolicy`, the
`bypassReason` field becomes part of the audit log — write it as if
auditors will read it later.

## Lessons learned (real incidents)

- A green build on `refs/pull/{id}/merge` is necessary but not sufficient for
  the policy gate. Always check `/statuses` for an explicit build-success
  status object, not just a codecoverage status.

- `bypassPolicy:true` without the repo-level "Bypass policies" permission
  still returns 403 — the API does not give you new permissions you don't
  already have on the account.

- Closing your own comment threads is safe; closing someone else's threads
  by silently changing status is acceptable but adding editorial follow-up
  notes ("Accepted as-is") under your identity is not. The status change is
  procedural; the comment is impersonation.

- When the UI works but the API doesn't, the answer is usually a permission
  delta between the SSO session and the PAT, not an API bug.
