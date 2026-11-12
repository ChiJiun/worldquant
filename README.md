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

- LLM agent（Claude Code 或 Codex）負責：找市場機制、建立假說、設計一條 alpha、一次只改一個變因、讀結果、歸因 bottleneck、更新下一步。
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
7. 若要用平台真實相關性而不是表達式結構代理，先跑 `python -m app fetch-correlations` 把 BRAIN self/prod correlation 快取到 `research/state/alpha_correlations.json`。
8. selection 會先在同一變體/同收益來源 cluster 中選 best（BRAIN self-correlation >= 0.7 或結構相似度 >= 0.85 任一成立就視為同 cluster），再排除與已提交 alpha 高相關的 alpha（同樣兩個訊號取聯集），最後才寫入 `outputs/submit_queue.csv`。
9. 完整流程收尾時可執行 `select-alphas --finalize-run --clear-candidates`：寫入可接續的 final state，並清空下一輪輸入 `data/candidates.jsonl`。

## 目錄

```text
app/
```

Python 程式。現在只保留：

- `config.py`: 讀 `.env` 與 simulation settings。
- `api/clients.py`: WorldQuant login / simulate / poll / result client。
- `simulator.py`: 讀候選、跑 simulate、寫 JSONL artifacts。
- `research.py`: 更新 family memory、passed/failed logs、decision log。
- `validation.py`: 從 research memory 產生 validation report；`--refresh` 會重抓 BRAIN 結果與 self-correlation。
- `attribution.py`: parent-vs-child / family best / global best 的指標歸因。
- `selection.py`: 對 passed alphas 做 fingerprint、相關性 clustering、submit queue。
- `correlations.py`: 解析 BRAIN self/prod correlation 回應、維護 `research/state/alpha_correlations.json` 快取。
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
- `research/state/alpha_correlations.json`: `fetch-correlations` 快取的 BRAIN self/prod correlation，`select-alphas` 優先使用。
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
docs/
```

研究員 layer 的文件，程式不讀：

- `docs/researcher-workflow.md`: 研究員 layer 的設計規格（modes、policies、integration boundary）。
- `docs/research-policy.md`: 兩個 agent skill 共用的 policy、failure taxonomy、reflection JSON。
- `docs/researcher-prompt.md`: 給 LLM 的完整研究員 prompt。

```text
.claude/skills/   .codex/skills/   CLAUDE.md
```

agent 整合：

- `.claude/skills/worldquant-researcher-workflow/SKILL.md`: Claude Code 的研究 workflow skill，用 `/worldquant-researcher-workflow [mode]` 叫用。
- `.codex/skills/worldquant-researcher-workflow/SKILL.md`: Codex 版，用 `$worldquant-researcher-workflow [mode]` 叫用。兩份流程要同步，共用的 policy 放在 `docs/research-policy.md`。
- `CLAUDE.md`: 給 Claude Code 的專案說明：安全規則（`.env` 帳密、測試不打 live API）、常用指令、結構摘要、改程式時要同步的文件。

```text
logs/
```

程式 log。

## 設定

建立本機 `.env`：

```powershell
Copy-Item .env.example .env
```

先用 mock 跑通本機流程。`.env` 保持預設的 `WQ_DRY_RUN=true` 即可。dry-run 下 `simulate` 預設會被擋（exit code 2），要加 `--allow-mock` 才會跑；放行後寫進 `research/` 的列會在 `source` 欄標成 `mock`，`select-alphas` 會跳過它們。即使如此，smoke run 還是不要對真實研究資料跑：用單次 shell 環境變數把路徑指到暫存目錄（shell 變數會覆蓋 `.env` 的值，而且不會留在 `.env` 裡影響之後的 live run）：

```powershell
$env:WQ_DRY_RUN = "true"
$env:WQ_RESEARCH_DIR = "C:\tmp\wq-smoke\research"
$env:WQ_OUTPUT_DIR = "C:\tmp\wq-smoke\outputs"
$env:WQ_CANDIDATE_FILE = "C:\tmp\wq-smoke\candidates.jsonl"
$env:WQ_LOG_DIR = "C:\tmp\wq-smoke\logs"
C:\Users\USER\anaconda3\python.exe -m app init-data
C:\Users\USER\anaconda3\python.exe -m app simulate --allow-mock --limit 1 --current-run
```

跑完後開新的 shell，或用 `Remove-Item Env:WQ_RESEARCH_DIR` 等指令清掉這些變數。

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

啟動研究 workflow。Claude Code：

```text
/worldquant-researcher-workflow
/worldquant-researcher-workflow pass-alpha-search
/worldquant-researcher-workflow pass-alpha-improvement
```

Codex 用同樣的 mode，只是前綴換成 `$`：

```text
$worldquant-researcher-workflow pass-alpha-improvement
```

這個入口會讀 `research/state/family_memory.json` 自動判斷目前在哪個 loop，或依你指定的 mode 強制進入：

- `pass_alpha_search_loop`
- `pass_alpha_improvement_loop`

目前這兩個 loop 不是獨立 CLI，而是同一個 research workflow 的兩個狀態。
Python 負責 simulate / validation / attribution / artifact IO，agent 負責研究判斷。

優先使用 skill 命令直接選 loop；`python -m app research --mode ...` 只算 debug / 狀態檢查入口。所有 mode 的意義見下方「Workflow 呼叫」。

## Workflow 呼叫

主要入口是 skill 指令，不是 Python CLI。Claude Code：

```text
/worldquant-researcher-workflow
```

Codex：

```text
$worldquant-researcher-workflow
```

這會讓 agent 依 `research/state/family_memory.json` 自動決定目前該進哪個 loop。兩個 skill 的步驟相同（`.claude/skills/` 與 `.codex/skills/`），共用 `docs/research-policy.md`。

如果你想手動指定流程，可以直接帶 mode（兩邊都一樣，只差前綴）：

```text
/worldquant-researcher-workflow pass-alpha-search
/worldquant-researcher-workflow pass-alpha-improvement
/worldquant-researcher-workflow literature-scout
/worldquant-researcher-workflow hypothesis-builder
/worldquant-researcher-workflow alpha-designer
/worldquant-researcher-workflow result-reflector
/worldquant-researcher-workflow template-governor
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

