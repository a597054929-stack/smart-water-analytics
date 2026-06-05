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

## 1月8日 4294 万吨误值事件

### 现象

概览页 1月8日总用水量显示为 -4,292 万 m³，4 个 DMA 的当日柱状图看起来异常
（远超正常 2-3 万 m³/日的 4-5 个数量级）。Anomaly 页未报任何警。

### 排查过程

#### 第一阶段：定位误值来源

`daily_totals.json` 中 1月8日 meter 713911 的值为 **-42,940,982.59 m³**。
直接打开该日的源 Excel `20260108.xlsx`，发现 meter 713911 共有 24 条小时记录，
其中 22 条为 0：

- 01:00: +42,940,982.59 m³
- 02:00: -42,940,982.59 m³

两条**正负相消**的误值（可能是某次消防测试/换表读数的手工录入错位），
理想情况下应该全部丢弃。但代码里只丢弃了正向的 42940982，负向的
-42940982 因为 `consumption > MAX_METER_DAILY` 检查的是正值，单
`consumption < 0` 走 else 分支，绕过 cap，**进入 daily cache**，
与 22 条 0 相加后得到 -42,940,982.59。

#### 第二阶段：修复 cap 检查 → abs()

`scripts/real_data_converter.py`：

```python
# 之前：
if consumption > MAX_METER_DAILY:
    data_errors.append({...}); continue

# 修复后：
if abs(consumption) > MAX_METER_DAILY:
    data_errors.append({...}); continue
```

注释里要写清楚 **为什么是 abs()**——否则下一个看到代码的人会以为
多此一举，再"简化"回去。

#### 第三阶段：单日测试 → 全量修补

因为全量 151 天的 Excel 重读需要 3 小时（pandas+openpyxl 50s/文件），
先写一个**只跑 1月18日**的独立测试脚本，验证修复后 0 个误报（无干净日被错杀），
**1月8日**作为对照，确认 meter 713911 的 +/- 两行都被记录到 data_errors。
两日测试都通过后，**不再重跑 151 天 Excel**，而是直接修补缓存：

```python
# 1) 扫描缓存里 abs>40000 的剩余漏网值（找到了 2 个：1月8 713911 + 1月30 773591）
# 2) 从缓存删除 + 追加到 data_errors.json
# 3) 对所有缓存值执行 round(v, 2) 修复浮点尾数（249,979 个值被取整）
# 4) 重新调 _build_daily_dma / _build_top20 / _build_anomalies 等下游函数
# 5) dashboard 用 `USE_REAL_DATA=1 node build.cjs` 重新打包
```

整个修补 + 重建 12 个下游 JSON + 重新打包 dist 只需 **~30 秒**，
对比全量重读 Excel 的 3 小时提速 360×。

#### 第四阶段：浮点尾数 (`3.3299999999999996`) 问题

修补缓存后，原始 JSON 里仍有大量 `3.3299999999999996` 这种值。
原因不是 `round(L/1000, 2)` 没生效（每条小时记录确实取整了），
而是**24 条 rounded 值求和**后浮点误差重新出现，且旧版本用 `round(..., 3)`
生成的缓存值现在被加载回来作为 Python float，本质就是 `3.33` 的最近
IEEE-754 表示。修复：在缓存写入前对每个值**显式** `round(v, 2)`。

### 经验总结（追加）

### 6. 对称异常：正负相消的 cap 检查

数值阈值检查（`x > limit`）对正负异常的处理不一致——正值触发，负值绕过。
金融、计量、累计计数场景几乎都会有这种"对冲"误值（消防测试、配对结算）。
**始终用 `abs(x) > limit`**，并在注释里写明。

### 7. 全量重算 vs 修补缓存的权衡

数据 pipeline bug 修复后**不要无脑全量重跑**：

- 全量重跑 = 重新读所有源文件 × 所有 I/O + 解析 + 验证 + 重新算所有衍生。
  9,963 表 × 151 天 × 24 小时 ≈ 36M 行，慢。
- 修补缓存 = 找到坏值在缓存里的位置，删除/修正 + 重新调**纯函数**的下游
  衍生函数。秒级，前提是**所有下游函数是纯函数**（只读 cache + meter_map）。

设计 pipeline 时让"读取源"和"从缓存衍生"两阶段严格分离，
后续 bug 修复就能用后者这种快路径。

