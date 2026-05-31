# Cross-Arm Isolation Red-Team Corpus

On-ramp for **M2 — Isolation & Resource Control**. This directory is the
**spec of what must fail**: a structured corpus of cross-boundary access
attempts, each tagged with the verdict an isolation enforcer must produce.

No enforcer code lives here yet (that's a later issue). Today this is the
test fixture a future guard is built against, test-first.

## Files

- [`redteam-corpus.yaml`](redteam-corpus.yaml) — the cases.

## Schema

```yaml
active_arm: arm-alpha
active_arm_root: ~/Documents/github/arm-alpha
cases:
  - id: <unique-slug>
    category: <attack class>
    verdict: refuse | allow
    attempt: <the prompt or path/command under test>
    rationale: <why this verdict>
```

- **`refuse`** — the attempt reads or writes outside the active arm root
  (a sibling arm, the private `company/` brain, or user-level secrets), or is a
  prompt-injection trying to disable isolation. A correct enforcer denies it.
- **`allow`** — a control that stays inside the active arm (or reads a generic,
  shared brain skill). Present so an enforcer that blindly refuses *everything*
  still fails the corpus — isolation must be precise, not paranoid.

## Categories covered

path-traversal-read · absolute-path-read · secrets-read · git-history-read ·
brain-private-read · symlink-escape · cross-arm-write · upward-leak ·
secrets-reuse · prompt-injection · plus in-arm / brain-generic allow controls.

## Loading

The corpus is plain YAML (PyYAML or any parser):

```python
import yaml
cases = yaml.safe_load(open("tests/isolation/redteam-corpus.yaml"))["cases"]
refuse = [c for c in cases if c["verdict"] == "refuse"]
```
