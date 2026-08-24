# ADR 0002: PostgreSQL Events and Leased Work

- Status: Accepted
- Date: 2026-08-24

## Context

Background tasks tied to an API process disappear during restart and cannot safely coordinate replicas. Audit events that can be edited by application code do not provide trustworthy lineage.

## Decision

Use PostgreSQL for durable work leases and ordered promotion events. Workers claim rows with `FOR UPDATE SKIP LOCKED`, heartbeat ownership, and bounded retries. State and events commit in the same transaction. Event-producing transactions take a transaction-scoped advisory lock before allocating sequence values, so visible sequence order matches commit order. A database trigger rejects event update and deletion; repository permissions omit those operations.

SSE streams stored sequences and replays from `Last-Event-ID`. PostgreSQL remains authoritative after gaps.

## Consequences

PostgreSQL is required. Operators can inspect and recover leases without reconstructing an in-memory queue. Serialized event insertion is an intentional audit-throughput tradeoff. Event retention and database capacity require explicit management.
