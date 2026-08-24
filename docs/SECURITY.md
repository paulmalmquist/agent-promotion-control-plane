# Security

## Intended deployment

The included standalone demo is trusted and local. It has zero required credentials and is not an internet-facing production control plane. Production deployments must add authentication, authorization, tenant isolation, network policy, secret management, rate limiting, durable artifact storage, external scheduler ownership, and runtime authority envelopes through replacement adapters.

Do not put sensitive production evidence into demo fixtures or screenshots. Do not expose FastAPI documentation publicly without an explicit decision.

## Promotion safety

- A hard-gate failure or remaining hard gate blocks promotion regardless of weighted score.
- Promotion is asynchronous and no `PROMOTED` state or event exists before confirmed registry success.
- Lifecycle approvals bind immutable policy and evidence snapshots and cannot be revoked after queuing.
- Candidate revisions reject stale reviewer writes.
- Every mutation has an idempotency receipt and request fingerprint.
- Registry retries use a stable publication token for external deduplication.
- PostgreSQL rejects event update and deletion with a database trigger.
- No force-promote or bypass route exists.

Promotion changes which tested version new production runs select. It does not authorize a run or grant tool access. Execution remains governed by downstream authority envelopes.

## Provider data handling

Deterministic providers are the default. The optional OpenAI rubric evaluator runs server-side, requests strict structured output, sets `store=False`, records usage metadata, and stores only sanitized raw-response artifacts. Its default model is controlled by `OPENAI_EVAL_MODEL=gpt-5-mini`. Define explicit redaction and retention rules before sending production evidence to any external provider.

An artificial-intelligence-assisted detector may rank already persisted deterministic signals. It cannot invent discovery evidence.

## Supply chain

Continuous integration:

- installs from committed npm and uv lockfiles;
- pins Gitleaks to an immutable action commit;
- runs `npm audit --audit-level=high` without forced remediation or ignored failures;
- rejects SQLAlchemy/Alembic drift;
- rejects OpenAPI and generated-type drift;
- validates line-feed shell files and builds Docker images;
- runs backend, component, production-SSE, Compose, and Playwright tests.

Review dependency lockfile changes and container base-image digests. Use least-privilege repository and database credentials. Database application roles should not own migration objects; event trigger protections should be installed by a migration owner and inaccessible to the application role.

## Next.js August 2026 notice

Before each release, check the official [Next.js August 2026 security notice](https://nextjs.org/blog/upcoming-nextjs-security-release-august-2026) and the stable release channel. Use the patched stable Next.js 16 release as soon as it is available. If the announced patch is not yet available, retain the newest compatible stable release, keep the service private and local, document the pending upgrade here, and do not represent it as production-ready.

Release record fields:

```text
Checked at: 2026-08-24 14:24:39 -04:00
Installed Next.js: 16.3.2 (committed npm lockfile)
Announced patched stable available: No. The notice schedules 16.3.3 for 2026-08-26; npm latest is 16.3.2.
Announced severity: One critical vulnerability; full impact details remain embargoed until release.
Disposition: Keep the reference implementation private/local and upgrade before any production use.
```

## Reporting

This repository is private. Report suspected vulnerabilities to the repository owner through a private GitHub security advisory or another agreed private channel. Do not open a public issue containing exploit details, secrets, customer evidence, or registry tokens.

No license is included. That is a governance choice, not a security grant.
