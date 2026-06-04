# 数据科学家面试 — 项目指南

> 本文档解释项目的设计决策，连接到行业应用场景，并提供面试常见问题的参考答案。

---

## 1. 项目概述（30 秒电梯演讲）

**Smart Water Analytics** 是一个端到端的水务数据分析平台：每日水表数据采集、异常检测、7 天预测、自然语言 AI Agent 查询，以及 MLOps 级别的数据管道。

展示五大核心能力：
1. **MLOps 成熟度** — 管道透明、Schema 验证、漂移检测
2. **结构化 + 非结构化数据** — Text-to-SQL 查询数据库 + JSON 工具查询预汇总数据
3. **评估体系** — 25 道 QA 测试题 + 自动化评分
4. **数据工程** — 自动异常检测、缺失值处理、检查点机制
5. **工程质量** — 生产级日志、清晰错误信息、运行摘要

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
| `agent/agent_executor.py` | ReAct Agent 和工具选择提示 |
| `agent/tool_router.py` | 规则引擎工具预选 |
| `agent/memory.py` | 对话记忆摘要 |
| `tests/qa_pairs.json` | 25 道 QA 测试题 |
| `tests/evaluate.py` | 评分逻辑 |

---

## 9. 故意不做的（Out of Scope）

- **Kafka / 流式采集** — 会分散"管道透明性"的核心信息，同样的代码换传输层即可
- **MLflow / W&B** — 对作品集过于重量级
- **深度学习模型** — 用 Z-score + 滚动窗口 + 指数平滑是有意为之，可解释性优先
- **多语言** — 仅支持中文 + 英文

---

## 10. 模拟面试 Q&A（19 题，项目深挖版）

> 这部分是**看过你作品**的面试官会问的，每题含 "面试官想听什么"。**练的时候用 STAR 格式**（Situation / Task / Action / Result）。

### 一、项目定位

**Q1: Walk me through this project in 2 minutes.**
A: 这是澳门水务的智能消费分析平台。背景是 **9,963 个真实水表、4 个 DMA 区域（澳門低區、澳門填海A區、澳大橫琴區、路氹城區）、43 种物业类型、151 天的逐时数据**。三个核心能力：
1. 异常检测 — 14 天滚动 Z-score + tanh 压缩，分类 spike / drop / zero / watch，~1,500 个异常/151 天
2. 7 天预测 — Top-50 水表 LinearRegression + 周期/趋势特征，每天 ~5KB JSON
3. AI Agent — LangChain + FastAPI，13 个工具（10 JSON + 3 text-to-SQL），multi-agent 可切

配套 6 阶段 MLOps pipeline（pandera schema 校验 + drift 检测 + checkpoint）、GitHub Actions CI、Docker、gitleaks 都有。
🔍 听数字精度。不要讲 "做了 dashboard 和 agent" 这种空话。

**Q2: What real problem does this solve?**
A: 真实业务是 **NRW（Non-Revenue Water，产销差）** —— 主管和分表读数差就是漏损/偷水信号，`monthly_main_sub_diff.json` 就是这个差。
- 异常检测 → 漏损报警（drop = 破裂/spike = 私接大用户）
- 预测 → 容量规划
- Agent → 降低人工查询成本

对 HKT 的同构性：把 "水表" 换成 "基站"、"漏损" 换成 "客户掉线率"，业务逻辑一样。
🔍 听能不能跳出技术讲业务。

### 二、数据工程

**Q3: Why daily JSONs AND hourly SQLite? Why not just one store?**
A: 架构硬约束 — **dashboard 是静态 HTML，没有运行时 DB 连接**。这意味着 dashboard 想看的数据必须在 build 时预聚合进 JSON。
- **Daily JSONs**（14 个，~7MB）→ dashboard + Agent 的 10 个 JSON 工具。查 <1ms
- **Hourly JSONs**（4 个）→ 未来 hourly 视图
- **hourly_meter.db**（4.6M 行，30 天 SQLite）→ Agent `sql_query` 工具做 ad-hoc 自由查询

