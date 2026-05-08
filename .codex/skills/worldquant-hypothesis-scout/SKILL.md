---
name: worldquant-hypothesis-scout
description: Research WorldQuant BRAIN alpha mechanisms and produce economically coherent hypothesis JSON. Use when Codex needs to act as the research agent, read alpha-design sources, map mechanisms to config/fields.json, draft 3-8 FASTEXPR candidates, or write outputs/alpha_hypotheses.json for app alpha-workflow.
---

# WorldQuant Hypothesis Scout

Act as the research agent. Produce hypotheses, not judged results.

## Independence Boundary

Make research decisions independently. Do not pre-label candidates as submit-ready, do not tune to expected Judge preferences, and do not edit Judge or Governor artifacts. Hand off only through `outputs/alpha_hypotheses.json`.

## Required Context

Read these before drafting candidates:

- `.codex/memories/worldquant_brain_research_principles.md`
- `../alpha-discovery-workflow/references/hypotheses-schema.md`
- `./references/source-notes.md`
- `config/fields.json`

Use only legitimate public pages, authorized PDFs, user-provided files, or local notes. Do not use unauthorized uploads as source material.

## Workflow

1. Choose one mechanism per hypothesis: information delay, liquidity pressure, risk premium, accounting quality, event drift, crowding reversal, or volatility dislocation.
2. Verify every field exists in `config/fields.json`; if the catalog is a stub, run `catalog-sync` before relying on fields.
3. Draft 3-8 FASTEXPR candidates from the same mechanism.
4. Vary only one or two controlled dimensions: window, normalization, decay, neutralization-compatible field, or event gate.
5. Write `outputs/alpha_hypotheses.json` using the schema reference.

## Output Standard

Each hypothesis must include:

- `id`
- `family`
- `source_urls`
- `economic_mechanism`
- `rationale`
- `expected_horizon`
- `failure_modes`
- `alphas[].expression`
- `alphas[].rationale`

Avoid copying formula lists. Convert examples into mechanisms, field families, and expression patterns.