### 8. 浮点尾数 (`X.9999999999`) 的根源

`json.dump(3.33)` 不会写出 `3.33` 字面量，而是 `3.3300000000000001`
（Python 3.1+ 改进了，会写出最短能往返的表示 `3.33`，但**加载回来后**
的 float 仍是 IEEE-754 不精确的）。所以即使每行源头 `round(L/1000, 2)`，
24 行 sum 之后还是会有 `3.3299999999999996`。**在缓存层**显式取整
是最便宜的修复。

#### 外部 corrections 文件（meter 712720）

##### 现象

Meter 712720 在 4/16-4/27 之间因为设置错误，原始读数被乘以 10。
原本真值约 2,600-2,700 m³/日，错误期间显示 26,000-27,000 m³/日。
需要把这段数据在源头修正，未来 converter 重跑也要保持正确。

##### 设计选择：数据进配置，代码只读配置

考虑到这是孤例（只有这一只表的设置错误），不该为它修改 converter 的核心逻辑。
最干净的抽象是外部 JSON 文件：

- **优点**：
  - 未来类似修正只需加一行 JSON，不改代码
  - 非工程师（数据分析师）也能维护
  - 修正历史有 git 记录
  - 可以用 `--corrections /dev/null` 测试时禁用所有修正
- **缺点**（可接受）：
  - 多了一个外部依赖
  - 需要保证文件路径在不同环境下都正确（用绝对路径常量解决）

**错误的替代方案**：
- ❌ 改 Excel 源文件：一次性，丢了下次 sync
- ❌ 缓存里直接除 10：没有版本控制、不在 git 里
- ❌ 改 converter 加 `DATA_CORRECTIONS` 常量：每加一只表都要改代码、rebuild
- ❌ 数据库表存修正：过度设计，1 条记录用不到

##### 实现

**`backend/data/corrections.json`**（提交到 git）：
```json
[
  {"meterId": "712720", "start": "2026-04-16", "end": "2026-04-27",
   "factor": 0.1, "reason": "设置错误-读数×10 (用户2026-06-05确认)"}
]
```

**`scripts/real_data_converter.py`**：
- 新增 `DEFAULT_CORRECTIONS_FILE` 常量
- 新增 `_load_corrections(path)` 加载器（带字段校验，缺字段报错）
- 新增 `_apply_correction(mid, date_str, consumption, corrections)` 行级修正
- `_aggregate_dates` 接受 `corrections: list[dict] | None` 参数
- **关键顺序**：行级取整 → `_apply_correction` → cap 检查
  （修正先于 cap，让修正后的值能通过更紧的 cap）
- `--corrections PATH` CLI flag（默认 `backend/data/corrections.json`）
- `MAX_METER_DAILY` 顺手从 40,000 降到 4,000（更紧的合理性见限制表）

##### 重新跑 vs 快速修补

这次需要应用 4/16 起的修正 + 新 cap。第一次尝试用 `--since 2026-04-16`
让 converter 重读 46 天 Excel 文件，估算 38 分钟。

**用户反馈"太久了"**——这是正确反应。改成快速修补路径：
1. 直接改缓存：712720 4/16-4/27 ÷10，cap>4000 的 35 条删掉、加到 data_errors
2. 重跑 `_build_daily_dma` / `_build_top20` / `_detect_anomalies` 等纯函数
3. 重新 `json.dump` 下游 12 个 JSON
4. `node build.cjs` 重新打包

**总耗时 ~30 秒**，对比 Excel 重读路径提速 75×。

**经验**：converter 修复的"快路径"前提是**所有下游 build 函数是纯函数**
（只读 cache + meter_map，不读源文件）。这次正好满足。如果某次修复需要改
源数据解析逻辑（pd.read_excel 路径），就只能走 `--full` / `--since` 慢路径。

##### 经验 9 & 10（追加）

### 9. 数据修正进配置，代码只读配置

孤例的数据修正（已知 meter 设置错误）不该写进 converter 代码。配置驱动的设计：
- 修正规则 = 数据，应该有版本控制
- 加载逻辑 = 代码，应该通用
- 两者解耦后，未来类似修正零代码改动

### 10. 修正先于 cap（顺序敏感）

数据流顺序很重要：
- 错：`cap → 修正` → 修正后值还得再过 cap，可能被多丢
- 对：`修正 → cap` → 修正后值能通过更紧的 cap，符合"已知数据正确"语义