三个存储各有 SLA，不能合并。
🔍 听为什么不是"一个 PostgreSQL 解决所有"。

**Q4: How do you handle incremental data?**
A: Converter 默认 incremental，~55s/天：
1. 读 `daily_totals.json` 缓存找 `last_date`
2. 列源 dir 里 > `last_date` 的 xlsx
3. 读新文件（~50s，openpyxl 慢但只对新文件）
4. 合并 `merged = {**cache, **new_daily}`（内存）
5. 从 merged 全量**反派生**所有 daily JSON（<1s）
6. append hourly JSON（<1s）
7. `INSERT OR IGNORE` SQLite + DELETE `> today - 30` 老行

关键：**反派生而不是重读 Excel**。`daily_totals.json` 缓存 100KB/天，让 incremental 不重读 150 天历史。
🔍 听缓存为什么叫 daily_totals、为什么 hourly append 而不是重派生。

**Q5: What if Excel format changes tomorrow?**
A: 三层防御：
1. Converter 早 fail — openpyxl 失败直接 `sys.exit(1)`
2. Pipeline pandera schema — 验列名/类型
3. `drift` stage — KS-test p<0.05 报警

1 月我加 4 个 DMA 时 schema 变了，`--since 2026-01-01` 强制重派生 + 手动改 `pipeline/schema.py` 的 `VALID_DMAS`。
🔍 听有没有想过上游变更。

### 三、ML 方法

**Q6: Walk me through your anomaly detection.**
A: 14 天滚动 Z-score + tanh 压缩。
```python
z = (current - mean_14d) / std_14d
score = tanh(z / 3)  # 压缩到 [-1, 1]
```
- spike: `current > mean × 4` AND `score > 0.5`
- drop: `current < mean × 0.3` AND `score > 0.4`
- zero: `current == 0` AND `mean > 1`
- watch: `current > mean × 1.5` AND `score > 0.25`

为什么 14 天：覆盖 2 个完整周，剔周内波动。短了被单次高峰污染，长了反应慢。
为什么 tanh：Z-score 极端值会爆炸（漏损可能 100σ），tanh 压到 [-1, 1] 后阈值是常数。
为什么不是 IsolationForest：单变量时序 + 业务量级，Z-score 解释性 100% — 工程师能直接说"这户超过 4 倍均值"。
🔍 听算法选择背后的 trade-off，不是"X 流行所以用 X"。

**Q7: Why Linear Regression? Why not Prophet or LSTM?**
A: 三个真实约束让 LR 正确：
1. **样本量**：top-50 water meters，每个 ~100 个数据点。LSTM 严重过拟合；Prophet 至少 1-2 年数据
2. **可解释**：LR 系数 = "周末效应 +X 升"、DMA 系数 = "路氹比低区多 Y 升"，业务方能直接看
3. **训练时间**：LR ~50ms，LSTM GPU 也要 10 分钟

诚实承认：MAPE ~15-25%，单 meter variance 本身就大。**长尾 9,900 个 meter 不预测**（数据稀疏）—— 明确的设计选择。
🔍 诚实承认限制。说"LR 在我数据量下正确，100k+ 时会换" = 加分。说"LR 永远够" = 减分。

**Q8: How do you evaluate model quality? Show me a number.**
A: 三层评估：
1. **离线 metrics** — LR R² 在 `predictions.json` metadata，top-50 平均 R² ~0.6-0.8
2. **离线 QA 评估** — 25 题 `tests/qa_pairs.json`，agent 调工具后比对关键词，keyword recall ~70%
3. **业务反馈** — 工程师标 10 个 case "对/错"，人工调阈值

**老实说没做 backtest / time-series CV**，这是已知缺口。生产里应该 rolling window 评估（每加 7 天评估预测 7 天 MAPE）。
🔍 承认缺口比装作完美更好。

