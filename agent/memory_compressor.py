"""Two-tier conversation memory: recent N turns raw + older turns summarized via LLM.

This addresses a gap in the project's memory layer: before this module
existed, ``agent/memory.py`` only kept the most recent 6 messages verbatim
(window memory). Anything older was silently dropped, so a 20-turn
conversation would "forget" meter IDs, dates, and preferences mentioned
at the start.

Pattern (per Claude Code's design + LangChain's "summary memory"):

- Short history (<= recent_turns)  →  return verbatim
- Long history                     →  summarize older turns with an LLM,
                                       keep recent N turns verbatim

Failure modes — three layers of fallback, the most graceful to the
most degraded:

1. LLM works           →  summary text + recent verbatim
2. LLM call fails      →  empty summary + recent verbatim
3. Compressor crashes  →  caller falls back to legacy ``summarize_messages``

The class is deliberately minimal: no LangChain graph, no persistence.
A higher-level helper (``get_context_for_agent`` in ``memory.py``) is
responsible for I/O and integration with ``chat_history.json``.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


SUMMARY_PROMPT = """你是一个对话摘要助手。请把以下对话历史压缩成一段简洁摘要。

要求：
- 保留所有具体数字、日期、表号、用户偏好
- 保留关键事实（"用户问过什么、回答过什么"）
- 保留数据查询的具体结果
- 不要添加对话里没有的信息
- 控制在 200 字以内

对话历史：
{history}

输出摘要："""


class MemoryCompressor:
    """Two-tier conversation memory: recent N verbatim + older summarized."""

    def __init__(
        self,
        llm,
        recent_turns: int = 6,
        summary_max_chars: int = 800,
    ) -> None:
        if recent_turns < 1:
            raise ValueError("recent_turns must be >= 1")
        if summary_max_chars < 1:
            raise ValueError("summary_max_chars must be >= 1")
        self.llm = llm
        self.recent_turns = recent_turns
        self.summary_max_chars = summary_max_chars

    def compress(self, history: list[BaseMessage]) -> dict:
        """Compress ``history`` into ``{"recent": [...], "summary": str}``.

        Short histories (len <= recent_turns) are returned verbatim with
        an empty summary — no LLM call is made.
        """
        if len(history) <= self.recent_turns:
            return {"recent": list(history), "summary": ""}

        older = history[: -self.recent_turns]
        recent = list(history[-self.recent_turns :])
        older_text = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
            for m in older
        )
        try:
            resp = self.llm.invoke(
                [SystemMessage(content=SUMMARY_PROMPT.format(history=older_text))]
            )
            content = resp.content
            if isinstance(content, list):
                # Newer LangChain versions return content as a list of blocks.
                content = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict)
                )
            summary = (content or "")[: self.summary_max_chars]
        except Exception:
            # Graceful degradation: don't blow up the agent over a
            # summarization failure. Caller can fall back to legacy
            # ``summarize_messages`` if it cares about older context.
            summary = ""
        return {"recent": recent, "summary": summary}

    def reconstruct_context(self, compressed: dict) -> str:
        """Render a compressed bundle as a single string for system-prompt injection."""
        parts: list[str] = []
        summary = compressed.get("summary") or ""
        if summary:
            parts.append(f"[Earlier conversation summary]\n{summary}\n")
        recent = compressed.get("recent") or []
        if recent:
            parts.append("[Recent conversation]")
            for m in recent:
                role = "User" if isinstance(m, HumanMessage) else "Assistant"
                parts.append(f"{role}: {m.content}")
        return "\n".join(parts)


__all__ = ["MemoryCompressor", "SUMMARY_PROMPT"]
