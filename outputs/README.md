# outputs

Runtime API simulation artifacts.

The app writes:

- `outputs/runs/<run_id>/input.jsonl`
- `outputs/runs/<run_id>/results.jsonl`
- `outputs/runs/<run_id>/errors.jsonl`
- `outputs/runs/<run_id>/summary.json`
- `outputs/simulate_results.jsonl`
- `outputs/simulate_errors.jsonl`
- `outputs/final_alpha_recommendations.md`
- `outputs/submit_queue.csv`
- `outputs/correlation_report.md`

Runtime outputs are ignored by git. This README and the example file are tracked.

`outputs/final_alpha_recommendations.md` is the human-readable final recommendation report after the selection gate. It includes the candidate expression, IS metrics, economic meaning, selection reason, OS/overfit risk, and submitted-alpha correlation check.

The real report is ignored by git. Use `outputs/final_alpha_recommendations.example.md` as the tracked sanitized example.
