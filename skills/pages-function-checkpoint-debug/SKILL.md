---
name: pages-function-checkpoint-debug
description: When a Cloudflare Pages Function (or any Worker-style serverless handler) returns a generic 502/500 hiding the actual error, instrument the handler with a `?debug=1` query param + an in-memory checkpoint array that accumulates step markers and gets returned in the response body. Lets you bisect "which step crashed" in 1-2 deploy/retest cycles instead of guessing for hours.
when_to_use: Cloudflare Pages Functions, Cloudflare Workers, AWS Lambda, GCP Cloud Functions, Vercel/Netlify functions — any serverless handler whose runtime error stays inside the platform's edge layer and doesn't reach the caller. Especially when you can't easily attach a debugger (no `wrangler tail`, no Lambda log streaming, no Otel collector) and need a one-shot diagnostic.
triggers: ["pages function 502", "worker crash debug", "serverless 500 hidden error", "checkpoint debug pattern", "where is my function crashing"]
---

# Pages Function Checkpoint Debug

## When this fires

You hit a Pages Function / Worker. Auth path returns 401 cleanly. Post-auth
flow returns a generic 502 / 500 with body like `error code: 502` or
`Internal Server Error` — no stack trace, no useful info. `wrangler tail`
either isn't available (older Pages deploys) or your error isn't reaching it.

You need to know **which step is throwing**, fast.

## The pattern

Three pieces:

### 1. Global try/catch wrapper

Wrap your handler so any uncaught throw returns a JSON 500 with the message
+ a truncated stack — never a CF edge 502. Without this, the platform layer
intercepts the crash and serves its generic page.

```ts
export const POST: APIRoute = async (ctx) => {
  try {
    return await runHandler(ctx);
  } catch (err) {
    const msg = (err as Error)?.message ?? String(err);
    const stack = ((err as Error)?.stack ?? '').split('\n').slice(0, 5).join(' | ');
    return jsonResponse({ ok: false, error: 'uncaught', message: msg.slice(0, 400), stack: stack.slice(0, 600) }, 500, origin);
  }
};
async function runHandler(ctx) { /* your real code */ }
```

### 2. Checkpoint accumulator with `?debug=1`

Inside the handler, keep an array. Every meaningful step pushes a marker
with a timestamp + optional payload. When `?debug=1`, the marker payload
gets included; otherwise it's just step names (cheap).

```ts
const debug = new URL(request.url).searchParams.get('debug') === '1';
const checkpoints: Array<{ step: string; ts: number; data?: any }> = [];
const step = (name: string, extra: any = {}) => {
  checkpoints.push({ step: name, ts: Date.now(), data: debug ? extra : undefined });
  return null;  // never early-returns; diagnostics ride along
};

const debugWrap = (resp: Response): Response => {
  if (!debug) return resp;
  return resp.text().then((t) => {
    const parsed = (() => { try { return JSON.parse(t); } catch { return { rawBody: t }; } })();
    parsed.checkpoints = checkpoints;
    return new Response(JSON.stringify(parsed), { status: resp.status, headers: resp.headers });
  }) as unknown as Response;
};
```

### 3. Sprinkle steps + ONE early-return that you move forward

Add steps before AND after each suspect operation. Then add a single
`if (debug) return debugWrap(...)` that you progressively move FORWARD
through the handler each deploy until the response stops returning
("crash before this checkpoint, so the bug is between the last successful
checkpoint and this one").

```ts
step('1-locked', { bucket });
const channels = await getAllChannels(kv, userId);
step('2-got-channels', { count: channels.length });
// ... more steps ...
if (debug) return debugWrap(jsonResponse({ status: 'debug-stop-after-step-N', checkpoints }, 200, origin));
// suspicious code below — uncomment the return AT this checkpoint until you find the crash
```

## Workflow

1. Deploy handler with global try/catch + checkpoint array + ONE early-return after the first checkpoint.
2. Trigger handler with `?debug=1`. Confirm response returns the checkpoint(s) you've reached. If it returns 502, the crash is BEFORE step 1 — bug is in module load OR the try/catch itself.
3. Move the early-return FORWARD by 1-2 steps. Redeploy. Re-trigger.
4. Repeat step 3 until you cross a step where the response stops returning checkpoints. The crash is in the operation between the last successful checkpoint and the failed one.
5. Inspect that operation. Fix.
6. Remove `?debug=1` from any production trigger (workflow YAML, cron). Leave the checkpoint scaffold in code — it's harmless when `debug=0` (array isn't read).

## When NOT to use

- **`wrangler tail` works for you** — use that first. Tail gives you `console.log` output without redeploys. Checkpoints are for when tail is unavailable (Pages deploys without Functions metadata, restrictive IAM, etc.) or when you need the diag in the response body for a downstream caller.
- **You can repro locally** — `wrangler pages dev` or `wrangler dev` gives you stack traces in the terminal. No need for in-band diagnostics.
- **The error is reaching the caller** — if you already have a useful error message back from the function, this skill is overkill.

## Calibration

Real-case from 2026-05-19: hidden bug in a Pages Function caused 502s with no visibility.
- 1 deploy: added try/catch + 5 checkpoints. Got past step 5, crash after.
- 2nd deploy: added 5 more checkpoints inside the suspect block. Found crash between step 8a (load item) and 8b (mirror photos). Inspected step 8b — saw the photo URLs were full paths, not filenames. Bug found in ~30 min total.

Without this pattern: would have been a 2-3 hour wrangler tail wrestle or a multi-day mystery.

## Anti-patterns to refuse

- **Adding 50 checkpoints up front.** Adds noise. Start with 5; bisect.
- **Logging full request/response bodies into the checkpoint payload.** KV/log size limits matter; truncate to <200 chars per data field.
- **Leaving `?debug=1` in production triggers after the bug is fixed.** Costs cycles (the wrap reads the body to inject checkpoints).
- **Returning 200 from a real failure just because `debug=1` is on.** Keep the actual HTTP code (502/500) — only ADD the checkpoint payload.

## Related

- `dry-run-gate-pattern` — companion for safe testing of any side-effectful handler before going live
- `cache-bust-deploy-validation` — verify your deploy actually shipped before assuming the bug is in the code (sometimes the bug is "old code still served")
- `post-check-verification` — 3D Diligent: always verify behavior with evidence
