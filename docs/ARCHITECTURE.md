# 架构总览

> **最后更新**：2026-06-08
> **维护者**：李志泉
> **本文档是项目权威架构说明**。如其他文档（如 `README.md`、
> `GLOSSARY.md`）与本文档冲突，**以本文档为准**。

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

## 怎么读这份文档

| 你的需求 | 看哪一节 |
|---------|---------|
| 30 秒了解项目 | 速览表 + 图 1 |
| 讲给面试官 | 图 1 + 3NF 分析 + 12.1 Agent 工具清单 |
| 加一个新工具 | Cookbook 第 1 条 + 第 17 节代码入口 |
| 修数据 bug | 第 14.4 节 corrections.json |
| 部署到新机器 | 第 16 节 + bat 脚本 |
| 面试被追问 deep dive | 3NF + 图 6 ER + 预测故事 |
| 想知道"为什么这么设计" | 演进记录 + 3NF 分析 |

## 目录

1. [图 1：五层整体架构](#图-1五层整体架构)
2. [图 2：Pipeline 7 个 Stage](#图-2pipeline-7-个-stage-详细流)
3. [图 3：Mock vs 真实数据分支](#图-3mock-数据-vs-真实数据分支)
4. [图 4：转换器 3 种运行模式](#图-4转换器-3-种运行模式)
5. [图 5：Agent PES 流程](#图-5agent-planner-executor-synthesizer-流程)
6. [图 6：数据库 ER 关系](#图-6数据库-er-关系)
7. [图 7：典型日更时序](#图-7典型日更时序)
8. [图 8：部署拓扑](#图-8部署拓扑)
9. [数据存储详解](#9-数据存储详解)
10. [Pipeline 7 Stage 详解](#10-pipeline-7-stage-详解)
11. [3NF 分析](#11-3nf-分析)
12. [应用层](#12-应用层)
13. [测试与评估](#13-测试与评估)
14. [典型工作流](#14-典型工作流)
15. [Trade-off 与限制](#15-trade-off-与限制)
16. [部署](#16-部署)
17. [代码入口速查](#17-代码入口速查)
18. [Cookbook：常见任务](#18-cookbook常见任务)
19. [演进记录](#19-演进记录)

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
                │  • 13 个 daily JSON (~60MB)          │
                │  • 4 个 hourly JSON                  │
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
   │  └────────┬─────────┘           │    │  │ 13 JSON +        │           │
   │           ▼                     │    │  │ 4 hourly JSON +  │           │
   │  ┌──────────────────┐           │    │  │ hourly_meter.db  │           │
   │  │ 本地单 HTML      │           │    │  │ 9963 表 / 151 天 │           │
   │  │ bundle           │           │    │  └────────┬─────────┘           │
   │  └──────────────────┘           │    │           ▼                     │
   │                                 │    │  ┌──────────────────┐           │
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

# 9. 数据存储详解

## 9.1 为什么是 JSON 而不是直接写 DB？

**仪表盘是静态 HTML，运行时无数据库连接**。仪表盘想显示什么，必须
在 build 时**预聚合进 JSON**。这是核心架构决策。

## 9.2 产物清单（真实数据分支 `output_real/`）

### 9.2.1 Daily aggregates（13 个 JSON，仪表盘主用）

| 文件 | 形态 | 大小 | 备注 |
|------|------|------|------|
| `daily_dma.json` | `[{date, dmas: {dma: {...}}}]` | ~3 KB/天 | 4 个 DMA × res/nonRes 拆分 |
| `daily_top20.json` | `[{date, top20: [{meterId, total, ...}]}]` | ~5 KB/天 | 每日 Top-20 |
| `weekly.json` | `[{weekStart, ..., dailyTotals}]` | ~3 KB/周 | 7 天滚动聚合 |
| `rank_changes.json` | `[{meterId, daysInTop20, avgRank, ...}]` | ~8 KB | 全期累计 |
| `monthly_main_sub_diff.json` | `[{month, diffs: [...]}]` | ~10-30 KB/月 | 主-分表差（NRW） |
| `cotai_calendar.json` | `[{date, items: [...]}]` | 视路氹城區活动量 | 非住宅 Top-15 |
| `anomalies.json` | `[{date, meterId, type, score, ...}]` | 视异常数量 | 14 天滚动窗口 |
| `predictions.json` | `{predictions: [...]}` | ~46 KB | Top-50 预测 |
| `predictions_fitted.json` | `{fitted: [...]}` | ~16 KB | 历史拟合值 |
| `meter_info.json` | `{meterId: {dma, propertyType, ...}}` | ~2.5 MB | 水表元数据 |
| `search_index.json` | `[{id, contract, building, dma, type}]` | ~1.5 MB | 模糊搜索索引 |
| `available_dates.json` | `["2026-01-01", ...]` | <1 KB | 排序日期列表 |
| `data_errors.json` | `[{date, meterId, rawValue, reason}]` | ~8 KB | 误值累计（>4000 m³/日） |

**2026-06-05 移除**：`predictions_by_building.json`——被按 meter 视图
取代，节省 ~13KB + 1 次 IPC。

### 9.2.2 Hourly aggregates（4 个 JSON，仪表盘未来用）

| 文件 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `hourly_dma.json` | `[{date, hour, dmas: {dma: total}}]` | ~6 KB/天 | 24h × DMA 折线图 |
| `hourly_calendar.json` | `[{date, hours: [v0..v23]}]` | <1 KB/天 | 24h 热力图 |
| `hourly_top_meters.json` | `[{date, top: [...]}]` | ~7 KB/天 | 高耗水户 24h 画像 |
| `peak_hours.json` | `[{date, dma, peakHour, ...}]` | ~2 KB/天 | 峰谷分析（18:00-22:00） |

### 9.2.3 Hourly detail（嵌套 SQLite）

| 文件 | 行数（30 天） | 用途 |
|------|--------------|------|
| `hourly_meter.db` | ~4.6M | agent 的 sql_query 工具的 ad-hoc 查询 |

### 9.2.4 Internal cache（仅 converter 自用）

| 文件 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `daily_totals.json` | `{date_str: {meterId: total}}` | ~100 KB/天 | 跳过历史 Excel 重读 |

**Converter 保护**：
> "The cache is safe to delete: the next run will fall back to processing every available Excel file (effectively --full)."

## 9.3 真实数据 vs Mock 数据文件差异

| 类别 | Mock 有 | Real 有 |
|------|---------|---------|
| meter_daily.json | ✅ | ❌ **缺**（影响 Stage 3 残差分析） |
| daily_top20_by_dma.json | ✅ | ❌ |
| daily_total_by_dma.json | ✅ | ❌ |
| model_comparison.json | ✅ | ❌ |
| data_errors.json | ❌ | ✅ |
| 4 个 hourly JSON | ❌ | ✅ |
| hourly_meter.db | ❌ | ✅ |
| daily_totals.json (cache) | ❌ | ✅ |

---

# 10. Pipeline 7 Stage 详解

| Stage | 中文 | 做什么 | 真数据时是否干活 |
|-------|------|-----------|---------------|
| 1 `ingest` | 数据摄取 | 读 13 个 JSON → 13 个 DataFrame | ✅ 干 |
| 2 `clean` | 数据清洗 | 质量规则作用于 `meter_daily` | ⚠️ No-op（已清洗） |
| 3 `detect_anomalies` | 异常校验 | Pandera 校验 + 统计 by_type/by_dma | ⚠️ 只校验不算 |
| 4 `predict` | 预测校验 | 行数检查 | ⚠️ 只校验不算 |
| 5 `load_sql` | 写 SQLite | DROP+CREATE 10 张表 + ATTACH hourly_meter.db | ✅ 干 |
| 6 `drift` | 漂移检测 | KS（数值）+ 卡方（分类）vs baseline | ✅ 干（首次存 baseline） |
| 7 `data_health` | 健康检查 | 单表 z-score + 跳变 + 销户对 | ✅ 干（监控） |

每个 stage 详细说明见 `GLOSSARY.md` 和 pipeline 代码注释。

**运行命令**：
```bash
python pipeline/orchestrator.py \
  --src backend/data/output_real \
  --db  backend/data/analytics_real.db
```

---

# 11. 3NF 分析

10 张表的 schema 是 **OLAP 风格**（读密集型仪表盘），所以有取舍。

## 11.1 1NF——原子值

| 规则 | 状态 | 备注 |
|------|------|------|
| 无重复组 | ✅ | 所有列原子 |
| TEXT 里藏 JSON | ⚠️ | `weekly.totalByDma`, `weekly.dailyTotals`, `weekly.wdByDmaRes` |

JSON 列是**有意的反范式**——为了仪表盘读取速度（一次读、无 join）。

## 11.2 2NF——无部分依赖

✅ 干净。每张表都是自然单/复合键，无代理键。

## 11.3 3NF——无传递依赖

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

---

# 12. 应用层

## 12.1 Agent（FastAPI :8000）

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

## 12.2 Frontend（Node :5173）

12 个 JS 模块按依赖顺序加载：`home.js`, `trend.js`, `rank.js`,
`diff.js`, `anomaly.js`, `search.js`, `predict.js`, `map.js`,
`calendar.js`, `chat.js`, `tabs.js`, `utils.js`。ECharts 5 + Leaflet，
暗色主题。

**两种加载策略**（build 时由 `USE_REAL_DATA` 决定）：
- Mock 模式：单个 `all_data.json` bundle
- Real 模式：14 个独立 JSON 并行加载，再按 `DIRECT/INDIRECT` 分流
  避免子表重复计量

---

# 13. 测试与评估

| 测试层 | 数量 | 耗时 | 测什么 |
|--------|------|------|--------|
| 单元（pytest） | 104 | ~37s | 纯逻辑，不调 LLM |
| LLM QA（evaluate.py） | 30 | ~10 分钟 | 真模型调用，按工具准确率、关键词召回、行为通过/失败、延迟、失败率打分 |

**最新运行**：通过率 76.7%，失败率 0%，语义通过 93%。

**Schema 完整性测试**：grep 系统 prompt 里的 `FROM <table>` 引用，
断言在真实 SQLite DB 里存在——抓住"工具改名了但 prompt 没改"的情
况。

---

# 14. 典型工作流

## 14.1 首次接入（真实数据）

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

## 14.2 每日增量

```bat
bat\real\convert_real_data.bat              REM ~55s
bat\real\start_pipeline_real.bat            REM ~10s
bat\real\start_dashboard_real.bat           REM ~5s
REM agent 保持运行
```

## 14.3 倒填（旧数据补录）

```bat
bat\real\convert_real_data.bat --since 2026-04-01
```

⚠️ Hourly JSONs 是 append-only——倒填会打乱时间序。要么 `--full` 重
置，要么让仪表盘按 `date` 字段排序。

## 14.4 单表数据修正（不改代码）

编辑 `backend/data/corrections.json` 加 `{meterId, start, end, factor,
reason}`。下次 converter 跑时自动应用。用于：
- 水表设置错误（×N / +N 偏移）
- 水表某天停用
- 整栋建筑集体修正

---

# 15. Trade-off 与限制

| 限制 | 影响 | 缓解 |
|------|------|------|
| `hourly_meter.db` 30 天上限 | ATTACH 在 ~7M 行后变慢 | 可调 `--hourly-window` |
| 异常检测需 14 天 | 冷启动前 14 天 0 异常 | 算法约束；预期行为 |
| Top-50 预测模型 | 长尾水表预测不准 | 设计选择（数据稀疏） |
| `daily_totals.json` 是隐式状态 | 删了触发下次 `--full` | 有 fallback 到首次运行行为 |
| Hourly JSONs append-only | 倒填会乱序 | `--full` 重置 |
| 单表日 cap 4000 m³ | 超过视为误值丢弃 | 记到 `data_errors.json`，异常页可查 |
| Mock 缺 `meter_daily.json` | Stage 3 残差分析无法跑 | 加 `meter_daily.json` 到 mock generator |
| 单表数据修正 | 默认要改 converter 代码 | `corrections.json` 外部文件——不改代码 |
| 单小时单表更新 | 当前架构不支持局部重派生 | 待加 `patches.json` 机制 |

---

# 16. 部署

| 模式 | 运行什么 | 何时 |
|------|----------|------|
| **静态 HTML** | 只有 `frontend/dist/dashboard.html` | 分享、Telegram、邮件、无服务器 |
| **Docker Compose** | `agent`（Python）+ `dashboard`（Node）两个服务 | 本地开发 |
| **内部服务器** | 静态 HTML 放 VPN 后 | 生产供运维团队 |

仪表盘**完全离线**可用（所有数据内联）。Agent 是**可选**——没有
agent 仪表盘照样跑。

---

# 17. 代码入口速查

| 文件 | 作用 |
|------|------|
| `scripts/real_data_converter.py` | Excel → JSON + SQLite（3 种运行模式） |
| `scripts/mock_data_generator.py` | 合成数据生成器 |
| `pipeline/orchestrator.py` | 7 stage MLOps 管线 + checkpoint |
| `pipeline/sql_loader.py` | JSON → SQLite 加载器（ATTACH `hourly_meter.db`） |
| `pipeline/schema.py` | 11 个 Pandera schema（数据契约） |
| `pipeline/data_quality.py` | `meter_daily` 清洗规则 |
| `agent/server.py` | FastAPI 入口（`/api/chat` SSE + `/api/metrics`） |
| `agent/multi_agent.py` | Planner-Executor-Synthesizer 管线 |
| `agent/agent_tools.py` | 16 个工具实现（全部 `@safe_tool_call` 装饰） |
| `agent/sql_refinement.py` | SQL 自我修正（重试坏查询） |
| `agent/memory_compressor.py` | 两段式记忆：近期原文 + 旧摘要 |
| `agent/dangerous_paths.py` | 路径黑名单（`.env`/`/etc`/`C:/Windows`） |
| `agent/tool_audit.py` | JSONL 工具调用审计日志 |
| `agent/safe_tool_call.py` | 装饰器：超时 + 路径检查 + 审计 |
| `frontend/build.cjs` | 静态站构建（`USE_REAL_DATA` 感知 + 敏感资料保护注入） |
| `bat/real/*.bat` | Windows 一键入口脚本 |

---

# 18. Cookbook：常见任务

### 加一个 Agent 工具
1. `agent/agent_tools.py` 加新函数 + 注册到 `ALL_TOOLS`
2. `agent/multi_agent.py` 的 `PLANNER_PROMPT` 工具列表加一行
3. `tests/test_agent_tools.py` 加单测
4. 重启 agent

### 加一张 SQL 表
1. `pipeline/schema.py` 加新 Pandera schema + 注册到 `SCHEMA_REGISTRY`
2. `pipeline/sql_loader.py` 加写入函数
3. `agent/sql_tools.py` 的 `get_table_schema_tool` 会自动看到
4. 跑 pipeline 验证

### 改预测模型
1. 改 `scripts/real_data_converter.py` 的预测调用
2. 跑 `--full` 重派生
3. 跑 `evaluate.py` 看 R²

### 修一个水表某天数据错了
1. 编辑 `backend/data/corrections.json` 加 `{meterId, start, end, factor, reason}`
2. 跑 `convert_real_data.bat`（任何模式都行）
3. 跑 pipeline + 重建 dashboard

### 加一个新 DMA
1. 在 `pipeline/schema.py` 的 `VALID_DMAS` 加 DMA 名
2. converter + pipeline 会自动识别

---

# 19. 演进记录

| 日期 | 改动 | 原因 |
|------|------|------|
| 2026-06-04 | 接入真实数据分支 | demo 数据展示不出真实模式 |
| 2026-06-05 | 移除 `predictions_by_building.json` | 被 per-meter 视图取代 |
| 2026-06-05 | 加 `corrections.json` 外部修正机制 | 不改代码修单表数据 |
| 2026-06-08 | 合并 `REAL_DATA_ARCHITECTURE.md` 进本文件 | 消除权威混淆 |
| 2026-06-08 | **加两段式记忆**（`agent/memory_compressor.py`） | 长对话 token 爆掉 → 摘要压缩 + 滑动窗口 |
| 2026-06-08 | **加工具沙盒**（`safe_tool_call` 装饰器 + `tool_audit.py` + `dangerous_paths.py`） | 16 个工具裸跑 → 加超时 + 路径黑名单 + JSONL 审计 |
| 2026-06-08 | **加 harness 回归**（`tests/harness/agent_behaviors.json`，30 case） | prompt 改动无 fail-fast 保护 → mock-LLM 离线回归 |
| 2026-06-08 | **加 ADR-0004**（`docs/adr/0004-claude-code-design.md`） | 业界标杆参考 + 后续改进有 ADR 兜底 |
| 2026-06-08 | **Stage 3 残差分析**（`orchestrator.py`） | detect_anomalies 加 RMSE/MAE/bias，JOIN predictions vs meter_daily |
| 2026-06-08 | **Stage 4 Pandera 校验**（`schema.py` + `orchestrator.py`） | 新增 `PredictionsBuildingRowSchema`，`PredictionRowSchema` lower/upper 改 nullable |
| 2026-06-08 | **敏感资料保护修复**（`build.cjs`） | `USE_REAL_DATA=1` 注入密码解锁逻辑，mock 模式保持开放 |
| 2026-06-08 | **清除真实 meter ID**（`corrections.json` + `qa_pairs.json`） | 712720→MOCK0001, 753832→MOCK7538 |
| 待加 | `patches.json` 单点更新 | 修单水表单小时数据 |
| 待加 | mock 数据补 `meter_daily.json` | 让 Stage 3 残差分析两边都能跑 |

---

> **再次强调**：本文档是**架构权威**。如其他文件（`README.md`、
> `GLOSSARY.md`、代码注释、CHANGELOG）信息与本文档冲突，**以本文档为准**。
> 改动架构时，**先改本文档，再改代码**。
