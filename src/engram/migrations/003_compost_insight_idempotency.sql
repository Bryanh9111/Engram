-- Migration 003 — Compost insight idempotency
-- Debate 024 synthesis (2026-04-23)
--
-- Why: dogfood 2026-04-23 found 4 rows where 2 should be. Same root_insight_id
-- pushed twice yielded 4 chunks (= 2 pushes × 2 chunks). Compost-side
-- computeRootInsightId is deterministic UUIDv5 over (project + sorted fact_ids),
-- but Engram never enforced uniqueness on (root_insight_id, chunk_index).
--
-- Changes (purely additive, no table rebuild):
--   1. PHASE 1 — clean historical duplicates: keep MIN(created_at) per
--      (root_insight_id, chunk_index); delete the rest. Cascade to
--      compost_insight_sources via existing AFTER DELETE trigger
--      (002:142-144).
--   2. PHASE 2 — partial UNIQUE INDEX on the structural key. WHERE clause
--      includes json_type checks so malformed source_trace (missing fields)
--      are NOT covered by UNIQUE — a tradeoff: enforces idempotency for
--      well-formed compost writes (which is everything from
--      compost-engram-adapter, since splitter.ts:54-65 always sets both
--      fields), accepts that pathological clients could bypass. CHECK on
--      json_type would require table rebuild (SQLite lacks ALTER ADD CHECK)
--      and is deferred until proven necessary.
--
-- CRITICAL: db.py _SCHEMA must include the same UNIQUE INDEX (kept in sync
-- so fresh installs get it).

BEGIN IMMEDIATE;

-- =================================================================
-- PHASE 1: Delete historical duplicates
-- Keep earliest (created_at min) per (root_insight_id, chunk_index)
-- Delete the rest. Trigger memories_compost_map_ad cascades to
-- compost_insight_sources.
-- =================================================================
DELETE FROM memories
WHERE origin = 'compost'
  AND id NOT IN (
    SELECT id FROM (
      SELECT
        id,
        ROW_NUMBER() OVER (
          PARTITION BY
            json_extract(source_trace, '$.root_insight_id'),
            json_extract(source_trace, '$.chunk_index')
          ORDER BY created_at ASC, id ASC
        ) AS rn
      FROM memories
      WHERE origin = 'compost'
        AND json_extract(source_trace, '$.root_insight_id') IS NOT NULL
        AND json_extract(source_trace, '$.chunk_index') IS NOT NULL
    )
    WHERE rn = 1
  )
  AND json_extract(source_trace, '$.root_insight_id') IS NOT NULL
  AND json_extract(source_trace, '$.chunk_index') IS NOT NULL;

-- =================================================================
-- PHASE 2: Partial UNIQUE INDEX on structural key
-- =================================================================
CREATE UNIQUE INDEX IF NOT EXISTS idx_compost_insight_idempotency
ON memories(
  json_extract(source_trace, '$.root_insight_id'),
  json_extract(source_trace, '$.chunk_index')
)
WHERE origin = 'compost'
  AND json_type(source_trace, '$.root_insight_id') = 'text'
  AND json_type(source_trace, '$.chunk_index')     = 'integer';

COMMIT;

-- =================================================================
-- POST-COMMIT (run separately if needed):
-- PRAGMA wal_checkpoint(TRUNCATE);
-- =================================================================
