# Debate 020 — Engram Phase 3 优先级

**Debate ID**: 020-phase3-priority
**Rounds**: 1
**Style**: independent evaluation (blinded — no cross-contamination)
**Advisors**: gemini, codex, sonnet, opus
**Started**: 2026-04-17T18:30:00Z

## Question

Engram v3.4 Slice B Phase 2 S2 刚完成，Compost 双向通道 runtime 全部落地（stream_for_compost / invalidate_compost_fact / export-stream）。214/214 tests 绿，main @ 3ece2ca pushed。handover 和文档都同步到最新。

现在要决定 Phase 3 四个候选的优先级和顺序。

## Candidates

**候选 A — ARCHITECTURE.md**（纯文档，~半天）
把 origin 不变量 / trust boundary / Compost 契约 / append-only 规则 / API surface 纪律正式化成一份 architecture doc。Compost session 做 Phase 5 adapter 需要读我们的硬约束 reference。可直接从已写的 5 条 pinned memory 蒸馏。

**候选 B — engram lint 扩展**（代码 + 测试，~1 天）
增加 compost-specific lint 检查：origin=compost 无 source_trace（schema 已挡，这是 defense-in-depth）/ expires_at 已过期仍 active / insight kind 非 compost origin / compost_insight_sources 孤儿。

**候选 C — recall/proactive 分层**（debate 019 Q5 F）
触发条件: 生产 >10 条 compost entry。当前生产 DB 有 0 条 compost entry。目的: 让 compost-origin insight 只在 deep budget 或显式查询时返回，不稀释 human/agent 的 recall 命中。

**候选 D — GC daemon**（代码 + 调度）
触发条件: 见到第一条 expired compost entry (30-day grace per contract)。当前无 expired entry。扫 expires_at 过期的 compost entries 物理删 + 扫 compost_insight_sources 孤儿。

## Context Constraints

1. Solo dev，每个选择都是真实工作时间
2. Compost session 正在并行开发 Phase 5 adapter，需要接口稳定
3. Engram 是零-LLM / 零外部依赖的个人记忆库，不是商业产品
4. "永不做清单" 仍生效（no silent auto-delete / no blob memories / no opaque ranking / no background rewriting）
5. 数据驱动触发原则: 没真实问题不加功能

## User's Initial Judgment

倾向 A (ARCHITECTURE.md) 最优，因为 Compost Phase 5 需要它且成本最低。但担心是不是过度偏好文档工作，实际应该先做 B (lint) 以免将来 compost entries 积累后难回溯清理。

## Asked From Each Advisor

1. 推荐顺序
2. 每项的预期 ROI (成本 vs 价值)
3. 是否有第五选项用户没列
4. 独立开发者视角 vs 团队视角该如何权衡

## Background References

- `/Users/zion/Repos/Zylo/Engram/CLAUDE.md` — project instructions incl. roadmap + disciplines
- `/Users/zion/Repos/Zylo/Engram/README.md` — public-facing overview
- `/Users/zion/Repos/Zylo/Compost/docs/engram-integration-contract.md` — Compost 集成契约
- `debates/019-compost-integration-implementation/synthesis.md` — Compost 集成 7 决策
- `docs/non-exposed-schema-fields.md` — API surface 白名单
- Latest commits: 90dcac8 / a2d5332 / ea223fa / 3ece2ca