在 `WQ_DRY_RUN=true` 或 `WQ_CLIENT_MODE=mock` 下，`simulate` 會直接報錯（exit code 2）而不會送出 mock 結果，避免把合成數據寫進真實研究日誌。只有為了跑通流程時加 `--allow-mock`：此時 recorder 會在 `research/logs/experiment_decisions.jsonl` 與 `passed_alphas.csv` / `failed_alphas.csv` 的 `source` 欄標 `mock`（真實結果是 `live`），`outputs/current_run/summary.json` 也會帶 `source`，而 `select-alphas` 會跳過 `source=mock` 的列。舊的 CSV 沒有 `source` 欄，第一次 append 時會補上欄位，舊列留空並視為 live。

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

看一條 candidate 相對父代、family best、global best 的指標變化（預設看 global best）：

```powershell
C:\Users\USER\anaconda3\python.exe -m app attribute
C:\Users\USER\anaconda3\python.exe -m app attribute --candidate-id ANALYST_REV_001
```

輸出包含 `vs_parent` / `vs_family_best` / `vs_global_best` 每個指標的 from/to/delta、`improved` / `worsened` 清單、整體 `verdict`（`net_improvement`、`improvement_with_trade_off`、`trade_off`、`regression_with_trade_off`、`regression`、`unchanged`、`incomparable`）與下一步提示。`unchanged` 是所有可比指標都相同；`incomparable` 是父代連一個可比指標都沒有（例如父代最後一筆是平台錯誤的 error row），此時只有 family / global 比較可用。父代由 candidate 的 `parent_candidate_id` 決定，依序從 family memory、`experiment_decisions.jsonl`、`passed_alphas.csv` / `failed_alphas.csv` 找（手動用 `record-passed-alpha` 補登的父代只在 CSV；CSV 中沒有任何指標的 error row 會被跳過，改取同 candidate 更早有指標的列）；同一份歸因也會在每次 simulate 後自動寫進 `research/logs/experiment_decisions.jsonl` 每筆成功結果的 `latest_vs_parent`（simulate 失敗的 error row 沒有指標可比，不帶這個欄位）。沒寫 `parent_candidate_id` 的 candidate 會得到 `no_parent_recorded`。

同一個 `candidate_id` 曾在不同 family 重用時，`attribute` 會取 family memory 裡最先找到的那條並在報告加 `warning`（也印到 stderr）；用 `--result-id <alpha id>` 指定要看哪一條。

驗證 candidate（預設 global best），並在平台 SELF_CORRELATION 還是 PENDING 時改用 `fetch-correlations` 的快取：

```powershell
C:\Users\USER\anaconda3\python.exe -m app validate-candidate
C:\Users\USER\anaconda3\python.exe -m app validate-candidate --candidate-id ANALYST_REV_001 --refresh --write-artifact
```

