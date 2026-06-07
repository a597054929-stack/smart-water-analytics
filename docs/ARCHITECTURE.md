# 架构总览

## 30 秒速览

| 指标 | 数值 |
|------|------|
| **水表总数** | 9,963 |
| **活跃水表** | 6,630 |
| **日级数据周期** | 151 天 |
| **小时级数据周期** | 30 天 |
| **DMA 区域数** | 4（澳門低區 / 澳門填海A區 / 澳大橫琴區 / 路氹城區） |
| **SQLite 表数** | 10 |
| **Agent 工具数** | 16 |
| **单文件仪表盘大小** | ~5 MB |
| **数据模式** | Mock（500 表 / 125 天）+ 真实（9.9K 表 / 151 天）双分支 |

## 项目是什么

**澳门智慧水务分析平台**——监控各 DMA 区域的用水量、检测异常、预测下
周需求、用自然语言（中/英）回答运维人员的问题。

---

# 图 1：五层整体架构

```
                ┌──────────────────────────────────────┐
                │  0. 数据源（Excel 原始）             │
                │  • 每日 ~25K 行小时读数              │
                │  • 参考文件：水表元数据              │
                │  • 真实数据：9,963 表 / 151 天       │
                │  • Mock 数据：500 表 / 125 天        │
                └─────────────────┬────────────────────┘
                                  │ openpyxl 读
                                  ▼
                ┌──────────────────────────────────────┐
                │  1. 转换器产物（文件系统）            │
                │  • 21 个 JSON 产物 (~60MB)           │
                │  • hourly_meter.db (~4.6M 行)        │
                │  • 3 种运行模式                      │
                └─────────────────┬────────────────────┘
                                  │ 读 JSON
                                  ▼
                ┌──────────────────────────────────────┐
                │  2. Pipeline (7 stage MLOps)         │
                                  │
        ingest → clean → detect → predict → load_sql → drift → data_health
                                  │
                                  ▼
                ┌──────────────────────────────────────┐
                │  3. 服务层                            │
                │     analytics.db (10 张表)            │
                │     OLAP 风格，故意反 3NF             │
                └─────────────┬────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
   ┌────────────────────────┐      ┌────────────────────────────┐
   │  4a. 前端仪表盘         │      │  4b. AI 代理（可选）        │
   │  dashboard.html        │      │  FastAPI :8000             │
   │  (~5MB 单文件)         │◄────►│  LangChain                 │
   │  ECharts + Leaflet     │ SSE  │  Planner-Executor-         │
   │  完全离线可跑          │      │  Synthesizer               │
   └────────────────────────┘      │  16 工具 + text-to-SQL     │
                                    └────────────────────────────┘
                                                  │
                                                  ▼
                                      ┌────────────────────────────┐
                                      │  5. 用户                    │
                                      │     浏览器 / 聊天 UI        │
                                      └────────────────────────────┘
```

---

# 图 2：Pipeline 7 个 Stage 详细流

```
                  ┌──────────────────────────────────────────┐
                  │  输入：output_real/*.json (~60MB)         │
                  └─────────────────────┬────────────────────┘
                                        │
                                        ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │  ingest  │──▶│  clean   │──▶│ detect_  │──▶│ predict  │
   │ JSON→DF  │   │ 质量规则 │   │ anomalies│   │ LightGBM │
   │ 类型化   │   │(real 跳) │   │(当前no-op)│   │  R²0.84  │
   └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘
        │              │              │              │
        │ 每个 stage 写 checkpoint    │              │
        ▼              ▼              ▼              ▼
   ┌────────────────────────────────────────────────────────┐
   │  checkpoints/stage_ingest.json                         │
   │  checkpoints/stage_clean.json                          │
   │  checkpoints/stage_detect.json                         │
   │  checkpoints/stage_predict.json                        │
   └────────────────────────────────────────────────────────┘
                                                       │
                                                       ▼
                                          ┌──────────────────────┐
                                          │  load_sql            │
                                          │  DROP+CREATE         │
                                          │  写 analytics.db     │
                                          │  (含 ATTACH          │
                                          │   hourly_meter.db)  │
                                          └──────────┬───────────┘
                                                     │
                              ┌──────────────────────┼──────────────────────┐
                              ▼                      ▼                      ▼
                    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
                    │  analytics.db    │   │  drift           │   │  data_health     │
                    │  (10 张表)       │◀──│  KS / 卡方       │   │  z-score / 跳变  │
                    │                  │   │  vs baseline     │   │  / 销户对        │
                    └──────────────────┘   └──────────────────┘   └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  reports/        │
                    │  run_summary.md  │
                    └──────────────────┘
```

