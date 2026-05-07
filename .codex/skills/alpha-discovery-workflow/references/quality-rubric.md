# Alpha Quality Rubric

Use this rubric after simulation. It is based on commonly shared WorldQuant BRAIN requirements and community automation thresholds:

- USA Delay-1 passing floor: Sharpe above 1.25, Fitness above 1.0, Turnover between 1% and 70%.
- Delay-0 usually needs stricter Sharpe and Fitness.
- CHN is stricter: commonly shared BRAIN documentation gives higher Sharpe and Returns thresholds.
- Community automation examples often use Sharpe around 1.58+, Fitness >= 1.0, Turnover <= 0.7, no failed checks, and correlation filtering.

References checked on 2026-05-07:

- WorldQuant Brain documentation mirror / Scribd snippet: passing Sharpe, Fitness, Turnover, CHN thresholds, self-correlation notes.
- RussellDash332/WQ-Brain README: IS pass criteria.
- xiegengcai/world-quant-brain DeepWiki: selection criteria and failure/correlation filtering.
- Public WorldQuant IQC page: scoring depends on submitted alpha quality and quantity, but exact platform checks remain in BRAIN.

## Tiers

### high

Use for direct family promotion candidates:

- `checks_failed == 0`
- behavior similarity `< 0.55`
- USA D1: Sharpe `>= 1.58`, Fitness `>= 1.3`, Turnover `1%..40%`
- Delay-0 or CHN: use stricter platform floors, then require a buffer above those floors
- Economic mechanism is clear and parameterizable

### medium

Use for refinement:

- No failed checks and behavior similarity `< 0.7`
- Meets or nearly meets platform floor, or has Sharpe `>= 0.8`, Fitness `>= 0.5`, Turnover `0.5%..80%`
- Defect is plausibly fixable by window, decay, neutralization, truncation, or wrapper changes

### low

Reject or archive:

- Failed checks, behavior similarity `>= 0.7`, nonsensical economics, extreme turnover, weak Sharpe/Fitness, or unstable stage metrics
- Do not add low quality families to `config/templates.json`
