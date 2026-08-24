# Paul OS Handoff

## Scope

The current operator checkout is `C:\Projects\paul-os`. That path is documentation context only. Every helper command accepts `PAUL_OS_REPO` or an explicit repository path; runtime code never depends on this checkout location.

```powershell
$env:PAUL_OS_REPO = 'C:\Projects\paul-os'
```

## Integration shape

Paul OS is the application. Do not mount another Next.js application or add a second design system. Lazy-load the browser-neutral `PromotionShell` from `packages/promotion-ui` into the existing Vite feature structure at `/agents/promotion`, beneath `PlatformShell`.

Link to the feature from Attention and Evidence. Keep Evidence active in the numbered rail and do not create another numbered destination. Use the existing API client and hooks to implement `PromotionDataSource`, event subscription, and navigation.

Review these Paul OS sources before editing because they remain authoritative:

- `07-protocols/console-grammar/CONSOLE_GRAMMAR.md`
- `docs/adr/0006-authority-envelopes.md`
- `docs/planning/phase-2-quiet-console-plan.md`
- the current governed critical-copy artifacts
- the current frontend feature, API, hook, and `PlatformShell` implementations

## Decision surface

Standalone mode can open its own governed lifecycle-decision dialog. In Paul OS, inject the decision callback and route it through Attention. Attention remains the sole mutation surface; the embedded package must not send the promotion mutation directly.

Promotion lifecycle approval and authority envelopes solve different problems:

> Promotion changes which tested version new production runs select. It does not authorize a run or grant tool access.

A `PromotionLifecycleApproval` is a version-selection lifecycle decision bound to the candidate, target stage, policy hash, evaluation snapshot, decision, actor, and rationale. It is consumed when registry publication queues. It is not an evaluation-run or per-run approval.

Paul OS bounded authority envelopes remain the downstream mechanism for execution scope, tools, inputs, budgets, validity, and run counts. The first production run after promotion and any scope expansion or approval-required action still follow `C:\Projects\paul-os\docs\adr\0006-authority-envelopes.md`.

## Visual grammar

Map the package's semantic tokens to Paul OS tokens at the host boundary:

| Meaning | Default | Paul OS rule |
|---|---:|---|
| Governed decision / primary emphasis | `#9578ff` | Purple decision token |
| Comparison / progress | `#2f9d82` | Teal secondary category |
| Degraded / incomplete / non-safety blocked | Host amber | Always pair icon or mark with text |
| Safety / authorization stop | Host red | Use only for explicit stop states |
| Nominal / successful | Neutral | Quiet treatment; never introduce green |

Use Paul OS typography, numbered navigation, rules, connectors, spacing, and purpose-built drafting marks. Add no generic icon dependency and no stock sparkle, wand, robot, database-cylinder, or code-bracket imagery. Preserve non-color labels, keyboard behavior, and reduced motion.

## Cold-read contract

Critical copy remains a versioned and hashed artifact. The first two lines on each blocker, rationale, pending publication, failure-recovery, or consequential-action screen must tell a context-free reviewer:

1. what this screen governs and what happened;
2. what they should do next and what that action changes.

Keep sentences to 16 words or fewer, expand acronyms on first use, put meaning beside every number, demote raw identifiers and blocker codes, and state each action's consequence and reversibility. Run deterministic copy checks and compare the rendered digest to the governed artifact after applying Paul OS composition.

## Suggested transplant steps

1. Build the package and copy or workspace-link its distributable output into the Paul OS repository.
2. Add a promotion feature adapter beside existing Vite features.
3. Map host API hooks and SSE replay into `PromotionDataSource` and the event subscription.
4. Add the `/agents/promotion` lazy route under `PlatformShell`.
5. Add contextual Attention and Evidence links without adding a rail destination.
6. Inject the Attention lifecycle-decision callback.
7. Map semantic tokens and verify governed-copy digest.
8. Run embedded navigation, authorization-envelope, responsive, keyboard, and reduced-motion tests.

No script should mutate the Paul OS checkout without an explicit path and operator action.
