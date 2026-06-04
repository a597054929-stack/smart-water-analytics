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
