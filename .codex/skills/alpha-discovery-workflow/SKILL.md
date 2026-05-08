---
name: alpha-discovery-workflow
description: Automate WorldQuant BRAIN alpha discovery from market-arbitrage hypothesis research through alpha expression drafting, simulation, result judgment, iterative refinement, and promotion of valuable alpha families into GA templates. Use when Codex is asked to find alphas, research market inefficiencies online, separate hypothesis-finding and alpha-judging roles, run or improve WorldQuant Brain simulate/GA scripts, classify alpha quality, or maintain config/templates.json for GA mining.
---

# Alpha Discovery Workflow

Use this skill as the operating procedure for this repo's alpha mining loop. Keep the professional research role, simulation triage role, and GA/template governance role separate even when one Codex instance executes all passes.

## Repo Map

Read `references/repo-map.md` before changing code or running commands.
Read `references/quality-rubric.md` before judging simulated alphas or changing thresholds.
Read `references/artifact-contracts.md` before changing workflow artifacts.
Read `references/failure-taxonomy.md` before classifying failures.
Read `references/stop-rules.md` before proposing follow-up experiments.
Read `.codex/memories/worldquant_brain_research_principles.md` before acting as Hypothesis Scout when the file exists.
Use `worldquant-hypothesis-scout` for Literature Scout, Hypothesis Builder, and Alpha Designer modes.
Use `worldquant-alpha-judge` for Simulation Runner / Alpha Judge and Result Reflector modes.
Use `worldquant-template-governor` for template promotion and GA family governance.

Agent independence rule: each mode makes its own decision from persisted artifacts, not from another mode's private reasoning. Literature Scout writes source notes, Hypothesis Builder writes hypotheses without formulas, Alpha Designer writes candidates without judging them, Alpha Judge records metrics, Result Reflector decides the next experiment, and Governor promotes only from judged artifacts. If a later mode disagrees, record a separate decision instead of rewriting the prior rationale.

Primary tool command:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\candidate_batch.json --promote
```

Hypothesis Scout writes `outputs/alpha_hypotheses.json` without formulas. Alpha Designer then writes `outputs/candidate_batch.json`, which is the expression input to the tool. The app also accepts the legacy `hypotheses[].alphas[].expression` shape for backward compatibility.

Other local commands:

```powershell
C:\Users\USER\anaconda3\python.exe -m app catalog-sync --output config\fields.json
C:\Users\USER\anaconda3\python.exe -m app login-check
C:\Users\USER\anaconda3\python.exe -m app generate --count 10
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
C:\Users\USER\anaconda3\python.exe -m app mine --cycles 20 --sleep-seconds 5
C:\Users\USER\anaconda3\python.exe -m app dashboard --limit 10
```

## Mode Split

### 1. Literature Scout

Goal: find reliable research sources and extract market mechanisms, observable proxies, expected regimes, and family ideas. Do not generate formulas.

Output: `outputs/source_notes.json`.

Prompt: `references/prompt-library/literature_scout_prompt.md`.

### 2. Hypothesis Builder

Goal: convert sources and family memory into falsifiable alpha hypotheses. Do not generate final alpha expressions.

Procedure:

1. Read `outputs/source_notes.json`, `outputs/family_memory.json`, prior summaries, and config.
2. Produce hypotheses with mechanism, allowed proxies, expected effect, main risk, and next design hint.
3. Avoid repeating failed families unless a specific fix is proposed.
4. Write `outputs/alpha_hypotheses.json`.

Prompt: `references/prompt-library/hypothesis_builder_prompt.md`.

### 3. Alpha Designer

Goal: convert approved hypotheses into a small number of legal, testable BRAIN expressions. Do not judge results.

Rules:

- Use only supported fields/operators from `config/fields.json`.
- Change no more than one design dimension per candidate.
- In interactive workflows, output exactly one next alpha unless the user asks for a batch.
- Write `outputs/candidate_batch.json`.

Prompt: `references/prompt-library/alpha_designer_prompt.md`.

### 4. Simulation Runner / Alpha Judge

Goal: decide whether simulated results are submit-ready, improvement candidates, or rejects.

Procedure:

1. Simulate the scout's candidates with the repo's Brain client or mock client when credentials/network are unavailable.
2. Inspect `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `margin`, `checks_failed`, stage metrics, and behavior similarity.
3. Assign `triage_decision` and `quality_tier` using `references/quality-rubric.md`.
4. Decide:
   - `submit_ready`: already passes WorldQuant submission gates.
   - `refine_candidate`: not submit-ready, but close enough and economically coherent enough to improve.
   - `reject`: failed checks, weak economics, duplicate behavior, or too far from submission.
5. Record standardized failure types from `references/failure-taxonomy.md`.
6. Run `python -m app alpha-workflow --hypotheses outputs/candidate_batch.json --promote` for the deterministic simulate/judge/report pass.

Prompt: `references/prompt-library/alpha_judge_prompt.md`.

### 5. Result Reflector

Goal: compare the latest result against its parent and decide exactly one next experiment or stop decision.

Rules:

- Identify the dominant bottleneck.
- Do not suggest cosmetic parameter changes.
- If a family shows diminishing returns, stop the family.
- If Fitness > 1.2 and Turnover < 40%, check weight concentration, sub-universe Sharpe, and self-correlation before more formula tuning.
- Write `outputs/candidate_result.json`, `outputs/experiment_decisions.json`, and update `outputs/next_experiment.json`.

Prompt: `references/prompt-library/result_reflector_prompt.md`.

### 6. Family Memory / Template Governor

Goal: update family memory and decide whether a family should enter templates / GA search. Do not invent new alphas.

Prompt: `references/prompt-library/template_governor_prompt.md`.

If the user explicitly requests parallel agents, delegate independent modes as separate agents. Otherwise run all modes locally and keep their persisted outputs separate.

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
- At least two variants should have promising results before family promotion unless the user explicitly overrides.
- Do not promote if all variants fail the same dominant bottleneck.

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

## Guardrails

- Do not auto-submit alphas; stop at simulation, quality tiering, and template promotion unless the user explicitly asks for submission.
- Do not add garbage templates to make GA run. Empty templates are better than broad, unvalidated families.
- Do not optimize only for Sharpe. Penalize failed checks, excessive turnover, unstable stage metrics, high behavior similarity, and weak economics.
- Keep changes repo-local unless the user explicitly authorizes external paths.
