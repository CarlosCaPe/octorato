#!/usr/bin/env python3
"""Tests for g__stop__diagram-first.py (rule COMMS.diagram-first).

Pins the every-reply trigger (no word floor), the opening-diagram check, the
short-text check (prose cap, no long non-bullet paragraph), the exemptions
(paste-ready ask, input-needed-only, hatch), the shape names as diagnostic text,
the block-once and fail-open contract, and the wiring (hooks.json, rules.yaml,
friction signatures, CLAUDE.md anchor, panel preflight, lineage).

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
BULLETS = "- The hook reads the staged files.\n- The ledger records one digest.\n- The reviewer checks it.\n"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LEDGER = tempfile.mkdtemp(prefix="stop-block-ledger-")  # never the live cache


def _full(obj):
    """The gate prints one short line naming a detail file (scripts/stop_block.py);
    the full text the model reads lives there."""
    if not obj or " · detail: " not in str(obj.get("reason", "")):
        return obj.get("reason") if obj else None
    text = Path(obj["reason"].rsplit(" · detail: ", 1)[1]).read_text(encoding="utf-8")
    return text.split("\n\n", 1)[1]


def _run(payload) -> dict:
    env = dict(os.environ)
    env.pop("OCTO_KERNEL_OPEN", None)
    env["OCTO_STOP_BLOCK_DIR"] = _LEDGER
    data = payload if isinstance(payload, str) else json.dumps(payload)
    cp = subprocess.run([sys.executable, str(GATE)], input=data, capture_output=True,
                        text=True, env=env, encoding="utf-8")
    out = cp.stdout.strip()
    obj = json.loads(out) if out else None
    return {"rc": cp.returncode, "json": obj, "full": _full(obj)}


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

    def test_numbered_steps_with_sub_bullets_block(self):
        reply = "1. read\n   - skip binaries\n2. hash\n   - one per commit\n3. record\n\n" + FILL
        self.assertIn("numbered", self.v(reply))

    def test_unindented_line_breaks_the_numbered_run(self):
        reply = "1. read\nNote here.\n2. hash\nNote here.\n3. record\n\n" + FILL
        self.assertNotIn("numbered", self.v(reply))
        self.assertIn("no opening diagram", self.v(reply))

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

    def test_opening_diagram_with_short_bullets_passes(self):
        self.assertEqual(self.v(DIAG + BULLETS), "")

    def test_one_lead_line_then_diagram_passes(self):
        self.assertEqual(self.v("The flow:\n\n" + DIAG + BULLETS), "")

    def test_ascii_table_fence_counts_as_diagram(self):
        table = "```\n| PR  | state  |\n|-----|--------|\n| one | review |\n```\n\n"
        self.assertEqual(self.v(table + BULLETS), "")
        box = "```text\n+-----+-----+\n| a   | b   |\n+-----+-----+\n```\n\n"
        self.assertEqual(self.v(box + BULLETS), "")

    def test_plaintext_fences_count_mermaid_does_not(self):
        body = "hook ──► ledger ──► receipt\n```\n\n"
        for info in ("plaintext", "text-plain"):
            self.assertEqual(self.v(f"```{info}\n" + body + BULLETS), "")
        self.assertNotEqual(self.v("```mermaid\n" + body + BULLETS), "")

    def test_fenced_2d_summary_may_lead(self):
        twod = "```\n2D Delegate: gate\n  Q1 Ventosas: x\n  Q2 MCP/API: N/A\n  Q3 Delegate: LOAD\n```\n\n"
        self.assertEqual(self.v(twod + DIAG + BULLETS), "")
        self.assertIn("no opening diagram", self.v(twod + "The gate reads the reply."))

    def test_diagram_then_long_paragraph_blocks(self):
        self.assertIn("paragraph", self.v(DIAG + FILL))

    def test_diagram_then_prose_over_cap_blocks(self):
        bullets = "".join(f"- item {i} touches one script and the tests ran on the branch today.\n"
                          for i in range(12))
        self.assertIn("cap", self.v(DIAG + bullets))

    def test_bullet_continuation_is_not_a_paragraph(self):
        reply = DIAG + "- The hook reads the staged files\n  and skips binaries on the way.\n"
        self.assertEqual(self.v(reply), "")

    def test_long_lead_line_blocks(self):
        lead = "word " * 25 + "\n\n"
        self.assertNotEqual(self.v(lead + DIAG + "hook -> ledger -> receipt. " + FILL), "")

    def test_bash_fence_is_not_a_diagram(self):
        self.assertNotEqual(self.v("```bash\nls -> out\n```\n\nhook -> ledger -> receipt. " + FILL), "")

    def test_arrow_token_counts_one_per_arrow(self):
        rx = self.g._ARROW
        self.assertEqual(len(rx.findall("a -> b --> c ---> d")), 3)
        self.assertEqual(len(rx.findall("a => b → c ⟶ d ─► e")), 4)
        self.assertEqual(rx.findall("a --!> b <!-- c"), [])

    def test_html_comment_end_is_not_a_flow(self):
        self.assertNotIn("flow", self.v("<!-- note --!> and <!-- other --!> here. " + FILL))

    def test_short_reply_without_diagram_blocks(self):
        self.assertNotEqual(self.v("hook -> ledger -> receipt, done."), "")
        self.assertNotEqual(self.v("Converge pass running in the background."), "")

    def test_reason_carries_the_operator_phrase(self):
        self.assertIn("flow first; text short and in bullets; offer more detail in one line "
                      "instead of writing it", self.g.build_reason("x"))

    def test_word_floor_ignores_glyph_tokens(self):
        self.assertEqual(self.g.count_words(["─► ├─ 1. ok - -> two"]), 2)

    def test_paste_ask_exempt(self):
        self.assertEqual(self.v("hook -> ledger -> receipt. " + FILL, "pásame el mensaje para pegar"), "")

    def test_input_needed_only_exempt(self):
        self.assertEqual(self.v("Two PRs touch the same gate.\n\ninput-needed: which branch?"), "")

    def test_input_needed_with_long_lead_blocks(self):
        self.assertNotEqual(self.v("hook -> ledger -> receipt. " + FILL + "\n\ninput-needed: which branch?"), "")

    def test_input_needed_not_last_does_not_exempt(self):
        self.assertNotEqual(self.v("input-needed: which?\n\nhook -> ledger -> receipt. " + FILL), "")

    def test_hatch_exempt(self):
        self.assertEqual(self.v("hook -> ledger -> receipt. " + FILL + "\ndiagram-ok"), "")

    def test_shapes_inside_code_quote_blockquote_are_not_named(self):
        for reply in ("Run `a -> b -> c` now. " + FILL, 'He said "a -> b -> c". ' + FILL,
                      "> a -> b -> c\n\n" + FILL):
            out = self.v(reply)
            self.assertIn("no opening diagram", out)
            self.assertNotIn("flow", out)

    def test_plain_long_prose_blocks(self):
        self.assertIn("no opening diagram", self.v(FILL * 3))

    def test_footer_and_disclose_do_not_count(self):
        reply = (DIAG + BULLETS + "\n\nProvenance: Basis: " + "a -> b " * 80 + "· Engine: x"
                 + "\n💡 Unlock-suggestion: " + "x -> y " * 80)
        self.assertEqual(self.v(reply), "")

    def test_empty_reply_passes(self):
        self.assertEqual(self.v(""), "")


class ProcessTest(unittest.TestCase):
    def test_block_on_violation(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run({"transcript_path": _transcript(Path(d), "a -> b -> c. " + FILL)})
        self.assertEqual(r["rc"], 0)
        self.assertEqual(r["json"]["decision"], "block")
        self.assertIn("DIAGRAM-FIRST", r["json"]["reason"])
        self.assertIn("diagram-ok", r["full"])
        self.assertNotIn("\n", r["json"]["reason"])

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
        for v in ("flow", "numbered", "numbered_nested", "before_after", "es", "status", "structure",
                  "late_diagram", "status_line_25", "long_paragraph", "prose_cap", "plain_60",
                  "input_long_lead", "flipped_status_line", "flipped_plain_prose", "2d_lead_no_diagram"):
            self.assertIn(f"violation_{v}.json", names)
        for b in ("", "_paste_ready", "_input_only", "_status_diagram", "_table_diagram", "_hatch",
                  "_stop_hook_active", "_2d_lead", "_plaintext_fence"):
            self.assertIn(f"benign{b}.json", names)

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
