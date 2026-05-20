---
name: arm-synthetics
description: Per-arm health check templates. Each arm defines a synthetics.yaml with endpoints to probe + expected responses + cron schedule. The skill ships the template + GH Action runner. Failures open issues IN THE ARM REPO (not the brain) to preserve octopus arm isolation. Use when onboarding a new arm or when an arm's health monitoring needs a scheduled probe.
---

# Brain Synthetics (observability surface 7)

This surface runs **per-arm health monitoring**: each arm gets its own synthetics config, its own GH Action runner, and alerts that stay in the arm's own repo. Arm isolation is preserved — the brain never sees one arm's failures bleed into another arm's monitoring surface.

## When to use

- Onboarding a new arm: drop the template files, edit `synthetics.yaml`, commit, scheduled probes start working
- Existing arm needs health monitoring beyond what's already there (e.g. `sitemap-test` for the public site already exists for one arm — synthetics generalises it)
- Operator says "monitor X for me daily" / "sondea Y cada hora" / "health check para Z"

## Files this skill installs

Two templates live under `~/.claude/templates/arm-synthetics/`:

1. **`synthetics.yaml.template`** — copied into the arm at `<arm>/synthetics.yaml`. Operator edits the endpoints + expectations.
2. **`synthetics.yml.workflow-template`** — copied into the arm at `<arm>/.github/workflows/arm-synthetics.yml`. Reads the yaml, runs the probes, opens an issue ON THE ARM REPO on failure.

A helper script `~/.claude/scripts/arm-synthetics-runner.py` does the actual probing — sits in the brain so all arms share the same runner code without duplication.

## Workflow when installing into a new arm

1. From inside `<arm>/` repo, run:
   ```
   cp ~/.claude/templates/arm-synthetics/synthetics.yaml.template ./synthetics.yaml
   mkdir -p .github/workflows
   cp ~/.claude/templates/arm-synthetics/synthetics.yml.workflow-template .github/workflows/arm-synthetics.yml
   ```
2. Edit `synthetics.yaml`: add endpoints, expected status codes, optional regex/JSON path on response.
3. Commit + push to the arm repo. The GH Action picks up the cron schedule.

## synthetics.yaml schema

```yaml
arm: my-arm-slug           # arm slug; sourced into issue titles
schedule: "0 */6 * * *"    # cron (default every 6h)
probes:
  - name: site-home
    method: GET
    url: https://www.dataqbs.com/
    expect_status: 200
    expect_regex: '<title>dataqbs'   # optional
    timeout_seconds: 30
  - name: api-chat-health
    method: GET
    url: https://www.dataqbs.com/api/health
    expect_status: 200
    expect_json_path: '$.ok'        # optional, value must be truthy
    expect_json_value: true         # optional
    timeout_seconds: 15
```

## Alerting (arm isolation rule)

- Failed probe → opens an issue **on the arm's own repo**, labelled `arm-synthetic-failure`.
- The brain digest (Port 5) aggregates **only counts** across arms (e.g. "3 synthetics failing across all arms today") — never the arm name, never the failed endpoint URL.
- The brain runner script never writes the arm's URL or response into a brain-side log.

## AC coverage

- AC-1: template `synthetics.yaml.template` (this file references it)
- AC-2: per-arm GH Action template `synthetics.yml.workflow-template`
- AC-3: failures open issue IN ARM REPO — `gh issue create --repo $(git config remote.origin.url ...)` resolves the current arm's repo
- AC-4: brain digest count-only aggregation across `~/.claude/synthetics-state/` count file (one per arm, gitignored)

## Cross-references

- Prior art: per-arm `sitemap-test`-style workflows — covered the use case before this generalised it. New arm-synthetics CAN coexist with arm-specific probes; the latter stay as the arm's specialised checks.

## Non-goals (per spec)

- Cross-arm correlation (octopus isolation forbids)
- Browser-screenshot diffing (use a separate tool like `agent-browser` for visual regression)
- Cost / latency SLOs on the probes themselves (use Port 3 SLOs over the arm's main service)
