# Skill Manifest (`skill.json`)

> Machine-readable manifest for a distributable skill. On-ramp for **M5 — Distribution**
> (signed, semver-versioned skill packages). Schema: [`skill-manifest.schema.json`](skill-manifest.schema.json).

A skill that wants to be installable by a stranger ships a `skill.json` alongside its `SKILL.md`:

```json
{
  "name": "querymaster",
  "version": "1.4.0",
  "license": "MIT",
  "description": "Global database query agent — dry-run by default across 6 engines.",
  "capabilities": ["Bash", "Read", "Write"],
  "dependencies": {
    "token-efficient-prompting": ">=1.0.0"
  },
  "author": "octorato",
  "homepage": "https://github.com/CarlosCaPe/octorato"
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | ✅ | lowercase kebab-case slug, matches `skills/<name>/` |
| `version` | ✅ | semver 2.0.0 — reproducible, upgradeable installs |
| `license` | ✅ | SPDX id (`MIT`, `Apache-2.0`, `AGPL-3.0-only`) or `proprietary` |
| `description` | — | one-line summary |
| `capabilities` | — | privileged tools the skill declares it needs (blast radius) |
| `dependencies` | — | `{ skill-slug: semver-range }` |
| `author` / `homepage` | — | attribution / source URL |

Validate a manifest:

```bash
python3 scripts/validate-skill-manifest.py skills/querymaster/skill.json
python3 scripts/validate-skill-manifest.py --selftest   # checks the bundled samples
```

Out of scope for now (the larger M5 epic): the registry, signing, and dependency resolution.
