# WorldQuant BRAIN Research Principles

Last updated: 2026-05-08

## Sources Reviewed

- IQC Alpha Advanced Series 5, Scribd page: https://www.scribd.com/document/1018126643/737578644-IQC-Alpha-Advanced-Series-5
- Finding Alphas / Introduction to Alpha Design, notes.yeshiwei.com PDF: https://notes.yeshiwei.com/_downloads/9a536da31207cc1942b82e5769782af6/WorldQuant_FindingAlphas.pdf

Do not use Z-Library or other unauthorized uploads as source material. Use public snippets, legitimate copies, local user-provided files, or official/authorized resources.

## Core Professional Understanding

An alpha is a forecast of future relative returns, implemented as daily stock positions. A good alpha is not just a formula with a high backtest metric; it should express a plausible information mechanism that changes through time and can be transformed into cross-sectional positions.

The starting point for alpha design should be a market mechanism:

- information delay: fundamentals, estimates, news, or events are incorporated slowly;
- temporary liquidity pressure: volume shocks and short-horizon price moves later revert;
- risk premium: persistent compensation for bearing volatility, leverage, balance-sheet, or liquidity risk;
- accounting quality: cash flow, earnings, capex, debt, tax, and asset/liability relationships reveal quality or distress;
- crowding reversal: signals work until they become too similar or too crowded;
- option/volatility dislocation: implied volatility and realized volatility can reveal repricing pressure.

Data changes matter more than static levels. Prefer deltas, ranks, rolling ranks, z-scores, quantiles, rolling sums/means, argmin/argmax, and event gates over raw fields.

## Expression Design Patterns

Common robust FASTEXPR patterns:

- normalize first: `rank`, `zscore`, `ts_rank`, `ts_zscore`, `quantile`;
- control bad data: `ts_backfill`, winsorization, NaN handling;
- reduce unintended exposure: `group_neutralize`, `group_rank`, vector neutralization where appropriate;
- control turnover: decay, longer windows, `hump`, and `trade_when`;
- use event filters: volume above ADV, news/event indicators, thresholded fundamentals, or volatility regime checks;
- combine signals only when they share one coherent mechanism.

Useful research families:

- leverage and balance-sheet ratios: assets, liabilities, debt, equity, current liabilities;
- profitability and efficiency: operating income, EBIT, cash flow, capex, sales/assets;
- estimate revisions: EPS or net-profit estimates scaled by price or compared with prior values;
- news-derived vector fields: vector averages or event-count fields after backfill/aggregation;
- volatility dislocation: implied volatility versus realized/parkinson volatility, or volatility changes over time;
- liquidity-conditioned reversal: short-term return reversal gated by abnormal volume or ADV.

Do not copy formula lists blindly. Treat example formulas as templates for mechanisms: identify the field family, normalization, time horizon, gating condition, and risk exposure being neutralized.

## Scout Rules

1. Start from a single economic mechanism.
2. Map the mechanism to fields that actually exist in `config/fields.json`.
3. Draft 3-8 variants with small changes: window, normalization, decay, neutralization, or one same-family field substitution.
4. Record expected horizon, failure mode, and neutralization choice.
5. Avoid loose linear combinations of unrelated fields.

## Judge Rules

- `submit_ready`: no failed checks, behavior similarity below duplicate threshold, region/delay-specific Sharpe and Fitness floors passed, turnover in acceptable range.
- `refine_candidate`: no failed checks, coherent economics, behavior similarity below 0.7, Sharpe at least 0.8, Fitness at least 0.5, turnover roughly 0.5%-80%.
- `reject`: failed checks, weak economic story, extreme turnover, unstable stages, high similarity, or too far from submission gates.

Quality tiers apply only after submission gates are passed.

## Empirical Research Principles From Interactive Alpha Search

1. Do not optimize alpha by random formula mutation. Work by alpha family and change one dimension at a time.

2. Intraday signed pressure reversal is real but turnover-heavy. Useful proxies:
   - `(close - open) / (high - low + 0.01)`
   - `(2 * close - high - low) / (high - low + 0.01)`
   - `(vwap - close) / (high - low + 0.01)`

3. Hard `trade_when` filters often reduce turnover but destroy return density. Do not use hard gating unless returns remain stable.

4. Over-smoothing reduces turnover but usually also reduces Sharpe / Returns.

5. Pure range expansion, overnight gap reversal, and absolute movement efficiency were weak in current tests.

6. Long-horizon return z-score reversal is currently the strongest family. Best current candidate:

```text
signed_power(
    -ts_decay_linear(((returns - ts_mean(returns, 120)) / (1 + ts_std_dev(returns, 120))), 90),
    0.9
)
```

Current reference metrics: Sharpe 1.18, Turnover 10.64%, Fitness 1.37, Returns 16.77%, Drawdown 12.20%.

7. Full `rank()` destroys useful z-score amplitude in this family. Avoid `rank()` unless concentration cannot be solved otherwise.

8. `signed_power` compression is better than `rank()` for controlling extreme exposure. Useful power range: 0.85-0.95.

9. Once Fitness > 1.2 and Turnover < 40%, stop blind optimization. Prioritize:
   - weight concentration;
   - sub-universe Sharpe;
   - self-correlation.

10. Use 101 Formulaic Alphas as structural evidence, not a copy source. Key lessons: short holding periods, low average pairwise correlation, and returns-volatility relationships matter; formula copying does not.
