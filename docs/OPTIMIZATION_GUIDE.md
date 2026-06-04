# AI Agent 性能优化实战指南

> 基于 Smart Water Analytics 项目的优化经验，适用于 LangChain/LangGraph + LLM Agent 架构。

---

## 一、优化全景

### 最终效果

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 系统提示 | ~845 tokens | ~304 tokens | -64% |
| 对话历史 | ~1,600 tokens | ~400 tokens | -75% |
| 工具数量 | 18 个 | 10 个 | -44% |
| JSON 工具调用 | 15-69ms | <1ms | -95% |
| max_tokens | 2048 | 1024 | -50% |
| 工具选择 | LLM 自主选择 | 规则预选 + LLM 确认 | 减少 1-2 轮 |

### 优化层次

```
┌─────────────────────────────────────────────────┐
│  P0: 立竿见影（改几行代码）                      │
│  ├── 缩短对话历史                                │
│  └── 减少 max_tokens                            │
├─────────────────────────────────────────────────┤
│  P1: 基础优化（改几十行代码）                    │
│  ├── JSON 数据内存缓存                           │
│  └── 精简系统提示                                │
├─────────────────────────────────────────────────┤
│  P2: 架构优化（新增模块）                        │
│  ├── 对话摘要注入（长期记忆）                    │
│  └── 工具合并（18→13）                           │
├─────────────────────────────────────────────────┤
│  P3: 智能优化（新增引擎）                        │
│  └── 规则引擎工具预选                            │
└─────────────────────────────────────────────────┘
```

---

## 二、P0 立竿见影

### 2.1 缩短对话历史

**问题：** 保留 20 条消息，每条平均 80 tokens，共 ~1,600 tokens。每轮 LLM 调用都要发送全部历史。

**方案：** 保留最近 6 条（3 轮对话），旧消息压缩为摘要。

```python
# server.py
if len(chat_history) > 6:
    chat_history[:] = chat_history[-6:]
```

**效果：** 每次请求减 ~1,200 tokens，LLM 推理快 20-30%。

**注意事项：**
- 缩短历史会丢失上下文 → 用 P2 的对话摘要弥补
- 6 条是经验值：太少（3-4 条）会丢失最近的上下文，太多（10+）浪费 tokens

### 2.2 减少 max_tokens

**问题：** LLM 生成长回复（表格、emoji、详细解释），输出 tokens 多，生成慢。

**方案：** 限制最大输出长度。

```python
# agent_executor.py
max_tokens=1024  # 原 2048
```

**效果：** 输出生成时间减半，回复更简洁。

**注意事项：**
- 太小（512）会导致长回复被截断
- 1024 对大多数问题足够，复杂报告可能需要更多

---

## 三、P1 基础优化

### 3.1 JSON 数据内存缓存

**问题：** 每次工具调用都从磁盘读取 JSON 文件。`predictions.json`（377KB）每次读取 66ms。

**方案：** 用字典做内存缓存，首次读取后后续调用直接返回。

```python
_data_cache = {}

def _load(filename):
    if filename not in _data_cache:
        with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
            _data_cache[filename] = json.load(f)
    return _data_cache[filename]
```

**效果：** `get_predictions` 从 15ms 降到 0.9ms（16 倍加速）。

**注意事项：**
- 数据文件变化时缓存不会自动更新
- 静态数据（如 mock 数据）完全安全
- 生产环境需要加 `invalidate_cache()` 或 TTL 机制

### 3.2 精简系统提示

**问题：** 系统提示 ~845 tokens，包含详细的工具选择指南和能力列表。LLM 每轮都要"阅读"这些内容。

**方案：** 精简为关键指令，删除冗余描述。

```python
SYSTEM_PROMPT = """You are a Smart Water Analytics AI Assistant.

PAGE CONTEXT: If a [PAGE CONTEXT] block exists, use it directly.
Never say you can't determine the page — the answer is in the block.

TOOL GUIDE:
- query_anomalies: mode=list/stats/analyze
- query_consumption: mode=daily/weekly/compare
- get_predictions: query_type=meter/building
- SQL tools: for precise aggregations, top-N, joins

RULES:
- Always use tools for real data. Never fabricate.
- Answer in user's language. Be concise.
- anomalyScore 0-1, 0.7+ needs attention.
"""
```

**效果：** 845→304 tokens（-64%）。

**原则：**
- 删除"能力列表"（工具描述已经说明了）
- 删除"工作流程"（LLM 已经知道怎么用工具）
- 保留"关键规则"（防幻觉、页面上下文）

---

## 四、P2 架构优化

### 4.1 对话摘要注入（长期记忆）

**问题：** 缩短历史到 6 条后，旧对话的上下文丢失。用户问"上次那个水表"时 LLM 不知道指的是哪个。

**方案：** 从旧消息中提取关键信息，压缩为 `[CONVERSATION MEMORY]` 系统消息。

```python
# memory.py
def summarize_messages(messages):
    """提取用户话题、提到的时间段、区域、建筑"""
    # 关键词提取，不需要 LLM 调用
    ...

def build_memory_message(messages):
    """构建 [CONVERSATION MEMORY] 系统消息"""
    summary = summarize_messages(messages)
    return {"role": "system", "content": f"[CONVERSATION MEMORY]\n{summary}"}
```

**注入位置：** 在 system messages 中，位于 page context 之后、历史之前。

```
[PAGE CONTEXT] active_tab=anomaly, date=2026-05-05
[CONVERSATION MEMORY] User discussed: Zone-3 anomalies; Time periods: 2026-04
recent history...
user question
```

**效果：** 保留长期记忆，同时保持消息列表精简。

