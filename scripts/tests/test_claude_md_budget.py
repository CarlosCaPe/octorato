#!/usr/bin/env python3
"""brain_doctor's claude-md-budget check (spec v10, AC-17).

The constitution must load at most 12,000 tokens by the committed estimator
(characters / 4) and carry no section written in Spanish. The pre-#392
CLAUDE.md (master b2c8b9a) is kept as a plain-text sample because CI checks
out one commit and the historical blob is not reachable there; its sha256 is
pinned below.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402

PRE_392 = Path(__file__).resolve().parent / "claude-md-samples" / "pre-392-CLAUDE.md.txt"
PRE_392_SHA256 = "585210a3bfd6eb617d7dc1a9e85cf7ad1798f2cab267216268fa764af17c4ea7"


def check_text(text: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "CLAUDE.md")
        p.write_text(text, encoding="utf-8")
        return brain_doctor.check_claude_md_budget(False, path=p)


class ClaudeMdBudgetTest(unittest.TestCase):
    def test_current_claude_md_passes(self):
        r = brain_doctor.check_claude_md_budget(False)
        self.assertEqual(r.status, brain_doctor.PASS, r.message)

    def test_pre_392_claude_md_fails_on_size_and_language(self):
        raw = PRE_392.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PRE_392_SHA256)
        text = raw.decode("utf-8")
        self.assertEqual(brain_doctor.estimate_tokens(text), 24154)
        r = check_text(text)
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("24,154 tokens (chars/4) over the 12,000 ceiling", r.message)
        heads = [h for h, _, _ in brain_doctor.spanish_sections(text)]
        self.assertEqual(len(heads), 3, heads)
        for start in ("### Unsourced-attribute (la circunstancia",
                      "### Unsourced-absence (un ",
                      "### ULTRA RULE — Do-it-today (no dejes"):
            self.assertTrue(any(h.startswith(start) for h in heads), (start, heads))
        self.assertIn("3 non-English section(s)", r.message)

    def test_one_token_over_the_ceiling_fails(self):
        ceiling = brain_doctor.CLAUDE_MD_TOKEN_CEILING
        at = "## Rule\n" + "x" * (ceiling * 4 - len("## Rule\n") + 3)
        self.assertEqual(brain_doctor.estimate_tokens(at), ceiling)
        self.assertEqual(check_text(at).status, brain_doctor.PASS)
        over = at + "x"
        self.assertEqual(brain_doctor.estimate_tokens(over), 12001)
        r = check_text(over)
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("12,001 tokens", r.message)

    def test_spanish_data_inside_an_english_section_does_not_trip(self):
        text = (
            "## Paste-ready message\n"
            "When the ask is \"pásame el mensaje / sin formato / para pegar\", the message "
            "ships raw. Filler words to avoid (EN: delve/leverage · ES: ahondar/aprovechar/"
            "utilizar/robusto/fluido/fomentar/exhaustivo, además, asimismo, en conclusión). "
            "A bare go-ahead such as `dale` or `sí` never counts as a send request, and a "
            "quoted trigger like `para que lo pegues en el chat` is data the gate matches on.\n"
        )
        self.assertEqual(brain_doctor.spanish_sections(text), [])
        self.assertEqual(check_text(text).status, brain_doctor.PASS)

    def test_a_spanish_prose_section_fails(self):
        text = (
            "## Rule\nEnglish prose that explains what the rule enforces and why it exists, "
            "with enough words to be measured as a section of its own here.\n\n"
            "### Regla\nUn hecho circunstancial no autoriza el atributo categórico de la cosa, y "
            "el adjetivo que la contraparte nunca dijo es una pregunta, no un dato, por eso "
            "jamás viaja dentro de un entregable sin su frase textual de la contraparte.\n"
        )
        hits = brain_doctor.spanish_sections(text)
        self.assertEqual([h for h, _, _ in hits], ["### Regla"])
        self.assertEqual(check_text(text).status, brain_doctor.FAIL)

    def test_fixture_pair_selftest(self):
        fx = ROOT / "registry" / "fixtures" / "META.constitution-budget"
        self.assertEqual(brain_doctor.selftest_claude_md_budget(fx), 0)
        # Two benign files are one-edit twins of a violation (one char under
        # budget, the Spanish section quoted). The third is an English control
        # carrying Spanish proper nouns, which kills the ratio=0.0 mutation.
        over = (fx / "violation_over_budget.md").read_text(encoding="utf-8")
        self.assertEqual(brain_doctor.estimate_tokens(over), 12001)
        self.assertEqual(brain_doctor.estimate_tokens(
            (fx / "benign_over_budget_minus_one_char.md").read_text(encoding="utf-8")), 12000)

    def test_runs_in_fast_and_registry_profiles(self):
        self.assertIn("claude-md-budget", dict(brain_doctor.CHECKS))
        self.assertNotIn("claude-md-budget", brain_doctor.SLOW_CHECKS)
        src = (ROOT / "scripts" / "brain_doctor.py").read_text(encoding="utf-8")
        self.assertIn("+ [check_claude_md_budget(args.fix)])", src)


if __name__ == "__main__":
    unittest.main()
