# Claude (Opus) — Round 1 Analysis

## Recommended Order: A → (wait) → C → B → D

Concrete time estimate: A ≈ 0.5d. Everything else: postpone.

## Per-candidate ROI

### A — ARCHITECTURE.md

**Cost**: ~0.5d. User's estimate is roughly right IF we shoehorn from existing pinned memories (`e5749c50c84c` / `9d51ee6a8bfd` / `4927125bb2d7` / `83bf757a3709` / `a167bc678f53` / `c266b5d41250`). It becomes 1-1.5d if we try to write it from scratch.

**Value**: High, time-sensitive:
- Compost's Phase 5 adapter is being built **now**. They need to know our hard constraints (HC-1/2, trust boundary, origin invariants) before making their own design decisions. Every day without ARCHITECTURE.md = risk of Compost building against assumptions that don't match reality.
- The act of writing forces us to re-check that the pinned memories are consistent (debate 019 / contract / code). Finding drift here is cheap; finding drift from Compost's integration later is expensive.
- Public-facing: first repo visitor sees README, then ARCHITECTURE.md. Open-source credibility anchor.

**ROI**: Unbeatable. Half-day for permanent reference + derisking active parallel integration.

### B — engram lint 扩展

**Cost**: ~1d, but the value floor is very low right now.

**Problem**: Schema CHECK already enforces the invariants (origin=compost requires source_trace + expires_at + kind=insight). Lint would catch precisely the memories that **cannot exist in the first place**. Orphans in `compost_insight_sources` can't exist without a memory_id (trigger cascades on delete). The only real check with teeth is "expired compost entries still status=active" — but that's GC's job (candidate D), not lint's.

**ROI**: Low. Mostly defense-in-depth theater. Would feel productive without being productive.

### C — recall/proactive 分层

**Correct to defer**. Zero compost entries means zero evidence that ranking theater is needed. Building now = `opaque ranking` accusation if we guess wrong.

### D — GC daemon

**Correct to defer**. 30-day grace means the first expired entry is at least 30 days after first compost write, and we have zero compost writes. Months of runway.

## 5th Option the User Missed

**E — Compost session 实际 dogfood**. Don't build more; go write a real Compost Phase 5 adapter call and observe the 9-key contract in action end-to-end across sessions. This is data-triggered development in its purest form: you don't design v4.1 / v5 / v6 speculatively, and likewise shouldn't design Phase 3 cleanup tooling without data.

The alternative framing: **let Compost be the forcing function**. If Phase 5 lands, we'll discover what lint rules actually matter (not what we guess at). If it doesn't land soon, Phase 3 is moot.

## Solo Dev vs Team Tradeoff

For **solo dev**: ARCHITECTURE.md is a note-to-self for future-you + a contract with Compost session (also future-you). Lint is speculative maintenance. Priority: A → wait.

For **team**: Reverse. Team has parallel capacity, lint-as-guardrail prevents one person's schema surprise breaking another's integration, ARCHITECTURE.md risks being a living document nobody maintains. Priority: B + A in parallel.

User is solo. Do A. Wait for data. Don't confuse "feeling productive" with "producing value".

## Self-Check on User's Bias

User worried they're rationalizing A because "doc work feels safe". Answer: **They're not.** The evidence:

1. Compost's Phase 5 is a real, named, time-bound external consumer. That's the opposite of speculative.
2. B has concrete failure to articulate value ("defense-in-depth" is the tell — schema already enforces).
3. A compounds (reference used by multiple future work); B only activates when Compost entries exist.

If the user were rationalizing, the evidence for A would be weaker. It's not.