### 四、MLOps / 系统设计

**Q9: Why a 6-stage pipeline with checkpoints? Isn't that overkill for a portfolio?**
A: 是 portfolio，但架构和真生产一样：
1. **Stage-level failure isolation** — `load_sql` 失败不污染前面 4 个 stage
2. **Checkpointing** — 故障恢复从 1 小时降到 ~10 秒
3. **Schema validation at boundary** — 脏数据不跨 stage 传染
4. **Drift detection** — 6 阶段最末，KS-test / 卡方，模拟生产监控

1 月加 4 个 DMA 时，pipeline 跑到 `detect_anomalies` 立刻抛 schema 错，告诉我哪一列不对 — 不用等 dashboard 加载才看见。
🔍 听 checkpoint 解决什么问题，不是"我会用 stage pipeline"。

**Q10: I see `clean`, `detect_anomalies`, `predict` stages — what do they do for real data?**
A: **老实说 real 模式下它们基本是 no-op 或 validator**，因为异常检测和预测已经在 converter 那一层做完了（增量场景下必须在那做，否则 pipeline 跑 3 小时）。
- `clean`: real data 上游清洗过 → `{"status": "skipped"}`
- `detect_anomalies`: 只验格式 + distribution stats，**不重跑检测**
- `predict`: 只检查行数 >0，**不重跑预测**

实际工作量在 `load_sql`（11 表 + 4.6M 行 ATTACH + 索引）和 `drift`（KS / 卡方）。

**架构判断**而不是失误：detection 移到 pipeline 跑 3 小时，prediction 训练 9,963 个模型要 3 小时，daily workflow 就废了。**重活留 converter（增量、~55s），监督留 pipeline（轻量、~10s）**。
🔍 这题 90% 候选人不知道。答出来 = 强信号：你有架构判断。

**Q11: 100x more meters (1M), what breaks first?**
A: 1. **Converter 内存合并** — 1M meter × 151 天 = 600MB 缓存，5-10 分钟/天
2. **`hourly_meter.db`** — 30 天窗口从 4.6M 行变 460M 行，**SQLite 直接死**（专门 cap 30 天就是这个原因）
3. **Excel 读** — 30 个 2.5M 行文件，openpyxl 1h+

改法：Polars/DuckDB 替 pandas（10x）、hourly → ClickHouse、pyarrow 替 openpyxl。**Daily JSONs 不变**（dashboard 仍吃这个）。
🔍 听具体瓶颈，不是"加更多机器"。

### 五、LLM / Agent 工程

**Q12: Why 13 tools instead of one mega-tool?**
A: 工具多 = LLM 选择成本高；少 = 不知道该调谁。**3-15 是 LangChain sweet spot**。
- **JSON tools (10)**：读 `output_real/*.json`，**结构化但语义聚合**（"看 5/20 top 20"）
- **SQL tools (3)**：ad-hoc 自由查询（"5/20 凌晨 3 点某 DMA 流量"）

拆分原则：**调用成本匹配查询粒度**。问"今天异常"用 `query_anomalies(list)`，问"5/20 凌晨某 DMA"才进 SQL。System prompt 明确说"聚合用 JSON，自由查询用 SQL"。
🔍 听为什么这么拆。

**Q13: How do you evaluate the agent? How do you know it's not hallucinating?**
A: 三层防线：
1. **结构化输出** — Tool 是 typed function，参数 JSON schema 校验
2. **离线 QA 评估** — 25 个三元组（question / expected-tool / expected-keywords）
3. **手动审计** — 跑完看 5-10 个 case

已知限制：
- 关键词 recall 粗糙，LLM 答对但用不同词就算 0
- 没做 semantic eval（应 GPT-4 judge）
- 没做 hallucination detector
🔍 承认限制是 senior 标志。