`--refresh` 會用 candidate 的 `result_id` 重新從 BRAIN 抓 alpha（PENDING 的 checks 通常會變成結果）、更新 `family_memory.json` 裡**同一個 `result_id`** 的所有快照（同名 candidate 但指向別的 alpha 的快照不會被動到），並順便把它的 self-correlation 寫進 `research/state/alpha_correlations.json`。需要 live client；`WQ_DRY_RUN=true` 下會直接報錯。

同一個 `candidate_id` 曾在不同 family 重用時，報告會多一個 `warning` 說明選到哪個 `result_id`；用 `--result-id <alpha id>` 可以明確指定要驗證哪一條。只給 `--result-id` 不給 `--candidate-id` 時，會用 alpha id 跨所有 family 搜尋，不會被忽略而默默驗證 global best。找不到 candidate、memory 檔不存在、memory 檔不是合法 JSON（訊息會寫 corrupt，不會當成空的覆蓋掉）、live client 的連線或平台錯誤、mock client 的未知 id，都會印出 `error:` 並以 exit code 1 結束，不會噴 traceback。改用快取判定的 self_corr check 會帶 `fetched_at`，太舊就先 `fetch-correlations --refresh`。

手動補登一條已驗證的 passed alpha（取代以前散落在根目錄的 append_*.py 腳本）：

```powershell
C:\Users\USER\anaconda3\python.exe -m app record-passed-alpha `
  --candidate-id BLUE_SYNERGY_001 `
  --family blue_ocean_hybrid_synthesis `
  --expression "ts_decay_linear(rank(close), 10)" `
  --result-id O0ovlO0R `
  --sharpe 1.28 --fitness 0.87 --returns 0.0577 --drawdown 0.085 --turnover 0.0582
