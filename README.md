# WorldQuant BRAIN API Simulator

這個專案先砍到最小目標：穩定 WorldQuant BRAIN API simulate，並用 deterministic artifacts 支援研究員式 alpha loop。

目前不做 GA、不做自動 template promotion、不做多 agent workflow。LLM 的定位是替代人類研究員的研究行為：管理 family、假設、一次一個變因、結果反思與 validation decision；BRAIN simulation 和市場驗證仍由外部系統負責。

## 核心流程

```text
LLM researcher
  -> read research/state + research/logs + outputs
  -> design exactly one candidate in data/candidates.jsonl
  -> python -m app simulate --limit 1 --current-run
  -> BRAIN API submit / poll / result parsing
  -> outputs/current_run + cumulative outputs/*.jsonl
  -> research/state + research/logs
  -> LLM reflects and decides stop / continue / validate / select
```

## Workflow 總覽

這個 repo 把研究判斷和 deterministic IO 分開：

- LLM/Codex 負責：找市場機制、建立假說、設計一條 alpha、一次只改一個變因、讀結果、歸因 bottleneck、更新下一步。
- Python 程式負責：讀 candidate、登入 BRAIN、送 simulate、poll、抓 result、解析 metrics、寫 artifacts。
- `research/` 負責保存本機研究狀態；GitHub 只追蹤說明、schema、failure taxonomy，不追蹤實驗流水帳和 alpha 狀態。
- `outputs/` 是程式輸出，不手寫；`data/` 是人工或 LLM 準備輸入的地方。

一輪標準流程：

1. 讀 `research/state/family_memory.json`、`research/logs/*`、`outputs/simulate_results.jsonl`。
2. 在 `data/candidates.jsonl` 放入一條 candidate。
3. 執行 `python -m app simulate --limit 1 --current-run`。
4. 程式寫入 `outputs/current_run/`、`outputs/simulate_results.jsonl` 或 `outputs/simulate_errors.jsonl`。
5. recorder 更新 `research/state/family_memory.json`、`research/logs/experiment_decisions.jsonl`、`passed_alphas.csv` 或 `failed_alphas.csv`。
6. 若 candidate 接近提交門檻，先跑 validation；若有多個可用 alpha，再跑 selection 做低相關性篩選。
7. selection 會先在同一變體/同收益來源 cluster 中選 best，再排除與 `research/submissions/submitted_alphas.csv` 高相關的 alpha，最後才寫入 `outputs/submit_queue.csv`。
8. 完整流程收尾時可執行 `select-alphas --finalize-run --clear-candidates`：寫入可接續的 final state，並清空下一輪輸入 `data/candidates.jsonl`。

## 目錄

```text
app/
```

Python 程式。現在只保留：

- `config.py`: 讀 `.env` 與 simulation settings。
- `api/clients.py`: WorldQuant login / simulate / poll / result client。
- `simulator.py`: 讀候選、跑 simulate、寫 JSONL artifacts。
- `research.py`: 更新 family memory、passed/failed logs、decision log。
- `validation.py`: 從 research memory 產生 validation report。
- `selection.py`: 對 passed alphas 做 fingerprint、相關性 clustering、submit queue。
- `research_paths.py`: 集中定義 `research/` 新 layout，並保留舊路徑 fallback。
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
- `outputs/final_alpha_recommendations.md`: selection gate 後的人類閱讀版最終建議報告。
- `outputs/final_alpha_recommendations.example.md`: 可推上 GitHub 的 sanitized 報告範例。

```text
research/
```

研究員 layer 的狀態與記憶。GitHub 只保留說明、分類與 schema/example；實際實驗狀態預設寫到 ignored 子目錄，避免把本機 alpha、portfolio、validation 記錄推上遠端。

- `research/failure_taxonomy.json`: 標準 failure labels。
- `research/README.md`: research artifact 管理規則。
- `research/schema/`: artifact 欄位與 layout 文件。
- `research/examples/`: 可公開的小型 sanitized 範例。
- `research/state/family_memory.json`: family -> variants -> best candidate -> failure modes -> reusable lessons。
- `research/state/best_alphas.txt`: global best 與每個 family best 的短摘要。
- `research/state/portfolio.json`: 本機最佳因子/portfolio 狀態。
- `research/logs/experiment_decisions.jsonl`: 每條結果的 bottleneck、decision、next action。
- `research/logs/passed_alphas.csv`: 進入 validation 的候選。
- `research/logs/failed_alphas.csv`: 未通過或平台錯誤的候選。
- `research/logs/validation_reports.*`: validation report，只有指定 `--write-artifact` 時才寫入。
- `research/submissions/submitted_alphas.csv`: 本機提交追蹤。
- `research/notes/hypotheses.md`: working notes；要公開時請整理到 `docs/` 或 `research/examples/`。

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

