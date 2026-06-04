# Agent 性能分析与优化方案

## 性能瓶颈定位

### 瓶颈 1：LLM 推理时间（主瓶颈，占 80%+）

每次用户提问，Agent 需要 **2-4 轮 LLM 调用**：

```
用户提问 → LLM 思考 → 调用工具 A → LLM 思考 → 调用工具 B → LLM 思考 → 生成回答
          [1 次]                    [1 次]                    [1 次]
```

每轮 LLM 调用需要处理：
- 系统提示：~845 tokens
- 工具描述：~1,170 tokens
- 对话历史：~1,600 tokens（20 条消息）
- 当前轮次的上下文：~1,000 tokens
- **每轮合计：~4,600 tokens 输入**

3 轮总计：**~13,800 tokens 输入 + 输出**

mimo-v2.5-pro 每轮推理约 3-8 秒，3 轮就是 **10-25 秒**。

### 瓶颈 2：对话历史过长

当前保留最近 20 条消息（~1,600 tokens），其中包含：
- 10 条页面上下文失败记录（messages 0-9）— **完全无用**
- 重复的相似问题

每次请求都要发送这 20 条消息给 LLM，增加了：
- 输入 token 数 → 推理时间变长
- LLM 注意力分散 → 可能忽略关键信息

### 瓶颈 3：18 个工具过多

LLM 每次推理都要"阅读"所有 18 个工具的描述来决定调用哪个：
- 工具描述总计：~1,170 tokens
- 选择空间大 → LLM 可能选错工具或需要更多思考轮次

### 瓶颈 4：JSON 文件每次从磁盘读取

`_load()` 函数每次工具调用都从磁盘读取 JSON 文件：
- `predictions.json`：377KB，66ms
- `predictions_by_building.json`：90KB，69ms
- `daily_dma.json`：95KB，39ms
- 其他文件：1-5ms

虽然单次很快，但在多轮调用中会累积。

### 瓶颈 5：LLM 回复过于冗长

LLM 生成大量 Markdown 表格、emoji、详细解释，增加了输出 token 数和生成时间。

---

## 量化数据

| 指标 | 当前值 | 优化目标 |
|------|--------|----------|
| 对话历史条数 | 20 条 | 5-8 条 |
| 历史 token 数 | ~1,600 | ~400 |
| 工具数量 | 18 个 | 10-12 个 |
| 工具描述 token 数 | ~1,170 | ~600 |
| 每轮 LLM 输入 token | ~4,600 | ~2,500 |
| LLM 轮次 | 2-4 次 | 1-2 次 |
| 预估总耗时 | 10-25 秒 | 3-8 秒 |

---

## 优化方案（按优先级排序）

### 方案 1：缩短对话历史（效果最明显，改动最小）

**文件：** `agent/server.py`

```python
# 当前：保留最近 20 条
if len(chat_history) > 20:
    chat_history[:] = chat_history[-20:]

# 优化：保留最近 6 条（3 轮对话）
if len(chat_history) > 6:
    chat_history[:] = chat_history[-6:]
```

**效果：** 每次请求减少 ~1,200 tokens 输入，LLM 推理快 20-30%。

### 方案 2：JSON 数据缓存（消除重复磁盘读取）

**文件：** `agent/agent_tools.py`

```python
# 当前：每次调用都读磁盘
def _load(filename):
    with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)

# 优化：内存缓存
_data_cache = {}

def _load(filename):
    if filename not in _data_cache:
        with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
            _data_cache[filename] = json.load(f)
    return _data_cache[filename]

def invalidate_cache():
    """Server restart or data refresh calls this."""
    _data_cache.clear()
```

**效果：** 首次调用后，后续工具调用的 JSON 加载时间从 38-69ms 降到 <0.1ms。

### 方案 3：减少工具数量（减少 LLM 选择困难）

当前 18 个工具可以合并为 ~10 个：

| 当前工具 | 合并方案 |
|----------|----------|
| `get_anomaly_stats` + `query_anomalies` + `analyze_anomaly` | → `query_anomalies(type=summary/detail/analyze)` |
| `get_building_predictions` + `get_predictions` | → `get_predictions(type=meter/building)` |
| `query_daily_dma` + `query_weekly` + `compare_months` | → `query_consumption(type=daily/weekly/compare)` |
| `generate_report` | 保留 |
| `generate_chart` | 保留 |
| `query_monthly_diff` | 保留（NRW 专用） |
| `query_rank_changes` | 保留 |
| `query_meters` | 保留 |
| `get_data_overview` | 保留 |
| `get_current_page_context` | 保留 |
| 3 个 SQL 工具 | 保留 |

**效果：** 工具描述 token 减少 ~40%，LLM 选择更快更准。

### 方案 4：精简系统提示（减少每轮开销）

当前系统提示包含详细的工具选择指南（~845 tokens）。可以精简为：

```python
SYSTEM_PROMPT = """You are a Smart Water Analytics AI Assistant.

PAGE CONTEXT: If a [PAGE CONTEXT] block exists, use it directly to answer
page-related questions. Never say you can't determine the page.

RULES:
- Use tools to get real data. Never fabricate numbers.
- Answer in the user's language.
- Keep answers concise: key findings first, details on request.
- For precise queries (top-N, sums, joins), prefer SQL tools.
- For summaries and overviews, prefer JSON tools.
"""
```

**效果：** 系统提示从 ~845 tokens 减少到 ~200 tokens。

### 方案 5：限制 LLM 输出长度

**文件：** `agent/agent_executor.py`

```python
# 当前
max_tokens=2048

# 优化：减少输出长度
max_tokens=1024
```

**效果：** LLM 生成时间减半，回复更简洁。

### 方案 6：添加响应缓存（可选，高级优化）

对相同参数的查询缓存 LLM 响应：

```python
from functools import lru_cache

@lru_cache(maxsize=32)
def _cached_tool_call(tool_name: str, args_json: str) -> str:
    tool = tool_map[tool_name]
    return tool.invoke(json.loads(args_json))
```

**效果：** 重复查询秒返回。

---

## 推荐实施顺序

1. **方案 1**（缩短历史）— 改 1 行代码，立即见效
2. **方案 2**（JSON 缓存）— 改 ~10 行代码，消除磁盘 IO
3. **方案 5**（减少 max_tokens）— 改 1 行代码，回复更快
4. **方案 4**（精简提示）— 改提示文本，每轮都省 tokens
5. **方案 3**（合并工具）— 改动较大，需要重写工具定义
6. **方案 6**（响应缓存）— 可选，适合生产环境

**前 4 项改动量小、风险低、效果明显，建议优先实施。**
