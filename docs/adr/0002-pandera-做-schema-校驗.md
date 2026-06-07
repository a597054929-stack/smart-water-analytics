# ADR-0002: 用 Pandera 在管道邊界做 Schema 校驗

**狀態**: Accepted · **日期**: 2026-06-07

## Context

MLOps 管道從 Excel 讀 raw data、清洗、轉換、載入 SQLite。每個階段的 input/output 都是 DataFrame 或 dict。沒有校驗時，欄位改名、型別變動、單位錯（公升 vs 立方米）會在下游悄悄爆炸。

候選方案：
- **Pydantic**: 主要給 API 用，DataFrame 校驗較弱
- **Pandera**: 為 DataFrame 設計，schema 宣告式，可直接表達「`total` 必須 ≥ 0」「`date` 必須是 ISO 8601」
- **自寫 assert**: 簡單但散落各處，難維護

## Decision

在管道邊界使用 Pandera DataFrameSchema。每個 stage 的 output 都先 `validate()`，失敗時 raise 並終止 pipeline。

實作位置：`pipeline/schema.py` 定義 10 個 schema：
- `MetersSchema`, `DailyDmaSchema`, `HourlyMeterSchema`
- `AnomaliesSchema`, `PredictionsSchema`, `RankChangesSchema`
- `SearchIndexSchema`, `CotaiCalendarSchema`, `WeeklySchema`
- `MonthlyDiffSchema`

每個 schema 明確指定：欄位名、dtype、nullable、value range、regex pattern。

## Consequences

### 正面
- ✅ **Fail fast** — 欄位缺失在 stage 邊界就拋錯，不會污染下游
- ✅ **可讀文件** — schema 本身就是資料契約
- ✅ **可測試** — 故意構造 bad DataFrame 跑 schema 驗證（見 `tests/test_pipeline.py`）
- ✅ **跨 stage 統一** — 不論哪個 stage 產出，都要過同樣的 contract

### 負面
- ❌ **DataFrame 開銷** — 校驗 4M row 的 hourly 表需要 ~3s
- ❌ **不驗證內容合理性** — Pandera 看欄位存在 + 型別對，不看「這個數值合不合理」（那靠 `data_quality.py` 的 IQR cap）

### 緩解措施
- 只在 stage 邊界驗證，不在中間 loop 驗（避免重複成本）
- 業務規則（如 `abs(consumption) > 40000 → data_error`）走 `data_quality.py`，不混在 schema

## 參考

- `pipeline/schema.py`
- `pipeline/orchestrator.py:stage_load_sql` — 在載入 SQLite 前校驗
- `tests/test_pipeline.py:TestSchemaValidation` — 校驗測試
