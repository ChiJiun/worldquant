# /alpha-workflow

Use `$alpha-discovery-workflow` in `D:\Code\worldquant`.

Run the full autonomous workflow:

1. Search the web for current market-arbitrage or alpha hypotheses with economic reasoning.
2. Act as Hypothesis Scout and write `outputs/alpha_hypotheses.json` using `.codex/skills/alpha-discovery-workflow/references/hypotheses-schema.md`.
3. Act as Alpha Judge and run:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\alpha_hypotheses.json --promote
```

4. Read the generated report in `outputs/alpha_workflow_*.md`.
5. If `outputs/promotable_families.json` contains high-tier families, convert only those into vetted `config/templates.json` entries.
6. Run:

```powershell
C:\Users\USER\anaconda3\python.exe -m pytest
```

Do not auto-submit alphas. Keep all changes inside this repo unless explicitly authorized.
