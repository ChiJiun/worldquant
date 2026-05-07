# WorldQuant Brain Alpha Miner

## 專案目標

這個專案是一台可持續運轉的 WorldQuant Brain alpha 挖掘機器，核心流程是：

- 生成 WorldQuant Brain 可接受的 alpha 表達式
- 自動登入、送出 `simulate`、輪詢、抓取結果
- 用歷史結果回饋模板治理、搜尋權重與去重策略
- 持續記錄 session、checkpoint、best alpha、失敗原因與行為相似度

目前已驗證 `login -> simulate -> poll -> fetch alpha result` 的真實串接可運作。

## 目前能力

### 1. 真實 Brain 串接

- 支援 `basic/json/form/auto` 登入策略
- 已驗證 `basic auth` 可用
- `simulate` payload 已調整為 Brain 可接受格式
- 公式輸出為 Brain 接受的中綴寫法，例如 `(a - b)`，不再使用 `sub(a, b)`
- simulation 完成後會以 alpha id 抓取結果與 checks

### 2. 模板引擎與多欄位邏輯

目前內建模板包含：

- `mean_reversion`
- `momentum`
- `price_volume_divergence`
- `fundamental_cross`
- `volatility_reversion`
- `breakout`
- `quality_value`
- `acceleration`
- `range_reversion`
- `quality_efficiency`
- `volume_confirmed_breakout`
- `liquidity_reversal`
- `fundamental_momentum_spread`

新模板開始更明確結合多欄位邏輯，例如：

- 價格突破搭配成交量確認
- 流動性壓力下的均值回歸
- 基本面排序與價格動能 spread

### 3. 搜尋與自動治理

- 主要搜尋引擎為 `GeneticSearchEngine`
- `MCTSSearchEngine` 保留為可擴充骨架
- 支援：
  - elite 保留
  - crossover
  - mutation
  - immigrant 注入
  - 歷史種子回灌
- 模板治理已升級為混合式：
  - 靜態 `template whitelist / blacklist`
  - 根據歷史 `avg_reward / avg_sharpe / avg_fitness / failure_ratio` 自動降權
  - 自動將高失敗、高負回報模板列入動態黑名單
  - 對穩定高分模板建立動態白名單偏好

### 4. 去重與相似度分析

目前相似度分成兩層：

- pre-simulate:
  - 指紋去重
  - operator 骨架
  - 欄位集合
  - token overlap
- post-simulate:
  - 依真實 alpha 行為做相似度分析
  - 會比較 `Sharpe / Fitness / Returns / Drawdown / Turnover / Margin`
  - 也會納入 `checks` 與 `stage_metrics`

這代表系統已經不只是看字串像不像，而是開始看 alpha 的實際行為輪廓。

### 5. 結果分析維度

抓回結果後，系統現在會保留更多維度：

- `checks`
- `checks_failed`
- `failed_check_names`
- `stage`
- `stage_metrics`
- `universe`
- `region`
- `delay`
- `neutralization`
- `grade`
- `classifications`
- `behavior_similarity`

reward 也會額外懲罰：

- checks fail
- stage 間表現不穩定
- 與既有 alpha 行為過度相似

### 6. 長期 session、checkpoint 與 dashboard

已加入：

- `mining_sessions` table
- 每輪 cycle checkpoint
- `resume-mine`
- `session-report`
- `dashboard`

dashboard 會自動產生：

- 最近 session 摘要
- template performance
- frequent failures
- universe breakdown
- stage breakdown
- failed checks
- best alphas

輸出檔：

- [outputs/session_dashboard.md](D:/Code/worldquant/outputs/session_dashboard.md)

## 重要輸出

### 日誌

- [logs/app.log](D:/Code/worldquant/logs/app.log)
- [logs/events.log](D:/Code/worldquant/logs/events.log)

### 一般輸出

- [outputs/run_summary.csv](D:/Code/worldquant/outputs/run_summary.csv)
- [outputs/failed_alphas.csv](D:/Code/worldquant/outputs/failed_alphas.csv)
- [outputs/best_alphas.txt](D:/Code/worldquant/outputs/best_alphas.txt)
- [outputs/session_dashboard.md](D:/Code/worldquant/outputs/session_dashboard.md)
- [data/worldquant.db](D:/Code/worldquant/data/worldquant.db)

### 持續挖掘輸出

- [outputs_continuous/run_summary.csv](D:/Code/worldquant/outputs_continuous/run_summary.csv)
- [outputs_continuous/failed_alphas.csv](D:/Code/worldquant/outputs_continuous/failed_alphas.csv)
- [outputs_continuous/best_alphas.txt](D:/Code/worldquant/outputs_continuous/best_alphas.txt)
- [outputs_continuous/session_dashboard.md](D:/Code/worldquant/outputs_continuous/session_dashboard.md)
- [data/continuous_mine.db](D:/Code/worldquant/data/continuous_mine.db)

## 常用指令

### 登入測試

```powershell
C:\Users\USER\anaconda3\python.exe -m app login-check
```

### 單輪搜尋

```powershell
C:\Users\USER\anaconda3\python.exe -m app search --generations 1
```

### 持續挖掘

```powershell
C:\Users\USER\anaconda3\python.exe -m app mine --cycles 20 --sleep-seconds 5
```

### 從最新 checkpoint 恢復

```powershell
C:\Users\USER\anaconda3\python.exe -m app resume-mine --sleep-seconds 5
```

### 查看最近 session

```powershell
C:\Users\USER\anaconda3\python.exe -m app session-report --limit 10
```

### 重新生成 dashboard

```powershell
C:\Users\USER\anaconda3\python.exe -m app dashboard --limit 10
```

### 背景長跑

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_continuous_mine.ps1
```

## 如何中斷

前景執行可直接按：

```powershell
Ctrl + C
```

若在背景執行，先查 PID：

```powershell
Get-Process | Where-Object { $_.ProcessName -like '*powershell*' -or $_.ProcessName -like '*python*' }
```

再停止：

```powershell
Stop-Process -Id <PID> -Force
```

## 目前已知限制

- 系統已經是可用的 alpha mining engine，但仍不能保證穩定產出高分 alpha
- post-sim 行為相似度已經上線，但仍不是原生 time-series correlation
- 真實 simulation 可能很慢，仍需調整 `WQ_MAX_POLL_ATTEMPTS` 與 `WQ_POLL_INTERVAL_SECONDS`
- 正式 submission 流程目前仍維持人工確認優先，系統以 research/simulate 為主

## 當前一句話總結

這個專案現在已經是可持續運作的 WorldQuant Brain alpha 挖掘系統，而且已具備模板治理、行為相似度、checkpoint resume 與 dashboard；接下來的重點會是讓「好 alpha 的比例」持續上升。
