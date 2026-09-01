"""会话管理：事件队列 + 对话历史（阶段一基础版）。"""
from __future__ import annotations

import asyncio
import uuid


class Session:
    def __init__(self, sid: str | None = None):
        self.id = sid or uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.history: list[dict] = []  # OpenAI 格式 messages
        self.running = False

    def push(self, event: str, data=None) -> None:
        self.queue.put_nowait({"event": event, "data": data})


# 全局会话表（单进程内存态）
SESSIONS: dict[str, Session] = {}


def get_session(sid: str | None = None) -> Session:
    if sid and sid in SESSIONS:
        return SESSIONS[sid]
    s = Session(sid)
    SESSIONS[s.id] = s
    return s
