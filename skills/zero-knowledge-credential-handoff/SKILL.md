---
name: zero-knowledge-credential-handoff
description: "Deliver credentials (new account passwords, initial logins) to end users when the agent, and ideally the operator, must never see, print or type the value. The secret goes from AWS Secrets Manager through process memory into one short-lived HTML page per user in a private S3 bucket; only a presigned URL comes out. Includes verify-without-reading, revoke, the residual risks of a bearer link, and alternatives when a true one-time view is required."
metadata:
  short-description: "Hand out passwords via short-lived presigned links, value never printed"
---

# Zero-Knowledge Credential Handoff

## What

A way to get a password from a vault to the person who needs it without the value passing through an agent transcript, a terminal, a chat draft or the operator's eyes.

```
Secrets Manager --(in memory)--> local process --> private S3 object (one page per user)
                                       |
                                       +--> prints: name, OK, expiry      (never the value)
                                       +--> writes: links file, mode 0600 (presigned GET URLs)

links file --> verify (status, bytes, marker; never the body)
           --> outward send, one link per user  (stays a gated send)
           --> revoke once the user confirms login
```

Script: `scripts/secret_handoff.py`.

## When to use

- New accounts were created in bulk and each user needs their initial password.
- A rotated credential has to reach a non-technical user who has no vault access.
- The party creating the accounts is an AI agent, whose context is logged and replayed, so any value it reads is effectively published to its transcript.

Do not use it when a true one-time view is required. See *Alternatives*.

## Why not the obvious routes

| Route | Problem |
|---|---|
| Agent reads the secret and pastes it in a message | The value now lives in the transcript, the tool log and the chat history, with no expiry. |
| Operator copies it by hand | Works, but the operator sees every password and becomes the bottleneck. |
| Password in an email or chat body | Permanent, searchable, forwarded, backed up. Cannot be revoked. |
| Public or long-lived shared link | No expiry and no way to tell who opened it. |

A presigned link is not perfect (see *Residual risks*), but it expires on its own, can be killed early, and keeps the value out of every log between the vault and the user.

## What "zero-knowledge" means here, exactly

The value never enters the agent's context, the terminal output, or a file on local disk. That is the claim, and it is the whole claim.

It does not mean nobody in the middle could read it. Whoever holds the link holds a capability to fetch the page until it expires. That includes the agent that relays the link and anyone who can read the links file. The property is "did not see it", backed by a short window and a revoke, and not "could not have seen it".

## How

Prerequisites: `boto3`, and AWS credentials allowed to call `secretsmanager:GetSecretValue` on the secret plus `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` on the bucket (add `s3:ListBucketVersions` and `s3:DeleteObjectVersion` if the bucket is versioned). The secret must be a `SecretString` holding a JSON object that maps each key to its value:

```json
{"alice": "<password>", "bob": "<password>"}
```

Every mode that changes something previews by default and needs `--execute`.

```bash
# 1. One time: create or harden the bucket.
#    Block Public Access (all four), default SSE-AES256, lifecycle expiry on the prefix.
python3 scripts/secret_handoff.py --init-bucket \
    --bucket <bucket> --region <region> --profile <profile> --execute

# 2. Publish. Preview first (checks the bucket and that every key exists), then for real.
python3 scripts/secret_handoff.py \
    --secret-id <secret-id> --keys alice,bob \
    --bucket <bucket> --expires-in 43200 \
    --account-format 'DOMAIN\{key}' \
    --links ./links.json --profile <profile> --region <region>
#    ...add --execute to write the pages and sign the URLs.

# 3. Verify without reading: HTTP status, byte length, account marker, headers.
python3 scripts/secret_handoff.py --verify --links ./links.json

# 4. Send each user their own link over the chosen channel (a gated outward send).

# 5. Revoke after each user confirms login, then prove the link is dead.
python3 scripts/secret_handoff.py --revoke --links ./links.json --keys alice \
    --profile <profile> --region <region> --execute
python3 scripts/secret_handoff.py --verify --links ./links.json --keys alice --expect-gone
```

`--revoke` without `--keys` revokes every entry in the links file. `--revoke --all` sweeps the whole prefix. When the last entry is revoked the links file is removed.

### What the script guarantees

| Property | Mechanism |
|---|---|
| Value never printed | Output is the key name, a status and the expiry. Errors print an exception class or AWS error code, never exception text or a traceback. |
| Value never on local disk | Read into memory, written straight to S3. The links file holds URLs only. |
| Bucket cannot be public | Publish refuses unless all four Block Public Access settings are on (`--skip-preflight` exists for accounts where an account-level block covers it). |
| Encrypted at rest | Each object is written with SSE-AES256. |
| Not cached | `Cache-Control: no-store`, plus `noindex`, `no-referrer` and a `default-src 'none'` CSP on the page. No scripts, no external resources. |
| Object expires | Lifecycle rule on the prefix, default 2 days. The URL itself expires after `--expires-in` (default 12 h, hard maximum 7 days). |
| Re-publish kills the old link | Each page gets a fresh random object key and the recipient's earlier objects are deleted first, so an older URL cannot come back to life. |
| Recipient name not in the URL | The object path uses a hash of the key, not the key. |
| Revoke is complete | Deletes every version and delete marker under the recipient's path, then re-lists and reports `remaining=0`. |
| Verify does not leak | Prints status, byte count and yes/no checks. The body is read in memory and dropped. |

