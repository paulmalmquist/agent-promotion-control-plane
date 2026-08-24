# Demo Script

## Goal

Show that evaluation readiness, lifecycle eligibility, and registry activation are distinct, evidence-backed states. The demonstration requires no credentials and uses deterministic providers.

## Prepare

```bash
docker compose up --build --wait --wait-timeout 180
```

Open <http://localhost:3001>. Keep <http://localhost:8000/docs> available for API inspection.

If you reset before presenting, explain that reset rebuilds mutable demo fixtures. It preserves the append-only event sequence and records `DEMO_RESET_COMPLETED`.

## 1. Orient on Overview

Read the two opening lines aloud. They should explain what is governed, what changed, and what a reviewer should inspect next. Point out the lifecycle funnel, recent immutable events, externally owned jobs, registry outcomes, and evaluation velocity.

Explain the three independent displays: evaluation readiness, promotion eligibility, and registry activation.

## 2. Inspect a failed hard gate

Open the seeded blocked candidate. Its weighted score is intentionally high, but one hard gate failed. Confirm:

- readiness math exposes the failed hard gate;
- promotion eligibility is blocked;
- the failure uses a label and explanation, not color alone;
- the technical blocker code is secondary;
- no force-promote action exists.

Capture `docs/assets/blocked-candidate-detail.png` at the release viewport.

## 3. Inspect incomplete evidence

Open the candidate with insufficient samples. Show the required and observed sample counts beside the percentage. Explain that empty requirement sets are satisfied, while a nonempty unmet requirement remains incomplete.

## 4. Explain automation ownership

Open Automation and read:

> This control plane does not execute cron. The demo command, CLI/API, or named external scheduler triggers each job.

Show each job's trigger owner, connection state, last observed run, next expected trigger, and grace window. Open a disconnected job and confirm it plainly says it will not run automatically.

## 5. Run the autonomous cycle

```bash
docker compose exec -T api python -m promotion_control_plane.cli.main run-demo-cycle \
  --idempotency-key live-demo-cycle
```

Watch the ninth candidate progress through discovery, planning, evaluation, gates, eligibility, queued registry publication, worker activation, and monitoring. The UI consumes sequence-backed SSE events. Refresh or disconnect briefly, then reconnect and confirm replay fills the gap.

During publication, show that the candidate remains `ELIGIBLE` with `PROMOTION_PENDING`. Only after registry success should stage become `PROMOTED` and status become `ACTIVE`.

## 6. Inspect audit lineage

Open the candidate timeline. Follow correlation and causation links across discovery, evaluation, decision, approval, queued operation, registry result, and monitoring. Confirm the promoted event and immutable version appear only after registry success.

## 7. Explain authority

Read the governed statement:

> Promotion changes which tested version new production runs select. It does not authorize a run or grant tool access.

Explain that Paul OS authority envelopes still govern scope, tools, inputs, budgets, validity, and run counts. Promotion lifecycle approval does not replace that flow.

## 8. Prove idempotency

Repeat the exact demo cycle command. It should return the recorded result without creating another candidate, registry version, or event sequence for the same intent.

Run the exact Compose startup command again and confirm all long-lived services remain healthy:

```bash
docker compose up --build --wait --wait-timeout 180
```

## Release captures

Capture these real Playwright-rendered files after all material gaps are fixed:

- `docs/assets/control-plane-overview.png`
- `docs/assets/blocked-candidate-detail.png`

Do not retouch state, numbers, or status colors in the screenshots.
