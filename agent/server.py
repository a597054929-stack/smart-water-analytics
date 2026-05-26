"""
FastAPI Server — AI Agent Backend

Serves the LangChain agent as a REST API.
The dashboard's chat widget connects to this server.
"""

import sys, json
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os

app = FastAPI(title="Smart Water AI Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    chart: Optional[dict] = None


# Lazy-load agent
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        from agent_executor import create_water_agent
        _agent = create_water_agent()
    return _agent


# Conversation memory (last 10 turns)
chat_history: list[dict] = []


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Process a chat message through the agent."""
    question = req.question.strip()
    if not question:
        return ChatResponse(answer="Please enter a question.")

    try:
        agent = get_agent()

        messages = chat_history + [{"role": "user", "content": question}]
        result = agent.invoke({"messages": messages})

        # Extract the last AI response
        answer = ""
        chart = None
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content:
                content = msg.content
                # Handle list-type content (some providers return content blocks)
                if isinstance(content, list):
                    texts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
                    content = " ".join(texts) if texts else str(content)
                answer = content
                break

        # Check for chart data in tool outputs
        for msg in result["messages"]:
            if hasattr(msg, "content") and msg.content:
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and "echarts_option" in data:
                        chart = data["echarts_option"]
                except (json.JSONDecodeError, TypeError):
                    pass

        # Store conversation history (keep last 10 turns)
        chat_history.append({"role": "user", "content": question})
        chat_history.append({"role": "assistant", "content": answer})
        if len(chat_history) > 20:
            chat_history[:] = chat_history[-20:]

        return ChatResponse(answer=answer, chart=chart)
    except Exception as e:
        return ChatResponse(answer=f"Error: {str(e)}")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/reset")
async def reset():
    """Clear conversation history."""
    chat_history.clear()
    return {"status": "ok", "message": "Conversation reset"}


if __name__ == "__main__":
    print("Starting Smart Water AI Assistant...")
    print("  API: http://localhost:8000/api/chat")
    print("  Health: http://localhost:8000/api/health")
    uvicorn.run(app, host="0.0.0.0", port=8000)
