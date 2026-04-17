# Debate 019 — Engram-Side Implementation of Compost Integration Contract

**Date**: 2026-04-16
**Scope**: 在战略骨架与 Compost contract 约束下，Engram 侧的实现决策
**Mode**: decision-making（共识为目标，非 adversarial）
**Participants**: Opus 4.7, Codex, Sonnet (Gemini 配额耗尽跳过)
**Rounds**: 1

---

## 不可挑战的战略骨架（硬边界，debate 不评议）

```
Compost  = 个人 AI 大脑 / 分析伙伴 / self-evolving L4-L6 / 主动 push
Engram   = 整个个人记忆库 / 海马 + 瞬时记忆 / zero-LLM recall
关系     = 双向通道核心 (非 opt-in)
分发     = fork 模板 (每人独立 git clone)
时间尺度 = 10+ 年单用户深度陪伴
```

**战略层已由用户和 Compost session 锁定**。Debate 范围只是"如何在这些原则下实现"。

---

## 契约硬约束（来自 engram-integration-contract.md）

- **HC-1 独立性**: 两边任一 down/uninstall，另一边正常运行
- **HC-2 零 LLM recall**: Engram recall 路径永不调 LLM（写路径可选）
- **HC-3 职责分工**: Compost 产 insight/pattern/synthesis（LLM 衍生），Engram 产 event/note/reflection/preference（原始记忆）

Contract 提出的 insight payload：
```json
{
  "origin": "compost",
  "kind": "insight",
  "content": "<=2000 chars",
  "source_trace": { "compost_fact_ids": [...], "synthesized_at": "...", ... },
  "ttl_seconds": 7776000,
  "confidence": 0.85
}
```

---

## 立即冲突：与 v3.3 Slice A 的 schema 冲突

**刚上线的 schema CHECK** (migration 001_slice_a_schema.sql):
```sql
CHECK(origin IN ('human','agent'))
-- memories 主表拒 origin=compiled/compost 任何 LLM 产物
```

Contract 要 `origin=compost` 写回 → **直接违反 schema CHECK** + `test_architecture_invariants.py::test_compiled_origin_rejected_by_schema`。

⚠️ 任何决策都必须解决这个冲突。v3.3 Slice A commit `7c8f172` 已 push，改 schema 又要一次 migration。

---

## Kind 扩展需求（Anchor v2 已预告）

现有 5 kinds（工作场景）: `constraint` / `decision` / `procedure` / `fact` / `guardrail`
需要加（生活/情感/外部）: `event` / `note` / `reflection` / `preference` / `person` / `habit` / `goal` / `insight`(from Compost)

---

## 7 个决策点

### Q1 — 承载 Compost 产物的 schema 策略（关键）

> Compost 要写 `origin=compost` + `kind=insight` 到 Engram。Engram 的 `CHECK(origin IN ('human','agent'))` + `trust boundary` 怎么适配？

路径：
- **A. Origin 扩展**: `CHECK(origin IN ('human','agent','compost'))`. Compost 直接进 memories 主表，走 default recall 但带 `origin` 标记
- **B. Kind 分离**: 新 `kind=insight` + 保留 origin CHECK. Insight 默认**不进** proactive recall，用户 opt-in recall 时才出
- **C. 物理隔离**: 新表 `compost_insights`（独立 FTS5），独立 MCP tool `recall_insights`，不污染 memories
- **D. 混合**: 新 kind=insight + 新 origin=compost，但放 memories 主表（A + B 组合）

### Q2 — Long-form 写路径 LLM 归属

> 用户写 "今天日记..." 几千字，谁负责拆分成 atomic entries？

路径：
- **A. Compost 预拆**: Engram 写路径保持零 LLM，用户把长文送 Compost，Compost LLM 提取事件后写回 Engram
- **B. Engram LLM-on-write**: 新增 write pipeline，用户直接 `engram add` 长文，Engram 调 LLM 拆（违反 anchor "recall 零 LLM" 的字面但不违反精神）
- **C. 用户手拆**: 用户自己 split，Engram 只存 atomic
- **D. 分 kind 策略**: `kind=note` 长文允许，不拆；`kind=event` 限长，强制拆

