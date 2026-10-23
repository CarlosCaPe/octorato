#!/usr/bin/env python3
"""Tests for the reply panel's source class (FLOW.panel-before-reply, FR-06).

Pins the Basis parser: `Basis` followed by a colon or whitespace, any case,
the label followed by a colon or a `·` separator; a Basis that is empty or
names self / own reasoning stays SELF; a word that merely contains `self`
inside a longer token does not make it SELF.

Stdlib only:

    python3 -m unittest scripts.tests.test_reply_panel_source_class
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
GATE = SCRIPTS / "g__stop__reply-panel.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("reply_panel_gate_sc", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RP = _load_gate()
BODY = "The row counts match the source table.\n\n"

SOURCED = [
    "Provenance: Basis /home/u/notes.md:11-62 · Engine: main loop",
    "Procedencia: Basis REST de SharePoint DEV (status 200) · /home/u/a.md",
    "Procedencia · Basis: /tmp/a.md",
    "Provenance · Basis: output of `ai-sync` and `brain_doctor.py --fast`",
    "Provenance: basis git log origin/master",
    "Provenance: BASIS: git log",
    "**Provenance:** **Basis** migration.log",
    "Provenance: Basis: scripts/selftest.py",
    "Provenance: Basis: `self-review.md`, migration.log",
    "Provenance: Basis: self_check.sh:12-40",
    "Provenance: Basis: git log, checked myself",
    "Provenance: Basis: /opt/selfhosted/run.log",
]

SELF = [
    "Provenance: Basis: myself",
    "Provenance: Basis: self-review",
    "Provenance: Basis self-assessment",
    "Provenance: Basis: self-review of scripts/x.py, migration.log",
    "Provenance: Basis: self-evident",
    "Provenance: Basis: SELF · Engine: main loop",
    "Provenance: Basis self",
    "Provenance: Basis own reasoning",
    "Provenance: Basis: my own reasoning",
    "Provenance: Basis: razonamiento propio",
    "Provenance: Basis: eigene Überlegung",
    "Provenance: Basis: eigene Ueberlegung",
    "Provenance: Basis: git log + own reasoning",
    "Provenance: Basis: migration.log, myself",
    "Provenance: Basis: SELF (no sources)",
    "Provenance: Basis",
    "Provenance: Basis · Engine: main loop",
    "Provenance: Basis none",
    "Provenance: Basis —",
    "Provenance: Engine: main loop",
    "Provenance: Basisfoo bar",
    "Procedencia: /tmp/panel_block.txt",
    "Procedencia · Basis: razonamiento propio",
    "Provenance: Basis: a.md\nProvenance: Basis self",
]


class SourceClassTests(unittest.TestCase):
    def test_sourced(self):
        for footer in SOURCED:
            with self.subTest(footer=footer):
                self.assertEqual(RP.source_class(BODY + footer), "SOURCED")

    def test_self(self):
        for footer in SELF:
            with self.subTest(footer=footer):
                self.assertEqual(RP.source_class(BODY + footer), "SELF")

    def test_no_footer_is_self(self):
        self.assertEqual(RP.source_class("Done."), "SELF")


Q = "input-needed: What is the name of the standby database host?"
INPUT = [
    "The rollback needs one value that is not in the log.\n\n" + Q,
    "Falta un dato.\n\ninput-needed: ¿Cuál es el RFC del cliente?\n\nProcedencia: Basis: la orden",
    "**input-needed:** What is the tenant id of the staging workspace?",
]
NOT_INPUT = [
    ("word " * 70) + "\n" + Q,                                      # over the word cap
    "One value is missing.\n\ninput-needed: Do you want it today or tomorrow?",   # menu
    "Falta un paso.\n\ninput-needed: ¿Confirmas el pago?",          # consent (irreducible)
    "Falta un dato.\n\ninput-needed: ¿Lo mando así?",               # permission
    "Falta un dato.\n\ninput-needed: ¿Procedo?",                    # opener
    "Merged the fix to master.\n\n" + Q,                           # a claim in the body
    "Waiting on 2 reviewers.\n\n" + Q,                             # a digit in the body
    "Is the log complete?\n\n" + Q,                                # two questions
    "One value is missing.\n\n" + Q + "\n\nThen I run the rollback.",  # not last
    "Provenance: Basis: x\n" + Q,                                   # footer before the question
    "One value is missing.\n\ninput-needed: the host name",          # no question mark
    "Q?\n" + Q + "\nProvenance: a\nProvenance: b",                  # two provenance lines
    "The bug was the parser and the branch now carries the fix for staging and production alike.\n\n" + Q,  # long context
    "The parser bug is gone.\nThe rollback needs one value.\n\n" + Q,  # two context lines
    "One value.\n\ninput-needed: Now that I merged the fix, what is the host?",  # claim in question
]


class InputNeededTests(unittest.TestCase):
    def test_input_class_quorum_one(self):
        self.assertEqual(RP.QUORUM["INPUT"], 1)
        for text in INPUT:
            with self.subTest(text=text[:50]):
                self.assertEqual(RP.source_class(text), "INPUT")

    def test_not_input(self):
        for text in NOT_INPUT:
            with self.subTest(text=text[:50]):
                self.assertNotEqual(RP.source_class(text), "INPUT")

    def test_explicit_self_basis_wins(self):
        self.assertEqual(RP.source_class("One value.\n\n" + Q + "\n\nProvenance: Basis: self"), "SELF")
        self.assertEqual(RP.source_class("One value.\n\n" + Q + "\n\nProvenance: Basis:"), "SELF")

    def test_long_reply_with_trailing_line_keeps_self(self):
        self.assertEqual(RP.source_class(NOT_INPUT[0]), "SELF")


if __name__ == "__main__":
    unittest.main()
