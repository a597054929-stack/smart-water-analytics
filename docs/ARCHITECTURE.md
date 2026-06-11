# 架構總览

> **最後更新**：2026-06-08
> **維護者**：李志泉
> **本文件是項目權威架構說明**。如其他文件（如 `README.md`、
> `GLOSSARY.md`）與本文件冲突，**以本文件為準**。

## 30 秒速览

| 指標 | 數值 |
|------|------|
| **水表總數** | 9,963 |
| **活跃水表** | 6,630 |
| **日級數據周期** | 151 天 |
| **小時級數據周期** | 30 天 |
| **DMA 區域數** | 4（澳門低區 / 澳門填海A區 / 澳大橫琴區 / 路氹城區） |
| **SQLite 表數** | 10 |
| **Agent 工具數** | 16 |
| **單檔案仪表盘大小** | ~5 MB |
| **數據模式** | Mock（500 表 / 125 天）+ 真實（9.9K 表 / 151 天）雙分支 |

## 項目是什麼

**澳門智慧水務分析平臺**——監察各 DMA 區域的用水量、检測異常、预測下
周需求、用自然語言（中/英）回答運維人員的問題。

## 怎麼讀這份文件

| 你的需求 | 看哪一節 |
|---------|---------|
| 30 秒了解項目 | 速览表 + 圖 1 |
| 加一個新工具 | Cookbook 第 1 條 + 第 17 節代碼入口 |
| 修數據 bug | 第 14.4 節 corrections.json |
| 部署到新機器 | 第 16 節 + bat 腳本 |

## 目錄

