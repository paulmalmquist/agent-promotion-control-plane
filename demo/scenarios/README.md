# Deterministic demo scenarios

The seed is fixed and safe to reset. It covers discovery, queued and active evaluation,
missing samples, a high score blocked by a hard gate, eligibility, promotion, and a
post-promotion regression. The autonomous cycle adds `change-risk-coordinator` and
advances it through registry activation using deterministic providers.

Run the cycle with `make demo`, `scripts/demo-cycle.ps1`, or the idempotent API. The
resident application does not execute schedules on its own.
