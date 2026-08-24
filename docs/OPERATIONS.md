# Operations

## Local demo

Require Docker Compose 2.20 or newer:

```bash
docker compose version
docker compose up --build --wait --wait-timeout 180
docker compose ps
```

All four services (`db`, `api`, `worker`, and `web`) are long-lived and must be healthy. There is no one-shot init service. In demo mode, the API entrypoint obtains a PostgreSQL advisory lock, runs `alembic upgrade head`, seeds only when needed, and then starts Uvicorn. The worker waits for API health.

Run the exact startup command a second time:

```bash
docker compose up --build --wait --wait-timeout 180
```

This proves concurrent-safe migration and idempotent seed behavior. Older Compose versions can mishandle exited one-shot services, which is why initialization stays in the long-lived API process.

Windows operators can run the complete two-pass verification:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-compose.ps1
```

The script checks the Compose version, all four health states, both HTTP surfaces, at least eight seeded candidates, and six seeded schedules.

## Explicit integrated startup

Set `STARTUP_BOOTSTRAP=false` and `DEMO_MODE=false` in the deployment environment. Run migrations as a coordinated deployment step before replicas start. Never let multiple production web processes improvise schema ownership.

```bash
STARTUP_BOOTSTRAP=false DEMO_MODE=false docker compose run --rm api alembic upgrade head
# Use this only for an approved non-production environment:
STARTUP_BOOTSTRAP=false DEMO_MODE=true docker compose run --rm api python -m promotion_control_plane.cli.main seed
STARTUP_BOOTSTRAP=false DEMO_MODE=false docker compose up -d --wait --wait-timeout 180
```

The seed step is for approved non-production environments only.

## Demo reset and append-only history

`POST /api/v1/demo/reset` is available only with `DEMO_MODE=true`. It takes an exclusive PostgreSQL maintenance lock, rebuilds mutable demo fixtures in one transaction, and appends `DEMO_RESET_COMPLETED`. It does not update, delete, or truncate `promotion_events`, and it does not restart their sequence. Reset idempotency receipts remain replayable; receipts for rebuilt mutable resources expire so they cannot replay dangling identifiers. Worker claims take the matching shared lock during their claim transaction, so reset excludes new claims while rebuilding fixtures. It does not cancel a provider call that was already claimed and started.

Reset is not a production recovery primitive. Disable it in integrated deployments and restore production state from coordinated database and artifact backups.

## Database migration drift

Against a fresh PostgreSQL database, continuous integration and releases run:

```bash
alembic upgrade head
alembic current --check-heads
alembic check
```

The final command must print `No new upgrade operations detected.` Any generated upgrade operation means SQLAlchemy models and migrations diverged; update and review a migration rather than suppressing the check.

## Worker operations

The worker claims evaluation work, schedule-triggered work, and registry operations using `FOR UPDATE SKIP LOCKED`. Each claim records owner, lease expiry, heartbeat, attempt, and error category. A worker may reclaim expired work. Registry reclaims always reuse the stable publication token.

Monitor:

- queued age and attempts by work type;
- lease expiry and heartbeat lag;
- terminal registry failures and blockers;
- external schedule grace-window misses;
- event sequence growth and SSE reconnect rates.

Do not manually edit a registry operation into success. Use the typed registry retry endpoint so validation, idempotency, state, and audit events remain atomic.

## Schedule ownership

This control plane does not execute cron. The demo command, CLI/API, or named external scheduler triggers each job.

The Automation screen reports trigger owner, connection state, last observed run, and next expected trigger. “Next expected trigger” is not a local timer. A disconnected owner means the job will not run automatically. The manual autonomous cycle records actual schedule-run rows rather than repainting fixture timestamps.

## Health and diagnosis

- `/healthz`: liveness and process availability.
- `/api/v1/health`: versioned service availability metadata.
- `/docs`: OpenAPI explorer in trusted local environments.

Use correlation IDs from RFC 7807 errors and event timelines. For a promotion stuck pending, inspect its registry operation lease, attempts, publication token hash, and latest typed outcome. Do not create a promoted version manually.

## Backup and recovery

Back up PostgreSQL with transactionally consistent tools and retain artifact storage according to policy. Restore the database and matching artifacts together. After recovery, let expired leases be reclaimed. Publication tokens make registry reconciliation safe, but operators must verify external registry identities before clearing terminal blockers.

Test recovery for these crash points:

1. after a request receipt but before state commit;
2. after work claim but before provider call;
3. after external publication succeeds but before local commit;
4. after local state commit but before an integrated host projects the event externally.

The standalone worker does not deliver external events. `EventSink` and the delivery record are integration seams; a host that enables them owns retry, acknowledgement, and dead-letter operations.

## Line endings and Windows

`.gitattributes` forces text and shell scripts to line-feed endings while retaining carriage-return/line-feed endings only for `.cmd` and `.bat`. Release checks scan tracked `*.sh` files as raw bytes, run `bash -n`, and build every image from a Windows checkout. A carriage return in a shell shebang is a release blocker.

Run the byte-level Windows check with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-lf.ps1
```

Run `bash -n` in Git Bash, a Linux container, or continuous integration; Windows Subsystem for Linux must have a distribution installed.

## Dependency audit

Run `npm audit --audit-level=high`. High and critical advisories fail. Moderate and low findings remain visible in output. Never run `npm audit fix --force` in continuous integration and never hide an audit failure with `continue-on-error`.

The live OpenAI smoke and cold-read certification run only when `OPENAI_API_KEY` is present. Otherwise they skip or record `unavailable`; they do not manufacture a passing certification.
