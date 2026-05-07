# Repo Map

Use these files for this workspace:

- `app/cli.py`: command entry point. `search` and `mine` run GA/MCTS through `AlphaPipeline`.
- `app/api/clients.py`: WorldQuant BRAIN login, simulate, poll, fetch result, and mock client.
- `app/templates.py`: template instantiation and GA mutation/crossover support.
- `app/search.py`: `GeneticSearchEngine` and MCTS skeleton.
- `app/pipeline/runner.py`: end-to-end candidate processing, quality gate, simulation, scoring, storage.
- `app/scoring.py`: reward and high/medium/low quality classifier.
- `app/storage.py`: SQLite persistence, CSV outputs, best alpha export, dashboard.
- `app/quality.py`: pre-simulation expression filters.
- `config/fields.json`: available fields, wrappers, groups, and decays.
- `config/templates.json`: vetted GA template families. This may be `{}` until good families are promoted.
- `.codex/skills/factor_backtest`: external Rule-of-8 multi-simulation skill from GRD-Chang/worldquant-skill.
- `.codex/skills/knowledge_base_search`: external knowledge-search skill from GRD-Chang/worldquant-skill. The upstream repo currently includes only the skill instructions, not the `Resources/` knowledge base referenced by the skill.

Default outputs:

- `outputs/run_summary.csv`
- `outputs/passed_alphas.csv`
- `outputs/failed_alphas.csv`
- `outputs/session_dashboard.md`
- `data/worldquant.db`

Useful environment variables:

- `WQ_DRY_RUN=true|false`
- `WQ_CLIENT_MODE=mock|requests|pyworldquant|auto`
- `WQ_STORAGE_PATH=data/name.db`
- `WQ_OUTPUT_DIR=outputs_name`
- `WQ_TEMPLATE_CONFIG=config/templates.json`
- `WQ_BATCH_SIZE`, `WQ_GENERATIONS`, `WQ_MINE_CYCLES`
