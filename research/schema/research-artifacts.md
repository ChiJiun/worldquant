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
| Submission tracker | `research/submissions/submitted_alphas.csv` | manual / submission workflow |
| Working notes | `research/notes/hypotheses.md` | researcher |

If a result should be shared, summarize it in `docs/` or place a sanitized miniature example under `research/examples/`.

## Submit Queue Gates

`python -m app select-alphas` writes `outputs/submit_queue.csv` only after:

1. selecting the best representative inside each high-correlation variant cluster,
2. rejecting winners whose expression fingerprint drifts away from the family/hypothesis economic meaning,
3. rejecting winners that are highly similar to already submitted alphas in `research/submissions/submitted_alphas.csv`.

Submitted alpha rows should include at least `alpha_id` and `expression`. Optional metric columns such as `sharpe`, `fitness`, `returns`, `drawdown`, and `turnover` improve metric-proxy similarity checks.
