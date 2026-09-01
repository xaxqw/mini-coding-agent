"""阶段一：极简 Coding Agent 工具层。

具备四个基础能力：列出目录、读取文件、写入文件、执行 shell 命令。
安全基线：文件操作被限制在沙箱工作区（WORKSPACE）内，防止越权读写。
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .config import Config

WORKSPACE = Path(Config.WORKSPACE).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# 文件写锁：串行化写入（避免并发写同一文件）
WRITE_LOCK = asyncio.Lock()
# 命令执行锁：同一时刻只跑一条 shell 命令
EXEC_LOCK = asyncio.Lock()


def _safe_path(rel_or_abs: str) -> Path:
    """把用户给的文件路径解析为 WORKSPACE 内的绝对路径，越界则拒绝。"""
    p = Path(rel_or_abs).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise PermissionError(f"路径越界，仅允许操作 {WORKSPACE} 内的文件: {rel_or_abs}")
    return p


async def tool_list_dir(path: str = ".") -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[错误] 路径不存在: {path}"
        if p.is_file():
            return f"[提示] {path} 是文件，不是目录"
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for it in items[:200]:
            suffix = "/" if it.is_dir() else ""
            size = it.stat().st_size if it.is_file() else ""
            lines.append(f"{it.name}{suffix}\t{size}")
        return "\n".join(lines) if lines else "(空目录)"
    except Exception as e:  # noqa: BLE001
        return f"[错误] {e}"


async def tool_read_file(path: str, offset: int = 0, limit: int = 400) -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"[错误] 文件不存在: {path}"
        if p.is_dir():
            return f"[错误] {path} 是目录，请用 list_dir"
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        lines = lines[offset:offset + limit]
        head = f"# 文件 {path}（共 {total} 行，显示 {len(lines)} 行）\n"
        body = "\n".join(
            f"{i + offset + 1:>5} | {ln[:2000]}" for i, ln in enumerate(lines)
        )
        return head + body
    except Exception as e:  # noqa: BLE001
        return f"[错误] {e}"


async def tool_write_file(path: str, content: str, append: bool = False) -> str:
    async with WRITE_LOCK:
        try:
            p = _safe_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(p, mode, encoding="utf-8") as f:
                f.write(content)
            action = "追加到" if append else "写入"
            return f"[成功] 已{action} {path}（{len(content)} 字符）"
        except Exception as e:  # noqa: BLE001
            return f"[错误] {e}"


async def tool_run_command(command: str, timeout: int | None = None) -> str:
    async with EXEC_LOCK:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=WORKSPACE,
                capture_output=True,
                text=True,
                timeout=timeout or Config.CMD_TIMEOUT,
                errors="replace",
            )
            out = proc.stdout
            err = proc.stderr
            head = f"$ {command}\n[退出码] {proc.returncode}\n"
            body = ""
            if out:
                body += f"[stdout]\n{out}\n"
            if err:
                body += f"[stderr]\n{err}\n"
            if not body:
                body = "(无输出)"
            return head + body
        except subprocess.TimeoutExpired:
            return f"[超时] 命令超过 {timeout or Config.CMD_TIMEOUT} 秒未结束，已终止"
        except Exception as e:  # noqa: BLE001
            return f"[错误] {e}"


# ---------- 工具注册表（OpenAI function calling 格式） ----------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出工作区内某个目录下的文件与子目录（含文件大小）。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，默认 '.'"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取工作区内的文本文件，带行号。可指定行偏移与行数上限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径（必须在工作区内）"},
                    "offset": {"type": "integer", "description": "起始行号，默认 0"},
                    "limit": {"type": "integer", "description": "最多读取行数，默认 400"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入或追加内容到工作区内的文件（自动创建父目录）。会覆盖已有内容，除非 append=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径（必须在工作区内）"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                    "append": {"type": "boolean", "description": "true 表示追加，false 表示覆盖（默认 false）"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在工作区目录下执行 shell 命令（Windows 用 cmd，其它平台用 bash）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的完整命令"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
                },
                "required": ["command"],
            },
        },
    },
]

TOOL_IMPL = {
    "list_dir": tool_list_dir,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "run_command": tool_run_command,
}
