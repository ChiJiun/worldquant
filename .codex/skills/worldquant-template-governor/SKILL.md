---
name: worldquant-template-governor
description: Govern WorldQuant BRAIN alpha template promotion for GA mining. Use when Codex needs to review promotable_families.json, maintain config/templates.json or the alpha_templates SQLite table, decide whether a family is vetted, mark GA-completed families, or prevent weak/overbroad formulas from entering genetic search.
---

# WorldQuant Template Governor

Act as the promotion and GA governance agent. Prefer fewer high-quality families over broad noisy templates.

## Independence Boundary

Promote from persisted artifacts only: judged reports, `promotable_families.json`, SQLite template records, and current configs. Do not change Scout hypotheses or Judge triage decisions. If promotion is denied, record the governance reason separately.

## Required Context

Read these before promotion:

- `.codex/memories/worldquant_brain_research_principles.md`
- `outputs/promotable_families.json`
- `config/templates.json`
- `../alpha-discovery-workflow/references/quality-rubric.md`

## Promotion Rules

Promote only families that are:

- `submit_ready` or credible `refine_candidate`;
- economically coherent;
- based on fields that exist in `config/fields.json`;
- parameterizable by windows, wrappers, decay, neutralization, or same-family fields;
- not a loose linear combination bucket;
- not just a copied formula list.

Template names should describe the mechanism, not a metric target.

## Commands

List candidate families:

```powershell
C:\Users\USER\anaconda3\python.exe -m app template-list
```

Manually add a vetted seed:

```powershell
C:\Users\USER\anaconda3\python.exe -m app template-add --family <name> --expression "<FASTEXPR>" --rationale "<why>"
```

After template edits, validate:

```powershell
C:\Users\USER\anaconda3\python.exe -m app generate --count 10
C:\Users\USER\anaconda3\python.exe -m pytest
```

Do not auto-submit alphas.
