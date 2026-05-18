---
name: floci-local-aws
description: Run AWS services locally — S3, DynamoDB, SQS, Lambda, ECS, ECR, OpenSearch, MSK/Kafka, Athena and ~45 more — using Floci, an MIT-licensed AWS emulator built with Quarkus Native. Use when the task involves local AWS development, integration testing, or CI without hitting real AWS, or when migrating off LocalStack Community Edition (sunset March 2026, now requires auth token). 24ms cold start, 13 MiB RAM at idle.
---

# Floci — Local AWS Emulator

Open-source, MIT-licensed drop-in replacement for LocalStack Community Edition. Use when an AWS-touching engagement needs local emulation for development, integration tests, or CI without spinning real AWS resources or paying for LocalStack Pro.

## When to use

- Integration tests against S3 / DynamoDB / SQS / SNS / Lambda / API Gateway / Step Functions without hitting real AWS
- Local dev loop for any AWS-backed service — avoid burning credits, work offline
- CI pipelines that need AWS endpoints reproducibly (Floci boots in 24ms in a container)
- Migrating off LocalStack Community Edition (sunset March 2026 — requires auth token, frozen security updates)
- Multi-account isolation in tests without provisioning sub-accounts in a real AWS org

## Source of truth

- Repository: `github.com/floci-io/floci` (verify before sharing — was MIT / 12k+ stars / Java + Quarkus Native at time of writing)
- Look in the repo README for: `Architecture Overview`, `Real Docker Integration`, `Supported Services`, `Persistence & Storage Modes`, `Multi-Account Isolation`, `SDK Integration`, `Testcontainers`, `Migrating from LocalStack`

## Quick start

```bash
# Docker
docker run --rm -p 4566:4566 floci/floci

# docker-compose
services:
  floci:
    image: floci/floci:latest
    ports: ["4566:4566"]
```

Point AWS SDKs at `http://localhost:4566` (same endpoint convention as LocalStack — most existing client config keeps working unchanged). Verify the exact env var names in the current README; common ones:

- `AWS_ENDPOINT_URL=http://localhost:4566`
- Region/credentials: any dummy value (Floci ignores real auth)

## What ~45 services usually covers

S3, DynamoDB, SQS, SNS, Lambda, API Gateway, IAM, STS, KMS, Secrets Manager, SSM Parameter Store, CloudWatch (Logs + Metrics), EventBridge, Step Functions, ECS (real Docker containers), ECR (real OCI registry — `docker push`/`pull` works), OpenSearch (real cluster), MSK / Kafka (via Redpanda), CodeBuild (real Docker builds), Athena, Glue basics, RDS proxy.

The canonical, version-specific list lives in `floci-io/floci` README under "Supported Services" — check there before promising a specific service to a client.

## Why it matters for the brain

| Property | Floci | LocalStack Community (post-2026) |
|---|---|---|
| Auth token required | No | Yes |
| Security updates | Active | Frozen |
| License | MIT | (Community edition discontinued) |
| Cold start | 24 ms | seconds |
| RAM at idle | 13 MiB | hundreds of MiB |
| Per-service fidelity | Real Docker / Redpanda / OpenSearch | Mostly mocks |

For consulting engagements that mention "we test locally with LocalStack" — Floci is the no-strings-attached upgrade path.

## Patterns to apply

### Integration tests with Testcontainers

Floci has a Testcontainers module — use it instead of standing up Floci manually in test fixtures. Spawned containers get torn down per-test or per-suite, which keeps CI deterministic.

### Multi-account isolation

When a test needs to simulate cross-account IAM (assume-role across two accounts), Floci's multi-account mode lets you do that without provisioning real sub-accounts. Check `Multi-Account Isolation` doc in the repo.

### Endpoint compatibility

The SDK's region/endpoint resolver may need a tweak if your code uses path-style vs virtual-host S3 addressing. Default: path-style works. If using SigV4 signing strictly, set `force_path_style=True` (Python) or equivalent.

## Limits to call out to a client

- New / preview AWS services may not be covered — check the supported list before promising
- IAM policy evaluation is "real enough" for most testing but doesn't replicate every edge case of the AWS authorizer
- Floci is not a pricing simulator — use AWS Pricing Calculator / Cost Explorer for cost modeling
- Verify license + service list at engagement start; open-source projects can pivot

## Related brain assets

- `querymaster` — when Floci's local stack includes a real Postgres-compatible engine (Aurora simulation), query it directly via QueryMaster instead of going through the AWS SDK
- Backend Architect agent, DevOps Automator agent — for arm-level integration patterns
- Sister pattern: `tabularis-db-client` — analogous "OSS replacement for commercial tool" recommendation, but for DB clients
