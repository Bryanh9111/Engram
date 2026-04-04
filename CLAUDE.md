# Engram

AI agent 记忆系统 - 类人脑的持久化记忆，为 coding agent 设计。

## 项目结构

```
src/engram/
  model.py      — MemoryObject, MemoryKind, MemoryOrigin, MemoryStatus
  db.py         — SQLite + FTS5 schema, init_db()
  store.py      — MemoryStore: remember/recall/forget/consolidate/health/export/stats/micro_index
  proactive.py  — ProactiveRecallEngine: 主动召回 + suppress
  cli.py        — CLI: engram add/search/forget/candidates/stats
  server.py     — MCP Server (FastMCP, 10 tools)
tests/
  test_model.py, test_store.py, test_proactive.py, test_cli.py, test_mcp.py
```

## 技术栈

- Python 3.11+ / uv
- SQLite + FTS5 (WAL mode)
- MCP protocol (FastMCP)
- pytest (85 tests)

## 开发规范

- TDD: 先写测试，看它失败，再写最小实现
- `uv run pytest tests/ -v` 运行全部测试
- `uv sync --extra dev --extra mcp` 安装依赖
- 不用 pip，不用全局安装，只用 uv
- 环境变量 `ENGRAM_DB` 指定数据库路径，默认 `~/.engram/engram.db`

## 记忆类型 (kind)

- `constraint` — 硬约束，半永久（"金额用整数分"）
- `decision` — 可修正的决策（"用 polling 不用 websocket"）
- `procedure` — 操作步骤，需版本控制（"先 seed Redis 再启动"）
- `fact` — 短命事实（"SearchV2 在 flag 后面"）
- `guardrail` — 事故驱动的防护（"这两个 migration 不能并行"）

## 记忆来源 (origin)

- `human` — 用户/人类显式写入（最高信任，proactive 推送）
- `agent` — AI agent 工作中自动写入（中信任，proactive 推送）
- `compiled` — compile() 生成的摘要（参考信任，不主动推送，只在 recall 时返回）

## 核心设计原则

- 主动召回 > 被动搜索（Proactive Recall）
- 写入质量 > 写入数量
- memories enter context as claims, not documents
- 永不自动删除，只标记候选归档
- Just-in-time guardrails, not ambient autobiography
- SQLite 是运行时真相源，Markdown 是编译/导出层
- origin 分离防止 AI 编译产物污染人类判断

## MCP Tools (10)

```bash
uv run engram-server  # 启动 MCP server
```

- `remember` — 写入记忆 (kind + origin)
- `recall` — 检索 (budget: tiny/normal/deep)
- `forget` — 软删除
- `consolidate` — 归档候选
- `proactive` — 文件打开时主动推送 guardrails
- `suppress` — 临时静音某条 proactive 记忆
- `health` — 健康检查 (矛盾/缺证据/孤岛)
- `micro_index` — 紧凑索引 (~200 tokens)
- `stats` — 统计
- `export` — 导出 (jsonl/markdown)
