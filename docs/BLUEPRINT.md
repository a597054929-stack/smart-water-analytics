# Smart Water Analytics — 项目蓝图

> 用简单的方式说明整个方案的技术细节。

---

## 一、这个项目做什么？

一家水务公司每天从 500 个水表采集用水数据。这个系统做三件事：

1. **清洗数据** — 去掉传感器故障、缺失值、异常尖峰
2. **发现问题** — 自动检测哪个水表、哪个区域出了异常
3. **回答问题** — 用户用自然语言提问（中文或英文），AI Agent 自动查数据并回答

---

## 二、数据流全景

```
原始 JSON 文件（每天 500 条）
        │
        ▼
┌─────────────────────────────────┐
│         数据管道 (pipeline)       │
│                                 │
│  1. ingest    读取 JSON          │
│  2. clean     IQR 缩尾 + 插值    │
│  3. detect    异常检测 + 数据质量 │
│  4. predict   7 天预测           │
│  5. load      写入 SQLite        │
│  6. drift     漂移检测           │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│     SQLite 数据库 (analytics.db) │
│                                 │
│  表: meters, anomalies,         │
│      predictions, consumption,  │
│      daily_dma, weekly, ...     │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│     AI Agent (LangGraph)        │
│                                 │
│  13 个工具:                      │
│  ├─ 10 个 JSON 工具（预汇总数据）│
│  └─ 3 个 SQL 工具（实时查询）    │
│                                 │
│  用户: "Zone-3 有多少异常？"      │
│  Agent: 调用 query_anomalies    │
│  返回: 8 条异常记录              │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│     Web 前端（ECharts 仪表盘）   │
│                                 │
│  对话窗口 + 图表 + 异常列表      │
└─────────────────────────────────┘
```

---

## 三、管道：6 个阶段详解

### 阶段 1: Ingest（采集）
- 读取 `backend/data/output/*.json` 文件
- 每个文件包含 500 个水表的日用水量
- 输出：Pandas DataFrame

### 阶段 2: Clean（清洗）
- **IQR 缩尾（Winsorization）**：用 Q1-3×IQR 和 Q3+3×IQR 作为上下界，超出的值替换为边界值
- **为什么缩尾不删除？** 删除会破坏时间序列连续性。缩尾保留记录存在性，同时限制幅度
- **缺失值插值**：相邻日期线性插值

### 阶段 3: Detect Anomalies（异常检测）
- Z-score > 3 标记为异常
- 滚动窗口（7 天）检测局部异常
- 输出异常记录到 `anomalies.json`

### 阶段 4: Predict（预测）
- 指数平滑（Exponential Smoothing）做 7 天预测
- 每个水表独立预测
- 输出到 `predictions.json`

### 阶段 5: Load SQL（写入数据库）
- 写入 SQLite，自动建索引
- 索引字段：`meterId`、`date`、`dma`
- 典型查询 O(log n)

### 阶段 6: Drift（漂移检测）
- **数值列**：KS 检验（Kolmogorov-Smirnov），p < 0.05 标记漂移
- **分类列**：卡方检验（Chi-square），p < 0.05 标记漂移
- 首次运行存基线，后续对比基线
- 输出 `drift_report.json`

### 检查点机制
```
ingest ✓  →  clean ✓  →  detect ✓  →  predict ✗  →  load  ⏭  →  drift  ⏭
                                   ↑
                          下次从这里恢复
```
每个阶段完成后保存检查点。失败后，下次运行从最后一个成功的阶段恢复，不重做已完成的工作。

---

## 四、AI Agent：如何回答用户问题

### 架构：ReAct Agent（LangGraph）

```
用户问题
    │
    ▼
┌──────────────┐
│  LLM 推理    │ ← 系统提示 + 工具描述 + 对话历史
│  (mimo-v2.5) │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│  工具路由    │────▶│  执行工具     │
│  (tool_router)│     │  (agent_tools)│
└──────────────┘     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  LLM 综合    │ → 最终回答
                     └──────────────┘
```

### 工具分类

**JSON 工具（预汇总数据，内存缓存 <1ms）：**

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `query_anomalies` | 异常查询 | mode: list / stats / analyze |
| `query_consumption` | 用水量查询 | mode: daily / weekly / compare |
| `get_predictions` | 预测查询 | query_type: meter / building |
| `query_meters` | 水表信息 | — |
| `get_data_overview` | 数据总览 | — |
| `query_rank_changes` | 排名变化 | — |
| `query_monthly_diff` | 主分表差（NRW） | — |
| `generate_chart` | ECharts 图表 | chart_type |
| `generate_report` | 生成报告 | — |
| `get_current_page_context` | 页面上下文 | — |

**SQL 工具（实时查询数据库）：**

| 工具 | 功能 |
|------|------|
| `list_tables_tool` | 列出数据库所有表 |
| `get_table_schema_tool` | 查看表结构 |
| `sql_query` | 执行任意 SQL |

### Agent 如何选择工具？

两种机制配合：

1. **规则引擎预选（tool_router.py）**：用户提问时，用关键词匹配预选最可能的工具，注入 `[TOOL HINT]` 系统消息
   - "5月用水同比4月" → 推荐 `query_consumption(mode=compare, month1=2026-04, month2=2026-05)`
   - "Zone-3 异常" → 推荐 `query_anomalies(mode=list, dma=Zone-3)`

