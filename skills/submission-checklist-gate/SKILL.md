---
name: submission-checklist-gate
description: Before sending a reply to a formal requirement (bank, government agency, any institution), build an explicit checklist of EVERYTHING the requesting message demands (attachments, signatures, formats) by re-reading the source file on disk, and audit the outbound package manifest against it. Trigger, any outbound submission answering an inbound requirement, especially when the inbound was summarized by a sub-agent.
metadata:
  type: lesson-learned
  status: active
---

# Submission Checklist Gate

## Symptom

A formal submission (signed form + annex) passes a strict content QA (every figure, reference and addressee verified, all PASS) and the institution still returns the procedure: a required attachment (official ID, both sides) was missing. The requesting email demanded it textually.

## Root cause

Two-layer loss:

1. The security pattern "bodies to disk + sub-agent summary" compressed the requirement list. The summary said "fill and sign the form" and silently dropped "attach a copy of your official ID, both sides". Summaries compress; requirements die in compression.
2. QA was scoped to document CONTENT (figures, fields, quotes, addressee). Nobody audited SUBMISSION COMPLETENESS: requirements-of-inbound vs attachment-manifest-of-outbound. Content QA PASS is not the same claim as "submission complete". They are two different audits.

## Fix

Before any outbound reply to a formal requirement:

1. Re-read the requesting message FROM DISK, never act on the sub-agent summary alone. Cheap extraction: `grep -in "adjunt\|anex\|requier\|identificaci\|copia\|firma\|formato\|vigente" <inbound.txt>` (adapt terms per language).
2. Write the explicit checklist: every document, attachment, signature and format the inbound demands.
3. Build the outbound manifest: `grep -in "Content-Disposition\|filename" <outbound.eml>` and reconcile 1:1 against the checklist. A missing item blocks the send. A zero-requirements inbound reconciling against a zero-attachments outbound is also a valid PASS; the point is the reconciliation, not the count.
4. Check precedents in the same case file: the same institution type usually asked the same thing before (identity validation is near-universal in financial and government flows). A prior fulfilled request is a free checklist.

## How to recognize next time

Any of these three means run the gate:

- You are about to send a reply that includes a filled or signed document to an institution.
- The inbound requirement reached you as a sub-agent summary, not as the raw file.
- Your QA prompt covers figures/quotes/fields but never asks "what must accompany this send".

## The three audits of a formal document

Content QA, completeness QA and context QA are different claims; the one you don't request explicitly does not happen:

| Audit | Question | Catches |
|---|---|---|
| Content | Is every figure/quote traceable to source? | Invented or drifted data |
| Completeness | Does the outbound manifest reconcile 1:1 with the inbound requirements? | Missing attachments, missing signatures |
| Context | Who is this document speaking to? | Addressee carried over from an adapted template |

## See also

- [[pre-merge-qa-gate]]: the QA gate pattern this extends from code merges to outbound submissions
- [[dry-run-gate-pattern]]: same fail-closed stance, applied to destructive operations
