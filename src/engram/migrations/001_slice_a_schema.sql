-- Migration 001 — Slice A: Schema Hardening
-- Debate 016/017/018 synthesis
-- Date: 2026-04-16
--
-- Changes:
--   1. memories: add scope enum + origin CHECK + length CHECK
--   2. Rebuild FTS5 after table swap
--   3. New table: recall_miss_log
--   4. New table: compost_cache (DDL only, data in v3.5)
--
-- CRITICAL: Run inside BEGIN IMMEDIATE ... COMMIT transaction
-- CRITICAL: Must rebuild FTS5 explicitly (external-content table)

BEGIN IMMEDIATE;

-- ============================================================
-- PHASE 1: Drop triggers so table swap doesn't cascade to FTS
-- ============================================================
DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;

-- ============================================================
-- PHASE 2: Create new table with CHECKs
-- ============================================================
CREATE TABLE memories_v2 (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL CHECK(length(content) <= 4000),
    summary       TEXT NOT NULL,
    kind          TEXT NOT NULL,
    origin        TEXT DEFAULT 'human' CHECK(origin IN ('human','agent')),
    project       TEXT,
    path_scope    TEXT,
    tags          TEXT DEFAULT '[]',
    confidence    REAL DEFAULT 1.0,
    evidence_link TEXT,
    status        TEXT DEFAULT 'active',
    strength      REAL DEFAULT 0.5,
    pinned        INTEGER DEFAULT 0,
    scope         TEXT NOT NULL DEFAULT 'project' CHECK(scope IN ('project','global','meta')),
    created_at    TEXT NOT NULL,
    accessed_at   TEXT,
    last_verified TEXT,
    access_count  INTEGER DEFAULT 0,
    CHECK(
        (scope = 'project' AND project IS NOT NULL)
        OR (scope IN ('global','meta') AND project IS NULL)
    )
);

-- ============================================================
-- PHASE 3: Migrate data (preserve rowid, infer scope)
-- Scope inference: project IS NULL → 'meta', else 'project'
-- User can manually re-scope to 'global' later via CLI.
-- ============================================================
INSERT INTO memories_v2 (
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, status, strength, pinned,
    scope,
    created_at, accessed_at, last_verified, access_count
)
SELECT
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, status, strength, pinned,
    CASE WHEN project IS NULL THEN 'meta' ELSE 'project' END AS scope,
    created_at, accessed_at, last_verified, access_count
FROM memories;

-- ============================================================
-- PHASE 4: Swap tables
-- ============================================================
DROP TABLE memories;
ALTER TABLE memories_v2 RENAME TO memories;

-- ============================================================
-- PHASE 5: Rebuild triggers (same as original)
-- ============================================================
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

-- ============================================================
-- PHASE 6: Rebuild FTS5 index (CRITICAL — external-content table)
-- Without this, FTS5 still points to old rowids even though they match.
-- Running rebuild is cheap insurance and required per SQLite docs.
-- ============================================================
INSERT INTO memories_fts(memories_fts) VALUES('rebuild');

-- ============================================================
-- PHASE 7: New table recall_miss_log (Slice A just creates, Slice C populates)
-- ============================================================
CREATE TABLE IF NOT EXISTS recall_miss_log (
    query_norm   TEXT NOT NULL,
    project      TEXT,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    hits         INTEGER NOT NULL DEFAULT 1,
    sample_query TEXT NOT NULL,
    PRIMARY KEY (query_norm, project)
);

-- ============================================================
-- PHASE 8: New table compost_cache (DDL only, data in v3.5)
-- Strict CHECK(origin='compiled') so this table cannot hold anything else.
-- ============================================================
CREATE TABLE IF NOT EXISTS compost_cache (
    cache_id        TEXT PRIMARY KEY,
    project         TEXT,
    prompt_hash     TEXT NOT NULL,
    source_hash     TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ttl_expires_at  TEXT NOT NULL,
    invalidated_at  TEXT,
    origin          TEXT NOT NULL DEFAULT 'compiled' CHECK(origin = 'compiled'),
    UNIQUE(project, prompt_hash)
);

CREATE INDEX IF NOT EXISTS idx_compost_cache_live
    ON compost_cache(project, ttl_expires_at)
    WHERE invalidated_at IS NULL;

COMMIT;

-- ============================================================
-- POST-COMMIT (run separately, not inside transaction)
-- Optional WAL checkpoint to compact journal after schema change:
-- PRAGMA wal_checkpoint(TRUNCATE);
-- ============================================================
