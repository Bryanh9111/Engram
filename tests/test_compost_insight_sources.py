"""Tests for compost_insight_sources auto-fill on remember(insight).

When an insight is written, every fact_id in source_trace['compost_fact_ids']
is mapped to the memory_id in the compost_insight_sources table. This is the
O(log n) lookup path used by invalidate_compost_fact to find which insights
to mark obsolete when a Compost fact changes.

Schema (from migration 002):
    compost_insight_sources(memory_id, fact_id) PK(memory_id, fact_id)
    Cascading DELETE via memories_compost_map_ad trigger.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "sources.db"))
    yield s
    s.close()


def _sources(store: MemoryStore, memory_id: str) -> set[str]:
    rows = store.conn.execute(
        "SELECT fact_id FROM compost_insight_sources WHERE memory_id = ?",
        (memory_id,),
    ).fetchall()
    return {r[0] for r in rows}


def _insight(store: MemoryStore, content: str, fact_ids: list[str], **extra):
    return store.remember(
        content=content,
        kind=MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={"compost_fact_ids": fact_ids, **extra.get("trace_extra", {})},
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


class TestAutoFill:
    def test_single_fact_id_creates_one_row(self, store):
        mem = _insight(store, "insight A", ["f1"])
        assert _sources(store, mem.id) == {"f1"}

    def test_multiple_fact_ids_create_multiple_rows(self, store):
        mem = _insight(store, "insight B", ["f1", "f2", "f3"])
        assert _sources(store, mem.id) == {"f1", "f2", "f3"}

    def test_empty_fact_ids_creates_no_rows(self, store):
        # source_trace satisfies the NOT NULL CHECK even with empty array
        mem = _insight(store, "insight C no facts", [])
        assert _sources(store, mem.id) == set()

    def test_other_keys_in_source_trace_ignored(self, store):
        mem = store.remember(
            content="insight D with mixed trace",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={
                "compost_fact_ids": ["f9"],
                "note": "unrelated",
                "version": 2,
            },
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        assert _sources(store, mem.id) == {"f9"}

    def test_non_insight_kinds_never_fill(self, store):
        """Only kind=insight triggers the map write. A regular fact with a
        coincidental source_trace must not pollute the table."""
        store.remember(
            content="a plain fact",
            kind=MemoryKind.FACT,
            project="p1",
            source_trace={"compost_fact_ids": ["should_not_appear"]},
        )
        count = store.conn.execute(
            "SELECT COUNT(*) FROM compost_insight_sources"
        ).fetchone()[0]
        assert count == 0


class TestLookupShape:
    def test_fact_id_reverse_lookup(self, store):
        """The invalidation hot path joins from fact_id → memory_id. Prove
        the index is usable that way (multiple insights sharing one fact)."""
        mem_a = _insight(store, "insight sharing fact f1", ["f1", "f2"])
        mem_b = _insight(store, "insight also sharing f1", ["f1", "f3"])

        rows = store.conn.execute(
            "SELECT memory_id FROM compost_insight_sources WHERE fact_id = ?",
            ("f1",),
        ).fetchall()
        assert {r[0] for r in rows} == {mem_a.id, mem_b.id}


class TestCascadingDelete:
    def test_delete_memory_cascades_sources(self, store):
        """The memories_compost_map_ad trigger from migration 002 should
        wipe the map entries when the parent memory is hard-deleted."""
        mem = _insight(store, "to be deleted", ["f1", "f2"])
        assert _sources(store, mem.id) == {"f1", "f2"}

        store.conn.execute("DELETE FROM memories WHERE id = ?", (mem.id,))
        store.conn.commit()

        assert _sources(store, mem.id) == set()


class TestDedup:
    def test_content_dedup_does_not_duplicate_rows(self, store):
        """remember() dedups via FTS5 similarity; calling it twice with
        near-identical content must not create duplicate (memory_id, fact_id)
        rows (they would violate PK anyway, but we assert the store handles
        it cleanly instead of raising)."""
        mem1 = _insight(store, "checkout latency correlates with redis pool", ["f1", "f2"])
        mem2 = _insight(store, "checkout latency correlates with redis pool", ["f1", "f2"])
        # Dedup path returns the same memory.
        assert mem1.id == mem2.id
        assert _sources(store, mem1.id) == {"f1", "f2"}
