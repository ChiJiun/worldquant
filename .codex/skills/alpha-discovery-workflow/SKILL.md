---
name: alpha-discovery-workflow
description: Automate WorldQuant BRAIN alpha discovery from market-arbitrage hypothesis research through alpha expression drafting, simulation, result judgment, iterative refinement, and promotion of valuable alpha families into GA templates. Use when Codex is asked to find alphas, research market inefficiencies online, separate hypothesis-finding and alpha-judging roles, run or improve WorldQuant Brain simulate/GA scripts, classify alpha quality, or maintain config/templates.json for GA mining.
---

# Alpha Discovery Workflow

Use this skill as the operating procedure for this repo's alpha mining loop. Keep the roles separated even when one Codex instance executes both passes.

## Repo Map

Read `references/repo-map.md` before changing code or running commands.
Read `references/quality-rubric.md` before judging simulated alphas or changing thresholds.
Use `knowledge-base-search-skill` when local WorldQuant field/operator/optimization knowledge is needed.
Use `factor-backtest-skill` when batching exactly 8 expressions through a multi-simulation flow.

Primary tool command:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\alpha_hypotheses.json --promote
```

The hypothesis scout must write JSON in the schema shown in `references/hypotheses-schema.md` before running the tool.

Other local commands:

```powershell
C:\Users\USER\anaconda3\python.exe -m app login-check
C:\Users\USER\anaconda3\python.exe -m app generate --count 10
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
C:\Users\USER\anaconda3\python.exe -m app mine --cycles 20 --sleep-seconds 5
C:\Users\USER\anaconda3\python.exe -m app dashboard --limit 10
```

## Role Split

### Hypothesis Scout

Goal: find economically plausible market-arbitrage hypotheses, not random formulas.

Procedure:

1. Search the web for current academic papers, practitioner notes, WorldQuant community examples, and market microstructure observations. Prefer primary or technically concrete sources.
2. Extract one mechanism per hypothesis: behavioral bias, information delay, liquidity provision, risk premium, accounting quality, event drift, or crowding reversal.
3. Map the mechanism to available WorldQuant fields from `config/fields.json`.
4. Draft 3-8 FASTEXPR candidates from the same mechanism. Keep the field set small and economically coherent.
5. Record why each candidate should work, expected horizon, likely failure mode, and suggested neutralization.
6. Write the final candidate batch to `outputs/alpha_hypotheses.json`.

Do not promote a hypothesis to GA templates before at least one direct simulation shows promise.

### Alpha Judge

Goal: decide whether simulated results justify refinement, family promotion, or rejection.

Procedure:

1. Simulate the scout's candidates with the repo's Brain client or mock client when credentials/network are unavailable.
2. Inspect `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `margin`, `checks_failed`, stage metrics, and behavior similarity.
3. Assign `quality_tier` using `references/quality-rubric.md`.
4. Decide:
   - `reject`: low quality, failed checks, no economic mechanism, or duplicate behavior.
   - `refine`: medium quality or near-threshold result with a fixable defect.
   - `promote_family`: high quality, clear mechanism, low similarity, and stable checks.
5. For `refine`, change one mechanism-preserving dimension at a time: window, decay, neutralization, truncation, rank/zscore wrapper, or one field substitution from the same dataset.
6. Run `python -m app alpha-workflow --hypotheses outputs/alpha_hypotheses.json --promote` for the deterministic simulate/judge/report pass.

If the user explicitly requests parallel agents, delegate Hypothesis Scout and Alpha Judge as separate agents. Otherwise run the two passes locally and keep their outputs separate.

## Template Promotion

`config/templates.json` is intentionally allowed to be empty. Only add a template family after direct simulation evidence supports it.

Promotion checklist:

- At least one expression in the family is high quality, or multiple related expressions are medium quality with consistent economic interpretation.
- The family can be parameterized by fields/windows/wrappers without becoming a loose linear combination bucket.
- The template name describes the mechanism, not a metric target.
- The allowed fields are in the same economic family or dataset.
- The family has an obvious mutation surface for GA: windows, wrappers, decay, neutralization-compatible fields.

After adding or editing templates, run:

```powershell
C:\Users\USER\anaconda3\python.exe -m app generate --count 10
C:\Users\USER\anaconda3\python.exe -m pytest
```

## Research Log

When the installed recorder skill is available, use `alpha-research-recorder` style logs:

- Create `session_meta` before any round.
- Create a `round_NNNN.yml` after each scout/judge cycle.
- Fill economic fields first: hypothesis, interpretation, insights.

## Guardrails

- Do not auto-submit alphas; stop at simulation, quality tiering, and template promotion unless the user explicitly asks for submission.
- Do not add garbage templates to make GA run. Empty templates are better than broad, unvalidated families.
- Do not optimize only for Sharpe. Penalize failed checks, excessive turnover, unstable stage metrics, high behavior similarity, and weak economics.
- Keep changes repo-local unless the user explicitly authorizes external paths.
