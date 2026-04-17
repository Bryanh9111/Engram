"""Tests for MCP tool invalidate_compost_fact — Compost → Engram
invalidation channel per debate 019 Q7.

When a Compost fact underlying an insight changes, Compost calls this
tool with the affected fact_ids. Engram reverse-looks-up via
compost_insight_sources and marks the matching insight memories as
obsolete (soft delete). Physical purge with 30-day grace is GC daemon
territory (Phase 3), out of scope here.

Return shape:
    {"invalidated_memory_ids": [...], "count": N}
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "inv.db"))
    yield s
    s.close()


def _insight(store: MemoryStore, content: str, fact_ids: list[str], **kw):
    return store.remember(
        content=content,
        kind=MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={"compost_fact_ids": fact_ids},
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        **kw,
    )


def _status_of(store: MemoryStore, memory_id: str) -> str:
    return store.conn.execute(
        "SELECT status FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()[0]


class TestCoreBehavior:
    def test_empty_fact_ids_is_noop(self, store):
        from engram.server import _handle_invalidate_compost_fact

        result = _handle_invalidate_compost_fact(store, [])
        assert result == {"invalidated_memory_ids": [], "count": 0}

    def test_single_fact_invalidates_single_insight(self, store):
        from engram.server import _handle_invalidate_compost_fact

        mem = _insight(store, "insight A about checkout latency", ["f1"])
        result = _handle_invalidate_compost_fact(store, ["f1"])

        assert result["count"] == 1
        assert result["invalidated_memory_ids"] == [mem.id]
        assert _status_of(store, mem.id) == "obsolete"

    def test_single_fact_invalidates_all_sharing_insights(self, store):
        from engram.server import _handle_invalidate_compost_fact

        mem_a = _insight(store, "insight one about billing", ["f1", "f2"])
        mem_b = _insight(store, "insight two also uses f1", ["f1", "f3"])
        mem_c = _insight(store, "insight three only f3", ["f3"])

        result = _handle_invalidate_compost_fact(store, ["f1"])

        assert set(result["invalidated_memory_ids"]) == {mem_a.id, mem_b.id}
        assert result["count"] == 2
        assert _status_of(store, mem_a.id) == "obsolete"
        assert _status_of(store, mem_b.id) == "obsolete"
        assert _status_of(store, mem_c.id) == "active"

    def test_multiple_fact_ids_union(self, store):
        from engram.server import _handle_invalidate_compost_fact

        mem_a = _insight(store, "insight on f1 payments routing", ["f1"])
        mem_b = _insight(store, "different insight on f2 login flow", ["f2"])
        mem_c = _insight(store, "third insight uses f3 caching", ["f3"])

        result = _handle_invalidate_compost_fact(store, ["f1", "f2"])

        assert set(result["invalidated_memory_ids"]) == {mem_a.id, mem_b.id}
        assert _status_of(store, mem_c.id) == "active"

    def test_unknown_fact_id_returns_zero(self, store):
        from engram.server import _handle_invalidate_compost_fact

        _insight(store, "only insight fact f1", ["f1"])
        result = _handle_invalidate_compost_fact(store, ["nonexistent"])

        assert result == {"invalidated_memory_ids": [], "count": 0}


class TestIdempotency:
    def test_already_obsolete_reported_once(self, store):
        from engram.server import _handle_invalidate_compost_fact

        mem = _insight(store, "single insight", ["f1"])

        first = _handle_invalidate_compost_fact(store, ["f1"])
        assert first["count"] == 1
        second = _handle_invalidate_compost_fact(store, ["f1"])
        # The map row still exists — still resolves — but already obsolete.
        # We still surface it so Compost can confirm the target is gone.
        assert second["invalidated_memory_ids"] == [mem.id]
        assert _status_of(store, mem.id) == "obsolete"


class TestPinnedHandling:
    def test_pinned_insight_still_invalidated(self, store):
        """Compost is the authority on insight freshness. Pinning an insight
        expresses user intent, but a stale insight from a superseded fact is
        worse than useless — invalidate regardless of pinned."""
        from engram.server import _handle_invalidate_compost_fact

        mem = _insight(store, "pinned insight f1 backed", ["f1"], pinned=True)
        result = _handle_invalidate_compost_fact(store, ["f1"])

        assert result["count"] == 1
        assert _status_of(store, mem.id) == "obsolete"


class TestAuditLog:
    def test_ops_log_records_invalidation(self, store):
        from engram.server import _handle_invalidate_compost_fact

        mem = _insight(store, "insight about auditability", ["f1"])
        _handle_invalidate_compost_fact(store, ["f1"])

        row = store.conn.execute(
            """SELECT op, memory_id FROM ops_log
               WHERE op = 'invalidate_compost_fact'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        assert row is not None
        assert row[1] == mem.id


class TestScoping:
    def test_non_insight_kinds_untouched(self, store):
        """Only compost_insight_sources drives invalidation; other memories
        never populate the map, so they can't be hit even if a fact_id
        string collides with one of their tags or content."""
        from engram.server import _handle_invalidate_compost_fact

        regular = store.remember(
            content="a regular fact mentioning f1 in its content",
            kind=MemoryKind.FACT,
            project="p",
        )
        _handle_invalidate_compost_fact(store, ["f1"])
        assert _status_of(store, regular.id) == "active"


class TestMCPToolRegistration:
    def test_tool_is_registered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ENGRAM_DB", str(tmp_path / "m.db"))
        from engram.server import create_server

        server = create_server()
        assert (
            server._tool_manager.get_tool("invalidate_compost_fact") is not None
        )
