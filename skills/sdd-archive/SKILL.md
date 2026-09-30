---
name: sdd-archive
description: >
  SDD step 7. Close a feature: require the converge verdict, update docs/project.md with the
  feature and any architecture decisions, and write a README in the spec directory. Specs already
  live in docs/specs/<yyyymmddHHMM>-<feature-name>/ and are not moved; legacy root files are.
  Use after /sdd-review is complete and the feature is ready to merge.
argument-hint: <feature-name> (optional, derived from feature.md if omitted)
---

# SDD: Archive

## Inputs

| Input          | Required | Description                                                                      | Example              |
|----------------|----------|----------------------------------------------------------------------------------|----------------------|
| `feature_name` | Optional | Archive folder name in kebab-case. Derived from `feature.md` heading if omitted. | `jwt-authentication` |

## Steps

### Step 0: Validate Inputs (ALWAYS DO THIS FIRST)

Locate the spec directory: `docs/specs/<yyyymmddHHMM>-<feature-name>/`, the one holding
`feature.md`. A legacy spec may still sit at the project root instead.

- If `feature.md` or `plan.md` do not exist → stop and tell the user both files are required.
- Note whether `review.md` and `impl-summary.md` exist next to them.
- If `feature_name` is provided → use it as the archive directory name (kebab-case).
- If `feature_name` is missing → read `feature.md` and derive it from the `# Feature:` heading,
  converting to kebab-case (e.g. "User Authentication" → `user-authentication`). Proceed automatically.

---

## Process

### 1. Determine the Feature Name
Use `feature_name` from Step 0. For a spec already in `docs/specs/`, the directory name is the feature name. For legacy root files, capture the timestamp with `date +"%Y%m%d%H%M"` and prepend it: `<yyyymmddHHMM>-<feature-name>` (e.g. `202604191430-jwt-authentication`).

### 2. Verify Completion
Completion is a converge verdict, not ticked checkboxes (criteria are never ticked).
- For a `Spec-Format: ears-1` spec, require a `CONVERGE-VERDICT: CONVERGED` for this spec
  directory, newer than the last change to its code. Today that verdict is the final message
  of the converge subagent in this session; from v9 phase 3 on, the receipt ledger records it
  and the push gate checks it. If the latest verdict says `GAPS`, or none is available, stop
  and tell the user to run `/sdd-converge`.
- For an older spec without that header, warn the user that completion was never verified
  and ask for confirmation before archiving.

### 3. Update docs/project.md

This is a critical step. Read `docs/project.md` in full, then read the archived
`feature.md` and `plan.md` to extract what actually changed. Update `project.md`
across the following sections: add sections if they do not already exist.

#### 3a. Features List
Locate or create a `## Features` section. Add the new feature as a single line entry:

```markdown
## Features
- **<Feature Name>**: <one-sentence description of what it does> (`docs/<feature-name>/`)
```

Preserve the existing list. Append the new entry: do not reorder or remove existing entries.

#### 3b. Architecture Decisions
Scan `feature.md` (Technical Scope, Revision History) and `plan.md` (Architecture Decisions)
for any decisions that represent a meaningful change or addition to how the system is built.

Examples of what qualifies:
- A new architectural pattern introduced (e.g., added an event-driven flow, introduced CQRS for a module)
- A cross-cutting decision that will affect future features (e.g., "all auth tokens use RS256 signing")
- A deliberate deviation from existing conventions, with rationale
- A new integration point with an external system

Examples of what does NOT qualify:
- Routine implementation choices that follow existing conventions
- File naming or package placement decisions
- Minor refactors that don't change architectural direction

For qualifying decisions, locate or create an `## Architecture Decisions` section:

```markdown
## Architecture Decisions

| Date | Decision | Rationale | Feature |
|------|----------|-----------|---------|
| <date> | <what was decided> | <why> | [<Feature Name>](docs/<feature-name>/) |
```

If the table already exists, append a new row. Do not recreate the table.

#### 3c. API Surface (if applicable)
If the feature added or changed REST endpoints, locate or create an `## API` section
and document the new endpoints:

```markdown
## API
| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | /api/v1/auth/login | Authenticate user, returns JWT | No |
| POST | /api/v1/auth/refresh | Refresh access token | Yes (refresh token) |
```

Only add endpoints that are new or changed. Preserve existing entries.

#### 3d. Environment / Configuration
If the feature introduced new environment variables, configuration keys, add them to an
`## Environment & Configuration` section:

```markdown
## Environment & Configuration
| Key | Description | Required | Default |
|-----|-------------|----------|---------|
| JWT_SECRET | Secret key for JWT signing | Yes | none |
| JWT_EXPIRY_MINUTES | Access token TTL in minutes | No | 15 |
```

### 4. Show the project.md Changes
Before writing, present a summary of every change you are about to make to `project.md`:

```
## Proposed project.md Updates

### Features (1 addition)
- Added: JWT Authentication

### Architecture Decisions (1 addition)
- Added: All tokens signed with RS256; public key distributed via /.well-known/jwks.json

### API (2 additions)
- Added: POST /api/v1/auth/login
- Added: POST /api/v1/auth/refresh

### Environment & Configuration (2 additions)
- Added: JWT_SECRET
- Added: JWT_EXPIRY_MINUTES

### No changes to
- Tech Stack, Architecture overview, Conventions
```

Ask the user to confirm before writing. If they request changes to the proposed
updates, apply their corrections first, then write.

### 5. Place the Files
- **Spec already in `docs/specs/<yyyymmddHHMM>-<feature-name>/`** (every spec `/sdd-feature`
  writes): move nothing. Its path is the key the converge verdict and the receipt were recorded
  under, and moving it would orphan them.
- **Legacy files at the project root:** move them into a new spec directory:

```bash
SPEC_DIR="docs/specs/$(date +"%Y%m%d%H%M")-<feature-name>"
mkdir -p "$SPEC_DIR"
mv feature.md plan.md "$SPEC_DIR/"
[ -f review.md ] && mv review.md "$SPEC_DIR/"
[ -f impl-summary.md ] && mv impl-summary.md "$SPEC_DIR/"
```

### 6. Create a Brief Summary
Create `README.md` in the spec directory:

```markdown
# <Feature Name>

Implemented on: <date>

<Brief description of what was built, key files, and any notable decisions.>
```

### 7. Confirm
Report the final summary to the user:
- The spec directory and what it holds (`feature.md`, `plan.md`, `review.md` and `impl-summary.md` if present), and whether anything was moved
- Sections updated in `docs/project.md`
- Remind them to commit the spec directory and `docs/project.md` to version control
