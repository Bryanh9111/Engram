"""Tests for MCP tool stream_for_compost — contract-shaped projection
over MemoryStore.stream_entries.

Contract (engram-integration-contract.md line 111):
    Each entry includes memory_id, kind, content, project, scope,
    created_at, updated_at, tags, origin.

The tool is a thin wrapper that:
    - parses ISO since string → datetime
    - converts string kinds → MemoryKind enum
    - forwards project / include_compost unchanged
    - caps the stream at `limit` so MCP transport stays bounded
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope
from engram.store import MemoryStore


CONTRACT_KEYS = {
    "memory_id",
    "kind",
    "content",
    "project",
    "scope",
    "created_at",
    "updated_at",
    "tags",
    "origin",
}


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "stream.db"))
    yield s
    s.close()


def _compost_insight(store: MemoryStore, content: str, fact_ids: list[str]):
    return store.remember(
        content=content,
        kind=MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={"compost_fact_ids": fact_ids},
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


class TestContractShape:
    def test_returns_list(self, store):
        from engram.server import _handle_stream_for_compost

        assert _handle_stream_for_compost(store) == []

    def test_entry_has_exact_contract_keys(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(
            content="first project memory",
            kind=MemoryKind.FACT,
            project="p1",
            tags=["t1", "t2"],
        )
        [entry] = _handle_stream_for_compost(store)
        assert set(entry.keys()) == CONTRACT_KEYS

    def test_memory_id_renamed_from_id(self, store):
        from engram.server import _handle_stream_for_compost

        mem = store.remember(content="x", kind=MemoryKind.FACT, project="p")
        [entry] = _handle_stream_for_compost(store)
        assert entry["memory_id"] == mem.id
        assert "id" not in entry

    def test_updated_at_equals_created_at(self, store):
        """Append-only model — content never mutates, so updated_at mirrors
        created_at until a real edit API ever exists."""
        from engram.server import _handle_stream_for_compost

        mem = store.remember(content="frozen content", kind=MemoryKind.FACT, project="p")
        [entry] = _handle_stream_for_compost(store)
        assert entry["updated_at"] == entry["created_at"]
        assert entry["created_at"] == mem.created_at.isoformat()

    def test_enum_values_serialized_as_strings(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="serialize me", kind=MemoryKind.DECISION, project="p")
        [entry] = _handle_stream_for_compost(store)
        assert entry["kind"] == "decision"
        assert entry["origin"] == "human"
        assert entry["scope"] == "project"

    def test_tags_is_list(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(
            content="tagged", kind=MemoryKind.FACT, project="p",
            tags=["a", "b"],
        )
        [entry] = _handle_stream_for_compost(store)
        assert entry["tags"] == ["a", "b"]


class TestParameterForwarding:
    def test_since_parsed_from_iso_string(self, store):
        from engram.server import _handle_stream_for_compost

        now = datetime.now(timezone.utc)
        for i, ts in enumerate([now - timedelta(hours=2), now]):
            store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (f"m{i}", f"c{i}", f"s{i}", ts.isoformat()),
            )
        store.conn.commit()

        cutoff = (now - timedelta(hours=1)).isoformat()
        entries = _handle_stream_for_compost(store, since=cutoff)
        assert len(entries) == 1
        assert entries[0]["memory_id"] == "m1"

    def test_kinds_string_list_converts_to_enum_filter(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="fact entry", kind=MemoryKind.FACT, project="p")
        store.remember(content="decision entry", kind=MemoryKind.DECISION, project="p")
        store.remember(content="procedure entry", kind=MemoryKind.PROCEDURE, project="p")

        entries = _handle_stream_for_compost(store, kinds=["fact", "decision"])
        got = {e["kind"] for e in entries}
        assert got == {"fact", "decision"}

    def test_project_filter(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="pay entry", kind=MemoryKind.FACT, project="pay")
        store.remember(content="bill entry", kind=MemoryKind.FACT, project="bill")
        entries = _handle_stream_for_compost(store, project="pay")
        assert len(entries) == 1
        assert entries[0]["project"] == "pay"

    def test_compost_excluded_by_default(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="human fact", kind=MemoryKind.FACT, project="p")
        _compost_insight(store, "compost insight", ["f1"])

        entries = _handle_stream_for_compost(store)
        origins = {e["origin"] for e in entries}
        assert "compost" not in origins
        assert "human" in origins

    def test_include_compost_flag(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="human fact", kind=MemoryKind.FACT, project="p")
        _compost_insight(store, "compost insight", ["f1"])

        entries = _handle_stream_for_compost(store, include_compost=True)
        origins = {e["origin"] for e in entries}
        assert origins == {"human", "compost"}


class TestLimitGuard:
    def test_default_limit_caps_transport(self, store):
        from engram.server import _handle_stream_for_compost

        for i in range(20):
            store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (
                    f"m{i:02d}",
                    f"c{i}",
                    f"s{i}",
                    (datetime.now(timezone.utc) - timedelta(seconds=100 - i)).isoformat(),
                ),
            )
        store.conn.commit()

        entries = _handle_stream_for_compost(store, limit=5)
        assert len(entries) == 5
        # ASC order — oldest first
        assert entries[0]["memory_id"] == "m00"

    def test_zero_limit_returns_empty(self, store):
        from engram.server import _handle_stream_for_compost

        store.remember(content="one", kind=MemoryKind.FACT, project="p")
        assert _handle_stream_for_compost(store, limit=0) == []


class TestMCPToolRegistration:
    def test_tool_is_registered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ENGRAM_DB", str(tmp_path / "m.db"))
        from engram.server import create_server

        server = create_server()
        assert server._tool_manager.get_tool("stream_for_compost") is not None