1. [圖 1：五層整體架構](#圖-1五層整體架構)
2. [圖 2：Pipeline 7 個 Stage](#圖-2pipeline-7-個-stage-详細流)
3. [圖 3：Mock vs 真實數據分支](#圖-3mock-數據-vs-真實數據分支)
4. [圖 4：轉換器 3 種運行模式](#圖-4轉換器-3-種運行模式)
5. [圖 5：Agent PES 流程](#圖-5agent-planner-executor-synthesizer-流程)
6. [圖 6：數據庫 ER 關系](#圖-6數據庫-er-關系)
7. [圖 7：典型日更時序](#圖-7典型日更時序)
8. [圖 8：部署拓扑](#圖-8部署拓扑)
9. [數據存储详解](#9-數據存储详解)
10. [Pipeline 7 Stage 详解](#10-pipeline-7-stage-详解)
11. [3NF 分析](#11-3nf-分析)
12. [應用層](#12-應用層)
13. [測試與評估](#13-測試與評估)
14. [典型工作流](#14-典型工作流)
15. [Trade-off 與限制](#15-trade-off-與限制)
16. [部署](#16-部署)
17. [代碼入口速查](#17-代碼入口速查)
18. [Cookbook：常見任務](#18-cookbook常見任務)
19. [演進記錄](#19-演進記錄)

---

# 圖 1：五層整體架構

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

# 圖 2：Pipeline 7 個 Stage 详細流

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

# 圖 3：Mock 數據 vs 真實數據分支

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

**關键**：兩套數據**完全物理隔离**——不同的目錄、不同的 DB、不同的
bat 腳本。切換 = `USE_REAL_DATA=1`，零共享狀態。

---

# 圖 4：轉換器 3 種運行模式

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

**成本對比**：

| 模式 | 耗時 | 何時用 |
|------|------|--------|
| 增量（1 天新數據） | **~55s** | 每天早上定時跑 |
| 全量重派生 | ~2 小時 | Schema 變化、bug 修復 |
| 從 JSON 重派生（不讀 Excel） | <1s | 純函數 bug 修復（`corrections.json`） |

---

# 圖 5：Agent Planner-Executor-Synthesizer 流程

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
   │       {"tool": "query_consumption", "params": {mode:"daily", date, dma}},     │
   │       {"tool": "query_consumption", "params": {mode:"compare", month1, month2, dma}},     │
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

**為什麼是 3 步 LLM 而不是 1 個 ReAct agent**：
- **Plan 可检查**——出錯時能看到 Planner 想乾什麼，不是黑盒
- **Token 效率**——每次 LLM 調用只看到 focused context
- **強制走完整**——多步查询被明確列出

---

# 圖 6：數據庫 ER 關系

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
  │  totalByDma         │  ← JSON 对象
  │  grandTotal         │
  │  weekdayAvg         │
  │  weekendAvg         │
  │  wdByDmaRes         │  ← JSON 对象
  │  rain               │
  │  dailyTotals        │  ← JSON 数组
  └─────────────────────┘
```

- `weekly.totalByDma` / `wdByDmaRes` / `dailyTotals` 是 JSON 字串
- `anomalies` / `rank_changes` 重復了 `meters` 表的欄位（避免 join）
- `monthly_diff.subs` 是逗號分隔字串

---

# 圖 7：典型日更時序

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

# 圖 8：部署拓扑

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

# 9. 數據存储详解

## 9.1 為什麼是 JSON 而不是直接寫 DB？

**仪表盘是靜态 HTML，運行時无數據庫連接**。仪表盘想顯示什麼，必须
在 build 時**预聚合進 JSON**。這是核心架構決策。

## 9.2 產物清單（真實數據分支 `output_real/`）

### 9.2.1 Daily aggregates（13 個 JSON，仪表盘主用）

| 檔案 | 形态 | 大小 | 備注 |
|------|------|------|------|
| `daily_dma.json` | `[{date, dmas: {dma: {...}}}]` | ~3 KB/天 | 4 個 DMA × res/nonRes 拆分 |
| `daily_top20.json` | `[{date, top20: [{meterId, total, ...}]}]` | ~5 KB/天 | 每日 Top-20 |
| `weekly.json` | `[{weekStart, ..., dailyTotals}]` | ~3 KB/周 | 7 天滾動聚合 |
| `rank_changes.json` | `[{meterId, daysInTop20, avgRank, ...}]` | ~8 KB | 全期累計 |
| `monthly_main_sub_diff.json` | `[{month, diffs: [...]}]` | ~10-30 KB/月 | 主-分表差（NRW） |
| `cotai_calendar.json` | `[{date, items: [...]}]` | 视路氹城區活動量 | 非住宅 Top-15 |
| `anomalies.json` | `[{date, meterId, type, score, ...}]` | 视異常數量 | 14 天滾動視窗 |
| `predictions.json` | `{predictions: [...]}` | ~46 KB | Top-50 预測 |
| `predictions_fitted.json` | `{fitted: [...]}` | ~16 KB | 歷史拟合值 |
| `meter_info.json` | `{meterId: {dma, propertyType, ...}}` | ~2.5 MB | 水表元數據 |
| `search_index.json` | `[{id, contract, building, dma, type}]` | ~1.5 MB | 模糊搜索索引 |
| `available_dates.json` | `["2026-01-01", ...]` | <1 KB | 排序日期列表 |
| `data_errors.json` | `[{date, meterId, rawValue, reason}]` | ~8 KB | 誤值累計（>4000 m³/日） |

**2026-06-05 移除**：`predictions_by_building.json`——被按 meter 视圖
取代，節省 ~13KB + 1 次 IPC。

### 9.2.2 Hourly aggregates（4 個 JSON，仪表盘未來用）

| 檔案 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `hourly_dma.json` | `[{date, hour, dmas: {dma: total}}]` | ~6 KB/天 | 24h × DMA 折線圖 |
| `hourly_calendar.json` | `[{date, hours: [v0..v23]}]` | <1 KB/天 | 24h 熱力圖 |
| `hourly_top_meters.json` | `[{date, top: [...]}]` | ~7 KB/天 | 高耗水戶 24h 畫像 |
| `peak_hours.json` | `[{date, dma, peakHour, ...}]` | ~2 KB/天 | 峰谷分析（18:00-22:00） |

### 9.2.3 Hourly detail（嵌套 SQLite）

| 檔案 | 行數（30 天） | 用途 |
|------|--------------|------|
| `hourly_meter.db` | ~4.6M | agent 的 sql_query 工具的 ad-hoc 查询 |

### 9.2.4 Internal cache（仅 converter 自用）

| 檔案 | 形态 | 大小 | 用途 |
|------|------|------|------|
| `daily_totals.json` | `{date_str: {meterId: total}}` | ~100 KB/天 | 跳過歷史 Excel 重讀 |

**Converter 保護**：
> "The cache is safe to delete: the next run will fall back to processing every available Excel file (effectively --full)."

## 9.3 真實數據 vs Mock 數據檔案差异

| 類別 | Mock 有 | Real 有 |
|------|---------|---------|
| meter_daily.json | ✅ | ❌ **缺**（影響 Stage 3 残差分析） |
| daily_top20_by_dma.json | ✅ | ❌ |
| daily_total_by_dma.json | ✅ | ❌ |
| model_comparison.json | ✅ | ❌ |
| data_errors.json | ❌ | ✅ |
| 4 個 hourly JSON | ❌ | ✅ |
| hourly_meter.db | ❌ | ✅ |
| daily_totals.json (cache) | ❌ | ✅ |

---

# 10. Pipeline 7 Stage 详解

| Stage | 中文 | 做什麼 | 真數據時是否乾活 |
|-------|------|-----------|---------------|
| 1 `ingest` | 數據摄取 | 讀 13 個 JSON → 13 個 DataFrame | ✅ 乾 |
| 2 `clean` | 數據清洗 | 质量規則作用於 `meter_daily` | ⚠️ No-op（已清洗） |
| 3 `detect_anomalies` | 異常校驗 | Pandera 校驗 + 統計 by_type/by_dma | ⚠️ 只校驗不算 |
| 4 `predict` | 预測校驗 | 行數检查 | ⚠️ 只校驗不算 |
| 5 `load_sql` | 寫 SQLite | DROP+CREATE 13 張表 + ATTACH hourly_meter.db | ✅ 乾 |
| 6 `drift` | 漂移检測 | KS（數值）+ 卡方（分類）vs baseline | ✅ 乾（首次存 baseline） |
| 7 `data_health` | 健康檢查 | 單表 z-score + 跳變 + 销戶對 | ✅ 乾（監察） |

每個 stage 详細說明見 `GLOSSARY.md` 和 pipeline 代碼註解。

**運行命令**：
```bash
python pipeline/orchestrator.py \
  --src backend/data/output_real \
  --db  backend/data/analytics_real.db
```

---

# 11. 3NF 分析

13 張表的 schema 是 **OLAP 風格**（讀密集型仪表盘），所以有取舍。

## 11.1 1NF——原子值

| 規則 | 狀態 | 備注 |
|------|------|------|
| 无重復組 | ✅ | 所有列原子 |
| TEXT 裡藏 JSON | ⚠️ | `weekly.totalByDma`, `weekly.dailyTotals`, `weekly.wdByDmaRes` |

JSON 列是為了仪表盘讀取速度（一次讀、无 join）。

## 11.2 2NF——无部分依賴

✅ 乾淨。每張表都是自然單/復合键，无代理键。

## 11.3 3NF——无传递依賴



| 违反 | 位置 | 為什麼 |
|------|------|--------|
| 水表元數據冗余 | `anomalies`, `rank_changes` 重復了 `meters` 表的 `contractId/buildingName/dma/propertyType` | 讀效能——異常查看器只讀一張表，不 join |
| 逗號分隔多值 | `monthly_diff.subs` = `"12345,67890,..."` | 输出形态——仪表盘把 subs 顯示為逗號列表 |
| weekly 裡 JSON 聚合 | `totalByDma` = `{"Zone-1": 1234, ...}` | 预先聚合，省每次頁面載入的 CPU |


---

# 12. 應用層

## 12.1 Agent（FastAPI :8000）

Planner-Executor-Synthesizer 管線（同一個 LLM，3 個專門 prompt）。
這是生產路徑；老的單 ReAct agent 留作 fallback。

**工具清單（16 個）**：
- 11 個讀 JSON：`query_meters`, `query_anomalies`, `get_anomaly_stats`,
  `query_consumption` (mode: daily/weekly/compare), `query_rank_changes`,
  `query_monthly_diff`, `get_predictions` (query_type: meter/building),
  `get_data_overview`
- 3 個文字轉 SQL：`list_tables_tool`, `get_table_schema_tool`, `sql_query`
  （只讀、參數化、禁止 DDL/DML）
- 1 個頁面上下文讀取：让 agent 解析"這周 / 当前 zone"
- 1 個 ECharts 圖表構建器：输出 `echarts_option` JSON，前端渲染

**三層容錯**：
1. **SQL 自我修正**（`sql_refinement.py`）——壞 SQL 在工具內最多重
   試 2 次，不消耗 ReAct 步骤
2. **回問澄清**（`agent_executor.py` prompt）——含混問題傳回中文澄
   清選项，不調工具，每轮最多 1 次
3. **`query_data_quality` 工具**——暴露 converter 級別的數據錯誤，
   agent 能說"我看到 4 處數據錯誤"而不是靜默污染

**端點**：`/api/chat`（SSE 流）、`/api/chat/sync`、`/api/health`、
`/api/reset`、`/api/history`。對話歷史持久化到 `chat_history.json`
（保留最近 6 轮）。

## 12.2 Frontend（Node :5173）

12 個 JS 模塊按依賴順序載入：`home.js`, `trend.js`, `rank.js`,
`diff.js`, `anomaly.js`, `search.js`, `predict.js`, `map.js`,
`calendar.js`, `chat.js`, `tabs.js`, `utils.js`。ECharts 5 + Leaflet，
暗色主題。

**兩種載入策略**（build 時由 `USE_REAL_DATA` 決定）：
- Mock 模式：單個 `all_data.json` bundle
- Real 模式：14 個独立 JSON 並行載入，再按 `DIRECT/INDIRECT` 分流
  避免子表重復計量

---

# 13. 測試與評估

| 測試層 | 數量 | 耗時 | 測什麼 |
|--------|------|------|--------|
| 單元（pytest） | 104 | ~37s | 純逻辑，不調 LLM |
| LLM QA（evaluate.py） | 30 | ~10 分鐘 | 真模型調用，按工具準確率、關键詞召回、行為通過/失敗、延迟、失敗率打分 |

**最新運行**（2026-06-08）：通過率 86.7%（26/30），工具準確率 80.0%，關键詞召回 88.3%，失敗率 0%，平均延迟 30.8s。verdict: pass。

**Schema 完整性測試**：grep 系統 prompt 裡的 `FROM <table>` 引用，
断言在真實 SQLite DB 裡存在——抓住"工具改名了但 prompt 没改"的情
况。

---

# 14. 典型工作流

## 14.1 首次接入（真實數據）

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

## 14.3 倒填（舊數據补錄）

```bat
bat\real\convert_real_data.bat --since 2026-04-01
```

⚠️ Hourly JSONs 是 append-only——倒填會打亂時間序。要麼 `--full` 重
置，要麼让仪表盘按 `date` 欄位排序。

## 14.4 單表數據修正（不改代碼）

编辑 `backend/data/corrections.json` 加 `{meterId, start, end, factor,
reason}`。下次 converter 跑時自動應用。用於：
- 水表設置錯誤（×N / +N 偏移）
- 水表某天停用
- 整棟建筑集體修正

---

# 15. Trade-off 與限制

| 限制 | 影響 | 緩解 |
|------|------|------|
| `hourly_meter.db` 30 天上限 | ATTACH 在 ~7M 行後變慢 | 可調 `--hourly-window` |
| 異常检測需 14 天 | 冷启動前 14 天 0 異常 | 算法約束；预期行為 |
| Top-50 预測模型 | 長尾水表预測不準 | 設計選擇（數據稀疏） |
| `daily_totals.json` 是隐式狀態 | 删了触發下次 `--full` | 有 fallback 到首次運行行為 |
| Hourly JSONs append-only | 倒填會亂序 | `--full` 重置 |
| 單表日 cap 4000 m³ | 超過视為誤值丢弃 | 記到 `data_errors.json`，異常頁可查 |
| Mock 缺 `meter_daily.json` | Stage 3 残差分析无法跑 | 加 `meter_daily.json` 到 mock generator |
| 單表數據修正 | 默認要改 converter 代碼 | `corrections.json` 外部檔案——不改代碼 |
| 單小時單表更新 | 当前架構不支持區域重派生 | 待加 `patches.json` 機制 |

---

# 16. 部署

| 模式 | 運行什麼 | 何時 |
|------|----------|------|
| **靜态 HTML** | 只有 `frontend/dist/dashboard.html` | 分享、Telegram、邮件、无服務器 |
| **Docker Compose** | `agent`（Python）+ `dashboard`（Node）兩個服務 | 本地開發 |

仪表盘**完全离線**可用（所有數據內联）。Agent 是**可選**——没有
agent 仪表盘照样跑。

---

# 17. 代碼入口速查

| 檔案 | 作用 |
|------|------|
| `scripts/real_data_converter.py` | Excel → JSON + SQLite（3 種運行模式） |
| `scripts/mock_data_generator.py` | 合成數據產生器 |
| `pipeline/orchestrator.py` | 7 stage MLOps 管線 + checkpoint |
| `pipeline/sql_loader.py` | JSON → SQLite 載入器（ATTACH `hourly_meter.db`） |
| `pipeline/schema.py` | 11 個 Pandera schema（數據契約） |
| `pipeline/data_quality.py` | `meter_daily` 清洗規則 |
| `agent/server.py` | FastAPI 入口（`/api/chat` SSE + `/api/metrics`） |
| `agent/multi_agent.py` | Planner-Executor-Synthesizer 管線 |
| `agent/agent_tools.py` | 16 個工具實现（全部 `@safe_tool_call` 裝饰） |
| `agent/sql_refinement.py` | SQL 自我修正（重試壞查询） |
| `agent/memory_compressor.py` | 兩段式記憶：近期原文 + 舊摘要 |
| `agent/dangerous_paths.py` | 路徑黑名單（`.env`/`/etc`/`C:/Windows`） |
| `agent/tool_audit.py` | JSONL 工具調用审計記錄 |
| `agent/safe_tool_call.py` | 裝饰器：超時 + 路徑检查 + 审計 |
| `scripts/find_alternating_pairs.py` | 交替用水表對检測（Pearson + 贪心匹配） |
| `frontend/build.cjs` | 靜态站構建（`USE_REAL_DATA` 感知 + 敏感資料保護注入） |
| `bat/real/*.bat` | Windows 一键入口腳本 |

---

# 18. Cookbook：常見任務

### 加一個 Agent 工具
1. `agent/agent_tools.py` 加新函數 + 註冊到 `ALL_TOOLS`
2. `agent/multi_agent.py` 的 `PLANNER_PROMPT` 工具列表加一行
3. `tests/test_agent_tools.py` 加單測
4. 重启 agent

### 加一張 SQL 表
1. `pipeline/schema.py` 加新 Pandera schema + 註冊到 `SCHEMA_REGISTRY`
2. `pipeline/sql_loader.py` 加寫入函數
3. `agent/sql_tools.py` 的 `get_table_schema_tool` 會自動看到
4. 跑 pipeline 驗证

### 改预測模型
1. 改 `scripts/real_data_converter.py` 的预測調用
2. 跑 `--full` 重派生
3. 跑 `evaluate.py` 看 R²

### 修一個水表某天數據錯了
1. 编辑 `backend/data/corrections.json` 加 `{meterId, start, end, factor, reason}`
2. 跑 `convert_real_data.bat`（任何模式都行）
3. 跑 pipeline + 重建 dashboard

### 加一個新 DMA
1. 在 `pipeline/schema.py` 的 `VALID_DMAS` 加 DMA 名
2. converter + pipeline 會自動識別

---

# 19. 演進記錄

| 日期 | 改動 | 原因 |
|------|------|------|
| 2026-06-04 | 接入真實數據分支 | demo 數據展示不出真實模式 |
| 2026-06-05 | 移除 `predictions_by_building.json` | 被 per-meter 视圖取代 |
| 2026-06-05 | 加 `corrections.json` 外部修正機制 | 不改代碼修單表數據 |
| 2026-06-08 | 合並 `REAL_DATA_ARCHITECTURE.md` 進本檔案 | 消除權威混淆 |
| 2026-06-08 | **加兩段式記憶**（`agent/memory_compressor.py`） | 長對話 token 爆掉 → 摘要壓縮 + 滑動視窗 |
| 2026-06-08 | **加工具沙盒**（`safe_tool_call` 裝饰器 + `tool_audit.py` + `dangerous_paths.py`） | 16 個工具裸跑 → 加超時 + 路徑黑名單 + JSONL 审計 |
| 2026-06-08 | **加 harness 回归**（`tests/harness/agent_behaviors.json`，30 case） | prompt 改動无 fail-fast 保護 → mock-LLM 离線回归 |
| 2026-06-08 | **加 ADR-0004**（`docs/adr/0004-claude-code-design.md`） | 業界標桿參考 + 後續改進有 ADR 兜底 |
| 2026-06-08 | **Stage 3 残差分析**（`orchestrator.py`） | detect_anomalies 加 RMSE/MAE/bias，JOIN predictions vs meter_daily |
| 2026-06-08 | **Stage 4 Pandera 校驗**（`schema.py` + `orchestrator.py`） | 新增 `PredictionsBuildingRowSchema`，`PredictionRowSchema` lower/upper 改 nullable |
| 2026-06-08 | **敏感資料保護修復**（`build.cjs`） | `USE_REAL_DATA=1` 注入密碼解鎖逻辑，mock 模式保持開放 |
| 2026-06-08 | **清除真實 meter ID**（`corrections.json` + `qa_pairs.json`） | 712720→MOCK0001, 753832→MOCK7538 |
| 2026-06-08 | **Agent ask-back 全鏈路**（`multi_agent.py` + `server.py` + `chat.js`） | 模糊输入触發反問 + 選项按鈕 + real DMA 名 + 自然語言問題 |
| 2026-06-08 | **交替用水表對检測**（`scripts/find_alternating_pairs.py`） | 路氹城區 29 對负相關表，贪心匹配保证唯一性 |
| 2026-06-09 | **execute() dedup + 断路器**（`multi_agent.py`） | Q1 工具調用 42→2，延迟 149s→9s。3 層防護：(tool, params) 去重、2 連續 fail 熔断、max_tools=8 上限 |
| 2026-06-09 | **SQL 自纠去重**（`sql_refinement.py`） | 同錯誤連續 2 次熔断 / SQL 未變熔断 — 避免 LLM rewrite 死循環 |
| 2026-06-09 | **PLANNER 軟提示**（`multi_agent.py`） | "不要重復調同工具" + "不要查 schema" + "不要交叉驗证" + "1-3 calls/題" |
| 2026-06-09 | **Eval v2: 86.7% → 93.3%**（30 QA live LLM） | pass_rate +6.6pp, kw_recall +8.4pp, latency -43%；2 FAIL→PASS（Q24 SQL、Q25 report）。详細報告 `reports/eval_v1 vs v2_optimization.md` |
| 2026-06-09 | **execute dedup 測試**（`tests/test_execute_dedup.py`，6 cases） | 防改壞：去重 / 断路器 / 上限 / 重置 |
| 待加 | `patches.json` 單點更新 | 修單水表單小時數據 |
| 待加 | mock 數據补 `meter_daily.json` | 让 Stage 3 残差分析兩邊都能跑 |

---

> **再次強調**：本文件是**架構權威**。如其他檔案（`README.md`、
> `GLOSSARY.md`、代碼註解、CHANGELOG）信息與本文件冲突，**以本文件為準**。
> 改動架構時，**先改本文件，再改代碼**。
