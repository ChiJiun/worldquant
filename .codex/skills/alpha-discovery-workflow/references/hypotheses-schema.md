# Hypotheses JSON Schema

Write scout output to `outputs/alpha_hypotheses.json` with this shape:

```json
{
  "session_id": "20260507_example",
  "hypotheses": [
    {
      "id": "liquidity_reversal_after_volume_shock",
      "family": "liquidity_reversal_after_volume_shock",
      "source_urls": ["https://example.com/source"],
      "economic_mechanism": "Temporary liquidity demand pushes prices away from fair value; reversal appears after volume pressure normalizes.",
      "rationale": "A volume shock combined with weak short-horizon return can identify forced trading pressure.",
      "expected_horizon": "5-20 trading days",
      "failure_modes": ["crowded reversal", "high turnover", "sector-specific liquidity regimes"],
      "alphas": [
        {
          "expression": "rank(-(returns / (1 + ts_rank(volume, 20))))",
          "rationale": "Ranks negative short-horizon return scaled by recent volume pressure."
        }
      ]
    }
  ]
}
```

Required fields:

- `hypotheses[].id`
- `hypotheses[].family`
- `hypotheses[].alphas[].expression`

Recommended fields:

- `source_urls`
- `economic_mechanism`
- `rationale`
- `expected_horizon`
- `failure_modes`
