"""Tests for MemoryStore.stream_entries — the generator powering the
Engram → Compost event-source channel (debate 019 Q4).

Contract (engram-integration-contract.md):
    - Filter by since / kinds / project
    - Yields in created_at ASC order
    - `origin=compost` excluded by default (feedback-loop prevention, Q7)
    - Include `active` and `resolved`; exclude `obsolete`
    - Stable memory_id, clear updated_at semantics
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "stream.db"))
    yield s
    s.close()


def _write_compost_insight(store: MemoryStore, content: str, **overrides) -> str:
    """Helper: write a valid compost insight (must satisfy all three CHECKs)."""
    mem = store.remember(
        content=content,
        kind=MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={"compost_fact_ids": ["f1"]},
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        **overrides,
    )
    return mem.id


class TestStreamEntriesBasics:
    def test_empty_store_yields_nothing(self, store):
        assert list(store.stream_entries()) == []

    def test_returns_iterator_not_list(self, store):
        store.remember(content="a fact", kind=MemoryKind.FACT, project="p1")
        result = store.stream_entries()
        # Must be iterable but not a concrete list — we want lazy streaming
        # for unbounded result sets.
        assert iter(result) is not None
        assert not isinstance(result, list)

    def test_yields_memory_objects(self, store):
        store.remember(content="seed fact", kind=MemoryKind.FACT, project="p1")
        entries = list(store.stream_entries())
        assert len(entries) == 1
        from engram.model import MemoryObject
        assert isinstance(entries[0], MemoryObject)
        assert entries[0].content == "seed fact"

    def test_ordered_by_created_at_ascending(self, store):
        # Force distinct timestamps via direct inserts (remember uses _now())
        now = datetime.now(timezone.utc)
        for i, ts in enumerate(
            [now - timedelta(minutes=5), now - timedelta(minutes=2), now]
        ):
            store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p1', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (f"m{i}", f"content {i}", f"s{i}", ts.isoformat()),
            )
        store.conn.commit()
        ids = [e.id for e in store.stream_entries()]
        assert ids == ["m0", "m1", "m2"]


class TestStreamEntriesFilters:
    def test_since_filters_strictly_after(self, store):
        now = datetime.now(timezone.utc)
        for i, ts in enumerate([
            now - timedelta(hours=2),
            now - timedelta(hours=1),
            now,
        ]):
            store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p1', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (f"m{i}", f"c{i}", f"s{i}", ts.isoformat()),
            )
        store.conn.commit()

        cutoff = now - timedelta(hours=1, minutes=30)
        entries = list(store.stream_entries(since=cutoff))
        assert {e.id for e in entries} == {"m1", "m2"}

    def test_kinds_filter_restricts_to_union(self, store):
        store.remember(content="c1 constraint about money", kind=MemoryKind.CONSTRAINT, project="p1")
        store.remember(content="f1 a throwaway fact", kind=MemoryKind.FACT, project="p1")
        store.remember(content="d1 decision text", kind=MemoryKind.DECISION, project="p1")

        facts_only = list(store.stream_entries(kinds=[MemoryKind.FACT]))
        assert len(facts_only) == 1
        assert facts_only[0].kind == MemoryKind.FACT

        pair = list(
            store.stream_entries(kinds=[MemoryKind.FACT, MemoryKind.DECISION])
        )
        assert {e.kind for e in pair} == {MemoryKind.FACT, MemoryKind.DECISION}

    def test_project_filter(self, store):
        store.remember(content="payments rule", kind=MemoryKind.FACT, project="pay")
        store.remember(content="billing rule", kind=MemoryKind.FACT, project="bill")
        entries = list(store.stream_entries(project="pay"))
        assert len(entries) == 1
        assert entries[0].project == "pay"

    def test_kinds_none_means_all_kinds(self, store):
        store.remember(content="fact entry", kind=MemoryKind.FACT, project="p1")
        store.remember(content="decision entry", kind=MemoryKind.DECISION, project="p1")
        entries = list(store.stream_entries(kinds=None))
        assert len(entries) == 2

    def test_combined_filters(self, store):
        store.remember(content="payments fact", kind=MemoryKind.FACT, project="pay")
        store.remember(content="payments decision", kind=MemoryKind.DECISION, project="pay")
        store.remember(content="billing fact", kind=MemoryKind.FACT, project="bill")

        entries = list(
            store.stream_entries(
                kinds=[MemoryKind.FACT],
                project="pay",
            )
        )
        assert len(entries) == 1
        assert entries[0].project == "pay"
        assert entries[0].kind == MemoryKind.FACT


class TestStreamEntriesFeedbackLoopPrevention:
    """Debate 019 Q7: origin=compost excluded by default from the stream,
    so Compost does not re-ingest its own insights as new observations."""

    def test_compost_origin_excluded_by_default(self, store):
        store.remember(content="human fact", kind=MemoryKind.FACT, project="p1")
        _write_compost_insight(store, "compost insight")

        entries = list(store.stream_entries())
        origins = {e.origin for e in entries}
        assert MemoryOrigin.COMPOST not in origins
        assert MemoryOrigin.HUMAN in origins

    def test_include_compost_flag_opt_in(self, store):
        store.remember(content="human fact", kind=MemoryKind.FACT, project="p1")
        _write_compost_insight(store, "compost insight")

        entries = list(store.stream_entries(include_compost=True))
        origins = {e.origin for e in entries}
        assert MemoryOrigin.COMPOST in origins


class TestStreamEntriesStatusFilter:
    def test_excludes_obsolete(self, store):
        mem = store.remember(content="will be forgotten", kind=MemoryKind.FACT, project="p1")
        store.forget(mem.id)
        assert list(store.stream_entries()) == []

    def test_includes_resolved(self, store):
        mem = store.remember(content="resolved entry", kind=MemoryKind.FACT, project="p1")
        store.conn.execute(
            "UPDATE memories SET status = 'resolved' WHERE id = ?", (mem.id,)
        )
        store.conn.commit()

        entries = list(store.stream_entries())
        assert len(entries) == 1
        assert entries[0].status == MemoryStatus.RESOLVED

    def test_excludes_expired_compost_even_with_include_flag(self, store):
        """Expired insights should not stream — expires_at is enforced at view
        level (memory_scores), and stream_entries respects the same TTL."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        # Raw insert to bypass store.remember (which would refuse in dedup
        # checks and whose expires_at must be future for typical cases).
        store.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status,
                strength, pinned, scope, source_trace, expires_at, created_at)
               VALUES (?, ?, ?, 'insight', 'compost', NULL, '[]', 'active',
                       0.5, 0, 'global', ?, ?, ?)""",
            (
                "expired",
                "stale insight",
                "s",
                '{"compost_fact_ids":["f1"]}',
                past.isoformat(),
                (past - timedelta(days=30)).isoformat(),
            ),
        )
        store.conn.commit()

        entries = list(store.stream_entries(include_compost=True))
        assert all(e.id != "expired" for e in entries)


class TestStreamEntriesLaziness:
    def test_lazy_generator_supports_large_sets(self, store):
        # Build a moderate-size set; assert we can early-break without
        # materializing the rest.
        for i in range(100):
            store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p1', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (
                    f"m{i:03d}",
                    f"content {i}",
                    f"s{i}",
                    (datetime.now(timezone.utc) - timedelta(seconds=200 - i)).isoformat(),
                ),
            )
        store.conn.commit()

        gen = store.stream_entries()
        first_three = []
        for entry in gen:
            first_three.append(entry.id)
            if len(first_three) == 3:
                break
        assert first_three == ["m000", "m001", "m002"]
