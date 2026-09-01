# TEST_REPORT.md — 对照题目要求测试报告

> 测试对象：`mini-coding-agent`（commit `33e18bd` 一阶段 + `f56b78e` 二阶段）
> 测试时间：2026-09-01
> 测试环境：Windows / Python 3.13 / FastAPI 0.141 / openai 3.6 / gpt-5.2-codex @ api.apilio.ai/v1

---

## 一、一阶段「极简 Coding Agent」对照

| # | 题目要求 | 实现位置 | 测试方法 | 结果 |
|---|---------|---------|---------|------|
| 1.1 | Agent 具备**读写文件**能力 | `backend/tools.py` `tool_read_file` / `tool_write_file` | 单元测试：写 3 行文件 → 读回 → 校验行号/内容 | ✅ 通过 |
| 1.2 | Agent 具备**运行 shell 命令**能力 | `backend/tools.py` `tool_run_command` | 单元测试：`python -c "print(1+1)"` → 退出码 0 / 输出 2 | ✅ 通过 |
| 1.3 | 能完成**指定文件总结**任务 | Agent 循环 + `list_dir`/`read_file` | CLI 真实模型跑"总结工作区有哪些文件" → `list_dir` 列出 3 个文件 → 模型输出总结 | ✅ 通过 |
| 1.4 | 能完成**按需求编写脚本**任务 | Agent 循环 + `write_file`/`run_command` | CLI 真实模型跑"写斐波那契前 10 项脚本并运行" → 自动完成 list_dir → write_file(fib10.py) → run_command → 输出 `0 1 1 2 3 5 8 13 21 34` | ✅ 通过 |
| 1.5 | 交付形式不限（web/TUI/CLI 皆可） | CLI 入口 `backend/cli.py`（另有 WebUI） | `python -m backend.cli "任务"` 单轮/多轮可用 | ✅ 通过（CLI + WebUI 双形态） |
| 1.6 | 开发完成后**上传 GitHub 并提供仓库地址** | 仓库 `xaxqw/mini-coding-agent` | `git log` 3 commit 已 push；GitHub 网页确认 | ✅ 通过 |
| 1.7 | 使用的库不限制 | 仅 `openai` SDK + `fastapi`/`uvicorn` | `requirements.txt` 4 个依赖 | ✅ 通过 |

**一阶段结论：7/7 通过**

## 二、二阶段方向一「四项增强」对照

| # | 题目要求 | 实现位置 | 测试方法 | 结果 |
|---|---------|---------|---------|------|
| 2.0 | **阶段一完成后先 commit，再开始阶段二** | git 历史 `33e18bd` → `f56b78e` 父子关系 | `git log --oneline`：stage1 在底、stage2 在上 | ✅ 通过 |
| 2.1 | **Web UI（基础对话功能）** | `backend/main.py` + `frontend/index.html` | `GET /` 200；SSE 事件流连通；前端 8 项交互元素（输入框/发送/SSE/审批面板/提问面板/工具卡片/状态灯/模型信息）齐全 | ✅ 通过 |
| 2.2 | **工具并行调用（含并发冲突设计）** | `backend/agent.py` `asyncio.gather`；`backend/tools.py` `WRITE_LOCK`/`EXEC_LOCK` | ① 真实模型：`list_dir` 后同时发起 4 个 `read_file` 并行执行 ② 专项：10 并发写同一文件 → 写锁串行化、无内容交错 | ✅ 通过 |
| 2.3 | **工具权限控制（危险工具需用户同意）** | `backend/tools.py` 黑名单 + `backend/agent.py` `_approve_command` + `/api/resolve` | ① 黑名单 10 类破坏性命令全部命中、7 类安全命令放行 ② 真实模型：`rm -rf /tmp/...` 触发 `approval_request` → 批准 → 执行（退出码 0）| ✅ 通过 |
| 2.4 | **ask_user（提问后继续 Agent loop）** | `backend/agent.py` `_ask_user` + pending 挂起恢复 | 真实模型：模型调用 `ask_user` 提问 → 前端回答"我喜欢吃苹果" → loop 恢复 → **继续写入 `favorite_fruit.md`** | ✅ 通过 |
| 2.5 | 允许提出其它改进方向并实现 | 见下表 | — | ✅ 3 项 |

### 2.5 额外改进方向

| 改进 | 实现 | 验证 |
|------|------|------|
| 沙箱隔离 | 路径 `resolve()` 后校验必须在 `workspace/` 内 | `../secret.txt` / `C:\Windows\...` / `D:\x.txt` / `/etc/passwd` 全部拒绝 |
| Mock 模式 | 无 API Key 时规则模拟全链路 | 6 种关键词场景（总结/写脚本/审批/提问/运行/闲聊）全部正确 |
| SSE 断开保护 / 并发会话防护 | 客户端断开即停止消费队列；Agent 运行中重复请求返回 409 | 实测连接断开后服务不泄漏队列事件；空消息 400、运行中 409 |

**二阶段结论：方向一 6/6 通过（含 3 项额外改进）**

## 三、测试详情记录

### 3.1 工具层单元测试（不依赖 LLM）

```
危险命令黑名单：10 命中 ✓ / 7 放行 ✓
沙箱越界：5 种路径全部拒绝 ✓
write_file → read_file → list_dir 往返正常 ✓
run_command 安全命令正常 / 危险命令抛审批标记 ✓
```

### 3.2 一阶段 CLI 实测（真实模型）

```
任务1"总结工作区" → list_dir → 模型输出 3 个文件说明 ✓
任务2"写斐波那契脚本并运行" → list_dir → write_file → run_command → 输出正确 ✓
```

### 3.3 二阶段 e2e 实测（真实模型，test_real.py）

```
用例1 写文件        → [成功] 已写入 sum1to100.py ✓
用例2 危险命令审批   → approval_request → 批准 → 退出码 0 ✓
用例3 ask_user      → 提问"你最喜欢的水果" → 回答 → 继续写 favorite_fruit.md ✓
用例4 并行调用      → list_dir 后 4 个 read_file 并行 ✓
```

### 3.4 并发冲突专项

```
10 个并发 write_file 同一文件 → 最终文件归属单一写入者，无内容交错 ✓
```

## 四、交付核对

| 交付项 | 状态 |
|--------|------|
| GitHub 仓库（3 commit，顺序：stage1 → stage2 → test） | ✅ `https://github.com/xaxqw/mini-coding-agent` |
| REVIEW.md 自评说明 | ✅ 已更新至真实模型验证 |
| README.md 部署/使用说明 | ✅ |
| start.bat / start.sh / Dockerfile 一键启动 | ✅ |
| 录屏（腾讯会议） | ⏳ 候选人手动录制（须含与 AI 交互过程） |

## 五、遗留风险与建议

1. **录屏**是硬性交付项，需候选人自行录制并展示与 AI 助手的交互过程。
2. 危险命令识别为启发式黑名单：可加 LLM 语义兜底，降低未命中风险。
3. 会话为内存态：如需演示重启保留，可加 SQLite 持久化。
4. 生产部署建议：Docker 镜像构建后需显式挂载 `workspace/` 卷（沙箱目录）。