查看或指定 research mode：

```powershell
C:\Users\USER\anaconda3\python.exe -m app research --mode pass-alpha-improvement
```

可用模式：

- `auto`
- `pass-alpha-search`
- `pass-alpha-improvement`

啟動研究 workflow：

```text
$worldquant-researcher-workflow
$worldquant-researcher-workflow pass-alpha-search
$worldquant-researcher-workflow pass-alpha-improvement
```

這個入口會讀 `research/state/family_memory.json` 自動判斷目前是在，或依你指定的 mode 強制進入：

- `pass_alpha_search_loop`
- `pass_alpha_improvement_loop`

目前這兩個 loop 不是獨立 CLI，而是同一個 research workflow 的兩個狀態。
Python 負責 simulate / validation / artifact IO，Codex agent 負責研究判斷。

優先使用 skill 命令直接選 loop；`python -m app research --mode ...` 只算 debug / 狀態檢查入口。

## Workflow 呼叫

主要入口是 skill 指令，不是 Python CLI：

```text
$worldquant-researcher-workflow
```

這會讓 Codex 依 `research/state/family_memory.json` 自動決定目前該進哪個 loop。

如果你想手動指定流程，可以直接帶 mode：

```text
$worldquant-researcher-workflow pass-alpha-search
$worldquant-researcher-workflow pass-alpha-improvement
$worldquant-researcher-workflow literature-scout
$worldquant-researcher-workflow hypothesis-builder
$worldquant-researcher-workflow alpha-designer
$worldquant-researcher-workflow result-reflector
$worldquant-researcher-workflow template-governor
```

對應意義：

- `pass-alpha-search`: 找新的 family / hypothesis，直到找到第一個可 pass 的 alpha。
- `pass-alpha-improvement`: 針對既有 pass alpha 做單變因改善，直到沒有明顯改善空間。
- `literature-scout`: 讀文獻找市場機制，不先寫公式。
- `hypothesis-builder`: 把市場機制整理成可驗證假說。
- `alpha-designer`: 產生一條具體 alpha。
- `result-reflector`: 讀最新結果，判斷下一步。
- `template-governor`: 把穩定 family 整理成 template。

如果你只是想看目前狀態，不是要真正跑 workflow，可以用：

```powershell
C:\Users\USER\anaconda3\python.exe -m app research --mode auto
```

這個指令只會回報狀態，不是主工作流入口。

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

策略型 simulation settings 不建議寫在 `.env`。`.env` 只放帳密、API、timeout、路徑等執行環境；Instrument Type、Region、Universe、Language、Decay、Delay、Truncation、Neutralization、Pasteurization、Lookback、Max Trade、Max Position 由 LLM 依策略在每次實驗指定。

最推薦寫在 `data/candidates.jsonl` 的 candidate metadata，讓公式和設定一起被保存：

```json
{
  "candidate_id": "A_settings_001",
  "family": "cashflow_quality",
  "expression": "rank(cashflow / assets)",
  "changed_dimension": "truncation_0.08_to_0.05",
  "simulation_settings": {
    "instrument_type": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "language": "FASTEXPR",
    "decay": 0,
    "delay": 1,
    "truncation": 0.05,
    "neutralization": "INDUSTRY",
    "pasteurization": "ON",
    "lookback": 0,
    "max_trade": "OFF",
    "max_position": "OFF"
  }
}
```

也可以用單次 command 覆蓋，不需要改 `.env`：

```powershell
C:\Users\USER\anaconda3\python.exe -m app simulate --limit 1 --current-run `
  --instrument-type EQUITY `
  --region USA `
  --universe TOP3000 `
  --language FASTEXPR `
  --decay 0 `
  --delay 1 `
  --truncation 0.08 `
  --neutralization INDUSTRY `
  --pasteurization ON `
  --lookback 0 `
  --max-trade OFF `
  --max-position OFF
```

