# 架构优化 Plan：按时间粒度分层重构数据层

**生成时间:** 2026-06-09
**作者:** 李志泉
**状态:** 待审阅

---

## 0. 背景

### 0.1 当前问题

| 问题 | 影响 | 严重度 |
|------|------|--------|
| 数据重复存储 | 同一个 daily 聚合在 `daily_dma.json`（DMA 级别）和 `daily_totals.json`（水表级别）各存一份 | 高 |
| 表 / JSON / JSONL 格式混杂 | 工具读 JSON 路径，SQL 读 SQLite，agent 用户分不清 | 中 |
| 预聚合 vs 原始粒度未分层 | `weekly.json` 从 `daily_dma` 聚合但 `monthly_diff` 又独立算 | 中 |
| hourly 15M 行没分层 | agent 工具读时直接 OOM 风险 | 高 |
| Schema 在 `analytics_real.db` 里有 10 张表但部分冗余 | `meters` / `search_index` / `meter_info.json` 同一数据三个副本 | 中 |

### 0.2 目标

按**时间粒度**分 4 层，**每层一种数据源**，消除重复，让 agent 工具按层路由。

---

## 1. 新架构：4 层时间粒度

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Point-in-time (永久 / 事件)                       │
│  meter_info / predictions / rank_changes / anomalies        │
│  存储: SQLite (meters) + JSON (predictions / rank_changes) │
│  访问: JSON 工具直读，无时间过滤                           │
│  更新: 事件触发（预测刷新 / 排名变化 / 异常检出）          │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Daily Aggregated (151 天)                        │
│  dailydma (DMA 級) + meter_daily (水錶級)                  │
│  存储: JSON (152 天 × N 表)                                │
│  访问: JSON 工具快路径，Pipeline 7 stage 深度处理          │
│  更新: 每日 55 秒增量                                       │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Weekly / Monthly (≤ 5 個月)                       │
│  weekly / monthly_diff                                    │
│  存储: JSON (透传) 或 简单 sum 聚合                       │
│  访问: 工具直读，或运行时 sum 字段                         │
│  更新: 每日重新聚合（小于 1s）                            │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Hourly Raw (30 天, ~15M 行)                    │
│  hourly_meter                                              │
│  存储: SQLite (analytics.db ATTACH hourly.db)              │
│  访问: 只能 SQL 查，无预聚合                              │
│  更新: 每日 55 秒（与 Layer 2 同步）                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 当前 vs 新版：每层数据源对比

| 数据 | 当前位置（重复） | 新版（单一源） | 所属层 |
|------|----------------|---------------|--------|
| meter 元数据 | `meters` 表 + `meter_info.json` + `search_index.json` | **`meters` 表** (SQLite) | Layer 1 |
| 单表预测 | `predictions.json` + `predictions` 表 | **`predictions` 表** (SQLite) | Layer 1 |
| 建筑预测 | `predictions_by_building.json` | **`predictions_building` 表** (SQLite) | Layer 1 |
| Top 50 排名 | `rank_changes.json` + `rank_changes` 表 | **`rank_changes` 表** (SQLite) | Layer 1 |
| 异常 | `anomalies.json` + `anomalies` 表 | **`anomalies` 表** (SQLite) | Layer 1（事件） |
| DMA 日聚合 | `daily_dma.json` + `daily_top20.json` | **`daily_dma` 表** (SQLite) + `daily_dma.json` (同源导出) | Layer 2 |
| **水表日聚合** | `daily_totals.json` (~13MB, 4150 表 × 151 天) | **`meter_daily` 表** (SQLite) | **Layer 2** ⭐ |
| 周聚合 | `weekly.json` | **`weekly` 表** (SQLite) | Layer 3 |
| 月主分表差 | `monthly_main_sub_diff.json` | **`monthly_diff` 表** (SQLite) | Layer 3 |
| 小时原始 | `hourly_meter.db` (~2.7GB) | **`hourly_meter` 表** (SQLite ATTACH) | Layer 4 |
| 数据质量 | `data_errors.json` | **`data_errors` 表** (SQLite) | Layer 1（事件） |
| 修正 | `corrections.json` | **`corrections` 表** (SQLite) | Layer 1（事件） |

