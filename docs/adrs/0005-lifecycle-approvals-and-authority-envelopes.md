# ADR 0005: Lifecycle Approvals and Authority Envelopes

- Status: Accepted
- Date: 2026-08-24

## Context

Promotion selects a version for future production runs. Paul OS uses bounded authority envelopes to authorize execution scope. Calling both mechanisms “approval” without defining their boundaries could imply per-run approval or accidental runtime authority.

## Decision

Name the control-plane record `PromotionLifecycleApproval`. Bind it to the exact candidate, target stage, policy hash, evaluation snapshot, decision, actor, and rationale. Allow revocation only before publication queues; queuing consumes the snapshot. Do not add evaluation-run approvals.

Promotion changes which tested version new production runs select. It does not authorize a run or grant tool access.

Paul OS authority envelopes remain downstream controls for tools, inputs, budgets, validity, and run counts. In Paul OS, an injected callback routes the lifecycle decision through Attention.

## Consequences

Promotion cannot expand execution authority. The first production run after promotion and any scope-expanding or approval-required action still follow the authority-envelope flow. Standalone and embedded decision interfaces share domain semantics but not necessarily the same mutation surface.
