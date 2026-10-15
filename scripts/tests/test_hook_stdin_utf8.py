#!/usr/bin/env python3
"""Hook scripts decode their stdin payload as UTF-8, whatever the host default.

Claude Code writes the hook payload as UTF-8 JSON. On Windows, Python's default
stdin encoding is the ANSI code page (cp1252), so a script that calls
`sys.stdin.read()` without reconfiguring it reads every non-ASCII character as
mojibake. For the reply-panel gate that changed the digest of any reply
carrying a middle dot or an accent, so no panel receipt could ever match it.

The behaviour case pipes UTF-8 bytes into the reply gate with PYTHONUTF8 and
PYTHONIOENCODING removed, and checks the digest the gate reports against
panel_digest on the original text. The structure case checks every script that
reads stdin reconfigures it at module level, after `import sys`.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = SCRIPTS.parent / "registry" / "fixtures" / "FLOW.panel-before-reply"
sys.path.insert(0, str(SCRIPTS))

import panel_digest  # noqa: E402

# The arming-surface gate is edited only by the operator's own hand; it is
# tracked here so the gap stays visible instead of silently passing.
KNOWN_GAPS = {"g__pretool__arming-surface.py"}


def _reconfigures_stdin(src: str) -> bool:
    tree = ast.parse(src)
    sys_seen = False
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name == "sys" for a in node.names):
            sys_seen = True
        if isinstance(node, (ast.Try, ast.For)):
            seg = ast.get_source_segment(src, node) or ""
            if "reconfigure" in seg and "stdin" in seg:
                return sys_seen
    return False


class HookStdinUtf8(unittest.TestCase):
    def test_reply_gate_digest_survives_non_ascii(self):
        fx = json.loads((FIXTURES / "violation_ac03_no_receipt.json").read_text(encoding="utf-8"))
        text = fx["last_assistant_message"]
        self.assertTrue(any(ord(c) > 127 for c in text), "fixture must carry a non-ASCII char")
        payload = {k: v for k, v in fx.items() if k != "_fixture"}
        payload["transcript_path"] = str(FIXTURES / fx["transcript_path"])
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        r = subprocess.run([sys.executable, str(SCRIPTS / "g__stop__reply-panel.py")],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, env=env, timeout=60)
        err = r.stderr.decode("utf-8", "replace")
        m = re.search(r"Digest: ([0-9a-f]{64})", err)
        self.assertIsNotNone(m, err)
        self.assertEqual(m.group(1), panel_digest.digest(text, recipients=["operator"]))

    def test_every_stdin_reader_reconfigures(self):
        missing = []
        for f in sorted(SCRIPTS.glob("*.py")):
            src = f.read_text(encoding="utf-8")
            reads = "sys.stdin.read()" in src or "json.load(sys.stdin)" in src
            if reads and not _reconfigures_stdin(src):
                missing.append(f.name)
        self.assertEqual(sorted(set(missing) - KNOWN_GAPS), [])


if __name__ == "__main__":
    unittest.main()
