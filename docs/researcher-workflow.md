# LLM Researcher Workflow

This document defines the next layer above the minimal API simulator. The goal is not to let an LLM freely generate alphas. The goal is to make the LLM perform disciplined researcher behavior while deterministic tools handle simulation and result capture.

Current repo priority remains stable BRAIN API simulation plus deterministic research memory:

```text
data/candidates.jsonl -> python -m app simulate -> outputs/runs/<run_id>/ -> research/
```

Only add this researcher layer after live simulate is reliable.

## Core Principle

The LLM replaces a junior quantitative researcher's workflow, not the backtest system and not market validation.

The loop is:

```text
market mechanism hypothesis
-> observable proxy
-> alpha family
-> one design change
-> simulation
-> failure attribution
-> research memory update
-> stop / continue / validate / promote
```

## Responsibilities

LLM researcher owns:

- market-mechanism reasoning
- hypothesis generation
- expression design
- result interpretation
- one-step experiment planning
- memory summarization

Python tools own:

- login
- BRAIN simulation submission
- polling
- result parsing
- artifact writing
- deterministic validation

## Researcher Modes

Use one researcher with internal modes. Do not start with multiple independent agents.

### 1. Literature Scout

Find research-backed market mechanisms. Do not output alpha expressions.

Output:

```json
{
  "mechanism": "long-horizon return z-score reversal",
  "economic_story": "Stocks with extreme long-horizon return deviations may revert.",
  "observable_proxy": ["returns", "ts_mean", "ts_std_dev"],
  "possible_failure": ["weight_concentration", "sub_universe_fail"]
}
```

### 2. Hypothesis Builder

Convert research notes and memory into falsifiable hypotheses. Do not output final expressions.

Each hypothesis must include:

- family
- mechanism
- observable proxy
- expected direction
- expected horizon
- expected failure modes
- difference from tested families

### 3. Alpha Designer

Convert one approved hypothesis into exactly one BRAIN expression.

Rules:

- output exactly one expression
- change only one design dimension
- preserve the family mechanism
- do not use unsupported fields or operators
- do not use `rank()` if the family depends on amplitude unless reflection asks for it
- do not add filters unless a known bottleneck requires them

### 4. Result Reflector

Analyze the latest simulation result and decide exactly one next action.

Reflection checklist:

1. What changed in the expression?
2. What improved versus parent?
3. What worsened versus parent?
4. What is the dominant bottleneck?
5. What is the likely causal reason?
6. Should the family continue, stop, validate, revert, or promote?
7. What is the next single action?

### 5. Template Governor

Promote only robust, interpretable families into a template/search layer.

Do not promote if:

- improvements are cosmetic
- every variant fails the same bottleneck
- the family depends on unsupported operators
- yearly or sub-universe behavior is unstable with no fix

## Research Policies

### Exploration

If a family is unproven:

- test at most one alpha per run
- look for any signal in Sharpe, Fitness, Returns, or stable behavior
- record all invalid and failed directions

### Development

If a family has promising results:

- perform one-dimensional tuning only
- prefer interpretable parameters
- do not change lookback, decay, power, normalization, and filters all at once

### Candidate Validation

If Fitness > 1.2 and Turnover < 40:

- stop blind formula tuning
- check weight concentration
- check sub-universe Sharpe
- check self-correlation
- check out-of-sample robustness when available

### Stop Rule

Stop a family if:

- five consecutive variants do not improve Fitness meaningfully
- the same dominant failure repeats three times
- Sharpe, Returns, Turnover, and Drawdown only trade off with no net improvement
- platform/operator errors show the idea cannot be expressed reliably

## Failure Taxonomy

Use standard labels:

- `turnover_too_high`
- `returns_too_low`
- `sharpe_too_low`
- `drawdown_too_high`
- `weight_concentration`
- `sub_universe_fail`
- `self_corr_fail`
- `signal_amplitude_destroyed`
- `over_smoothing`
- `hard_filter_destroyed_returns`
- `direction_wrong`
- `operator_invalid`
- `unit_incompatible`
- `platform_timeout`
- `platform_auth_error`

## Current Artifacts

The deterministic recorder maintains:

```text
research/family_memory.json
research/experiment_decisions.jsonl
research/failure_taxonomy.json
research/passed_alphas.csv
research/failed_alphas.csv
research/best_alphas.txt
```

Use JSONL for append-only logs and JSON for current state snapshots. Reusable lessons live inside `family_memory.json` to avoid creating extra per-round files.

## Main Researcher Prompt Core

```text
You are WorldQuant Researcher Agent.

You replace a junior quantitative researcher in the alpha discovery loop.

You do not randomly generate formulas.
You work like a disciplined researcher:

1. Start from market mechanisms, not formulas.
2. Organize ideas by alpha family.
3. Generate falsifiable hypotheses.
4. Convert one hypothesis into one valid BRAIN expression.
5. Change only one design dimension per experiment.
6. After simulation, compare the result with parent, family best, and global best.
7. Diagnose the bottleneck before proposing the next experiment.
8. Record every failure and do not repeat failed directions.
9. If a candidate has Fitness > 1.2 and Turnover < 40, prioritize validation.
10. Promote only robust and interpretable families into templates.

Allowed fields:
open, high, low, close, volume, vwap, returns.

Never use unsupported operators.
Never copy public alpha formulas directly.
Output machine-readable JSON plus a short human summary.
```

## Current Integration Boundary

Do not implement this as autonomous formula generation yet.

The next engineering milestone is:

1. stabilize live `python -m app simulate`
2. improve timeout and error classification
3. add parent-vs-child result attribution
4. add deterministic validation check runner
5. add operator-aware one-action planning