---

# 图 3：Mock 数据 vs 真实数据分支

```
   ┌─────────────────────────────────┐    ┌─────────────────────────────────┐
   │  Mock 分支（CI / 离线 demo）    │    │  真实数据分支（生产 / 面试 demo）│
   │                                 │    │                                 │
   │  ┌──────────────────┐           │    │  ┌──────────────────┐           │
   │  │ mock_data_       │           │    │  │ 真实 Excel       │           │
   │  │ generator.py     │           │    │  │ ~150 个 .xlsx    │           │
   │  └────────┬─────────┘           │    │  └────────┬─────────┘           │
   │           ▼                     │    │           ▼                     │
   │  ┌──────────────────┐           │    │  ┌──────────────────┐           │
   │  │ output/          │           │    │  │ real_data_       │           │
   │  │ 18 个 JSON       │           │    │  │ converter.py     │           │
   │  └────────┬─────────┘           │    │  │ 增量/全量/倒填   │           │
   │           ▼                     │    │  └────────┬─────────┘           │
   │  ┌──────────────────┐           │    │           ▼                     │
   │  │ analytics.db     │           │    │  ┌──────────────────┐           │
   │  │ 500 表 / 125 天  │           │    │  │ output_real/     │           │
   │  └────────┬─────────┘           │    │  │ 21 JSON +        │           │
   │           ▼                     │    │  │ hourly_meter.db  │           │
   │  ┌──────────────────┐           │    │  │ 9963 表 / 151 天 │           │
   │  │ 本地单 HTML      │           │    │  └────────┬─────────┘           │
   │  │ bundle           │           │    │           ▼                     │
   │  └──────────────────┘           │    │  ┌──────────────────┐           │
   │                                 │    │  │ analytics.db     │           │
   │                                 │    │  │ 9.9K 表 / 151 天 │           │
   │                                 │    │  └────────┬─────────┘           │
   │                                 │    │           ▼                     │
   │                                 │    │  ┌──────────────────┐           │
   │                                 │    │  │ 14 个独立 JSON   │           │
   │                                 │    │  │ 并行加载         │           │
   │                                 │    │  └──────────────────┘           │
   └─────────────────────────────────┘    └─────────────────────────────────┘
```

**关键**：两套数据**完全物理隔离**——不同的目录、不同的 DB、不同的
bat 脚本。切换 = `USE_REAL_DATA=1`，零共享状态。

---

# 图 4：转换器 3 种运行模式

```
                          ┌──────────────────────┐
                          │  Excel 文件落到       │
                          │  source dir           │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  daily_totals.json    │
                          │  缓存存在?             │
                          └──────────┬───────────┘
                                     │
                ┌────────────────────┼────────────────────┐
                │                    │                    │
                ▼                    ▼                    ▼
        ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
        │  默认（增量）│    │  --full      │    │  --since     │
        │  读 last_date│    │  忽略缓存    │    │  倒填指定    │
        │  列 > 缓存   │    │  全部重派生  │    │  日期之后    │
        │  的新文件    │    │              │    │              │
        └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
               │                   │                   │
               └───────────────────┼───────────────────┘
                                   │
                                   ▼
                          ┌──────────────────────┐
                          │  合并: cache +        │
                          │  new_daily            │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  反派生 daily JSON    │
                          │  (~1s 全内存)         │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  append hourly JSON   │
                          │  + INSERT OR IGNORE   │
                          │  hourly_meter.db      │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  写回 cache           │
                          └──────────┬───────────┘
                                     │
                                     ▼
                ┌────────────────────────────────────┐
                │  产出：                              │
                │  • 13 个 daily JSON                  │
                │  • 4 个 hourly JSON                  │
                │  • hourly_meter.db                   │
                └────────────────────────────────────┘
```

**成本对比**：

