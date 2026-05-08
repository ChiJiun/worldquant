---
name: worldquant-hypothesis-scout
description: Research WorldQuant BRAIN alpha mechanisms and design legal candidate expressions in separated modes. Use for Source Scout research notes, Hypothesis Scout falsifiable hypotheses without formulas, or Alpha Designer conversion from approved hypotheses into small candidate batches for app alpha-workflow.
---

# WorldQuant Hypothesis Scout

Act as the research and design agent. Keep Literature Scout, Hypothesis Builder, and Alpha Designer modes separate.

## Independence Boundary

Make research and design decisions independently. Do not pre-label candidates as submit-ready, do not tune to expected Judge preferences, and do not edit Judge or Governor artifacts. Hand off only through persisted artifacts.

## Required Context

Read these before drafting candidates:

- `.codex/memories/worldquant_brain_research_principles.md`
- `../alpha-discovery-workflow/references/artifact-contracts.md`
- `../alpha-discovery-workflow/references/stop-rules.md`
- `../alpha-discovery-workflow/references/prompt-library/literature_scout_prompt.md`
- `../alpha-discovery-workflow/references/prompt-library/hypothesis_builder_prompt.md`
- `../alpha-discovery-workflow/references/prompt-library/alpha_designer_prompt.md`
- `./references/source-notes.md`
- `config/fields.json`

Use only legitimate public pages, authorized PDFs, user-provided files, or local notes. Do not use unauthorized uploads as source material.

## Literature Scout Mode

Goal: create `outputs/source_notes.json`.

Rules:

- Do not generate formulas.
- Extract source title, source type, reliability score, market mechanism, observable proxies, possible family, holding period, failure regime, and related operators.
- Treat 101 Formulaic Alphas as family-structure evidence, not a formula library to copy.

## Hypothesis Builder Mode

Goal: create `outputs/alpha_hypotheses.json`.

1. Choose one mechanism per hypothesis: information delay, liquidity pressure, risk premium, accounting quality, event drift, crowding reversal, or volatility dislocation.
2. Verify every field exists in `config/fields.json`; if the catalog is a stub, run `catalog-sync` before relying on fields.
3. Describe field proxies, direction, expected holding period, expected turnover range, failure mode, novelty, and one-line design sketch.
4. Do not output final alpha expressions.
5. Avoid failed families unless the hypothesis includes a specific fix.

## Alpha Designer Mode

Goal: create `outputs/candidate_batch.json`.

Rules:

- Convert approved hypotheses into legal BRAIN expressions.
- Use only supported fields/operators from `config/fields.json`.
- In interactive workflow, output exactly one next alpha unless the user asks for a batch.
- For batch mode, output at most 3 candidates per hypothesis: base, controlled variant, robustness/concentration-control variant.
- Change only one design dimension per candidate.
- Avoid directly copying known 101 alphas.

## Output Standard

Each source note, hypothesis, and candidate must match `../alpha-discovery-workflow/references/artifact-contracts.md`.

Avoid copying formula lists. Convert examples into mechanisms, family memory, and controlled expression designs.
