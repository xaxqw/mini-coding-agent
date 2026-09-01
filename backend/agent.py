"""Agent 核心：LLM 驱动的工具调用循环。

流程：
    user 消息 → LLM → 有 tool_calls?
        ├─ 否 → 生成最终回复，结束
        └─ 是 → 并行执行工具（asyncio.gather）
                ├─ run_command 命中危险黑名单 → 审批 pending，挂起等用户
                ├─ ask_user → 提问 pending，挂起等用户回答
                └─ 其它 → 直接执行
             结果回填 → 再次调用 LLM → 循环

并发设计（对应题目"工具并行调用/并发冲突"）：
- 只读工具（list_dir/read_file）真正并行；
- 写工具（write_file）持全局写锁，串行化，杜绝同文件互相覆盖；
- 命令执行互斥（EXEC_LOCK），同一时刻只跑一条 shell 命令。
"""
from __future__ import annotations

import asyncio
import json

from openai import AsyncOpenAI

from .config import Config
from .session import Session
from .tools import TOOLS, TOOL_IMPL, _ApprovalRequired, is_dangerous

SYSTEM_PROMPT = """你是一个极简 Coding Agent，运行在受控沙箱工作区里，负责帮用户完成编码与文件任务。
你可以使用以下工具：
- list_dir / read_file / write_file：管理工作区内的文件（仅限工作区）
- run_command：执行 shell 命令（危险命令会被安全机制拦截，需要用户批准后才能执行）
- ask_user：需要澄清需求、确认决策、或信息不足无法继续时，向用户提问

行为准则：
1. 先看清任务需求，必要时用 list_dir 摸清工作区现状，再动手。
2. 写代码任务：先写完整可运行的文件，再用 run_command 做基本验证。
3. 需要用户决策时（如删除文件、选择方案）用 ask_user，不要擅自猜测。
4. 回复简洁、直接，说明你做了什么、结果如何。
5. 一次可以并行调用多个互不依赖的工具（例如同时读多个文件）。
"""


