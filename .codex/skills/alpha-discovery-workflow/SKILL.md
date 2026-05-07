---
name: alpha-discovery-workflow
description: Automate WorldQuant BRAIN alpha discovery from market-arbitrage hypothesis research through alpha expression drafting, simulation, result judgment, iterative refinement, and promotion of valuable alpha families into GA templates. Use when Codex is asked to find alphas, research market inefficiencies online, separate hypothesis-finding and alpha-judging roles, run or improve WorldQuant Brain simulate/GA scripts, classify alpha quality, or maintain config/templates.json for GA mining.
---

# Alpha Discovery Workflow

Use this skill as the operating procedure for this repo's alpha mining loop. Keep the professional research role, simulation triage role, and GA/template governance role separate even when one Codex instance executes all passes.

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
C:\Users\USER\anaconda3\python.exe -m app catalog-sync --output config\fields.json
C:\Users\USER\anaconda3\python.exe -m app login-check
C:\Users\USER\anaconda3\python.exe -m app generate --count 10
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
C:\Users\USER\anaconda3\python.exe -m app mine --cycles 20 --sleep-seconds 5
C:\Users\USER\anaconda3\python.exe -m app dashboard --limit 10
```

## Role Split

### Hypothesis Scout

Goal: act as a professional quantitative researcher: read papers, research notes, and market-structure evidence, then design economically plausible market-arbitrage hypotheses and alpha expressions.

Procedure:

1. Search the web for current academic papers, practitioner notes, WorldQuant community examples, and market microstructure observations. Prefer primary or technically concrete sources.
2. Extract one mechanism per hypothesis: behavioral bias, information delay, liquidity provision, risk premium, accounting quality, event drift, or crowding reversal.
3. Map the mechanism to available WorldQuant fields from `config/fields.json`. If the catalog is still the stub version, run `catalog-sync` first and do not invent fields.
4. Draft 3-8 FASTEXPR candidates from the same mechanism. Keep the field set small and economically coherent.
5. Record why each candidate should work, expected horizon, likely failure mode, and suggested neutralization.
6. Write the final candidate batch to `outputs/alpha_hypotheses.json`.

Do not promote a hypothesis to GA templates before at least one direct simulation shows promise.

### Alpha Judge

Goal: decide whether simulated results are submit-ready, improvement candidates, or rejects.

Procedure:

1. Simulate the scout's candidates with the repo's Brain client or mock client when credentials/network are unavailable.
2. Inspect `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `margin`, `checks_failed`, stage metrics, and behavior similarity.
3. Assign `triage_decision` and `quality_tier` using `references/quality-rubric.md`.
4. Decide:
   - `submit_ready`: already passes WorldQuant submission gates.
   - `refine_candidate`: not submit-ready, but close enough and economically coherent enough to improve.
   - `reject`: failed checks, weak economics, duplicate behavior, or too far from submission.
5. For `refine`, change one mechanism-preserving dimension at a time: window, decay, neutralization, truncation, rank/zscore wrapper, or one field substitution from the same dataset.
6. Run `python -m app alpha-workflow --hypotheses outputs/alpha_hypotheses.json --promote` for the deterministic simulate/judge/report pass.

If the user explicitly requests parallel agents, delegate Hypothesis Scout and Alpha Judge as separate agents. Otherwise run the two passes locally and keep their outputs separate.

## Template Promotion

`config/templates.json` is intentionally allowed to be empty. Template governance primarily lives in SQLite so users can manually add seed expressions and review families.

Rules:

- Put `submit_ready` and `refine_candidate` expressions into the `alpha_templates` DB table.
- Put GA or research expressions that pass submission gates into `submittable_alphas`.
- Mark a family `ga_completed` after GA produces a submit-ready alpha from that family.
- Use `quality_tier` only for alphas that already pass submission gates: `high`, `medium`, or `low`.
- The family can be parameterized by fields/windows/wrappers without becoming a loose linear combination bucket.
- The template name describes the mechanism, not a metric target.
- The allowed fields are in the same economic family or dataset.
- The family has an obvious mutation surface for GA: windows, wrappers, decay, neutralization-compatible fields.

Manual template DB commands:

```powershell
C:\Users\USER\anaconda3\python.exe -m app template-add --family <name> --expression "<FASTEXPR>" --rationale "<why>"
C:\Users\USER\anaconda3\python.exe -m app template-list
C:\Users\USER\anaconda3\python.exe -m app submittable-list
```

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
