---
name: worldquant-researcher-workflow
description: Run the disciplined WorldQuant BRAIN alpha research loop. Use when Claude should act as the quantitative researcher for this repo - read research memory, pick a loop or mode, design exactly one alpha experiment, run or prepare a BRAIN simulation, read the artifacts, attribute the result to the one changed dimension, update family memory, and decide stop / continue / validate / promote.
argument-hint: "[pass-alpha-search | pass-alpha-improvement | literature-scout | hypothesis-builder | alpha-designer | result-reflector | template-governor]"
---

# WorldQuant Researcher Workflow (Claude Code)

The same workflow exists for Codex under `.codex/skills/worldquant-researcher-workflow/`. Keep the two in sync when the loop changes; the shared policy, failure taxonomy and reflection JSON live in `docs/research-policy.md`.

## Invocation

`$ARGUMENTS` is the optional mode:

```text
/worldquant-researcher-workflow
/worldquant-researcher-workflow pass-alpha-search
/worldquant-researcher-workflow pass-alpha-improvement
/worldquant-researcher-workflow literature-scout
/worldquant-researcher-workflow hypothesis-builder
/worldquant-researcher-workflow alpha-designer
/worldquant-researcher-workflow result-reflector
/worldquant-researcher-workflow template-governor
```

With no mode, infer it from research memory and the latest artifacts (`python -m app research --mode auto` prints the deterministic view). If the explicit mode and the memory state conflict, follow the explicit mode unless it would violate a hard stop condition.

Run every command with the interpreter that has this project installed (`.venv\Scripts\python.exe -m app ...` here; README examples use the Anaconda interpreter). `python -m app` below means that interpreter.

## Safety

- `.env` holds the user's BRAIN credentials. Never read, print, copy or commit its values; `python -m app settings` shows only `has_username` / `has_password`.
- `simulate`, `login-check`, `result`, `fetch-correlations`, `validate-candidate --refresh` and `record-passed-alpha --fetch-metrics` talk to the live BRAIN API when `WQ_DRY_RUN=false`. Run them only because the user asked for this workflow to run; never inside tests or as a "quick check".
- `WQ_DRY_RUN=true` is the program default and what `.env.example` ships with. Under it every command uses `MockBrainClient`. Only three live-only calls are refused outright (`fetch-correlations` without `--allow-mock`, `record-passed-alpha --fetch-metrics`, `validate-candidate --refresh`); **`simulate` is not refused** and still appends mock results (`result_id=mock-...`, `raw.mode=mock`) to `research/logs/*` and `research/state/family_memory.json`, and `select-alphas` does not filter them out. Before step 5 run `python -m app settings` and confirm `dry_run=False` and `client_mode=requests`; if it says `dry_run=True`, stop and ask the user instead of simulating.
- Do not edit files under `research/state/` or `research/logs/` by hand; the recorder owns them. Hand-maintained files are `research/notes/` and `research/submissions/submitted_alphas.csv` (one row per real submission); manually verified alphas go through `python -m app record-passed-alpha`.

## Core Rule

Replace the junior researcher behavior, not the backtest system.

Claude owns research judgment:

```text
market mechanism -> observable proxy -> alpha family -> one design change
-> simulate -> failure attribution -> memory update -> stop / continue / validate
```

Python and BRAIN own deterministic work:

