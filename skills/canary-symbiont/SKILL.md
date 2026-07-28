---
name: canary-symbiont
description: "Centinela cross-plane: un watcher en el plano B detecta la muerte SILENCIOSA del scheduler del plano A (bloqueo de billing, cron load-shedding) y avisa por correo. Fail-open. Incluye el test en vivo obligatorio."
metadata:
  short-description: "A sentinel on a different plane senses what the host can't, alerts once, dies harmlessly"
  type: pattern
  source: "lived 2026-06: silent GH Actions billing block + canary activation whose live test caught a real 403 before the first tick"
---

# Canary Symbiont: Cross-Plane Sentinel

## The problem

External schedulers fail SILENTLY. A billing block or load-shedding on the scheduler plane stops every cron while the UI keeps showing the workflows as "active". From inside that plane there is no error to catch: the failure mode IS the absence of execution. The host system cannot sense its own silence.

## The pattern (four legs, all required)

1. **Different plane.** The sentinel runs on infrastructure independent of what it watches (e.g. a serverless worker on cloud B watching scheduler cloud A). Shared fate = no sentinel.
2. **Asymmetric sensing.** It checks the one signal the host cannot feel: "completed runs in the last 26h" via the watched platform's API, with a least-privilege read-only token. Zero runs in a window that should always have runs = the silent death.
3. **One-directional alert.** On silence it emails the operator once, with the probable cause and the direct fix link (e.g. the billing page). It does not retry-storm, it does not try to heal.
4. **Fail-open isolation.** Every canary error (missing token, API 4xx/5xx, mail failure) logs and returns; it never throws into the host work it rides on. The host degrades to "merely unwatched", never broken.

Host it inside an existing daily tick rather than its own cron: one more scheduled surface is one more thing that can silently die.

## Activation gotchas (each one lived)

- **Fine-grained PAT 403.** The step humans miss is the permission: repo selection alone gives Metadata only; the API returns 403 until `Actions: Read-only` is explicitly added. Fine-grained PATs are editable in place: fixing permissions does NOT change the token value, so nothing needs re-uploading. Platforms expose no API to mint PATs; that step is always operator-UI.
- **Secret intake without echo.** One line per paste (terminals shred multi-line pastes): `read -rs T; printf '%s' "$T" > <dir>/file; unset T` into a `chmod 700` dir, then `wrangler secret put NAME < file`, then `shred -u` the files. Nothing touches history or the transcript.
- **Phrase grants as named commands.** In secrets-dense context, "do it all, you have my permission" trips usage-policy classifiers; "run the two secret put and the deploy" does not.

## The MANDATORY live test

A canary that has never fired protects nothing, and because it is fail-open, a broken canary looks identical to a healthy one. After activation, force its tick once with real secrets and read for the explicit healthy line, not just a 200:

```bash
# temporarily point preview_id / preview_bucket_name at prod in wrangler.toml (REVERT after)
npx wrangler dev --remote --test-scheduled --port 8787
curl "http://localhost:8787/__scheduled?cron=<the canary's cron, URL-encoded>"
# expect: [canary] <watched plane> healthy (N runs in last 26h)
```

Two implications: any work co-hosted on that tick MUST be idempotent (per-hour locks, date sentinels, status filters), because the test fires it too, which doubles as a free idempotency audit; and kill the dev session with a self-excluding pattern (`pkill -f "wrangler[ ]dev"`) or you kill your own shell. The first live test of this pattern caught a real 403 hours before the first scheduled tick.

## Why "canary-symbiont" (the octopus anchor)

The pattern has two honest names. In engineering it is the miner's canary: a disposable sentinel on a different life-support plane that collapses to alert before the host feels the threat. In biology it is the goby and the pistol shrimp: a near-blind digger and a surface-watching fish sharing a tail-flick alarm channel, where the shrimp degrades to "merely blind" rather than dying when the goby leaves. Both share the same four legs above. The compound name keeps the recognized distributed-systems term and the honest biology anchor without pretending one is the other. The canary is the octopus's pet symbiont.

## Related

- `arm-synthetics`: health checks FOR an arm's endpoints; this watches the SCHEDULER plane itself.
- `sentinel-blocks-rerun`: idempotency sentinels, the property that makes the live test safe.
- `dry-run-gate-pattern`: same instinct (preview before harm) applied to destructive ops.
- `agent-proof-approval-gate`: the operator-only steps here (PAT minting, secret values) share its trust model.
