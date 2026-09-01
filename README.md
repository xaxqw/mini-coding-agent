# Mini Coding Agent

> 笔试试题：一阶段「极简 Coding Agent」交付。
> 二阶段增强见后续 commit（WebUI / 工具并行 / 权限审批 / ask_user）。

一个最简的 Coding Agent：具备**读写文件**和**运行 shell 命令**的能力，可完成"总结指定文件""按需求编写脚本"等基础任务。

## 阶段一能力

| 工具 | 说明 |
|------|------|
| `list_dir` | 列出工作区内目录内容（含文件大小） |
| `read_file` | 读取文本文件，带行号，支持行偏移/上限 |
| `write_file` | 写入/追加文件（自动创建目录，沙箱内） |
| `run_command` | 执行 shell 命令（cmd / bash），可设超时 |

安全基线：所有文件操作被限制在沙箱目录 `workspace/` 内，越界读写会被拒绝。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置模型（可选）
#    复制 .env.example 为 .env，填入公司提供的 OPENAI_API_KEY
#    不填则自动进入 Mock 模式（规则模拟，无需 Key 即可演示）

# 3. 启动 CLI
python -m backend.cli                     # 交互式对话
python -m backend.cli "总结工作区里有什么"  # 单轮执行
```

## 技术栈

- Python 3.10+ / FastAPI（阶段二） / OpenAI 兼容 API
- Agent 循环：LLM 决策 → 工具调用 → 结果回填 → 再次决策，直到任务完成
- 支持任意 OpenAI 兼容接口（Base URL + Key 可配），默认 DeepSeek

## 目录结构

```
mini-coding-agent/
├── backend/
│   ├── config.py     # 配置（.env）
│   ├── tools.py      # 工具层（文件 + shell + 沙箱）
│   ├── agent.py      # Agent 循环核心
│   ├── session.py    # 会话管理
│   └── cli.py        # 阶段一入口（CLI）
├── workspace/        # Agent 沙箱工作区
├── .env.example      # 环境配置模板
└── requirements.txt
```
