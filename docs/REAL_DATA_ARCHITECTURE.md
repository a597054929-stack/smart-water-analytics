# 真实数据架构（Real Data Architecture）

> 描述 Smart Water Analytics 接入真实澳门水务数据后的**当前实现**状态。
> 计划文档见 `docs/PLAN_REAL_DATA.md`；本文是事实基准。

---

## 一、为什么需要真实数据分支

模拟数据（`scripts/mock_data_generator.py`）只有 500 个水表 / 125 天，用于离线演示、CI、面试 demo 都合适，但展示不出：

- 真实数据量下的查询性能
- 真实水表分布（住宅 vs 商业、4 个 DMA 分区）
- 真实的小时级消费模式（夜间低 vs 晚高峰）
- 真实主-分表差额（NRW 漏损信号）

所以从 2026-06-04 起加了真实数据分支。两套数据**完全物理隔离**：

```
backend/data/
├── output/         daily_dma.json, anomalies.json, ...   ← mock
├── analytics.db
├── output_real/    同上 + 4 个 hourly JSON + 缓存        ← real
└── analytics_real.db
```

切换 = 跑另一侧的 bat，零共享状态。

---

## 二、存储策略（核心架构）

dashboard 是**静态 HTML**（inlined CSS+JS+data），runtime **无数据库连接**。这意味着 dashboard 想显示什么，必须在 build 时预聚合进 JSON。

```
Excel 原始数据（每天一个 .xlsx，~25K 行小时记录）
    │
    ▼
┌──────────────────────────┐
│  real_data_converter.py  │  (incremental, ~55s / 新增一天)
└──────────────────────────┘
    │
    ├─→ 日级聚合  ──►  backend/data/output_real/
    │                 ├─ daily_dma.json, daily_top20.json
    │                 ├─ anomalies.json, predictions.json
    │                 ├─ cotai_calendar.json, weekly.json
    │                 ├─ rank_changes.json, monthly_main_sub_diff.json
    │                 └─ meter_info.json, search_index.json
    │                 用途: dashboard 全部 tab
    │
    ├─→ 小时级聚合 ─► backend/data/output_real/
    │                 ├─ hourly_dma.json         (date × hour × DMA)
    │                 ├─ hourly_calendar.json    (date × 24h profile)
    │                 ├─ hourly_top_meters.json  (date × top-10 meter profile)
    │                 └─ peak_hours.json         (date × DMA peak hour)
    │                 用途: 未来 dashboard hourly 视图
    │
    └─→ 小时级明细 ─► backend/data/output_real/hourly_meter.db
                      ├─ hourly_meter 表 (~4.6M 行 / 30 天)
                      └─ 用途: agent 的 text-to-SQL 工具做 ad-hoc 查询
```

### 关键决策

| 决策 | 为什么 |
|------|--------|
| Dashboard **不查 DB** | 静态 HTML 无 DB 连接；想看的数据必须预聚合 |
| **Daily JSON 全量重派生** | 反派生（异常、Top-N、排名）需要全量数据；纯 Python 内存计算比读 Excel 快得多 |
| **Hourly JSON 增量 append** | Hourly 视图只看消费模式，不需要重派生旧数据 |
| **hourly_meter.db 滚动到 30 天** | SQLite 在 7M 行时还快；30 天 ≈ 7M 行 ≈ 600MB；超过会显著拖慢 ATTACH |
| **daily_totals.json 是内部缓存** | 让 incremental 不重读历史 Excel；24MB / 151 天；**仅供 converter 自己使用**，dashboard/agent 不读 |

---

## 三、Converter 三种运行模式

```bash
# 默认（增量）：只处理比 cache 新的 Excel 文件
python scripts/real_data_converter.py

# 强制全量：忽略 cache，重新处理所有 Excel（~2 小时 / 151 天）
python scripts/real_data_converter.py --full

# 倒填：忽略 cache，处理 >= 指定日期的所有 Excel
python scripts/real_data_converter.py --since 2026-01-01

# 自定义 hourly window
python scripts/real_data_converter.py --hourly-window 60
```

### 工作原理（增量模式）

```
1. 读 daily_totals.json 缓存 → 找到 cache 最后日期 last_date
2. 列 source dir 里 > last_date 的所有 .xlsx 文件
3. 读这些新文件 → 得到 new_daily[date][meterId] = total
                            + new_hourly_rows = [(meterId, "YYYY-MM-DD HH:00", val)]
4. 合并: merged = {**cache, **new_daily}
5. 写回缓存
6. 从 merged 全量反派生所有 daily_*.json（内存计算，~1s）
7. 从 new_daily_with_readings 增量 append 到 hourly_*.json
8. INSERT OR IGNORE new_hourly_rows 到 hourly_meter.db
9. DELETE rows older than (latest_date - hourly_window + 1) days
```

### 每日增量运行成本

