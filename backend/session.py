"""会话管理：事件队列（SSE 推送）+ pending 机制（危险命令审批 / ask_user 提问）。

Agent loop 需要用户介入时（审批危险命令、回答提问），会创建一个 pending 项，
挂起等待；前端通过 /api/resolve 解决 pending 后，loop 自动恢复继续执行。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Pending:
    pid: str                  # pending 唯一 ID
    kind: str                 # "approval" | "ask"
    payload: dict             # approval: {"command": ...} / ask: {"question": ...}
    event: asyncio.Event = field(default_factory=asyncio.Event)
    resolved: bool = False
    result: dict = field(default_factory=dict)


class Session:
    def __init__(self, sid: str | None = None):
        self.id = sid or uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.history: list[dict] = []          # OpenAI 格式 messages
        self.pending: dict[str, Pending] = {}  # pending_id -> Pending
        self.running = False

    # ---------- 事件推送 ----------
    def push(self, event: str, data: Any = None) -> None:
        self.queue.put_nowait({"event": event, "data": data})

    # ---------- pending 挂起 / 恢复 ----------
    def create_pending(self, kind: str, payload: dict) -> Pending:
        p = Pending(pid=uuid.uuid4().hex[:10], kind=kind, payload=payload)
        self.pending[p.pid] = p
        return p

    async def wait_for(self, pending: Pending, timeout: float = 1800.0) -> dict:
        """等待用户解决 pending；超时返回 {'cancelled': True}。"""
        try:
            await asyncio.wait_for(pending.event.wait(), timeout)
        except asyncio.TimeoutError:
            return {"cancelled": True, "reason": "等待用户响应超时"}
        return pending.result

    def resolve(self, pending_id: str, result: dict) -> bool:
        p = self.pending.get(pending_id)
        if not p or p.resolved:
            return False
        p.resolved = True
        p.result = result
        p.event.set()
        return True


# 全局会话表（单进程内存态，演示足够）
SESSIONS: dict[str, Session] = {}


def get_session(sid: str | None = None) -> Session:
    if sid and sid in SESSIONS:
        return SESSIONS[sid]
    s = Session(sid)
    SESSIONS[s.id] = s
    return s
