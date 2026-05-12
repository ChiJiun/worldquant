---
name: worldquant-researcher-workflow
description: "Run disciplined WorldQuant BRAIN alpha research workflows. Use when Codex should act like a quantitative researcher: read research memory, find market mechanisms, design exactly one alpha experiment, run or prepare BRAIN simulation, parse artifacts, reflect on bottlenecks, update family memory, decide stop/continue/validate/promote, or maintain the repo's researcher workflow."
---

# WorldQuant Researcher Workflow

## Invocation

Use the skill command with an explicit mode when you want to force a loop:

```text
$worldquant-researcher-workflow pass-alpha-search
$worldquant-researcher-workflow pass-alpha-improvement
$worldquant-researcher-workflow literature-scout
$worldquant-researcher-workflow hypothesis-builder
$worldquant-researcher-workflow alpha-designer
$worldquant-researcher-workflow result-reflector
$worldquant-researcher-workflow template-governor
```

If no mode is provided, infer the mode from research memory and the latest artifacts.
If the explicit command and the memory state conflict, follow the explicit command unless it would violate a hard stop condition.

## Core Rule

Replace the junior researcher behavior, not the backtest system.

The LLM owns research judgment:

```text
market mechanism -> observable proxy -> alpha family -> one design change
-> simulate -> failure attribution -> memory update -> stop / continue / validate
```

Python and BRAIN own deterministic work:

```text
candidate IO -> simulation submit/poll/result -> metrics parsing -> artifacts
```

## Required State Read

Before proposing any alpha, read the available state:

- `research/state/family_memory.json`
- `research/logs/experiment_decisions.jsonl`
- `research/state/best_alphas.txt`
- `research/logs/passed_alphas.csv`
- `research/logs/failed_alphas.csv`
- `outputs/simulate_results.jsonl`
- `outputs/simulate_errors.jsonl`
- `data/candidates.jsonl`
- `config/fields.json`

If `research/` is missing, run:

```powershell
C:\Users\USER\anaconda3\python.exe -m app init-research
```

## One-Round Workflow

The workflow has two loops:

- `pass_alpha_search_loop`: search for the first candidate that can plausibly pass validation.
- `pass_alpha_improvement_loop`: improve an already pass-worthy candidate until it is ready to submit.

Perform one loop at a time.

## Loop Policy

- In `pass_alpha_search_loop`, keep proposing new families until one family produces a pass-worthy candidate or the family is abandoned.
- If a family is abandoned, write that outcome into research memory and immediately continue searching with a new family.
- In `pass_alpha_improvement_loop`, stay on the same family and change only one design dimension at a time.
- If the pass-worthy family can no longer improve meaningfully, freeze the best candidate for that family and stop tuning that family.
- The overall workflow stops only when a pass-worthy candidate is finalized, the user stops it, or the invocation safety limit is reached.

1. Diagnose current state.
   - Identify best global candidate, best family candidate, recent failures, and stopped families.
   - If any candidate has `Fitness > 1.2` and `Turnover < 40`, prioritize validation over more tuning.
   - Once a family has a pass-worthy candidate, stay in `pass_alpha_improvement_loop` until validation blocks clear or the family is stopped.

2. Choose exactly one mode:
   - `literature_scout`: find mechanism, no formula.
   - `hypothesis_builder`: produce falsifiable family hypothesis, no formula.
   - `alpha_designer`: produce exactly one expression.
   - `result_reflector`: analyze latest result and choose one next action.
   - `template_governor`: promote only robust families into templates.

3. For alpha design, obey hard constraints:
   - Output exactly one alpha.
   - Change only one design dimension from the parent.
   - Preserve the family mechanism.
   - Use only supported fields/operators from `config/fields.json`.
   - Do not copy public formulas directly.
   - Do not use `rank()` when amplitude is the edge unless prior reflection explicitly asks for it.
   - Do not add filters unless the dominant bottleneck justifies it.

