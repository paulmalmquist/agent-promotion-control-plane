# Integration Guide

## Choose replacement adapters

Standalone demo adapters are local and trusted. An integrated deployment normally replaces candidate and evaluation sources, the promotion registry, artifact storage, event sink, schedule source, authentication, and tenancy. The Python service exports these protocols:

```text
CandidateSource
CandidateDetector
EvaluationSource
EvaluatorProvider
PromotionRegistry
ScheduleSource
ArtifactStore
EventSink
```

Construct a router with injected use cases via `create_router()` or construct the complete FastAPI application with `create_app()`. Keep the domain package independent of FastAPI, SQLAlchemy, model providers, schedulers, and filesystems.

## API contract

The checked-in OpenAPI document is generated from the application factory. Generated TypeScript types are derived from that artifact and committed. Continuous integration regenerates both and rejects drift.

All mutation requests must include `Idempotency-Key`. Candidate mutations also send `expected_candidate_revision`. Treat `409` as a prompt to refresh and re-evaluate intent, not as a request to overwrite. Errors use RFC 7807 with stable `code` and `correlation_id` extensions.

Subscribe to the versioned event endpoint with `Last-Event-ID`. Store the last applied numeric sequence and reduce events idempotently. A disconnect is normal; replay from PostgreSQL closes gaps.

## Schedule invocation

This control plane does not execute cron. GitHub Actions, Cloud Scheduler, Kubernetes CronJobs, Temporal, Celery, Paul OS, a CLI operator, or another named owner calls the idempotent schedule-trigger endpoint or CLI.

Every schedule definition includes `trigger_owner`, `trigger_mode`, `owner_reference`, `connection_state`, `last_observed_run_at`, `next_expected_trigger_at`, and grace-window metadata. “Next expected trigger” is the owner's expected call time. A disconnected definition will not run automatically.

Example pattern:

```bash
job_id="<scheduled-job-uuid>"
curl --fail-with-body \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: github-actions-nightly-2026-08-24" \
  -d '{"actor":"github-actions","trigger_source":"GITHUB_ACTIONS","payload":{"occurrence":"2026-08-24"}}' \
  "http://localhost:8000/api/v1/schedules/${job_id}/trigger"
```

Resolve the job UUID from `GET /api/v1/schedules` or use its stable `job_key` with the CLI. Use a stable key derived from the external scheduler's occurrence identity. Retrying the same occurrence is safe; changing its body under the same key returns `409`.

Equivalent CLI pattern:

```bash
docker compose exec -T api python -m promotion_control_plane.cli.main trigger-schedule nightly-candidate-discovery \
  --idempotency-key github-actions-nightly-2026-08-24 \
  --actor github-actions
```

An installed deployment may invoke the equivalent `promotion-control-plane trigger-schedule` entry point.

## Registry contract

`PromotionRegistry.publish` receives a stable publication token and immutable publication snapshot. The adapter must return an already-created external version when called again with the same token. Do not infer success from a timeout. A worker reclaim calls again with the same token, then records the returned identity atomically.

Map permanent external validation or authorization failures to typed terminal failures. Map bounded timeouts and transient service errors to retriable failures. Never mark a candidate promoted before a confirmed, idempotent registry response.

## Embed the React package

`packages/promotion-ui` is browser-neutral. Inject:

- initial serializable view models;
- a `PromotionDataSource` for queries and mutations;
- a `PromotionEventEnvelope` subscription;
- navigation and route helpers;
- a lifecycle-decision callback;
- host semantic tokens.

The package contains no `next/*`, Server Component, Next routing, or proxy import. Its styles are scoped under `[data-promotion-control-plane]`. Hosts should lazy-load `PromotionShell`, preserve keyboard and reduced-motion behavior, and map semantic tokens rather than override component selectors.

Default categories are purple `#9578ff` for governed decisions and teal `#2f9d82` for comparison and progress. Amber denotes degraded, incomplete, or non-safety blocking conditions. Red is reserved for explicit safety or authorization stops. Nominal success is quiet and neutral.

In a host with a governed mutation surface, implement the lifecycle callback there. The package must not silently call standalone mutation routes when an injected callback exists.

## Production checklist

1. Disable demo startup bootstrap and deterministic seed.
2. Run Alembic explicitly under deployment coordination.
3. Configure authentication, tenant isolation, and least-privilege database roles.
4. Replace local registry and artifact adapters.
5. Register each external trigger owner and monitor missed grace windows.
6. Implement the optional event sink and its host-owned retry and dead-letter policy.
7. Test stable publication-token recovery against the real registry.
8. Apply runtime authority envelopes in the execution system.
9. Review governed critical copy and record its digest.
10. Run the complete security and disaster-recovery checklist.
