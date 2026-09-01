# REVIEW.md — 候选人自评说明

## 做了什么

**一阶段：极简 Coding Agent（commit `feat(stage1)`）**
- 实现 Agent 循环：LLM 决策 → 工具调用 → 结果回填 → 再次决策
- 四个基础工具：`list_dir` / `read_file` / `write_file` / `run_command`
- 沙箱隔离：文件操作限制在 `workspace/` 内
- Mock 模式：无 API Key 也可离线演示完整链路
- 交付形态：CLI（`python -m backend.cli`），支持单轮/多轮交互

**二阶段：方向一四项增强（commit `feat(stage2)`）**
1. **Web UI**：聊天界面 + 工具调用可视化卡片 + 状态灯
2. **工具并行调用**：`asyncio.gather` 并行执行互不依赖的工具；并发冲突设计——文件写入全局写锁串行化、命令执行互斥
3. **工具权限控制**：危险命令黑名单（`rm -rf`/`format`/`shutdown` 等破坏性命令）拦截后转人工审批，批准才执行
4. **ask_user**：Agent 提问 → loop 挂起 → 用户回答 → 自动恢复

## 设计决策

| 问题 | 方案 |
|------|------|
| 工具并发冲突 | 写操作串行化（WRITE_LOCK），只读并行；命令执行互斥（EXEC_LOCK） |
| 危险命令识别 | 黑名单正则（启发式），覆盖跨平台破坏性命令，命中即审批 |
| 沙箱逃逸防护 | 路径 `resolve()` 后校验前缀，`../` 越界直接拒绝 |
| 用户交互挂起 | `asyncio.Event` + pending 表，SSE 推送到前端，`/api/resolve` 恢复 loop |
| 无 Key 可演示 | Mock 模式按关键词触发工具调用，覆盖写文件/审批/提问/并行四类场景 |

## 验证情况

`test_flow.py` 全链路自动化测试 4/4 通过：
- ✅ 创建脚本 → `write_file`
- ✅ 危险命令 → 审批通过并执行
- ✅ `ask_user` → 提问并恢复 loop
- ✅ 工具并行调用（同时下发 2 个工具）

## 未完成 / 可改进

- 真实模型接入：拿到公司 API Key 后填入 `.env` 即可切换（当前已验证 Mock 模式全链路）
- 流式输出（token 级打字机）未做，当前为整段消息推送
- 会话持久化未做（内存态，重启丢失）
