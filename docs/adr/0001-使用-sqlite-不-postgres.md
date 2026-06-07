# ADR-0001: 使用 SQLite 而非 PostgreSQL 作為主要資料儲存

**狀態**: Accepted · **日期**: 2026-06-07

## Context

資料管道把每天 Excel 處理後的結果載入一個關聯式資料庫，供 AI Agent 做 text-to-SQL 查詢，並給前端 dashboard 查詢。候選方案：

- **PostgreSQL**: 成熟、支援並發寫入、有完整的 SQL dialect
- **SQLite**: 零基礎設施、單一檔案、無需連線池

## Decision

使用 SQLite，檔案放在 `backend/data/analytics.db` (mock) / `analytics_real.db` (real)。僅有一個寫入者（pipeline orchestrator），讀取者（Agent 工具）使用唯讀連線。

## Consequences

### 正面
- ✅ **零維運** — 不需要 DB server、備份策略、連線池
- ✅ **檔案可攜** — DB 可以 gitignore、透過 volume 分享
- ✅ **測試友善** — `:memory:` SQLite 讓單元測試不需 mock
- ✅ **啟動快** — 沒有連線 handshake，pipeline 冷啟動 < 100ms

### 負面
- ❌ **無並發寫入** — 同時多個 writer 會鎖衝突
- ❌ **無內建 replication** — 需要靠檔案層備份
- ❌ **SQL dialect 限制** — 不支援部分 Postgres 特性（`RETURNING` 有限、沒有 `JSONB` 完整語義）

### 緩解措施
- 寫入集中在 pipeline orchestrator 的最後階段 `stage_load_sql`，不存在並發寫入
- 備份靠 `daily_totals.json` cache + JSON artifacts (在 SQLite 之外還有完整資料)
- 不用 SQLite 特有語法，所有 SQL 保持 Postgres 相容 (為將來遷移留路)

## 參考

- `backend/data/analytics.db` (mock, 1.2 MB)
- `backend/data/analytics_real.db` (real, 9,963 meters, 4.6M hourly rows)
- `pipeline/sql_loader.py:SqlLoader` 載入器
