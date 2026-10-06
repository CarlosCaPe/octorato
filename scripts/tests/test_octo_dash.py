#!/usr/bin/env python3
"""Anchors for `octo dash` (scripts/octo_dash.py) and the status line.

Pinned: untrusted text (PR titles, branch names, URLs, friction gate names)
renders inert; every missing source degrades to a message instead of failing;
the PR section reads only the stored snapshot and states its age; the status
line answers from its cache with a spec field read live, and a smoke timing
that only catches an order-of-magnitude regression (AC-20 is measured over
100 calls by hand, never asserted here, so a loaded CI box cannot flake it).
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import octo_dash  # noqa: E402
import statusline  # noqa: E402


class Sandbox(unittest.TestCase):
    def setUp(self):
        self._home = os.environ.get("HOME")
        self.home = tempfile.mkdtemp(prefix="octo-dash-test-")
        os.environ["HOME"] = self.home
        self.root = Path(self.home) / "brain"
        (self.root / "docs" / "specs").mkdir(parents=True)

    def tearDown(self):
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home
        shutil.rmtree(self.home, ignore_errors=True)

    def spec(self, name, status, plan="- [x] T01 a\n- [ ] T02 b\n"):
        d = self.root / "docs" / "specs" / name
        d.mkdir()
        (d / "feature.md").write_text(f"# F\n\n> **Spec-Format:** ears-1\n> **Status:** {status}\n",
                                      encoding="utf-8")
        if plan is not None:
            (d / "plan.md").write_text(plan, encoding="utf-8")
        return d

    def snapshot(self, prs, age=120):
        octo_dash.cache_dir().mkdir(parents=True, exist_ok=True)
        octo_dash.snapshot_path().write_text(
            json.dumps({"taken_ts": time.time() - age, "prs": prs}), encoding="utf-8")

    def page(self):
        return octo_dash.render(octo_dash.collect(self.root))


class DashEscaping(Sandbox):
    def test_script_title_renders_inert(self):
        self.snapshot([{"number": 9, "title": "<script>alert('x')</script>",
                        "headRefOid": "b" * 40, "headRefName": "evil\"><svg onload=1>",
                        "isDraft": True, "url": "javascript:alert(1)"}])
        page = self.page()
        low = page.lower()
        self.assertNotIn("<script", low)
        self.assertNotIn("<svg", low)
        self.assertNotIn("javascript:", low)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", page)

    def test_only_github_pull_urls_become_links(self):
        self.snapshot([{"number": 3, "title": "t", "headRefOid": "c" * 40, "headRefName": "b",
                        "url": "https://github.com/owner/repo/pull/3"},
                       {"number": 4, "title": "t", "headRefOid": "d" * 40, "headRefName": "b",
                        "url": "https://evil.example/pull/4"}])
        page = self.page()
        self.assertIn('href="https://github.com/owner/repo/pull/3"', page)
        self.assertNotIn("evil.example", page)

    def test_friction_gate_name_escaped(self):
        p = octo_dash.friction_ledger_path()
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"gate": "<b>g</b>", "ts": time.time()}) + "\nnot json\n",
                     encoding="utf-8")
        page = self.page()
        self.assertIn("&lt;b&gt;g&lt;/b&gt;", page)
        self.assertIn("2 ledger line(s), 1 line(s) with no recognised fields", page)

    def test_page_has_no_external_fetch(self):
        page = self.page().lower()
        for needle in ("<script", "http://", "<link", "@import", "fonts.googleapis"):
            self.assertNotIn(needle, page)


class DashMissingData(Sandbox):
    def test_everything_missing_still_renders(self):
        shutil.rmtree(self.root / "docs")
        page = self.page()
        for text in ("no docs/specs directory", "no snapshot yet", "not available",
                     "Gate receipt", "Live kernel processes"):
            self.assertIn(text, page)

    def test_corrupt_snapshot_is_named(self):
        octo_dash.cache_dir().mkdir(parents=True)
        octo_dash.snapshot_path().write_text("{not json", encoding="utf-8")
        self.assertIn("snapshot unreadable", self.page())

    def test_spec_counts_and_age(self):
        self.spec("200001010000-alpha", "draft")
        self.spec("200001020000-beta", "converged", plan=None)
        self.snapshot([], age=3700)
        page = self.page()
        self.assertIn("1/2", page)
        self.assertIn("0/0", page)
        self.assertIn("snapshot age: 1h01m", page)
        self.assertIn("no open pull requests in the snapshot", page)

    def test_write_page_prints_a_path_under_cache(self):
        out = octo_dash.write_page(self.root)
        self.assertTrue(out.is_file())
        self.assertEqual(out.parent, octo_dash.cache_dir())

    def test_refresh_failure_keeps_rendering(self):
        env = dict(os.environ, PATH="/nonexistent")
        cp = subprocess.run([sys.executable, str(SCRIPTS / "octo_dash.py"), "--refresh",
                             "--root", str(self.root)], capture_output=True, text=True,
                            env=env, timeout=60)
        self.assertEqual(cp.returncode, 2, cp.stderr)
        self.assertIn("snapshot failed", cp.stderr)
        self.assertTrue(Path(cp.stdout.strip()).is_file())

    def test_selftest(self):
        self.assertEqual(octo_dash.selftest(), 0)

    def test_non_object_snapshot_is_named(self):
        octo_dash.cache_dir().mkdir(parents=True)
        for raw, kind in (("[]", "list"), ("null", "NoneType"), ("42", "int"), ('"str"', "str")):
            octo_dash.snapshot_path().write_text(raw, encoding="utf-8")
            page = self.page()
            self.assertIn(f"snapshot malformed: top level is {kind}", page, raw)

    def test_malformed_prs_value_is_named(self):
        octo_dash.cache_dir().mkdir(parents=True, exist_ok=True)
        for prs, kind in (("oops", "str"), ({"number": 1}, "dict")):
            octo_dash.snapshot_path().write_text(
                json.dumps({"taken_ts": time.time(), "prs": prs}), encoding="utf-8")
            self.assertIn(f"snapshot malformed: prs is {kind}, not a list", self.page())
        octo_dash.snapshot_path().write_text(
            json.dumps({"taken_ts": time.time(), "prs": [7, {"number": 2, "title": "ok"}]}),
            encoding="utf-8")
        page = self.page()
        self.assertIn("1 pull request entry(ies) not an object", page)
        self.assertIn("#2", page)


class GitOptionalLocks(Sandbox):
    """The gate reads run `git status`, which would take .git/index.lock in
    the live brain; every git call they make must carry GIT_OPTIONAL_LOCKS=0."""

    def _record(self):
        import receipt_ledger
        seen, real = [], receipt_ledger._git

        def spy(brain_dir, *args, **kw):
            seen.append(receipt_ledger.scrubbed_env().get("GIT_OPTIONAL_LOCKS"))
            return real(brain_dir, *args, **kw)
        receipt_ledger._git = spy
        self.addCleanup(setattr, receipt_ledger, "_git", real)
        return seen

    def test_dash_gate_read(self):
        seen = self._record()
        os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        octo_dash.read_gate(SCRIPTS.parent)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"0"})
        self.assertNotIn("GIT_OPTIONAL_LOCKS", os.environ)  # restored after

    def test_statusline_refresh(self):
        seen = self._record()
        saved = os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        self.addCleanup(lambda: os.environ.pop("GIT_OPTIONAL_LOCKS", None) if saved is None
                        else os.environ.__setitem__("GIT_OPTIONAL_LOCKS", saved))
        statusline.compute_state(str(SCRIPTS.parent))
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"0"})


class DashFriction(Sandbox):
    """Field names follow friction_ledger.py (gate, kind, code, session, ts)."""

    def setUp(self):
        super().setUp()
        self.fdir = Path(self.home) / "friction"
        self.fdir.mkdir()
        os.environ["OCTO_FRICTION_DIR"] = str(self.fdir)
        self.addCleanup(os.environ.pop, "OCTO_FRICTION_DIR", None)

    def test_rows_and_unrecognised(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        lines = [{"v": 1, "key": "k1", "ts": now, "session": "s", "kind": "deny",
                  "event": "PreToolUse", "gate": "g__demo.py", "code": "send-ask", "tool": "Bash"},
                 {"v": 1, "key": "k2", "ts": now, "gate": "g__demo.py", "code": "send-ask"},
                 {"v": 1, "key": "k3", "ts": now, "gate": ""},
                 ["not", "an", "object"]]
        (self.fdir / "ledger.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
        page = self.page()
        self.assertIn("5 ledger line(s), 3 line(s) with no recognised fields", page)
        self.assertIn("g__demo.py", page)
        self.assertIn("send-ask", page)
        self.assertNotIn(">?<", page)

    def test_naive_and_z_timestamps_are_utc(self):
        z = octo_dash._ts_of({"ts": "2026-10-06T12:00:00Z"})
        naive = octo_dash._ts_of({"ts": "2026-10-06T12:00:00"})
        self.assertEqual(z, naive)
        self.assertEqual(z, 1791288000.0)
        # A ledger line written 2 h ago with a Z timestamp lands in the 24 h window.
        two_h = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
        (self.fdir / "ledger.jsonl").write_text(
            json.dumps({"v": 1, "key": "k", "ts": two_h, "gate": "g__z.py", "code": "c"}) + "\n",
            encoding="utf-8")
        row = octo_dash.read_friction(time.time())["rows"][0]
        self.assertEqual((row["gate"], row["d1"], row["d7"]), ("g__z.py", 1, 1))

    def test_non_numeric_fp_rate_renders_dash(self):
        import octo
        rep = {"days": 7, "ledger_rows": 1, "latency_rows": 0,
               "gates": [{"gate": "g", "denies": 1, "labelled": {"fp_rate": "high"}},
                         {"gate": "h", "denies": 1, "labelled": {"fp_rate": True}}]}
        had = hasattr(octo, "friction_report")
        old = getattr(octo, "friction_report", None)
        octo.friction_report = lambda days: rep
        self.addCleanup(lambda: setattr(octo, "friction_report", old) if had
                        else delattr(octo, "friction_report"))
        page = self.page()
        self.assertIn("octo friction, last 7 day(s)", page)
        self.assertNotIn("high", page)

    def test_octo_friction_report_rendered_in_process(self):
        import octo
        rep = {"days": 7, "since": "x", "ledger_rows": 4, "latency_rows": 2, "ledger_dir": "d",
               "label_window": None,
               "gates": [{"gate": "<i>g</i>", "denies": 4, "sessions": 1, "codes": {},
                          "latency_n": 2, "latency_p50_ms": 12.0, "latency_p95_ms": 40.0,
                          "timeouts": 0, "labelled": {"tp": 1, "fp": 3, "fp_rate": 0.75}}]}
        had = hasattr(octo, "friction_report")
        old = getattr(octo, "friction_report", None)
        octo.friction_report = lambda days: rep
        self.addCleanup(lambda: setattr(octo, "friction_report", old) if had
                        else delattr(octo, "friction_report"))
        page = self.page()
        self.assertIn("octo friction, last 7 day(s): 4 deny/block row(s)", page)
        self.assertIn("&lt;i&gt;g&lt;/i&gt;", page)
        self.assertIn("75%", page)


class StatusLine(Sandbox):
    def run_line(self, payload):
        return subprocess.run([sys.executable, str(SCRIPTS / "statusline.py")],
                              input=json.dumps(payload), capture_output=True, text=True,
                              env=dict(os.environ), timeout=30)

    def test_active_spec_newest_not_converged(self):
        self.spec("200001010000-old-open", "draft")
        self.spec("200001020000-newer-open", "approved")
        self.spec("200001030000-newest-done", "converged")
        got = statusline.active_spec(str(self.root), brain=str(self.root))
        self.assertEqual(got["name"], "200001020000-newer-open")

    def test_cwd_inside_a_spec_wins(self):
        self.spec("200001010000-old-open", "draft")
        done = self.spec("200001030000-newest-done", "converged")
        got = statusline.active_spec(str(done), brain=str(self.root))
        self.assertEqual(got["name"], "200001030000-newest-done")

    def test_line_from_cached_state(self):
        self.spec("200001010000-alpha", "draft")
        statusline.write_state({"ts": time.time(), "gate": "ok", "live": 3})
        out = statusline.line({"workspace": {"current_dir": str(self.root)}}, statusline.read_state())
        self.assertTrue(out.startswith("gate ok · 3 live · spec alpha draft 1/2"), out)

    def test_ansi_and_control_bytes_stripped_from_spec_name(self):
        self.spec("200001010000-a\x1b[31mred\x1b]0;title\x07b\x07c", "draft")
        statusline.write_state({"ts": time.time(), "gate": "ok", "live": 1})
        out = statusline.line({"workspace": {"current_dir": str(self.root)}}, statusline.read_state())
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertIn("spec aredbc draft", out)

    def test_merge_hooks_keeps_operator_statusline(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "merge-hooks.py"), "--selftest"],
                            capture_output=True, text=True, timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_bad_stdin_still_prints(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "statusline.py")], input="{nope",
                            capture_output=True, text=True, env=dict(os.environ), timeout=30)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("gate", cp.stdout)

    def test_timing_smoke(self):
        payload = {"workspace": {"current_dir": str(self.root)}}
        self.run_line(payload)  # first render fills the cache
        times = []
        for _ in range(15):
            t = time.perf_counter()
            cp = self.run_line(payload)
            times.append(time.perf_counter() - t)
            self.assertEqual(cp.returncode, 0)
        # Order-of-magnitude guard only; AC-20 is measured by hand over 100 calls.
        self.assertLess(statistics.median(times), 1.5)


if __name__ == "__main__":
    unittest.main()
