"""Recall miss log tests — debate 016 Q4 decision.

Local FTS5 miss observability. When recall() returns empty results for a
non-empty query, we log the query to recall_miss_log. 3-6 months of data
collected can feed an offline `compost import-miss-hints` workflow later,
or trigger v5 (multi-path recall + rerank) when miss rate signals demand.

This closes tech debt #3: recall_miss_log table existed since migration
001 but had no writer. Writer was originally slated for "Slice C" which
was killed by Slice B (Compost integration).
"""

from __future__ import annotations

import pytest

from engram.model import MemoryKind
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(str(tmp_path / "miss_log.db"))


class TestRecallMissLog:
    def test_empty_recall_logs_miss(self, store):
        """FTS5 returns zero rows -> log one miss entry."""
        results = store.recall("nonexistent_unique_token_xyz_12345")
        assert results == []

        row = store.conn.execute(
            "SELECT query_norm, sample_query, hits FROM recall_miss_log"
        ).fetchone()
        assert row is not None
        assert "nonexistent_unique_token_xyz_12345" in row[0]
        assert row[1] == "nonexistent_unique_token_xyz_12345"
        assert row[2] == 1

    def test_repeated_miss_upserts_hit_count(self, store):
        """Same query hitting empty results twice -> one row, hits=2."""
        store.recall("ghost_query_abc")
        store.recall("ghost_query_abc")

        rows = store.conn.execute(
            "SELECT hits FROM recall_miss_log WHERE query_norm LIKE '%ghost_query_abc%'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 2

    def test_case_and_whitespace_normalized_in_key(self, store):
        """query_norm collapses case + whitespace so near-identical queries merge."""
        store.recall("HELLO World")
        store.recall("  hello   world  ")

        rows = store.conn.execute(
            "SELECT query_norm, hits FROM recall_miss_log"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "hello world"
        assert rows[0][1] == 2

    def test_empty_query_not_logged(self, store):
        """Empty/whitespace query = recent fallback, not a miss."""
        store.recall("")
        store.recall("   ")

        count = store.conn.execute(
            "SELECT COUNT(*) FROM recall_miss_log"
        ).fetchone()[0]
        assert count == 0

    def test_hit_query_not_logged(self, store):
        """Query with results -> no miss log entry."""
        store.remember(content="Money values use integer cents", kind=MemoryKind.CONSTRAINT)
        results = store.recall("Money integer cents")
        assert len(results) >= 1

        count = store.conn.execute(
            "SELECT COUNT(*) FROM recall_miss_log"
        ).fetchone()[0]
        assert count == 0

    def test_project_scoped_miss_keyed_separately(self, store):
        """Same query across different projects -> separate rows."""
        store.recall("ghost", project="alpha")
        store.recall("ghost", project="beta")
        store.recall("ghost")  # no project = cross-project

        rows = store.conn.execute(
            "SELECT project, hits FROM recall_miss_log ORDER BY project"
        ).fetchall()
        assert len(rows) == 3

    def test_null_project_normalizes_for_pk_upsert(self, store):
        """project=None upserts correctly despite SQLite NULL != NULL semantics."""
        store.recall("missing")
        store.recall("missing")

        rows = store.conn.execute(
            "SELECT hits FROM recall_miss_log"
        ).fetchall()
        assert len(rows) == 1, "project=None must upsert to same row, not duplicate"
        assert rows[0][0] == 2