| 模式 | 耗时 | 何时用 |
|------|------|--------|
| 增量（1 天新数据） | **~55s** | 每天早上定时跑 |
| 全量重派生 | ~2 小时 | Schema 变化、bug 修复 |
| 从 JSON 重派生（不读 Excel） | <1s | 纯函数 bug 修复（`corrections.json`） |

---

# 图 5：Agent Planner-Executor-Synthesizer 流程

```
                        ┌──────────────────────────────────────┐
                        │  用户在浏览器提问                      │
                        │  "比较 3 月和 4 月 Zone-3 用水"        │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │  FastAPI :8000 接收请求              │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  ① Planner (LLM, temperature=0, max_tokens=1024)                │
   │     输入: 用户问题 + 页面上下文 (选中的 DMA/日期)                │
   │     输出: JSON 计划                                                │
   │     [                                                            │
   │       {"tool": "get_anomaly_stats",  "params": {month,dma}},     │
   │       {"tool": "query_daily_dma",    "params": {date,dma}},     │
   │       {"tool": "compare_months",     "params": {m1,m2,dma}},     │
   │       {"tool": "generate_chart",     "params": {chart_type}}     │
   │     ]                                                            │
   └───────────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  ② Executor (确定性调用，无 LLM)                                  │
   │     循环执行 plan 的每个 step：                                    │
   │                                                                   │
   │     for step in plan:                                             │
   │         tool = TOOL_REGISTRY[step.tool]                          │
   │         result = tool.invoke(step.params)                        │
   │         results.append(result)                                   │
   │                                                                   │
   │     工具可能是：                                                   │
   │     • 11 个读 JSON 工具                                          │
   │     • 3 个 text-to-SQL 工具（参数化、只读）                       │
   │     • 1 个页面上下文读取器                                        │
   │     • 1 个 ECharts 图表构建器                                     │
   └───────────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  ③ Synthesizer (LLM, temperature=0, max_tokens=2048)             │
   │     输入: 用户问题 + 计划 + 所有工具结果（截断到 2000 字符/step） │
   │     输出: 自然语言回答（中文 / 英文同语）                          │
   │     规则：包含具体数字、提到生成的图表、承认数据缺失               │
   └───────────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────────┐
                        │  返回 SSE 流：                         │
                        │  {answer, chart, plan, tools_called}   │
                        └──────────────────────────────────────┘
```

**为什么是 3 步 LLM 而不是 1 个 ReAct agent**：
- **Plan 可检查**——出错时能看到 Planner 想干什么，不是黑盒
- **Token 效率**——每次 LLM 调用只看到 focused context
- **强制走完整**——多步查询被明确列出

---

# 图 6：数据库 ER 关系

```
  ┌─────────────────────┐
  │  meters (8 列)       │  ← 水表元信息
  │─────────────────────│
  │  meterId        PK  │
  │  dma                │
  │  propertyType       │
  │  isResidential      │
  │  contractId         │
  │  buildingName       │
  │  supplyMode         │
  │  mainCode           │
  └──────────┬──────────┘
             │ meterId (FK 隐式，SQLite 无外键约束)
   ┌─────────┼──────────────────────────────────────────┐
   │         │          │           │          │          │
   ▼         ▼          ▼           ▼          ▼          ▼
┌────────┐┌────────┐┌──────────┐┌────────┐┌────────┐┌────────┐
│meter_  ││anoma-  ││predic-   ││rank_   ││monthly_││search_ │
│daily   ││lies    ││tions     ││changes ││diff    ││index   │
│(3 列)  ││(12 列) ││(5 列)    ││(9 列)  ││(10 列) ││(5 列)  │
│PK:     ││PK:     ││PK:       ││PK:     ││PK:     ││PK:     │
│meter+  ││date+   ││meter+    ││meterId ││month+  ││id      │
│date    ││meter   ││date      ││        ││mainMtr ││        │
└────────┘└────────┘└──────────┘└────────┘└────────┘└────────┘
                          │
                          │ (无外键，按 building 聚合)
                          ▼
                    ┌──────────────┐
                    │ predictions_ │
                    │ building     │
                    │ (5 列)       │
                    │ PK:          │
                    │ building+    │
                    │ date         │
                    └──────────────┘

  ┌─────────────────────┐
  │  daily_dma (9 列)   │  ← 按日按 DMA 聚合
  │─────────────────────│
  │  date      PK       │
  │  dma       PK       │
  │  total               │
  │  residential         │
  │  nonResidential      │
  │  resCount            │
  │  nonResCount         │
  │  meterCount          │
  │  rain                │
  └──────────┬──────────┘
             │ date
             ▼
  ┌─────────────────────┐
  │  weekly (11 列)     │  ← 周聚合
  │─────────────────────│
  │  weekStart   PK     │
  │  weekEnd            │
  │  label              │
  │  dates              │  ← JSON 数组
  │  totalByDma         │  ← JSON 对象（反 3NF）
  │  grandTotal         │
  │  weekdayAvg         │
  │  weekendAvg         │
  │  wdByDmaRes         │  ← JSON 对象（反 3NF）
  │  rain               │
  │  dailyTotals        │  ← JSON 数组（反 3NF）
  └─────────────────────┘
```

