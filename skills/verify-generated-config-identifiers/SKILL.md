---
name: verify-generated-config-identifiers
description: "Schema-valid generated config is not semantically correct: check every external identifier (metric, field, column, env key) against the vendor docs before sending. Triggers when generating dashboards, monitors, IaC or pipelines."
metadata:
  type: reference
---

# Verify generated config identifiers (schema-valid is not correct)

A generated artifact that **parses** or **imports** without error is not validated. The validator that runs on import checks shape, not whether the names you wrote exist in the target system. A dashboard with a typo'd metric imports with HTTP 200 and then shows an empty panel forever. The failure is silent: no error, no exception, just a tile reading "No Data" that everyone assumes is a transient gap.

This is the single most common failure mode of LLM-generated config, because the model produces plausible-looking identifiers from pattern, not from the live schema.

## The two reflexes

### 1. Verify every external identifier against authoritative vendor docs

Before shipping any artifact that references another system's identifiers, confirm each name against first-party docs, not memory:

- Metric names (Datadog `postgresql.*`, `airflow.*`, cloud-provider namespaces)
- API fields, response keys, query-language columns (SQL, KQL, PromQL, JMESPath)
- Env var names, secret keys, tag keys
- Enum/constant values

Use the authoritative source: the vendor's metrics reference page, the integration's metadata, the API schema. For Microsoft/Azure, the Microsoft Learn MCP returns the exact `Name in REST API`. Never ship a guessed name. A guessed name is the same class of bug whether a human or a model wrote it.

Watch for near-miss traps:
- A name that *sounds* right but does not exist (`postgresql.queries.exec_time` when the real metric is `postgresql.queries.duration.max`).
- An aggregation invalid for the metric type (`p95:` on a gauge, `.as_count()` on a non-count metric).
- A metric the integration simply does not emit (`airflow.task.retries`) that renders permanent No Data.
- Namespace drift (`azure.dbforpostgresql.*` vs `azure.dbforpostgresql_flexibleservers.*`).
- A shorthand whose meaning you assumed wrong (`dt` meaning DATE, not timestamp).

### 2. Run an adversarial expert panel over non-trivial artifacts

One review pass misses cross-domain errors because no single reviewer holds every domain. Fan out one lens per domain, each prompted to find real, specific issues with a concrete fix, then synthesize:

- **Schema lens** — will it import? Widget shapes, formula-to-query references, template-variable usage, required fields.
- **One lens per integration** — do these exact metric/field names and tags exist in *that* integration's namespace?
- **Thresholds / SRE lens** — do the dashboard thresholds match the alert monitors and the documented source of truth? Env coverage right? Missing high-value signals?

The synthesizer dedups, ranks by severity, drops anything speculative or refuted, and decides import-readiness only on zero blockers. Apply blocker/high fixes; keep dashboard, alert monitor, and the source-of-truth doc consistent (a fix to one usually implies a fix to the other two). For artifacts that reference unconfirmed identifiers, verify (reflex 1) rather than shipping the guess: re-introducing an unverified name is the exact bug the panel just removed.

See `peripheral-parallel-dispatch` and `bug-hunter` for the fan-out mechanics; this skill is about *what* the panel must check on generated config specifically.

## Why it matters

The cost asymmetry is large. Verifying a name costs one doc lookup. Shipping a wrong name costs a dashboard that looks done, passes its demo, and silently protects nothing until an incident reveals the panel was empty the whole time. "Imports cleanly" is the trap, not the proof.

Related: [[verify-root-cause-before-claiming]] (verify against the real system, not the symptom), [[harmonization-over-accretion]].
