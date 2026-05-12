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