**反 3NF 字段**（OLAP 故意为之）：
- `weekly.totalByDma` / `wdByDmaRes` / `dailyTotals` 是 JSON 字符串
- `anomalies` / `rank_changes` 重复了 `meters` 表的字段（避免 join）
- `monthly_diff.subs` 是逗号分隔字符串

---

# 图 7：典型日更时序

```
 时间  │  角色        │  动作
═══════╪══════════════╪══════════════════════════════════════
 08:00 │  运维        │  新 Excel 落到 source dir
       │              │  双击 bat\real\convert_real_data.bat
       │              ▼
 08:00 │  converter   │  python real_data_converter.py
  ~50s │              │  ├─ 读 cache 找 last_date
       │              │  ├─ 列 > last_date 的新 Excel
       │              │  ├─ openpyxl 读新文件 ~50s
       │              │  ├─ 合并 cache + new_daily
       │              │  ├─ 反派生 daily JSON ~1s
       │              │  ├─ append hourly JSON
       │              │  └─ INSERT OR IGNORE hourly_meter.db
       │              ▼
 08:01 │  运维        │  双击 start_pipeline_real.bat
       │              ▼
 08:01 │  pipeline    │  python orchestrator.py
  ~10s │              │  ├─ ingest（读 output_real/*.json）
       │              │  ├─ clean（real data 跳过）
       │              │  ├─ detect_anomalies（no-op）
       │              │  ├─ predict（LightGBM）
       │              │  ├─ load_sql（DROP+CREATE 写 DB）
       │              │  ├─ drift（vs baseline）
       │              │  └─ data_health（z-score）
       │              ▼
 08:02 │  运维        │  双击 start_dashboard_real.bat
       │              ▼
 08:02 │  build       │  USE_REAL_DATA=1 node build.cjs
  ~5s  │              │  ├─ npm ci
       │              │  ├─ 拷贝 14 个 JSON 到 dist/data/
       │              │  └─ 构建静态资源
       │              ▼
 08:03 │  浏览器      │  http://localhost:5173 自动看到新数据
       │              │
       │   (agent 一直跑着，不重启)                      │
       │              ▼
 任意  │  浏览器      │  点 chat icon 提问
 时间  │              │  ↓
       │  agent       │  Planner-Executor-Synthesizer
       │              │  ↓
       │              │  返回 SSE 流（answer + chart）
```

---

# 图 8：部署拓扑

```
  ┌──────────────────────────────────────────────────────────┐
  │  开发机（你的电脑）                                       │
  │                                                          │
  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
  │  │ Excel    │→ │real_data_│→ │pipeline/ │→ │  agent/  │ │
  │  │ source   │  │converter │  │orchestrtr│  │server.py │ │
  │  │          │  │  .py     │  │  .py     │  │  :8000   │ │
  │  └──────────┘  └──────────┘  └────┬─────┘  └────┬─────┘ │
  │                                   │              │       │
  │                                   ▼              │       │
  │                            ┌──────────┐          │       │
  │                            │analytics │          │       │
  │                            │  .db     │◀─────────┘       │
  │                            └────┬─────┘                  │
  │                                 │                        │
  │                                 ▼                        │
  │                          ┌──────────┐                    │
  │                          │frontend/ │                    │
  │                          │build.cjs │                    │
  │                          │  :5173   │                    │
  │                          └────┬─────┘                    │
  └───────────────────────────────┼──────────────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
       ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
       │ 静态 HTML    │  │ Telegram Bot │  │  VPN 服务器  │
       │ dashboard    │  │ 自动发送     │  │ 内部同事     │
       │  .html       │  │ 更新后的     │  │ 浏览器访问   │
       │ ~5MB 单文件  │  │ dashboard    │  │ 同一静态 HTML│
       │ (可邮件/IM)  │  │              │  │              │
       └──────────────┘  └──────────────┘  └──────────────┘

       可选：FastAPI agent 通过 SSE 回答 chat 问题
            （agent 跑在开发机上，浏览器打 http://开发机IP:8000）
```

