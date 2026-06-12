"""
FastAPI Server — AI Agent Backend

Features:
- Streaming SSE output (real-time token delivery)
- Tool call visualization (shows which tools are being used)
- Conversation persistence (saves to JSON file)
- In-memory metrics counters (chat requests, tool calls, failures)
"""

import json
import os
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")


from datetime import UTC

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Smart Water AI Assistant")

# Phase 6 vuln 1: CORS whitelist from env. Default = dev-friendly
# (vite dev server at :5173 + same-origin dashboard at :8000). Set
# CORS_ALLOWED_ORIGINS to a comma-separated list in production.
_CORS_DEFAULT = "http://localhost:5173,http://localhost:8000"
_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", _CORS_DEFAULT)
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the dashboard's data files (frontend/dist/data/*) at /data/*.
# The dashboard's inlined JS fetches meter_info.json, anomalies.json, etc.
# from /data/. Without this mount, every data file 404s.
_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist", "data")
)
if os.path.isdir(_DATA_DIR):
    app.mount("/data", StaticFiles(directory=_DATA_DIR), name="data")
else:
    # Phase 6 vuln 6: warn loudly instead of silently skipping the
    # mount. Operators need to know the dashboard bundle isn't being
    # served (otherwise they'll spend an hour debugging 404s on
    # /data/meter_info.json).
    import logging
    logging.warning(
        "CORS_ALLOWED_ORIGINS-style: _DATA_DIR %s does not exist; "
        "/data/* routes will 404. Build the dashboard first: "
        "`cd frontend && node build.cjs`",
        _DATA_DIR,
    )


# ── Phase 6 vuln 2: API key auth + per-IP rate limit ───────────
# Set AGENT_API_KEY in production to require a Bearer token on
# /api/chat, /api/chat/sync, /api/metrics, and /api/history. When
# the env var is unset, auth is disabled (dev mode) but rate
# limiting still applies.
_AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
_RPM_LIMIT = int(os.environ.get("AGENT_API_KEY_RPM", "30"))   # per IP per minute
_bearer = HTTPBearer(auto_error=False)


