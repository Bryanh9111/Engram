"""Engram SQLite database initialization."""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    summary      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    origin       TEXT DEFAULT 'human',
    project      TEXT,
    path_scope   TEXT,
    tags         TEXT DEFAULT '[]',
    confidence   REAL DEFAULT 1.0,
    evidence_link TEXT,
    status       TEXT DEFAULT 'active',
    strength     REAL DEFAULT 0.5,
    pinned       INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    accessed_at  TEXT,
    last_verified TEXT,
    access_count INTEGER DEFAULT 0
);

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

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
