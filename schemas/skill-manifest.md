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

## How `license` is decided, and the three ways it used to be wrong

A skill's license comes from four places, in this order, and only the last of them is a
default:

1. the skill's own license file, when its terms are recognized;
2. its front-matter `license:`, when it declares one and ships no license file;
3. nothing at all, reported by name, when the two disagree or the file cannot be read;
4. the repo default, and only when the skill declares nothing and carries no license
   file under any name this generator looks for.

Three roads to a silent false claim ran through that list. Two are closed and one is a
standing residual, stated here rather than left to be found:

* **Front-matter `license:` was written and never read.** Eight skills declared one;
  the generator ignored the field and wrote the repo default. A skill saying
  `license: Apache-2.0` therefore published MIT, under this repo's copyright, over
  someone else's material. CLOSED: the declaration is compared against the license file
  and a disagreement is a refusal, and with no license file the declaration is honoured
  instead of overwritten.
* **Only MIT was a whole-document match.** The commit that introduced whole-document
  matching said "a license is recognized whole, or it is not recognized", and that was
  true of one recognizer out of six. Apache-2.0 with a Commons Clause appended,
  Apache-2.0 under the heading "This software is NOT licensed under the terms below",
  GPL-3 with a commercial restriction added, BSD-4-Clause, BSD-3-Clause-Clear and a
  multi-license notices file were each answered with a single clean SPDX id. CLOSED for
  prepended, appended and clause-count changes: every recognizer now anchors at both
  ends of the document and refuses text carrying terms outside them.
  **RESIDUAL:** only MIT and BSD-3-Clause are matched word for word. Apache-2.0,
  GPL-3.0, AGPL-3.0 and MPL-2.0 are checked section by section between their anchors, so
  a clause rewritten in the middle of a 200-line license with the section headings left
  in place is not detected.
* **The filename test decides "absent", and absent decides the default.** A name it
  does not recognize is not "no license here", it is "not looked for", and both are
  written into the manifest as this repo's own terms.

  The extension half used to be an allow-list, and that is the wrong polarity for this
  decision: missing a member costs a silent false legal claim, including one costs a
  refusal, and a refusal is a human being asked. It is a deny-list now (source code,
  structured data, images, archives, binaries), so a name whose words say license is
  read unless its bytes are code. `LICENSE.pdf` is deliberately NOT excluded: it holds
  terms nobody here can read, and the honest answer to that is the refusal the reader
  already raises, not silent absence. CLOSED, with the measured enumeration of real
  names on a developer machine written above `_LICENSE_STEMS` in the generator, counts
  included, so the claim can be checked without reading the code. The previous revision
  covered `COPYING.LESSER` (44 copies) and missed `COPYING.LIB` (195), which is the
  same failure one layer down: closing one member of a class and calling it closed.

  **RESIDUAL:** the STEM half is still a list (`license`, `licence`, `copying`,
  `unlicense`, `copyright`, `licenseref`, plurals and version suffixes of each). A
  license named `TERMS.md`, `EULA.txt` or `Artistic` carries none of those words and is
  still read as absent. Notices files (`LICENSE-3RD-PARTY`) are excluded on purpose:
  they list what OTHER people's code is under, and reading one as the package's own
  terms is the mirror of the same bug.

### What a refusal says

A refusal names the word that differs, quoted with the line it sits on, because a
refusal that misdiagnoses sends whoever fixes it to read the wrong sentence.

**No corpus percentage is published here, on purpose.** An earlier draft of this file
carried one. It was measured by running the recognizer over every license-named file on
one developer's disk, and it is not reproducible by anyone, including the machine that
produced it: two runs of the same selection days apart returned different denominators,
because `$HOME` is a live tree where package installs add and remove license files
between runs. A number that moves under its own author is decoration, not evidence, and
this document should not carry the one kind of claim the recognizer exists to refuse.

What the sweep is good for is finding SHAPES, and those are reproducible because each
one becomes a fixture. Three came out of it and all three are pinned by tests: a curled
or straight quote around `"Software"` is typography and must not decide (before the
comparison ran over words, a family of packages that writes `'Software'` with
apostrophes was told its "grant sentence is not MIT's"); a `BSD 3-Clause License` title
line above the text is a title, not terms; and an Apache-2.0 copy that stops at the end
of clause 9 with no `END OF TERMS AND CONDITIONS` is a whole license, which is why
`_Anchored.ends` is a list of forms rather than one phrase. Anyone re-running such a
sweep should expect different counts and the same shapes.

Typography is not terms. The comparison runs over words, so quote glyphs, emphasis
markers, comment fences, line wrapping, rst underlines and intra-word hyphens cannot
decide whether a license is recognized. What may sit AROUND a license (a title, a
copyright notice and its holder continuations, an SPDX tag, a signature block, a bare
URL, a horizontal rule) is judged only once the license body has been located; nothing
inside that body is ever dropped.

### `NOASSERTION`

Where the evidence names two licenses and settles on neither, the manifest carries
SPDX's own `NOASSERTION` and the generator prints every skill that does, on every run.
It is not a license and it is not a default: it is the absence of a claim, kept visible
so the open question keeps being asked.

## Nothing INTERPRETS `license`, and everything protects it

Both halves are true and they read as a contradiction in the wrong order, so take them
together. `octo_pkg.py` hashes, signs, verifies and installs the manifest AS A WHOLE, so
the license field travels inside what the tree hash protects and a value changed after
signing fails verification. It never reads the field: `grep -in licen scripts/octo_pkg.py`
is empty. Integrity, not interpretation. That is why a wrong value matters for what it
CLAIMS in public rather than for a code path it would break, and why the generator
reports rather than defaults.

No code in this repo consumes the `license` field. `octo_pkg` never mentions it (`grep -in
licen scripts/octo_pkg.py` returns nothing), and a lock entry carries name, kind, version,
`tree_sha256`, signer, source and `installed_at`. Install, verify, publish and sync all
ignore it. What makes a wrong value matter is not a code path: the repo is public and the
field is a published assertion about someone else's terms, which is why the generator
reports rather than defaults. Anything that says the field is "acted on at publish time"
is describing an intention, not this HEAD.

`description` mirrors the skill's front matter as written. In 48 of the 233 shipped
manifests that description is byte-equal to the skill's first markdown heading, so the
manifest carries a title rather than a summary (46 are six words or fewer, a looser test
that catches two more short titles and misses four long headings; every skill has a
front-matter description, so none of the 233 falls back to the heading). Faithful to the
source, and not a summary; changing it means editing the skills, not the manifests.

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
