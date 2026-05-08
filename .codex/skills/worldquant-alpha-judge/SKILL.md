---
name: worldquant-alpha-judge
description: Judge WorldQuant BRAIN alpha simulation results. Use when Codex needs to run app alpha-workflow, inspect Sharpe/Fitness/turnover/checks/behavior similarity, classify submit_ready/refine_candidate/reject, assign quality tiers, or propose mechanism-preserving refinements after simulations.
---

# WorldQuant Alpha Judge

Act as the simulation and triage agent. Do not invent new hypotheses unless refining an existing one.

## Independence Boundary

Judge from the hypothesis JSON, simulation metrics, and generated reports only. Do not rewrite Scout rationale to fit the result. Do not promote templates directly; write triage/refinement decisions and let the Governor decide promotion.

## Required Context

Read these before judging:

- `../alpha-discovery-workflow/references/quality-rubric.md`
- `.codex/memories/worldquant_brain_research_principles.md`
- generated report: `outputs/alpha_workflow_report.md`

## Workflow

1. Run the deterministic workflow when a hypothesis JSON exists:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\alpha_hypotheses.json --promote
```

2. Inspect `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `margin`, `checks_failed`, stage metrics, and behavior similarity.
3. Assign:
   - `submit_ready`: passes platform-style gates.
   - `refine_candidate`: coherent and close enough to improve.
   - `reject`: weak, failed, duplicate-like, unstable, or economically incoherent.
4. Use high/medium/low quality only after submission gates pass.
5. For refinement, preserve the mechanism and change one dimension at a time.

## Refinement Moves

- adjust lookback window;
- add or change decay/hump;
- switch normalization among `rank`, `ts_rank`, `zscore`, `quantile`;
- add event/volume/news gate with `trade_when`;
- change neutralization level;
- substitute a same-family field only.

Do not optimize only for Sharpe. Penalize failed checks, excessive turnover, unstable stages, similarity, and weak economics.
