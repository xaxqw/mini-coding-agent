# Mini Coding Agent

> 笔试试题交付：一阶段「极简 Coding Agent」+ 二阶段方向一「四项增强」。

一个最简的 Coding Agent：具备**读写文件**和**运行 shell 命令**的能力，可完成"总结指定文件""按需求编写脚本"等基础任务；并实现了 **Web UI、工具并行调用、危险命令权限审批、ask_user 提问**四项增强。

## 能力总览

### 一阶段（CLI 交付）

| 工具 | 说明 |
|------|------|
| `list_dir` | 列出工作区内目录内容（含文件大小） |
| `read_file` | 读取文本文件，带行号，支持行偏移/上限 |
| `write_file` | 写入/追加文件（自动创建目录，沙箱内） |
| `run_command` | 执行 shell 命令（cmd / bash），可设超时 |

### 二阶段（方向一，全选）

1. **Web UI**：完整聊天界面，工具调用实时可视化（参数/结果卡片），输入区、状态灯、危险命令审批面板、ask_user 问答面板。
2. **工具并行调用**：互不依赖的工具用 `asyncio.gather` 并行执行；对并发冲突有专门设计——**文件写入全局写锁串行化**（杜绝同文件互相覆盖）、**命令执行互斥**（同一时刻只跑一条 shell 命令）。
3. **工具权限控制**：破坏性命令（`rm -rf` / `format` / `shutdown` / `del /s` / `git push -f` 等黑名单模式）会被拦截，必须**用户点击"允许"后才执行**，拒绝则返回安全结果。
4. **ask_user 工具**：Agent 需要澄清需求/确认决策时调用 `ask_user`，Agent loop 挂起等待，用户回答后自动恢复继续执行。

安全基线：所有文件操作被限制在沙箱目录 `workspace/` 内，越界读写会被拒绝。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置模型（可选）
cp .env.example .env
#    编辑 .env 填入公司提供的 OPENAI_API_KEY（支持任意 OpenAI 兼容 API）
#    不填 Key 自动进入 Mock 模式（规则模拟，无需 Key 即可体验全链路）

# 3. 启动 Web UI（阶段二）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
#    浏览器打开 http://127.0.0.1:8000

# 或使用 CLI（阶段一，依然可用）
python -m backend.cli "总结工作区里有什么"
```

Windows 下可双击 `start.bat` 一键启动；Linux/macOS 用 `./start.sh`。

## 测试

| 脚本 | 模式 | 说明 |
|------|------|------|
| `test_flow.py` | Mock | 无 Key 也能跑：写文件 / 危险审批 / ask_user / 并行，4 用例 |
| `test_real.py` | 真实模型 | 接入 OpenAI 兼容网关后用真实 LLM 验证同 4 个用例 |

```bash
python test_flow.py   # 需服务已启动；Mock 模式下即可全通过
python test_real.py   # 需 .env 配置真实 Key
```

## API

| 接口 | 说明 |
|------|------|
| `GET /` | Web UI |
| `POST /api/chat` | `{message, session_id?}` 启动 Agent 任务 |
| `GET /api/events?session_id=` | SSE 事件流（实时推送消息/工具/审批/提问） |
| `POST /api/resolve` | `{pid, session_id, approved?/answer?}` 解决审批/提问，恢复 Agent |
| `GET /api/info` | 模型与沙箱信息 |

## 技术栈

- Python 3.10+ / FastAPI / SSE 流式推送 / OpenAI 兼容 API
- Agent 循环：LLM 决策 → 工具调用（可并行）→ 结果回填 → 再次决策，直到任务完成
- 前端：原生 HTML/CSS/JS 单页（深色终端风格，无构建依赖）

## 目录结构

```
mini-coding-agent/
├── backend/
│   ├── config.py     # 配置（.env，无 Key 自动 Mock）
│   ├── tools.py      # 工具层（文件 + shell + 沙箱 + 危险命令黑名单 + 并发锁）
│   ├── agent.py      # Agent 循环（并行执行 / 审批 / ask_user）
│   ├── session.py    # 会话（事件队列 + pending 挂起恢复）
│   ├── main.py       # FastAPI 入口 + SSE
│   └── cli.py        # 阶段一入口（CLI）
├── frontend/index.html  # Web UI（单文件）
├── workspace/        # Agent 沙箱工作区
├── test_flow.py      # 全链路自动化测试（Mock，4 用例）
├── test_real.py      # 全链路自动化测试（真实模型，4 用例）
├── .env.example
└── requirements.txt
```

## Git 提交历史

```
feat(stage2): webui + parallel tools + permission control + ask_user   ← 二阶段
feat(stage1): minimal coding agent - file tools + shell commands       ← 一阶段
```
