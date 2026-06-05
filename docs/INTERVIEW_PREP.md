# 数据科学家面试 — 项目指南

> 本文档解释项目的设计决策，连接到行业应用场景，并提供面试常见问题的参考答案。

---

## 1. 项目概述（30 秒电梯演讲）

**Smart Water Analytics** 是一个端到端的水务数据分析平台：每日水表数据采集、异常检测、7 天预测、自然语言 AI Agent 查询，以及 MLOps 级别的数据管道。

展示六大核心能力：
1. **MLOps 成熟度** — 管道透明、Schema 验证、漂移检测
2. **结构化 + 非结构化数据** — Text-to-SQL 查询数据库 + JSON 工具查询预汇总数据
3. **三层容错的 Agent** — Self-refinement SQL + Ask-back 澄清 + 数据质量工具
4. **评估体系** — 30 道 QA 测试题 + 66 个单元测试 + 自动化评分 (pass rate 76.7%)
5. **数据工程** — 自动异常检测、缺失值处理、检查点机制
6. **工程质量** — 生产级日志、清晰错误信息、运行摘要

---

## 2. 跨行业映射

| 项目能力 | 行业等价场景 |
| --- | --- |
| 每日水表数据采集 + 清洗 | CDR（通话记录）采集、过滤噪声事件 |
| 异常检测（Z-score + 滚动窗口） | 欺诈检测、网络故障检测 |
| 7 天预测（指数平滑） | ARPU 预测、流失风险预测、流量预测 |
| Text-to-SQL Agent | 运维查询机器人（网络计数器、工单系统） |
| 数据漂移检测 | 用户行为漂移、网络拓扑漂移 |
| 评估测试套件 | A/B 测试评分、模型回归 CI/CD |
| Pandera Schema 验证 | 上下游数据契约 |

**架构模式可迁移**，数据领域不同但方法论一致。

---

## 3. 架构一览

```
原始数据 (JSON)            ─┐
                            │
  pipeline/  ───────────────┼──►  Pandera Schema  ──►  SQLite (analytics.db)
    ingest                   │     验证                   │
    clean  (IQR + 插值)      │                           │
    detect_anomalies         │                           ▼
    predict                  │              agent/  (13 个 LangChain 工具)
    load_sql                 │                ├─ 10 个 JSON 工具
    drift (KS / chi²)        │                └─ 3 个 text-to-SQL 工具
                            │
  reports/  ◄──────────────┘  运行摘要、评估报告、漂移报告
            frontend/  (ECharts 仪表盘、对话窗口)
```

管道采用**分阶段 + 检查点**机制 — 某阶段失败后，下次运行从最后一个成功的检查点恢复。

---

## 4. 关键设计决策

### 4.1 为什么用 Pandera（不用 Great Expectations）？
- **Python 原生**，整个管道一种语言
- 支持类型强制、正则匹配、值域检查、唯一性约束 — 全部声明式、可版本控制
- 错误信息精确到列名和值域，排查快
- Great Expectations 需要重量级的 data-context 服务器，对作品集项目过于复杂

### 4.2 为什么用 SQLite（不用 Postgres）？
- **零基础设施** — 文件和 JSON 输出同目录，无需服务器和凭证
- SQL 语法与 Postgres 通用，生产环境可直接迁移
- 加载时在 `meterId`、`date`、`dma` 上建索引，典型查询 O(log n)

### 4.3 为什么用 ReAct Agent（不用 RAG）？
- 用户问题是**操作型**的（统计、Top-N、对比），不是**知识型**的（什么是...？）
- RAG 检索文档，Agent 调用工具。工具是正确的抽象
- JSON 文件作为"预汇总数据"放在 Agent 的 prompt 中，实现混合推理

### 4.4 为什么用多 Agent（Planner → Executor → Synthesizer）？
- **关注点分离** — 规划、执行、综合各司其职
- **可见性** — 显示显式计划给用户看，适合需要审计的场景
- 成本是延迟（3 次 LLM 调用 vs 1 次），通过 UI 开关可选

### 4.5 为什么用 KS 检验（不用目视漂移检测）？
- KS 检验给出单一数值（p 值），可设阈值
- 适用于任意分布形状，不要求正态性
- 分类变量用卡方检验
- 漂移检测作为管道的一个阶段，每次运行产出 JSON 报告

