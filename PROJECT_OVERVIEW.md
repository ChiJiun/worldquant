# WorldQuant Brain Alpha Workflow

This repo is a research-first WorldQuant BRAIN alpha workflow.

Core loop:

1. A quant researcher agent searches papers, research notes, and market-structure evidence.
2. The agent writes market-arbitrage hypotheses and FASTEXPR candidates to `outputs/alpha_hypotheses.json`.
3. `app alpha-workflow` simulates candidates, records metrics, and triages each alpha:
   - `submit_ready`: already passes submission gates.
   - `refine_candidate`: economically coherent and close enough to improve.
   - `reject`: not worth continuing.
4. `submit_ready` and `refine_candidate` expressions are stored in the SQLite `alpha_templates` table for manual review or future GA work.
5. GA-generated families that reach submission gates are marked complete and recorded in `submittable_alphas`.

`quality_tier` is only for alphas that already pass submission gates:

- `high`: expert-level target, such as Sharpe >= 2.0 and Turnover < 40%.
- `medium`: strong pass, such as Sharpe >= 1.58 with acceptable turnover.
- `low`: still passes submission gates, but does not meet medium/high standards.

## Commands

Sync the WorldQuant BRAIN field/operator catalog after local `.env` credentials are valid:

```powershell
C:\Users\USER\anaconda3\python.exe -m app catalog-sync --output config\fields.json
```

Run the research workflow after a hypothesis JSON exists:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\alpha_hypotheses.json --promote
```

Manually manage template candidates:

```powershell
C:\Users\USER\anaconda3\python.exe -m app template-add --family <name> --expression "<FASTEXPR>" --rationale "<why>"
C:\Users\USER\anaconda3\python.exe -m app template-list
C:\Users\USER\anaconda3\python.exe -m app submittable-list
```

Run GA after vetted templates are available:

```powershell
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
```

Validate:

```powershell
C:\Users\USER\anaconda3\python.exe -m pytest
```

## Important Files

- `app/workflow.py`: hypothesis JSON -> simulate -> triage -> template/submittable DB.
- `app/storage.py`: SQLite tables and CSV outputs.
- `app/scoring.py`: submission gates, refinement triage, high/medium/low tiers.
- `app/catalog.py`: authenticated BRAIN catalog sync for data fields/operators.
- `app/pipeline/runner.py`: GA simulation path.
- `config/templates.json`: vetted GA template config; may be `{}`.
- `.codex/skills/alpha-discovery-workflow`: agent operating procedure.

Secrets and generated outputs are ignored by git:

- `.env`
- `data/`
- `outputs*/`
- `logs*/`
- `__pycache__/`
