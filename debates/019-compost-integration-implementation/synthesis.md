# Debate 019 Synthesis — Engram-Side Implementation of Compost Integration

**Date**: 2026-04-16
**Participants**: Opus 4.7, Codex, Sonnet (Gemini 配额耗尽)
**Rounds**: 1

---

## 票数汇总

| Q | Opus | Codex | Sonnet | 结果 |
|---|------|-------|--------|------|
| Q1 Schema 策略 | D | D | D | **3/3 D** 采纳 |
| Q2 Long-form 写路径 | A | D | A | **2/3 A**, D 可融合 |
| Q3 Cross-project scope | A | A | A | **3/3 A** 采纳 |
| Q4 Stream API surface | C | C | C | **3/3 C** 采纳 |
| Q5 Recall UX | E (新) | B | C | **3-way 分歧**, 融合为 F |
| Q6 Storage / TTL / GC | D | D | D | **3/3 D** 采纳 |
| Q7 Invalidation 通道 | B | B | B | **3/3 B** 采纳 |

---

## 最终决策

### Q1 — D: 新 kind=insight + 新 origin=compost + 放主表

Schema 扩展:
```sql
CHECK(origin IN ('human','agent','compost'))
CHECK(origin != 'compost' OR kind = 'insight')           -- trust boundary
CHECK(origin != 'compost' OR source_trace IS NOT NULL)   -- 可追溯
CHECK(origin != 'compost' OR expires_at IS NOT NULL)     -- 必须有 TTL
```

`kind` 枚举扩展（Engram 自主加）:
- 保留: `constraint` / `decision` / `procedure` / `fact` / `guardrail`
- 新加: `insight` (专属 Compost), `event`, `note`, `reflection`, `preference` (用户/agent)
- `person` / `habit` / `goal` 暂不加，等真实使用再触发

### Q2 — A + D 融合: Engram 写路径零 LLM，schema 按 kind 差异化允许长度

**核心原则**（采 Opus/Sonnet 的 A）: Engram 写路径**永远不调 LLM**。长文拆分是**工作流**约定，不是 Engram 内建能力。

**实现层面**（采 Codex 的 D 精髓）: Schema 里 `kind=note` 保留接受长文（最多 4000 字符）的能力，`kind=event` 建议 < 500 字（soft warning）。

**工作流**:
- 用户直接 `engram add long_journal.md` → agent 检测长度 > threshold → 提示"use `compost add` instead"
- Compost 收到长文 → LLM 拆分 → 回写 Engram 多条 atomic entries (`kind=event`, `kind=reflection` 等)
- Engram 侧永远只存已拆好的 atomic claims

### Q3 — A: scope=global

直接复用 Slice A 的三元 scope。Compost cross-project insight → `scope=global`, `project IS NULL`。零新增枚举，零 migration。

### Q4 — C: MCP tool + CLI 两者

共用 handler, <50 LoC 额外成本。API 形态:
- MCP: `mcp__engram__stream_for_compost(since, kinds, project?) → NDJSON stream`
- CLI: `engram export-stream --kinds=event,note,reflection --since=2026-04-01 [--project=X]`
- **共用底层**: `MemoryStore.stream_entries(since, kinds, project)` generator

关键规则:
- **`origin=compost` 条目默认排除** (避免 Compost 读自己回写的 insight 形成循环)
- `memory_id` 稳定, `updated_at` 用于 Compost 判断是否重新 extract
- 只流 `kinds ∈ {event, note, reflection, preference}` (生活/情感记忆)，不流工作 guardrail

### Q5 — F (融合三方): 分层默认策略

Opus/Codex/Sonnet 三方分歧，综合最优:

**recall() 默认行为**:
- 包含 compost 条目（Sonnet C 精神: 避免 agent 系统性跳过）
- MCP response 返回**两个 list**:
  ```json
  {
    "results": [...],           // human/agent entries, sorted by effective_score
    "insights": [...]           // origin=compost entries, separate list
  }
  ```
- CLI 输出两段（Sonnet C）:
  ```
  === Your memories ===
  [decision] abc123 ...
  [fact] def456 ...

  === Compost insights ===
  [insight] xyz789 ...   (synthesized 2026-04-10, expires 2026-07-10)
  ```
- 若 `insights` 空则 CLI 省略第二段（节省 token）
- Filter 选项: `recall(include_compost=False)` 纯净模式; `recall(only_compost=True)` 只看 insight

**proactive() 默认行为** (Codex B 精神):
- **默认不含 compost**（避免 proactive 每次 prompt 前置时 compost 挤占）
- 但 **独立跑一次** `scope='global' AND origin='compost'` top-3 作为"背景知识"注入（Sonnet 第3独家风险）
- MCP response: `{"guardrails": [...], "background_insights": [...]}`

**effective_score 排序不变**（Opus 顾虑）: 仍按 `(pinned, score, recency)` 排，compost 条目用同一排序但在独立列表里，不污染 human/agent 排序。

### Q6 — D: 分级 GC (expired→隐藏, expired+N 天→物理删)

