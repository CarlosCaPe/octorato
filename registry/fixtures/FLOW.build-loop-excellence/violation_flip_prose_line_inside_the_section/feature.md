# Feature: Toy

> **Status:** approved
> **Spec-Format:** ears-1

## Summary

A fixture spec for the push gate.

## Glossary

- **Exporter**: writes the report.

## Acceptance Criteria

- [ ] AC-01: THE Exporter SHALL write UTF-8.
- [ ] AC-02: WHEN a job finishes, THE Exporter SHALL write the report.

## Run evidence

- RUN-01 [AC-01, AC-02] `python3 app.py`: exit 0, the report is written in UTF-8
Ran on a clean checkout.

## Revision History

| Date | Change Summary |
|------|----------------|
| 2026-09-30 | Initial spec |
