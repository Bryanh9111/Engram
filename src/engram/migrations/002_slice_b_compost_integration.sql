-- Migration 002 — Slice B Phase 1: Compost Integration Foundation
-- Debate 019 synthesis (2026-04-16)
-- Codex DDL accepted verbatim.
--
-- Changes:
--   1. memories.origin CHECK expanded to include 'compost'
--   2. memories gets source_trace (JSON) and expires_at columns
--   3. compost-specific CHECKs: origin=compost requires kind=insight,
--      source_trace NOT NULL, expires_at NOT NULL
--   4. New side table compost_insight_sources (memory_id, fact_id)
--   5. Partial index for live compost entries
--   6. memory_scores view adds TTL filter
--
-- CRITICAL: Run inside BEGIN IMMEDIATE ... COMMIT (debate 017 W2)
-- CRITICAL: Must rebuild FTS5 explicitly after table swap (debate 017 W1)

BEGIN IMMEDIATE;

-- ============================================================
-- PHASE 1: Drop dependent objects before table swap
-- ============================================================
DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;
DROP VIEW IF EXISTS memory_scores;

-- ============================================================
-- PHASE 2: Rebuild memories with compost insight support
-- Notes:
--   * Keep rowid because memories_fts uses content_rowid='rowid'
--   * source_trace stores contract payload JSON for provenance
--   * expires_at required for origin='compost' entries
--   * kind can be 'insight' (compost-only), see CHECK below
-- ============================================================
CREATE TABLE memories_v3 (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL CHECK(length(content) <= 4000),
    summary       TEXT NOT NULL,
    kind          TEXT NOT NULL,
    origin        TEXT DEFAULT 'human' CHECK(origin IN ('human','agent','compost')),
    project       TEXT,
    path_scope    TEXT,
    tags          TEXT DEFAULT '[]',
    confidence    REAL DEFAULT 1.0,
    evidence_link TEXT,
    source_trace  TEXT,
    status        TEXT DEFAULT 'active',
    strength      REAL DEFAULT 0.5,
    pinned        INTEGER DEFAULT 0,
    scope         TEXT NOT NULL DEFAULT 'project' CHECK(scope IN ('project','global','meta')),
    created_at    TEXT NOT NULL,
    accessed_at   TEXT,
    last_verified TEXT,
    expires_at    TEXT,
    access_count  INTEGER DEFAULT 0,
    CHECK(
        (scope = 'project' AND project IS NOT NULL)
        OR (scope IN ('global','meta') AND project IS NULL)
    ),
    CHECK(source_trace IS NULL OR json_valid(source_trace)),
    CHECK(expires_at IS NULL OR julianday(expires_at) IS NOT NULL),
    CHECK(origin != 'compost' OR kind = 'insight'),
    CHECK(origin != 'compost' OR source_trace IS NOT NULL),
    CHECK(origin != 'compost' OR expires_at IS NOT NULL)
);

-- ============================================================
-- PHASE 3: Copy data, preserve rowid for external-content FTS5
-- Existing rows are human/agent with no source_trace/expires_at.
-- ============================================================
INSERT INTO memories_v3 (
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, source_trace, status, strength, pinned, scope,
    created_at, accessed_at, last_verified, expires_at, access_count
)
SELECT
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, NULL, status, strength, pinned, scope,
    created_at, accessed_at, last_verified, NULL, access_count
FROM memories;

-- ============================================================
-- PHASE 4: Swap tables
-- ============================================================
DROP TABLE memories;
ALTER TABLE memories_v3 RENAME TO memories;

-- ============================================================
-- PHASE 5: Side table for O(log n) invalidation lookup
-- WITHOUT ROWID because PK is the access path.
-- ============================================================
CREATE TABLE IF NOT EXISTS compost_insight_sources (
    memory_id TEXT NOT NULL,
    fact_id   TEXT NOT NULL,
    PRIMARY KEY (memory_id, fact_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_compost_insight_sources_fact_id
    ON compost_insight_sources(fact_id);

-- Partial index for live compost entries (proactive/recall hot path)
CREATE INDEX IF NOT EXISTS idx_memories_compost_live
    ON memories(origin, status, expires_at)
    WHERE origin = 'compost' AND status = 'active';

-- ============================================================
-- PHASE 6: Recreate derived objects
-- memory_scores view excludes expired entries
-- ============================================================
CREATE VIEW memory_scores AS
SELECT id,
  CASE WHEN pinned = 1 THEN 10.0
  ELSE
    confidence
    * (1.0 + 0.1 * MIN(access_count, 20))
    * (1.0 / (1.0 + 0.02 * MAX(0, julianday('now') - julianday(COALESCE(accessed_at, created_at)))))
  END AS effective_score
FROM memories
WHERE status IN ('active', 'resolved')
  AND (expires_at IS NULL OR julianday(expires_at) > julianday('now'));

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

-- Cascade delete from side table when memory is deleted
CREATE TRIGGER memories_compost_map_ad AFTER DELETE ON memories BEGIN
    DELETE FROM compost_insight_sources WHERE memory_id = old.id;
END;

-- ============================================================
-- PHASE 7: Rebuild FTS5 index (MANDATORY for external-content)
-- Without this, searches against migrated rows silently miss.
-- ============================================================
INSERT INTO memories_fts(memories_fts) VALUES('rebuild');

COMMIT;

-- ============================================================
-- POST-COMMIT (run separately):
-- PRAGMA wal_checkpoint(TRUNCATE);
-- ============================================================