更一般的：**已知正确的修正应当跑在所有"误值检测"之前**。修正让数据"对"，
cap 让数据"干净"，这两件事分开，顺序是修正在前。

---

## 相关文件

### Agent 页面上下文（早期调试）
- `agent/_page_state.py` — 页面上下文存储模块
- `agent/agent_tools.py` — 工具定义（含 `get_current_page_context`）
- `agent/agent_executor.py` — Agent 创建和系统提示
- `agent/server.py` — FastAPI 服务端（含诊断日志）
- `start_agent_minimax.bat` — MiniMax 启动脚本（已改为 OpenAI 兼容）
- `start_agent_mimo.bat` — mimo 启动脚本

### 1月8日 4294 万吨误值事件
- `scripts/real_data_converter.py` — `_aggregate_dates` 里的 `MAX_METER_DAILY = 40_000` cap（用 `abs()`）
- `scripts/real_data_converter.py` — phase 6 写入 `data_errors.json` + 注入 `data_error` 类型异常
- `frontend/build.cjs` — `dataErrors` loader field + `D.dataErrors` 暴露
- `frontend/js/home.js` — `renderDataIntegrity` banner + KPI tooltip `anomBreakdown`
- `frontend/js/anomaly.js` — sort-by-score (data_error 优先) + 數據異常 filter chip + CSV `data_errors` 区块
- `backend/data/output_real/data_errors.json` — 16 条累积误值 sidecar

---

## 712720 复发问题 + 自动健康监测 stage

### 问题背景

`backend/data/corrections.json` 在 2026-06-05 加入后，解决了 712720 的 4/16-4/27 ×10
配置错误。但用户提了两个延伸问题：

1. **"再跑一次 `convert_real_data.bat`，712720 会复发吗？"**
2. **"如果有新的数据质量惊喜，怎么发现？"** — 之前 712720 是用户肉眼看 `daily_totals.json` 才发现的，
   没有任何自动告警。

### 复发行为分析

| 区间 | 行为 | 原因 |
|------|------|------|
| 4/16 - 4/27 712720 | **不会复发** | `corrections.json` 每次启动都加载，`/10` 在 cap check 之前应用 |
| 4/29 712720 (37,697 m³) | **会作为 `data_error` 复发** | 4/29 是真实异常（不是配置错误），4,000 cap 正确地将其 drop 掉 |
| 新数据 | **没有自动告警** | 之前的 pipeline 没有"全表扫描异常"阶段 |

**核心认识：** 4/29 的复发是**正确**行为 — 4/29 是真异常，4,000 cap 就是要 drop 它。
问题在于用户没法在不看 cache 的情况下知道这件事。解决方案 = 一个自动健康监测 stage。

### 解决方案：两轨并行

#### 轨 1：自动监测 stage（`stage_data_health`）

`pipeline/orchestrator.py` 新增 7 号 stage `stage_data_health`，跑在所有清洗之后。
三个检测器对 `[date, meterId, total]` DataFrame 做全表扫描：

```python
detect_per_meter_outliers(threshold_z=4.0)    # 每表 z-score，捕捉 712720 / 4月16日 类
detect_daily_jumps(threshold_ratio=20.0)      # value-ratio max/min，捕捉骤增 + 归零
detect_negative_pairs(cancellation_threshold=0.01)  # 启发式，捕捉 +/- 抵消类
```

输出到 `checkpoints/stage_data_health.json`，结构 = `summary` + `recent_*`（最近 30 天 top 50）+ `*_all`。
`recent_*` 是给人类看的；`*_all` 是给 notebook 深度排查用的；`summary` 计数用于 CI 阈值。

**为什么是 value-ratio 而不是 delta-ratio：**
delta-ratio 用 `|Δtoday| / median(|Δ|)`，对**稳定**表（std≈0）失效 — 那个表的 median
delta 也是 0，无法比较。value-ratio 用 `max(value, median) / min(value, median)`，
对**任何**表都能给出一个有意义的乘数 — 2600 → 26000 在 delta-ratio 下 delta=23400（可能
median 很小，倍数失真），在 value-ratio 下直接是 10×，更直观。

