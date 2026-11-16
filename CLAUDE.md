# CLAUDE.md

WorldQuant BRAIN alpha simulate / research artifact 工具。Python 負責 deterministic IO（candidate 讀取、BRAIN simulate/poll/result、metrics 解析、research artifacts、attribution、validation、correlation gate），LLM 負責研究判斷。完整說明在 `README.md`，研究員 layer 的設計在 `docs/researcher-workflow.md`。

## 語言與風格

- 程式碼、識別字、註解、docstring、測試名稱：英文（沿用既有慣例）。
- 繁體中文：`README.md`、`docs/researcher-prompt.md`、本檔。英文：`docs/researcher-workflow.md`、`docs/research-policy.md`、`research/README.md`、`research/schema/*.md`、`data/` / `outputs/` / `logs/` 的 README、兩份 skill 檔。新文件依同類檔案的語言。
- 不要為一次性需求在根目錄新增腳本；需要可重複的操作就加成 `python -m app` 子命令並補測試與 README。

## 常用指令

```powershell
.venv\Scripts\python.exe -m pytest -q          # 全部測試（CI 跑 3.11 / 3.12 / 3.13）
.venv\Scripts\python.exe -m app --help         # 子命令清單
.venv\Scripts\python.exe -m app settings       # 看目前設定（不印帳密）
```

沒有 `.venv` 時：`python -m venv .venv` 後 `.venv\Scripts\pip install -e ".[dev]"`。

## 安全規則（最重要）

- `.env` 含使用者的 BRAIN 帳密。不要讀出、印出、複製到任何檔案或訊息，也不要 commit（已在 `.gitignore`）。
- 測試只能用 `app.api.MockBrainClient`，不可打 live BRAIN API；`tests/conftest.py` 的 `settings` fixture 已是 `dry_run=True`、`client_mode="mock"`。
- 會打 live API 的指令：`simulate`、`login-check`、`result`、`fetch-correlations`、`validate-candidate --refresh`、`record-passed-alpha --fetch-metrics`。只有使用者明確要跑研究流程時才執行。
- `WQ_DRY_RUN=true` 是程式預設（`.env.example` 也是），此時全部走 `MockBrainClient`。CLI 在 dry-run / mock 下會拒絕四個操作：`simulate` 與 `fetch-correlations` 沒帶 `--allow-mock`、`record-passed-alpha --fetch-metrics`、`validate-candidate --refresh`（後兩者沒有放行旗標；`fetch-correlations --refresh` 不是被擋的那個）。`simulate --allow-mock` 仍會寫進 `research/`，但 recorder 會在 `experiment_decisions.jsonl` 與 `passed_alphas.csv` / `failed_alphas.csv` 的 `source` 欄標 `mock`（真實結果是 `live`；舊 CSV 沒有這欄，第一次 append 時會補上欄位、舊列留空並視為 live），`select-alphas` 會跳過 `source=mock` 的列並在報告印 `mock_rows_skipped`。mock 標記另外可在 `family_memory.json`、`experiment_decisions.jsonl`、`outputs/simulate_results.jsonl` 與 `outputs/current_run/results.jsonl` 的 `metrics.raw.mode=mock` / `metrics.alpha_id=mock-...` 看到；`result_id` 本身仍是 expression 的 md5 前 12 碼。family memory 的保護只有兩層：`_is_better_candidate` 一律拒收 mock，所以 mock 不會成為 `global_best`；family `best_candidate` 會收 mock，但第一筆真實結果會無條件取代它；`recent_candidates` 沒有保護。要跑真實 simulate 前先用 `python -m app settings` 確認 `dry_run=False`、`client_mode=requests`；不確定就問使用者。要在 dry-run 下跑通流程時，用單次 shell 環境變數（不要寫進 `.env`）把 `WQ_RESEARCH_DIR`、`WQ_OUTPUT_DIR`、`WQ_CANDIDATE_FILE`、`WQ_LOG_DIR` 指到暫存目錄，再加 `--allow-mock`，不要對真實 `research/` 跑。
- `research/`、`outputs/`、`data/` 都是本機研究資料，被 `.gitignore` 忽略（追蹤的只有各目錄的 README、`research/failure_taxonomy.json`、`research/schema/` 與 `*.example.*` 範例；`.gitignore` 白名單允許 `research/examples/`，但目前沒有追蹤任何檔）；不要把真實 alpha、expression、portfolio 寫進會進版控的檔案（`outputs/*.example.*`、`research/examples/` 要 sanitized）。
- 刪除 `research/` 下的任何檔案（含 `research/old/` 舊版備份）前要先問使用者。

## 專案結構摘要