| 项目 | 时间 | 说明 |
|------|------|------|
| 读 1 天 Excel（~25K 行） | ~50s | openpyxl 慢，但只对新文件做 |
| 反派生 daily aggregates | <1s | 纯 Python，全内存 |
| Append hourly JSONs | <1s | load + concat + write |
| UPDATE hourly_meter.db | <1s | INSERT OR IGNORE 跳过重复；DELETE 老数据 |
| **总计** | **~55s / 新增一天** | |

对比：全量重派生 151 天需要 ~2 小时（25K 行 × 151 天）。

---

## 四、产物清单

写到这里：`backend/data/output_real/`

### Daily aggregates（dashboard 主用）

| 文件 | 形态 | 大小 | 备注 |
|------|------|------|------|
| `daily_dma.json` | `[{date, dmas: {dma: {...}}}]` | ~3 KB/天 | 4 个 DMA × res/nonRes 拆分 |
| `daily_top20.json` | `[{date, top20: [{meterId, total, ...}]}]` | ~5 KB/天 | 每日 Top-20 |
| `weekly.json` | `[{weekStart, ..., dailyTotals}]` | ~3 KB/周 | 7 天滚动聚合 |
| `rank_changes.json` | `[{meterId, daysInTop20, avgRank, ...}]` | ~8 KB | 全期累计 |
| `monthly_main_sub_diff.json` | `[{month, diffs: [...]}]` | ~10-30 KB/月 | 主-分表差（NRW） |
| `cotai_calendar.json` | `[{date, items: [...]}]` | 视路氹城區活动量 | 非住宅 Top-15 |
| `anomalies.json` | `[{date, meterId, type, score, ...}]` | 视异常数量 | 14 天滚动窗口 |
| `predictions.json` | `{predictions: [{meterId, predictions: [{date, value}], ...}]}` | ~46 KB | Top-50 指数平滑 |
| `predictions_fitted.json` | `{fitted: [...]}` | ~16 KB | 历史拟合值 |
| `meter_info.json` | `{meterId: {dma, propertyType, ...}}` | ~2.5 MB | 水表元数据 |
| `search_index.json` | `[{id, contract, building, dma, type}]` | ~1.5 MB | 模糊搜索索引 |
| `available_dates.json` | `["2026-01-01", ...]` | <1 KB | 排序日期列表 |
| `data_errors.json` | `[{date, meterId, rawValue, reason}]` | ~8 KB | 误值累计表（abs>4000 m³/日） |

**Removed in 2026-06-05:** `predictions_by_building.json`（按建築物聚合預測已被
"按 meter" 視圖取代，節省 ~13KB + 一次 IPC）。`scripts/real_data_converter.py`
不再生成此文件，`frontend/build.cjs` 也不再 copy。

### Hourly aggregates（dashboard 未来用，目前未被消费）

| 文件 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `hourly_dma.json` | `[{date, hour, dmas: {dma: total}}]` | ~6 KB/天 | 24h × DMA 折线图 |
| `hourly_calendar.json` | `[{date, hours: [v0..v23]}]` | <1 KB/天 | 24h 热力图 |
| `hourly_top_meters.json` | `[{date, top: [{meterId, profile: [v0..v23], info}]}]` | ~7 KB/天 | 高耗水户 24h 画像 |
| `peak_hours.json` | `[{date, dma, peakHour, peakValue, offPeakAvg, hourlyProfile}]` | ~2 KB/天 | 峰谷分析（peak = 18:00-22:00） |

### Internal cache（仅 converter 自己用）

| 文件 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `daily_totals.json` | `{date_str: {meterId: total}}` | ~100 KB/天 | 跳过历史 Excel 读 |

### SQLite

| 文件 | 行数（30 天） | 用途 |
|------|--------------|------|
| `hourly_meter.db` | ~7M | agent 的 sql_query 工具的 ad-hoc 查询 |

---

## 五、Pipeline 集成

`pipeline/orchestrator.py` 的 6 个阶段中：

1. **ingest** — 读 `output_real/*.json` 进 DataFrame
2. **clean** — 跳过（real data 不需要 IQR 缩尾；用户清洗过）
3. **detect_anomalies** — 验证 `anomalies.json` 格式
4. **predict** — 验证 `predictions*.json` 行数
5. **load_sql** — DROP+CREATE 所有表，从 `output_real/` 重读 JSON，**包括 ATTACH `hourly_meter.db`**
6. **drift** — KS/卡方对比基线（首次运行存基线）

**⚠️ 重要**：阶段 5 现在会从 `--src` 指定目录读 `hourly_meter.db`（之前是 bug，硬编码 mock 路径）。所以运行命令是：

```bash
python pipeline/orchestrator.py \
  --src backend/data/output_real \
  --db backend/data/analytics_real.db
```

Pipeline 是**幂等的全量重跑**：每次都 DROP+CREATE 所有表，从最新 JSON 重建。增量在 converter 层做，pipeline 不感知。

---

## 六、典型工作流

### 首次接入（从零开始）

