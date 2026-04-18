# Engram Architecture

> Canonical reference for Engram's structure, hard constraints, and integration
> contracts. Written for (a) future-me reading this after six months away,
> (b) external integrators (Compost today, others later) that need our guarantees.
>
> If this document drifts from the code, the code is authoritative — but file
> an issue. Drift should fail CI, not just be discovered by reviewers.

**Version**: v3.4 Slice B Phase 2 S2 complete
**Last commit at write**: `0416823`
**Tests at write**: 223/223 passing

---

## 1. Identity & Scope

Engram is a persistent, zero-LLM memory store for AI coding agents. It runs
local-first on SQLite + FTS5 and exposes operations through:

- **MCP server** (FastMCP, 14 tools) — the canonical agent-facing surface
- **CLI** (`engram …`, 10 subcommands) — the same operations for humans and scripts
- **Python API** (`MemoryStore`) — the underlying implementation

Engram is **not** a chatbot memory, a vector store, a knowledge base, or a
sync server. It is a queryable brain whose contract is: *memories enter
context as atomic claims with provenance, and retrieval cost stays constant
regardless of memory count.*

**Strategic anchor** (pinned memory `c266b5d41250`): Engram is the user's
entire personal memory library — workflow today, broader life domains later.
Not a business product.

---

## 2. Hard Constraints (HC-1 / HC-2)

These are the load-bearing invariants. Every design decision must preserve
both. Attempts to violate them require a debate-level revisit.

### HC-1 — Independence survives

Engram must run fully without Compost installed. Compost must run fully
without Engram installed. Either side crashing or being uninstalled must not
degrade the other's availability.

**Enforcement**: `tests/test_architecture_invariants.py::TestNoCompostImport`
greps the entire `src/engram/` tree for `compost` imports; any direct
Python-level coupling fails CI.

### HC-2 — Engram recall is zero-LLM

The hot path injected before every LLM call (recall, proactive, micro_index,
health) must never invoke an LLM. Retrieval is deterministic FTS5/SQLite.

LLM usage may eventually appear on the *write* path (v4 compile) but the
runtime recall remains deterministic.

**Enforcement**: `TestNoLLMInCore` scans `src/engram/**.py` for imports of
`anthropic`, `openai`, `google.generativeai`, `google.genai`, `cohere`,
`litellm`; any match fails CI.

### Never-Do List (GPT-5.4 derived, permanent)

1. **No silent auto-delete** — memories only transition to `obsolete` via
   explicit `forget()` / `invalidate_compost_fact()` / schema expiry.
2. **No blob memories / wiki dumps** — `length(content) <= 4000`
   schema CHECK; atomic claims only.
3. **No opaque ranking** — every recall score is computable from visible
   columns (see §9). `pinned` short-circuits to 10.0 for auditability.
4. **No background rewriting** — no process modifies `content` after write.
   `_strengthen` only bumps `strength` / `accessed_at` / `access_count`.

---

## 3. Memory Model

### 3.1 Kinds (6)

| Kind | Lifetime | Example |
|------|----------|---------|
| `constraint` | Semi-permanent | "Money values use integer cents end-to-end" |
| `decision` | Until revisited | "Use polling not websockets" |
| `procedure` | Version-controlled | "Seed Redis, then worker, then API" |
| `fact` | Short-lived | "UserSearchV2 behind SEARCH_V2=1" |
| `guardrail` | Incident-driven | "Never parallelize migration 0042/0043" |
| `insight` | Compost synthesis (reserved) | Cross-project pattern from Compost |

`insight` is locked to `origin=compost` by schema CHECK.

### 3.2 Origins (3)

| Origin | Trust | Proactive | Stream Exported |
|--------|-------|-----------|-----------------|
| `human` | Highest | Yes | Yes |
| `agent` | Medium | Yes | Yes |
| `compost` | Reference | **No** | **Excluded by default** (feedback-loop prevention) |

The `compiled` origin existed in early designs but was removed in v3.4 P0
after debate 018 moved LLM-synthesized content to `compost_cache` (its own
table with its own CHECK). Enum drift prevention:
`TestEnumSchemaAlignment` + `TestMCPDocStringAlignment`.

