# Alpha Quality Rubric

Use this rubric after simulation. Separate submit/refine/reject triage from quality tiers.

- USA Delay-1 passing floor: Sharpe above 1.25, Fitness above 1.0, Turnover between 1% and 70%.
- Delay-0 usually needs stricter Sharpe and Fitness.
- CHN is stricter: commonly shared BRAIN documentation gives higher Sharpe and Returns thresholds.
- Community automation examples often use Sharpe around 1.58+, Fitness >= 1.0, Turnover <= 0.7, no failed checks, and correlation filtering.

References checked on 2026-05-07:

- WorldQuant Brain documentation mirror / Scribd snippet: passing Sharpe, Fitness, Turnover, CHN thresholds, self-correlation notes.
- RussellDash332/WQ-Brain README: IS pass criteria.
- xiegengcai/world-quant-brain DeepWiki: selection criteria and failure/correlation filtering.
- Public WorldQuant IQC page: scoring depends on submitted alpha quality and quantity, but exact platform checks remain in BRAIN.

## Triage

### submit_ready

The alpha passes platform-style gates:

- no failed checks
- behavior similarity below the duplicate threshold
- USA Delay-1: Sharpe >= 1.25, Fitness >= 1.0, Turnover 1%-70%
- stricter Delay-0/CHN floors when applicable

### refine_candidate

The alpha does not pass submission gates yet, but is close enough to improve:

- no failed checks
- behavior similarity < 0.7
- Sharpe >= 0.8
- Fitness >= 0.5
- Turnover 0.5%-80%
- economic mechanism is coherent

### reject

Failed checks, weak economics, duplicate behavior, extreme turnover, or too far from submission.

## Quality Tiers

Only assign high/medium/low after `submit_ready` is true. A low quality alpha still passes submission gates.

### high

Use for expert-level submission candidates:

- Sharpe >= 2.0
- Fitness >= 1.3
- Turnover < 40%
- no failed checks
- low behavior similarity
- clear economic mechanism

### medium

Use for strong but less exceptional submission candidates:

- passes submission gates
- Sharpe >= 1.58, Fitness >= 1.0, Turnover <= 70%

### low

Use for minimum-pass submission candidates:

- passes submission gates
- does not meet medium/high standards
- still save to `submittable_alphas`