---

# 详细说明（文字部分）

## 1. 数据源

- **每日文件**：一天一个 Excel，每行一个水表，列是 24 个小时读数
  （openpyxl 读取）
- **参考文件**：水表元数据——DMA、建筑、物业类型、合同号、供应方式
- 源文件位于 `backend/data/MACAU-reference/`
- 两个生成器：`scripts/real_data_converter.py`（生产）+ 
  `scripts/mock_data_generator.py`（CI / 离线 demo）

## 2. 转换器产物

### 2.1 为什么是 JSON 而不是直接写 DB？

**仪表盘是静态 HTML，运行时无数据库连接**。仪表盘想显示什么，必须
在 build 时**预聚合进 JSON**。这是核心架构决策。

### 2.2 产物清单（真实数据分支）

| 类别 | 文件 | 消费者 |
|------|------|--------|
| **日级聚合** | `daily_dma.json`, `daily_top20.json`, `weekly.json`, `rank_changes.json`, `monthly_main_sub_diff.json`, `cotai_calendar.json`, `anomalies.json`, `predictions.json`, `predictions_fitted.json`, `meter_info.json`, `search_index.json`, `available_dates.json`, `data_errors.json` | 仪表盘所有 tab |
| **小时级聚合** | `hourly_dma.json`, `hourly_calendar.json`, `hourly_top_meters.json`, `peak_hours.json` | 未来 hourly 视图 |
| **小时级明细** | `hourly_meter.db`（~4.6M 行 / 30 天） | Agent 文本转 SQL |
| **内部缓存** | `daily_totals.json`（~100 KB/天） | 仅 converter 用 |

**2026-06-05 移除**：`predictions_by_building.json`——被按 meter 视图
取代，省 ~13KB + 1 次 IPC。

## 3. Pipeline 7 个 Stage

| Stage | 做什么 | 为什么存在 |
|-------|--------|-----------|
| **1. ingest** | 把每个 `output_real/*.json` 读成 `dict[str, DataFrame]` | 解耦 Excel 解析（慢、脆）和 schema 校验（快、确定） |
| **2. clean** | `data_quality.py` 规则作用于 `meter_daily`（real data 跳过） | 数字进 DB 前的信任边界 |
| **3. detect_anomalies** | 重新打分异常（当前 no-op） | 标记真检测器该插入的位置 |
| **4. predict** | 建筑级预测（LightGBM，R² 0.84 vs 线性 0.05） | 预测烤进 DB，仪表盘秒开 |
| **5. load_sql** | 从 DataFrame 写 `analytics.db`（10 张表） | 幂等——重跑同结果；崩溃恢复 = 重跑 |
| **6. drift** | KS（数值）/ 卡方（分类）vs 已存 baseline | 在 schema 漂移毁仪表盘前抓住 |
| **7. data_health** | 单表 z-score、日环比跳变、销户对 | 监控——喂给 `02_health_check.ipynb` |

### 3.1 为什么有 Checkpoint？

每个 stage 写 `stage_<name>.json` 到 `checkpoints/`。如果 stage 4 崩
了，可以 `--resume-from stage_4` 而不用重读所有 Excel。Pipeline 本身
**幂等全量重跑**；增量在 converter 层做，pipeline 不感知。

### 3.2 运行命令

```bash
python pipeline/orchestrator.py \
  --src backend/data/output_real \
  --db  backend/data/analytics_real.db
```

## 4. 服务层（SQLite）