4. Write or update one candidate in `data/candidates.jsonl`.
   Include:
   - `candidate_id`
   - `family`
   - `expression`
   - `parent_candidate_id`
   - `changed_dimension`
   - `notes`

5. Run at most one simulation unless the user explicitly asks for a batch:

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate --limit 1 --current-run
```

6. Read new artifacts from `outputs/current_run/` and `research/`.

7. Reflect with the taxonomy in `references/research-policy.md`.
   Decide exactly one next action:
   - `test_formula`
   - `validate_checks`
   - `stop_family`
   - `promote_template`

8. Before recommending submission, run the selection gate:
   - select the best representative inside each high-correlation variant cluster
   - verify the candidate still preserves the family/hypothesis economic meaning
   - compare against `research/submissions/submitted_alphas.csv`
   - only use `outputs/submit_queue.csv` as the recommended submission list

## Artifact Discipline

Do not create a new file or directory for every research step.

Use these fixed files/directories:

- `data/candidates.jsonl`: overwrite with the next single candidate.
- `outputs/current_run/`: overwrite the latest simulation snapshot.
- `outputs/simulate_results.jsonl`: append cumulative live results.
- `outputs/simulate_errors.jsonl`: append cumulative errors.
- `research/state/family_memory.json`: current research memory.
- `research/logs/experiment_decisions.jsonl`: append decisions.
- `research/logs/passed_alphas.csv` and `research/logs/failed_alphas.csv`: append candidate classification.
- `research/state/best_alphas.txt`: overwrite best summary.
- `research/submissions/submitted_alphas.csv`: local submitted-alpha registry used to block high-correlation resubmissions.
- `outputs/submit_queue.csv`: final recommended submission queue after variant, economic-meaning, and submitted-correlation gates.

Do not create ad hoc Markdown reports, extra analysis files, new prompt files, or per-round notes unless the user explicitly asks.

Validation commands should print to stdout by default. Use `--write-artifact` only when the user explicitly asks to persist validation reports.

## Memory Discipline

When an experiment teaches something reusable, write it into `research/state/family_memory.json` instead of creating a new file.

Useful lessons include:

- a one-change experiment materially improved or worsened Sharpe, Fitness, turnover, drawdown, or sub-universe checks
- a design direction repeatedly causes the same failure
- a family reaches a stop rule
- a candidate reaches submit-worthy validation

Keep lessons compact and action-oriented: what changed, what improved/worsened, and how the next researcher should use it.

## Stop Condition

Do not stop the workflow just because one experiment finished.

Continue the loop until one of these is true:

- A candidate is submit-worthy: platform checks are acceptable, Fitness and Sharpe are near or above submission thresholds, turnover is acceptable, weight concentration passes, sub-universe Sharpe passes, and self-correlation is not blocking.
- The family stop rule triggers: five consecutive variants without meaningful improvement or three repeated dominant failures.
- The user explicitly stops the workflow.
- A safety limit for the current invocation is reached; in that case, report the current best candidate and the exact next action, but do not call the research complete.

When a candidate improves but is not submit-worthy, output `next_action.type = "test_formula"` and keep the family in development.

## Current Best-Family Heuristic

For long-horizon return z-score reversal, remember the known conclusion unless artifacts contradict it:

```text
signed_power(
  -ts_decay_linear(((returns - ts_mean(returns, 120)) / (1 + ts_std_dev(returns, 120))), 90),
  0.95
)
```

If `power=0.975` raised returns but worsened Sharpe, Fitness, and Drawdown, stop power tuning and validate `power=0.95`.

## Output Format

When acting as the researcher agent, end with compact JSON plus a short summary:

```json
{
  "mode": "alpha_designer",
  "decision": "validate_best_candidate",
  "family": "long_horizon_return_zscore_reversal",
  "changed_dimension": "none_validation_first",
  "next_action": {
    "type": "validate_checks",
    "checks": ["weight_concentration", "sub_universe_sharpe", "self_corr", "os_performance"]
  }
}
```

Use `references/research-policy.md` for the full policy and failure taxonomy.
