"""阶段一交付入口：CLI 单轮/多轮交互版极简 Coding Agent。

用法：
    python -m backend.cli            # 交互式对话
    python -m backend.cli "总结工作区"  # 单轮执行

能力：list_dir / read_file / write_file / run_command（沙箱工作区 workspace/ 内）。
"""
from __future__ import annotations

import asyncio
import sys

from .agent import Agent
from .config import Config
from .session import get_session

BANNER = r"""
  __  __ _       _        ____            _
 |  \/  (_)_ __ (_) ___  / ___|___  _ __ | |_ __ _  ___
 | |\/| | | '_ \| |/ __| | |   / _ \| '_ \| __/ _` |/ __|
 | |  | | | | | | | (__  | |__| (_) | | | | || (_| | (__
 |_|  |_|_|_| |_|_|\___|  \____\___/|_| |_|\__\__,_|\___|
"""


def _print_events(session) -> None:
    """CLI 简易渲染：把队列里的事件打印出来（工具调用 + 消息 + 结果）。"""
    while not session.queue.empty():
        ev = session.queue.get_nowait()
        t, d = ev["event"], ev["data"] or {}
        if t == "message" and d.get("role") == "assistant":
            print(f"\n🤖 {d['content']}\n")
        elif t == "tool_call":
            print(f"🔧 调用工具 {d['name']}({d.get('arguments', '')})")
        elif t == "tool_result":
            out = (d.get("output") or "").splitlines()
            shown = "\n".join(out[:12]) + ("\n…" if len(out) > 12 else "")
            print(f"   └─ 结果 [{d.get('status')}]:\n{shown}\n")
        elif t == "error":
            print(f"\n❌ 出错: {d.get('message')}\n")


async def main_async(text: str | None = None) -> None:
    print(BANNER)
    mode = "Mock 模式（未配置 API Key）" if Config.is_mock() else f"模型 {Config.MODEL}"
    print(f"Mini Coding Agent · {mode} · 沙箱 {Config.WORKSPACE}\n")
    print("输入任务开始（exit 退出，Ctrl+C 中断）\n")

    session = get_session()
    while True:
        try:
            if text:
                msg = text
                text = None  # 单轮后进入交互模式
            else:
                msg = input("你 > ").strip()
            if msg.lower() in ("exit", "quit", "q"):
                break
            if not msg:
                continue
            agent = Agent(session)
            await agent.run(msg)
            _print_events(session)
        except (KeyboardInterrupt, EOFError):
            print("\n再见 👋")
            break


def main() -> None:
    asyncio.run(main_async(sys.argv[1] if len(sys.argv) > 1 else None))


if __name__ == "__main__":
    main()