LLM researcher 可以把 simulation setting 當成實驗維度，但一輪只能改一個維度。若本輪改的是 setting，例如 `truncation 0.08 -> 0.05` 或 `delay 1 -> 0`，`data/candidates.jsonl` 的 `changed_dimension` 和 `notes` 必須清楚寫出來，避免和 formula change 混在一起。

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
- 每個失敗都寫入 `research/logs/failed_alphas.csv` 和 `research/logs/experiment_decisions.jsonl`。
- workflow 不因單輪實驗完成而停止；只有找到有提交機會的 alpha、family stop rule 觸發、使用者要求停止，或本次執行安全上限到達時才停。
- 學到的 reusable lesson 寫進 `research/state/family_memory.json`，不要為每輪分析另開新檔。

### 兩個 loop 的呼叫方式

`pass_alpha_search_loop` 和 `pass_alpha_improvement_loop` 都是透過同一個入口啟動：

```text
$worldquant-researcher-workflow
```

workflow 會先讀研究記憶，再決定現在應該找新 alpha，還是針對既有 pass alpha 做改善。
如果之後要做成明確的 Python 指令，再另外加 `python -m app research --mode ...` 類型的入口。

### prompt

從.codex讀取 worldquant 量化研究員的skill，遵循其workflow，不斷尋找alpha，務必找到fitness>2.0的alpha

---

並遵循以下流程：
1️. **上網搜索**文獻研究與異常發現搜尋學術論文、量化部落格、因子投資研究識別市場機制與可觀察模式
2️. 假說形式化將研究發現轉為可測試的假說明確指定所需的 fields 和 operators
3️. Alpha 表達式設計使用 WorldQuant BRAIN 語法設計 alpha遵循 one-change-per-experiment 原則
4️. 回測執行與結果分析透過 simulator 運行回測使用 21 種標準失敗標籤分類
5️. 變體生成與迭代6 種變體策略（參數掃描、算子替換、欄位替換等）追蹤父子關係進行歸因分析
6️. 驗證與過擬合檢查7項驗證測試（樣外測試、參數敏感度、交易成本等）計算信心分數
7️. 相關性聚類與最優選擇以 0.7 相關性閾值聚類從每群中選出最佳代表（考慮IS、turnover、robustness）計算最終投資組合

---

指標記得要幫我做相關性聚類的最優篩選，還要考慮在OS會不會是全域最優，不要在IS overfit，在portolio的檔案用來保存最佳因子

### Submit Queue Gate

`python -m app select-alphas` 不是單純排序 passed alpha。它會做三層 gate：

1. **變體內選 best**：同 parent、同 family、同 core signal/direction 或結構相似度高的 alpha 會被分在同一 cluster，只保留 quality score 最高者。
2. **經濟意涵檢查**：candidate 的 expression fingerprint 必須和 family/hypothesis 的 core signal 一致；例如 news hypothesis 不應最後變成純 return-reversal。
3. **已提交相關性檢查**：cluster winner 仍要和 `research/submissions/submitted_alphas.csv` 比對；如果和已提交 alpha 的結構/metric proxy similarity >= 0.85，就不進 `outputs/submit_queue.csv`。

不同 hypothesis 若其實使用同一組 field/operator、同一 direction，或被判定為同一 `core_signal`，也會被視為相同或相似收益來源，進同一 correlation cluster 競爭代表 alpha。

完整流程結束時可用：

```powershell
C:\Users\USER\anaconda3\python.exe -m app select-alphas --finalize-run --clear-candidates
```

這會額外寫入：

- `research/state/latest_final_selection_report.json`: 下一輪 workflow 可直接讀的 structured final state。
- `research/logs/final_selection_reports.jsonl`: 每次 finalize 的 append-only 歷史。
- `outputs/final_alpha_recommendations.md`: 人類閱讀用報告，包含 expression、IS 表現、經濟意涵、OS/overfit 風險與 submitted correlation。

`data/candidates.jsonl` 只是下一輪輸入，可以在 finalize 後清空。`research/logs/passed_alphas.csv` 不自動刪除，因為它是後續低相關性篩選和收益來源去重的累積候選池。

實際運行產生的 `outputs/final_alpha_recommendations.md` 被 `.gitignore` 忽略，不會推到 GitHub；只追蹤 sanitized 範例 `outputs/final_alpha_recommendations.example.md`。

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
