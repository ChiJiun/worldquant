# Stop Rules

Use stop rules to avoid wasting simulations on exhausted families.

## Family Stop Rule

Stop a family after 5 consecutive attempts if any of these holds:

- Fitness does not improve by at least `0.05` versus the family baseline.
- Sharpe, returns, and turnover only trade off with no net Fitness improvement.
- Self-correlation risk is high and no orthogonal design change is available.
- The same dominant failure type repeats 3 times.
- Operator/unit failures show the required data cannot be expressed with current catalog support.

## Interactive Workflow Rule

When the user is actively iterating, Alpha Designer outputs exactly one next alpha expression unless the user asks for a batch.

## Submit-Candidate Rule

If latest alpha has Fitness above `1.2` and Turnover below `40%`, stop blind formula tuning. First check:

- weight concentration;
- sub-universe Sharpe;
- self-correlation.

## Promotion Stop Rule

Do not promote a family if all improvements are cosmetic parameter changes or if all variants fail the same bottleneck.
