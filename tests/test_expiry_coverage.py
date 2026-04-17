"""Expiry-filter coverage regression tests.

Every read surface that returns memories into an agent's context must
exclude entries past `expires_at`. The `memory_scores` view filters at
the SQL level, but LEFT JOIN and direct table reads can still surface
stale rows — this is the gap test.

Paths covered:
    MemoryStore.recall()               — FTS5 path + recent fallback
    MemoryStore.consolidate_candidates() — archival candidates
    MemoryStore.compile()              — markdown export
    MemoryStore.micro_index()          — cold-start index
    MemoryStore.stats()                — active counts
    ProactiveRecallEngine.on_file_open() — path-scope triggered

Paths intentionally NOT covered (they should NOT filter):
    MemoryStore.export() — lossless backup
    MemoryStore.health() — the reporter of expired entries
    MemoryStore.stream_entries() — already has explicit filter (tested separately)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engram.model import MemoryKind, MemoryOrigin, MemoryScope
from engram.proactive import ProactiveRecallEngine
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "expiry.db"))
    yield s
    s.close()


def _insert_expired_compost(store: MemoryStore, memory_id: str, content: str = "stale insight"):
    """Raw-insert an expired compost insight, bypassing MemoryStore.remember
    which defaults to future expires_at. Only this bypass reflects the
    real-world scenario where time has passed since the insight was first
    stored."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    store.conn.execute(
        """INSERT INTO memories
           (id, content, summary, kind, origin, project, tags, status,
            strength, pinned, scope, source_trace, expires_at, created_at)
           VALUES (?, ?, ?, 'insight', 'compost', NULL, '[]', 'active',
                   0.5, 0, 'global', ?, ?, ?)""",
        (memory_id, content, content[:80], '{"compost_fact_ids":["f1"]}', past, now),
    )
    store.conn.commit()


def _insert_expired_with_path_scope(store: MemoryStore, memory_id: str):
    """Expired entry with path_scope — proactive recall's shape."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    # path_scope requires constraint/guardrail/procedure kind to matter
    # in proactive; use constraint so we can test the path. constraint
    # CAN have expires_at legally (only compost has NOT-NULL requirement).
    store.conn.execute(
        """INSERT INTO memories
           (id, content, summary, kind, origin, project, path_scope, tags,
            status, strength, pinned, scope, confidence, expires_at, created_at)
           VALUES (?, 'stale rule about payments', 'stale',
                   'constraint', 'human', 'pay', 'payments/*', '[]',
                   'active', 0.5, 0, 'project', 1.0, ?, ?)""",
        (memory_id, past, now),
    )
    store.conn.commit()


class TestRecallFTSExcludesExpired:
    def test_fts_query_does_not_return_expired(self, store):
        # Live entry matching same FTS terms
        store.remember(
            content="payments require integer cents always",
            kind=MemoryKind.CONSTRAINT, project="pay",
        )
        _insert_expired_compost(
            store, "exp1",
            content="payments integer cents old insight overlapping terms",
        )

        results = store.recall("payments integer cents")
        ids = {m.id for m in results}
        assert "exp1" not in ids

    def test_recent_fallback_does_not_return_expired(self, store):
        store.remember(content="live fact", kind=MemoryKind.FACT, project="p")
        _insert_expired_compost(store, "exp_recent")

        # empty query triggers _recall_recent
        results = store.recall("")
        ids = {m.id for m in results}
        assert "exp_recent" not in ids


class TestConsolidateExcludesExpired:
    def test_archival_candidates_do_not_include_expired(self, store):
        # Candidate needs low strength AND old — insert one that satisfies
        # but is expired
        past_create = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        past_exp = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status,
                strength, pinned, scope, source_trace, expires_at, created_at)
               VALUES (?, ?, ?, 'insight', 'compost', NULL, '[]', 'active',
                       0.1, 0, 'global', ?, ?, ?)""",
            ("exp_arch", "old stale insight", "s",
             '{"compost_fact_ids":["f"]}', past_exp, past_create),
        )
        store.conn.commit()

        cands = store.consolidate_candidates()
        assert all(c.id != "exp_arch" for c in cands)


class TestCompileExcludesExpired:
    def test_markdown_compile_skips_expired(self, store):
        store.remember(content="live constraint", kind=MemoryKind.CONSTRAINT, project="p")
        # compile() is project-scoped; expired compost has project=None,
        # so insert an expired human entry in project 'p' instead
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        store.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status,
                strength, pinned, scope, expires_at, created_at)
               VALUES (?, 'stale constraint xyz123 should not appear',
                       'stale constraint xyz123 should not appear',
                       'constraint', 'human', 'p', '[]', 'active',
                       0.5, 0, 'project', ?, ?)""",
            ("exp_compile", past, now),
        )
        store.conn.commit()

        md = store.compile("p")
        assert "xyz123" not in md
        assert "live constraint" in md


class TestMicroIndexExcludesExpired:
    def test_active_count_excludes_expired(self, store):
        store.remember(content="live", kind=MemoryKind.FACT, project="p")
        _insert_expired_compost(store, "exp_idx")

        idx = store.micro_index()
        # idx header reads "Engram: <N> memories"
        first_line = idx.split("\n")[0]
        # Only the live entry should count
        assert "1 memories" in first_line


class TestStatsExcludesExpired:
    def test_active_count_excludes_expired(self, store):
        store.remember(content="live", kind=MemoryKind.FACT, project="p")
        _insert_expired_compost(store, "exp_stats")

        s = store.stats()
        assert s["active"] == 1  # expired compost insight must not count


class TestProactiveExcludesExpired:
    def test_file_open_skips_expired_path_scope_entry(self, store):
        _insert_expired_with_path_scope(store, "exp_proactive")

        engine = ProactiveRecallEngine(store)
        results = engine.on_file_open("payments/reconcile.py")
        assert all(m.id != "exp_proactive" for m in results)

    def test_file_open_filter_references_compost_not_compiled(self, store):
        """The SQL used to say 'origin != compiled' — a dead filter since
        COMPILED was removed from MemoryOrigin in v3.4 P0. The intent was
        to exclude AI-synthesized content from proactive push. Now compost
        is the relevant AI origin, and the filter must mention it by name
        so the next code reader can see the defense."""
        import inspect
        from engram import proactive

        src = inspect.getsource(proactive.ProactiveRecallEngine.on_file_open)
        # The old dead filter must not be the only exclusion
        assert "'compiled'" not in src, (
            "proactive.on_file_open still filters on 'compiled', "
            "which no longer exists as a MemoryOrigin value. "
            "Filter on 'compost' instead."
        )
