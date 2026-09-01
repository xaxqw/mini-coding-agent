"""工具层：Agent 可调用的基础工具（文件读写 / 目录列表 / shell 命令）。

安全设计：
1. 沙箱：文件工具路径必须解析后位于 WORKSPACE 内，防目录穿越（../）与越权读写。
2. 写冲突：write_file 全局写锁串行化，避免并行写同一文件互相覆盖。
3. 命令互斥：run_command 全局执行锁，同一时刻只允许一个命令运行。
4. 危险命令：破坏性命令（rm -rf / format / shutdown 等）命中黑名单，
   由 Agent 层转交给用户审批（approval_required），不直接执行。
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path

from .config import Config

WORKSPACE = Path(Config.WORKSPACE).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------- 并发控制 ----------
# 文件写锁：串行化所有写入，防止并行写同一文件产生冲突
WRITE_LOCK = asyncio.Lock()
# 命令执行锁：同一时刻只跑一条 shell 命令，避免输出/状态互相污染
EXEC_LOCK = asyncio.Lock()

# ---------- 危险命令黑名单（启发式，命中即需用户审批） ----------
DANGEROUS_PATTERNS = [
    # 递归删除
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|-f[a-zA-Z]*r?)\b",
    r"\brm\s+-rf\b", r"\brm\s+-fr\b",
    r"\brmdir\s+/[sSqQ]", r"\brmdir\s+.*/s",
    r"\bdel\s+/([sSqQfF])", r"\berase\s+/([sSqQfF])",
    r"\brd\s+/s\b", r"\bRemove-Item\b", r"\bdel\s+.*-recurse",
    # 磁盘 / 分区 / 格式化
    r"\bformat\s+[a-zA-Z]:", r"\bmkfs\b", r"\bfdisk\b", r"\bdiskpart\b",
    r"\bFormat-Volume\b", r"\bformat\s+/[qQfF]",
    # 系统级破坏
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\breg\s+delete\b", r"\bregedit\b", r"\bsc\s+delete\b",
    r"\bschtasks\s+/delete", r"\bwmic\s+.*delete",
    r"\btaskkill\s+/f\b", r"\bkill\s+-9\b", r"\bpkill\s+-9\b",
    # fork bomb / 自毁
    r":\(\)\s*\{", r"\bfork\s+bomb",
    # 直接覆盖系统关键文件 / 整盘
    r">\s*/etc/(passwd|shadow|fstab|hosts)",
    r">\s*C:\\Windows", r">\s*/dev/(sda|hda)",
    r"\bdd\s+if=.*of=/dev/",
    # 危险管道执行
    r"\bcurl\b.*\|\s*(ba)?sh", r"\bwget\b.*\|\s*(ba)?sh",
    r"iwr\b.*\|\s*iex", r"\bIEX\b",
    # chmod/chown 全盘
    r"\bchmod\s+-R\s+777\s*/", r"\bchown\s+-R\b.*/\s*$",
    # git 破坏
    r"\bgit\s+push\s+(-f|--force)",
    r"\bgit\s+reset\s+--hard\s+HEAD~",
]

_DANGEROUS_RE = re.compile("|".join(DANGEROUS_PATTERNS), re.IGNORECASE)


def is_dangerous(command: str) -> bool:
    """启发式判断命令是否危险（命中黑名单返回 True）。"""
    return bool(_DANGEROUS_RE.search(command))


def _safe_path(rel_or_abs: str) -> Path:
    """把用户给的文件路径解析为 WORKSPACE 内的绝对路径，越界则拒绝。"""
    p = Path(rel_or_abs).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise PermissionError(f"路径越界，仅允许操作 {WORKSPACE} 内的文件: {rel_or_abs}")
    return p


# ---------- 工具实现 ----------
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
    """写文件（写锁串行化）。append=True 表示追加。"""
    async with WRITE_LOCK:  # 写冲突设计：串行化写入
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
    """执行 shell 命令（执行锁互斥）。危险命令由 Agent 层拦截审批。"""
    if is_dangerous(command):
        # 抛特殊标记，Agent 层会把它转成审批流程
        raise _ApprovalRequired(command)
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


class _ApprovalRequired(Exception):
    """内部异常：标记危险命令，需要用户审批。"""

    def __init__(self, command: str):
        super().__init__(f"危险命令需要审批: {command}")
        self.command = command


# ---------- 工具注册表（OpenAI function calling 格式） ----------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出工作区内某个目录下的文件与子目录（含文件大小）。目录不存在时返回错误。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，相对或绝对，默认 '.'"}},
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
            "description": "在工作区目录下执行 shell 命令（Windows 用 cmd，其它平台用 bash）。危险命令会被拦截并要求用户批准。",
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
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户提问。当你需要澄清需求、确认关键决策、或缺少必要信息无法继续时使用。调用后 Agent 会暂停，等待用户回答。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "向用户提出的问题"},
                },
                "required": ["question"],
            },
        },
    },
]

TOOL_IMPL = {
    "list_dir": tool_list_dir,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "run_command": tool_run_command,
    "ask_user": None,  # 由 Agent 层特殊处理
}
