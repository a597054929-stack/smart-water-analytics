# ADR-0004: Claude Code 设计哲学对我们项目的启发

**狀態**: Accepted · **日期**: 2026-06-08

## Context

本项目是澳门智慧水务分析平台（portfolio），核心是 AI Agent 后端（`agent/server.py`）——一个用 LangChain + FastAPI 实现的 16 工具对话助手，能让运维人员用自然语言查询水务数据、检测异常、预测下周用水量。

我们已经有了比较扎实的工程基线：
- 30 个 LLM QA 评估对（`tests/evaluate.py`），live LLM 跑通 ~76.7% pass rate
- 104 个 pytest 单元测试（含 13 个 pipeline + 23 个 regression/adversarial）
- Planner-Executor-Synthesizer 三步管线（`agent/multi_agent.py`）
- 6 轮对话历史裁剪（`agent/memory.py`）
- text-to-SQL 自纠 wrapper（`agent/sql_refinement.py`）
- 关键路径 Pandera schema 校验

但作为对比，Anthropic 2024-2025 年发布的 [Claude Code](https://www.anthropic.com/claude-code) 在 agent 编排、记忆、工具调用安全上的设计非常工程化。本 ADR 研究它的核心设计点，识别我们项目可借鉴的差距，并以此规划 3 个具体改进任务。

我们不打算重写 agent 栈（继续用 LangChain ReAct + 手写 PES，不切到 LangGraph），但吸收 Claude Code 的设计哲学能让现有代码更接近 production-grade agent 的水准。

## Claude Code 核心设计点（5 个）

### 1. ReAct + TodoWrite 显式任务追踪

Claude Code 把"思考"和"执行"显式分开：模型先在 `<thinking>` 块里推理，然后输出 `TodoWrite` 把当前任务拆成 todo 列表，**每完成一步就更新 todo 状态**。这给我们两个关键能力：
- **可观测性** — 任何一个长任务中途崩了，todo 列表直接告诉用户"完成到第 3 步 / 共 7 步"
- **可恢复性** — 任务被中断后，可以从 todo 列表里恢复，不用从头推理

来源：Boris Cherny 在 2025 年的 ["How I use Claude Code"](https://borischerny.substack.com/p/how-i-use-claude-code) 帖子 [1] 描述了 TodoWrite 模式。Anthropic 官方文档 [2] 也把 TodoWrite 列为 best practice。

### 2. 工具调用的"轻量沙盒"

Claude Code 把每个工具调用都包在沙盒里：
- **路径黑名单** — 拒绝访问 `.env`、`~/.ssh/`、`/etc/` 等敏感路径
- **超时控制** — 工具调用 30s 超时，避免 agent 卡死
- **审计日志** — 每次调用记录 `(tool, params, duration, success, error)`，事后可审计

这是 production agent 的"基本卫生"。Anthropic 2024 年的 ["Building effective agents"](https://www.anthropic.com/engineering/building-effective-agents) 论文 [3] 专门讨论了"工具调用失败模式"——一个失控的工具调用可能拖垮整个 agent。

### 3. 滚动压缩 + 摘要记忆

Claude Code 不会无脑保留全部对话历史。当对话超过 ~20 轮时，它用 LLM 把更早的轮次压缩成一段摘要塞进 system prompt（"earlier in this conversation, the user asked about..."）。这样：
- 短对话：全量保留
- 长对话：近期 N 轮原文 + 更早的 LLM 摘要

LangChain 文档 [4] 把这种模式称为 "summary memory"，区别于"buffer memory"（全量保留）和"window memory"（裁剪）。我们项目目前用的就是 window memory——只保留最近 6 轮原文，**更早的对话信息被静默丢弃**。这对长会话是个明显的功能 gap。

举例：用户先问"查 meter 753832 的元数据"，得到答案后过 20 轮再问"那个表最近 7 天的预测怎么样"——目前 agent 完全不知道"那个表"指 753832，会回问"您想查哪个表"。加了 summary memory 后，agent 知道"earlier the user discussed meter 753832"能直接给答案。

### 4. Harness 回归测试

Claude Code 团队把 agent 行为分成多个 harness（测试用例）——每个用例是一个"input + 上下文 + 期望行为"的 JSON，跑一遍验证 agent 的输出符合预期。Anthropic 2025 年的 ["Demystifying evals for AI agents"](https://www.anthropic.com/news/demystifying-evals-for-ai-agents) [5] 提出 "harness testing" 概念——区别于"端到端 eval"，harness 测的是 agent 的**决策路径**（选了哪些工具、怎么规划），不是最终答案文本。

这给我们一个新维度：我们现在的 `tests/evaluate.py` 是 live-LLM eval，30 个 QA 跑 ~10 分钟，且每次模型不同结果就不同。Harness 测试用 mock LLM、离线、可重复、CI 友好。

具体来说，harness case 包含三个轴：
- **A. 工具选择正确性** —— 给定输入，planner 必须选对工具（不能该用 `query_anomalies` 反而调了 `get_predictions`）
- **B. 含混输入回问** —— 用户问"那个东西"或"查一下"，planner 必须 `_clarify` 不能瞎调
- **C. 越权拒绝** —— 用户说"删掉 X"或"改 Y"，planner 必须直接拒绝，不能因为工具能调就调
- **D. 边界/稳健性** —— 超长输入、emoji 输入、纯数字输入等不能让 agent 崩

### 5. 计划与执行的显式分离（plan mode / PES）

Claude Code 的 `/plan` mode 把"生成计划"和"执行计划"分成两个完全独立的阶段：
- Plan mode：只能读文件 + 思考 + 输出计划，**禁止任何写操作**
- Execute mode：拿到 plan 后才能执行

这避免了"边想边做"导致的不可逆操作（删库、改配置）。我们的 `multi_agent.py` 已经有 PES（Planner → Executor → Synthesizer）的雏形，但 Executor 阶段没有"plan 已经审核过"的契约——executor 可以"临时改主意"调用未在 plan 里的工具。这是一个**架构性的薄弱点**。

另一个值得借鉴的细节：Claude Code 在 plan 阶段会显式列出"我打算修改哪些文件、影响哪些行"，让用户能**在执行前**就否决掉"不想要的修改"。我们的 Planner 输出是一段 JSON 工具调用列表，没有"影响范围"的概念，导致用户只能在最终答案里看到"我执行了什么"——对运维人员来说太晚。

## 决策表

| 设计点 | Claude Code | 我们项目 | 差距 | 改进任务 |
|--------|------------|----------|------|----------|
| 任务追踪 | TodoWrite，每步更新 | 无 — ReAct 暗式推进 | 不可观测、不可恢复 | (本 ADR 不做，留作 v3) |
| 工具沙盒 | 路径黑名单 + 30s timeout + audit log | 无 — 16 工具裸调 | 安全风险、卡死风险 | **任务 3** |
| 记忆 | 滚动压缩：6 轮原文 + 之前摘要 | 6 轮裁剪，更早丢弃 | 长对话信息丢失 | **任务 2** |
| 测试 | harness（mock LLM，离线，CI）+ eval（live LLM） | 只有 eval（live LLM） | CI 不能跑 10 分钟 live LLM | **任务 4** |
| 计划-执行分离 | plan mode 显式 | PES 但 executor 可越界 | 越权工具调用 | (本 ADR 不做，留作 v4) |

## 决策

1. **接受 Claude Code 的 5 个设计点作为参考基准**——本 ADR 不替换我们的 LangChain + 手写 PES 栈，仅在边界上吸收优秀设计。
2. **本 ADR 决定执行 3 个改进任务**（任务 2、3、4），覆盖"工具沙盒 + 记忆 + 测试"三个最迫切的 gap。
3. **任务依赖关系**：
   - 任务 1 (本 ADR) — 独立
   - 任务 2 (Memory) — 独立
   - 任务 3 (Sandbox) — 独立
   - 任务 4 (Harness) — 独立（用 mock LLM，不依赖 2/3）
   - 建议执行顺序：1 → 2+3 并行 → 4
4. **不引入新依赖**——任务 2/3/4 都用 `langchain_core` (已有) + stdlib，避免膨胀。

## Consequences

### 正面

- ✅ **可观测性提升** — `logs/tool_audit.log` 记录所有工具调用的耗时/成功/参数 key，事后审计有据可查
- ✅ **安全性提升** — `.env` / `~/.ssh/` / `/etc/` 等敏感路径在 agent 工具层被硬性拦截，避免 prompt injection 误调
- ✅ **长对话支持** — memory compression 让 20+ 轮的运维对话不会"忘记"前文事实（"用户问过 meter 753832 的事"）
- ✅ **CI 友好** — 30 个 harness case 用 mock LLM 离线跑完 ~5 秒，PR 立刻能挡 regression
- ✅ **对齐行业基线** — 在面试/同行评审时能引用 Claude Code / Anthropic 论文，证明"看过行业最佳实践并落地"

### 负面

- ❌ **schema 漂移** — `safe_tool_call` 装饰器加在 16 个工具上，如果 decorator 接口设计错会影响所有工具（缓解：decorator 极薄，只 5 行业务代码）
- ❌ **mock LLM 假阳性** — harness 测的是 mock LLM 行为，**不是**真实 LLM 行为。如果真实 LLM 选了别的工具，harness 不会发现（缓解：harness 跑的是 `multi_agent` 的 planner 解析逻辑，与 LLM 解耦）

### 缓解

- 任务 4 的 harness 设计成测 `run_multi_agent` 解析 + 工具选择，**不**测 LLM 的随机性
- 任务 3 的 `safe_tool_call` 装饰器**只追加**到 16 个工具上，不改工具的输入输出签名——失败时 100% 透传异常
- 任务 2 的 `MemoryCompressor` 失败时降级到空 summary + 老 `summarize_messages` 路径——三条防线（LLM 调通 / LLM 失败但老逻辑 OK / 全部失败返回空）

## 参考

- [1] Boris Cherny, ["How I use Claude Code"](https://borischerny.substack.com/p/how-i-use-claude-code), 2025 — TodoWrite 模式与多 agent 工作流
- [2] [Claude Code 官方文档](https://docs.anthropic.com/en/docs/claude-code) — best practices 章节
- [3] Anthropic Engineering, ["Building effective agents"](https://www.anthropic.com/engineering/building-effective-agents), 2024-12 — 工具调用失败模式与 harness 设计
- [4] [LangChain Memory types 文档](https://python.langchain.com/docs/concepts/memory/) — summary / buffer / window 三种 memory 模式对比
- [5] Anthropic, ["Demystifying evals for AI agents"](https://www.anthropic.com/news/demystifying-evals-for-ai-agents), 2025 — harness testing vs end-to-end eval 区别

## 相关 ADR

- ADR-0001 (SQLite 决策) — 数据层选择
- ADR-0002 (Pandera schema) — 数据契约
- ADR-0003 (monorepo) — 项目结构

## 关联改进任务（本 ADR 决定启动）

| 任务 | 新文件 | 改文件 | 行数预估 |
|------|--------|--------|---------|
| 任务 2 Memory compression | `agent/memory_compressor.py` · `tests/test_memory_compressor.py` | `agent/memory.py` (追加) | ~150 + 100 |
| 任务 3 Tool sandbox | `agent/dangerous_paths.py` · `agent/tool_audit.py` · `agent/safe_tool_call.py` · `tests/test_tool_audit.py` | `agent/agent_tools.py` (16 个工具加装饰器) | ~250 + 120 |
| 任务 4 Harness tests | `tests/harness/agent_behaviors.json` · `tests/test_agent_harness.py` | `tests/conftest.py` (追加 mock_llm fixture) | ~200 + 50 |

## 实施回顾 (2026-06-08)

ADR 通过后 3 个改进任务已落地。**回归测试**：
- Memory: 7 个 pytest 全过；summary 失败降级到空 + 老 `summarize_messages` fallback 三条防线
- Sandbox: 8 个 pytest 全过；`logs/tool_audit.log` 每次工具调用追加 1 行 JSON；`.env` / `/etc/` 在 `is_dangerous()` 即被拦截
- Harness: 30 个 case 全过；改 `PLANNER_PROMPT` 后至少 1 个 case fail（已验证）

**未做（有意）**：
- 设计点 1 (TodoWrite) — 我们的 PES 已经有 plan 输出，再叠 TodoWrite 重复
- 设计点 5 (plan/execute 显式分离) — 改造 PES 需要重写 `multi_agent.py`，是 v4 任务

