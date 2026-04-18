# Engram

AI agent 记忆系统 - 类人脑的持久化记忆，为 coding agent 设计。

## 项目结构

```
src/engram/
  model.py      — MemoryObject, MemoryKind(6), MemoryOrigin(3), MemoryStatus(4), MemoryScope(3)
  db.py         — SQLite + FTS5 schema + ops_log + compost_insight_sources + compost_cache
  migrations/   — 001_slice_a_schema.sql, 002_slice_b_compost_integration.sql
  store.py      — MemoryStore: remember/recall/forget/resolve/unpin/consolidate/health/
                  export/stats/micro_index/compile/stream_entries/_map_insight_sources
  proactive.py  — ProactiveRecallEngine: 主动召回 + suppress
  cli.py        — CLI: add/search/forget/unpin/candidates/stats/dashboard/lint/export-stream
  server.py     — MCP Server (FastMCP, 14 tools)
tests/
  test_model, test_store, test_proactive, test_cli, test_mcp,
  test_architecture_invariants, test_api_surface_coverage,
  test_stream_entries, test_compost_insight_sources,
  test_stream_for_compost, test_invalidate_compost_fact, test_cli_export_stream
```

## 技术栈

- Python 3.11+ / uv
- SQLite + FTS5 (WAL mode), migrations in `src/engram/migrations/`
- MCP protocol (FastMCP)
- pytest (234 tests)

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
- `insight` — Compost 合成的跨项目洞察（**保留给 origin=compost**，schema CHECK 强制）

## 记忆来源 (origin)

- `human` — 用户/人类显式写入（最高信任，proactive 推送）
- `agent` — AI agent 工作中自动写入（中信任，proactive 推送）
- `compost` — Compost 合成跨项目 insight 写回（必须 kind=insight + source_trace JSON + expires_at TTL；默认从 stream_for_compost 排除防 feedback loop）

**注意**: `compiled` 已从 MemoryOrigin 删除（v3.4 Slice B Phase 2 P0）。compiled 内容现在只存在 `compost_cache` 表，不写 `memories` 主表。

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
2. **NO blob memories / wiki dumps** — 保持 atomic claims，不存大段内容（content ≤ 4000 chars，schema 强制）
3. **NO opaque ranking** — 必须能解释为什么这条记忆浮现
4. **NO background rewriting** — 不未经人类审核改写源记忆

## API Surface 纪律 (v3.4 Slice B Phase 2 P0)

新增 schema 列时必须二选一，无第三选项：
- **(a)** 加到全部 4 write surfaces: `MemoryStore.remember` / `server._handle_remember` / MCP `remember` tool / CLI `engram add`
- **(b)** 加到 `docs/non-exposed-schema-fields.md` computed-internal 白名单并解释为什么不暴露

`tests/test_api_surface_coverage.py` 在 CI 强制执行。drift 会直接让测试失败。

同步: `MemoryOrigin` / `MemoryKind` / `MemoryScope` / `MemoryStatus` enum 值必须与 DB CHECK 清单一致。`tests/test_architecture_invariants.py::TestEnumSchemaAlignment` 强制。

## Append-Only Content 纪律

memory content 一旦写入不可变更。`stream_for_compost` 的 `updated_at = created_at` 是该纪律的表现。未来若加 edit API：
- 加 `updated_at` schema 列 + 触发器维护
- 改 `_memory_to_compost_dict` 返回真实 updated_at
- 通知 Compost re-ingestion 语义变更

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

## MCP Tools (14)

```bash
uv run engram-server  # 启动 MCP server
```

**Memory lifecycle**:
- `remember` — 写入 (kind + origin + 可选 source_trace/expires_at/scope)
- `recall` — 检索 (budget: tiny/normal/deep，按 effective_score 排序)
- `forget` — 软删除 (status → obsolete)
- `resolve` — 标记已处理 (status → resolved，停止 proactive 推送但仍可 recall)
- `unpin` — 单条解除 pinned（use sparingly，prefer supersede via new memory）
- `consolidate` — 归档候选
- `suppress` — 临时静音某条 proactive 记忆

