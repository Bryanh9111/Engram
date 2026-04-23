"""Tests for compost insight structural dedup (migration 003 / debate 024).

The fix: same root_insight_id + chunk_index across two writes returns the
existing row instead of creating a duplicate. UUIDv5 in compost-engram-adapter
makes the key deterministic; Engram is the authoritative enforcer.

Schema (from migration 003 / db.py _SCHEMA):
    UNIQUE INDEX idx_compost_insight_idempotency
        ON memories(json_extract($.root_insight_id), json_extract($.chunk_index))
        WHERE origin='compost' AND json_type both correct.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "dedup.db"))
    yield s
    s.close()


def _compost_insight(
    store: MemoryStore,
    content: str,
    *,
    root_insight_id: str,
    chunk_index: int,
    fact_ids: list[str] | None = None,
):
    return store.remember(
        content=content,
        kind=MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={
            "root_insight_id": root_insight_id,
            "chunk_index": chunk_index,
            "compost_fact_ids": fact_ids or [],
        },
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


class TestStructuralDedup:
    def test_same_rid_and_chunk_returns_existing(self, store):
        """Two writes with identical (root_insight_id, chunk_index) collapse
        to one row. The fix for the dogfood-found 4-rows-where-2-should-be."""
        rid = "2ffbf27d-4949-55fd-8508-15d966e6bc03"
        m1 = _compost_insight(store, "digest content A", root_insight_id=rid, chunk_index=0)
        m2 = _compost_insight(store, "digest content A modified slightly", root_insight_id=rid, chunk_index=0)
        assert m1.id == m2.id
        # Exactly one row in DB
        count = store.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE origin='compost'"
        ).fetchone()[0]
        assert count == 1

    def test_same_rid_different_chunks_are_distinct(self, store):
        """A 2-chunk insight produces 2 rows (chunk 0 + chunk 1)."""
        rid = "2ffbf27d-4949-55fd-8508-15d966e6bc03"
        m0 = _compost_insight(store, "chunk 0 content", root_insight_id=rid, chunk_index=0)
        m1 = _compost_insight(store, "chunk 1 content", root_insight_id=rid, chunk_index=1)
        assert m0.id != m1.id
        count = store.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE origin='compost'"
        ).fetchone()[0]
        assert count == 2

    def test_different_rids_are_distinct(self, store):
        """Two compost insights with different root_insight_id never merge,
        even at chunk_index=0."""
        m1 = _compost_insight(store, "insight A", root_insight_id="aaaa-bbbb", chunk_index=0)
        m2 = _compost_insight(store, "insight B", root_insight_id="cccc-dddd", chunk_index=0)
        assert m1.id != m2.id

    def test_dedup_does_not_strengthen(self, store):
        """PUT semantics: re-writing the same chunk does NOT bump strength
        or access_count. Compost duplicate is infrastructure noise (scheduler
        retry, manual re-push), not user re-confirmation."""
        rid = "deadbeef-1234"
        m1 = _compost_insight(store, "insight", root_insight_id=rid, chunk_index=0)
        s1 = m1.strength
        ac1 = m1.access_count
        m2 = _compost_insight(store, "insight", root_insight_id=rid, chunk_index=0)
        assert m2.strength == s1
        assert m2.access_count == ac1


class TestFallbackPaths:
    def test_compost_without_root_insight_id_falls_back_to_fts5(self, store):
        """Compost insights lacking root_insight_id (legacy / malformed)
        still get the FTS5 content dedup as a safety net. Preserves existing
        behavior tested in test_compost_insight_sources.TestDedup."""
        s1 = store.remember(
            content="checkout latency correlates with redis pool",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"compost_fact_ids": ["f1"]},
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        s2 = store.remember(
            content="checkout latency correlates with redis pool",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"compost_fact_ids": ["f1"]},
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        assert s1.id == s2.id

    def test_non_compost_origin_uses_fts5(self, store):
        """origin=human/agent ignores the structural path entirely."""
        m1 = store.remember(content="some procedure step one", kind=MemoryKind.PROCEDURE, project="p")
        m2 = store.remember(content="some procedure step one", kind=MemoryKind.PROCEDURE, project="p")
        assert m1.id == m2.id

    def test_compost_with_partial_source_trace_falls_back(self, store):
        """Has root_insight_id but no chunk_index — falls back to FTS5."""
        s1 = store.remember(
            content="partial trace insight content here",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"root_insight_id": "abc-123"},  # no chunk_index
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        s2 = store.remember(
            content="partial trace insight content here",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"root_insight_id": "abc-123"},
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        # FTS5 content dedup catches it (same content)
        assert s1.id == s2.id


class TestUniqueIndexDefenseInDepth:
    def test_direct_insert_of_duplicate_is_blocked_by_unique_index(self, store):
        """Even if a buggy client bypasses the application-level dedup,
        the partial UNIQUE INDEX prevents two rows with the same
        (root_insight_id, chunk_index)."""
        import sqlite3

        rid = "blocked-by-index"
        m1 = _compost_insight(store, "first", root_insight_id=rid, chunk_index=0)

        # Try to bypass remember() and INSERT directly (simulates
        # buggy producer or schema migration import).
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                """INSERT INTO memories (
                    id, content, summary, kind, origin, project, scope,
                    source_trace, status, strength, pinned, tags,
                    confidence, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "duplicate-id-different",
                    "different content",
                    "summary",
                    "insight",
                    "compost",
                    None,
                    "global",
                    f'{{"root_insight_id": "{rid}", "chunk_index": 0}}',
                    "active",
                    0.5,
                    0,
                    "[]",
                    1.0,
                    datetime.now(timezone.utc).isoformat(),
                    datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
                ),
            )
            store.conn.commit()