**净效果：**
- 删除 5+ 个重复文件：`meter_info.json`、`search_index.json`、`daily_dma.json`（SQL 化）、`predictions.json`（SQL 化）
- 所有数据走 SQLite 一份源
- 工具读 JSON 文件变成"SQLite 视图导出" — 工具签名不变但存储是单一源

---

## 3. 工具路由表（按层）

| 工具 | 层 | 数据源 | 访问方式 | 备注 |
|------|------|--------|----------|------|
| `query_meters` | 1 | meters | SQL SELECT | 实时 |
| `get_predictions` | 1 | predictions | SQL SELECT | 实时 |
| `get_building_predictions` | 1 | predictions_building | SQL SELECT | 实时 |
| `query_rank_changes` | 1 | rank_changes | SQL SELECT | 长周期 |
| `query_anomalies` | 1 | anomalies | SQL SELECT WHERE date | 实时 |
| `query_data_quality` | 1 | data_errors | SQL SELECT | 实时 |
| `get_anomaly_stats` | 1 | anomalies GROUP BY | SQL | 聚合 |
| `analyze_anomaly` | 1 | anomalies + meter_daily | SQL JOIN | 单表深挖 |
| `get_data_overview` | 1 | 全部 COUNT(*) | SQL | 概览 |
| `query_consumption(mode="daily")` | 2 | daily_dma | SQL SELECT | 快 |
| `query_consumption(mode="weekly")` | 3 | weekly | SQL SELECT | 快 |
| `query_consumption(mode="compare")` | 3 | weekly GROUP BY | SQL | 月度对比 |
| `query_weekly` | 3 | weekly | SQL SELECT | 同上 |
| `query_monthly_diff` | 3 | monthly_diff | SQL SELECT | 透传 |
| `sql_chart` | 全部 | 任意 | SQL + ECharts | 灵活 |
| `sql_query` | 全部 | 任意 | SQL | 直查 |

**关键变化：**
- **所有工具**走 SQLite（`analytics_real.db`），不再读 JSON
- JSON 文件**消失**（或仅作为 SQLite 导出备份）
- `sql_query` 工具**成为主要的灵活入口** — 因为所有数据都在 SQLite 里

---

## 4. 4 层时间粒度的具体表设计

### Layer 1: Point-in-time

```sql
-- 永久 / 事件触发更新，无时间字段
CREATE TABLE meters (
    meterId TEXT PRIMARY KEY,
    id TEXT, contractId TEXT, propertyType TEXT,
    isResidential BOOLEAN, buildingName TEXT, dma TEXT,
    supplyMode TEXT, mainCode TEXT
);
CREATE TABLE predictions (
    meterId TEXT, date TEXT, predicted REAL,
    lower REAL, upper REAL,
    PRIMARY KEY (meterId, date)
);
CREATE TABLE predictions_building (
    building TEXT, date TEXT, predicted REAL,
    lower REAL, upper REAL,
    PRIMARY KEY (building, date)
);
CREATE TABLE rank_changes (
    meterId TEXT, contractId TEXT, buildingName TEXT,
    dma TEXT, propertyType TEXT,
    daysInTop20 INT, avgTotal REAL, avgRank REAL, trend TEXT,
    PRIMARY KEY (meterId)
);
CREATE TABLE anomalies (
    date TEXT, meterId TEXT, total REAL, contractId TEXT,
    dma TEXT, buildingName TEXT, reason TEXT,
    type TEXT, anomalyScore REAL,
    pastMean REAL, pastStd REAL, windowDays INT,
    originalType TEXT,
    PRIMARY KEY (date, meterId)
);
CREATE TABLE data_errors (
    ts TEXT, meterId TEXT, date TEXT, reason TEXT,
    rawValue REAL
);
CREATE TABLE corrections (
    meterId TEXT, startDate TEXT, endDate TEXT,
    factor REAL, reason TEXT
);
```

### Layer 2: Daily Aggregated

