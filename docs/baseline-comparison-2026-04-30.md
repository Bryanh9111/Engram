# Memory-Shape Baseline Comparison

> **Status**: Reading-only design reference, 2026-04-30
> **Source**: `Personal/Research-and-Integration/agent-memory/ATM-Bench/third_party/{A-mem,HippoRAG,mem0,MemoryOS}`
> **Purpose**: Verify whether Engram's memory shape is missing concepts that the four ATM-Bench-ported baselines treat as load-bearing. Outcome must be one of: (a) confirm Engram already covers, (b) record an idea worth tracking for a future trigger, (c) explicitly reject and note why.
>
> **Not in scope**: integrating any of these as runtime dependencies (per ARCHITECTURE.md HC-1 + HC-2 and the 2026-04-30 integration debate, Engram does not adopt ATM-Bench as a roadmap item).

---

## Reference summary

| Project | Core idea | Storage shape |
|---|---|---|
| A-Mem | Agentic memory, Zettelkasten-inspired notes; LLM generates structured attributes + contextual descriptions + links on each write | Memory note with attributes, tags, contextual description; LLM-driven dynamic linking and evolution |
| HippoRAG 2 | Neurobiologically-inspired graph memory for multi-hop retrieval and continual learning; offline graph index + online retrieval | Knowledge graph over passages; entity/relation triples; non-parametric — no model fine-tune |
| mem0 | Multi-level state (User / Session / Agent); production memory layer with +26% accuracy / 91% faster / 90% fewer tokens vs OpenAI memory on LOCOMO | Multi-level state model with adaptive personalization; pluggable vector stores |
| MemoryOS | OS-style hierarchical short/mid/long-term storage with four modules (Storage / Updating / Retrieval / Generation); persona-aware | Tiered storage; pluggable engines; MCP server with 4 module abstractions |

---

## Concept-by-concept comparison vs Engram

Engram's frozen surface (per ARCHITECTURE.md): 6 kinds × 3 origins × 3 scopes × confidence × strength × pinned × accessed_at × access_count × expires_at × source_trace × status × tags × project × path_scope × content (≤4000 chars).

