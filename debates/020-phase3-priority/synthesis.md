# Synthesis — Debate 020: Engram Phase 3 优先级

**Debate**: 2026-04-17 | 1 round | 4 participants independent evaluation

## 统一结论

**Ship A (trimmed) today → trim B to 2 real checks + B.5 expiry audit → defer C/D.**

**强制前置**: A 不是纯文档活 — **Codex 发现 server.py 有 3 处 origin='compiled' drift（line 244/276/296），MCP server 的 instructions 和 docstring 仍告诉 agents origin 是 human/agent/compiled，但 enum 和 DB CHECK 都已是 human/agent/compost**。这是 v3.4 P0 enum 迁移时漏改的，每个用 MCP 的 Claude 都在读错误的 origin 说明。必须在 A 里同步修。

## 四方立场概览

| 模型 | 推荐顺序 | A 估时 | B 态度 | 第 5 选项 |
|------|---------|--------|--------|-----------|
| 🟡 Gemini | A → B → wait C/D | 0.5d | "紧随其后" | 契约测试化（verify_adapter.py）|
| 🔴 Codex | A-lite → B → wait C/D | **0.5-1d** | 1-1.5d（审计型）| **A-lite + drift fix** |
| 🟠 Sonnet | A → B(trimmed) → skip C/D | ~4h | 1d → 3-4h（删 schema 冗余）| **B.5 expiry 过滤审计**|
| 🐙 Opus | A → wait → C → B → D | ~0.5d | Low ROI（schema 已挡）| **E = Compost dogfood 作 forcing function**|

## 一致点

1. **A 必须先做** — 全票。Compost Phase 5 正在并行开发，缺 canonical reference 每天累积错误假设成本。
2. **A 的 confirmation bias 检查**: 不是拖延 — Compost Phase 5 是真实命名的时间敏感消费者，不是 "someday useful"。
3. **C / D 严守数据触发** — 全票延迟。0 条 compost entry / 0 条 expired = YAGNI。
4. **B 需要裁剪** — Sonnet + Codex 都指出：schema CHECK 已在写路径挡住 `origin=compost` 三元约束。lint 再检这些是测 SQLite 不是测 Engram 代码。

## 关键分歧

### 分歧 1: B 的有效检查清单

- **Sonnet**: 只保留两个: `expires_at 过期仍 active` (时间性，schema 无法挡) + `compost_insight_sources` 孤儿。
- **Codex**: 警告孤儿检查的细节陷阱 — `invalidate_compost_fact` 软删后 map row 被保留用于幂等，简单查询会误报。建议做之前先澄清语义。
- **收敛**: 孤儿检查要先决定 "孤儿" 的准确定义（status=obsolete 的 memory_id + map row 是否算孤儿？答案取决于 Phase 3 GC 设计）。先做 expiry 检查，孤儿等 GC 定义。

### 分歧 2: 第 5 选项

四个模型给了四个不同的 5th option，构成完整补集：

- **Gemini E1**: Contract-as-Code — 把 A 的硬约束写成 `verify_adapter.py` 让 Compost 自测
- **Codex E2**: A-lite + drift fix — 统一契约/命名/CLI 文案 + 1-2 个 invariant tests
- **Sonnet E3 (B.5)**: Expired-filter audit across all read paths (recall/stream_for_compost/export/proactive) — 30 分钟
- **Opus E4**: Compost dogfood 作 forcing function — 不建造，等真实数据

**实际上这四个互补**:
- E2 (Codex) 是 A 必须包含的（否则 A 本身就是骗人的文档）
- E3 (Sonnet) 是立刻要做的独立小任务（30min，高风险低成本）
- E1 (Gemini) 是 A 的升级版（如果 A 足够好 E1 就不需要）
- E4 (Opus) 是 A 之后的默认策略（数据驱动）

## 推荐路径（基于四方共识 + 关键发现）

**今天的工作（总 ~5-6 小时）**:

1. **E3 先做** (~30min): 验证 `expires_at` 过期过滤在所有读路径 (recall, stream_for_compost, export, proactive) 一致。发现问题立即修 + 加测试。**这是最高 ROI**：极低成本，可能防一个 correctness bug 偷偷溜进 Compost 集成。

2. **Codex drift fix** (~30min): 修 server.py line 244/276/296 三处 origin='compiled' 过时引用，换成 'compost'。加一个不变量测试: MCP server instructions + 关键 docstring 内的 origin 列表必须与 MemoryOrigin enum 一致（用 AST 或 string match）。**这是 Codex 独家发现**，其他三个模型都没注意到。

3. **A (ARCHITECTURE.md)** (~3-4h): 从 5 条 pinned memory 蒸馏。必须包含（按 Gemini 提醒）"如何验证这些规则"的自动化思路引用——列出对应的不变量测试。
   - 结构：Identity & scope → Hard constraints (HC-1 独立性 / HC-2 零 LLM) → Trust boundary (origin 三值语义 + invalidate pinned 决策) → Append-only content → API surface 纪律 → Compost 双向通道契约 → v3.4 Slice B 完成清单 + Phase 3 触发条件
   - 引用所有相关 pinned memory id (e5749c50c84c / 9d51ee6a8bfd / 4927125bb2d7 / 83bf757a3709 / a167bc678f53 / c266b5d41250) 
   - 终点链接：`debates/019-compost-integration-implementation/synthesis.md`, `docs/non-exposed-schema-fields.md`

**下次 session (1-3 小时)**:

4. **B (trimmed)** (~1-2h): 只加 `expires_at 过期仍 active` lint 检查（E3 已验证 recall 路径，lint 是人工扫描工具为背书）。孤儿检查等 Phase 3 GC 设计时一起决定语义。

**延迟到数据触发**:
- C recall/proactive 分层（等 >10 compost）
- D GC daemon（等第一条 expired）

## 意外发现及 Action Items

1. **drift: server.py 3 处 'compiled'** — Codex 发现。今天必须修，归入 A 的工作。
2. **expiry filter coverage 未审计** — Sonnet 发现。30min 独立任务，今天做。
3. **Arch doc 必须带"如何验证"** — Gemini 提醒。A 里列出对应测试路径。
4. **孤儿定义未明** — Codex 警告。B 阶段先做 expiry，孤儿留给 Phase 3 GC 规划。

## Quality Scores

| Advisor | Length | Citation | Code | Engagement | Total |
|---------|--------|----------|------|------------|-------|
| 🟡 Gemini | 25 | 25 | 0 | 0 | 50 (proceed, 5th option abstract) |
| 🔴 Codex | 25 | 25 | 25 | 0 | 75 ✓ (独家发现 drift) |
| 🟠 Sonnet | 25 | 25 | 25 | 0 | 75 ✓ (精确定位 schema 冗余) |
| 🐙 Opus | 25 | 25 | 25 | 0 | 75 ✓ (forcing function 框架) |

*Engagement 0 因为独立评估（blinded mode），模型没有互相看对方响应。这是设计选择以防 anchoring。*

## Final Recommendation

**Order**: E3 expiry audit (30min) → Codex drift fix (30min) → A ARCHITECTURE.md (3-4h) → defer B/C/D until Compost integration produces data.

**Why**: 全票认定 A 优先。两个独家技术发现（server.py drift + 未审计的 expiry filter coverage）不做不行，但都小，可整体纳入今天工作。B 被裁剪到只剩 1-2 个真实有效检查，可等明天。

**User 的 confirmation bias 担忧**: 可以放心。证据是强烈不对称的，A 的价值不依赖"doc feels safe"的心理补偿。
