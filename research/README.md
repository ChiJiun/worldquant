# research

Research files are split between tracked workflow metadata and ignored local runtime state.

Tracked files:

- `README.md`: this guide.
- `failure_taxonomy.json`: stable failure labels used by the recorder.
- `schema/`: optional field/schema documentation for research artifacts.
- `examples/`: small sanitized examples only.

Ignored local files:

- `state/family_memory.json`: current family memory, global best, reusable lessons.
- `state/best_alphas.txt`: human-readable best candidate summary.
- `state/portfolio.json`: local portfolio or champion pool state.
- `logs/experiment_decisions.jsonl`: append-only experiment decisions.
- `logs/passed_alphas.csv`: candidates that reached the validation gate.
- `logs/failed_alphas.csv`: failed candidates and platform errors.
- `logs/validation_reports.jsonl` and `logs/validation_reports.csv`: persisted validation reports.
- `submissions/submitted_alphas.csv`: local submission tracking.
- `notes/hypotheses.md`: working research notes, unless manually sanitized and moved into docs.

The app writes new artifacts into this layout by default. Legacy flat files in `research/` and archived files under `research/old/` are still readable as a fallback so old work is not stranded during migration.

`python -m app select-alphas` uses `submissions/submitted_alphas.csv` as a final gate. A passed alpha can enter `outputs/best_alphas.csv` as a variant winner, but it will not enter `outputs/submit_queue.csv` if it is too similar to an already submitted alpha or if its expression no longer matches the hypothesis economic meaning.

When a workflow round is complete, run `python -m app select-alphas --finalize-run --clear-candidates` to persist `state/latest_final_selection_report.json`, append `logs/final_selection_reports.jsonl`, and clear `data/candidates.jsonl` for the next design. Keep `logs/passed_alphas.csv`; it is cumulative selection memory, not disposable scratch output.
