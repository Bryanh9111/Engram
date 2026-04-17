# Non-Exposed Schema Fields

**Purpose**: Whitelist of `memories` table columns that are intentionally NOT exposed through public write surfaces (`MemoryStore.remember`, MCP `_handle_remember`, MCP `remember` tool, CLI `engram add`).

**Enforcer**: `tests/test_api_surface_coverage.py` — every non-whitelisted schema column MUST appear in all four write surfaces or the test fails.

**Invariant**: A new schema column is either user-settable (add to all four surfaces in the same PR) or computed-internal (add to this whitelist in the same PR). No third option.

## Whitelist

| Field | Why not exposed |
|-------|-----------------|
| `id` | Auto-generated in `MemoryObject.__post_init__` via `_generate_id()`. Callers cannot choose IDs. |
| `status` | Lifecycle state machine (`active` → `resolved`/`obsolete`). Managed through `forget`, `resolve` APIs, not `remember`. |
| `strength` | Recall-reinforcement counter. Starts at 0.5, bumped by `_strengthen` on dedup hit and decayed by consolidation. Never user-set. |
| `summary` | Auto-derived from `content` via `_make_summary` (first 200 chars). `MemoryStore.remember` accepts an override kwarg but the MCP/CLI surfaces do not, by design — if a caller wants a custom summary they should phrase `content` to carry it. |
| `created_at` | Wall-clock timestamp set at object construction. |
| `accessed_at` | Updated by `_touch` on every recall. |
| `last_verified` | Reserved for future re-verification workflow. Not set by any current code path. |
| `access_count` | Incremented by `_touch` on recall and `_strengthen` on dedup. |

## Rationale

- **Determinism** — Auto-derived fields (`id`, `summary`, `created_at`) keep identity stable across callers.
- **Lifecycle separation** — `status` has its own explicit verbs (`forget`, `resolve`) so users cannot smuggle state transitions through `remember`.
- **Effective-score integrity** — `strength`, `accessed_at`, `access_count` feed the `memory_scores` view. Letting callers set them would let a bad actor pin arbitrary memories to the top without using `pinned`.

## When to change this list

Adding a column:
- If the new column is user-settable (e.g., a new tag-like attribute), do NOT add it here — add it to all four surfaces.
- If the new column is computed-internal (e.g., another decay signal), add a row here AND cover it in the `_row_to_memory` roundtrip.

Removing a column:
- If a previously internal field becomes user-settable (e.g., explicit `last_verified` override), remove it here AND add to all four surfaces in the same PR.
