# WorldQuant Brain Alpha Workflow

這個 repo 是一套研究優先的 WorldQuant BRAIN alpha workflow。流程把「研究假設」、「模擬評審」、「模板治理」拆成三個獨立 agent，讓每個角色只根據已落地的檔案與資料庫紀錄做判斷，不互相改寫推理。

## Agent Workflow

1. Literature Scout
   查資料並抽取可測市場機制，產生 `outputs/source_notes.json`。不能產生 alpha 公式。

2. Hypothesis Builder
   把來源與 family memory 轉成可證偽假設，產生 `outputs/alpha_hypotheses.json`。不能產生 final expression。

3. Alpha Designer
   把單一假設轉成合法 BRAIN expression，產生 `outputs/candidate_batch.json`。互動流程下一次只輸出一條 alpha。

4. Simulation Runner / Alpha Judge
   執行 `app alpha-workflow`，模擬候選 alpha，並把結果追加到固定 output 檔案。

5. Result Reflector
   比較 latest / parent / family best，分類失敗原因，決定下一個單一實驗或停止。

6. Family Memory / Template Governor
   更新 `family_memory.json`，並決定哪些 alpha family 可以進 template / GA 流程。

各 mode 不共享私下推理，只透過檔案與 SQLite 紀錄交接。

## 專案記憶

WorldQuant / alpha 設計相關記憶放在專案內：

```text
.codex/memories/worldquant_brain_research_principles.md
```

這份記憶刻意不放在全域 Codex memory，避免本專案的 WorldQuant 假設污染其他專案，也確保 repo 自己帶著完整研究脈絡。

## 核心目錄

```text
.codex/
```

Codex agent 指令、角色 skill、專案記憶。Python runtime 不會 import 這個目錄。

```text
config/
```

可編輯設定：

- `fields.json`: BRAIN fields/operators catalog。
- `templates.json`: vetted GA template families。

```text
data/
```

SQLite runtime 狀態，預設是 `data/worldquant.db`。儲存 candidates、metrics、hypotheses、templates、submittable alphas。

```text
outputs/
```

Agent 交接 artifacts 與報告。約定是每種類型一個固定檔案，跨 workflow run 持續更新：

- `alpha_hypotheses.json`: Scout 當前 hypothesis batch。
- `source_notes.json`: Literature Scout 的來源與 market mechanism 摘要。
- `candidate_batch.json`: Alpha Designer 產生的合法 expression batch。
- `candidate_result.json`: Judge/Reflector 的結構化單候選結果。
- `alpha_workflow_report.md`: Judge 累積 run report。
- `promotable_families.json`: 累積可供 Governor 審核的 family。
- `family_memory.json`: family 層級的有效/無效結論與下一步。
- `experiment_decisions.json`: Reflector 的決策紀錄。
- `next_experiment.json`: 互動流程下一個單一實驗。
- `failure_taxonomy.csv`: 標準化失敗原因。
- `operator_errors.json`: operator / unit 錯誤紀錄。
- `run_summary.csv`: 累積 simulation summary。
- `passed_alphas.csv`: 累積 submit-ready alphas。
- `failed_alphas.csv`: 累積失敗紀錄。
- `session_dashboard.md`: 目前 dashboard snapshot。
- `best_alphas.txt`: 累積 best alpha log。

```text
logs/
```

Runtime logs，用於 debug login、simulation、pipeline error。

```text
scripts/
```

PowerShell 自動化輔助腳本。Python app 核心流程不依賴它們。

## 主要命令

同步 fields/operators：

```powershell
C:\Users\USER\anaconda3\python.exe -m app catalog-sync --output config\fields.json
```

執行 hypothesis 到 simulation / triage 的研究 workflow：

```powershell
C:\Users\USER\anaconda3\python.exe -m app alpha-workflow --hypotheses outputs\alpha_hypotheses.json --promote
```

查看 template 與可提交 alpha：

```powershell
C:\Users\USER\anaconda3\python.exe -m app template-list
C:\Users\USER\anaconda3\python.exe -m app submittable-list
```

執行 GA search：

```powershell
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
```

跑測試：

```powershell
C:\Users\USER\anaconda3\python.exe -m pytest
```

## `pyproject.toml` 的用途

`pyproject.toml` 是 Python 專案設定檔，不是 workflow 資料。它告訴 Python 工具：

- 這個 package 怎麼 build / install；
- package 名稱與 Python 版本需求；
- runtime dependencies，例如 `numpy`、`pandas`、`requests`；
- 哪些 module 屬於這個 project；
- pytest 預設從哪個目錄找測試。

簡單說，它是 tooling metadata，負責 packaging、dependency resolution、editable install、test discovery。

## Artifact Contracts

詳細 schema 在：

```text
.codex/skills/alpha-discovery-workflow/references/artifact-contracts.md
```

核心資料流：

```text
source_notes.json
  -> alpha_hypotheses.json
  -> candidate_batch.json
  -> run_summary.csv / candidate_result.json
  -> experiment_decisions.json / next_experiment.json
  -> family_memory.json
  -> templates.json / GA search
```

重要規則：

- Literature Scout 只輸出 market mechanism，不輸出公式。
- Hypothesis Builder 只輸出可測假設，不輸出 final expression。
- Alpha Designer 才輸出 expression，且互動流程一次只輸出一條。
- Result Reflector 每次只決定一個 next action。

## Failure Taxonomy

標準 failure labels 在：

```text
.codex/skills/alpha-discovery-workflow/references/failure-taxonomy.md
```

常用類型：

- `turnover_too_high`
- `return_density_too_low`
- `weight_concentration`
- `sub_universe_fail`
- `self_corr_risk`
- `operator_invalid`
- `unit_incompatible`
- `signal_amplitude_destroyed`
- `over_smoothing`
- `hard_filter_destroyed_returns`
- `direction_wrong`
- `no_directional_edge`

Judge / Reflector 不能只看 Sharpe。BRAIN 類 Fitness 會同時受到 Sharpe、Returns、Turnover 和檢查項影響。

## Promotion Rules

Family 狀態建議：

- `candidate`: 有初步機制，但結果不足。
- `reserve`: 暫停但不刪除，等待新資料或新 operator。
- `promotable_family`: 至少兩個 promising variants，且失敗模式已知。
- `template_ready`: 可參數化進 `templates.json` 或 SQLite template table。
- `submit_candidate`: 已接近或通過提交檢查，優先做 concentration / sub-universe / self-corr validation。
- `pruned_family`: 同一瓶頸重複失敗或停止規則觸發。

不要 promote：

- 只靠 cosmetic parameter change 變好；
- 所有 variants 都卡同一 failure bottleneck；
- 依賴 unsupported operator；
- yearly behavior 不穩且沒有修法。

## Stop Rules

停止規則在：

```text
.codex/skills/alpha-discovery-workflow/references/stop-rules.md
```

重點：

- 同一 family 連續 5 次沒有 Fitness 提升至少 `0.05`，停止。
- 如果只是 Sharpe / Returns / Turnover 互相 trade-off，停止。
- 同一 dominant failure 重複 3 次，停止或換 family。
- Fitness > 1.2 且 Turnover < 40% 時，不再盲目優化公式，先檢查 weight concentration、sub-universe Sharpe、self-corr。

## Prompt Library

Prompt library 在：

```text
.codex/skills/alpha-discovery-workflow/references/prompt-library/
```

主要 prompt：

- `literature_scout_prompt.md`
- `hypothesis_builder_prompt.md`
- `alpha_designer_prompt.md`
- `alpha_judge_prompt.md`
- `result_reflector_prompt.md`
- `template_governor_prompt.md`
