# Plan: Diagram-Always Replies

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/dim/8c8dcf2e3741`; the live `~/.claude` copy is never edited (arming surface). Supersedes the trigger of `docs/specs/202611151120-diagram-first/`.

## Tasks

- [ ] T01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08] scripts/g__stop__diagram-first.py: drop the word floor and the shape requirement, add the Prose_Cap and Long_Paragraph checks, the Input_Only lead cap, the wider diagram glyph set, and the new reason text.
- [ ] T02 [AC-09] registry/fixtures/COMMS.diagram-first/: rename the flipped benign fixtures to `violation_flipped_*`, add the new benign and violation cases.
- [ ] T03 [AC-01, AC-02, AC-03, AC-04, AC-07, AC-08, AC-09] scripts/tests/test_diagram_first.py: rewrite the matcher and wiring tests for the new contract.
- [ ] T04 [AC-10, AC-11, AC-14] CLAUDE.md, skills/human-cadence/SKILL.md: the every-reply rule, the HTML fallback, the Detail_Offer shape, the rule-8 exception.
- [ ] T05 [AC-12, AC-13] scripts/impact-radius-hook.py, scripts/grafo-ledger-check.py, scripts/grafo-turn-reset.py: advisories to the model only.
- [ ] T06 [AC-11] registry/rules.yaml, connectome/lineage.yaml: the COMMS.diagram-first title and the lineage node.
- [ ] T07 [AC-10] registry/fixtures/COMMS.no-menu-question/benign_detail_offer.json, registry/fixtures/COMMS.no-menu-question/benign_detail_offer_transcript.jsonl: pin the verbless Detail_Offer as a benign Menu_Gate case.

## Convergence 1

- [ ] T08 [AC-16, AC-17] scripts/grafo-ledger-check.py, scripts/grafo-turn-reset.py, scripts/tests/test_graph_advisory_relay.py: key the advisory by the payload `session_id`, drop it with no real session, catch decode errors and unlink in `finally`.
- [ ] T09 [AC-07, AC-15] scripts/g__stop__diagram-first.py, scripts/tests/test_diagram_first.py, registry/fixtures/COMMS.diagram-first/benign_2d_lead.json, registry/fixtures/COMMS.diagram-first/benign_plaintext_fence.json, registry/fixtures/COMMS.diagram-first/violation_2d_lead_no_diagram.json: skip a leading fenced 2D summary; accept `plaintext` and `text-plain` fences.
- [ ] T10 [AC-14] skills/human-cadence/SKILL.md, skills/4d-paradigm-protocol/SKILL.md: 2D placement, reviewed bodies keep the bullet shape, motion lives in the HTML artifact, staged diagrams in chat.