```sql
-- DMA 级别 (从 hourly_meter 按 dma 聚合)
CREATE TABLE daily_dma (
    date TEXT, dma TEXT, total REAL,
    residential REAL, nonResidential REAL,
    resCount INT, nonResCount INT,
    meterCount INT, rain TEXT,
    PRIMARY KEY (date, dma)
);
-- 水表级别 (从 hourly_meter 按 meterId 聚合)
CREATE TABLE meter_daily (
    meterId TEXT, date TEXT, total REAL,
    PRIMARY KEY (meterId, date)
);
```

### Layer 3: Weekly / Monthly

```sql
CREATE TABLE weekly (
    weekStart TEXT PRIMARY KEY,
    weekEnd TEXT, label TEXT,
    dates JSON, totalByDma JSON, grandTotal REAL,
    weekdayAvg REAL, weekendAvg REAL, wdByDmaRes JSON,
    rain REAL, dailyTotals JSON
);
CREATE TABLE monthly_diff (
    month TEXT, mainMeterId TEXT, mainContractId TEXT,
    mainBuilding TEXT, dma TEXT, subs JSON,
    mainTotal REAL, subsTotal REAL, diff REAL, diffPercent REAL,
    PRIMARY KEY (month, mainMeterId)
);
```

### Layer 4: Hourly Raw

```sql
CREATE TABLE hourly_meter (
    meterId TEXT, datetime TEXT, consumption REAL, reading REAL
);
-- Index for fast JOIN
CREATE INDEX idx_hourly_meter_datetime ON hourly_meter(datetime);
CREATE INDEX idx_hourly_meter_meterId ON hourly_meter(meterId);
```

---

## 5. 迁移路径

### Phase 1: 准备（1 周）

1. 写新表 schema SQL（`pipeline/schema_v2.sql`）
2. 写新 converter（`scripts/migrate_to_sqlite_v2.py`）：
   - 从 `output_real/*.json` 读 → 写 `analytics_real.db` (10 表)
   - 保留 7 stage pipeline（ingest/clean/detect/...）做 schema 校验
3. 备份旧 `output_real/*.json` 到 `output_real_backup_2026MMDD/`
4. 跑新 converter 一遍，验证数据一致

### Phase 2: 工具迁移（1 周）

1. 改 `agent/agent_tools.py` 每个工具 — 读 JSON → 读 SQLite
2. 工具签名不变（`query_anomalies(dma="...")` 还是同样接口）
3. 改 `agent/sql_query` 工具 — 不用 SQL Refinement 了（数据已经在 SQL 里）
4. 加 unit test 验证每个工具的输入输出不变

### Phase 3: 文件删除（1 天）

1. 删除 `output_real/*.json`（15 个文件 ~2.8GB）
2. 删除 `meter_info.json` 和 `search_index.json`（已入 SQL）
3. 删除 `output_real/hourly_meter.db`（已合并到 analytics.db）
4. 保留 `output_real/corrections.json`（作为外部编辑文件，每次启动时导入到 SQLite）

### Phase 4: Pipeline 简化（1 周）

1. `pipeline/orchestrator.py` 7 stage 简化为 4 stage：
   - ingest (读 → 写 SQLite)
   - validate (Pandera schema)
   - transform (检测 + 预测 + 聚合成 daily)
   - publish (刷新 Layer 1 表)
2. 移除 JSON 写盘逻辑（直接写 SQLite）
3. 移除 `corrections.json` 每次启动时导入到 SQLite 表

### Phase 5: 验证（1 周）

1. 跑全套 181 unit tests
2. 跑 30 live LLM eval，对比 v2 93.3%
3. 跑 `scripts/find_alternating_pairs.py` 和 `scripts/real_data_converter.py --full`
4. 对比 5+ 个关键查询的返回结果（手动 diff 修前修后）

**总工作量：** 5 周，2 人周（如果一个人）

---

