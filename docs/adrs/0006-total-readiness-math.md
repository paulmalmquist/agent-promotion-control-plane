# ADR 0006: Total Readiness Math

- Status: Accepted
- Date: 2026-08-24

## Context

Policies may intentionally contain no hard gates, criteria, weights, or sample requirements. Undefined division and compensable hard gates would make readiness misleading.

## Decision

Define `safe_ratio(n, 0) = 1.0` and `safe_mean([]) = 1.0`. Treat every empty requirement set as satisfied. No weighted criteria yields a null score displayed as “Not required” and weighted readiness `1.0`; a nonzero weighted threshold in that configuration is invalid. Hard gates remain non-compensable.

Readiness is the equal average of hard-gate readiness, weighted readiness, sample completeness, and evaluation completeness. It reports evaluation evidence only.

## Consequences

Readiness is defined for every valid policy and remains stable during registry failure. Policy validation and exhaustive empty-set tests are mandatory.
