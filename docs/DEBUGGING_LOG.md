# 调试经验总结：AI Agent 工具调用与页面上下文问题

## 问题背景

Smart Water AI Agent 基于 LangChain ReAct 架构，使用 FastAPI + SSE 流式输出。
前端会把当前页面状态（active_tab、selected_date、selected_dma 等）作为 `context` 传给后端，
后端通过 `set_page_context()` 存储，供 `get_current_page_context` 工具读取。

**核心问题：** 用户问"我在看什么页面"时，LLM 始终返回 "no page context available"，
声称调用了 `get_current_page_context` 工具 10 次，全部失败。

---

## 排查过程

### 第一阶段：怀疑 set_page_context 没被调用

**尝试：** 在 `server.py` 的 streaming 和 sync 端点中加了 `set_page_context` 的错误日志。

**结果：** 日志显示 `context={...}` 正常传入，`set_page_context` 没有抛异常。
但 `get_current_page_context` 工具仍然返回空。

### 第二阶段：怀疑 LangGraph 工具运行时看不到模块全局变量

**假设：** LangGraph 的 `create_react_agent` 在执行工具时，可能把工具函数绑定到了
自己的命名空间，导致 `_page_state.PAGE_STATE` 这个模块级变量对工具不可见。

**尝试：** 创建了独立的 `_page_state.py` 模块，把 `PAGE_STATE`、`set_page_context`、
`get_page_context` 从 `agent_tools.py` 抽离出来。

**结果：** 问题依然存在。工具直接调用时返回正确数据，但通过 LLM 调用时返回空。

### 第三阶段：添加调试端点直接检查服务器进程状态

**尝试：** 添加了 `/api/debug/pagestate` 端点，暴露：
- `_page_state.PAGE_STATE` 的内容
- `get_current_page_context` 工具的 `invoke()` 结果
- `get_page_context()` 直接调用结果

**结果：**
```json
{
  "PAGE_STATE": {"active_tab": "overview", "selected_date": "2026-04-15"},
  "tool_invoke_result": "{\"context\": {\"active_tab\": \"overview\", ...}}",
  "get_page_context_direct": {"active_tab": "overview", ...}
}
```
**所有值都正确！** 问题不在存储层，不在工具层，而在 LLM 层。

### 第四阶段：加诊断日志，确认 LLM 是否真正调用了工具

**尝试：** 在 `server.py` 中加了工具调用日志：
```python
if node_name == "tools" and "messages" in node_output:
    for msg in node_output["messages"]:
        print(f"[chat] tool={msg.name}", ...)
```

**结果（关键发现）：**
```
[chat] msgs=22 (sys=1 hist=20 user=1)
[chat] final_answer_preview=# ❌ 我依然看不到您眼前的屏幕...
```
**没有任何 `[chat] tool=` 行！** LLM 从头到尾没有发起过一次真正的工具调用。
它在文字中说"我调用了 10 次工具"，但这是幻觉（hallucination）。

---

## 根因

**MiniMax-M3 通过 Anthropic 兼容端点（`https://api.minimaxi.com/anthropic`）
不支持真正的 tool use。**

LLM 生成的文字中包含"我调用了 get_current_page_context"，但这只是文本输出，
不是结构化的 `tool_call`。LangGraph 从未收到 tool_call，自然也不会执行工具。

同样的原因也解释了为什么所有工具（query_weekly、get_data_overview、sql_query）
都报 "Tool result missing due to internal error" — LLM 编造了工具调用和失败结果。

---

## 解决方案

### 方案 1：换用支持 tool use 的模型（推荐）

切换到 mimo-v2.5-pro（OpenAI 兼容协议），工具调用立即正常工作。

**配置要点：**
```bat
set LLM_PROVIDER=mimo
set LLM_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1
set LLM_MODEL=mimo-v2.5-pro
```

OpenAI 兼容协议的 tool use 支持远好于 Anthropic 兼容协议。

### 方案 2：修改系统提示（兼容性兜底）

在系统提示中加入明确指令：
```
CRITICAL — PAGE CONTEXT:
If you see a [PAGE CONTEXT] block at the start of the conversation, it tells you
exactly what the user is currently viewing on their screen. Use it DIRECTLY to
answer questions like "what page am I on?". NEVER say you cannot determine the
page — the answer is always in the [PAGE CONTEXT] block.
```

这让 LLM 直接从系统消息中读取上下文，不依赖工具调用。
但这只是权宜之计 — 如果 LLM 不支持 tool use，所有数据查询工具也会失效。

### 方案 3：MiniMax 改用 OpenAI 兼容端点

```bat
set LLM_PROVIDER=openai
set LLM_BASE_URL=https://api.minimax.chat/v1
set LLM_MODEL=MiniMax-M3
```

---

## 经验教训

### 1. 工具调用失败时，先确认 LLM 是否真正发起了调用

LangGraph 的 `stream_mode="updates"` 会输出每个节点的执行情况：
- `agent` 节点：LLM 的输出（可能包含幻觉的工具调用描述）
- `tools` 节点：实际执行的工具（只有真正的 tool_call 才会触发）

**如果 `tools` 节点没有输出，说明 LLM 在编造工具调用。**

### 2. 不同 LLM 提供商的 tool use 支持差异巨大

| 提供商 | 协议 | tool use 支持 |
|--------|------|--------------|
| OpenAI | OpenAI API | 完整支持 |
| Anthropic | Anthropic API | 完整支持 |
| MiniMax | Anthropic 兼容 | **不支持**（产生幻觉） |
| MiniMax | OpenAI 兼容 | 待验证 |
| mimo | OpenAI 兼容 | 支持 |

### 3. 模块全局变量在 LangGraph 中的可见性

LangGraph 的工具运行时可能会重新绑定工具函数，导致闭包中的全局变量不可见。
解决方法：把共享状态放在独立模块（`_page_state.py`）中，通过 import 获取，
而不是依赖函数闭包。

### 4. Windows bat 文件必须用 CRLF

LF 换行的 bat 文件在 cmd.exe 中会报 "'xxx' is not recognized as an internal or
external command"。解决方法：`.gitattributes` 中加 `*.bat text eol=crlf`，
写入时用二进制模式转换换行符。

### 5. 端口冲突的静默失败

Python 的 `uvicorn.run()` 在端口被占用时抛出 `WinError 10048`，窗口会闪退。
解决方法：bat 文件启动前用 PowerShell `Get-NetTCPConnection` 检查并清理端口。

---

## 相关文件

- `agent/_page_state.py` — 页面上下文存储模块
- `agent/agent_tools.py` — 工具定义（含 `get_current_page_context`）
- `agent/agent_executor.py` — Agent 创建和系统提示
- `agent/server.py` — FastAPI 服务端（含诊断日志）
- `start_agent_minimax.bat` — MiniMax 启动脚本（已改为 OpenAI 兼容）
- `start_agent_mimo.bat` — mimo 启动脚本