def _verify_api_key(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """HTTPBearer dep. If AGENT_API_KEY is set, require a matching
    Authorization: Bearer <key> header. If unset, allow anyone (dev).
    """
    if not _AGENT_API_KEY:
        return "dev-no-auth"
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization: Bearer header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if creds.credentials != _AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "ok"


# Per-IP in-memory rate limiter. Sliding 60s window.
# For multi-worker / multi-process this is per-worker only — fine for
# small ops. A production deployment with N workers should use Redis
# or similar. Phase 6 plan notes this as out of scope.
class _RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.rpm = rpm
        self.hits: dict[str, list[float]] = {}

    def check(self, ip: str) -> bool:
        now = time.time()
        window = [t for t in self.hits.get(ip, []) if t > now - 60]
        if len(window) >= self.rpm:
            self.hits[ip] = window
            return False
        window.append(now)
        self.hits[ip] = window
        return True


_rate_limiter = _RateLimiter(_RPM_LIMIT)


def _enforce_rate_limit(request: Request) -> None:
    """FastAPI dep. Reject if IP exceeds the per-minute quota."""
    ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.check(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: max {_RPM_LIMIT} req/min per IP",
        )


class ChatRequest(BaseModel):
    question: str
    mode: str = "agent"  # "agent" (single) or "multi" (planner+executor+synthesizer)
    context: dict | None = None  # page state from the frontend
    #   { active_tab, selected_date, selected_dma, sensitive_unlocked, likely_intent }

class ChatResponse(BaseModel):
    answer: str
    chart: dict | None = None
    plan: list | None = None
    tools_called: list | None = None
    clarify: dict | None = None  # ask-back options for ambiguous queries
    context_used: dict | None = None  # echoes back what the agent saw


# ── Utility Endpoints (typed for Swagger UI) ────────────────

class HealthResponse(BaseModel):
    status: str
    history_turns: int


class ResetResponse(BaseModel):
    status: str
    message: str


class HistoryResponse(BaseModel):
    history: list


class QuestionsResponse(BaseModel):
    questions: list


class QuestionEntry(BaseModel):
    ts: str
    question: str
    mode: str
    tab: str | None = None
    intent: str | None = None


class MetricsResponse(BaseModel):
    chat_requests_total: dict[str, int]   # {"agent": 12, "multi": 3}
    tool_calls_total: dict[str, int]      # {"query_anomalies": 7, "sql_db_query": 5}
    chat_failures_total: int
    questions_logged_total: int


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
QUESTION_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question_log.json")

def load_history():
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

chat_history = load_history()


# ── Question Log (累積所有使用者問題，供分析) ────────────────

def log_question(question: str, mode: str, context: dict | None = None):
    """Append a user question to the persistent log."""
    from datetime import datetime
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "question": question,
        "mode": mode,
        "tab": (context or {}).get("active_tab"),
        "intent": (context or {}).get("likely_intent"),
    }
    log = []
    if os.path.exists(QUESTION_LOG_FILE):
        try:
            with open(QUESTION_LOG_FILE, encoding="utf-8") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    with open(QUESTION_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    _METRICS["questions_logged_total"] += 1


# ── Metrics (in-memory counters; reset on process restart) ─────

_METRICS: dict[str, object] = {
    "chat_requests_total": Counter(),   # mode -> count
    "tool_calls_total": Counter(),      # tool name -> count
    "chat_failures_total": 0,
    "questions_logged_total": 0,
}


def record_chat_request(mode: str) -> None:
    """Bump the chat request counter for the given mode."""
    _METRICS["chat_requests_total"][mode] += 1  # type: ignore[index]


def record_tool_call(name: str) -> None:
    """Bump the per-tool counter."""
    _METRICS["tool_calls_total"][name] += 1  # type: ignore[index]


def record_chat_failure() -> None:
    """Bump the failure counter (any unhandled exception in /api/chat)."""
    _METRICS["chat_failures_total"] += 1  # type: ignore[operator]


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


def _detect_clarify(text: str) -> dict | None:
    """Detect if the single-agent answer is a clarify response.

    The ReAct agent's CLARIFICATION rule instructs it to return numbered
    options with '请选择' or '请回'. This function parses that pattern
    into a structured clarify dict that the frontend can render as buttons.

    Returns:
      {"question": "...", "options": ["opt1", ...], "default": "opt1"}
      or None if no clarify pattern found.
    """
    import re as _re
    # Match patterns like:
    #   "1) xxx  2) yyy  3) zzz. 请选择"
    #   "1) xxx  2) yyy 请选择(回数字即可)"
    # Also handle Chinese parens: "1）xxx 2）yyy"
    has_clarify_signal = any(kw in text for kw in ["请选择", "请回", "回数字", "请选择("])
    if not has_clarify_signal:
        return None
    # Extract numbered options: "1) xxx" or "1）xxx" or "1. xxx"
    # Stop at the next numbered option or at 请选择/请回 signals
    option_matches = _re.findall(
        r'[1-4][)）.]\s*(.+?)(?=[1-4][)）.]|请选择|请回|\Z)',
        text,
    )
    if not option_matches:
        return None
    options = [opt.strip().rstrip("，。、. \t") for opt in option_matches if opt.strip()]
    if len(options) < 2:
        return None
    default_opt = None
    for i, opt in enumerate(options):
        if "[默认]" in opt or "[default]" in opt.lower():
            default_opt = opt.replace("[默认]", "").replace("[default]", "").strip()
            options[i] = default_opt
    if not default_opt:
        default_opt = options[0]
    # The question is the text before the first numbered option
    first_option_pos = text.find("1)")
    if first_option_pos < 0:
        first_option_pos = text.find("1）")
    if first_option_pos < 0:
        first_option_pos = text.find("1.")
    question = text[:first_option_pos].strip() if first_option_pos > 0 else text
    return {
        "question": question,
        "options": options,
        "default": default_opt,
    }


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


@app.post("/api/chat", tags=["chat"], summary="Streaming chat with SSE (tool events + final answer)",
          dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def chat(req: ChatRequest):
    """Streaming chat — SSE events for tool calls and final answer."""
    question = req.question.strip()
    if not question:
        async def empty():
            yield f"data: {json.dumps({'type': 'answer', 'content': 'Please enter a question.'})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    log_question(question, req.mode, req.context)
    record_chat_request(req.mode)

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
                # Flush so the frontend sees the planner start immediately
                # instead of staring at "Thinking..." for 10-30 seconds.
                # SSE comments (lines starting with ":") are valid keepalives.
                yield ": ping\n\n"

                # Run the blocking LLM call in a worker thread so the
                # event loop stays free to flush SSE events.
                import asyncio
                result = await asyncio.to_thread(run_multi_agent, question, req.context)

                for tool_name in result.get("tools_called", []):
                    yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"

                payload = {"type": "answer", "content": result["answer"]}
                if result.get("chart"):
                    payload["chart"] = result["chart"]
                if result.get("plan"):
                    payload["plan"] = result["plan"]
                if result.get("clarify"):
                    payload["clarify"] = result["clarify"]
                if req.context:
                    payload["context_used"] = req.context
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                final_answer = result["answer"]

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
                from tool_router import format_tool_hint, route_question
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
                                    record_tool_call(msg.name)

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
                # Detect if the ReAct agent returned a clarify response
                # (plain text with numbered options + "请选择").
                clarify = _detect_clarify(final_answer)
                if clarify:
                    payload["clarify"] = clarify
                if req.context:
                    payload["context_used"] = req.context
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            # Save to history
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": final_answer})
            if len(chat_history) > 6:
                chat_history[:] = chat_history[-6:]
            # Phase 6 vuln 4: offload file write to a worker thread so
            # the event loop stays free to flush SSE events to the
            # client. The chat() handler runs on the event loop and
            # sync I/O here would block SSE delivery.
            import asyncio
            await asyncio.to_thread(save_history, chat_history)

        except Exception as e:
            record_chat_failure()
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Non-streaming fallback ────────────────────────────────────

@app.post("/api/chat/sync", response_model=ChatResponse,
               dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def chat_sync(req: ChatRequest):
    """Non-streaming chat (for compatibility)."""
    question = req.question.strip()
    if not question:
        return ChatResponse(answer="Please enter a question.")

    log_question(question, req.mode, req.context)
    record_chat_request(req.mode)

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
        from tool_router import format_tool_hint, route_question
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
        # Phase 6 vuln 4: see chat() handler note above
        import asyncio
        await asyncio.to_thread(save_history, chat_history)

        clarify = _detect_clarify(answer)
        return ChatResponse(answer=answer, chart=chart, clarify=clarify, context_used=req.context)
    except Exception as e:
        return ChatResponse(answer=f"Error: {str(e)}")


# ── Frontend Dashboard ────────────────────────────────────────
# The dashboard is built by `frontend/build.cjs` into a self-contained
# single HTML file (CSS + JS + data all inlined). Serving it from
# the agent server means a single port serves both the API and the UI.
# In dev: http://localhost:8000/ opens the chat; /docs opens Swagger.

_DASHBOARD_HTML = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist", "dashboard.html")
)


@app.get("/", tags=["frontend"], summary="Serve the dashboard HTML (chat + tabs)")
async def index():
    if not os.path.exists(_DASHBOARD_HTML):
        return HTMLResponse(
            "<h1>Dashboard not built</h1>"
            "<p>Run <code>cd frontend && node build.cjs</code> to build "
            "frontend/dist/dashboard.html</p>",
            status_code=503,
        )
    # Phase 6 vuln 5: FileResponse with sendfile/streaming,
    # consistent with /data/* which uses the same pattern via
    # StaticFiles. The dashboard.html is 144 KB so the prior
    # f.read() wasn't a memory problem, but it broke the
    # "one response pattern" contract.
    return FileResponse(_DASHBOARD_HTML, media_type="text/html")


# ── API Endpoints ─────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse, tags=["utility"], summary="Liveness + conversation turn count")
async def health():
    # Phase 6 vuln 2: keep /api/health auth-free so liveness probes
    # (k8s/ALB) work without provisioning an API key. Other
    # sensitive routes (chat, chat_sync, history, metrics) are
    # gated via Depends(_verify_api_key).
    return {"status": "ok", "history_turns": len(chat_history) // 2}


@app.post("/api/reset", response_model=ResetResponse, tags=["utility"], summary="Clear in-memory conversation history",
               dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def reset():
    chat_history.clear()
    # Phase 6 vuln 4: see chat() handler note above
    import asyncio
    await asyncio.to_thread(save_history, chat_history)
    return {"status": "ok", "message": "Conversation reset"}


@app.get("/api/history", response_model=HistoryResponse, tags=["utility"], summary="Last 6 conversation turns (user + assistant pairs)",
               dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def get_history():
    return {"history": chat_history}


@app.get("/api/questions", response_model=QuestionsResponse, tags=["analytics"], summary="Full question log for usage analysis",
               dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def get_questions():
    """Return the full question log for analysis."""
    if os.path.exists(QUESTION_LOG_FILE):
        with open(QUESTION_LOG_FILE, encoding="utf-8") as f:
            return {"questions": json.load(f)}
    return {"questions": []}


@app.get("/api/metrics", response_model=MetricsResponse, tags=["analytics"], summary="In-process counters for chat/tool/failure rates",
               dependencies=[Depends(_verify_api_key), Depends(_enforce_rate_limit)])
async def get_metrics():
    """Return current process metrics counters.

    Lightweight Prometheus-style snapshot — no external dependency.
    Counters reset on process restart, so use for rate computation
    (rate over time) rather than lifetime totals.
    """
    return {
        "chat_requests_total": dict(_METRICS["chat_requests_total"]),  # type: ignore[arg-type]
        "tool_calls_total": dict(_METRICS["tool_calls_total"]),         # type: ignore[arg-type]
        "chat_failures_total": _METRICS["chat_failures_total"],         # type: ignore[arg-type]
        "questions_logged_total": _METRICS["questions_logged_total"],   # type: ignore[arg-type]
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print("Starting Smart Water AI Assistant...")
    print(f"  API: http://{args.host}:{args.port}/api/chat (streaming)")
    print(f"  Sync: http://{args.host}:{args.port}/api/chat/sync")
    print(f"  Health: http://{args.host}:{args.port}/api/health")
    uvicorn.run(app, host=args.host, port=args.port)