### Q3 — Cross-project insight scope

> Compost 合成跨项目 insight（如"你所有项目都用 TDD"）→ scope 字段怎么标？

路径：
- **A. scope=global**: 复用 Slice A 已有三元 (project/global/meta)
- **B. scope=meta**: meta 原本预留"关于用户自身"，global 给"跨项目知识"
- **C. 新 scope 值 `insight`**: 独占语义
- **D. scope 三元不动**，Compost insight 用 `tag` 标 cross-project

### Q4 — Stream API surface

> Compost 需要 poll Engram event/note/reflection 作 ingest source. 接口形态？

路径：
- **A. 仅 MCP**: `mcp__engram__stream_for_compost(since, kinds)` 返回 NDJSON 流
- **B. 仅 CLI**: `engram export-stream --kinds=event,note --since=...` 输出 stdout
- **C. 两者**: MCP tool + CLI 命令（共用一个 handler）
- **D. SQL view**: Engram 暴露 `engram_compost_stream` view，Compost 自己用 sqlite3 读（零新 API 面，但耦合 DB 文件路径）

### Q5 — User review UX（recall 输出标记）

> 用户做 `recall()` 时，怎么区分 `origin=compost` 条目和自己的记忆？

路径：
- **A. CLI prefix**: `[compost]` 前缀 + MCP response 加 `origin` 字段
- **B. 默认排除 + opt-in flag**: `recall(include_compost=True)` 才出 compost 条目
- **C. 独立结果 section**: recall 输出两段 `--- your memories ---` / `--- compost insights ---`
- **D. 可排序标记**: 按 `(origin, score)` 排，compost 永远在 human/agent 之后

### Q6 — Storage growth（TTL 与 GC）

> Compost payload 带 `ttl_seconds=7776000`（90 天默认）。过期后怎么办？

路径：
- **A. 自动 GC daemon**: 后台定期删 `expires_at < now` 的 compost 条目
- **B. Lint warning only**: `engram lint` 提示 staleness，用户手动清
- **C. 过期=隐藏不显式删**: `recall` 过滤 expired，存储保留审计
- **D. 分级**: `expired`→隐藏，`expired + N 天`→自动 GC

### Q7 — Contract invalidation 实装

> Compost fact 变更后，要 invalidate 对应的 Engram insight. 通道？

路径：
- **A. HTTP webhook**: Engram 启 HTTP endpoint，Compost POST invalidation
- **B. MCP tool**: `mcp__engram__invalidate_compost_fact(compost_fact_ids)`
- **C. Compost 直接写 DB**: Compost 拿 Engram DB 路径直写 `status=obsolete`
- **D. 不实装**: 只靠 TTL 自然过期

---

## 每方专注与立场格式

- **Opus**: 10 年维护成本 + 信任边界 + schema 演进成本
- **Codex**: SQLite/FTS5/CHECK/trigger 实现可行性 + migration 路径
- **Sonnet**: agent 使用模式 + UX 可感知性 + 错误路径

格式：每方对 Q1-Q7 给 A/B/C/D/E 选择 + 1-2 句理由。最后给推荐组合（e.g. "1D + 2A + 3A + 4C + 5A + 6A + 7B"）。

## 共识规则

- 3/3 一致 → 直接采纳
- 2/3 多数 → 采纳，少数派意见进 amendment
- 3 方分歧 → 标记 NEEDS_USER_DECISION

## 输出

- `rounds/r001_{opus,sonnet,codex}.md` 个人立场
- `synthesis.md` 最终决议
- 可执行形式：更新后的 v3.4 路线（覆盖 v3.3 Slice A 的一些约束）
