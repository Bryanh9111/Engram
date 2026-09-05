"""Rebuildable, transactionally maintained Han bigram search projection."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_HAN_RUN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af]{2,}")


def cjk_query(text: str) -> str | None:
    """Quoted bigram phrases require contiguous matches, including two-Han words."""
    phrases = []
    for run in dict.fromkeys(_HAN_RUN.findall(text)):
        terms = [run[i : i + 2].encode("utf-8").hex() for i in range(len(run) - 1)]
        phrases.append('"' + " ".join(terms) + '"')
    return " OR ".join(phrases) or None


def ensure_indexes(conn: sqlite3.Connection) -> None:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='search_index_state'"
    ).fetchone():
        return
    sql = (Path(__file__).parent / "migrations/004_search_indexes.sql").read_text()
    # executescript commits any prior transaction; init_db calls us after schema init.
    # Recheck under the write lock so simultaneous first starts cannot double-apply.
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='search_index_state'"
        ).fetchone():
            statement = ""
            for line in sql.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ""
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def rebuild_indexes(conn: sqlite3.Connection) -> dict:
    with conn:
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        conn.execute("DELETE FROM memories_cjk")
        conn.execute(
            "INSERT INTO memories_cjk(rowid,grams) SELECT rowid,grams FROM memories_cjk_source"
        )
        conn.execute(
            "UPDATE search_index_state SET indexed_revision=source_revision, rebuilt_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        )
        conn.execute(
            "INSERT INTO memories_fts(memories_fts,rank) VALUES('integrity-check',1)"
        )
        conn.execute("INSERT INTO memories_cjk(memories_cjk) VALUES('integrity-check')")
    return index_status(conn)


def index_status(conn: sqlite3.Connection) -> dict:
    conn.execute("SAVEPOINT search_status")
    try:
        return _index_status(conn)
    finally:
        conn.execute("ROLLBACK TO search_status")
        conn.execute("RELEASE search_status")


def _index_status(conn: sqlite3.Connection) -> dict:
    state = conn.execute(
        "SELECT version,source_revision,indexed_revision,indexed_at,rebuilt_at FROM search_index_state WHERE name=?",
        ("memories",),
    ).fetchone()
    missing = conn.execute(
        "SELECT count(*) FROM memories_cjk_source s LEFT JOIN memories_cjk i ON i.rowid=s.rowid WHERE i.rowid IS NULL OR i.grams != s.grams"
    ).fetchone()[0]
    orphan = conn.execute(
        "SELECT count(*) FROM memories_cjk i LEFT JOIN memories m ON m.rowid=i.rowid WHERE m.rowid IS NULL"
    ).fetchone()[0]
    error = None
    try:
        conn.execute(
            "INSERT INTO memories_fts(memories_fts,rank) VALUES('integrity-check',1)"
        )
        conn.execute("INSERT INTO memories_cjk(memories_cjk) VALUES('integrity-check')")
    except sqlite3.DatabaseError as exc:
        error = str(exc)
    return {
        "error": error,
        "ok": error is None and missing == 0 and orphan == 0 and state[1] == state[2],
        "version": state[0],
        "source_revision": state[1],
        "indexed_revision": state[2],
        "indexed_at": state[3],
        "rebuilt_at": state[4],
        "missing_or_changed": missing,
        "orphan": orphan,
        "mode": "synchronous",
    }
