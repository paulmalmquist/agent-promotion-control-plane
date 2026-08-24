# ADR 0001: Asynchronous Registry-Gated Promotion

- Status: Accepted
- Date: 2026-08-24

## Context

Registry publication is external work that can be slow, fail, time out, or succeed before the local response is recorded. Treating approval as immediate promotion would publish a false lifecycle fact.

## Decision

Promotion approval queues a leased registry operation and returns `202 Accepted`. The candidate remains stage `ELIGIBLE` with status `PROMOTION_PENDING`. Only confirmed registry success creates an immutable promoted version, stage `PROMOTED`, status `ACTIVE`, and event `PROMOTED`.

Terminal failure returns the candidate to `ELIGIBLE`, sets `BLOCKED`, and records a typed blocker. Explicit retries revalidate the immutable snapshot and reuse the operation's stable publication token. There is no force-promote path.

## Consequences

The interface exposes registry activation separately from readiness and eligibility. Clients observe an operation or subscribe to events. Registry adapters must implement publication-token idempotency, and tests must cover crash-after-external-success recovery.
