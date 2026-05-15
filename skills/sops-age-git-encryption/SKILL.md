---
name: sops-age-git-encryption
description: "SOPS + age (per-user keys) as the default encryption stack for HIPAA / GDPR / SOC-2 / regulated-data git repos. Two-layer envelope (SOPS AES-256-GCM for values + age X25519/ChaCha20-Poly1305 for key wrap), per-user revocation in one command, no GPG fragility. Includes encrypt-vs-clear matrix, key custody decision tree, and upgrade path to KMS."
metadata:
  short-description: "Default git-encryption stack for regulated repos"
---

# SOPS + age Git Encryption

## What

A default encryption stack for git repos that hold regulated content (PHI, PII, PCI, controlled-classified data, internal architecture chats with patient identifiers, raw API payloads from a SaaS like Microsoft Graph). Encrypted blobs are committed to the repo as ciphertext; per-user age keys decrypt locally. Per-user revocation requires only a recipient-list edit, not a full repo rewrite.

## Why

Most regulated engagements eventually face the question: "we want to commit transcripts / raw API exports / embeddings — how?"

The wrong defaults cost real money:

- **Plaintext + .gitignore** — works until someone forgets, or the file moves, or git history grows. Once plaintext lands, it stays in history forever; remediation requires `git filter-repo` + force-push.
- **git-crypt + GPG** — per-user revocation requires a full repo rewrite. GPG keyring fragility is its own discipline. Production-deployed but every team that uses it hits the "expired key" issue at least once.
- **Encrypting everything** — defeats the purpose of git for code review. Only encrypt regulated paths; keep source code clear.
- **Single shared symmetric key** — no per-user revocation possible. One leaked laptop compromises everything.

SOPS + age beats those alternatives on:
- Per-user revocation in one command (`sops updatekeys` after editing `.sops.yaml`)
- Per-file envelope encryption with a fresh data key per file
- Encrypted YAML/JSON stays structurally diffable for PR review (paths visible, values opaque)
- CI integration is trivial (one age key as a CI secret)
- No GPG keyring; no expired-key hell
- Both `sops` and `age` install user-scope on Windows (winget), macOS (brew), Linux (apt) with no admin

## How the Two Layers Compose (Precise)

This is the single point most descriptions get wrong. Get it right and crypto reviewers nod.

- **SOPS** encrypts each leaf value in YAML/JSON/etc. with **AES-256-GCM**, using a 32-byte data key chosen per file.
- **age** wraps that data key for each recipient using:
  - **X25519** ECDH key agreement
  - **HKDF-SHA256** to derive a 32-byte symmetric key
  - **ChaCha20-Poly1305** AEAD to wrap the file key

Two independent layers. SOPS-AES-GCM (value layer) + age-X25519/ChaCha20-Poly1305 (key-wrap layer). Don't conflate them in the doc.

## Project Status (correct as of 2026)

- **SOPS**: originally created at Mozilla (2017); donated to **CNCF Sandbox** in 2023; now maintained by the `getsops/` GitHub org. Public production users include GitLab among others. The "Mozilla-backed" framing in older docs is outdated.
- **age**: active project at age-encryption.org/v1; reference implementation at `FiloSottile/age`.
- **Pin SOPS ≥ 3.7.3** — fix for the MAC-validation bypass (CVE-2022-39259, GHSA-w6f4-7vqw-3wrx). ≥ 3.8 is a more conservative pin and recommended.

## Encrypt-vs-Clear Matrix

| Path pattern | Encrypted? | Reason |
|---|---|---|
| `users/*/transcripts/*` | ✅ | Raw meeting text, regulated-suspect |
| `users/*/raw/**` | ✅ | Raw API payloads (mail bodies, chat content) |
| `users/*/embeddings/<date>.json` | ✅ | Vectors derived from regulated content |
| `users/*/_inventory.json` | ✅ | Org metadata (people, sites) — quasi-identifiers |
| `users/*/_health.log` | ✅ | May include error context with regulated content |
| `users/*/digests/*.md` | ❌ | Already PHI-scrubbed by pipeline |
| `users/INDEX.md` | ❌ | Hash → email mapping (not regulated) |
| `<arm>/knowledge.json` | ❌ | Project roadmap; no regulated content |
| `lib/`, `*.js`, configs | ❌ | Source code — must be code-reviewable |

**Rule**: encrypt regulated paths; keep source code clear. Encrypting code defeats PR review.

## Implementation (10 steps, ~30 min on a clean repo)

