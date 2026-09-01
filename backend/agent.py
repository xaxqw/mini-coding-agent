"""阶段一：极简 Coding Agent 核心循环。

流程：用户消息 → LLM 决策 → 顺序执行工具调用 → 结果回填 → 再次调用 LLM，直到无工具调用。
支持 OpenAI 兼容 API（填 .env）与 Mock 模式（无 Key 时规则模拟）。
"""
from __future__ import annotations

import asyncio
import json

from openai import AsyncOpenAI

from .config import Config
from .session import Session
from .tools import TOOLS, TOOL_IMPL

SYSTEM_PROMPT = """你是一个极简 Coding Agent，运行在受控沙箱工作区里，负责帮用户完成编码与文件任务。
你可以使用以下工具：
- list_dir / read_file / write_file：管理工作区内的文件（仅限工作区）
- run_command：在工作区目录下执行 shell 命令

行为准则：
1. 先看清任务需求，必要时用 list_dir 摸清工作区现状，再动手。
2. 写代码任务：先写完整可运行的文件，再用 run_command 做基本验证。
3. 回复简洁、直接，说明你做了什么、结果如何。
"""


class Agent:
    def __init__(self, session: Session):
        self.session = session
        self.client = None if Config.is_mock() else AsyncOpenAI(
            api_key=Config.API_KEY,
            base_url=Config.BASE_URL,
        )

    async def _llm(self) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + self.session.history
        if Config.is_mock():
            return await self._mock_llm(msgs)
        resp = await self.client.chat.completions.create(
            model=Config.MODEL,
            messages=msgs,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        d = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        return [d]

    async def _exec_tool(self, tc: dict) -> dict:
        """顺序执行单个工具调用，返回 OpenAI tool 消息体。"""
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        fn = TOOL_IMPL.get(name)
        if fn is None:
            out = f"[错误] 未知工具: {name}"
        else:
            try:
                out = await fn(**args)
            except TypeError as e:
                out = f"[错误] 工具参数不合法: {e}"
            except Exception as e:  # noqa: BLE001
                out = f"[错误] {e}"
        self.session.push("tool_result", {
            "tool_call_id": tc["id"], "name": name, "status": "ok", "output": out,
        })
        return {"role": "tool", "tool_call_id": tc["id"], "content": out}

    async def run(self, user_message: str) -> None:
        self.session.running = True
        self.session.history.append({"role": "user", "content": user_message})
        try:
            for _ in range(30):
                assistant = (await self._llm())[0]
                self.session.history.append(assistant)
                text = assistant.get("content") or ""
                if text:
                    self.session.push("message", {"role": "assistant", "content": text})
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    break
                for tc in tool_calls:
                    self.session.push("tool_call", {
                        "tool_call_id": tc["id"], "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    })
                    result = await self._exec_tool(tc)
                    self.session.history.append(result)
            self.session.push("status", {"state": "done"})
        except Exception as e:  # noqa: BLE001
            self.session.push("error", {"message": str(e)})
            self.session.push("status", {"state": "error"})
        finally:
            self.session.running = False
            self.session.push("done", {})

    # ---------- Mock 模式（无 API Key 时演示） ----------
    async def _mock_llm(self, msgs: list[dict]) -> list[dict]:
        last = msgs[-1]["content"]
        if last.startswith("TOOL_OK:"):
            return [{"role": "assistant", "content": "工具执行成功，任务已完成。"}]
        content = last
        if "总结" in content or "查看" in content or "读取" in content or "分析" in content:
            return [{"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "list_dir", "arguments": json.dumps({"path": "."})}},
            ]}]
        if "脚本" in content or "创建" in content or "写一个" in content or "编写" in content:
            return [{"role": "assistant", "content": "好的，我来创建一个 Python 脚本。",
                     "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "write_file", "arguments": json.dumps({
                     "path": "hello.py",
                     "content": "print('Hello from mini coding agent!')\nfor i in range(1, 6):\n    print(f'line {i}')\n"})}},
            ]}]
        if "运行" in content or "执行" in content or "跑" in content:
            return [{"role": "assistant", "content": "好的，我来运行它验证结果。",
                     "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "run_command", "arguments": json.dumps(
                     {"command": "python hello.py"})}},
            ]}]
        return [{"role": "assistant", "content": "（Mock 模式）我理解你的需求了。可以试试对我说：总结工作区 / 创建一个脚本 / 运行脚本。"}]
