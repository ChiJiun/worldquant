# Research Artifact Layout

Runtime artifacts are intentionally ignored by git.

| Artifact | Path | Owner |
| --- | --- | --- |
| Family memory | `research/state/family_memory.json` | recorder / researcher |
| Best summary | `research/state/best_alphas.txt` | recorder |
| Portfolio state | `research/state/portfolio.json` | selection / manual review |
| Decisions log | `research/logs/experiment_decisions.jsonl` | recorder |
| Passed alphas | `research/logs/passed_alphas.csv` | recorder |
| Failed alphas | `research/logs/failed_alphas.csv` | recorder |
| Validation reports | `research/logs/validation_reports.*` | validation command |
| Final selection state | `research/state/latest_final_selection_report.json` | selection finalize |
| Final selection history | `research/logs/final_selection_reports.jsonl` | selection finalize |
| Submission tracker | `research/submissions/submitted_alphas.csv` | manual / submission workflow |
| Correlation cache | `research/state/alpha_correlations.json` | `fetch-correlations` command |
| Working notes | `research/notes/hypotheses.md` | researcher |

If a result should be shared, summarize it in `docs/` or place a sanitized miniature example under `research/examples/`.

## Passed / Failed Alpha CSV Columns

`passed_alphas.csv` columns (`PASSED_FIELDS` in `app/research.py`): `recorded_at`, `candidate_id`, `family`, `expression`, `result_id`, `sharpe`, `fitness`, `returns`, `drawdown`, `turnover`, `decision`, `source`. `failed_alphas.csv` adds `dominant_bottleneck`, `error_type`, `error`.

`source` is `live` for results fetched from BRAIN and `mock` for rows written by `python -m app simulate --allow-mock` (the `MockBrainClient`); the same tag is stored in every `experiment_decisions.jsonl` row. `select-alphas` skips `source=mock` rows and reports how many it skipped as `mock_rows_skipped`. A CSV written before the column existed is upgraded in place on the next append: the header gains `source` and existing rows keep an empty value, which readers treat as `live`. `record-passed-alpha` always writes `live` because it requires a BRAIN alpha id.

## Submit Queue Gates

`python -m app select-alphas` writes `outputs/submit_queue.csv` only after:

1. selecting the best representative inside each high-correlation variant cluster,
2. rejecting winners whose expression fingerprint drifts away from the family/hypothesis economic meaning,
3. rejecting winners that are highly similar to already submitted alphas in `research/submissions/submitted_alphas.csv`.

Submitted alpha rows should include at least `alpha_id` and `expression`. When `research/state/alpha_correlations.json` holds a BRAIN self-correlation entry for a candidate, that platform number (threshold 0.7) is checked alongside the structural comparison against this CSV (threshold 0.85); either signal crossing its threshold blocks submission, platform first. The CSV also attaches the local record of the matching submitted alpha.

## Correlation Cache

`python -m app fetch-correlations` stores `{"version": 2, "updated_at": ..., "alphas": {alpha_id: {"self": {...}, "prod": {...}}}}`. Each entry keeps `max_correlation`, `min_correlation`, `record_count`, `records` (schema-zipped rows from BRAIN) and `fetched_at`. Pairwise clustering uses `|correlation|` from the `self` records; the submit gate uses the signed `max_correlation`. An entry whose `max_correlation` is `null` (written by `--allow-mock` smoke runs) is ignored by selection, has no `fetched_at` to report, and is refetched on the next live run. `prod` entries are stored for reference only. `correlation_report.md` prints the oldest `fetched_at` so a stale cache is visible.

A file whose `version` is not the current `CACHE_VERSION` (version 1 files may contain `0.0` values written by an early mock client) or that is not valid JSON loads as an empty cache with a warning in the log. Before the next write it is renamed to `alpha_correlations.json.v<old>` or `alpha_correlations.json.corrupt` (a counter is appended when that name exists) and the `fetch-correlations` report lists it as `previous_cache_backup`; nothing is overwritten.

Use `--finalize-run` to write the structured final state. Use `--clear-candidates` only after the current candidate input has already been simulated and selected. `passed_alphas.csv` remains cumulative because removing it would erase the candidate pool needed for future clustering.