2. **LLM 确认**：LLM 看到 TOOL HINT 后决定是否使用推荐工具，或根据上下文选择其他工具

### 为什么混合使用 JSON 和 SQL 工具？

- **JSON 工具**：预汇总数据，查询快（<1ms），适合"概览"类问题
- **SQL 工具**：实时查询数据库，灵活，适合精确聚合、Top-N、JOIN
- 一轮对话可以混合使用两种工具

---

## 五、性能优化

### 优化前 vs 优化后

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 系统提示 | ~845 tokens | ~304 tokens（-64%） |
| 对话历史 | ~1,600 tokens | ~400 tokens（-75%） |
| 工具数量 | 18 个 | 13 个（-28%） |
| JSON 工具调用 | 15-69ms | <1ms（-95%） |

### 优化手段

```
P0: 缩短对话历史（20→6条） + 减少 max_tokens（2048→1024）
P1: JSON 内存缓存 + 精简系统提示
P2: 对话摘要注入 + 工具合并（18→13）
P3: 规则引擎工具预选
```

---

## 六、评估体系

### 25 道 QA 测试题

```json
{
  "question": "Zone-3 有多少异常？",
  "expected_tool": "query_anomalies",
  "expected_params": {"mode": "list", "dma": "Zone-3"},
  "keywords": ["异常", "Zone-3"]
}
```

### 评分指标

- **工具准确率**：Agent 是否调用了正确的工具
- **参数准确率**：参数是否正确
- **关键词召回率**：回答中是否包含关键信息

### 为什么不用 RAGAS？

RAGAS 针对 RAG 管道（忠实度、回答相关性）。这个 Agent 是**工具调用型**，不是检索型。评估的是工具准确率和关键词召回率。

---

## 七、前端

- **ECharts 图表**：异常分布、用水趋势、预测曲线
- **对话窗口**：实时流式 SSE 输出，显示正在运行的工具
- **多 Agent 模式**：可选的 Planner → Executor → Synthesizer 三阶段模式
- **响应式**：支持手机和桌面

---

## 八、项目文件结构

```
portfolio/
├── agent/                    # AI Agent 核心
│   ├── server.py            # FastAPI 服务器 + SSE 流式输出
│   ├── agent_executor.py    # ReAct Agent + 系统提示
│   ├── agent_tools.py       # 13 个 LangChain 工具
│   ├── sql_tools.py         # Text-to-SQL 工具
│   ├── tool_router.py       # 规则引擎工具预选
│   ├── memory.py            # 对话记忆摘要
│   └── _page_state.py       # 页面上下文状态
├── pipeline/                 # 数据管道
│   ├── orchestrator.py      # 管道运行器（6 阶段）
│   ├── schema.py            # Pandera Schema 验证
│   ├── data_quality.py      # IQR 缩尾 + 缺失值处理
│   ├── drift.py             # KS 检验 + 卡方检验
│   └── predict.py           # 指数平滑预测
├── tests/                    # 评估框架
│   ├── qa_pairs.json        # 25 道 QA 测试题
│   ├── evaluate.py          # 评分逻辑
│   └── test_*.py            # 单元测试（39 个）
├── frontend/                 # Web 前端
├── backend/data/             # 数据目录
├── reports/                  # 运行报告
├── docs/                     # 文档
├── scripts/                  # 工具脚本
├── Dockerfile                # Docker 镜像
├── docker-compose.yml        # 一键启动
├── requirements.txt          # Python 依赖
├── LICENSE                   # MIT 协议
└── .env.example              # 环境变量模板
```

---

## 九、跨行业映射

同样的架构模式可以迁移到其他行业：

| 项目能力 | 电信行业等价 |
|----------|-------------|
| 每日水表数据采集 + 清洗 | CDR（通话记录）采集、过滤噪声事件 |
| 异常检测（Z-score + 滚动窗口） | 欺诈检测、网络故障检测 |
| 7 天预测（指数平滑） | ARPU 预测、流失风险预测 |
| Text-to-SQL Agent | 运维查询机器人（网络计数器、工单系统） |
| 数据漂移检测 | 用户行为漂移、网络拓扑漂移 |
| 评估测试套件 | A/B 测试评分、模型回归 CI/CD |
| Pandera Schema 验证 | 上下游数据契约 |

**架构模式可迁移，数据领域不同但方法论一致。**

---

## 十、技术栈总结

| 层 | 技术 | 为什么选它 |
|----|------|-----------|
| Agent 框架 | LangGraph (LangChain) | ReAct 循环、工具绑定、流式输出 |
| LLM | mimo-v2.5-pro (OpenAI 兼容) | 支持 tool use、速度快、成本低 |
| 数据管道 | Pandas + Pandera | 声明式 Schema 验证、Python 原生 |
| 数据库 | SQLite | 零基础设施、SQL 语法通用 |
| 漂移检测 | SciPy (KS + chi²) | 统计检验、可设阈值 |
| 前端 | ECharts + SSE | 丰富图表、实时流式输出 |
| 服务器 | FastAPI | 异步、流式 SSE 原生支持 |
| 容器化 | Docker + docker-compose | 一键启动开发环境 |
