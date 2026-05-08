# WorldQuant BRAIN API Simulator

這個專案先砍到最小目標：穩定 WorldQuant BRAIN API simulate，並用 deterministic artifacts 支援研究員式 alpha loop。

目前不做 GA、不做自動 template promotion、不做多 agent workflow。LLM 的定位是替代人類研究員的研究行為：管理 family、假設、一次一個變因、結果反思與 validation decision；BRAIN simulation 和市場驗證仍由外部系統負責。

## 核心流程

```text
data/candidates.jsonl
  -> python -m app simulate
  -> outputs/runs/<run_id>/
  -> outputs/simulate_results.jsonl
  -> outputs/simulate_errors.jsonl
  -> research/family_memory.json
  -> research/experiment_decisions.jsonl
```

## 目錄

```text
app/
```

Python 程式。現在只保留：

- `config.py`: 讀 `.env` 與 simulation settings。
- `api/clients.py`: WorldQuant login / simulate / poll / result client。
- `simulator.py`: 讀候選、跑 simulate、寫 JSONL artifacts。
- `cli.py`: CLI entry point。

```text
data/
```

人工與 LLM 都可以寫入的輸入區。主要檔案：

- `data/candidates.jsonl`: 一行一條 candidate，JSONL 格式。

每行格式：

```json
{"candidate_id":"A_manual_001","family":"api_smoke","expression":"rank(close)","notes":"manual test"}
```

```text
outputs/
```

程式輸出區。主要檔案：

- `outputs/runs/<run_id>/input.jsonl`: 該次執行的輸入快照。
- `outputs/runs/<run_id>/results.jsonl`: 該次成功結果。
- `outputs/runs/<run_id>/errors.jsonl`: 該次錯誤。
- `outputs/runs/<run_id>/summary.json`: 該次摘要。
- `outputs/simulate_results.jsonl`: 跨 run 累積成功結果。
- `outputs/simulate_errors.jsonl`: 跨 run 累積錯誤。

```text
research/
```

研究員 layer 的狀態與記憶。這些檔案由 simulate 後的 recorder 更新，LLM 下一輪要先讀這裡：

- `research/family_memory.json`: family -> variants -> best candidate -> failure modes -> reusable lessons。
- `research/experiment_decisions.jsonl`: 每條結果的 bottleneck、decision、next action。
- `research/passed_alphas.csv`: 進入 validation 的候選。
- `research/failed_alphas.csv`: 未通過或平台錯誤的候選。
- `research/best_alphas.txt`: global best 與每個 family best 的短摘要。
- `research/failure_taxonomy.json`: 標準 failure labels。

```text
config/
```

保留 BRAIN fields/operators catalog。現在不依賴 template 設定。

```text
logs/
```

程式 log。

## 設定

建立本機 `.env`：

```powershell
Copy-Item .env.example .env
```

先用 mock 跑通本機流程：

```env
WQ_DRY_RUN=true
WQ_CLIENT_MODE=requests
```

要打 live API 時：

```env
WQ_DRY_RUN=false
WQ_CLIENT_MODE=requests
WQ_AUTH_MODE=auto
WQ_REQUEST_TIMEOUT_SECONDS=60
WQ_MAX_POLL_ATTEMPTS=120
WQ_POLL_INTERVAL_SECONDS=5.0
```

`WQ_REQUEST_TIMEOUT_SECONDS` 是單次 HTTP request timeout。  
`WQ_MAX_POLL_ATTEMPTS * WQ_POLL_INTERVAL_SECONDS` 是每條 simulation 最多等待時間。

## 命令

初始化可編輯資料檔：

```powershell
C:\Users\USER\anaconda3\python.exe -m app init-data
```

只初始化 researcher artifacts：

```powershell
C:\Users\USER\anaconda3\python.exe -m app init-research
```

檢查設定，不印出帳密：

```powershell
C:\Users\USER\anaconda3\python.exe -m app settings
```

檢查登入：

```powershell
C:\Users\USER\anaconda3\python.exe -m app login-check
```

跑 `data/candidates.jsonl`：

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate
```

研究 workflow 建議用固定輸出目錄，避免每輪新增 `outputs/runs/<run_id>/`：

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate --limit 1 --current-run
```

只跑一條 expression：

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate --expression "rank(close)" --family api_smoke
```

限制本次最多跑一條：

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate --limit 1
```

讀單一 alpha / result：

```powershell
C:\Users\USER\anaconda3\python.exe -m app result <alpha_or_result_id>
```

跑測試：

```powershell
C:\Users\USER\anaconda3\python.exe -m pytest
```

## 寫入規則

給 LLM 或人工追加候選時，只改 `data/candidates.jsonl`。

規則：

- 一行一個 JSON object。
- 必填 `expression`。
- 建議填 `candidate_id`、`family`、`notes`。
- 建議填 `parent_candidate_id`、`changed_dimension`，讓 reflection 可以追蹤「一次只改一個變因」。
- 不要把結果手寫進 `outputs/`，那裡由程式產生。
- 不要把帳密寫進任何 JSONL。

## Researcher Policy

LLM 只能做研究判斷，不直接替代回測或 validation。

硬規則：

- 從市場機制與 observable proxy 開始，不先亂湊公式。
- alpha 記憶單位是 `family -> hypothesis -> expression variants -> results -> failure modes`。
- 每輪只提交一條 alpha。
- 每條 alpha 只改一個 design dimension。
- 如果 `Fitness > 1.2` 且 `Turnover < 40%`，停止盲目調參，先進入 validation。
- 同一 family 連續 5 次沒有改善，標記為 stopped。
- 每個失敗都寫入 `research/failed_alphas.csv` 和 `research/experiment_decisions.jsonl`。
- workflow 不因單輪實驗完成而停止；只有找到有提交機會的 alpha、family stop rule 觸發、使用者要求停止，或本次執行安全上限到達時才停。
- 學到的 reusable lesson 寫進 `research/family_memory.json`，不要為每輪分析另開新檔。

## 下一步

接下來可以加：

- parent-vs-child metric attribution
- validation check runner
- operator-aware alpha designer
- template governor

研究員 layer 的設計規格先放在：

```text
docs/researcher-workflow.md
```

重點是讓 LLM 替代人類研究員的研究行為，而不是替代 BRAIN simulation 或市場驗證。
