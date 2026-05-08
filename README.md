# WorldQuant Brain Alpha Workflow

這個 repo 是一套研究優先的 WorldQuant BRAIN alpha workflow。流程把「研究假設」、「模擬評審」、「模板治理」拆成三個獨立 agent，讓每個角色只根據已落地的檔案與資料庫紀錄做判斷，不互相改寫推理。

## Agent Workflow

1. `worldquant-hypothesis-scout`
   研究市場機制，讀取專案記憶與來源筆記，產生 `outputs/alpha_hypotheses.json`。

2. `worldquant-alpha-judge`
   執行 `app alpha-workflow`，模擬候選 alpha，並把結果追加到固定 output 檔案。

3. `worldquant-template-governor`
   讀取已評審 artifacts，決定哪些 alpha family 可以進 template / GA 流程。

三個 agent 不共享私下推理，只透過檔案與 SQLite 紀錄交接。

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
- `alpha_workflow_report.md`: Judge 累積 run report。
- `promotable_families.json`: 累積可供 Governor 審核的 family。
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
