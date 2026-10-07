#!/usr/bin/env python3
"""r__subagent-stop__qa-receipt.py: SubagentStop reflex that writes a QA receipt.

v7 phase 3 (docs/architecture/v7-nothing-ships-unverified.md). When a subagent
finishes and its final message carries the verdict protocol

    QA-VERDICT: PASS | FAIL | NEEDS-WORK
    QA-SCOPE: PR #260            (or a branch, a sha, a file set)
    QA-HEAD: <40-digit commit>   (the commit reviewed; a merge pins it)

or the v9 converge protocol (skills/sdd-converge)

    CONVERGE-VERDICT: CONVERGED | GAPS
    CONVERGE-SCOPE: docs/specs/<yyyymmddHHMM>-<feature-name>

or the panel protocol (FLOW.panel-before-send)

    PANEL-TO: <recipient>        (one per recipient)
    PANEL-MENTION: <who>         (one per person mentioned)
    PANEL-ATTACH: <sha256> <path> (one per attachment)
    PANEL-BODY-BEGIN / <exact text> / PANEL-BODY-END
    PANEL-VERDICT: PASS | NEEDS-WORK
    PANEL-SHA256: <64 hex>       (recomputed from the block; recorded only if equal)

this hook, running in the harness process, appends a receipt to the global
ledger with the agent id, type, the harness-written agent transcript path and
the harness `uuid` and `timestamp` of the transcript entry the report came
from. qa-merge-gate re-reads that exact entry before honoring the receipt, so
the line is a pointer, not the proof, and a resumed agent's later reply cannot
change what an earlier receipt says. The report is read from the transcript
first (a verdict delivered through SubagentHandback included); the payload
message is the fallback only when the transcript yields no verdict.

Why here and not in prose: "QA approved" typed by the main loop is
indistinguishable from an invention. The verdict has to come from a different
context and be recorded by something the main loop does not control.

Never blocks. Fail-open on every error.
Stdin: {"session_id", "agent_id", "agent_type", "agent_transcript_path",
        "last_assistant_message", ...}
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    text = str(data.get("last_assistant_message") or "")
    tp = str(data.get("agent_transcript_path") or "")
    try:
        import receipt_ledger
        # The transcript's final report comes first: it is the report every
        # consumer re-reads, and the payload message can differ from it (a
        # quoted protocol line in the last text block, while the delivered
        # handback says something else). The entry's harness uuid and timestamp
        # anchor the receipt, so a later reply of a resumed agent cannot change
        # what this receipt says. The payload is the fallback only when the
        # transcript yields no verdict.
        report, entry_ts, entry_uuid = (receipt_ledger.last_assistant_entry(tp)
                                        if tp else ("", "", ""))
        base = {
            "agent_id": data.get("agent_id") or "",
            "agent_type": data.get("agent_type") or "",
            "agent_transcript_path": tp,
            "session_id": data.get("session_id") or "",
        }
        for kind, parse in (("qa", receipt_ledger.parse_verdict),
                             ("converge", receipt_ledger.parse_converge),
                             ("panel", receipt_ledger.parse_panel)):
            source, anchor = report, {"entry_uuid": entry_uuid, "entry_ts": entry_ts}
            verdict, scope = parse(source)
            if not verdict:
                source, anchor = text, {}
                verdict, scope = parse(source)
            if not verdict or (kind == "panel" and not scope):
                continue
            if kind == "panel":
                # The digest is the panel's scope, and it must be RECOMPUTED
                # from the block the reviewer read (body, recipients,
                # attachment hashes): a stated digest alone binds to nothing.
                # An attachment still on disk must hash to what was reviewed.
                import panel_digest
                got = panel_digest.recompute_from_report(source)
                if not got or got["digest"] != scope:
                    continue
                stale = False
                for sha, path in got["attachments"]:
                    try:
                        if path and panel_digest.file_sha256(path) != sha:
                            stale = True
                    except panel_digest.PanelDigestError:
                        pass
                if stale:
                    continue
                record = dict(base, kind=kind, verdict=verdict, digest=scope,
                              recipients=got["recipients"],
                              attachments=[h for h, _ in got["attachments"]], **anchor)
                receipt_ledger.append_global(record)
                continue
            record = dict(base, kind=kind, verdict=verdict, scope=scope, **anchor)
            if kind == "qa":
                record["head"] = receipt_ledger.parse_qa_head(source)
            receipt_ledger.append_global(record)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