### 3.3 Scopes (3)

| Scope | Requires | Use case |
|-------|----------|----------|
| `project` | project NOT NULL | The common case — work in one project |
| `global` | project IS NULL | Cross-project knowledge (Compost insights land here) |
| `meta` | project IS NULL | About the user or agent, not any project |

Schema CHECK: `(scope='project' AND project NOT NULL) OR (scope IN ('global','meta') AND project IS NULL)`.

### 3.4 Status Lifecycle

```
active ──forget──▶ obsolete
  │
  ├──resolve──▶ resolved (still searchable, but no proactive push)
  │
  └──invalidate_compost_fact──▶ obsolete (for compost-origin insights)

suspect — reserved, not populated by any current code path
```

`obsolete` never re-transitions.

---

## 4. Trust Boundary

The core invariant: **`origin` partitions memories by trust, and downstream
surfaces respect that partition uniformly**.

### 4.1 Origin → Retrieval policy

| Surface | Returns origin=human | Returns origin=agent | Returns origin=compost |
|---------|---------------------|---------------------|-----------------------|
| `recall()` | Yes | Yes | Yes (ranking-mixed) |
| `proactive()` | Yes | Yes | **No** (insight ≠ actionable guardrail) |
| `stream_for_compost()` | Yes | Yes | **No by default** (Q7 feedback loop) |
| `compile()` markdown | Yes | Yes | Yes |
| `health` lint | Yes (all kinds) | Yes | Yes |

### 4.2 Compost authority over insights (pinned decision)

`invalidate_compost_fact(fact_ids)` **ignores pinned state**.
Rationale (pinned memory `83bf757a3709`):

- Compost is the sole authority on whether an insight's upstream fact still
  holds. Users cannot independently verify insight freshness — they see a
  summary, not the underlying cross-project observations.
- A pinned stale insight is *more* dangerous than an unpinned stale insight,
  because `pinned=1` promotes it to `effective_score=10.0` in recall.
- `forget()` has a pinned guard (prevents human accident). `invalidate_compost_fact`
  does not (Compost is not a human).

To dispute an invalidation, re-write the content as `origin=human` under a
non-insight kind. The audit trail lives in `ops_log`.

**Enforcement**: `tests/test_invalidate_compost_fact.py::TestPinnedHandling::test_pinned_insight_still_invalidated`.

---

## 5. Append-Only Content Discipline

Memory `content` is immutable post-write. No code path updates it. The only
write-side mutations are:

- `_strengthen` on dedupe hit: bumps `strength`, `accessed_at`, `access_count`
- `_touch` on recall: updates `accessed_at`, `access_count`
- `status` transitions: `active` → `resolved` / `obsolete`
- `pinned` toggle via `unpin()` (never via `remember()` of the same content)

**Why it matters for integrations**: Compost's re-ingestion contract uses
`(memory_id, updated_at)` as the dedupe key. Because content never mutates,
`stream_for_compost` reports `updated_at = created_at`. If a future edit
API ever lands, three places change in lockstep:

1. Schema: add `updated_at` column + trigger
2. `server._memory_to_compost_dict`: return real `updated_at`
3. Notify Compost: re-ingestion semantics change

Pinned memory: `9d51ee6a8bfd`.

---

## 6. API Surface Discipline

Any new column added to the `memories` table **must** take one of two paths:

### (a) Exposed to all four write surfaces

- `MemoryStore.remember(..., new_field=...)`
- `server._handle_remember(..., new_field=...)`
- MCP `remember` tool signature
- CLI `engram add --new-field`

### (b) Computed-internal whitelist

Added to `docs/non-exposed-schema-fields.md` with a justification.

Third option: **does not exist**.

**Enforcement**: `tests/test_api_surface_coverage.py` — seven invariants that
iterate the schema, subtract the whitelist, and assert every surface covers
the user-settable set. PR merging a new column without touching all four
surfaces or the whitelist doc fails CI.

