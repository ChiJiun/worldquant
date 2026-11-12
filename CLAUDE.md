# CLAUDE.md

WorldQuant BRAIN alpha simulate / research artifact 工具。Python 負責 deterministic IO（candidate 讀取、BRAIN simulate/poll/result、metrics 解析、research artifacts、attribution、validation、correlation gate），LLM 負責研究判斷。完整說明在 `README.md`，研究員 layer 的設計在 `docs/researcher-workflow.md`。

## 語言與風格

- 程式碼、識別字、註解、docstring、測試名稱：英文（沿用既有慣例）。
- README 與 `docs/*.md` 以繁體中文為主，`docs/researcher-workflow.md`、`docs/research-policy.md`、`research/README.md` 與 skill 檔沿用英文。
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
- 會打 live API 的指令：`simulate`、`login-check`、`result`、`fetch-correlations`、`validate-candidate --refresh`、`record-passed-alpha --fetch-metrics`。只有使用者明確要跑研究流程時才執行；`WQ_DRY_RUN=true`（預設）下會用 mock，且 CLI 會拒絕那些會污染研究狀態的 live-only 操作。
- `research/`、`outputs/`、`data/`（除範例與 README）都是本機研究資料，被 `.gitignore` 忽略；不要把真實 alpha、expression、portfolio 寫進會進版控的檔案（`outputs/*.example.*`、`research/examples/` 要 sanitized）。
- 刪除 `research/` 下的任何檔案（含 `research/old/` 舊版備份）前要先問使用者。

## 專案結構摘要

- `app/cli.py`：所有子命令入口；新功能加在這裡並在 `tests/test_cli.py` 加測試。
- `app/api/clients.py`：`BrainClient` 抽象、`RequestsBrainClient`（live）、`MockBrainClient`（測試）。新增 API 要同時實作兩個 client 並加 abstract method。
- `app/simulator.py` → `app/research.py`（recorder：family memory、decisions log、passed/failed CSV）。
- `app/attribution.py`：parent-vs-child / family best / global best 指標歸因；recorder 與 `attribute` 指令共用。
- `app/validation.py`：validation report，`--refresh` 只覆寫同一 `result_id` 的快照。
- `app/correlations.py` + `app/selection.py`：BRAIN self/prod correlation 快取與 submit queue gate（平台 >= 0.7 或結構 >= 0.85 任一成立就擋）。
- `app/research_paths.py`：`research/` 的 layout；舊 flat layout 與 `research/old/` 只做讀取 fallback。
- artifact 欄位與 layout：`research/schema/research-artifacts.md`、`research/README.md`。

## 研究 workflow

- 用 skill `/worldquant-researcher-workflow [mode]`（`.claude/skills/worldquant-researcher-workflow/SKILL.md`）。Codex 版在 `.codex/skills/`，兩份流程要同步；共用的 policy、failure taxonomy、reflection JSON 在 `docs/research-policy.md`。
- 一輪只送一條 alpha、只改一個 design dimension；`data/candidates.jsonl` 必填 `parent_candidate_id` 與 `changed_dimension`，否則 attribution 與 lesson 推導會失效。
- 研究員 prompt 全文在 `docs/researcher-prompt.md`，調整研究行為改那份，不要複製進 README。

## 修改程式時

- 改 CLI 參數或輸出欄位時同步更新 README「命令」段與對應 skill 步驟；改 artifact 欄位時同步 `research/schema/research-artifacts.md`。
- 門檻常數集中：`SELF_CORRELATION_THRESHOLD`（`app/correlations.py`）、`CORRELATION_THRESHOLD`（`app/selection.py`）。
- 寫入 `research/logs/*.csv` 一律走 `app/research.py` 的 `_append_csv` 與欄位常數，不要自己開檔寫。
- 真實 `research/logs/passed_alphas.csv` 含舊腳本留下的重複 `result_id`，`record-passed-alpha` 只防新增，不會清理既有資料。
