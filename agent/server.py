"""
FastAPI Server — AI Agent Backend

Features:
- Streaming SSE output (real-time token delivery)
- Tool call visualization (shows which tools are being used)
- Conversation persistence (saves to JSON file)
"""

import sys, json, os, asyncio
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

app = FastAPI(title="Smart Water AI Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    mode: str = "agent"  # "agent" (single) or "multi" (planner+executor+synthesizer)
    context: Optional[dict] = None  # page state from the frontend
    #   { active_tab, selected_date, selected_dma, sensitive_unlocked, likely_intent }

class ChatResponse(BaseModel):
    answer: str
    chart: Optional[dict] = None
    plan: Optional[list] = None
    tools_called: Optional[list] = None
    context_used: Optional[dict] = None  # echoes back what the agent saw


# ── Agent ─────────────────────────────────────────────────────

_agent = None

def get_agent():
    global _agent
    if _agent is None:
        from agent_executor import create_water_agent
        _agent = create_water_agent()
    return _agent


# ── Conversation Persistence ──────────────────────────────────

CHAT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.json")

def load_history():
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

chat_history = load_history()


# ── Streaming Chat ────────────────────────────────────────────

def _format_context_message(ctx: dict) -> str:
    """Render the frontend page state as a short system message for the agent."""
    if not ctx:
        return ""
    parts = ["[PAGE CONTEXT] The user is currently viewing:"]
    for k, v in ctx.items():
        if v is None or v == "":
            continue
        parts.append(f"  - {k}: {v}")
    parts.append(
        "Use this to resolve references like 'this week', 'current zone', "
        "or 'what I'm looking at'. If the question seems to ask about the "
        "current page, prefer these values over guessing."
    )
    return "\n".join(parts)


def _extract_text(content):
    """Extract text from content (handles list-type content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return " ".join(texts) if texts else str(content)
    return str(content)


def _extract_chart(messages):
    """Extract ECharts config from tool outputs."""
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            try:
                data = json.loads(_extract_text(msg.content))
                if isinstance(data, dict) and "echarts_option" in data:
                    return data["echarts_option"]
            except (json.JSONDecodeError, TypeError):
                pass
    return None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Streaming chat — SSE events for tool calls and final answer."""
    question = req.question.strip()
    if not question:
        async def empty():
            yield f"data: {json.dumps({'type': 'answer', 'content': 'Please enter a question.'})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def stream():
        try:
            # Diagnostic: log what context the server actually received from
            # the frontend. Crucial for debugging "no page context" reports.
            # One line per request — easy to grep in the server console.
            import sys
            print(
                f"[chat] mode={req.mode} context={req.context}",
                file=sys.stderr,
                flush=True,
            )

            # Multi-agent mode
            if req.mode == "multi":
                from multi_agent import run_multi_agent
                yield f"data: {json.dumps({'type': 'tool', 'name': 'planner'})}\n\n"

                result = run_multi_agent(question, context=req.context)

                for tool_name in result.get("tools_called", []):
                    yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"

                payload = {"type": "answer", "content": result["answer"]}
                if result.get("chart"):
                    payload["chart"] = result["chart"]
                if result.get("plan"):
                    payload["plan"] = result["plan"]
                if req.context:
                    payload["context_used"] = req.context
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # Single-agent mode (default)
            else:
                # Update the page-context store so the get_current_page_context
                # tool sees the latest frontend state.
                #
                # `agent/` is not a real package (no __init__.py), so a bare
                # `import agent_tools` only works when cwd is agent/. The bat
                # files `cd agent` before starting, so this usually works, but
                # we also need to handle the case where the import fails (e.g.
                # when server.py is launched from elsewhere). If we can't
                # import set_page_context, the get_current_page_context tool
                # will return "no page context available" — visible to the
                # user as a confusing error. Surface the failure to stderr.
                try:
                    from agent_tools import set_page_context
                    set_page_context(req.context)
                except Exception as _ctx_err:
                    import sys
                    print(
                        f"[chat] set_page_context failed: {_ctx_err!r}",
                        file=sys.stderr,
                        flush=True,
                    )

                agent = get_agent()
                # LangChain requires all system messages to be a contiguous
                # block at the very start of the list. Strip any stale system
                # entries persisted from prior turns, then build a fresh
                # sequence: [context_system?, memory_system?, ...history, user].
                system_msgs = []
                if req.context:
                    system_msgs.append({
                        "role": "system",
                        "content": _format_context_message(req.context),
                    })

                history_no_system = [m for m in chat_history if m.get("role") != "system"]

                # Inject conversation memory from older messages that were trimmed
                from memory import build_memory_message
                if len(chat_history) > 6:
                    old_messages = chat_history[:-6]
                    memory_msg = build_memory_message(old_messages)
                    if memory_msg:
                        system_msgs.append(memory_msg)

                # Tool pre-selection: inject hint for likely tools
                from tool_router import route_question, format_tool_hint
                tool_recs = route_question(question)
                if tool_recs:
                    hint = format_tool_hint(tool_recs)
                    system_msgs.append({"role": "system", "content": hint})

                messages = system_msgs + history_no_system + [
                    {"role": "user", "content": question}
                ]

                # Diagnostic: log message count and tool calls
                sys_msg_count = sum(1 for m in messages if m.get("role") == "system")
                print(
                    f"[chat] msgs={len(messages)} "
                    f"(sys={sys_msg_count} hist={len(history_no_system)} user=1)",
                    file=sys.stderr, flush=True,
                )

                final_answer = ""
                chart = None

                for event in agent.stream({"messages": messages}, stream_mode="updates"):
                    for node_name, node_output in event.items():
                        if node_name == "tools" and "messages" in node_output:
                            for msg in node_output["messages"]:
                                if hasattr(msg, "name") and msg.name:
                                    print(
                                        f"[chat] tool={msg.name}",
                                        file=sys.stderr, flush=True,
                                    )
                                    yield f"data: {json.dumps({'type': 'tool', 'name': msg.name})}\n\n"

                        if node_name == "agent" and "messages" in node_output:
                            for msg in node_output["messages"]:
                                if hasattr(msg, "content") and msg.content:
                                    text = _extract_text(msg.content)
                                    if text and not text.startswith("{"):
                                        final_answer = text
                                if hasattr(msg, "content") and msg.content:
                                    try:
                                        data = json.loads(_extract_text(msg.content))
                                        if isinstance(data, dict) and "echarts_option" in data:
                                            chart = data["echarts_option"]
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                print(
                    f"[chat] final_answer_preview={final_answer[:300]}",
                    file=sys.stderr, flush=True,
                )

                if not final_answer:
                    result = agent.invoke({"messages": messages})
                    for msg in reversed(result["messages"]):
                        if hasattr(msg, "content") and msg.content:
                            final_answer = _extract_text(msg.content)
                            break
                    chart = _extract_chart(result["messages"])

                payload = {"type": "answer", "content": final_answer}
                if chart:
                    payload["chart"] = chart
                if req.context:
                    payload["context_used"] = req.context
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # Save to history
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": final_answer})
            if len(chat_history) > 6:
                chat_history[:] = chat_history[-6:]
            save_history(chat_history)

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Non-streaming fallback ────────────────────────────────────

@app.post("/api/chat/sync", response_model=ChatResponse)
async def chat_sync(req: ChatRequest):
    """Non-streaming chat (for compatibility)."""
    question = req.question.strip()
    if not question:
        return ChatResponse(answer="Please enter a question.")

    try:
        import sys
        print(f"[chat-sync] context={req.context}", file=sys.stderr, flush=True)
        try:
            from agent_tools import set_page_context
            set_page_context(req.context)
        except Exception:
            pass

        agent = get_agent()
        system_msgs = []
        if req.context:
            system_msgs.append({"role": "system", "content": _format_context_message(req.context)})
        history_no_system = [m for m in chat_history if m.get("role") != "system"]
        from memory import build_memory_message
        if len(chat_history) > 6:
            old_messages = chat_history[:-6]
            memory_msg = build_memory_message(old_messages)
            if memory_msg:
                system_msgs.append(memory_msg)
        from tool_router import route_question, format_tool_hint
        tool_recs = route_question(question)
        if tool_recs:
            system_msgs.append({"role": "system", "content": format_tool_hint(tool_recs)})
        messages = system_msgs + history_no_system + [
            {"role": "user", "content": question}
        ]
        result = agent.invoke({"messages": messages})

        answer = ""
        chart = None
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content:
                answer = _extract_text(msg.content)
                break

        chart = _extract_chart(result["messages"])

        chat_history.append({"role": "user", "content": question})
        chat_history.append({"role": "assistant", "content": answer})
        if len(chat_history) > 6:
            chat_history[:] = chat_history[-6:]
        save_history(chat_history)

        return ChatResponse(answer=answer, chart=chart, context_used=req.context)
    except Exception as e:
        return ChatResponse(answer=f"Error: {str(e)}")


# ── API Endpoints ─────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "history_turns": len(chat_history) // 2}


@app.post("/api/reset")
async def reset():
    chat_history.clear()
    save_history(chat_history)
    return {"status": "ok", "message": "Conversation reset"}


@app.get("/api/history")
async def get_history():
    return {"history": chat_history}


if __name__ == "__main__":
    print("Starting Smart Water AI Assistant...")
    print("  API: http://localhost:8000/api/chat (streaming)")
    print("  Sync: http://localhost:8000/api/chat/sync")
    print("  Health: http://localhost:8000/api/health")
    uvicorn.run(app, host="0.0.0.0", port=8000)
