# Governed Cold-Read Copy

Critical copy is release-controlled configuration, not ad hoc component text. The shared serializable artifact is `configs/copy/governed-copy.json`. It carries a schema version, canonical SHA-256 digest, every governed screen and action, and the semantic certification cases. The React package renders the matching typed artifact; release tests require byte-semantic equality and reject any digest drift.

Critical contexts include candidate blockers, promotion rationale, pending registry publication, terminal failure recovery, and every consequential action.

## Cold-read contract

The first two lines must let a reviewer with no surrounding context answer:

1. What is this screen and what happened?
2. What should I do, and what will that action change?

Additional deterministic rules:

- Keep every sentence at 16 words or fewer.
- Prefer short, active constructions; flag passive-voice patterns for review.
- Expand acronyms on first use.
- Put meaning beside every number.
- Keep raw identifiers and technical blocker codes secondary.
- State each action's consequence and whether it is reversible.
- Keep safety meaning independent of color.
- Reject a rendered digest that differs from the governed artifact.

## Semantic certification

The copy-only evaluator receives rendered text without application context. It returns its own inferred screen purpose, event, and effect of every button. Normal continuous integration runs a strict deterministic fake against every shared-artifact case and verifies that every screen and action is covered. A configured OpenAI run evaluates those same cases, returns model-derived structured fields, and uses `store=False`.

When no key is configured, record semantic certification as `unavailable`. Never convert absence, timeout, parse failure, or provider refusal into certification.
