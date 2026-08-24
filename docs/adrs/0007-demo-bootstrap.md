# ADR 0007: Advisory-Locked Demo Bootstrap

- Status: Accepted
- Date: 2026-08-24

## Context

The demo must start with one Compose command and initialize an empty database. A one-shot init container may make `docker compose up --wait` report failure after it exits cleanly on older Compose versions.

## Decision

Compose contains only long-lived `db`, `api`, `worker`, and `web` services. In demo mode, the API entrypoint obtains a PostgreSQL advisory lock, runs Alembic upgrade and idempotent seed-if-empty, then starts Uvicorn. The worker waits for API health. Integrated mode disables bootstrap and uses explicit migration and seed commands.

## Consequences

The exact startup command works from an empty database and can be repeated to prove idempotency. Production deployment tooling must coordinate migrations explicitly.
