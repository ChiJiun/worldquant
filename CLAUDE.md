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
- `WQ_DRY_RUN=true` 是程式預設（`.env.example` 也是），此時全部走 `MockBrainClient`。CLI 只會拒絕三個 live-only 操作（`fetch-correlations` 沒帶 `--allow-mock`、`--fetch-metrics`、`--refresh`）；**`simulate` 不會被擋**，mock 結果仍會寫進 `research/logs/*` 與 `family_memory.json`，而 `select-alphas` 不會過濾 mock 列（只有 `global_best` 在真實結果進來時會讓 mock 讓位）。mock 標記只在 `experiment_decisions.jsonl` 與 `family_memory.json` 的 `metrics` 裡看得到（`raw.mode=mock`、`metrics.alpha_id=mock-...`）；`passed_alphas.csv` / `failed_alphas.csv` 的 `result_id` 是 expression 的 md5 前 12 碼，**CSV 上沒有任何 mock 標記**，要辨識只能拿 `result_id` 對回 decisions log。要跑真實 simulate 前先用 `python -m app settings` 確認 `dry_run=False`、`client_mode=requests`；不確定就問使用者。要在 dry-run 下跑通流程時，把 `WQ_RESEARCH_DIR`、`WQ_OUTPUT_DIR`、`WQ_CANDIDATE_FILE` 指到暫存目錄，不要對真實 `research/` 跑。
- `research/`、`outputs/`、`data/` 都是本機研究資料，被 `.gitignore` 忽略（追蹤的只有各目錄的 README、`research/failure_taxonomy.json`、`research/schema/`、`research/examples/` 與 `*.example.*` 範例）；不要把真實 alpha、expression、portfolio 寫進會進版控的檔案（`outputs/*.example.*`、`research/examples/` 要 sanitized）。
- 刪除 `research/` 下的任何檔案（含 `research/old/` 舊版備份）前要先問使用者。

## 專案結構摘要

- `app/cli.py`：所有子命令入口；新功能加在這裡並在 `tests/test_cli.py` 加測試。
- `app/api/clients.py`：`BrainClient` 抽象、`RequestsBrainClient`（live）、`MockBrainClient`（測試）。新增 API 要同時實作兩個 client 並加 abstract method。
- `app/simulator.py` → `app/research.py`（recorder：family memory、decisions log、passed/failed CSV）。
- `app/attribution.py`：parent-vs-child / family best / global best 指標歸因；recorder 與 `attribute` 指令共用。
- `app/validation.py`：validation report，`--refresh` 只覆寫同一 `result_id` 的快照。
- `app/correlations.py` + `app/selection.py`：BRAIN self/prod correlation 快取與 submit queue gate（平台 >= 0.7 或結構 >= 0.85 任一成立就擋）。
- `app/research_paths.py`：`research/` 的 layout。舊 flat layout（`research/*.json|csv`）與 `research/old/` 只做讀取 fallback，而且只有三個檔有：`family_memory.json`（`research.py`，`init-research` 會把它複製到新路徑）、`passed_alphas.csv` 與 `submitted_alphas.csv`（`selection.py`）；其他檔案只讀新路徑。
- artifact 欄位與 layout：`research/schema/research-artifacts.md`、`research/README.md`。

## 研究 workflow

- 用 skill `/worldquant-researcher-workflow [mode]`（`.claude/skills/worldquant-researcher-workflow/SKILL.md`）。Codex 版在 `.codex/skills/`，兩份流程要同步；共用的 policy、failure taxonomy、reflection JSON 在 `docs/research-policy.md`。
- 一輪只送一條 alpha、只改一個 design dimension；`data/candidates.jsonl` 要填 `parent_candidate_id` 與 `changed_dimension`，否則 `vs_parent` 會是 `no_parent_recorded`、recorder 不會推導 family lesson（family best / global best 比較仍會做）。
- `.codex/.../SKILL.md` 的「Current Best-Family Heuristic」段含一條具體 expression，是舊內容；依上方「安全規則」新內容不要再這樣寫，要不要移除由使用者決定。
- 研究員 prompt 全文在 `docs/researcher-prompt.md`，調整研究行為改那份，不要複製進 README。

## 修改程式時

- 改 CLI 參數或輸出欄位時同步更新 README「命令」段與對應 skill 步驟；改 artifact 欄位時同步 `research/schema/research-artifacts.md`。
- 門檻常數集中：`SELF_CORRELATION_THRESHOLD`（`app/correlations.py`）、`CORRELATION_THRESHOLD`（`app/selection.py`）。
- 寫入 `passed_alphas.csv` / `failed_alphas.csv` 一律走 `app/research.py` 的 `_append_csv` 與 `PASSED_FIELDS` / `FAILED_FIELDS`（`validation.py` 的 `validation_reports.csv` 有自己的 writer），不要自己開檔寫。
- 真實 `research/logs/passed_alphas.csv` 含舊腳本留下的重複 `result_id`，`record-passed-alpha` 只防新增，不會清理既有資料。
