# Engram

AI agent 记忆系统 - 类人脑的持久化记忆，为 coding agent 设计。

## 项目结构

```
src/engram/
  model.py      — MemoryObject, MemoryKind, MemoryOrigin, MemoryStatus
  db.py         — SQLite + FTS5 schema + ops_log table, init_db()
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
- pytest (99 tests)

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

## 永不做清单（GPT-5.4 约束，永久有效）

1. **NO silent auto-delete** — 记忆只能被显式 forget/resolve
2. **NO blob memories / wiki dumps** — 保持 atomic claims，不存大段内容
3. **NO opaque ranking** — 必须能解释为什么这条记忆浮现
4. **NO background rewriting** — 不未经人类审核改写源记忆

## 写入质量规则 (kind-specific)

- `guardrail` 无 evidence_link → confidence 降至 0.7
- `constraint` 无 project 且无 path_scope → confidence 降至 0.8
- `procedure` 无 project 且无 path_scope → confidence 降至 0.9
- `fact`/`decision` 无强制字段
- 用户显式指定 confidence 时不覆盖

## Token 预算 (L0-L3)

- L0 ~200 tokens — `micro_index()` 冷启动定位
- L1 ~300 tokens — `recall(budget="tiny")` 紧凑卡片
- L2 ~2-5K tokens — `recall(budget="normal")` 完整对象（默认）
- L3 ~5-20K tokens — `recall(budget="deep")` 扩展结果 limit=50

## 记忆状态 (status)

- `active` — 正常，参与 proactive recall 和 recall
- `resolved` — 已处理，不再 proactive 推送但仍可 recall 搜索
- `suspect` — 可疑，需人工审核
- `obsolete` — 软删除，不参与任何检索

## 排序机制 (effective_score)

recall 结果按 effective_score 排序：
```
score = confidence × (1 + 0.1 × min(access, 20)) × (1 / (1 + 0.02 × days_since_access))
pinned 记忆 score = 10.0（始终最高）
```

## MCP Tools (12)

```bash
uv run engram-server  # 启动 MCP server
```

- `remember` — 写入记忆 (kind + origin)
- `recall` — 检索 (budget: tiny/normal/deep，按 effective_score 排序)
- `forget` — 软删除 (status → obsolete)
- `resolve` — 标记已处理 (status → resolved，停止 proactive 推送)
- `consolidate` — 归档候选
- `proactive` — 文件打开时主动推送 guardrails
- `suppress` — 临时静音某条 proactive 记忆
- `compile` — 按项目编译记忆为结构化 Markdown（零 LLM）
- `health` — 健康检查 (缺证据/孤岛/stale claims via check_stale=True)
- `micro_index` — 紧凑索引 (~200 tokens)
- `stats` — 统计
- `export` — 导出 (jsonl/markdown)

## CLI (8 commands)

```bash
engram add/search/forget/candidates/stats/dashboard/lint
```

- `dashboard` — 记忆脑全局状态（项目分布/kind分布/健康/近24h活动/热门记忆）
- `lint` — 全面健康检查（缺证据+孤岛+stale claims+kind-specific TTL）

## Kind-Specific Staleness TTL

`engram lint` 按 kind 检查陈旧度（只警告，不自动删除）：

- `fact` — 7 天
- `procedure` — 30 天
- `decision` — 90 天
- `constraint` / `guardrail` — 永不 age-flag（长期有效）

## Claude Code Hooks（可选自动化）

`hooks/` 目录提供 opt-in Claude Code hook 集成：
- `session_start.sh` — 会话开始时注入 brain overview (~200 tokens)
- `user_prompt_submit.sh` — 每个 prompt 前 whisper 相关记忆 (~150 tokens, `ENGRAM_WHISPER=0` 关闭)

安装：在 `~/.claude/settings.json` 的 hooks 配置里引用这些脚本。详见 `hooks/README.md`。

## Roadmap

```
v3.1 (current) — memory lint + Claude Code hooks
   ↓
v4 (trigger: 500 memories) — LLM compile with Planner→Worker→Critic
   ↓
v4.1 (trigger: 时间敏感 memories >10% 或 >30 条) — Temporal Expiry (A, deferred)
   ↓
v5 (trigger: >5 FTS5 miss 真实案例) — Multi-path Recall (C) + LLM rerank
   ↓
v6 (trigger: 2000 memories) — Embedding (sqlite-vec) + RRF fusion
   ↓
v7 (trigger: 3000 memories) — Memory graph + Dream agent
```

**KILLED**: Debounced Write Queue (durability > 省 commit)
