"""FastAPI 入口：静态前端 + Agent API（SSE 事件流 / 审批 / 提问回答）。

接口：
    GET  /                    Web UI
    POST /api/chat            {message} → 启动 Agent loop（后台运行，事件走 SSE）
    GET  /api/events          SSE 事件流（status/message/tool_call/tool_result/approval_request/ask_request/done/error）
    POST /api/resolve         {pid, approved? | answer?} → 解决审批/提问 pending，恢复 Agent loop
    GET  /api/info            模型配置信息（前端展示，不含 Key）
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import Agent
from .config import BASE_DIR, Config
from .session import get_session

app = FastAPI(title="Mini Coding Agent", version="1.0.0")

FRONTEND_DIR = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


class ChatBody(BaseModel):
    message: str
    session_id: str | None = None


class ResolveBody(BaseModel):
    pid: str
    session_id: str | None = None
    approved: bool | None = None
    answer: str | None = None


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/info")
async def info():
    return {
        "model": Config.MODEL if not Config.is_mock() else "mock（未配置 API Key）",
        "base_url": Config.BASE_URL if not Config.is_mock() else "-",
        "mock": Config.is_mock(),
        "workspace": str(Config.WORKSPACE),
    }


@app.post("/api/chat")
async def chat(body: ChatBody):
    if not body.message.strip():
        return JSONResponse({"error": "消息不能为空"}, status_code=400)
    session = get_session(body.session_id)
    if session.running:
        return JSONResponse({"error": "Agent 正在运行中，请稍后再试"}, status_code=409)
    agent = Agent(session)
    asyncio.create_task(agent.run(body.message.strip()))
    return {"session_id": session.id}


@app.post("/api/resolve")
async def resolve(body: ResolveBody):
    session = get_session(body.session_id)
    result = {}
    if body.approved is not None:
        result = {"approved": body.approved}
    elif body.answer is not None:
        result = {"answer": body.answer}
    if not session.resolve(body.pid, result):
        return JSONResponse({"error": "pending 不存在或已处理"}, status_code=404)
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request, session_id: str | None = None):
    """SSE：把会话队列里的事件实时推给前端；客户端断开即停止消费队列。"""

    async def gen():
        session = get_session(session_id)
        while True:
            try:
                ev = await asyncio.wait_for(session.queue.get(), timeout=15)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    return
                continue
            if await request.is_disconnected():
                return
            data = json.dumps(ev, ensure_ascii=False)
            yield f"data: {data}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def main():
    import uvicorn
    uvicorn.run(app, host=Config.HOST, port=Config.PORT, log_level="info")


if __name__ == "__main__":
    main()
