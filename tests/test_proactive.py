"""Tests for ProactiveRecallEngine: just-in-time guardrails, not autobiography."""

import pytest

from engram.model import MemoryKind
from engram.proactive import ProactiveRecallEngine
from engram.store import MemoryStore


@pytest.fixture
def engine(tmp_path):
    store = MemoryStore(str(tmp_path / "test.db"))
    # Load the 5 canonical test memories
    store.remember(
        content="Money values must use integer cents end-to-end, never introduce floats",
        kind=MemoryKind.CONSTRAINT,
        project="payments",
        path_scope="payments/*",
        pinned=True,
    )
    store.remember(
        content="Integration tests: seed Redis first, then start worker, then API",
        kind=MemoryKind.PROCEDURE,
        project="backend",
        path_scope="tests/integration/*",
    )
    store.remember(
        content="Use polling not websockets for job status because customer proxies break upgrades",
        kind=MemoryKind.DECISION,
        project="backend",
    )
    store.remember(
        content="UserSearchV2 is behind SEARCH_V2=1 feature flag, production defaults to V1",
        kind=MemoryKind.FACT,
        project="search",
        path_scope="search/*",
    )
    store.remember(
        content="Never parallelize migration-0042 and migration-0043, lock contention caused production failure",
        kind=MemoryKind.GUARDRAIL,
        project="backend",
        path_scope="migrations/*",
    )
    return ProactiveRecallEngine(store)


class TestProactiveRecall:
    def test_path_triggers_matching_constraint(self, engine):
        """Opening billing file should surface the cents constraint."""
        results = engine.on_file_open("payments/reconcile.ts")
        assert len(results) >= 1
        assert any("cents" in r.content for r in results)

    def test_path_triggers_matching_guardrail(self, engine):
        """Opening migration file should surface the parallelism guardrail."""
        results = engine.on_file_open("migrations/0042_add_index.sql")
        assert len(results) >= 1
        assert any("parallelize" in r.content for r in results)

    def test_path_triggers_procedure(self, engine):
        """Opening integration test should surface the Redis procedure."""
        results = engine.on_file_open("tests/integration/test_api.py")
        assert len(results) >= 1
        assert any("Redis" in r.content for r in results)

    def test_only_actionable_kinds_returned(self, engine):
        """Proactive recall should only push constraint/guardrail/procedure."""
        results = engine.on_file_open("search/index.ts")
        # The FACT about SearchV2 should NOT be proactively pushed
        for r in results:
            assert r.kind in (
                MemoryKind.CONSTRAINT,
                MemoryKind.GUARDRAIL,
                MemoryKind.PROCEDURE,
            )

    def test_max_3_results(self, engine):
        """Never push more than 3 memories."""
        results = engine.on_file_open("payments/handler.ts")
        assert len(results) <= 3

    def test_no_match_returns_empty(self, engine):
        """Unrelated path should return nothing."""
        results = engine.on_file_open("docs/README.md")
        assert len(results) == 0

    def test_low_confidence_excluded(self, engine):
        """Memories with confidence < 0.7 should not be proactively pushed."""
        engine.store.remember(
            content="Maybe we should refactor the auth module",
            kind=MemoryKind.CONSTRAINT,
            path_scope="auth/*",
            confidence=0.3,
        )
        results = engine.on_file_open("auth/login.ts")
        assert all(r.confidence >= 0.7 for r in results)

    def test_resolved_excluded_from_proactive(self, engine):
        """Resolved memories should not be proactively pushed."""
        from engram.model import MemoryStatus
        # Get a memory and mark it resolved
        results = engine.on_file_open("payments/reconcile.ts")
        assert len(results) >= 1
        mem_id = results[0].id
        engine.store.conn.execute(
            "UPDATE memories SET status = ? WHERE id = ?",
            (MemoryStatus.RESOLVED.value, mem_id),
        )
        engine.store.conn.commit()
        # Should no longer appear
        results_after = engine.on_file_open("payments/reconcile.ts")
        assert all(r.id != mem_id for r in results_after)

    def test_resolved_still_in_recall(self, engine):
        """Resolved memories should still be searchable via recall."""
        from engram.model import MemoryStatus
        results = engine.store.recall("integer cents")
        assert len(results) >= 1
        mem_id = results[0].id
        engine.store.conn.execute(
            "UPDATE memories SET status = ? WHERE id = ?",
            (MemoryStatus.RESOLVED.value, mem_id),
        )
        engine.store.conn.commit()
        results_after = engine.store.recall("integer cents")
        assert any(r.id == mem_id for r in results_after)

    def test_compiled_origin_excluded(self, engine):
        """origin='compiled' memories should not be proactively pushed."""
        from engram.model import MemoryOrigin
        engine.store.remember(
            content="Payments subsystem tends to use integer types",
            kind=MemoryKind.CONSTRAINT,
            path_scope="payments/*",
            origin=MemoryOrigin.COMPILED,
        )
        results = engine.on_file_open("payments/handler.ts")
        for r in results:
            assert r.origin != MemoryOrigin.COMPILED

    def test_suppress_hides_memory(self, engine):
        """Suppressed memories should not appear in proactive recall."""
        results_before = engine.on_file_open("payments/reconcile.ts")
        assert len(results_before) >= 1
        mem_id = results_before[0].id

        engine.suppress(mem_id, duration_seconds=60)

        results_after = engine.on_file_open("payments/reconcile.ts")
        assert all(r.id != mem_id for r in results_after)

    def test_suppress_expires(self, engine):
        """Suppression should expire after duration."""
        import time
        results = engine.on_file_open("payments/reconcile.ts")
        mem_id = results[0].id

        engine.suppress(mem_id, duration_seconds=0)  # instant expire
        time.sleep(0.01)

        results_after = engine.on_file_open("payments/reconcile.ts")
        assert any(r.id == mem_id for r in results_after)