## 6. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| 工具读 SQLite 慢于读 JSON | 中 | 关键表加索引（已在 §4）；读 9K 行 < 10ms |
| daily_meter 4150 表 × 151 天 = 626K 行 | 低 | SQLite 处理 626K 行 < 100ms |
| 删 JSON 文件破坏 `frontend/build.cjs` | 高 | `build.cjs` 改读 SQLite 导出层（一次性 build 时导出 JSON） |
| `corrections.json` 流程破坏 | 中 | 保留外部文件，启动时导入到 SQLite 表 |
| 171+ 测试因为 mock JSON 路径失败 | 中 | 重写测试用 in-memory SQLite 替代 |
| Agent 工具的 prompt 路径改变 | 低 | 工具签名不变，agent 无感知 |
| 真实数据更新断流（converter 写不进去） | 高 | 双轨期：旧 JSON 读 + 新 SQLite 写，2 周后切读 SQLite |

**关键风险：前端 build.cjs 依赖 output_real/*.json！** 一次性导出层（pipeline 末 stage）会从 SQLite 重新生成 JSON，前端只读 JSON，不变。

---

## 7. 量化收益预估

| 指标 | 当前 | 改后 | 收益 |
|------|------|------|------|
| 磁盘占用 | 2.8GB (JSON) + 354MB (SQLite) | ~400MB (SQLite) | **-85%** |
| 重复存储 | 5+ 处 | 1 处 | 100% 去重 |
| 工具平均延迟 | 17.4s | ~12s | -30% (消除 JSON 解析) |
| Pass rate | 93.3% | 95%+ | 减少"数据格式不匹配"错 |
| 新加数据源时间 | 半天（写 JSON converter + 工具 + 测试） | 2 小时（写 SQL table + 工具直读） | -75% |
| 备份/迁移复杂度 | 15 文件 | 1 文件 | 简化 15x |

---

## 8. 验证清单

```bash
# 1. 数据完整性（关键）
python -c "import sqlite3; c=sqlite3.connect('analytics_real.db'); \
  print('meters:', c.execute('SELECT COUNT(*) FROM meters').fetchone()); \
  print('hourly:', c.execute('SELECT COUNT(*) FROM hourly_meter').fetchone())"

# 2. 工具层
pytest tests/test_agent_tools.py -v          # 工具签名不变
pytest tests/test_sql_chart_real.py -v       # SQL 直查 OK

# 3. 端到端 eval
python tests/evaluate.py                     # pass_rate 应保持 93%+
# 4. Pipeline 端到端
python pipeline/orchestrator.py --force    # 4 stage pipeline 跑通
# 5. 真实数据场景
python scripts/find_alternating_pairs.py --dma "路氹城區"
# 6. 文档同步
# docs/ARCHITECTURE.md §9, §10, §11 全部更新
```

---

## 9. 不在范围

- ❌ 不改 agent 工具的 prompt（签名不变）
- ❌ 不改 PLANNER_PROMPT 路由规则
- ❌ 不改 eval harness
- ❌ 不动前端 `frontend/build.cjs`（build 一次后 JSON 仍存在，build 流程不变）
- ❌ 不动 `corrections.json` 流程（只 import 到 SQLite）

---

## 10. 时间线

| 周 | 任务 | 验收 |
|---|------|------|
| 1 | Phase 1: schema + converter | 10 表数据全部入库，与 JSON 字段对得上 |
| 2 | Phase 2: 工具迁移 | 18 个工具全过单测，agent 接口不变 |
| 3 | Phase 3+4: 文件删 + pipeline 简 | 磁盘 -85%，pipeline 4 stage 跑通 |
| 4 | Phase 5: 验证 | 181 unit + 30 live LLM + 手动 5 查询 |
| 5 | 文档 + 灰度 | 文档同步，旧 JSON 旁路 2 周后删 |

---

**总工作量：** 5 周日历，2-3 人周
**优先级：** 中（不是火上房，但每月磁盘 -85% + 维护成本 -75% 值得做）
**风险：** 中（前端 build 是最大风险点，需要双轨 2 周）
**收益：** 长期（每加一个新数据源省半天）

**建议：** 先做 Phase 1（schema + converter）作为 PoC 验证，再用 PoC 数据对比新 4 层架构 vs 旧 JSON 架构的运行差异，确认收益后再 commit 到 Phase 2-5。