10 张表的 schema 是 **OLAP 风格**（读密集型仪表盘），所以有取舍。

### 4.1 1NF——原子值

| 规则 | 状态 | 备注 |
|------|------|------|
| 无重复组 | ✅ | 所有列原子 |
| TEXT 里藏 JSON | ⚠️ | `weekly.totalByDma`, `weekly.dailyTotals`, `weekly.wdByDmaRes` |

JSON 列是**有意的反范式**——为了仪表盘读取速度（一次读、无 join）。

### 4.2 2NF——无部分依赖

✅ 干净。每张表都是自然单/复合键，无代理键。

### 4.3 3NF——无传递依赖

**故意违反 3NF**。这是 OLAP，不是 OLTP。

| 违反 | 位置 | 为什么 |
|------|------|--------|
| 水表元数据冗余 | `anomalies`, `rank_changes` 重复了 `meters` 表的 `contractId/buildingName/dma/propertyType` | 读性能——异常查看器只读一张表，不 join |
| 逗号分隔多值 | `monthly_diff.subs` = `"12345,67890,..."` | 输出形态——仪表盘把 subs 显示为逗号列表 |
| weekly 里 JSON 聚合 | `totalByDma` = `{"Zone-1": 1234, ...}` | 预先聚合，省每次页面加载的 CPU |

**面试金句**：
> "OLTP 部分（agent 的 text-to-SQL）是 3NF 干净的；OLAP 部分
>（仪表盘）故意反范式——把 join 成本从读路径移到 pipeline 路径。对
> 于 5MB 静态 dashboard 部署是正确取舍。"

## 5. 应用层

### 5.1 Agent（FastAPI :8000）

Planner-Executor-Synthesizer 管线（同一个 LLM，3 个专门 prompt）。
这是生产路径；老的单 ReAct agent 留作 fallback。

**工具清单（16 个）**：
- 11 个读 JSON：`query_meters`, `query_anomalies`, `get_anomaly_stats`,
  `query_daily_dma`, `query_weekly`, `query_rank_changes`,
  `query_monthly_diff`, `get_predictions`, `get_building_predictions`,
  `get_data_overview`, `compare_months`
- 3 个文本转 SQL：`list_tables_tool`, `get_table_schema_tool`, `sql_query`
  （只读、参数化、禁止 DDL/DML）
- 1 个页面上下文读取：让 agent 解析"这周 / 当前 zone"
- 1 个 ECharts 图表构建器：输出 `echarts_option` JSON，前端渲染

**三层容错**：
1. **SQL 自我修正**（`sql_refinement.py`）——坏 SQL 在工具内最多重
   试 2 次，不消耗 ReAct 步骤
2. **回问澄清**（`agent_executor.py` prompt）——含混问题返回中文澄
   清选项，不调工具，每轮最多 1 次
3. **`query_data_quality` 工具**——暴露 converter 级别的数据错误，
   agent 能说"我看到 4 处数据错误"而不是静默污染

**端点**：`/api/chat`（SSE 流）、`/api/chat/sync`、`/api/health`、
`/api/reset`、`/api/history`。对话历史持久化到 `chat_history.json`
（保留最近 6 轮）。

### 5.2 Frontend（Node :5173）

12 个 JS 模块按依赖顺序加载：`home.js`, `trend.js`, `rank.js`,
`diff.js`, `anomaly.js`, `search.js`, `predict.js`, `map.js`,
`calendar.js`, `chat.js`, `tabs.js`, `utils.js`。ECharts 5 + Leaflet，
暗色主题。

**两种加载策略**（build 时由 `USE_REAL_DATA` 决定）：
- Mock 模式：单个 `all_data.json` bundle
- Real 模式：14 个独立 JSON 并行加载，再按 `DIRECT/INDIRECT` 分流
  避免子表重复计量

## 6. 测试与评估

| 测试层 | 数量 | 耗时 | 测什么 |
|--------|------|------|--------|
| 单元（pytest） | 104 | ~37s | 纯逻辑，不调 LLM |
| LLM QA（evaluate.py） | 30 | ~10 分钟 | 真模型调用，按工具准确率、关键词召回、行为通过/失败、延迟、失败率打分 |

**最新运行**：通过率 76.7%，失败率 0%，语义通过 93%。

