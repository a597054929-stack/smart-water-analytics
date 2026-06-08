"""Conversation memory — extracts key facts from old messages.

When chat_history exceeds the retention limit, older messages are summarized
into a structured memory block that gets injected as a system message.
This preserves long-term context without bloating the prompt.
"""

import re


def summarize_messages(messages: list) -> str:
    """Extract key facts from a list of chat messages.

    Returns a compact summary string suitable for injection as a system message.
    """
    if not messages:
        return ""

    user_topics = []
    mentioned_months = set()
    mentioned_dmas = set()
    mentioned_buildings = set()
    question_count = 0

    # Patterns to extract
    month_pattern = re.compile(r"20\d{2}[-/]?0[1-9]|20\d{2}[-/]?1[0-2]")
    dma_pattern = re.compile(r"Zone-\d+", re.IGNORECASE)
    building_keywords = [
        "hotel", "resort", "tower", "mall", "hospital", "school",
        "university", "centre", "center", "park", "villa",
    ]

    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue

        if msg.get("role") == "user":
            question_count += 1
            # Keep a short preview of user questions (first 50 chars)
            preview = content.strip()[:50]
            if preview and preview not in user_topics:
                user_topics.append(preview)

            # Extract time references
            months = month_pattern.findall(content)
            mentioned_months.update(months)

            # Extract DMA zones
            dmas = dma_pattern.findall(content)
            mentioned_dmas.update(dmas)

            # Extract building names (simple keyword match)
            lower = content.lower()
            for kw in building_keywords:
                if kw in lower:
                    mentioned_buildings.add(kw)

    if not user_topics:
        return ""

    # Build summary
    parts = ["User discussed: " + "; ".join(user_topics[:5])]

    if mentioned_months:
        parts.append(f"Time periods: {', '.join(sorted(mentioned_months))}")
    if mentioned_dmas:
        parts.append(f"Zones: {', '.join(sorted(mentioned_dmas))}")
    if mentioned_buildings:
        parts.append(f"Buildings: {', '.join(sorted(mentioned_buildings))}")

    parts.append(f"Total {question_count} questions asked")

    return "\n".join(parts)


def build_memory_message(messages: list) -> dict | None:
    """Build a system message containing conversation memory.

    Returns a dict suitable for inserting into the message list,
    or None if there's nothing to remember.
    """
    summary = summarize_messages(messages)
    if not summary:
        return None

    return {
        "role": "system",
        "content": f"[CONVERSATION MEMORY]\n{summary}\n"
                   "Use this to understand the user's ongoing interests and avoid "
                   "repeating information already discussed.",
    }


# ── Two-tier compression (added 2026-06-08, see ADR-0004) ─────

def get_context_for_agent(session_id: str, llm, recent_turns: int = 6) -> str:
    """Two-tier memory. Falls back to ``summarize_messages`` if compressor fails.

    Layered fallback (most graceful first):
      1. Short history            → return verbatim, no LLM call
      2. Long history + LLM ok    → summary + recent verbatim
      3. Long history + LLM fail  → legacy regex summary + recent verbatim
      4. Total failure            → empty string

    The ``session_id`` argument is reserved for future per-session
    history (currently we read the single ``chat_history.json`` file).
    """
    # Local imports keep this module importable in test environments
    # where langchain_core isn't on the path.
    from pathlib import Path
    import json as _json
    from langchain_core.messages import AIMessage, HumanMessage

    from memory_compressor import MemoryCompressor

    _ = session_id  # currently unused; see docstring
    path = Path("agent/chat_history.json")
    if not path.exists():
        return ""
    try:
        raw = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""

    history = []
    for msg in raw:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            history.append(HumanMessage(content=content))
        elif role == "assistant":
            history.append(AIMessage(content=content))

    if not history:
        return ""

    compressor = MemoryCompressor(llm, recent_turns=recent_turns)

    # Short history: just return it
    if len(history) <= recent_turns:
        return compressor.reconstruct_context({"recent": history, "summary": ""})

    # Long history: compress
    try:
        return compressor.reconstruct_context(compressor.compress(history))
    except Exception:
        # Worst-case fallback: legacy regex summary + recent verbatim
        legacy = summarize_messages(raw)
        recent_text = "\n".join(
            f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
            for m in history[-recent_turns:]
        )
        if legacy:
            return f"[CONVERSATION MEMORY]\n{legacy}\n\n[Recent conversation]\n{recent_text}"
        return recent_text