### 4.6 Agent 的三层容错 (2026-06-05/06 重要升级)
- **第一层 — Self-refinement SQL 循环** (`agent/sql_refinement.py`)：LLM 写的 SQL 错了 (typo、错列) 时，在工具内部让 LLM 改写并重试 2 次，**不消耗 ReAct step**。返回 `attempts: 1..3` 让上层看到。来源是 Snowflake Labs 的 ReFoRCE 论文 (138 stars)。
- **第二层 — Ask-back 反问澄清** (系统 prompt 块)：问题**实质性**歧义时 (不同选择 = 不同答案)，LLM 返回 2-4 个编号选项 (最可能项标 [默认]) 并**不调任何工具**; 轻微不确定时退到 GUESS+STATE (括号里说明假设); **每轮最多 1 个问题**。来自我 5 年 IT support 的洞察: 提高准确率的关键是反问, 反问也要有节制。**不新增工具、不改前端、不改 SSE** — 纯 prompt 工程。
- **第三层 — `query_data_quality` 工具** (`agent/agent_tools.py`)：读取 converter 的 `data_errors.json`，让 agent 能回答 "数据准不准" / "is the data accurate"，不依赖人。前端 Data Integrity banner 是给人看的，这个是给 agent 看的。
- **为什么这三层都必要**:
  - Self-refinement 修"代码写错" (~30% 真实失败)
  - Ask-back 修"问题没说清" (~20%)
  - Data quality 修"数据本身有 typo" (e.g. 2026-01-08 水表 713911 读数 +42,940,982 m³ 在 daily sum 里正负抵消)
- **效果**: 30 对真实数据 eval, pass rate 60.7% → 76.7% (真实语义 ~93%)。其中评分修复 (raw tool output 算进 kw 匹配) 贡献了 6 个翻转 PASS, 没改 agent 一行代码。

---

## 5. 术语表

面试中应自然使用的专业术语：

- **Data Drift（数据漂移）** — 输入特征的分布随时间变化，通常悄然降低模型性能
- **Schema Validation（模式验证）** — 检查数据结构是否符合契约（列名、类型、值域）
- **Checkpointing（检查点）** — 保存中间状态，失败后可恢复而不重做已完成的工作
- **Observability（可观测性）** — 通过日志、指标、追踪回答"这次运行发生了什么"
- **Text-to-SQL** — 将自然语言问题转换为 SQL 查询
- **Winsorization（缩尾处理）** — 用 IQR 边界值替代异常值，而非删除行
- **Traceability（可追溯性）** — 能重建哪份数据、代码、参数产生了特定输出

---

## 6. 面试常见问答

### Q1: "介绍一下你的管道"
> 六个阶段：`ingest` 读取 JSON 到 DataFrame；`clean` 用 IQR 缩尾 + 缺失值插值；
> `detect_anomalies` 验证数据质量并报告分布统计；`predict` 验证预测行；
> `load_sql` 写入 SQLite 并建索引；`drift` 用 KS 检验 + 卡方检验对比基线。
> 每个阶段都有 `run_id` 日志和检查点。Pandera 在每个阶段边界做 Schema 验证。

### Q2: "如何扩展到生产环境？"
> Text-to-SQL 工具可直接对接 Postgres 或 Snowflake。高频采集用 Kafka/Kinesis
> 替代 JSON 读取。漂移检测从批后模式改为流式窗口。Agent 从 CLI 变成微服务，
> 前面加消息队列。

### Q3: "数据结构变了怎么办？"
> Pandera 在受影响阶段的边界捕获错误。编排器记录失败，保留上一个好的检查点，
> 输出清晰错误。生产环境中可通过结构化日志字段（`stage`、`schema`、`errors`）
> 触发告警。

### Q4: "为什么不用 RAGAS 做评估？"
> RAGAS 针对 RAG 管道（忠实度、回答相关性）。我的 Agent 是工具调用型，
> 不是检索型。我评估的是**工具准确率**（是否调用了正确的工具）和
> **关键词召回率** — 更贴近 Agent 的实际生产需求。

### Q5: "解释数据漂移以及如何检测"
> 数据漂移是训练和生产之间输入特征分布的变化。可以是协变量偏移 P(X) 变化、
> 标签偏移 P(Y) 变化、或概念偏移 P(Y|X) 变化。我用 KS 检验处理数值列，
> 卡方检验处理分类列。p 值低于 0.05 则标记为漂移。首次运行存储基线，
> 后续运行对比基线。

