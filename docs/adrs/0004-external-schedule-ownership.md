# ADR 0004: External Schedule Ownership

- Status: Accepted
- Date: 2026-08-24

## Context

Seeded cron-like definitions imply automation that does not exist if the service has no scheduler. A hidden resident scheduler would also duplicate production orchestration systems.

## Decision

The control plane observes schedules but does not own time. Each job names its trigger owner, mode, reference, connection state, last observed run, next expected trigger, and grace window. External schedulers, the API/CLI, or the demo cycle call an idempotent trigger command.

## Consequences

The Automation screen states that the control plane does not execute cron. Disconnected jobs plainly say they will not run automatically. Operators monitor missed expected triggers at the owner boundary.
