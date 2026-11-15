#!/usr/bin/env python3
"""Tests for g__stop__diagram-first.py (rule COMMS.diagram-first).

Pins the four shapes, the opening-diagram check, the word floor, the
exemptions (paste-ready ask, trailing input-needed, hatch), the quote and code
awareness, the block-once and fail-open contract, and the wiring (hooks.json,
rules.yaml, friction signatures, CLAUDE.md anchor, panel preflight, lineage).

Stdlib only:

    python3 -m unittest scripts.tests.test_diagram_first
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
GATE = SCRIPTS / "g__stop__diagram-first.py"
FIXTURES = ROOT / "registry" / "fixtures" / "COMMS.diagram-first"

FILL = ("The change is small and it touches one script, so the risk stays low. The tests ran on "
        "the branch and the result matches what the spec asks for, with no new dependency added. ") * 3
DIAG = "```\nhook ──► ledger ──► receipt\n         └─ ✓ written\n```\n\n"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(payload) -> dict:
    env = dict(os.environ)
    env.pop("OCTO_KERNEL_OPEN", None)
    data = payload if isinstance(payload, str) else json.dumps(payload)
    cp = subprocess.run([sys.executable, str(GATE)], input=data, capture_output=True,
                        text=True, env=env, encoding="utf-8")
    out = cp.stdout.strip()
    return {"rc": cp.returncode, "json": json.loads(out) if out else None}


def _transcript(tmp: Path, text: str, prompt: str = "explain it") -> str:
    p = tmp / "t.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "content": [{"type": "text", "text": text}]}}]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return str(p)


class MatcherTest(unittest.TestCase):
    def setUp(self):
        self.g = _load(GATE, "diagram_gate")
        self.rx = self.g._paste_ask_regex()

    def v(self, reply, prompt="explain it"):
        return self.g.find_violation(prompt, reply, self.rx)

    def test_flow_arrows_block(self):
        self.assertIn("flow", self.v("It goes hook -> ledger -> receipt. " + FILL))

    def test_numbered_steps_block(self):
        self.assertIn("numbered", self.v("Steps:\n\n1. read\n2. hash\n3. record\n\n" + FILL))

    def test_before_after_block_en_and_es(self):
        self.assertIn("before/after", self.v("**Before:** slow.\n\n**After:** fast.\n\n" + FILL))
        self.assertIn("before/after", self.v("- Antes: lento.\n- Después: rápido.\n\n" + FILL))

    def test_status_block(self):
        self.assertIn("status", self.v("- PR 1: merged\n- PR 2: pending\n- PR 3: blocked\n\n" + FILL))

    def test_status_table_rows_block(self):
        table = "| PR | State |\n|---|---|\n| 1 | merged |\n| 2 | pending |\n| 3 | ✗ |\n\n"
        self.assertIn("status", self.v(table + FILL))

    def test_structure_block(self):
        self.assertIn("structure", self.v("- a\n  - b\n  - c\n- d\n\n" + FILL))

    def test_late_diagram_says_move_to_top(self):
        out = self.v("It goes hook -> ledger -> receipt. " + FILL + "\n\n" + DIAG)
        self.assertIn("move it to the top", out)

    def test_opening_diagram_passes(self):
        self.assertEqual(self.v(DIAG + "It goes hook -> ledger -> receipt. " + FILL), "")

    def test_one_lead_line_then_diagram_passes(self):
        self.assertEqual(self.v("The flow:\n\n" + DIAG + "hook -> ledger -> receipt. " + FILL), "")

    def test_long_lead_line_blocks(self):
        lead = "word " * 25 + "\n\n"
        self.assertNotEqual(self.v(lead + DIAG + "hook -> ledger -> receipt. " + FILL), "")

    def test_bash_fence_is_not_a_diagram(self):
        self.assertNotEqual(self.v("```bash\nls -> out\n```\n\nhook -> ledger -> receipt. " + FILL), "")

    def test_short_reply_passes(self):
        self.assertEqual(self.v("hook -> ledger -> receipt, done."), "")

    def test_word_floor_ignores_glyph_tokens(self):
        self.assertEqual(self.g.count_words(["─► ├─ 1. ok - -> two"]), 2)

    def test_paste_ask_exempt(self):
        self.assertEqual(self.v("hook -> ledger -> receipt. " + FILL, "pásame el mensaje para pegar"), "")

    def test_trailing_input_needed_exempt(self):
        self.assertEqual(self.v("hook -> ledger -> receipt. " + FILL + "\n\ninput-needed: which branch?"), "")

    def test_input_needed_not_last_does_not_exempt(self):
        self.assertNotEqual(self.v("input-needed: which?\n\nhook -> ledger -> receipt. " + FILL), "")

    def test_hatch_exempt(self):
        self.assertEqual(self.v("hook -> ledger -> receipt. " + FILL + "\ndiagram-ok"), "")

    def test_shapes_inside_code_quote_blockquote_pass(self):
        self.assertEqual(self.v("Run `a -> b -> c` now. " + FILL), "")
        self.assertEqual(self.v('He said "a -> b -> c". ' + FILL), "")
        self.assertEqual(self.v("> a -> b -> c\n\n" + FILL), "")
        self.assertEqual(self.v("```\na -> b -> c\n```\n" + FILL), "")

    def test_plain_long_prose_passes(self):
        self.assertEqual(self.v(FILL * 3), "")

    def test_footer_and_disclose_do_not_count(self):
        reply = ("Done. " + "\n\nProvenance: Basis: a -> b -> c · Engine: x"
                 + "\n💡 Unlock-suggestion: x -> y -> z")
        self.assertEqual(self.v(reply + " " + FILL), "")

    def test_empty_reply_passes(self):
        self.assertEqual(self.v(""), "")


class ProcessTest(unittest.TestCase):
    def test_block_on_violation(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run({"transcript_path": _transcript(Path(d), "a -> b -> c. " + FILL)})
        self.assertEqual(r["rc"], 0)
        self.assertEqual(r["json"]["decision"], "block")
        self.assertIn("DIAGRAM-FIRST", r["json"]["reason"])
        self.assertIn("diagram-ok", r["json"]["reason"])

    def test_stop_hook_active_passes(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run({"transcript_path": _transcript(Path(d), "a -> b -> c. " + FILL),
                      "stop_hook_active": True})
        self.assertEqual((r["rc"], r["json"]), (0, None))

    def test_bad_stdin_and_missing_transcript_fail_open(self):
        self.assertEqual(_run("not json")["json"], None)
        self.assertEqual(_run({"transcript_path": "/nonexistent/t.jsonl"})["json"], None)
        self.assertEqual(_run("not json")["rc"], 0)


class WiringTest(unittest.TestCase):
    def test_registered_on_stop_in_hooks_json(self):
        hooks = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        cmds = [h.get("command", "") for grp in hooks["Stop"] for h in grp.get("hooks", [])]
        self.assertTrue(any("g__stop__diagram-first.py" in c for c in cmds))

    def test_panel_preflight_runs_it(self):
        pf = _load(SCRIPTS / "panel_preflight.py", "panel_preflight_t")
        names = [h[0] for h in pf.stop_hooks() if h[0] not in pf.SKIP]
        self.assertIn("g__stop__diagram-first.py", names)

    def test_rule_entry_anchor_and_fixtures(self):
        rules = (ROOT / "registry" / "rules.yaml").read_text(encoding="utf-8")
        self.assertIn("- id: COMMS.diagram-first", rules)
        self.assertIn("anchor: Diagram-first", rules)
        block = rules.split("- id: COMMS.diagram-first", 1)[1].split("\n- id:", 1)[0]
        self.assertIn("liveness_required: FIRES", block)
        self.assertIn("### Diagram-first", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        names = {p.name for p in FIXTURES.glob("*.json")}
        for v in ("flow", "numbered", "before_after", "es", "status", "structure", "late_diagram"):
            self.assertIn(f"violation_{v}.json", names)
            self.assertIn(f"benign_{v}.json", names)
        for b in ("short", "paste_ready", "input_needed", "status_line", "hatch", "codeblock",
                  "blockquote", "quoted", "plain_prose", "lead_line", "stop_hook_active"):
            self.assertIn(f"benign_{b}.json", names)

    def test_friction_signature_matches_the_block_text(self):
        raw = json.loads((ROOT / "registry" / "friction-signatures.json").read_text(encoding="utf-8"))
        rows = [s for s in raw["signatures"] if s["gate"] == "g__stop__diagram-first.py"]
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["pattern"], GATE.read_text(encoding="utf-8"))

    def test_lineage_node(self):
        lin = (ROOT / "connectome" / "lineage.yaml").read_text(encoding="utf-8")
        node = lin.split("- id: diagram-first-gate", 1)[1].split("\n  - id:", 1)[0]
        for s in ("scripts/g__stop__diagram-first.py", "registry/rules.yaml",
                  "registry/fixtures/COMMS.diagram-first", "hooks.json", "CLAUDE.md",
                  "skills/human-cadence/SKILL.md"):
            self.assertIn(s, node)

    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GATE), "--selftest", str(FIXTURES)],
                            capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


if __name__ == "__main__":
    unittest.main()
