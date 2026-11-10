#!/usr/bin/env python3
"""MEMORY.md sub-indexes (index_*.md linked from MEMORY.md) count as indexed.

MEMORY.md is split into secondary indexes to stay under the harness read limit.
Both readers of the index must follow that one hop: the recall hook's index pass
(brain-memory-recall.index_files) and brain_doctor's corpus-coverage check. A
directive listed only in a linked sub-index is covered; a directive listed in no
index stays uncovered.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain_doctor  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "brain_memory_recall", ROOT / "scripts" / "brain-memory-recall.py")
recall = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recall)

DIRECTIVE = "---\nname: x\ndescription: {d}\nmetadata:\n  type: feedback\n---\nbody\n"


def _memory(d: Path) -> Path:
    mem = d / "projects" / "-home-test" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text(
        "# Index\n- [Top rule](feedback_top.md)\n"
        "- [Sub index](index_extra.md)\n", encoding="utf-8")
    (mem / "index_extra.md").write_text(
        "---\nname: index_extra\n---\n- [Zebra quokka rule](feedback_sub.md)\n",
        encoding="utf-8")
    for name in ("feedback_top", "feedback_sub", "feedback_orphan"):
        (mem / f"{name}.md").write_text(DIRECTIVE.format(d=name), encoding="utf-8")
    return mem


class RecallFollowsSubIndex(unittest.TestCase):
    def test_index_files_includes_linked_subindex(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            names = [p.name for p in recall.index_files(mem / "MEMORY.md")]
            self.assertEqual(names, ["MEMORY.md", "index_extra.md"])

    def test_subindex_entry_is_scored(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            hits = recall.score_lines(mem / "MEMORY.md", {"zebra", "quokka"})
            self.assertIn("feedback_sub.md", [h[2] for h in hits])

    def test_unlinked_index_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            (mem / "index_unlinked.md").write_text(
                "- [Walrus narwhal](feedback_orphan.md)\n", encoding="utf-8")
            hits = recall.score_lines(mem / "MEMORY.md", {"walrus", "narwhal"})
            self.assertNotIn("feedback_orphan.md", [h[2] for h in hits])


    def test_prose_mention_does_not_link(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            (mem / "index_prose.md").write_text("- [Okapi tapir](feedback_orphan.md)\n", encoding="utf-8")
            with open(mem / "MEMORY.md", "a", encoding="utf-8") as fh:
                fh.write("Retired: see [old](index_prose.md) for history.\n")
            names = [p.name for p in recall.index_files(mem / "MEMORY.md")]
            self.assertNotIn("index_prose.md", names)

    def test_one_hop_only(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            (mem / "index_deep.md").write_text("- [Okapi tapir](feedback_orphan.md)\n", encoding="utf-8")
            with open(mem / "index_extra.md", "a", encoding="utf-8") as fh:
                fh.write("- [Deeper](index_deep.md)\n")
            names = [p.name for p in recall.index_files(mem / "MEMORY.md")]
            self.assertNotIn("index_deep.md", names)

    def test_duplicate_listing_does_not_take_two_slots(self):
        with tempfile.TemporaryDirectory() as d:
            mem = _memory(Path(d))
            with open(mem / "index_extra.md", "a", encoding="utf-8") as fh:
                fh.write("- [Zebra quokka again](feedback_top.md)\n")
            with open(mem / "MEMORY.md", "a", encoding="utf-8") as fh:
                fh.write("- [Zebra quokka top](feedback_top.md)\n")
            files = [h[2] for h in recall.score_lines(mem / "MEMORY.md", {"zebra", "quokka", "again", "top"})]
            self.assertEqual(len(files), len(set(files)))


class DoctorFollowsSubIndex(unittest.TestCase):
    def _run(self, d: Path):
        mem = _memory(d)
        (d / "skills").mkdir()
        with mock.patch.object(brain_doctor, "CLAUDE_DIR", d), \
                mock.patch.object(brain_doctor, "_brain_memory_dir", return_value=mem), \
                mock.patch.object(brain_doctor, "_claude_anchors", return_value=[]):
            return brain_doctor.check_corpus_coverage(False)

    def test_subindexed_directive_covered_orphan_not(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(Path(d))
        detail = res.message
        self.assertEqual(res.status, brain_doctor.FAIL)
        self.assertIn("memory directives (brain) 2/3", detail)
        self.assertIn("feedback_orphan", detail)
        self.assertNotIn("feedback_sub", detail.split("uncovered:")[-1])

    def test_unlinked_or_prose_linked_index_does_not_cover(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d)
            mem = _memory(dd)
            (mem / "index_prose.md").write_text("- [Okapi](feedback_orphan.md)\n", encoding="utf-8")
            with open(mem / "MEMORY.md", "a", encoding="utf-8") as fh:
                fh.write("Retired: see [old](index_prose.md).\n")
            (dd / "skills").mkdir()
            with mock.patch.object(brain_doctor, "CLAUDE_DIR", dd), \
                    mock.patch.object(brain_doctor, "_brain_memory_dir", return_value=mem), \
                    mock.patch.object(brain_doctor, "_claude_anchors", return_value=[]):
                res = brain_doctor.check_corpus_coverage(False)
        self.assertIn("memory directives (brain) 2/3", res.message)


if __name__ == "__main__":
    unittest.main()