```bash
# 1. Install (user-scope, no admin)
winget install Mozilla.SOPS FiloSottile.age      # Windows
# brew install sops age                            # macOS
# apt install sops age                             # Debian/Ubuntu

# 2. Generate age keypair tied to a specific laptop (BitLocker / FileVault protected)
age-keygen -o ~/.config/sops/age/keys.txt
# Public key prints to stdout — copy it for step 3
# Add ~/.config/sops/age/keys.txt to .gitignore (NEVER commit)

# 3. Create <arm>/.sops.yaml declaring path regexes + recipients
cat > <arm>/.sops.yaml <<'EOF'
creation_rules:
  - path_regex: clients/[^/]+/users/.*/(transcripts|raw|embeddings)/.*
    age: >-
      age1xxx... # operator@example.com
EOF

# 4. Encrypt existing regulated files in place
sops -e -i clients/<arm>/users/<slug>/transcripts/*.txt

# 5. Update .gitignore to remove now-encryptable paths from the ignore list
# (they're now safe to commit as ciphertext)

# 6. Add a pre-commit hook that blocks plaintext commits to regulated paths
# Verifies the first ~200 bytes of each regulated-path file include a `sops:` marker

# 7. Add a GitHub Actions audit job (.github/workflows/regulated-audit.yml)
# Server-side gate — fails if any file under regulated paths is unencrypted

# 8. Commit + push (encrypted blobs go to remote)
git add .
git commit -m "feat: enable SOPS+age encryption for regulated paths"
git push

# 9. Verify by clone-without-key
git clone <repo> /tmp/clone-test
cd /tmp/clone-test
cat clients/*/users/*/transcripts/*  # should be ciphertext, not plaintext

# 10. Document in <arm>/SECURITY.md
# Encryption policy, key rotation schedule (quarterly is HIPAA-friendly),
# onboarding/offboarding ceremony, break-glass restore
```

## Key Custody Decision Tree

| Scope | Recommended custody |
|---|---|
| Solo consultant on a single client laptop | Single age key on that laptop (BitLocker/FileVault protected) |
| 2–3 consultants on one engagement | Each consultant has own age key; recipient list in `.sops.yaml` includes all |
| Team grows past 3, OR auditor asks for decrypt logs | Upgrade to SOPS + KMS (Azure Key Vault / AWS KMS / GCP KMS); KMS produces decrypt audit logs |
| Highest sensitivity (real patient identifiers, not just adjacent data) | KMS with hardware token (YubiKey) for break-glass |

## Cross-Arm Boundary (Octopus rule)

Each client repo gets its OWN `.sops.yaml` with client-scoped recipients. Same consultant uses different age keys per arm:

```
~/.config/sops/age/<arm-1>.key
~/.config/sops/age/<arm-2>.key
```

Shared keys across arms would break arm isolation. Don't.

## When to Upgrade to KMS

| Trigger | Why KMS now |
|---|---|
| Team grows past 3 consultants | Per-user revocation still works with age, but log management gets unwieldy |
| Auditor asks: "prove who decrypted this and when" | age provides confidentiality + revocation but NOT decrypt audit trails. Only KMS gives that (HIPAA §164.312(b)). |
| BAA scope expands to actual patient identifiers | Higher sensitivity → higher control requirements |
| Client provisions a Key Vault for the consultant team | Use it; integrates cleanly with SOPS via `--kms` / `--azure-kv` flags |

## Pitfalls

- **OLD plaintext commits in git history**: encryption only protects FUTURE commits. If anyone ever committed plaintext regulated content, treat as compromised + run `git filter-repo` + force-push to all branches and tags.
- **Filenames and paths leak** even when content is encrypted. Apply naming hygiene: use sha256 slugs, not raw email addresses, in folder names.
- **CI runners with the decrypt key** are a concentration of risk. Scope read-only, rotate monthly.
- **Pin SOPS ≥ 3.7.3** (CVE-2022-39259 / GHSA-w6f4-7vqw-3wrx MAC bypass fix); ≥ 3.8 conservative.
- **Don't store the age private key alongside `.sops.yaml`** in the repo. Complete circumvention. Key file must NEVER be committed; it lives at `~/.config/sops/age/keys.txt` only.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| `git-crypt + GPG` | Per-user revocation requires full repo rewrite; GPG fragility |
| `transcrypt` | Less mature, niche |
| Encrypting source code | Defeats PR review |
| Single shared symmetric key across team | No per-user revocation possible |
| Storing age private key alongside `.sops.yaml` in the repo | Defeats encryption entirely |
| Skipping the pre-commit + CI audit | Eventually someone forgets `sops -e` and pushes plaintext |
| Skipping `SECURITY.md` | Auditor needs the paper trail; without it, the technical solution is fine but the audit fails |

## Composability

- `phi-aware-rag-ingestion` — produces the regulated paths this skill encrypts
- `security-best-practices` (existing) — security baseline; this skill is the encryption-specific specialization
- `security-threat-model` (existing) — threat model justifies the encryption choice
- `security-roles-least-privilege` (existing) — CI runner key scope is least-privilege

## Lessons Learned

- A 4-specialist consensus (Compliance Auditor, Security Engineer, Backend Architect, DevOps Automator) on a HIPAA-scoped engagement landed on SOPS + age (3/4 picked it; 1/4 recommended SOPS + Azure Key Vault as the upgrade path). The pattern below survived independent review.
- The most common failure mode is conflating SOPS' AES-256-GCM (value layer) with age's X25519/ChaCha20-Poly1305 (key-wrap layer). Crypto reviewers catch this; getting it right in the doc earns trust for the rest.
- The "Mozilla-backed" framing is outdated. SOPS is now CNCF Sandbox (donated 2023). Update older skill descriptions.
- Encryption is one of the few skills where a wrong default is silently wrong. Get the path matrix and the GHSA pin right BEFORE the first encrypted commit, not after.
