# Research Policy

## Modes

`literature_scout`

- Search for market mechanisms, not formulas.
- Extract economic story, observable proxy, candidate family, expected horizon, and failure modes.
- Do not output final expressions.

`hypothesis_builder`

- Convert notes and memory into falsifiable hypotheses.
- Include family, mechanism, proxy, expected direction, expected horizon, expected failure modes, and difference from tested families.

`alpha_designer`

- Convert one approved hypothesis into exactly one valid BRAIN expression.
- Change exactly one design dimension.
- Explain expected impact on Sharpe, Returns, Turnover, Drawdown, concentration, and sub-universe Sharpe.

`result_reflector`

- Compare latest result with parent, family best, and global best.
- Diagnose the dominant bottleneck before proposing the next action.
- Do not propose another formula if validation should come first.

`template_governor`

- Promote only robust, interpretable families.
- Do not promote if improvements are cosmetic, failures repeat, or yearly/sub-universe behavior is unstable.

## Policies

Exploration:

- If a family is unproven, test at most one alpha per run.
- Look for signal in Sharpe, Fitness, Returns, or stability.
- Record all invalid and failed directions.

Development:

- If a family is promising, tune one dimension at a time.
- Prefer interpretable parameters.
- Do not change lookback, decay, power, normalization, and filters in the same experiment.

Candidate validation:

- If Fitness > 1.2 and Turnover < 40, stop blind formula tuning.
- Check weight concentration, sub-universe Sharpe, self-correlation, and out-of-sample robustness.

Stop:

- Stop a family after five consecutive variants without meaningful Fitness improvement.
- Stop if the same dominant failure repeats three times.
- Stop if metrics only trade off without net improvement.

Workflow completion:

- Do not treat a normal simulation result as completion.
- Continue researching until a submit-worthy alpha is found, a family stop rule triggers, the user stops the run, or a per-invocation safety limit is reached.
- Use fixed artifact paths and avoid per-round report files.
- Store reusable lessons inside `research/family_memory.json`; do not create separate lesson files unless requested.

## Failure Taxonomy

- `turnover_too_high`
- `returns_too_low`
- `sharpe_too_low`
- `drawdown_too_high`
- `weight_concentration`
- `sub_universe_fail`
- `self_corr_fail`
- `signal_amplitude_destroyed`
- `over_smoothing`
- `hard_filter_destroyed_returns`
- `direction_wrong`
- `operator_invalid`
- `unit_incompatible`
- `platform_timeout`
- `platform_auth_error`
- `platform_error`
- `validation_failed`
- `validation_pending`
- `no_dominant_bottleneck`

## Reflection JSON

```json
{
  "decision": "continue_family / validate_best_candidate / stop_family / promote_template / record_failure",
  "dominant_bottleneck": "...",
  "latest_vs_parent": {
    "improved": [],
    "worsened": []
  },
  "causal_interpretation": "...",
  "next_action": {
    "type": "test_formula / validate_checks / stop_family / promote_template",
    "reason": "..."
  },
  "memory_update": {}
}
```
