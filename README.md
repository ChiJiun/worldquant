# WorldQuant BRAIN API Simulator

這個專案先砍到最小目標：穩定 WorldQuant BRAIN API simulate。

目前不做 GA、不做 template promotion、不做多 agent workflow。先把登入、送出 alpha、poll、讀結果、落地 artifacts 做穩，再往上加研究流程。

## 核心流程

```text
data/candidates.jsonl
  -> python -m app simulate
  -> outputs/runs/<run_id>/
  -> outputs/simulate_results.jsonl
  -> outputs/simulate_errors.jsonl
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
- 不要把結果手寫進 `outputs/`，那裡由程式產生。
- 不要把帳密寫進任何 JSONL。

## 下一步

等 live simulate 穩定後，再加：

- result classifier
- failure taxonomy
- family memory
- hypothesis/design workflow