```text
candidate IO -> simulation submit/poll/result -> metrics parsing -> artifacts
-> attribution (python -m app attribute) -> validation (python -m app validate-candidate)
-> correlation gate (python -m app fetch-correlations / select-alphas)
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

If `research/` is missing, run `python -m app init-research`.

## Two Loops

- `pass_alpha_search_loop`: search for the first candidate that can plausibly pass validation. Keep proposing new families until one produces a pass-worthy candidate or is abandoned; write an abandoned family into memory and continue with a new one.
- `pass_alpha_improvement_loop`: stay on the pass-worthy family and change only one design dimension at a time. When the family can no longer improve meaningfully, freeze its best candidate and stop tuning it.

Perform one loop at a time. The overall workflow stops only when a pass-worthy candidate is finalized, the user stops it, or the invocation safety limit is reached.

## One-Round Workflow

1. **Diagnose current state.** Identify the global best, each family best, recent failures and stopped families. If any candidate has `Fitness > 1.2` and `Turnover < 40`, prioritize validation over more tuning. Once a family has a pass-worthy candidate, stay in `pass_alpha_improvement_loop` until validation blocks clear or the family is stopped.

2. **Choose exactly one mode** (definitions in `docs/research-policy.md`): `literature_scout`, `hypothesis_builder`, `alpha_designer`, `result_reflector`, `template_governor`.

3. **For alpha design, obey the hard constraints:**
   - Output exactly one alpha and change only one design dimension from the parent. A simulation-setting override counts as a dimension; do not change formula and settings in the same experiment unless the user asks.
   - Preserve the family mechanism. Use only fields/operators listed in `config/fields.json`. Do not copy public formulas directly.
   - Do not use `rank()` when amplitude is the edge unless prior reflection asks for it. Do not add filters unless the dominant bottleneck justifies it.

4. **Write or overwrite one candidate in `data/candidates.jsonl`** with `candidate_id`, `family`, `expression`, `parent_candidate_id`, `changed_dimension`, `notes`, and optionally `simulation_settings`. `parent_candidate_id` and `changed_dimension` are what make the parent comparison work: without them `attribute` and the recorder's `latest_vs_parent` report `no_parent_recorded` (family-best and global-best comparisons still run) and no family lesson is derived for the round.

   ```json
   {
     "candidate_id": "A_settings_001",
     "family": "cashflow_quality",
     "expression": "rank(cashflow / assets)",
     "parent_candidate_id": "A_settings_000",
     "changed_dimension": "truncation_0.08_to_0.05",
     "notes": "test tighter truncation only",
     "simulation_settings": {"truncation": 0.05}
   }
   ```

   Strategy settings never go into `.env`; it is for credentials, API paths, timeouts and local paths. Per-run overrides are also available on the CLI (`--decay`, `--delay`, `--truncation`, `--neutralization`, `--universe`, `--region`, `--instrument-type`, `--language`, `--pasteurization`, `--lookback`, `--max-trade`, `--max-position`); whichever you use, record it in `changed_dimension` and `notes`.

5. **Run at most one simulation** unless the user asks for a batch. Check the client mode first (see Safety): a dry-run simulate writes mock rows into the real research logs.

   ```powershell
   python -m app settings
   python -m app simulate --limit 1 --current-run
   ```

6. **Read the new artifacts** in `outputs/current_run/` and `research/`, then let Python do the arithmetic:
   - `python -m app attribute --candidate-id <id>` gives child-vs-parent, family-best and global-best deltas with a `verdict` and `next_action_hint`. The recorder already stored the same block as `latest_vs_parent` in `research/logs/experiment_decisions.jsonl`.
   - When platform checks are still PENDING, `python -m app validate-candidate --candidate-id <id> --refresh` re-fetches the alpha and its self-correlation (live client only). Pass `--result-id <alpha id>` when the same `candidate_id` was reused across families; the report carries a `warning` when that happened.

7. **Reflect** with the taxonomy in `docs/research-policy.md` and decide exactly one next action: `test_formula`, `validate_checks`, `stop_family` or `promote_template`.

8. **Before recommending submission, run the selection gate:**
   - `python -m app fetch-correlations` (live) to cache BRAIN self-correlation for the passed alphas; re-run with `--refresh` after new submissions.
   - `python -m app select-alphas` picks the best representative inside each high-correlation cluster, checks the family's economic meaning, and blocks alphas that BRAIN self-correlation (>= 0.7) or the structural proxy against `research/submissions/submitted_alphas.csv` (>= 0.85) says duplicate a submitted alpha. Only `outputs/submit_queue.csv` is the recommended list.
   - When the round is complete, `python -m app select-alphas --finalize-run --clear-candidates` writes `research/state/latest_final_selection_report.json` for the next invocation.

## Artifact Discipline

Do not create a new file or directory for every research step. Fixed paths:

- `data/candidates.jsonl`: overwrite with the next single candidate.
- `outputs/current_run/`: latest simulation snapshot; `outputs/simulate_results.jsonl` / `simulate_errors.jsonl`: cumulative.
- `research/state/family_memory.json`: current research memory and reusable lessons (do not create separate lesson files).
- `research/logs/experiment_decisions.jsonl`, `passed_alphas.csv`, `failed_alphas.csv`: append-only, written by the recorder.
- `research/state/best_alphas.txt`: overwritten best summary.
- `research/state/alpha_correlations.json`: BRAIN correlation cache.
- `research/submissions/submitted_alphas.csv`: local registry of submitted alphas; hand-maintained, add a row after each real submission (there is no CLI for it yet).
- `research/logs/final_selection_reports.jsonl`, `research/state/latest_final_selection_report.json`: written by `select-alphas --finalize-run`.
- `outputs/submit_queue.csv`, `outputs/final_alpha_recommendations.md`: selection output.

Manually verified alphas that never went through the recorder are added with `python -m app record-passed-alpha ...`, never by editing the CSV.

Do not create ad hoc Markdown reports, extra analysis files, new prompt files or per-round notes unless the user asks. Validation commands print to stdout; use `--write-artifact` only when asked to persist reports.

## Memory Discipline

When an experiment teaches something reusable, write it into `research/state/family_memory.json` lessons (the recorder derives one automatically when `parent_candidate_id` and `changed_dimension` are present). Keep lessons compact and action-oriented: what changed, what improved or worsened, how the next researcher should use it.

## Stop Condition

Continue the loop until one of these is true:

- A candidate is submit-worthy: platform checks acceptable, Fitness and Sharpe near or above submission thresholds, turnover acceptable, weight concentration and sub-universe Sharpe pass, self-correlation not blocking.
- The family stop rule triggers: five consecutive variants without meaningful improvement, or three repeated dominant failures.
- The user explicitly stops the workflow.
- The per-invocation safety limit is reached: report the current best candidate and the exact next action, and do not call the research complete.

When a candidate improves but is not submit-worthy, output `next_action.type = "test_formula"` and keep the family in development.

## Output Format

End with compact JSON plus a short summary:

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