class Agent:
    def __init__(self, session: Session):
        self.session = session
        self.client = None if Config.is_mock() else AsyncOpenAI(
            api_key=Config.API_KEY,
            base_url=Config.BASE_URL,
        )

    # ---------- LLM 调用 ----------
    async def _llm(self) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + self.session.history
        if Config.is_mock():
            return await self._mock_llm(msgs)
        resp = await self.client.chat.completions.create(
            model=Config.MODEL,
            messages=msgs,
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=True,
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

    # ---------- 工具执行 ----------
    async def _exec_tool(self, tc: dict) -> dict:
        """执行单个工具调用；返回 OpenAI tool 消息体。"""
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}

        if name == "ask_user":
            question = str(args.get("question", "（未提供问题）"))
            return await self._ask_user(tc["id"], question)

        if name == "run_command":
            cmd = str(args.get("command", ""))
            if is_dangerous(cmd):
                return await self._approve_command(tc["id"], cmd)

        fn = TOOL_IMPL.get(name)
        if fn is None:
            out = f"[错误] 未知工具: {name}"
        else:
            try:
                out = await fn(**args)
            except _ApprovalRequired as e:
                # 直接调用层（mock 路径）也会走到这里
                return await self._approve_command(tc["id"], e.command)
            except TypeError as e:
                out = f"[错误] 工具参数不合法: {e}"
            except Exception as e:  # noqa: BLE001
                out = f"[错误] {e}"

        self.session.push("tool_result", {
            "tool_call_id": tc["id"], "name": name, "status": "ok", "output": out,
        })
        return {"role": "tool", "tool_call_id": tc["id"], "content": out}

    async def _approve_command(self, tool_call_id: str, command: str) -> dict:
        """危险命令 → 创建审批 pending → 挂起等用户 → 恢复执行。"""
        pending = self.session.create_pending("approval", {"command": command, "tool_call_id": tool_call_id})
        self.session.push("approval_request", {"pid": pending.pid, "command": command})
        self.session.push("status", {"state": "waiting_approval"})
        r = await self.session.wait_for(pending)
        self.session.push("status", {"state": "running"})
        if r.get("approved"):
            # 用户已批准：绕过黑名单执行（临时豁免）
            from .tools import EXEC_LOCK, WORKSPACE, Config as _C
            import subprocess
            async with EXEC_LOCK:
                try:
                    proc = subprocess.run(
                        command, shell=True, cwd=WORKSPACE,
                        capture_output=True, text=True,
                        timeout=int(_C.CMD_TIMEOUT), errors="replace",
                    )
                    out = f"$ {command}\n[退出码] {proc.returncode}\n[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr}"
                except subprocess.TimeoutExpired:
                    out = f"[超时] 命令超过 {_C.CMD_TIMEOUT} 秒，已终止"
                except Exception as e:  # noqa: BLE001
                    out = f"[错误] {e}"
            self.session.push("tool_result", {
                "tool_call_id": tool_call_id, "name": "run_command",
                "status": "approved", "output": out,
            })
            return {"role": "tool", "tool_call_id": tool_call_id, "content": out}
        denied = "用户拒绝执行危险命令，未执行。请改用安全方式完成任务。"
        self.session.push("tool_result", {
            "tool_call_id": tool_call_id, "name": "run_command",
            "status": "denied", "output": denied,
        })
        return {"role": "tool", "tool_call_id": tool_call_id, "content": denied}

    async def _ask_user(self, tool_call_id: str, question: str) -> dict:
        """ask_user → 创建提问 pending → 挂起等用户回答。"""
        pending = self.session.create_pending("ask", {"question": question})
        self.session.push("ask_request", {"pid": pending.pid, "question": question})
        self.session.push("status", {"state": "waiting_user"})
        r = await self.session.wait_for(pending)
        self.session.push("status", {"state": "running"})
        if r.get("cancelled"):
            content = "用户未在限定时间内回答，请基于现有信息继续，或再次询问。"
        else:
            content = f"用户的回答：{r.get('answer', '')}"
        self.session.push("tool_result", {
            "tool_call_id": tool_call_id, "name": "ask_user",
            "status": "ok", "output": content,
        })
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}

    # ---------- 主循环 ----------
    async def run(self, user_message: str) -> None:
        self.session.running = True
        self.session.push("status", {"state": "running"})
        self.session.history.append({"role": "user", "content": user_message})
        max_iters = 30
        try:
            for _ in range(max_iters):
                assistant = (await self._llm())[0]
                self.session.history.append(assistant)
                text = assistant.get("content") or ""
                if text:
                    self.session.push("message", {"role": "assistant", "content": text})
                tool_calls = assistant.get("tool_calls") or []
                if not tool_calls:
                    break
                # 工具并行调用：互不依赖的工具同时执行；写锁/执行锁内部保证冲突安全
                for tc in tool_calls:
                    self.session.push("tool_call", {
                        "tool_call_id": tc["id"], "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    })
                results = await asyncio.gather(*[self._exec_tool(tc) for tc in tool_calls])
                self.session.history.extend(results)
            else:
                self.session.push("message", {
                    "role": "assistant",
                    "content": "（已达到最大迭代次数，任务可能未完全完成，请继续提问）",
                })
            self.session.push("status", {"state": "done"})
        except Exception as e:  # noqa: BLE001
            self.session.push("error", {"message": str(e)})
            self.session.push("status", {"state": "error"})
        finally:
            self.session.running = False
            self.session.push("done", {})

    # ---------- Mock 模式（无 API Key 时演示全链路） ----------
    async def _mock_llm(self, msgs: list[dict]) -> list[dict]:
        """规则模拟：根据用户消息关键词触发工具调用，用于离线演示。"""
        last = msgs[-1]["content"]
        if last.startswith("USER_ANSWER:"):
            return [{"role": "assistant", "content": "好的，我按你的要求继续。任务已完成。"}]
        if last.startswith("APPROVED:") or last.startswith("DENIED:"):
            return [{"role": "assistant", "content": "已按你的决定继续。任务已完成。"}]
        if last.startswith("TOOL_OK:"):
            return [{"role": "assistant", "content": "工具执行成功，任务已完成。"}]

        content = last
        if "总结" in content or "查看" in content or "读取" in content or "分析" in content:
            return [{"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "list_dir", "arguments": json.dumps({"path": "."})}},
                {"id": "c2", "type": "function",
                 "function": {"name": "read_file", "arguments": json.dumps({"path": "hello.py"})}},
            ]}]
        if "脚本" in content or "创建" in content or "写一个" in content or "编写" in content:
            return [{"role": "assistant", "content": "好的，我来创建一个 Python 脚本。",
                     "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "write_file", "arguments": json.dumps({
                     "path": "hello.py",
                     "content": "print('Hello from mini coding agent!')\nfor i in range(1, 6):\n    print(f'line {i}')\n"})}},
            ]}]
        if "删除" in content or "清理" in content or "rm" in content or "危险" in content or "测试审批" in content:
            return [{"role": "assistant", "content": "这个操作有风险，我先征求你的批准。",
                     "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "run_command", "arguments": json.dumps(
                     {"command": "rm -rf ." if os_sep() == "/" else "del /s /q *"})}},
            ]}]
        if "运行" in content or "执行" in content or "跑" in content:
            return [{"role": "assistant", "content": "好的，我来运行它验证结果。",
                     "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "run_command", "arguments": json.dumps(
                     {"command": "python hello.py"})}},
            ]}]
        if "问" in content or "提问" in content or "ask" in content:
            return [{"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "ask_user", "arguments": json.dumps(
                     {"question": "（演示）你希望脚本输出到文件还是只打印到终端？"})}},
            ]}]
        return [{"role": "assistant", "content": "（Mock 模式）我理解你的需求了。可以试试对我说：总结工作区 / 创建一个脚本 / 运行脚本 / 测试审批 / 问我一个问题。"}]


def os_sep() -> str:
    import os
    return os.sep