**性能：** 在 905,805 行的真实数据上，detect_per_meter_outliers 0.5s（merge 向量化），
detect_daily_jumps 24.7s（仍是 iterrows），detect_negative_pairs 40.5s（仍是 iterrows）。
`daily_jumps` 和 `negative_pairs` 还能再优化（用 groupby + transform），但当前在
"每日 pipeline 跑一次"的频率下够用。

#### 轨 2：交互式调查 notebook（`01_data_correction.ipynb`）

stage 报了警之后，用户要能 30 秒内完成"调查 → 确认 → 应用 → 重建 → 验证"流程。
设计成 Jupyter notebook 是因为：

1. **用户已经习惯 `>>>`-style 内联 Python**（712720 调查时就是这么做的）
2. **可以保存 / 重跑 / 分享**给同事
3. **用 pandas 做交互式筛选**比 CLI 灵活

`_corrections_helper.py` 提供 5 个公开函数：
- `load_cache_as_df()` — 把 `daily_totals.json` 透视成 `(date, meterId, total)` DataFrame
- `find_per_meter_outliers` / `find_daily_jumps` / `find_negative_pairs` — 委托给 `dq.detect_*`
- `add_correction(...)` — 写入 `corrections.json`，带重叠检查（同 meter 已有 [start, end] 区间时拒绝）
- `rebuild_downstream(...)` — 调用 converter 自己的 `_build_*` 函数重派生 10 个 JSON，约 5 秒

**关键设计决定：辅助函数委托给 pipeline 的 `dq.detect_*`，而不是自己实现一份。**
之前两套实现各跑各的，数字对不上（helper 报 8,481 跳，pipeline 报 57,384 跳）—
refactor 后两边都是 57,384。`find_negative_pairs` 例外：保留 SQLite 抵消检测（`sum_h < abs_h * 0.1`），
因为 hourly 数据比 daily 启发式精确得多。

### 验证

1. **单元测试：** `tests/test_data_health.py` 13 个测试全绿（z>4 触发、min_history 跳
   过、value=0 算 inf、stage 空输入返回零计数），全部 `tests/` 52 个测试通过。
2. **真实数据回放：** 712720 的 4/16-4/27 在 `corrections.json` 加载后历史值是 557-2677 m³
   （/10 后），不触发 z-outlier。`find_daily_jumps` 仍报 22 跳 — 这些是真实的消费变化
   （不是配置错误），保留是正确行为。
3. **Notebook 端到端：** 跑 `01_data_correction.ipynb` 的 cell 1-7：
   - cell 1-3: 调查找到 4,882 / 57,384 / 1,200 三类异常
   - cell 4-5: 确认 712720 / 4/16-4/27 / factor=0.1
   - cell 5 的 `add_correction` 第二次跑会 raise `ValueError: overlaps existing...` —
     overlap 检查正常工作
   - cell 6: `rebuild_downstream` 写 10 个 JSON
   - cell 7: 重跑 find_*，712720 的 z-outlier = 0
4. **数据完整性 banner 仍然有效：** 4/29 712720 的 37,697 m³ 仍被 4,000 cap drop 成
   `data_error` — 这是**预期**行为，banner 仍能看见它。

### 经验教训

- **配置注入优于代码改动** — 712720 的修正通过 `corrections.json` 完成，没有改 converter
  任何一行。下一个 712720 风格的配置错误也是 30 秒的 JSON 文件改动 + 一次 notebook run。
- **告警系统要有"分级"输出** — 全量列表给 notebook 排查用，summary 计数给 CI 阈值用，
  recent top-50 给人工扫一眼用。一个 JSON 三种消费场景。
- **重写 `iterrows` 之前先 `groupby().transform()`** — `detect_per_meter_outliers` 用
  merge 之后 17× 提速（4.7s vs 8.7s on 62K rows）。其他两个仍是 iterrows，是下一轮优化点。
- **pandas `.style` 需要 jinja2** — `02_health_check.ipynb` 的 cell 2 默认会失败，fallback
  到纯文本 OK/WARN 标记。Plain text 输出在 terminal / nbconvert / GitHub 预览都能看。
- **`_corrections_helper.py` 重构为委托模式** — 之前两份实现分叉（一个跑 pipeline 算法、
  一个跑 notebook 算法），用户看到的数字不一致。改成 `find_*` 调 `dq.detect_*` 之后
  单一真相源，notebook 输出和 stage JSON 输出一致。