**Sibling invariant**: `TestEnumSchemaAlignment` does the same for enum
values vs DB CHECK clauses. Drift in either direction (enum value DB
rejects, or DB value enum lacks) fails CI.

Pinned memory: `e5749c50c84c`.

---

## 7. Compost Bidirectional Channel (v3.4 Slice B)

Contract: `/Users/zion/Repos/Zylo/Compost/docs/engram-integration-contract.md`
Debate resolving design questions: `debates/019-compost-integration-implementation/synthesis.md`

### 7.1 Engram → Compost (event source)

**MCP tool**: `stream_for_compost(since?, kinds?, project?, include_compost=False, limit=1000)`
**CLI**: `engram export-stream --since --kinds --project --include-compost --limit`

Contract shape (9 keys, exact):
```
{
  memory_id, kind, content, project, scope,
  created_at, updated_at, tags, origin
}
```

Semantics:
- `memory_id` renamed from `id` (contract convention)
- `updated_at = created_at` (§5, append-only)
- `origin=compost` excluded by default (feedback-loop prevention per debate 019 Q7)
- `limit` caps MCP transport at 1000; Compost polls in rounds

Schema obligations for writes with `origin=compost`:
- `kind = 'insight'` (CHECK)
- `source_trace` IS NOT NULL, valid JSON (CHECK × 2)
- `expires_at` IS NOT NULL (CHECK) — TTL required

### 7.2 Compost → Engram (invalidation)

**MCP tool**: `invalidate_compost_fact(fact_ids: list[str]) → {invalidated_memory_ids, count}`

Implementation:
1. Reverse-lookup `compost_insight_sources(memory_id, fact_id)` where `fact_id IN (?)`
2. Soft-delete matching memories (status → obsolete)
3. Audit each affected `memory_id` in `ops_log` with op='invalidate_compost_fact'
4. Ignore `pinned` status (§4.2)

Physical purge with 30-day grace is a Phase 3 GC daemon concern — not yet
implemented (trigger: first expired compost entry observed; currently 0).

### 7.3 Automatic source indexing

`remember(kind='insight', source_trace={'compost_fact_ids': [...]})` triggers
`_map_insight_sources` which populates `compost_insight_sources` with one
row per `fact_id`. `INSERT OR IGNORE` handles dedupe via content similarity
path. Cascading delete via `memories_compost_map_ad` trigger.

Non-insight kinds **never** write the map, even if `source_trace`
coincidentally carries `compost_fact_ids`.

Pinned memory: `4927125bb2d7`.

---

## 8. Expiry Filter Coverage

Every read path that surfaces memories into an agent's context (or into a
human-facing compile) must exclude entries past `expires_at`. Discovered gap
via debate 020 — fixed in commit `0416823`.

| Path | Filters expiry? | Notes |
|------|-----------------|-------|
| `recall()` FTS / recent | Yes | Explicit WHERE clause |
| `stream_entries()` / `stream_for_compost` | Yes | Explicit |
| `proactive()` | Yes | Explicit |
| `consolidate_candidates()` | Yes | Explicit |
| `compile()` | Yes | Explicit — no stale in human Markdown |
| `micro_index()` | Yes | Active counts exclude expired |
| `stats()` | Yes | Active counts exclude expired |
| `export()` | **No, by design** | Lossless backup must capture everything |
| `health()` | **No, by design** | It is the thing that reports expired as a problem |

Helper: `store._NOT_EXPIRED_SQL` constant, reused across queries.

**Enforcement**: `tests/test_expiry_coverage.py` — 8 regression tests, one
per filtering path. Raw-insert an expired entry, assert it does not surface.

---

## 9. Ranking (`effective_score`)

```
score = confidence × (1 + 0.1 × min(access_count, 20))
              × (1 / (1 + 0.02 × days_since_access))
pinned = 10.0   # short-circuits everything
```

Defined as a SQL view `memory_scores` (see `db.py`), so ranking is
inspectable by SELECT and auditable from CLI. No Python-side re-ranking
black box.

Budgets:
- `tiny` → `_to_card` projection (~50 tok each)
- `normal` → full `MemoryObject` dicts (default)
- `deep` → `limit = max(limit, 50)`, full dicts

