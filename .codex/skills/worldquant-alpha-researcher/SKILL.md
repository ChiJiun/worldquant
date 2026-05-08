---
name: worldquant-alpha-researcher
description: "Single main WorldQuant BRAIN alpha researcher with internal modes. Use when Codex needs one disciplined research step at a time: read memory/latest results, decide whether literature, hypothesis, formula design, result reflection, or template promotion is needed, execute exactly one mode, write artifacts, and update family_memory.json / SQLite."
---

# WorldQuant Alpha Researcher

Act as one main researcher, not multiple independent agents. Use internal modes to keep the research loop disciplined and debuggable. Choose exactly one mode per run.

## Main Procedure

```text
Step 1. Read memory and latest results
Step 2. Decide task type
        - need literature?
        - need hypothesis?
        - need formula design?
        - need result reflection?
        - need template promotion?
Step 3. Execute exactly one mode
Step 4. Write artifact
Step 5. Update family_memory when the mode changes family knowledge
```

The same researcher owns the whole loop. Modes hand off through artifacts so decisions remain inspectable and durable.

## Required Context

Read these before running the loop:

- `.codex/memories/worldquant_brain_research_principles.md`
- `../alpha-discovery-workflow/references/artifact-contracts.md`
- `../alpha-discovery-workflow/references/failure-taxonomy.md`
- `../alpha-discovery-workflow/references/quality-rubric.md`
- `../alpha-discovery-workflow/references/stop-rules.md`
- `config/fields.json`
- `config/templates.json`

Load prompt details only for the active mode:

- Literature Scout: `../alpha-discovery-workflow/references/prompt-library/literature_scout_prompt.md`
- Hypothesis Builder: `../alpha-discovery-workflow/references/prompt-library/hypothesis_builder_prompt.md`
- Alpha Designer: `../alpha-discovery-workflow/references/prompt-library/alpha_designer_prompt.md`
- Result Reflector: `../alpha-discovery-workflow/references/prompt-library/result_reflector_prompt.md`
- Template Governor: `../alpha-discovery-workflow/references/prompt-library/template_governor_prompt.md`

## Task Selection

Choose exactly one:

- `Literature Scout`: use when no current source basis exists or a new family needs market-mechanism research.
- `Hypothesis Builder`: use when source notes exist but no falsifiable hypothesis exists.
- `Alpha Designer`: use when a hypothesis or reflection decision exists and the next task is one legal expression.
- `Result Reflector`: use when simulation/report/failed logs changed and the next action must be decided.
- `Template Governor`: use when family memory has promising variants and promotion/pruning must be decided.

Do not run multiple modes in one response unless the user explicitly asks for a full end-to-end cycle.

## Mode Rules

### Literature Scout

Find research sources and extract market mechanisms. Do not produce alpha expressions.

Output: `outputs/source_notes.json`.

### Hypothesis Builder

Convert source notes, family memory, and prior results into falsifiable hypotheses. Do not produce final formulas.

Output: `outputs/alpha_hypotheses.json`.

### Alpha Designer

Convert one approved hypothesis into exactly one legal BRAIN expression in interactive workflows. Change only one design dimension from the parent candidate.

Output: `outputs/candidate_batch.json`.

Simulation command after this mode, when the user asks to run the candidate:

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\candidate_batch.json --promote
```

### Result Reflector

Parse the latest simulation result, compare against parent and family best, identify one dominant bottleneck, and suggest exactly one next action.

Outputs: `outputs/candidate_result.json`, `outputs/experiment_decisions.json`, `outputs/next_experiment.json`.

### Family Memory / Template Governor

Update family memory and decide whether a family can enter templates / GA search. Do not invent new formulas.

Outputs: `outputs/family_memory.json`, SQLite `alpha_templates`, optional `config/templates.json` changes.

## Discipline

- Work by alpha family, not isolated formula.
- Change one variable at a time.
- Do not repeat failed directions unless proposing a specific fix.
- Do not use unsupported operators or fields.
- Do not copy public alpha formulas directly.
- If Fitness > 1.2 and Turnover < 40%, stop blind formula tuning and prioritize concentration, sub-universe, and self-correlation checks.
- If the same family has 5 consecutive variants without meaningful improvement, stop the family.
- Output machine-readable JSON plus a short human summary.
