# META.skill-manifest-coverage fixture

The violation and benign pair for the coverage half of the PACKAGE primitive:
`docs/architecture/v8-kernel.md` section 4 promises "`skill.json` on every skill
directory", and this is what proves the promise is measured rather than asserted.

| Tree | Leg | Expected |
|---|---|---|
| `violation/` | violation | `covered-two/` has a `SKILL.md` and no `skill.json` -> FAIL, exit 1, the unlock names `covered-two` |
| `benign/` | benign | both skills carry a manifest -> PASS 2/2, exit 0, no unlock |

**The pair is exactly one edit apart**: `benign/skills/covered-two/skill.json` is the
only file that differs, and the selftest ASSERTS that (`_tree_diff`) instead of
trusting it. A pair that drifts to two edits stops proving which edit the ladder
reacted to, so the assertion is part of the proof and not a tidiness check.

The denominator is measured from the trees themselves (`skills/*/SKILL.md` = 2 in
both), never listed here. That mirrors the live check, where a hand-kept list would
be a second thing to forget and forgetting it would read as coverage.

Two states no pair can express are derived from these trees inside the selftest
rather than shipped as a third and fourth directory:

- **zero coverage** (`0/N`) by deleting both manifests from `benign/`. It must be a
  WARN, because the live brain is at 0/233 until the mechanical backfill lands and a
  FAIL there would wall every push on every branch.
- **empty denominator** (`0/0`) by pointing the scan at a `skills/` with nothing in
  it. It must be a FAIL: a brain with no skills is a root that resolved wrong, not a
  clean brain, and that is the one place a zero is allowed to mean something.

Run it:

    python3 scripts/octo_pkg.py --selftest registry/fixtures/META.skill-manifest-coverage

Dispatch is by LAYOUT, not by directory name: a `violation/` + `benign/` pair selects
these legs, a `signed/` sibling selects the install legs of `META.kernel-package`.
Renaming a fixture directory therefore cannot silently run the wrong legs and pass.

No key, no signature and no network: coverage is a question about which files exist
in this repo, so the selftest needs neither.
