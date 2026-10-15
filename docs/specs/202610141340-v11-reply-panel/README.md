# v11, No Reply Unreviewed

Implemented on: 2026-10-15

v7 made an unverified send impossible; v11 moves that boundary to the operator. Every reply the main loop gives the operator carries a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer subagent, or the Stop gate sends the turn back. Spec `feature.md` (22 acceptance criteria, `Spec-Format: ears-1`), plan `plan.md`, builder's record `review.md`. The converge verdict that closes it is the CONVERGED result of converge pass 9, after the last code commit of #417.

Key files: `scripts/g__stop__reply-panel.py` (the reply gate), `scripts/receipt_ledger.py` (`panel_receipts_for`), `scripts/panel_digest.py` (the digest and the reviewer block), `registry/fixtures/FLOW.panel-before-reply/` (selftest fixtures), `docs/architecture/v11-reply-panel.md` (contract and residuals R-01 to R-13).

Notable decisions: the gate runs at Stop, after the text is shown, because no Claude Code hook can block a reply before display; the protocol (draft, panel, then emit the approved text) keeps an unreviewed reply off the screen and the gate makes skipping it cost a rewrite turn. The quorum scales with the source: 3 reviewers for a SELF reply, 1 for a sourced one. The cost of a panel per reply is read on 2026-10-21 from the receipt ledger.