| Concept | A-Mem | HippoRAG 2 | mem0 | MemoryOS | Engram coverage | Verdict |
|---|---|---|---|---|---|---|
| Atomic-claim shape | Notes (multi-attribute) | Triples + passages | Multi-level state objects | Tiered records | ✅ `kind` enum × `content ≤ 4000` × source_trace | covered |
| Provenance / source_trace | Implicit (LLM-derived) | Passage IDs in graph | Optional metadata | Metadata fields | ✅ mandatory for `origin=compost`; tags + project elsewhere | covered |
| Decay / lifecycle | "Continuous evolution" (LLM rewrites) | None first-class | Adaptive update | "Updating" module | ✅ `expires_at` + `forget()` + `status` lifecycle; **Engram explicitly forbids background rewrite** (Never-Do List #4) | covered, divergent by design |
| Strength / reinforcement | Implicit via re-link | Implicit via graph edges | Implicit via update | Mid→long-term promotion | ✅ `strength` + `accessed_at` + `access_count`; `_strengthen` only mutates these | covered |
| Confidence / trust tier | LLM-judged | Retrieval score | Retrieval score | Module-internal | ✅ `confidence` + `origin` trust tier (human > agent > compost) | covered |
| Scope / project boundary | None | None | User/Session/Agent levels | Persona | ✅ `scope` (project / global / meta) + `project` + `path_scope` | covered (mem0's User/Session level differs but maps loosely to scope) |
| Multi-hop / cross-fact reasoning | Agentic links between notes | Graph traversal (core) | Vector retrieval | Hierarchical retrieval | ❌ Engram is single-path FTS5; **explicitly defers** to Compost (HC-3) | covered by Compost, not Engram |
| Hierarchical short/mid/long-term tiering | None | None | Multi-level state | Yes (core) | ❌ Engram does not tier by recency in storage | trigger candidate (only if recall miss rate increases past threshold) |
| LLM-on-write enrichment (auto-tagging, attribute extraction) | Yes (core) | Yes (graph build) | Yes | Yes | ⚠️ Engram allows LLM on write path (v4 compile triggered at 553 memories) but recall stays zero-LLM (HC-2). Currently no LLM-on-write shipped | trigger candidate (v4 compile already triggered, scope under re-evaluation per Compost Slice B partial supersession) |
| Multimodal (images / videos / emails) | Optional | Text-only | Optional | Optional | ❌ Engram is text-only with 4000 char cap | rejected — not Engram's anchor (personal memory library text first; multimodal is Compost / external) |
| Ranking explainability | Opaque (LLM judgment) | Opaque (graph score) | Opaque | Opaque | ✅ Engram requires every score computable from visible columns; `pinned` short-circuits to 10.0 | covered, **divergent on principle** (Never-Do List #3 forbids opaque ranking) |
| Graph / fact_links | Note links | Knowledge graph (core) | None first-class | Module-internal | ⚠️ Compost has `fact_links` table; Engram has no graph storage | covered by Compost, not Engram |
| Insight / synthesis derivation | Implicit (LLM rewrites) | Built into graph | Implicit | "Generation" module | ✅ `kind=insight` with `origin=compost` + `source_trace` + mandatory `expires_at` | covered |
| Cross-write deduplication | LLM-based merge | None | Update overwrites | Module-internal | ✅ Compost-insight `(root_insight_id, chunk_index)` UNIQUE; PUT semantics return existing id | covered |
| Personalization / user model | None | None | User-level state | Persona memory | ❌ Engram has no user-model layer | covered upstream by Compost Phase 5 user-model schema (migration 0015 user_patterns) |
| Multi-LLM provider abstraction | Per-provider | OpenAI / HF | Many | OpenAI / Deepseek / Qwen | N/A — Engram has no LLM provider | not applicable (HC-2 zero-LLM hot path) |

---

## Findings

### A — Covered without changes

Engram already encodes the load-bearing shape concepts: atomic claims, provenance, decay (`expires_at` + `forget()`), reinforcement (`strength` + `_strengthen`), confidence ladder, trust tier by origin, project / scope boundary, insight kind with mandatory source_trace, dedup PUT semantics, and explainable ranking. Across all four baselines no field maps to an Engram gap that has not been intentionally rejected.

### B — Trigger candidates (do not build now)

1. **Hierarchical short/mid/long-term tiering** (MemoryOS pattern, mem0's User/Session/Agent levels): Engram has no recency tier. Activate the existing `Phase 3 — recall/proactive tiering` roadmap row only when the existing trigger fires (`>10 compost entries in production` — currently 0).
2. **LLM-on-write enrichment** (A-Mem / mem0 / MemoryOS pattern): Engram's `v4 LLM compile` trigger already fired (553 memories). The roadmap row is annotated *"re-evaluate scope: partially superseded by Compost Slice B"*. The baseline reading reinforces that re-evaluation: any LLM-on-write feature in Engram should be additive to atomic claims (not rewriting them), and should rely on Compost for the synthesis surface rather than duplicating it.

### C — Explicitly rejected (record-and-move-on)

1. **Multimodal first-class** — out of Engram's anchor (personal memory library, text-first; multimodal handled by Compost adapters or external tools).
2. **Opaque LLM-judged ranking / agentic relinking that mutates content** — directly violates Never-Do List #3 (no opaque ranking) and #4 (no background rewriting). All four baselines do this; Engram intentionally does not.
3. **Multi-hop / graph-based retrieval inside Engram** — explicitly delegated to Compost via HC-3 (Compost owns synthesis). Compost already ships `fact_links` (P0-0) + recursive CTE traversal + `v_graph_health`.
4. **User model / persona inside Engram** — Compost Phase 5 already shipped `user_patterns` schema (migration 0015). Engram remains the working-memory layer.

---

## Conclusion

Engram's memory shape is consistent with the state of the art represented by these four baselines, **with a deliberately stricter posture on rewrite-discipline, rank-explainability, and zero-LLM hot path**. No design gap requires action today.

If a future trigger fires (recall miss rate, tiering threshold, or LLM-compile re-evaluation), revisit:
- MemoryOS hierarchical-storage module split as the reference for tiering ergonomics
- A-Mem's "structured attributes generated on write" as an LLM-on-write input shape, not as a content-rewrite mechanism

No follow-up work scheduled. Closes the 2026-04-30 reading-only reference task.

---

## Cross-references

- ARCHITECTURE.md §2 (Hard Constraints HC-1 / HC-2) — independence and zero-LLM recall
- ARCHITECTURE.md §11 (Roadmap) — trigger-based phase activation
- Engram pinned decision `2b2955d569a6` (2026-04-30) — Engram does not integrate ATM-Bench as a roadmap item
- Compost migration 0015 — `user_patterns` schema covering personalization layer
