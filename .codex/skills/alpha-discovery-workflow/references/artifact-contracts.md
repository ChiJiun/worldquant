# Artifact Contracts

Runtime artifacts live in `outputs/` and are ignored by git. Keep one stable file per artifact type and append or update content across runs.

## `outputs/source_notes.json`

Produced by Literature Scout. Contains research sources and market mechanisms only. No final alpha expressions.

```json
{
  "source_batch_id": "R_YYYYMMDD_001",
  "items": [
    {
      "source_title": "101 Formulaic Alphas",
      "source_type": "paper",
      "reliability_score": 4,
      "key_claim": "Formulaic alpha families can have low average correlation and short holding periods.",
      "market_mechanism": "Short-horizon formulaic alpha families can be low-correlated and volatility-linked.",
      "observable_proxy_using_allowed_fields": ["open", "high", "low", "close", "volume", "vwap", "returns"],
      "possible_alpha_family": "close_location_exhaustion",
      "expected_holding_period": "1-20 days",
      "expected_failure_mode": ["turnover_too_high", "self_corr_risk"],
      "already_tested": false
    }
  ]
}
```

## `outputs/alpha_hypotheses.json`

Produced by Hypothesis Scout. Contains falsifiable hypotheses only, not final formulas.

```json
{
  "hypotheses": [
    {
      "hypothesis_id": "H_YYYYMMDD_001",
      "family": "long_horizon_return_zscore_reversal",
      "hypothesis_type": "concentration_control",
      "market_mechanism": "Extreme long-horizon return deviations may revert, but raw z-scores can create concentrated portfolio weights.",
      "allowed_proxies": ["returns", "ts_mean(returns, 120)", "ts_std_dev(returns, 120)", "ts_decay_linear", "signed_power"],
      "expected_effect": {
        "returns": "slightly lower than raw",
        "turnover": "lower",
        "weight_concentration": "improved",
        "sub_universe": "possibly improved"
      },
      "main_risk": ["signal_amplitude_destroyed"],
      "next_design_hint": "Test mild signed_power compression between 0.85 and 0.95."
    }
  ]
}
```

## `outputs/candidate_batch.json`

Produced by Alpha Designer. This is the expression input for `app alpha-workflow`.

```json
{
  "candidate_batch_id": "B_YYYYMMDD_001",
  "candidates": [
    {
      "candidate_id": "A_YYYYMMDD_001",
      "hypothesis_id": "H_YYYYMMDD_001",
      "family": "long_horizon_return_zscore_reversal",
      "expression": "-ts_rank(returns, 120)",
      "changed_dimension": "base_version",
      "expected_effect": {
        "sharpe": "unknown",
        "returns": "medium",
        "turnover": "low",
        "drawdown": "unknown",
        "weight_concentration": "risk"
      },
      "why_this_is_not_duplicate": "Tests z-score reversal family, not short-horizon price pressure.",
      "risk_flags": ["sub_universe_fail"]
    }
  ]
}
```

## `outputs/candidate_result.json`

Optional structured export from Alpha Judge when raw platform data is available.

```json
{
  "candidate_id": "A_YYYYMMDD_001",
  "expression": "-ts_rank(returns, 120)",
  "aggregate": {
    "sharpe": 1.18,
    "turnover": 10.64,
    "fitness": 1.37,
    "returns": 16.77,
    "drawdown": 12.20,
    "margin": 31.53
  },
  "yearly": [{"year": 2019, "sharpe": 1.08, "returns": 12.86}],
  "checks": {
    "weight_concentration": "unknown",
    "sub_universe_sharpe": "unknown",
    "self_corr": "pending"
  },
  "classification": "submit_candidate",
  "failure_types": [],
  "notes": ""
}
```

## `outputs/experiment_decisions.json`

Produced by Reflection Analyst. Append one decision per evaluated candidate.

```json
{
  "decisions": [
    {
      "candidate_id": "A_YYYYMMDD_001",
      "decision": "control_concentration",
      "dominant_bottleneck": "weight_concentration_or_sub_universe_unknown",
      "next_experiment": {
        "expression": "-ts_rank(returns, 120)",
        "changed_dimension": "amplitude_compression_strength"
      },
      "stop_rule": "If concentration fails, stop this branch."
    }
  ]
}
```

## `outputs/family_memory.json`

Updated by Reflection Analyst and Governor.

```json
{
  "families": [
    {
      "family": "long_horizon_return_zscore_reversal",
      "status": "best_candidate",
      "mechanism": "Long-horizon return z-score mean reversion.",
      "best_expression": "signed_power(-ts_decay_linear(((returns - ts_mean(returns, 120)) / (1 + ts_std_dev(returns, 120))), 90), 0.9)",
      "best_metrics": {
        "sharpe": 1.18,
        "turnover": 10.64,
        "fitness": 1.37,
        "returns": 16.77,
        "drawdown": 12.20
      },
      "known_good_parameters": {
        "lookback": 120,
        "decay": 90,
        "power": 0.9
      },
      "known_bad_changes": [
        {
          "change": "rank() around expression",
          "reason": "Destroyed z-score amplitude and reduced returns."
        },
        {
          "change": "signed_power 0.5",
          "reason": "Compressed signal too strongly."
        }
      ],
      "risks": ["sub_universe_sharpe", "weight_concentration", "self_corr"],
      "attempt_count": 4,
      "next_allowed_tests": ["power=0.95", "power=0.88", "volume/liquidity robustness check"],
      "stop_rules": ["Do not use rank unless concentration cannot be solved otherwise."]
    }
  ]
}
```

## Additional Stable Files

- `outputs/failure_taxonomy.csv`: candidate_id, family, expression, failure_type, evidence, recorded_at.
- `outputs/next_experiment.json`: exactly one next experiment or validation action for interactive workflows.
- `outputs/operator_errors.json`: invalid operator/unit errors and the expression that produced them.
