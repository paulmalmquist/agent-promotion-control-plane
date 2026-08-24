# ADR 0003: Browser-Neutral Promotion UI

- Status: Accepted
- Date: 2026-08-24

## Context

The standalone Next.js interface must transplant into Paul OS, a Vite React host with locked console grammar and a governed mutation surface.

## Decision

Place reusable views in `packages/promotion-ui`. It imports no `next/*` module, Server Component primitive, Next router, or proxy. Hosts inject initial data, transports, event subscriptions, navigation, lifecycle decisions, and semantic tokens. Styles are scoped below `[data-promotion-control-plane]`.

The default palette uses purple and teal categories, amber for degraded non-safety state, red only for explicit safety or authorization stops, and quiet neutrals for success. The package uses no generic icon library.

## Consequences

The Next.js application owns server loaders, actions, routing, and SSE proxying. Paul OS can mount the same package without a second app, rail destination, or design system. Host adapters require dedicated integration tests.