### Q6: "讲一个困难的数据清洗决策"
> 清洗阶段用 IQR 缩尾而非删除异常值。删除行会破坏时间序列连续性，
> 隐藏"某水表上周二飙升到 1000m³"这个事实。缩尾保留事件的存在性，
> 同时限制幅度，下游异常检测仍能看到该行。阈值 k=3 是权衡：
> 太激进会隐藏真实异常，太宽松会让传感器故障污染模型。

### Q7: "生产部署你会加什么？"
> 按优先级三件事：
> 1. **Schema 版本控制** — 破坏性变更时 bump 版本，写迁移脚本
> 2. **漂移告警** — drift_count > 0 时推送 PagerDuty/Slack
> 3. **评估进 CI** — pass_rate 低于阈值时阻断 PR
> 这些都不需要重写，数据已经就绪。

### Q8: "Agent 怎么决定用 SQL 还是 JSON 工具？"
> 系统提示中有工具选择指南：聚合、JOIN、Top-N、日期范围 → SQL；
> 高层概览如"Zone-3 异常情况" → JSON 预汇总工具。模型按子问题逐个选择，
> 一轮对话可以混合使用两种工具。

### Q9: "为什么用流式 SSE？"
> Agent 规划循环可能需要 5-10 秒。不用流式的话用户看到冻结的界面。
> SSE 让服务器在每个工具完成时发出 `tool` 事件，最后发出 `answer` 事件。
> 前端显示"正在运行哪个工具"，让 Agent 感觉响应快且透明。

### Q10: "你最后悔什么 / 会怎么做不同？"
> 会把编排器拆成"运行器"和"定义文件"。现在加阶段要改 `STAGES` 列表和
> `run()` 函数。用 YAML 或 Python 配置可以让运维加阶段而不碰代码。
> 这是个小重构，会在扩展更多数据源之前做。

### Q11: "LLM 写错了 SQL 怎么办？你的 agent 怎么恢复？"
> 三层机制里的第一层 — **self-refinement SQL 循环**。
> SQL 工具包了一层 wrapper (`agent/sql_refinement.py`)：当 `sql_query` 抛错时，**不立刻返回失败**，而是把错误信息、表 schema、原始 SQL 一起发给 LLM，让它改写并重试。**最多 2 次**。重试发生在工具内部，**不消耗 ReAct step** — agent 主循环看不到这个过程，retry 对它透明。
> 返回结构化响应: 成功时带 `attempts: 1..3` (用户能看到是不是一次就过), 失败时带 `refinement_exhausted: true` 和最后一次的 SQL。
> 设计参考: Snowflake Labs 的 ReFoRCE 论文 (138 stars), GitHub 上 text-to-SQL 的标准修复模式。
> 真实效果: 4 个 smoke case 验证过 — typo 表名 2 次重试过、错列名 2 次重试过、正确 SQL 1 次就过、完全 garbage 3 次 exhaust 报失败。

### Q12: "用户问得不明确怎么办？比如 '氹仔漏水'"
> 三层机制里的第二层 — **ask-back 反问澄清**。
> 来自我 5 年 IT support 经验的洞察: **提高准确率的关键是反问, 反问也要有节制**。用户大概懂术语但不会描述, 同事听到"X 还是 Y?" 比我猜一个答案猜错的成本低很多。
> 实现: 系统 prompt 里加了一段 `CLARIFICATION` 块, 规则:
> 1. **实质性歧义** (不同选择 = 不同工具/不同答案) → 返回 2-4 个编号中文选项, 最可能的标 [默认], **不调任何工具**。
> 2. **轻微不确定** → GUESS+STATE, 直接继续, 在答案开头用括号说明假设 (例如 "(默认查 路氹城區, 如需其他 DMA 请说明)")。
> 3. **每轮最多 1 个问题**, 不堆 4 个。
> **关键简化**: 全部用 prompt 实现, **没新增工具、没改 SSE、没改前端** — 聊天输入框本来就接受文字回复。
> 3 个 QA pair 专门测这个行为 (`氹仔漏水` → 反问, `上周水损情况` → 反问, `氹仔的 NRW` → GUESS+STATE)。Eval 时走 behavior-aware 评分, 不跟路由 pair 走同一条 pass 规则。