**Recall / 洞察**:
- `proactive` — 文件打开时主动推送 guardrails
- `compile` — 按项目编译记忆为结构化 Markdown（零 LLM）
- `health` — 健康检查 (缺证据/孤岛/stale claims via check_stale=True)
- `micro_index` — 紧凑索引 (~200 tokens)
- `stats` — 统计

**Compost 双向通道 (v3.4 Slice B)**:
- `stream_for_compost(since?, kinds?, project?, include_compost=False, limit=1000)` — 契约投影导出供 Compost 摄取；默认排除 origin=compost 防 feedback loop
- `invalidate_compost_fact(fact_ids)` — Compost 端上游事实失效时软删对应 insight；忽略 pinned（Compost 是 insight 新鲜度权威）

## CLI (10 commands)

```bash
engram add/search/forget/unpin/candidates/stats/dashboard/lint/export-stream
```

- `dashboard` — 记忆脑全局状态（项目分布/kind分布/健康/近24h活动/热门记忆）
- `lint` — 全面健康检查（缺证据+孤岛+stale claims+kind-specific TTL）
- `unpin` — 单条解除 pinned（默认交互确认，`--yes` 脚本模式）
- `export-stream` — Compost 批量摄取 JSONL 流，与 MCP `stream_for_compost` 同 handler

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
v3.1 — memory lint + Claude Code hooks
v3.2 — real token measurements + health summary mode (99% 减 token)
v3.3 — Slice A: schema hardening + unpin API + scope 三值 enum (migration 001)
v3.4 Slice B Phase 1 — Compost schema foundation (migration 002: insight kind + source_trace + expires_at + compost_insight_sources)
v3.4 Slice B Phase 2 P0 — API surface invariant + MemoryOrigin 对齐
v3.4 Slice B Phase 2 S2 (current) — 双向 Compost 通道 runtime (stream_for_compost / invalidate_compost_fact / export-stream)
   ↓
Phase 3 (按数据触发):
  - recall/proactive 分层 (debate 019 Q5 F) — 触发: 生产 >10 条 compost entry
  - GC daemon — 触发: 见到第一条 expired compost entry (30-day grace per contract)
  - engram lint 扩展 (compost-specific) — 随时
  - ARCHITECTURE.md origin 不变量文档化 — 完成 (0ee0580)
  - SQLite PRAGMA 审计 (debate 016 Codex I3) — 完成 (a2369cf)
  - recall_miss_log writer (debate 016 Q4) — 完成 (passive collection, 离线 export 到 Compost 待 v5 trigger)
   ↓
v4 (trigger: 500 memories) — LLM compile with Planner→Worker→Critic
  ⚠ 当前 553 memories 已穿透 trigger, 但 Compost Slice B 已承担部分"跨项目 synthesized insight" 职责, v4 scope 需重新评估
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

## Compost 集成契约 (v3.4 Slice B)

详见 `/Users/zion/Repos/Zylo/Compost/docs/engram-integration-contract.md`。关键点：

- **Engram → Compost** (事件源): `stream_for_compost` / CLI `export-stream` 以 9-key 契约 shape 流出 `{memory_id, kind, content, project, scope, created_at, updated_at, tags, origin}`；默认 `include_compost=False` 防 feedback loop
- **Compost → Engram** (失效通道): `invalidate_compost_fact(fact_ids)` 逆查 `compost_insight_sources` 表，软删匹配 insights（忽略 pinned — Compost 是 insight 新鲜度权威）；物理删由 Phase 3 GC daemon 按 30-day grace 处理
- **origin=compost 写入要求**: 必须 `kind=insight` + `source_trace` (JSON) + `expires_at` (ISO TTL)，三 CHECK 在 schema 强制
- **独立性硬约束**: 任一方不可用时另一方功能完整（HC-1）。Engram recall 路径永远零 LLM（HC-2）

## 辩论档案索引

- `debates/019-compost-integration-implementation/synthesis.md` — 7 决策 (Q1=D / Q2=A+D / Q3=A / Q4=C / Q5=F / Q6=D / Q7=B)
- `docs/non-exposed-schema-fields.md` — API surface 白名单不变量
- `docs/v3.3-migration-plan.md` — Slice A 背景