```bat
REM 1. 转换所有可用 Excel（首次会处理所有 ~150 个文件，~2 小时）
bat\real\convert_real_data.bat

REM 2. 跑 pipeline，建 SQLite (~10s)
bat\real\start_pipeline_real.bat

REM 3. 启动 dashboard（build 时用 USE_REAL_DATA=1）
bat\real\start_dashboard_real.bat

REM 4. 启动 agent（设置 WATER_DATA_DIR + WATER_DB_PATH）
bat\real\start_agent_real.bat
```

### 日常增量（每天新文件）

```bat
REM 早上 8 点：新 Excel 到了
bat\real\convert_real_data.bat              :: ~55s

REM 跑 pipeline 刷新 SQLite
bat\real\start_pipeline_real.bat            :: ~10s

REM 重建 dashboard（数据已变）
bat\real\start_dashboard_real.bat           :: ~5s

REM agent 已经在跑就不动；要重启就
bat\real\start_agent_real.bat
```

### Backfill（旧数据补录）

比如 6/3 突然拿到 4 月份的 Excel 备份：

```bat
bat\real\convert_real_data.bat --since 2026-04-01
```

⚠️ 注意：这只影响 converter 的 daily JSON。**hourly_*.json 是 append-only**，4 月份的小时数据会**追加到现有 5/6 月的 hourly JSONs 后面**——dashboard 看到时间顺序会乱。

正确做法：先 `--full` 重置，或者接受乱序数据（dashboard 可以按 date 字段排序展示）。

### 修正数据错误（converter bug 修了之后）

```bat
REM 删除 cache，强制全量重派生（3 小时）
del backend\data\output_real\daily_totals.json
bat\real\convert_real_data.bat --full

REM 重跑 pipeline + 重建 dashboard
bat\real\start_pipeline_real.bat --force
bat\real\start_dashboard_real.bat
```

#### 快速修补路径（仅 cache + 下游 JSON 重新计算，~30 秒）

适用于 converter 修复属于**纯函数 bug**（如阈值检查、cap 改 abs()、取整）
而非**源数据解析**变化。直接用脚本修补缓存再重生 JSON：

```python
# 修补 cache + data_errors + 重新生成下游
python -X utf8 -u << 'PYEOF'
import sys; sys.path.insert(0, 'scripts')
import real_data_converter as rdc
cache = rdc._load_daily_totals_cache()
# 1. 删掉剩余坏值 + 追加到 data_errors.json
# 2. round(v, 2) 所有值
# 3. 重新调 _build_daily_dma / _build_anomalies / ...
# 4. 写回下游 12 个 JSON
PYEOF

REM 重建 dashboard
USE_REAL_DATA=1 node frontend/build.cjs
```

#### 已知 per-meter 设置错误 → `corrections.json`

第三种"修正"路径：**不修源数据、不改 converter 代码**，只在外部 JSON 加一条：

1. 编辑 `backend/data/corrections.json`，加一条 `{meterId, start, end, factor, reason}`
2. 跑 converter 任意模式（增量 / `--since` / `--full`），修正自动应用
3. 重建 dashboard

适用场景：meter 设置错误（×N / +N 偏移）、某天 meter 实际停用、某建筑集体修正等。
详见 `docs/DEBUGGING_LOG.md` "外部 corrections 文件（meter 712720）" 章节。

---

## 七、限制 & 已知 trade-off

| 限制 | 影响 | 缓解 |
|------|------|------|
| 151 天 hourly_meter.db 满窗口 ~3GB | ATTACH 慢 | 30 天 cap；如需更长可调 `--hourly-window` |
| 异常检测需 14 天 | 冷启动 14 天内 0 异常 | 预期；属于算法约束 |
| Predictions 用 top-50 训练 | 长尾水表的预测不准 | 是设计选择（数据稀疏） |
| `daily_totals.json` 是隐式状态 | 删除后下次跑会当首次 | 有保护（找不到时回退到 --full 行为） |
| Hourly JSONs append-only | backfill 会乱序 | 用 `--full` 重建 |
| 单水表日 cap 4000 m³ | 超过此值视作数据误值并丢弃 | `data_errors.json` 累计记录，异常页可查；详见 `docs/DEBUGGING_LOG.md` "1月8日 4294 万吨误值事件" |
| 已知 per-meter 数据修正（设置错误等） | 修复孤例需要改 converter 代码 | 编辑 `backend/data/corrections.json`（提交到 git），converter 启动时加载，**无需改代码** |

---

## 八、代码入口速查

| 文件 | 作用 |
|------|------|
| `scripts/real_data_converter.py` | Excel → JSON + SQLite 转换器（增量 / 全量 / backfill） |
| `pipeline/orchestrator.py` | 6 阶段 MLOps 管道（ingest → drift） |
| `pipeline/sql_loader.py` | JSON → SQLite 加载器（含 ATTACH hourly_meter.db） |
| `bat/real/convert_real_data.bat` | 转换器入口（透传所有参数） |
| `bat/real/start_pipeline_real.bat` | 管道入口 |
| `bat/real/start_dashboard_real.bat` | dashboard 入口（USE_REAL_DATA=1） |
| `bat/real/start_agent_real.bat` | agent 入口（带端口预检 + 8000 端口） |