**Q14: When is multi-agent mode worth it? When not?**
A: 值得 — 复合问题"对比路氹和低区过去 7 天预测精度并给原因" — 需要 plan + execute + synthesize。
不值得 — 简单查询"今天异常数"，multi-agent 多 2-3x 延迟 + cost。

UI 切 checkbox，默认关闭。**延迟 ~1s → ~4s，成本 1x → ~3x**，但复杂问题答案质量明显好。
🔍 听 trade-off 数字，不是"看情况"。

### 六、行为面

**Q15: Why pivot from water engineering to data science?**
A: 5 年水务工程师的**真实痛点**：
1. 漏损分析要手写 SQL，每次业务方问 1 小时报表
2. 异常检测全靠经验 — 老工程师凭"这户读数不对"判断，没量化
3. 预测调度靠 Excel 趋势外推，精度差

这个项目就是**把痛点用数据工程 + AI 重做一遍**。HKT 的场景结构一样 — 工程师天天写 SQL、缺量化监控、靠经验。**架构直接复用**。
🔍 听真实痛点驱动，别说"我想做 AI 改变世界"。

**Q16: Most difficult technical decision, and why?**
A: **`build.cjs` 的 loader 设计**。我之前写"try bundle first, fall back to individual JSONs"，看起来很优雅 — 一份代码支持 mock + real。

实际上：mock build 后 `dist/data/all_data.json`（3.9MB）留在那儿，下次 real build 也会复制 13 个 JSON，**loader 优先 try bundle 找到了 stale 3.9MB mock，UI 显示 mock 但用户以为是 real**。静默 bug，没报错。

修法：build.cjs 加 4 行 readdirSync + unlinkSync，**build 前清空 dist/data/**。

教训：**fallback 是反模式**，尤其当两种模式都合法时。看起来"容错"实际是"silent corruption"。
🔍 讲"失败 + 教训"比讲成功更 mature。

### 七、陷阱题

**Q17: Worst bug no one would notice for months?**
A: **API key 泄露 + 已轮换但 .env 没更新**。`bat/real/start_agent_real.bat` 之前硬编码了真 key，已迁到 `.env`，但**轮换的 key 还在 .env 里**。gitignore 兜住了上传，但 LLM provider 那边如果失效，agent 401，**用户不知道为什么**。

防御：写 `tests/test_no_secrets.py`，CI grep `sk-` / `tp-` 命中就 fail。

**Q18: 10x the budget, what would you change?**
A: 1. **Streaming ingestion** — Kafka consumer 替文件读取，latency 天→小时
2. **Polars/DuckDB 替 pandas** — converter 10x 提速
3. **Prophet/N-BEATS 替 LR** — 1M meter 训练成本可接受（GPU 一次 10 分钟）
4. **OpenTelemetry** — stage 耗时 + LLM 成本打点，grafana 看板
5. **Semantic eval** — GPT-4 judge，每月跑 trends

**Q19: Disagreed with a teammate, how handled?**
A: 真实案例：架构方向我选错了 — 我一开始想"运行时 SQL 查 dashboard 数据"。同事反馈"dashboard 是静态 HTML，应预聚合"。

我认错 + 重做。改 converter 加 incremental mode + 4 hourly JSON，~2 周工作量。

教训：**架构判断要听 domain 约束**，不要迷恋"动态查询"的灵活性。约束 = 静态 HTML + 增量更新 → 必须预聚合。

### 练习建议

1. **Q1-Q5 练表达** — 录音，2 分钟讲完项目
2. **Q6-Q14 练深度** — 每天抽 2 题口头答，对照答案
3. **Q15-Q16 练诚实** — 讲一个失败 + 教训比成功更得分
4. **Q10 重点练** — `clean`/`detect_anomalies` 是 no-op 这件事 90% 不知道，答出来 = 强信号
5. **Q16 + Q19 各备 STAR 故事** — 真实失败 + 反思 + 行动

