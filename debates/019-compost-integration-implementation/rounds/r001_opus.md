# Debate 019 — Opus 4.7 立场

**视角**: 10 年维护 + 信任边界 + schema 演进成本

---

### Q1 — D (混合: 新 kind=insight + 新 origin=compost，放主表)

10 年看, C (物理隔离) 引入双表双 FTS5 维护债, 每次 schema 改动都得两处同步; D 用两个维度（kind 做 UX 区分、origin 做审计追溯）在主表内达成同等隔离, 成本更低。代价是 v3.3 Slice A 的 `CHECK(origin IN ('human','agent'))` 要扩到 `IN ('human','agent','compost')` + invariant test 更新, 可接受。

### Q2 — A (Compost 预拆, Engram 写路径保持零 LLM)

Anchor v2 明说 "recall 路径零 LLM", 但 Codex D 引入 "kind-specific LLM 写路径" 是**边界开始腐蚀**的信号。5 年后有人会问"既然 event kind 可 LLM, decision 为什么不能", 然后是第二、第三。A 路径让 Engram 核心从不碰 LLM（连写入都不碰）, 边界清晰到连 CI invariant test 都能锁死。用户的长文入口应该是 `compost add long-form.md`, Compost 拆完回写 Engram。

### Q3 — A (scope=global)

Slice A 已经定义 scope 三元 (project/global/meta), **直接复用不新增枚举值**是最小扰动。Compost 的 cross-project insight 自然映射到 global 语义。B 建议把 meta 重定义为"跨项目知识"会推翻刚固化的 anchor 语义 (meta = 关于用户自身), 不划算。

### Q4 — C (MCP tool + CLI 两者)

两个目标用户不同: MCP tool 给 Compost adapter 程序化调用 (streaming + 结构化), CLI 给用户 debug / 导出到别处用 (NDJSON 手动 pipe)。共用 handler 成本 <50 LoC, 拒绝其中一个就卡死另一类用户。

### Q5 — **E (新方案)**: 默认包含 + stable sort 后置 + 字段标记

Codex B "默认排除" 让 insight 永远看不到 (Sonnet 正确识别 agent 系统性跳过风险)。Sonnet C "两段输出" 破坏 `effective_score` 排序一致性, 调用者要自己 merge 麻烦。

**折中**: default `recall()` 包含 compost, 但结果里 compost 条目**stable sort 到同 score 的 human/agent 之后** (即用 `(origin_priority, effective_score)` 排序, human/agent=0, compost=1)。CLI 输出加 `[compost]` 前缀, MCP response 保留 `origin` 字段。这样:
- agent 每次都能看到 insight, 不会系统性跳过
- 用户/agent 能一眼区分来源
- 不破坏 effective_score 排序, 只加副序键
- 需要纯人类记忆时可 `recall(origin=['human','agent'])` filter

### Q6 — D (分级 GC: expired→隐藏, expired+N 天→自动删)

A (直接 GC) 对用户不可逆, B (仅 lint) 不会自动回收存储, C (永不删) 10 年后表膨胀。D 给用户一个窗口期发现"这条 insight 其实还有用"→ 手动重新 pin 它就不删。GC 间隔用 SQLite 简单 cron: 每次 `engram stats` 或 session_start hook 跑一次清理。

### Q7 — B (MCP tool `invalidate_compost_fact`)

A (HTTP webhook) 给 Engram 加网络 server 是**架构倒退** (Engram 一直是 stdio MCP + CLI)。C (Compost 直写 DB) 违反 HC-1 独立性（创建共享 DB 耦合点）。D (只靠 TTL) 无法处理"Compost fact 早于 TTL 就变更"的快速迭代场景。B 是唯一既遵循 HC-1 又能实时响应的路径, 幂等性天然（同 fact_id 重复 invalidate 结果一致）。

---

## 推荐组合

```
Q1=D  Q2=A  Q3=A  Q4=C  Q5=E (修正版)  Q6=D  Q7=B
```

---

## Opus 独家警告

1. **schema CHECK 扩展后 invariant test 要更新**: `test_compiled_origin_rejected_by_schema` 要改成测 `origin IN ('human','agent','compost')` 的闭集断言。不然加个 `agent-synthesized` 之类的新 origin 就悄悄溜进来。

2. **origin 枚举一旦到 4 个值就危险**: 今天从 2 扩到 3 (加 compost), 5 年后诱惑加 `agent-v2` / `distilled` / `imported` 。必须写死在 ARCHITECTURE.md: "origin 只能增加，不能改语义, 任何新增需要 ADR + debate"。否则 origin 会变成垃圾抽屉。

3. **Compost 的 `synthesized_at` 字段要进 schema**: Contract 给了 payload 里有 `synthesized_at`，但 Engram schema 没字段存。加 `compost_synthesized_at TEXT NULL` 到 memories，让 Engram 能按"insight 年龄"做独立 TTL 判断，不完全信赖 Compost 的 `ttl_seconds`。

4. **10 年 scope=global 数量膨胀风险**: Compost 的 "cross-project insight" 产能极强 (L5 reasoning layer 激活后), 50 条/月 × 10 年 = 6000 条 global 条目。需要 `engram dashboard` 把 global 条目的频率 / 来源分布可视化, 否则 proactive recall 会被 "通用陈词滥调" 淹没。