---

## 10. CI-Enforced Invariants (index)

| Invariant | Enforcer |
|-----------|----------|
| Zero LLM SDK in core | `test_architecture_invariants.py::TestNoLLMInCore` |
| Zero Compost imports | `...::TestNoCompostImport` |
| Schema has scope/origin/length CHECKs | `...::TestSchemaInvariants` |
| Compost origin triad CHECK (kind=insight + source_trace + expires_at) | `...::TestSchemaInvariants` (5 tests) |
| `compost_cache` only accepts `origin=compiled` | `...::TestSchemaInvariants` |
| `memories` rejects `origin=compiled` | `...::TestSchemaInvariants` + `test_proactive.py::test_compiled_origin_rejected_by_schema` |
| Enum values = DB CHECK values | `...::TestEnumSchemaAlignment` |
| MCP docstrings reference only live origins | `...::TestMCPDocStringAlignment` |
| Four write surfaces cover user-settable columns | `test_api_surface_coverage.py` (7 tests) |
| `invalidate_compost_fact` ignores pinned | `test_invalidate_compost_fact.py::TestPinnedHandling` |
| Expiry filter on hot read paths | `test_expiry_coverage.py` (8 tests) |
| Feedback-loop exclusion of `origin=compost` from stream | `test_stream_entries.py::TestStreamEntriesFeedbackLoopPrevention` |
| No embedding column until v3.5+ re-evaluation | `...::TestNoEmbeddingColumn` |
| WAL + busy_timeout + raised cache_size PRAGMAs set | `...::TestPragmaConfiguration` (4 tests, debate 016 Codex I3) |

Current total: 227 tests across 13 test files.

---

## 11. Roadmap

| Phase | Trigger | Status |
|-------|---------|--------|
| v3.1 — memory lint + Claude Code hooks | — | done |
| v3.2 — real token measurements + health summary mode | — | done |
| v3.3 Slice A — schema hardening + unpin + scope tri-value | — | done (migration 001) |
| v3.4 Slice B Phase 1 — Compost schema foundation | — | done (migration 002) |
| v3.4 Slice B Phase 2 P0 — API surface invariant + enum realignment | — | done |
| v3.4 Slice B Phase 2 S2 — Compost bidirectional channel runtime | — | **done (current)** |
| Phase 3 — recall/proactive tiering | >10 compost entries in production | deferred (0 today) |
| Phase 3 — GC daemon (30-day grace physical purge) | first expired compost entry observed | deferred (0 today) |
| Phase 3 — extended `engram lint` (expired-still-active, orphan definition TBD) | any time | queued |
| Phase 3 — ARCHITECTURE.md | any time | **this file** |
| v4 — LLM compile with Planner→Worker→Critic | 500 memories | future |
| v4.1 — Temporal expiry (degrade, not hide) | time-sensitive > 10% | future |
| v5 — Multi-path recall + LLM rerank | >5 FTS5 miss cases | future |
| v6 — Embedding (sqlite-vec) + RRF fusion | 2000 memories | future |
| v7 — Memory graph + Dream agent | 3000 memories | future |

Data-driven triggers are load-bearing: speculative building before the
trigger violates the "NO opaque ranking" and Linus yagni principles.

---

## 12. Further Reading

- `README.md` — user-facing install, usage, FAQ
- `CLAUDE.md` — agent-facing project instructions (project structure, commands, disciplines)
- `docs/non-exposed-schema-fields.md` — computed-internal whitelist
- `docs/v3.3-migration-plan.md` — Slice A background
- `debates/019-compost-integration-implementation/synthesis.md` — integration design decisions
- `debates/020-phase3-priority/synthesis.md` — this doc's own origin story
- Pinned self-memories (recall against `project=engram`): `c266b5d41250`, `3c42d31657e6`, `a167bc678f53`, `e5749c50c84c`, `9d51ee6a8bfd`, `4927125bb2d7`, `83bf757a3709`, `1470755c0126`, plus the latest handover

When this file drifts from the code, add an invariant test and delete the
stale section. That's the only way docs stay honest.
