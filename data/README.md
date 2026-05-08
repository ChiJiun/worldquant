# data

Human/LLM editable input files.

Use `data/candidates.jsonl` for live work. One JSON object per line:

```json
{"candidate_id":"A_manual_001","family":"api_smoke","expression":"rank(close)","notes":"manual test"}
```

`data/candidates.example.jsonl` is tracked as a template. Runtime candidate files are ignored by git.