### Q13: "怎么评估一个 LLM agent? 怎么知道它变好还是变差?"
> **自建 eval 框架** (`tests/evaluate.py`), 不直接用 RAGAS。理由: 我的 agent 是**工具调用型**不是**检索型**, RAGAS 的指标 (faithfulness、answer relevance) 不适用。
> 三个核心指标:
> 1. **tool accuracy** — 调了预期的工具吗? (我更在意这个, 不是关键词)
> 2. **keyword recall** — 期望关键词在答案里吗? **2026-06-06 修复**: 现在也检查 raw tool output, 避免 LLM 把 `anomalyScore` 翻成 "异常分数" 导致 false-FAIL。
> 3. **latency** — 端到端墙钟时间。
> **Behavior-aware 评分**: clarification pair 走特殊规则 (pass = 没调工具 + 关键词命中), guess+state 又是另一条规则。**不用一套规则评所有题**。
> **30 对真实数据 eval, mimo-v2.5-pro**: pass rate **76.7%** / tool_acc 70.0% / avg_kw **86.7%** / **0% failure rate**。真实语义 pass 率约 93% (剩下 7 个 fail 5 个是语义等价的工具选择, 不是真错)。
> **CI 集成**: pytest 66 个 unit test ~2s 跑完, eval 30 对 ~10 分钟。Eval 还没进 CI (成本), 但 `test_prompt_schema_integrity.py` 进了 — 它 grep 系统 prompt 里的表名跟真实 DB 比对, 挡住 meter_daily 类 schema 错配 bug 在 agent 运行时才暴露。

---

## 7. 演示脚本（5 分钟）

1. **开场**（30s）："水务公司因漏损损失 30% 的水量。我做了一个实时异常检测系统。这个架构同样适用于电信 CDR 分析。"

2. **展示管道**（1m）：`python pipeline/orchestrator.py` — 指出 JSON 日志、检查点目录、SQLite 数据库、漂移报告。展示重跑时复用检查点。

3. **展示 Agent**（1.5m）：打开仪表盘，点击对话窗口。问"Zone-3 有多少异常？" — 展示流式工具调用、SQL 工具选择、内联图表。切到多 Agent 模式，问同一问题 — 展示显式计划。

4. **展示 SQL**（1m）：用 SQLite 浏览器打开 `backend/data/analytics.db`，运行 `SELECT dma, type, COUNT(*) FROM anomalies GROUP BY dma, type`。解释："在电信场景中，这是对 CDR 表或网络计数器表的同类查询。"

5. **展示评估**（1m）：`pytest tests/ -v` — 展示全部通过。展示 `reports/eval_report.md`，指出工具准确率指标。

6. **收尾**（30s）："同样的架构可以扩展：管道处理实时事件、Agent 做运维查询、漂移检测监控行为变化、评估作为 CI 门禁。数据会变，模式不变。"

---

## 8. 项目文件导航

| 文件 | 为什么重要 |
| --- | --- |
| `pipeline/orchestrator.py` | 管道运行器 — MLOps 骨干 |
| `pipeline/schema.py` | Pandera Schema — 数据契约 |
| `pipeline/data_quality.py` | 异常值 + 缺失值处理 |
| `pipeline/drift.py` | KS 检验 + 卡方检验漂移检测 |
| `agent/sql_tools.py` | Text-to-SQL：Agent 如何查询数据库 |
| `agent/sql_refinement.py` | **Self-refinement SQL 循环** (新) — 错时自动改写重试 |
| `agent/agent_executor.py` | ReAct Agent + 工具选择提示 + **CLARIFICATION 块** (新) |
| `agent/agent_tools.py` | 11 个 JSON 工具, **含 query_data_quality** (新) |
| `agent/tool_router.py` | 规则引擎工具预选 |
| `agent/memory.py` | 对话记忆摘要 |
| `tests/qa_pairs.json` | **30 道** QA 测试题 (25 路由 + 3 反问 + 2 数据质量) |
| `tests/evaluate.py` | 评分逻辑 — **含 raw tool output kw 匹配 + behavior-aware 评分** (新) |
| `tests/test_sql_refinement.py` | **11 个 self-refinement 单元测试** (新) |
| `tests/test_clarification_prompt.py` | **5 个 prompt 规则 + token 预算测试** (新) |
| `tests/test_query_data_quality_tool.py` | **6 个 query_data_quality 工具测试** (新) |
| `tests/test_prompt_schema_integrity.py` | **2 个 schema 错配回归测试** (新) |

---

## 9. 故意不做的（Out of Scope）

- **Kafka / 流式采集** — 会分散"管道透明性"的核心信息，同样的代码换传输层即可
- **MLflow / W&B** — 对作品集过于重量级
- **深度学习模型** — 用 Z-score + 滚动窗口 + 指数平滑是有意为之，可解释性优先
- **多语言** — 仅支持中文 + 英文