**Schema 完整性测试**：grep 系统 prompt 里的 `FROM <table>` 引用，
断言在真实 SQLite DB 里存在——抓住"工具改名了但 prompt 没改"的情
况。

## 7. 典型工作流

### 7.1 首次接入（真实数据）

```bat
REM 1. 转换所有 Excel（首次 ~2 小时 / 151 天）
bat\real\convert_real_data.bat

REM 2. 跑 pipeline，建 SQLite（~10s）
bat\real\start_pipeline_real.bat

REM 3. 用真实数据构建仪表盘
bat\real\start_dashboard_real.bat

REM 4. 启动 agent
bat\real\start_agent_real.bat
```

### 7.2 每日增量

```bat
bat\real\convert_real_data.bat              REM ~55s
bat\real\start_pipeline_real.bat            REM ~10s
bat\real\start_dashboard_real.bat           REM ~5s
REM agent 保持运行
```

### 7.3 倒填（旧数据补录）

```bat
bat\real\convert_real_data.bat --since 2026-04-01
```

⚠️ Hourly JSONs 是 append-only——倒填会打乱时间序。要么 `--full` 重
置，要么让仪表盘按 `date` 字段排序。

### 7.4 单表数据修正（不改代码）

编辑 `backend/data/corrections.json` 加 `{meterId, start, end, factor,
reason}`。下次 converter 跑时自动应用。用于：
- 水表设置错误（×N / +N 偏移）
- 水表某天停用
- 整栋建筑集体修正

## 8. Trade-off 与已知限制

| 限制 | 影响 | 缓解 |
|------|------|------|
| `hourly_meter.db` 30 天上限 | ATTACH 在 ~7M 行后变慢 | 可调 `--hourly-window` |
| 异常检测需 14 天 | 冷启动前 14 天 0 异常 | 算法约束；预期行为 |
| Top-50 预测模型 | 长尾水表预测不准 | 设计选择（数据稀疏） |
| `daily_totals.json` 是隐式状态 | 删了触发下次 `--full` | 有 fallback 到首次运行行为 |
| Hourly JSONs append-only | 倒填会乱序 | `--full` 重置 |
| 单表日 cap 4000 m³ | 超过视为误值丢弃 | 记到 `data_errors.json`，异常页可查 |
| 单表数据修正 | 默认要改 converter 代码 | `corrections.json` 外部文件——不改代码 |

## 9. 代码入口速查

| 文件 | 作用 |
|------|------|
| `scripts/real_data_converter.py` | Excel → JSON + SQLite（3 种运行模式） |
| `scripts/mock_data_generator.py` | 合成数据生成器 |
| `pipeline/orchestrator.py` | 7 stage MLOps 管线 + checkpoint |
| `pipeline/sql_loader.py` | JSON → SQLite 加载器（ATTACH `hourly_meter.db`） |
| `pipeline/schema.py` | 10 个 Pandera schema（数据契约） |
| `pipeline/data_quality.py` | `meter_daily` 清洗规则 |
| `agent/server.py` | FastAPI 入口（`/api/chat` SSE） |
| `agent/multi_agent.py` | Planner-Executor-Synthesizer 管线 |
| `agent/agent_tools.py` | 16 个工具实现 |
| `agent/sql_refinement.py` | SQL 自我修正（重试坏查询） |
| `frontend/build.cjs` | 静态站构建（`USE_REAL_DATA` 感知） |
| `bat/real/*.bat` | Windows 一键入口脚本 |

## 10. 部署

| 模式 | 运行什么 | 何时 |
|------|----------|------|
| **静态 HTML** | 只有 `frontend/dist/dashboard.html` | 分享、Telegram、邮件、无服务器 |
| **Docker Compose** | `agent`（Python）+ `dashboard`（Node）两个服务 | 本地开发 |
| **内部服务器** | 静态 HTML 放 VPN 后 | 生产供运维团队 |

仪表盘**完全离线**可用（所有数据内联）。Agent 是**可选**——没有
agent 仪表盘照样跑。

---

# 11. 工程基座（Engineering Foundation）

不是业务功能，而是支撑业务功能的基础设施层。

## 11.1 依赖与打包

