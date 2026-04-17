"""Engram SQLite database initialization."""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
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

CREATE TABLE IF NOT EXISTS compost_insight_sources (
    memory_id TEXT NOT NULL,
    fact_id   TEXT NOT NULL,
    PRIMARY KEY (memory_id, fact_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_compost_insight_sources_fact_id
    ON compost_insight_sources(fact_id);

CREATE INDEX IF NOT EXISTS idx_memories_compost_live
    ON memories(origin, status, expires_at)
    WHERE origin = 'compost' AND status = 'active';

CREATE TABLE IF NOT EXISTS recall_miss_log (
    query_norm   TEXT NOT NULL,
    project      TEXT,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    hits         INTEGER NOT NULL DEFAULT 1,
    sample_query TEXT NOT NULL,
    PRIMARY KEY (query_norm, project)
);

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

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    summary,
    tags,
    content='memories',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
END;

CREATE TABLE IF NOT EXISTS ops_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    op        TEXT NOT NULL,
    memory_id TEXT,
    kind      TEXT,
    project   TEXT,
    ts        TEXT NOT NULL,
    detail    TEXT
);

CREATE VIEW IF NOT EXISTS memory_scores AS
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

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_compost_map_ad AFTER DELETE ON memories BEGIN
    DELETE FROM compost_insight_sources WHERE memory_id = old.id;
END;
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
