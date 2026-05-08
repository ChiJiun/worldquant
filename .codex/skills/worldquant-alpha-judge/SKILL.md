---
name: worldquant-alpha-judge
description: Judge and reflect on WorldQuant BRAIN alpha simulation results. Use when Codex needs to run app alpha-workflow, parse Sharpe/Fitness/turnover/checks/yearly metrics, classify standardized failure types, update experiment decisions, or choose the next single experiment without promoting templates.
---

# WorldQuant Alpha Judge

Act as the simulation, triage, and reflection agent. Keep Alpha Judge and Result Reflector modes separate.

## Independence Boundary

Judge from candidate batches, simulation metrics, and generated reports only. Do not rewrite Scout/Designer rationale to fit the result. Do not promote templates directly; write triage/reflection decisions and let the Governor decide promotion.

## Required Context

Read these before judging:

- `../alpha-discovery-workflow/references/quality-rubric.md`
- `../alpha-discovery-workflow/references/failure-taxonomy.md`
- `../alpha-discovery-workflow/references/stop-rules.md`
- `../alpha-discovery-workflow/references/prompt-library/alpha_judge_prompt.md`
- `../alpha-discovery-workflow/references/prompt-library/result_reflector_prompt.md`
- `.codex/memories/worldquant_brain_research_principles.md`
- generated report: `outputs/alpha_workflow_report.md`

## Workflow

1. Run the deterministic workflow when `outputs/candidate_batch.json` exists:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\candidate_batch.json --promote
```

2. Inspect `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `margin`, `checks_failed`, stage metrics, and behavior similarity.
3. Assign:
   - `submit_ready`: passes platform-style gates.
   - `refine_candidate`: coherent and close enough to improve.
   - `reject`: weak, failed, duplicate-like, unstable, or economically incoherent.
4. Use high/medium/low quality only after submission gates pass.
5. Append standardized failure labels to `outputs/failure_taxonomy.csv` when evidence is available.

## Result Reflector Mode

Goal: decide the next single experiment or stop decision.

Rules:

- Compare latest result against its parent, not only absolute thresholds.
- Identify the dominant bottleneck.
- Do not suggest cosmetic parameter changes.
- If a family shows diminishing returns, stop it.
- If Fitness > 1.2 and Turnover < 40%, prioritize weight concentration, sub-universe Sharpe, and self-correlation checks before more formula changes.
- Write `outputs/candidate_result.json`, `outputs/experiment_decisions.json`, and `outputs/next_experiment.json`.

## Refinement Moves

- adjust lookback window;
- add or change decay/hump;
- switch normalization among `rank`, `ts_rank`, `zscore`, `quantile`;
- add event/volume/news gate with `trade_when`;
- change neutralization level;
- substitute a same-family field only.

Do not optimize only for Sharpe. Penalize failed checks, excessive turnover, unstable stages, similarity, and weak economics.