| 文件 | 角色 |
|------|------|
| `requirements.txt` | 最低版本声明（`>=`），给人用 |
| `requirements.lock.txt` | 当前环境的精确锁版本，给 CI 用 |
| `pyproject.toml` | 项目元数据、dev 依赖、工具配置（ruff/pytest/mypy） |
| `.github/workflows/ci.yml` | CI：lint (ruff) + test (pytest) 用 lock 文件 |

CI 流程：`pip install -r requirements.lock.txt` → `ruff check .` →
`pytest tests/`。

## 11.2 日志（`pipeline/logger.py`）

基于 `structlog`：
- 每行一个 JSON 对象（`ts`/`level`/`logger`/`message`/`run_id`）
- `run_id` 通过 `structlog.contextvars.bind_contextvars` 在整条管道
  传播，同一 run 的所有日志行带同一 `run_id`
- `stage(name)` 上下文管理器自动记录 `stage_start` / `stage_done` /
  `stage_failed` + `elapsed_s`
- 输出双写：stdout（`tail -f` 看实时） + `logs/pipeline.log`（事后回放）

公共 API：`new_run_id` / `get_run_id` / `set_run_id` / `get_logger` /
`stage`。5 个调用方（`orchestrator.py` / `sql_loader.py` / `validators.py`
/ `data_quality.py` / `drift.py`）无需修改。

## 11.3 数据契约（`pipeline/schema.py`）

10 个 Pandera `DataFrameSchema`，在 stage 边界验证：
`MetersSchema` / `DailyDmaSchema` / `HourlyMeterSchema` / `AnomaliesSchema`
/ `PredictionsSchema` / `RankChangesSchema` / `SearchIndexSchema` /
`CotaiCalendarSchema` / `WeeklySchema` / `MonthlyDiffSchema`。

`tests/test_pipeline.py::TestSchemaValidation` 故意构造坏 DataFrame
验证 schema 会拒绝它。详见 [ADR-0002](adr/0002-pandera-做-schema-校驗.md)。

## 11.4 FastAPI 端点契约

`agent/server.py` 8 个端点全都有 `response_model` + `tags` + `summary`：

| 端点 | Tags | 说明 |
|------|------|------|
| `POST /api/chat` | chat | 流式 SSE，含 tool 事件和最终答案 |
| `POST /api/chat/sync` | chat | 非流式 fallback |
| `GET /api/health` | utility | liveness + 会话轮数 |
| `POST /api/reset` | utility | 清空对话历史 |
| `GET /api/history` | utility | 最近 6 轮 |
| `GET /api/questions` | analytics | 完整问题日志（供分析） |
| `GET /api/metrics` | analytics | Prometheus 风格 Counter |
| `GET /docs` | (auto) | Swagger UI |

Swagger UI 自动生成在 `/docs`，可浏览可测试。`/api/metrics` 提供
4 个 counter：`chat_requests_total{mode}` / `tool_calls_total{tool_name}`
/ `chat_failures_total` / `questions_logged_total`，全部在内存中
（process 重启清零，适合速率计算）。

## 11.5 共享测试 fixture（`tests/conftest.py`）

`tmp_ckpt` / `db_path` / `pipeline_output` 三个 fixture 提到共享文件，
新增测试文件直接 `import pytest` 即可用，不必重复样板。

## 11.6 Docker HEALTHCHECK

`Dockerfile` 末尾有：

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1
```

`docker inspect` 看 `State.Health.Status` 即可；K8s 的 `livenessProbe`
可以直接复用 `api/health`。

## 11.7 Architecture Decision Records（`docs/adr/`）

3 篇 ADR 用 MADR 格式记录「为什么这么选」：

| # | 主题 | 结论 |
|---|------|------|
| [0001](adr/0001-使用-sqlite-不-postgres.md) | SQLite vs PostgreSQL | SQLite — 零运维、單檔案、測試友善 |
| [0002](adr/0002-pandera-做-schema-校驗.md) | Pandera vs Pydantic | Pandera — 為 DataFrame 設計，運行時校驗 |
| [0003](adr/0003-monorepo-單倉多組件.md) | monorepo vs polyrepo | 單倉 — 跨組件 refactor 容易、CI 統一 |

新决策 → 复制 `template.md` → 顺序编号 → 更新 `docs/adr/README.md` 索引。

