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

## Nothing reads `license` yet

No code in this repo consumes the `license` field. `octo_pkg` never mentions it (`grep -in
licen scripts/octo_pkg.py` returns nothing), and a lock entry carries name, kind, version,
`tree_sha256`, signer, source and `installed_at`. Install, verify, publish and sync all
ignore it. What makes a wrong value matter is not a code path: the repo is public and the
field is a published assertion about someone else's terms, which is why the generator
reports rather than defaults. Anything that says the field is "acted on at publish time"
is describing an intention, not this HEAD.

`description` mirrors the skill's front matter as written. In 43 of the shipped manifests
that front-matter description IS the skill's title, so the manifest carries a title rather
than a summary. Faithful to the source, and not a summary; changing it means editing the
skills, not the manifests.

## What the coverage claim covers

Every schema rule carries a negative fixture in
[`tests/skill-manifest-samples/negative-cases.json`](tests/skill-manifest-samples/negative-cases.json),
and every fixture carries its control: `--selftest` deletes that one rule from the schema
and requires the fixture to then PASS. Without the control a fixture can be rejected for
an unrelated reason and the rule stays unexercised, which is what the 233-manifest corpus
was doing: it is the generator's own output, so deleting any single rule still left it
233/233 valid. The selftest also fails when the schema grows a rule no fixture covers.

"Every rule" is a denominator, so here it is, stated rather than implied. It is
`CONSTRAINT_KEYWORDS` in the validator: `type`, `pattern`, `minLength`, `maxLength`,
`enum`, `const`, `uniqueItems`, `required`, `propertyNames`, `additionalProperties`. Two
of them are addressed more finely than the schema writes them, because the coarse form
lets one fixture stand in for rules it never touches: `required` counts per MEMBER
(`required/name`, `required/version`, `required/license`), and `type` counts wherever
nothing else on the same subschema pins the JSON type.

Three things are deliberately outside it, and each would otherwise read as covered:

* `format` is an annotation, not a rule. `jsonschema` enforces it only where the optional
  format extras are installed, so a fixture for it would pass or fail by machine rather
  than by branch. `homepage` is guarded by its `pattern`, which is a rule and has a fixture.
* `type` beside an `enum` or a `const` is subsumed. Those keywords already admit values of
  a single JSON type, so no manifest can violate `type` alone and no control can isolate
  it. Four sit in that position: `kind`, `capabilities/items`, `signature/namespace`,
  `signature/file`.
* A fixture proves a rule FIRES. It cannot prove the rule is tight. Widening an `enum`
  (adding a value to `kind` or to the capability vocabulary) leaves every fixture red,
  because a fixture violates the enum by naming something outside it either way. That
  class of mutation is not caught here and is not claimed to be.

## The generator writes all or none

`gen_skill_manifests.py` describes every skill before it writes any of them. A run that
cannot describe one writes nothing at all and exits 1, so the tree never disagrees with
the exit code. It also prints, as a report and never a refusal, any skill that names an
upstream source and ships no license file: those take the repo default, the corpus check
has no license file to compare against, and whether this repo's terms may speak for
someone else's material is a question for a human.

Out of scope for now (the larger M5 epic): the registry, signing, and dependency resolution.