**进阶方案（P3）：** 用 RAG 检索更精确的历史对话，而非简单关键词提取。

### 4.2 工具合并

**问题：** 18 个工具让 LLM 选择困难，工具描述占 ~1,170 tokens。

**方案：** 用 mode/type 参数合并相似工具。

| 合并前 | 合并后 | 区分方式 |
|--------|--------|----------|
| query_anomalies | query_anomalies | mode=list/stats/analyze |
| get_anomaly_stats | ↑ | ↑ |
| analyze_anomaly | ↑ | ↑ |
| get_predictions | get_predictions | query_type=meter/building |
| get_building_predictions | ↑ | ↑ |
| query_daily_dma | query_consumption | mode=daily/weekly/compare |
| query_weekly | ↑ | ↑ |
| compare_months | ↑ | ↑ |

**效果：** 18→13 个工具，工具描述 token 减少 ~40%。

**原则：**
- 合并的工具必须有明确的语义关联
- 用 mode/type 参数区分，不要让参数太复杂
- 保持旧函数名作为别名（向后兼容）

---

## 五、P3 智能优化

### 5.1 规则引擎工具预选

**问题：** LLM 从 13 个工具中选择，可能选错或需要多轮尝试。

**方案：** 用关键词匹配预选工具，注入 `[TOOL HINT]` 系统消息。

```python
# tool_router.py
_RULES = [
    (r"同比|对比|compare", "query_consumption", {"mode": "compare"}, 1.2),
    (r"预测|forecast", "get_predictions", {"query_type": "meter"}, 1.0),
    (r"异常|spike|leak", "query_anomalies", {"mode": "list"}, 1.0),
    ...
]

def route_question(question):
    """匹配关键词，返回推荐工具列表"""
    ...

def format_tool_hint(recommendations):
    """格式化为 [TOOL HINT] 系统消息"""
    ...
```

**注入效果：**
```
User: 5月用水同比4月

[System] [TOOL HINT] Based on the question, consider using:
  - query_consumption(mode=compare, month1=2026-05, month2=2026-04)

[Agent] → 直接调用 query_consumption，跳过"思考调用哪个工具"环节
```

**效果：** 减少 1-2 轮 LLM 调用，响应更快。

**进阶方案：** 用 ML 分类器替代规则引擎，准确率更高但需要训练数据。

---

## 六、未采用的方案（及原因）

### 6.1 向量搜索（RAG）用于异常查询

**方案：** 对 anomalies 做 embedding，用户问"漏水"时语义匹配 spike 类型。

**放弃原因：** 异常记录高度重复（48 条中 20+ 条 spike），向量区分度低，结果太多且不精确。

**适用场景：** 历史对话检索（每轮对话内容独特，区分度高）。

### 6.2 响应缓存

**方案：** 对相同参数的查询缓存 LLM 响应。

**放弃原因：** LLM 响应受对话历史影响，相同问题在不同上下文中答案不同。缓存命中率低。

**适用场景：** 无状态的 API 查询（如纯数据查询，不经过 LLM）。

### 6.3 流式输出优化

**方案：** 减少 SSE 事件频率，批量发送 token。

**放弃原因：** 当前实现已经足够快，瓶颈在 LLM 推理而非网络传输。

---

## 七、LLM 提供商选择经验

| 提供商 | 协议 | tool use 支持 | 推荐 |
|--------|------|--------------|------|
| OpenAI GPT-4o | OpenAI API | 完整 | ⭐ 首选 |
| Anthropic Claude | Anthropic API | 完整 | ⭐ 首选 |
| DeepSeek | OpenAI 兼容 | 支持 | 可用 |
| mimo-v2.5-pro | OpenAI 兼容 | 支持 | 可用 |
| MiniMax-M3 | Anthropic 兼容 | **不支持** | ❌ 不推荐 |
| MiniMax-M3 | OpenAI 兼容 | **不支持** | ❌ 不推荐 |

**关键发现：**
- Anthropic 兼容端点 ≠ Anthropic API。第三方通过兼容端点提供服务时，tool use 可能不完整。
- OpenAI 兼容协议的 tool use 支持更广泛、更稳定。
- 如果 LLM 不支持 tool use，它会**幻觉工具调用**（文字说"我调用了工具"，但实际没有）。

**诊断方法：** 在 LangGraph 的 tools 节点加日志。如果没有 `[chat] tool=xxx` 输出，说明 LLM 没有真正调用工具。

---

## 八、Windows 开发经验

### 8.1 Bat 文件必须用 CRLF

LF 换行的 bat 文件在 cmd.exe 中报错 `'xxx' is not recognized`。

```gitattributes
*.bat     text eol=crlf
```

### 8.2 端口冲突静默失败

Python 的 uvicorn 在端口被占用时抛 `WinError 10048`，窗口闪退。

```bat
REM 启动前检查端口
for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"`) do (
  if not "%%P"=="" taskkill /PID %%P /F >nul 2>&1
)
```

### 8.3 非包目录的 import

`agent/` 没有 `__init__.py`，不是 Python 包。用 sys.path bootstrap：

```python
from pathlib import Path
_agent_dir = str(Path(__file__).resolve().parent)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)
from sql_tools import ALL_SQL_TOOLS
```

---

## 九、检查清单

每次优化前，按此清单评估：

- [ ] 瓶颈在哪？（LLM 推理 / 工具执行 / 网络传输）
- [ ] 改动能量化吗？（tokens、ms、轮次）
- [ ] 风险多大？（改 1 行 vs 重写模块）
- [ ] 有没有副作用？（丢失上下文、缓存过期、兼容性）
- [ ] 能回滚吗？（git revert / feature flag）
