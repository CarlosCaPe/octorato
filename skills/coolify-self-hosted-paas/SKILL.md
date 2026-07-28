---
name: coolify-self-hosted-paas
description: "Alternativa autoalojada a Vercel, Heroku y Render: despliega apps, bases y servicios en tu propio servidor con git-push, SSL automatico y sin costo por asiento. Apache 2.0."
---

# Coolify — Self-Hosted PaaS

The OSS answer to "Vercel/Heroku/Netlify, but on your server." Single Docker-based install, web UI, git-push deploys, automatic SSL via Let's Encrypt, preview environments per PR. Apache 2.0.

## When to use

- Client wants Vercel/Heroku-like ergonomics but owns the infrastructure (cost, sovereignty, compliance)
- Many small services to manage centrally without per-service hosting bills
- Self-hosting on a single VPS or bare metal — Coolify orchestrates Docker for you
- The client's existing managed PaaS pricing is now exceeding the cost of a VPS + Coolify combo
- Air-gapped or on-prem deployments where SaaS PaaS isn't an option

## When NOT to use

- Client genuinely needs hyperscale edge / global CDN — Vercel/Cloudflare/Netlify still win
- Team doesn't want to operate the underlying infrastructure (Coolify is *less* managed than Vercel)
- Compliance regime that requires a SOC 2 / ISO 27001 certified provider (Coolify is OSS — *you* are the provider)

## Source of truth

- Repository: `github.com/coollabsio/coolify`
- License: Apache 2.0
- Install: single Docker-based bootstrap on a VPS (Hetzner / DigitalOcean / Linode / etc.)
- Web UI for project, server, application, and database management
- Supports: Docker, docker-compose, Dockerfile, Buildpacks, plain git repos

## Quick start (rough — verify against current README)

```bash
# On a fresh Ubuntu VPS:
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
# Then access the web UI at https://<your-vps>:8000 and add servers, projects, applications
```

After install: connect a git repo, choose build method, hit deploy. SSL is provisioned automatically.

## Coolify vs commercial PaaS — when each wins

| Need | Recommended |
|---|---|
| Cost-sensitive client, willing to operate VPS | **Coolify** |
| Hyperscale edge / global CDN out of the box | Vercel / Cloudflare Pages |
| Easiest possible "git push" with zero ops | Vercel / Netlify |
| Compliance regime requires SOC 2-certified provider | Commercial PaaS |
| Self-hosting required (data sovereignty, regulated industry) | **Coolify** |
| Single pane of glass for many small services on one VPS | **Coolify** |
| Need built-in preview deployments per PR | Either (Coolify has them, Vercel polished) |

## Recommendation pattern (proposals)

> "For clients spending more than ~$200/month on managed PaaS for non-edge workloads, Coolify on a $20-60/month VPS often pays for itself in the first quarter and gives the team full control of their deployment plane. It's the right call when data sovereignty, predictable cost, or freedom from PaaS lock-in matter. It's the wrong call when global edge performance or zero-ops is the primary requirement."

## Limits to disclose to a client

- **You become the operator** — uptime is your responsibility, not Vercel's
- No global edge CDN out of the box (single-region by default)
- Smaller ecosystem than Vercel/Netlify — fewer one-click integrations
- Apache 2.0 is permissive but the operator must maintain the install

## Related brain assets

- `cloudflare-deploy` — when global edge matters, prefer this over Coolify
- `vercel-deploy`, `netlify-deploy`, `render-deploy` — sister skills for the commercial alternatives
- Sister pattern: `floci-local-aws`, `tabularis-db-client` — "OSS replaces commercial tool" recommendations
- DevOps Automator agent — for hardening a Coolify install for client use (backups, monitoring, ops runbook)