- **读路径过滤**: recall/proactive 用 `(expires_at IS NULL OR julianday(expires_at) > julianday('now'))` 过滤
- **后台 GC**: 每次 `engram stats` / `engram lint` / session_start hook 跑一次:
  ```sql
  DELETE FROM memories
  WHERE origin = 'compost'
    AND status = 'active'
    AND expires_at IS NOT NULL
    AND julianday(expires_at) <= julianday('now', '-30 days');
  ```
- **lint 警告**: compost insight 7 天内过期 → `engram lint` 给 warning，用户可 `resolve` 转人类记忆保留
- **VACUUM**: 不放热路径, 月度 maintenance cron

### Q7 — B: MCP tool `invalidate_compost_fact`

```python
@mcp.tool()
def invalidate_compost_fact(compost_fact_ids: list[str]) -> dict:
    """Mark Compost insights as obsolete when source facts change/are superseded.
    Idempotent: same fact_ids can be invalidated repeatedly."""
```

实装: 维护 `compost_insight_sources` side table (fact_id → memory_id) 做快速反查（Codex Migration 002 已设计）。

---

## Migration 002 草稿 (采 Codex 的 DDL, 全盘接受)

见 `rounds/r001_codex.md` PHASE 1-7 的 SQL。关键点:

1. 单事务 `BEGIN IMMEDIATE ... COMMIT` (debate 017 硬约束)
2. 保留 `rowid` 迁移 (Codex W2 警告)
3. 显式 FTS5 `rebuild` (Codex W1 警告)
4. 新增字段: `source_trace JSON` + `expires_at TEXT`
5. 新增 table: `compost_insight_sources (memory_id, fact_id)` with index on `fact_id`
6. 新增 partial index: `idx_memories_compost_live` WHERE origin='compost' AND status='active'
7. memory_scores view 加 expires_at 过滤

## 独家警告（都接受）

**Opus 警告**:
- O1: invariant test 要改 (`test_compiled_origin_rejected_by_schema` 扩到 3 值闭集断言)
- O2: origin 只增不改语义，新增需 ADR + debate (写入 ARCHITECTURE.md)
- O3: `compost_synthesized_at` 独立 TTL 判断（不完全信 Compost 的 `ttl_seconds`）
- O4: 10 年 global compost 条目膨胀 → `engram dashboard` 可视化 global 来源分布

**Codex 警告**:
- C1: `CHECK` 不能 ALTER, 必须整表重建（已纳入 Migration 002）
- C2: external-content FTS5 绑 rowid 不是 id（已纳入）
- C3: DELETE 不缩文件，WAL churn → 月度 VACUUM 独立 cron

**Sonnet 警告**:
- S1: 信任污染在 prompt 层（Q5 F 方案通过"两个 list"解决）
- S2: 写失败状态歧义（Q2 A 通过"Engram 永远只收 atomic"解决）
- S3: Cross-project insight 触发时机（Q5 F 方案 proactive 独立 merge top-3 解决）

---

## 对 Compost session 的 contract 修正

1. **Payload 的 `origin` 字段**: 接受 `"compost"`（不是 `"compost-synthesis"` 或别的变体）
2. **`content ≤ 2000 chars`**: Compost 自拆，Engram schema 上限是 4000 (大于 contract 限制，不冲突)
3. **Engram 侧要求新增字段**:
   - `expires_at` 必填（TTL 实装要求）
   - `source_trace` 必填且 `json_valid`
   - `compost_fact_ids` 进 side table
4. **Invalidation API**: MCP `invalidate_compost_fact(compost_fact_ids: list)`（非 HTTP webhook）
5. **Stream API**: Compost 用 `mcp__engram__stream_for_compost(since, kinds, project?)`，不用 CLI
6. **Engram 默认不反流 compost origin**: 避免循环

---

## v3.3 Slice A → v3.4 Slice B 路线衔接

Slice A 完成 (commit `7c8f172`): scope enum + CHECK + recall_miss_log + compost_cache DDL

**v3.4 = Slice B + Compost integration**:
- Migration 002: schema 扩 origin / 新 kind / source_trace / expires_at / compost_insight_sources
- MCP tools: `stream_for_compost`, `invalidate_compost_fact`
- CLI: `engram export-stream`
- recall/proactive 分层策略（Q5 F）
- GC daemon + lint warning
- invariant tests 更新（O1）
- ARCHITECTURE.md 添加 "origin 只增不改" (O2)

**不含**（推到 Slice C 或后续）:
- `compost_cache` 表数据层（debate 016 遗留，现在语义已被 `origin=compost` insight 路径取代，可能废弃）
- Repository 抽象层
- WAL PRAGMA 审计

---

## 进入实施前置条件

- [ ] 本 synthesis 用户确认
- [ ] Contract 修正点同步给 Compost session
- [ ] Migration 002 审核（单事务 + FTS rebuild + CHECK）
- [ ] 现有 141 tests baseline 全绿
- [ ] 新 invariant tests 设计（origin 闭集 / kind 扩展 / compost_insight_sources 关系）

满足后进入 Slice B 实施。
