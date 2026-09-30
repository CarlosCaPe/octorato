# Feature: Fixture

> **Status:** draft
> **Spec-Format:** ears-1

## Summary

A fixture spec.

## Glossary

- **Exporter**: writes the report.
- **Scheduler**: runs jobs.

## Acceptance Criteria

- [ ] AC-01: THE Exporter SHALL write UTF-8.
- [ ] AC-02: The Exporter must write the report when a job finishes.
- [ ] AC-03: WHILE a job runs, THE Scheduler SHALL refuse a second start.
- [ ] AC-04: WHERE the retry option is enabled, THE Scheduler SHALL retry once.
- [ ] AC-05: IF the disk is full, THEN THE Exporter SHALL NOT truncate the previous report.

## Revision History

| Date | Change Summary |
|------|----------------|
| 2026-09-30 | Initial spec |
