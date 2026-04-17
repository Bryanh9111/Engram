### Q1 — D (origin=compost + kind=insight 进主表)

D 让 agent 在单次 recall() 里用 `origin` 字段判断信任级别，无需跨表查询。C 方案的 `recall_insights` 独立工具会让 agent 在每次上下文窗口组装时多一次决策："我需要先调 recall，再调 recall_insights 吗？" — 这是 UX 层的认知税，而不是性能问题。补充 CHECK `origin != 'compost' OR kind = 'insight'` 后 trust boundary 可机器验证。

### Q2 — A (Compost 预拆，Engram 零 LLM write path)

用户写日记直接送 Compost，Compost 拆后写回 Engram — agent 行为路径最清晰：`engram add` 永远是 atomic claim，不存在"这条 note 是拆了还是没拆"的歧义状态。B 方案 Engram 写路径加 LLM 后，agent 提交长文如果 LLM 调用超时或失败，错误路径是：写了一半还是没写？原文丢了吗？回滚边界模糊。C/D 要求用户手拆，对非技术用户不友好，10 年后用户心智不会记得"note 可以长，event 必须短"。

### Q3 — A (scope=global)

Agent 在跨项目 recall 时只需要过滤 `scope='global'`，无需理解 `global` vs `insight` 的语义差别。5 年后新接手 Engram 的维护者看到 scope=insight 会问："这不是 kind 字段的职责吗？" — 语义混乱是长期维护税。Codex 也选 A，共识。

### Q4 — C (MCP + CLI 共用 handler)

Agent 走 MCP，人工调试走 CLI，错误路径对称：MCP 超时 → CLI 可手动验证输出是否正确，排查 handler 还是传输层问题。D 方案 SQL view 直连 DB 路径的错误路径最差：Compost 读到半写入的 WAL 数据时没有任何 Engram 层的错误处理，问题静默传播。

### Q5 — C (独立 section，而非默认排除)

B 方案 (默认排除) 的问题：agent 每次 recall() 后需要判断"我应该再调一次 include_compost=True 吗？" — 这在 prompt 里是额外的元认知步骤，容易被省略，导致 agent 永远看不到 compost insight，集成形同虚设。C 方案两段式输出让 agent 一次调用拿到全量，在 prompt 里天然区分信任来源，agent 可以用"--- compost insights ---" 这个文本锚定来决定是否采信。用户手工 recall 时也立刻可见"这条是 Compost 合成的"，不会困惑"我什么时候写过这个？"

注：若 recall 结果无 compost 条目则省略第二段，不增加 token 浪费。

### Q6 — D (过期隐藏 + 宽限期后 GC)

错误路径：如果 GC daemon 崩溃（A 方案的单点风险），C 方案（只隐藏）会让 DB 无限膨胀，10 年用户积累 90 天轮转 insight 后 SQLite 文件体积不可控。D 的分级方案：recall 读路径过滤 expired（响应即时），GC 窗口（宽限 N 天）兜底物理删除。`engram stats` 可单独统计 expired-but-not-gc 条目数，用户可感知存储健康。`engram lint` 对即将过期（< 7 天）的 compost insight 给 warning，让用户有机会 review 后 `resolve` 转人类记忆。

### Q7 — B (MCP tool invalidate_compost_fact)

错误路径最关键：A 方案 HTTP webhook 如果 Compost 端发出但 Engram 端 HTTP server 未启动（HC-1 独立性），invalidation 消息丢失，insight 变成 stale 幽灵。B 方案 Compost 主动调 MCP，失败有明确返回码，Compost 可以重试或记录失败；Engram 不需要维护 HTTP server 进程。D 只靠 TTL 的问题：fact 被改正后 insight 还会存活最多 90 天，agent 读到的是错误知识。

---

## 推荐组合
Q1=D Q2=A Q3=A Q4=C Q5=C Q6=D Q7=B

---

## Sonnet 独家风险

1. **Compost insight 信任污染 (Q5 核心)**: 若 recall 不区分来源段（采用 A 或 B 方案），agent 在 system prompt 里看到"你倾向 TDD"这种 insight 时无法区分是用户显式写入还是 Compost 推断 — agent 会以高置信度执行，而 Compost 推断可能基于过时 fact。两段式输出是唯一在 prompt 层做信任区隔的方案，不依赖 agent 自己检查 origin 字段（agent 通常不会）。

2. **Write 失败的错误路径不对称 (Q2)**: 若采用 B 方案（Engram LLM-on-write），用户写 3000 字日记，LLM 拆分到一半 rate limit — Engram 的 rollback 语义是什么？存原文还是存半拆结果？agent 下次 recall 时如果遇到既有 note 又有 event（同源），会重复提取相同信息。A 方案把拆分责任归 Compost 后，失败=Compost 重试，Engram 始终只收到完整 atomic claim，写路径无歧义状态。

3. **Cross-project insight 触发时机缺失 (Q3 延伸)**: scope=global 解决了存储问题，但 agent 在项目 A 做 recall 时默认 `scope='project'` 不会返回 global insight — 需要明确 proactive() 在文件打开时检查 cross-project guardrail 的触发条件，否则 global scope 的 insight 永远需要用户显式 `recall(scope='global')` 才能浮现，10 年后用户会忘记这个开关存在。建议 proactive() 无论当前 project 如何，始终 merge 一次 `scope='global' AND origin='compost'` 的 top-3，作为背景知识注入。
