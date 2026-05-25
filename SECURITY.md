# Security Policy

Octorato is the open-source AI-agent operating system that powers a real
operator's brain. Because the repository *is* a running brain, its security
model is unusual — most of the discipline is about **what must never enter the
repo**, not just about vulnerabilities in code.

## Reporting a vulnerability

If you find a security issue — a secret-leak vector, an injection path, a way to
make an agent exfiltrate data across the arm-isolation boundary, or anything
that could harm an operator running this framework — **do not open a public
issue**.

- Email: **carlos.carrillo@dataqbs.com** with subject `SECURITY: octorato`.
- Expect an acknowledgement within 72 hours.
- Please include: affected file/path, reproduction steps, and impact.
- Coordinated disclosure preferred; we'll agree on a timeline before any public
  write-up.

## What "secure" means in this repo

Octorato's threat model centers on **not leaking the operator's private world**
into a public repository:

1. **No secrets, ever.** Keys, tokens, passwords live in `.env` / vault, never
   in git. Two enforcement layers guard this:
   - Commit-time: `scripts/check-generic.py` scans staged files + commit message
     against a private blocklist.
   - Push-time: `.githooks/pre-push` scans every pushed commit against
     `.githooks/push-policy.txt` (universal secret patterns + paths).
   Enable on a fresh clone with `git config core.hooksPath .githooks`.

2. **The brain stays generic.** No client names, coworker names, internal
   codenames, ticket IDs, internal URLs, or customer data — in any surface git
   records (file contents, filenames, branches, tags, commit messages). The
   operator's private `company/` directory is gitignored and never flows public.

3. **Arm isolation.** Each client "arm" is sealed; an arm never knows another
   arm exists. Contributions must never introduce cross-arm data paths.

4. **Agent safety.** Skills and agents must not encode prompt-injection sinks,
   unsandboxed destructive operations without a dry-run gate, or detection-evasion
   tooling. Dual-use security tooling requires a clear defensive/authorized
   context.

## Supported versions

This is a single-operator framework distributed from `master`. Security fixes
land on `master`; there are no long-lived release branches. Pull `master` to stay
current.

## If a leak reaches `master`

Rewrite history (`git filter-repo` or squash) and force-push immediately, then
rotate any exposed credential. Never silently fix and hope. See `CLAUDE.md` →
"The Brain Stays Generic" for the full enforcement protocol.