```

規則：

- `recorded_at` 預設為現在的 UTC 時間，可用 `--recorded-at` 指定，必須是 ISO-8601 格式。
- `--result-id` 必填且不可空白，因為這張表以 BRAIN alpha id 判重。
- `--decision` 只接受 `validate_best_candidate` 或 `promote_candidate`，確保這張表只放通過 pass gate 的 alpha。
- 同一個 `--result-id` 已存在時會拒絕寫入，除非加 `--allow-duplicate`。
- 數值欄位必須是有限數字；`nan`、`inf` 或非數字會被拒絕，避免污染 selection 的排序。
- 加 `--fetch-metrics` 會用 `--result-id` 從 BRAIN 補齊沒在命令列指定的指標；在 `WQ_DRY_RUN=true` 或 mock client 下會直接報錯。

抓 BRAIN 真實相關性並快取（預設抓 `research/logs/passed_alphas.csv` 裡所有 `result_id` 的 self-correlation）：

```powershell
C:\Users\USER\anaconda3\python.exe -m app fetch-correlations
C:\Users\USER\anaconda3\python.exe -m app fetch-correlations --alpha-id 2rJM0lwJ --kind both
C:\Users\USER\anaconda3\python.exe -m app fetch-correlations --limit 20 --refresh
```

- `--kind self|prod|both`：self 是跟自己帳號已提交 alpha 的相關性（BRAIN 提交門檻 0.7），`select-alphas` 只用這個。prod 是跟全平台 alpha 的相關性分布，目前只存進快取供人工參考，selection 不使用。
- 已快取（有數值）的 alpha 預設跳過；`--refresh` 強制重抓，提交新 alpha 後記得跑一次。`--limit N` 限制這次最多打 N 次 API（失敗的呼叫也算），方便分批。
- BRAIN 計算中會回 `Retry-After`，程式會照平台要求等待：上限 60 秒，下限是 `WQ_POLL_INTERVAL_SECONDS`（沒設時至少 1 秒），而且下限優先，所以設定間隔超過 60 秒時仍以設定為準；最多重試 `WQ_MAX_POLL_ATTEMPTS` 次。
- 在 `WQ_DRY_RUN=true` 或 mock client 下這個指令會直接報錯：mock 寫入的結果會被當成「平台已確認不相關」，讓已提交 gate 失效。只有為了跑通流程時加 `--allow-mock`，此時寫入的是沒有數值的空項目，`select-alphas` 會視為沒有快取，之後 live 執行也會把它重抓；報告裡的 `fetched_at` 只會對有數值的項目印出。
- 快取檔格式版本是 2。版本不符（例如舊版 1，可能含早期 mock 寫出的 `0.0`）或不是合法 JSON 的檔會被當成空的並寫 log，寫入新快取前會把舊檔改名為 `alpha_correlations.json.v1` / `alpha_correlations.json.corrupt`（已存在就加流水號），報告帶 `previous_cache_status` 與 `previous_cache_backup`。升版後舊的 live 快取要重抓一次。

跑測試：

```powershell
C:\Users\USER\anaconda3\python.exe -m pytest
```

開發環境安裝（含 pytest）：

```powershell
python -m pip install -e ".[dev]"
```

GitHub Actions 會在每個 PR 與 `main` 的 push 上執行 `pytest`（見 `.github/workflows/ci.yml`）。

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

`pass_alpha_search_loop` 和 `pass_alpha_improvement_loop` 都是透過同一個 skill 入口啟動，workflow 會先讀研究記憶，再決定現在應該找新 alpha，還是針對既有 pass alpha 做改善；指令與 mode 清單見上方「Workflow 呼叫」。`python -m app research --mode ...` 只是狀態檢查入口。

### 研究員 prompt

給 LLM 當 WorldQuant BRAIN 資深量化研究員的完整 prompt 放在 `docs/researcher-prompt.md`。它描述研究流程、硬性限制與輸出格式；要調整研究行為時改那份文件，不要把 prompt 內容複製進 README。

### Submit Queue Gate

`python -m app select-alphas` 不是單純排序 passed alpha。讀 `passed_alphas.csv` 時先排除 `source=mock` 的列（`simulate --allow-mock` 寫出的合成結果；報告與 `correlation_report.md` 會印 `mock_rows_skipped`，沒有 `source` 欄的舊列視為 live），然後做三層 gate：

1. **變體內選 best**：兩條 alpha 只要任一訊號過門檻就進同一 cluster：BRAIN self-correlation 快取裡彼此的 |correlation| >= 0.7，或表達式結構相似度（同 parent、同 core signal/direction、field/operator Jaccard）>= 0.85。注意 BRAIN self-correlation 只會列出該帳號已提交的 alpha，兩條尚未提交的候選不會互相出現，所以候選之間的 clustering 實務上多半仍是結構代理在做。每個 cluster 只保留 quality score 最高者。`outputs/alpha_correlation_matrix.csv` 裡只有平台值過門檻的配對寫平台值，其他配對一律寫結構分數，不混用尺度。
2. **經濟意涵檢查**：candidate 的 expression fingerprint 必須和 family/hypothesis 的 core signal 一致；例如 news hypothesis 不應最後變成純 return-reversal。
3. **已提交相關性檢查**：cluster winner 同時看兩個訊號，任一過門檻就擋：BRAIN self-correlation 快取回報的帶號 max correlation >= 0.7（`replaced_by` 填平台列出的最相關 alpha id），或與 `research/submissions/submitted_alphas.csv` 的結構相似度 >= 0.85。平台數值優先，但結構比對是快取過舊時的安全網：提交新 alpha 後沒 `--refresh`，表達式一模一樣的候選仍會被擋。gate 用的是帶號值，與 BRAIN 的 SELF_CORRELATION check 一致，所以強負相關不會擋提交（clustering 則用絕對值）。被擋的 alpha 不進 `outputs/submit_queue.csv`。`correlation_report.md` 會印出快取裡最舊的 `fetched_at`，太舊就重抓。

以前版本還有一個「metric proxy」相似度（對 Sharpe/Fitness/Returns 等指標向量算 Pearson），但所有好 alpha 的指標形狀都相近，會把不相關的 alpha 全部黏成一團，已經移除。

快取裡有 self-correlation 的 alpha，其 `self_corr_status` 會依 0.7 門檻標成 `pass`/`fail`，並影響 quality score；沒有快取的維持 `pending`。

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

已完成：

- parent-vs-child metric attribution（`python -m app attribute`，並自動寫入 `experiment_decisions.jsonl`）
- validation check runner（`python -m app validate-candidate --refresh`，含 self-correlation 快取）
- BRAIN 真實相關性（`python -m app fetch-correlations`）
- Claude Code skill 與專案 `CLAUDE.md`（與 Codex skill 共用 `docs/research-policy.md`）

接下來可以加：

- operator-aware alpha designer（送 simulate 前依 `config/fields.json` 驗證 field/operator）
- template governor

研究員 layer 的設計規格先放在：

```text
docs/researcher-workflow.md
```

重點是讓 LLM 替代人類研究員的研究行為，而不是替代 BRAIN simulation 或市場驗證。