## Residual risks (state these to the operator, do not bury them)

1. **A presigned URL is a bearer token.** Anyone who holds it can fetch the page until it expires or the object is deleted. There is no identity check on the reader.
2. **It is not one-time.** The page can be opened any number of times inside the window. You cannot tell from the link whether the intended user or someone else opened it. S3 server access logs or CloudTrail data events can show GETs after the fact, if enabled.
3. **Chat and mail link-preview fetchers may GET it.** Many messaging and mail products fetch a URL to build a preview or to scan it, which copies the page content to a third party's servers. Send the link in a way that suppresses previews where the channel allows it, and treat the channel provider as having had access.
4. **A shared device exposes every link on it.** If two users read their messages on the same machine or the same shared mailbox, each can open the other's link. Browser history keeps the URL for the full window even though the page is not cached.
5. **The links file is as sensitive as the passwords** until expiry. It is written mode 0600. Do not commit it, do not paste it whole into a chat, and let revoke remove it. `--print-urls` puts the URLs into stdout, which means into the agent transcript; use it only when that is accepted.
6. **The agent relaying the link could fetch it.** See *What "zero-knowledge" means here*. `--verify` does fetch each page once, in memory, to check it.
7. **Temporary credentials shorten the window silently.** A URL signed with session credentials (SSO, an assumed role) stops working when that session expires, even if `--expires-in` is longer. The script warns when it detects a session token. Users then see an access-denied XML page, which looks like a broken link.
8. **Lifecycle expiry is a backstop, not a timer.** Its granularity is whole days and deletion runs asynchronously. Until it fires, the object exists even though the URL is dead. Revoke is the control that matters.
9. **The channel is still the weak point.** This pattern protects the value on the way to the link. Sending the link to the wrong recipient hands over the password. Keep the send behind the normal outward-send gate, one link per person, and never post links to a group.

**Close the loop:** revoke after the user confirms a successful login, and have the user change the password at that point if the system allows it. A link that was never revoked is an open credential for the rest of its window.

## Alternatives when a true one-time view is needed

- **Self-hosted one-time-secret service.** A burn-after-read service deletes the secret on first retrieval, so a second open fails and the user can report that someone got there first. Self-host it; a public instance is a third party holding your credentials. Pick one that requires a click to reveal, otherwise a link-preview fetcher burns the secret before the user arrives.
- **Force a password change at first logon.** The delivered password becomes worthless after first use, which shrinks every risk above. Caveat: **RDP with Network Level Authentication cannot complete a forced password change.** NLA authenticates before the session exists, so a user flagged "must change password at next logon" is refused at the door. If RDP with NLA is the only way in, either provide another path for the change (a web password-change page, a console or VPN logon) or do not set the flag and rely on revoke plus a user-initiated change after first login. Do not turn NLA off to work around it.
- **Out-of-band split.** Send the link on one channel and a short page passphrase or the username on another. This raises the cost for anyone who holds only one channel. It needs more than this script provides.
- **No shared secret at all.** Where the system supports it, a self-service enrollment or reset flow tied to the user's own second factor removes the handoff entirely. Prefer it when it exists.

## Pitfalls

- **Running publish from an agent with `--print-urls`.** The URLs land in the transcript, which outlives the window in logs. Default to the links file.
- **Treating a preview as done.** Without `--execute`, revoke deletes nothing and exits 2 with `NOTHING DELETED`. Read the last line.
- **Setting `--expires-in` longer than the lifecycle.** The object disappears first and users get a 404. Keep the lifecycle at or above the URL lifetime.
- **Versioned buckets.** A plain delete leaves the old bytes as a noncurrent version. The script deletes all versions when it is allowed to list them and warns when it is not.
- **Verifying by opening the link in a browser.** That puts the password on a screen and the URL in a history. Use `--verify`.
- **Reusing one prefix for unrelated batches.** `--revoke --all` sweeps the whole prefix. Give each batch its own `--prefix` if they have different lifetimes.
- **Putting a secret-bearing bucket name, account id or URL into a tracked file.** The bucket and secret id are arguments, never constants.

## What was not designed in

- No per-reader identity check, no access counter, no burn-after-read. S3 alone cannot do these.
- No KMS customer-managed key. SSE-AES256 only. A CMK is possible but the signer then also needs `kms:Decrypt`.
- No transport policy on the bucket. A `aws:SecureTransport` deny policy is a reasonable addition; the script does not write bucket policies because that would replace an existing one.
- No guarantee the value is wiped from process memory. Python cannot promise that; the process is short-lived and drops its references.

## Composability

- `sops-age-git-encryption` for secrets that must live in a repo. This skill is for secrets that must reach a person.
- `dry-run-gate-pattern` for the preview-then-`--execute` convention the script follows.
- `post-check-verification` for the verify step before the send and the `--expect-gone` check after revoke.
