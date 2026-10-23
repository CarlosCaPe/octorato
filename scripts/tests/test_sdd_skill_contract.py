#!/usr/bin/env python3
"""The v9 contract lines of the SDD skills, pinned.

A skill is prose the model follows, so nothing executes it and no fixture can run
it. What CAN regress silently is the text: a skill edited back to ticking criteria,
to writing a plan over open markers or to moving a spec would pass every other
check. This test reads each skill and requires the sentences its acceptance
criterion rests on (docs/specs/202609301321-v9-done-is-a-verdict/feature.md), and
it runs from .githooks/pre-push with the rest of scripts/tests.

What it cannot see: whether a model obeys the sentence. It pins the instruction,
not the behaviour.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = ROOT / "skills"

# (criterion, skill, sentences that must be there, sentences that must not).
# Patterns are matched on the text with every run of whitespace collapsed to one
# space, so re-wrapping a paragraph does not break the pin.
CONTRACT = [
    ("AC-04", "sdd-plan",
     [r"spec_lint\.py --ready",
      r"If it exits non-zero, stop",
      r"open `\[NEEDS CLARIFICATION\]` markers",
      r"Do not write `plan\.md`"],
     []),
    ("AC-07", "sdd-analyze",
     [r"You modify \*\*no file\*\*",
      r"After `/sdd-plan`, before `/sdd-implement`",
      r"capped at \*\*50 findings\*\*",
      r"Ids are stable across re-runs"],
     []),
    ("AC-08", "sdd-implement",
     [r"Do not declare acceptance criteria met",
      r"never tick or annotate them in `feature\.md`",
      r"`/sdd-converge` decides completion"],
     [r"\[[xX]\] AC-\d+", r"AC-\d+: (?:Passed|Met|Done)", r"### Acceptance Criteria"]),
    ("AC-09", "sdd-review",
     [r"Never edit `feature\.md`",
      r"Criteria are not yours to tick or rewrite"],
     [r"\[[xX]\] AC-\d+", r"tick (?:the|each|every) (?:acceptance )?criteri"]),
    ("AC-10", "sdd-converge",
     [r"Completion claims are not evidence",
      r"`impl-summary\.md`, ticked boxes, commit messages and the implementer's report tell "
      r"you where to look, never what is true",
      r"Only code, tests you run, and outputs you observe count"],
     []),
    ("AC-11", "sdd-converge",
     [r"`plan\.md` is \*\*append-only\*\*",
      r"You never edit an existing line",
      r"## Convergence <n>",
      r"CONVERGE-VERDICT: CONVERGED \| GAPS",
      r"Anything else is `GAPS`"],
     []),
    ("AC-12", "sdd-converge",
     [r"you write \*\*nothing\*\*\. `plan\.md` stays byte-identical",
      r"`CONVERGED` only when every criterion is `met`",
      r"CONVERGE-SCOPE: <spec directory"],
     []),
    ("AC-18", "4d-spec",
     [r"Loop until `CONVERGED`"],
     []),
    ("AC-18", "sdd-yolo",
     [r"spec → plan → analyze → implement ⇄ converge → review → archive",
      r"Continue only on `CONVERGED`"],
     []),
    ("AC-19", "sdd-refine",
     [r"Ask \*\*one\*\* question",
      r"mark one as recommended",
      r"Apply it immediately to the section it affects",
      r"Only then ask the next question"],
     []),
    ("AC-22", "sdd-feature",
     [r"docs/specs/<yyyymmddHHMM>-<feature-name>/",
      r"The spec is born there and never moves"],
     []),
    ("AC-22", "sdd-archive",
     [r"docs/specs/<yyyymmddHHMM>-<feature-name>/",
      r"move nothing"],
     []),
    ("AC-22", "4d-spec",
     [r"born in `docs/specs/<yyyymmddHHMM>-<feature-name>/` and never moves"],
     []),
    ("AC-22", "sdd-yolo",
     [r"The spec directory `docs/specs/<yyyymmddHHMM>-<feature-name>/` stays where it is"],
     []),
]

# AC-18: the order the orchestrator names the steps in, inside its LARGE section.
LARGE_ORDER = ["/sdd-feature", "/sdd-refine", "/sdd-plan", "/sdd-analyze",
               "/sdd-implement", "/sdd-converge", "/sdd-review", "/sdd-archive"]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def read_skill(name: str) -> str:
    return squash((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))


def broken(text: str, required: list, forbidden: list) -> list:
    """Every contract sentence that is missing and every forbidden one that is there."""
    out = [f"missing: {p}" for p in required if not re.search(p, text)]
    out += [f"forbidden: {p}" for p in forbidden if re.search(p, text)]
    return out


def large_section(text: str) -> str:
    m = re.search(r"### LARGE \(score 6\+\)(.*?)(?= ## )", text)
    return m.group(1) if m else ""


def first_mentions(section: str) -> list:
    return [section.find(step) for step in LARGE_ORDER]


class SkillContractTest(unittest.TestCase):
    def test_every_skill_carries_its_contract_lines(self):
        for ac, skill, required, forbidden in CONTRACT:
            with self.subTest(criterion=ac, skill=skill):
                self.assertEqual(broken(read_skill(skill), required, forbidden), [])

    def test_removing_any_contract_line_is_caught(self):
        # Break the thing the test guards: take each sentence out, one at a time.
        for ac, skill, required, forbidden in CONTRACT:
            text = read_skill(skill)
            for pattern in required:
                with self.subTest(criterion=ac, skill=skill, removed=pattern):
                    cut = re.sub(pattern, "", text)
                    self.assertIn(f"missing: {pattern}", broken(cut, required, forbidden))

    def test_a_skill_edited_back_to_grading_is_caught(self):
        for skill, regression in (
                ("sdd-implement", " - [x] AC-01: Passed"),
                ("sdd-implement", " ### Acceptance Criteria"),
                ("sdd-review", " Then tick each criterion that passed in feature.md.")):
            with self.subTest(skill=skill, regression=regression):
                row = next(r for r in CONTRACT if r[1] == skill)
                self.assertTrue(broken(read_skill(skill) + regression, row[2], row[3]))

    def test_the_orchestrator_names_the_large_steps_in_order(self):
        section = large_section(read_skill("4d-spec"))
        self.assertTrue(section, "4d-spec has no `### LARGE (score 6+)` section")
        at = first_mentions(section)
        self.assertNotIn(-1, at, dict(zip(LARGE_ORDER, at)))
        self.assertEqual(at, sorted(at), dict(zip(LARGE_ORDER, at)))

    def test_a_reordered_large_flow_is_caught(self):
        section = large_section(read_skill("4d-spec"))
        swapped = (section.replace("/sdd-converge", "\0")
                   .replace("/sdd-implement", "/sdd-converge").replace("\0", "/sdd-implement"))
        at = first_mentions(swapped)
        self.assertNotEqual(at, sorted(at))


if __name__ == "__main__":
    unittest.main()
