# Final Alpha Recommendations

- generated_at: 2026-05-12T00:00:00Z
- recommended_count: 1
- submitted_registry_count: 2

## 1. EXAMPLE_ALPHA_ID

- status: `best`
- candidate_id: `EXAMPLE_candidate_001`
- family: `example_cashflow_quality`
- cluster_id: `C001`
- core_signal: `fundamental_value_quality`
- direction: `mixed`
- submit_score: `1.95`
- IS Sharpe: `2.10`
- IS Fitness: `1.72`
- IS Returns: `0.132`
- IS Turnover: `0.185`
- IS Drawdown: `0.061`
- economic_meaning: Fundamental ratios are used as a proxy for value, quality, or capital efficiency.
- selection_reason: Selected as the best representative of its high-correlation cluster after quality scoring, economic-meaning consistency check, and submitted-alpha correlation gate.
- OS_overfit_risk: medium: recommendation is based on IS metrics plus structural gates; require live OS/self-correlation review.
- submitted_correlation: Best submitted match `EXAMPLE_SUBMITTED_ALPHA` score=0.4200, reason=correlation_high.

```text
rank(cashflow / assets) + rank(ts_delta(ebitda / sales, 120))
```

If no alpha passes all gates, the real report lists blocked best candidates and explains whether they were rejected for submitted correlation or economic-meaning drift.