- `app/cli.py`：所有子命令入口；新功能加在這裡並在 `tests/test_cli.py` 加測試。
- `app/api/clients.py`：`BrainClient` 抽象、`RequestsBrainClient`（live）、`MockBrainClient`（測試）。新增 API 要同時實作兩個 client 並加 abstract method。
- `app/simulator.py` → `app/research.py`（recorder：family memory、decisions log、passed/failed CSV）。
- `app/attribution.py`：parent-vs-child / family best / global best 指標歸因；recorder 與 `attribute` 指令共用。父代沒有任何可比指標時 verdict 是 `incomparable`（不是 `unchanged`）；`find_in_alpha_csv` 會跳過沒有指標的 error row，回傳的 snapshot 用 `found_in` 帶檔案路徑（不是 `source`，那是 CSV 的 live/mock 欄；decisions 列也會補 `found_in`），`vs_parent` / `latest_vs_parent` 對應的欄位是 `reference_found_in`。`_compare_or_self` 判定 `is_family_best` / `is_global_best` 時兩邊都有 `result_id` 就比 `result_id`，否則比 `candidate_id`；非同一條時比較結果帶 `reference_candidate_id` 與 `reference_result_id`。`attribute --result-id` 與 `validate-candidate --result-id` 都能挑同名 `candidate_id` 中的某一條 alpha，沒給時報告帶 `warning`；只給 `--result-id` 時兩者都跨 family 搜尋（attribute 還會再找 decisions log 與 CSV），找不到的訊息是 `<any candidate> (result_id=...)`。
- `app/validation.py`：validation report，`--refresh` 只覆寫同一 `result_id` 的快照；只給 `--result-id` 不給 `--candidate-id` 時用 alpha id 跨 family 搜尋。
- `app/correlations.py` + `app/selection.py`：BRAIN self/prod correlation 快取與 submit queue gate（平台 >= 0.7 或結構 >= 0.85 任一成立就擋）。快取檔 `CACHE_VERSION` 是 2；舊版或損壞的檔載入時當成空的並 log，寫入前改名成 `alpha_correlations.json.v1` / `.corrupt`。
- `app/research_paths.py`：`research/` 的 layout。舊 flat layout（`research/*.json|csv`）與 `research/old/` 只做讀取 fallback，而且只有三個檔有：`family_memory.json`（`research.py`，`init-research` 會把它複製到新路徑）、`passed_alphas.csv` 與 `submitted_alphas.csv`（`selection.py`）；其他檔案只讀新路徑。
- artifact 欄位與 layout：`research/schema/research-artifacts.md`、`research/README.md`。

## 研究 workflow

- 用 skill `/worldquant-researcher-workflow [mode]`（`.claude/skills/worldquant-researcher-workflow/SKILL.md`）。Codex 版在 `.codex/skills/`，兩份流程要同步；共用的 policy、failure taxonomy、reflection JSON 在 `docs/research-policy.md`。
- 一輪只送一條 alpha、只改一個 design dimension；`data/candidates.jsonl` 要填 `parent_candidate_id` 與 `changed_dimension`，否則 `vs_parent` 會是 `no_parent_recorded`、recorder 不會推導 family lesson（family best / global best 比較仍會做）。
- 特定 family 的研究結論與具體 alpha expression 不放進 skill 或任何會進版控的檔案（`.codex/.../SKILL.md` 原有的「Current Best-Family Heuristic」段已移除）；這類結論屬於 `research/state/family_memory.json` 的 lessons（本機、gitignore）。
- 研究員 prompt 全文在 `docs/researcher-prompt.md`，調整研究行為改那份，不要複製進 README。

## 修改程式時

- 改 CLI 參數或輸出欄位時同步更新 README「命令」段與對應 skill 步驟；改 artifact 欄位時同步 `research/schema/research-artifacts.md`。
- 門檻常數集中：`SELF_CORRELATION_THRESHOLD`（`app/correlations.py`）、`CORRELATION_THRESHOLD`（`app/selection.py`）。
- 寫入 `passed_alphas.csv` / `failed_alphas.csv` 一律走 `app/research.py` 的 `_append_csv` 與 `PASSED_FIELDS` / `FAILED_FIELDS`（`validation.py` 的 `validation_reports.csv` 有自己的 writer），不要自己開檔寫。`_append_csv` 遇到舊 header 缺欄位時會重寫整檔補欄位（只加欄、不改值；寫到同目錄暫存檔、`shutil.copymode` 保留權限再 `os.replace`），所以新增欄位要放在 `PASSED_FIELDS` 裡；header 含程式不認識的欄位或重複欄名時不升級、照既有 header append、丟掉對不上的欄並 `LOGGER.warning`。這幾個 CSV 的讀取端（`research.py`、`attribution.py`、`selection.py`）一律用 `utf-8-sig`，帶 BOM 的檔不會被當成未知 header。
- `app/research.py` 的 `_load_memory` 遇到不是合法 JSON 的 `family_memory.json` 會丟 `ValueError`（訊息含 corrupt），不再當成空 memory；CLI 用 `CLI_ERRORS` 把 `ValueError`、`KeyError`、`RuntimeError`、`TimeoutError`、`OSError`、requests 例外轉成 `error:` 與 exit code 1。
- 真實 `research/logs/passed_alphas.csv` 含舊腳本留下的重複 `result_id`，`record-passed-alpha` 只防新增，不會清理既有資料。
