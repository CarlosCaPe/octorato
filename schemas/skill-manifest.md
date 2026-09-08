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
python3 scripts/validate-skill-manifest.py --selftest   # samples + one fixture per schema rule
python3 scripts/validate-skill-manifest.py skills/*/skill.json   # the whole corpus
```

The schema is resolved **next to the script** (`../schemas/skill-manifest.schema.json`),
not from an environment variable, so the answer depends on the tree you run in and not on
the machine you run on. `--schema <path>` overrides it deliberately.

Two checks live in the script rather than the schema, because a schema never sees where a
file lives: `name` must equal the directory for any file called `skill.json`, and no two
manifests in one invocation may declare the same name. Corpus-wide uniqueness and
dependency resolution stay in `octo_pkg`, which holds the package set (the lock and the
vendor dir); this script only knows the paths it was handed.

`homepage` is http(s) only, enforced by a `pattern`. `format: "uri"` is an annotation most
validators do not enforce, and where it is enforced `javascript:alert(1)` is a well-formed
URI that passes it.

Every schema rule carries a negative fixture in
[`tests/skill-manifest-samples/negative-cases.json`](tests/skill-manifest-samples/negative-cases.json),
and every fixture carries its control: `--selftest` deletes that one rule from the schema
and requires the fixture to then PASS. Without the control a fixture can be rejected for
an unrelated reason and the rule stays unexercised, which is what the 233-manifest corpus
was doing: it is the generator's own output, so deleting any single rule still left it
233/233 valid. The selftest also fails when the schema grows a rule no fixture covers.

Out of scope for now (the larger M5 epic): the registry, signing, and dependency resolution.
