# Evaluation Model

## Valid evidence

Readiness considers only non-stale results from the active evaluation plan. Each criterion declares an aggregation rule; sample-weighted mean is the default. A criterion is complete only when it has a valid result, meets its minimum sample count, and includes every required evidence item.

Evaluator providers return typed measurements. The central gate engine alone applies policy thresholds and assigns verdicts. A hard gate is `PASSED`, `FAILED`, or `REMAINING`; both `FAILED` and `REMAINING` block promotion, regardless of weighted score.

## Total math

The shared helpers make every empty requirement set satisfied:

```text
safe_ratio(numerator, 0) = 1.0
safe_mean([]) = 1.0
```

The following cases are explicit:

- No hard gates: hard-gate readiness is `1.0`.
- No required criteria: evaluation completeness is `1.0`.
- No sample-bearing criteria: sample completeness is `1.0`.
- A criterion with `minimum_samples = 0`: its sample completeness is `1.0`.
- `minimum_weighted_score = 0`: weighted readiness is `1.0`.
- No weighted criteria: weighted score is `null`, shown as “Not required,” and weighted readiness is `1.0`.
- A nonzero weighted threshold without weighted criteria: invalid policy configuration.
- Weights must total `1.0` only when weighted criteria exist.

For nonempty weighted criteria:

```text
weighted_score = 100 × Σ(weight × normalized_score)
weighted_readiness = min(weighted_score / required_score, 1)
readiness_percentage = 25 × (
  hard_gate_readiness
  + weighted_readiness
  + sample_completeness
  + evaluation_completeness
)
```

Incomplete weighted criteria contribute zero to the weighted sum. Numeric values are clamped and represented deterministically at domain boundaries. Readiness describes evidence only; approvals and registry activation are reported separately.

## Providers

- `DeterministicRuleEvaluator`: evaluates typed fixture or source values.
- `TestSuiteEvaluator`: invokes only allow-listed test commands with bounded resources.
- `SyntheticMetricEvaluator`: computes repeatable metrics from fixtures.
- `OpenAIRubricEvaluator`: optional server-side structured rubric evaluation.

The OpenAI adapter uses strict structured output, `store=False`, sanitized raw-response artifacts, usage metadata, and `OPENAI_EVAL_MODEL`, defaulting to `gpt-5-mini`. Callers must redact sensitive source material before submitting evaluator input; production adapters should enforce that policy at their trust boundary. Demo and normal continuous integration use deterministic providers.

Deterministic detectors persist source signals for requested signal types. An optional artificial-intelligence-assisted detector may rank persisted deterministic signals; it cannot create discovery evidence.

## Copy certification

Critical interface copy is itself a versioned, hashed configuration artifact. Deterministic release checks enforce two opening lines, sentences no longer than 16 words, active voice heuristics, expanded acronyms, action consequence and undo language, no raw identifiers in primary copy, and a rendered-copy digest matching the governed artifact.

A copy-only semantic evaluator receives no product context beyond rendered copy and must identify the screen purpose, what happened, and every button's effect. Normal continuous integration uses a strict fake provider. With an OpenAI key, a live run can record semantic certification. Without credentials, the result is `unavailable`, never `certified`.

## Required test boundaries

Tests cover every empty-set rule, threshold zero, invalid no-weights configuration, incomplete weighted criteria, hard-gate precedence, aggregation variants, staleness, sample weighting, and evidence requirements. At least one seeded candidate has a high weighted score and a failed hard gate; another lacks samples.
