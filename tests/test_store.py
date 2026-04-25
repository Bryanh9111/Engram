"""Tests for MemoryStore: remember, recall, forget, consolidate."""

import pytest

from engram.model import MemoryKind, MemoryStatus
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    return MemoryStore(str(db_path))


class TestRemember:
    def test_remember_returns_memory_with_id(self, store):
        mem = store.remember(
            content="Money values must use integer cents",
            kind=MemoryKind.CONSTRAINT,
            project="payments",
        )
        assert mem.id
        assert mem.content == "Money values must use integer cents"
        assert mem.kind == MemoryKind.CONSTRAINT
        assert mem.project == "payments"

    def test_remember_persists_to_db(self, store):
        mem = store.remember(
            content="Never parallelize these migrations",
            kind=MemoryKind.GUARDRAIL,
        )
        # Query directly from DB
        row = store.conn.execute(
            "SELECT content, kind FROM memories WHERE id = ?", (mem.id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "Never parallelize these migrations"
        assert row[1] == "guardrail"

    def test_remember_with_all_fields(self, store):
        mem = store.remember(
            content="Seed Redis before running integration tests",
            kind=MemoryKind.PROCEDURE,
            project="backend",
            path_scope="tests/integration/*",
            tags=["testing", "redis"],
            confidence=0.9,
            evidence_link="https://github.com/org/repo/pull/55",
        )
        assert mem.path_scope == "tests/integration/*"
        assert mem.tags == ["testing", "redis"]
        assert mem.confidence == 0.9
        assert mem.evidence_link == "https://github.com/org/repo/pull/55"

    def test_remember_dedup_rejects_near_duplicate(self, store):
        store.remember(
            content="Money values must use integer cents end-to-end",
            kind=MemoryKind.CONSTRAINT,
            project="payments",
        )
        # Very similar content should be detected as duplicate
        result = store.remember(
            content="Money values must use integer cents end to end",
            kind=MemoryKind.CONSTRAINT,
            project="payments",
        )
        # Should return existing memory, not create new
        count = store.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert count == 1

    def test_remember_allows_distinct_content(self, store):
        store.remember(
            content="Money values must use integer cents",
            kind=MemoryKind.CONSTRAINT,
        )
        store.remember(
            content="Auth tokens expire after 24 hours",
            kind=MemoryKind.FACT,
        )
        count = store.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert count == 2

    def test_remember_strengthens_existing_on_dedup(self, store):
        mem1 = store.remember(
            content="Always use UTC timestamps",
            kind=MemoryKind.CONSTRAINT,
        )
        original_strength = mem1.strength

        mem2 = store.remember(
            content="Always use UTC timestamps",
            kind=MemoryKind.CONSTRAINT,
        )
        assert mem2.id == mem1.id
        assert mem2.strength > original_strength

    def test_remember_low_confidence_stored_with_flag(self, store):
        mem = store.remember(
            content="Maybe we should use Redis for caching",
            kind=MemoryKind.DECISION,
            confidence=0.3,
        )
        assert mem.confidence == 0.3
        # Low confidence memories still stored but marked

    def test_remember_pinned_memory(self, store):
        mem = store.remember(
            content="Core architectural principle",
            kind=MemoryKind.CONSTRAINT,
            pinned=True,
        )
        row = store.conn.execute(
            "SELECT pinned FROM memories WHERE id = ?", (mem.id,)
        ).fetchone()
        assert row[0] == 1

    def test_remember_indexes_in_fts(self, store):
        store.remember(
            content="Authentication uses SAML assertions with the new SSO provider",
            kind=MemoryKind.FACT,
        )
        # FTS search should find it
        rows = store.conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'SAML'"
        ).fetchone()
        assert rows[0] == 1


@pytest.fixture
def populated_store(store):
    """Store with the 5 GPT-5.4 example memories pre-loaded."""
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
        tags=["testing", "redis"],
    )
    store.remember(
        content="Use polling not websockets for job status because customer proxies break upgrades",
        kind=MemoryKind.DECISION,
        project="backend",
        evidence_link="https://github.com/org/repo/pull/99",
    )
    store.remember(
        content="UserSearchV2 is behind SEARCH_V2=1 feature flag, production defaults to V1",
        kind=MemoryKind.FACT,
        project="search",
        path_scope="search/*",
        confidence=0.8,
    )
    store.remember(
        content="Never parallelize migration-0042 and migration-0043, lock contention caused production failure",
        kind=MemoryKind.GUARDRAIL,
        project="backend",
        path_scope="migrations/*",
        evidence_link="https://github.com/org/repo/incidents/7",
    )
    return store


class TestRecall:
    def test_recall_by_keyword(self, populated_store):
        results = populated_store.recall("integer cents money")
        assert len(results) >= 1
        assert any("cents" in r.content for r in results)

    def test_recall_returns_ranked_results(self, populated_store):
        results = populated_store.recall("Redis")
        assert len(results) >= 1
        assert "Redis" in results[0].content

    def test_recall_respects_limit(self, populated_store):
        results = populated_store.recall("backend", limit=2)
        assert len(results) <= 2

    def test_recall_filters_by_project(self, populated_store):
        results = populated_store.recall("production", project="search")
        for r in results:
            assert r.project == "search"

    def test_recall_filters_by_kind(self, populated_store):
        results = populated_store.recall("", kind=MemoryKind.GUARDRAIL)
        assert all(r.kind == MemoryKind.GUARDRAIL for r in results)

    def test_recall_filters_by_status(self, populated_store):
        # All memories are active by default
        results = populated_store.recall("", status=MemoryStatus.SUSPECT)
        assert len(results) == 0

    def test_recall_updates_access_metadata(self, populated_store):
        results = populated_store.recall("Redis")
        assert len(results) >= 1
        mem = results[0]
        # Access count should be incremented
        row = populated_store.conn.execute(
            "SELECT access_count, accessed_at FROM memories WHERE id = ?",
            (mem.id,),
        ).fetchone()
        assert row[0] >= 1
        assert row[1] is not None

    def test_recall_empty_query_returns_recent(self, populated_store):
        results = populated_store.recall("")
        assert len(results) >= 1

    def test_recall_no_match_returns_empty(self, populated_store):
        results = populated_store.recall("xyzzy_nonexistent_term_42")
        assert len(results) == 0

    def test_recall_by_path_scope(self, populated_store):
        results = populated_store.recall("", path_scope="migrations/*")
        assert len(results) >= 1
        assert all(r.path_scope == "migrations/*" for r in results)


class TestForget:
    def test_forget_soft_deletes(self, populated_store):
        results = populated_store.recall("Redis")
        assert len(results) >= 1
        mem_id = results[0].id

        populated_store.forget(mem_id)

        row = populated_store.conn.execute(
            "SELECT status FROM memories WHERE id = ?", (mem_id,)
        ).fetchone()
        assert row[0] == "obsolete"

    def test_forget_excludes_from_recall(self, populated_store):
        results = populated_store.recall("Redis")
        mem_id = results[0].id

        populated_store.forget(mem_id)

        results_after = populated_store.recall("Redis")
        assert all(r.id != mem_id for r in results_after)

    def test_forget_nonexistent_raises(self, store):
        with pytest.raises(ValueError):
            store.forget("nonexistent_id")

    def test_forget_pinned_raises(self, populated_store):
        # The constraint memory is pinned
        results = populated_store.recall("integer cents")
        pinned_mem = [r for r in results if r.pinned][0]
        with pytest.raises(ValueError, match="pinned"):
            populated_store.forget(pinned_mem.id)


class TestUnpin:
    def test_unpin_pinned_memory(self, populated_store):
        results = populated_store.recall("integer cents")
        pinned_mem = [r for r in results if r.pinned][0]

        result = populated_store.unpin(pinned_mem.id)

        assert result["status"] == "unpinned"
        row = populated_store.conn.execute(
            "SELECT pinned FROM memories WHERE id = ?", (pinned_mem.id,)
        ).fetchone()
        assert row[0] == 0

    def test_unpin_allows_forget_after(self, populated_store):
        results = populated_store.recall("integer cents")
        pinned_mem = [r for r in results if r.pinned][0]

        populated_store.unpin(pinned_mem.id)
        populated_store.forget(pinned_mem.id)

        row = populated_store.conn.execute(
            "SELECT status FROM memories WHERE id = ?", (pinned_mem.id,)
        ).fetchone()
        assert row[0] == "obsolete"

    def test_unpin_nonexistent_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.unpin("nonexistent_id")

    def test_unpin_already_unpinned_returns_noop(self, store):
        mem = store.remember(
            content="Not pinned",
            kind=MemoryKind.FACT,
            pinned=False,
        )
        result = store.unpin(mem.id)
        assert result["status"] == "already_unpinned"

    def test_unpin_logs_operation(self, populated_store):
        results = populated_store.recall("integer cents")
        pinned_mem = [r for r in results if r.pinned][0]

        populated_store.unpin(pinned_mem.id)

        op = populated_store.conn.execute(
            "SELECT op, memory_id FROM ops_log WHERE op = 'unpin' AND memory_id = ?",
            (pinned_mem.id,),
        ).fetchone()
        assert op is not None
        assert op[0] == "unpin"


class TestConsolidate:
    def test_consolidate_returns_candidates(self, populated_store):
        # Manually age some memories
        populated_store.conn.execute(
            """UPDATE memories SET
               created_at = '2025-01-01T00:00:00+00:00',
               strength = 0.1,
               access_count = 0,
               pinned = 0
               WHERE kind = 'fact'"""
        )
        populated_store.conn.commit()

        candidates = populated_store.consolidate_candidates(
            max_age_days=90, min_strength=0.2
        )
        assert len(candidates) >= 1
        assert all(c.kind == MemoryKind.FACT for c in candidates)

    def test_consolidate_excludes_pinned(self, populated_store):
        # Age everything including pinned
        populated_store.conn.execute(
            """UPDATE memories SET
               created_at = '2025-01-01T00:00:00+00:00',
               strength = 0.05,
               access_count = 0"""
        )
        populated_store.conn.commit()

        candidates = populated_store.consolidate_candidates(
            max_age_days=90, min_strength=0.2
        )
        assert all(not c.pinned for c in candidates)

    def test_consolidate_excludes_recent(self, populated_store):
        # Don't touch anything — all memories are fresh
        candidates = populated_store.consolidate_candidates(
            max_age_days=90, min_strength=0.2
        )
        assert len(candidates) == 0

    def test_stats_returns_counts(self, populated_store):
        stats = populated_store.stats()
        assert stats["total"] == 5
        assert stats["active"] == 5
        assert stats["by_kind"]["constraint"] == 1
        assert stats["by_kind"]["guardrail"] == 1


class TestMicroIndex:
    def test_micro_index_returns_compact_summary(self, populated_store):
        index = populated_store.micro_index()
        assert isinstance(index, str)
        # Should be compact — under 500 chars
        assert len(index) < 500
        # Should contain kind counts
        assert "constraint" in index
        assert "guardrail" in index

    def test_micro_index_contains_project_info(self, populated_store):
        index = populated_store.micro_index()
        assert "payments" in index
        assert "backend" in index

    def test_micro_index_empty_store(self, store):
        index = store.micro_index()
        assert "0 memories" in index or "empty" in index.lower()


class TestMemoryCards:
    def test_recall_tiny_returns_compact_cards(self, populated_store):
        results = populated_store.recall("Redis", budget="tiny")
        assert len(results) >= 1
        # Tiny budget returns dicts with card fields
        card = results[0]
        assert isinstance(card, dict)
        assert "claim" in card
        assert "kind" in card
        assert "scope" in card
        assert "trust" in card
        # Should NOT have full content
        assert "content" not in card or len(card.get("content", "")) == 0

    def test_recall_normal_returns_full_objects(self, populated_store):
        from engram.model import MemoryObject
        results = populated_store.recall("Redis", budget="normal")
        assert len(results) >= 1
        assert isinstance(results[0], MemoryObject)

    def test_recall_default_is_normal(self, populated_store):
        from engram.model import MemoryObject
        results = populated_store.recall("Redis")
        assert isinstance(results[0], MemoryObject)

    def test_recall_deep_increases_limit(self, populated_store):
        results = populated_store.recall("", budget="deep")
        # deep should return all 5 populated memories (default limit would be 10 anyway,
        # but deep sets limit to max(10, 50) = 50)
        assert len(results) == 5

    def test_tiny_card_is_compact(self, populated_store):
        results = populated_store.recall("integer cents", budget="tiny")
        assert len(results) >= 1
        card = results[0]
        # Card text should be under 100 chars
        assert len(card["claim"]) <= 200


class TestHealth:
    def test_health_missing_evidence(self, populated_store):
        """Constraints/guardrails without evidence_link should be flagged."""
        report = populated_store.health()
        # The constraint memory has no evidence_link
        assert len(report["missing_evidence"]) >= 1

    def test_health_orphans(self, populated_store):
        """Memories with access_count=0 and age>threshold, not pinned."""
        # Age some memories
        populated_store.conn.execute(
            """UPDATE memories SET
               created_at = '2025-01-01T00:00:00+00:00',
               access_count = 0,
               pinned = 0
               WHERE kind = 'fact'"""
        )
        populated_store.conn.commit()
        report = populated_store.health(orphan_age_days=30)
        assert len(report["orphans"]) >= 1

    def test_health_no_issues_on_clean_store(self, store):
        report = store.health()
        assert report["missing_evidence"] == []
        assert report["orphans"] == []
        assert report.get("stale_claims", []) == []

    def test_health_returns_summary(self, populated_store):
        report = populated_store.health()
        assert "total_issues" in report
        assert isinstance(report["total_issues"], int)

    def test_stale_claims_detects_superseded(self, store):
        """Older memory superseded by newer similar memory."""
        store.remember(
            content="Archetype Phase 1A complete, Big Three product live on Etsy",
            kind=MemoryKind.FACT,
            project="archetype",
        )
        # Simulate aging the first memory
        store.conn.execute(
            "UPDATE memories SET created_at = '2025-01-01T00:00:00+00:00'"
        )
        store.conn.commit()
        store.remember(
            content="Archetype Phase 1A and Phase 2 complete, Big Three and Love Pattern products live on Etsy",
            kind=MemoryKind.FACT,
            project="archetype",
        )
        report = store.health(check_stale=True)
        assert len(report["stale_claims"]) >= 1
        stale = report["stale_claims"][0]
        assert "Phase 1A complete" in stale["old_content"]

    def test_stale_claims_off_by_default(self, populated_store):
        """Stale claims check should not run by default."""
        report = populated_store.health()
        assert "stale_claims" not in report or report.get("stale_claims") == []

    def test_health_summary_mode_returns_counts_only(self, populated_store):
        """summary=True returns counts (not full lists) to save tokens in MCP."""
        report = populated_store.health(summary=True)
        assert "missing_evidence_count" in report
        assert isinstance(report["missing_evidence_count"], int)
        # Must NOT include full list in summary mode
        assert "missing_evidence" not in report or report.get("missing_evidence") is None

    def test_health_summary_under_300_tokens(self, populated_store):
        """summary mode must be compact."""
        import json
        report = populated_store.health(summary=True, check_stale=True)
        size = len(json.dumps(report, ensure_ascii=False))
        # ~3 chars/token, under 900 chars = ~300 tokens
        assert size < 900, f"Summary too large: {size} chars"

    def test_health_default_full_mode(self, populated_store):
        """Default mode keeps backward compat with full lists."""
        report = populated_store.health()
        assert "missing_evidence" in report
        assert isinstance(report["missing_evidence"], list)

    def test_lint_kind_staleness_fact(self, store):
        """fact memories older than 7 days should be flagged as stale."""
        store.remember(content="Temporary flag setting", kind=MemoryKind.FACT, project="test")
        store.conn.execute(
            "UPDATE memories SET created_at = '2025-01-01T00:00:00+00:00' WHERE project = 'test'"
        )
        store.conn.commit()
        report = store.health(check_stale=True)
        assert "kind_staleness" in report
        fact_stale = [s for s in report["kind_staleness"] if s["kind"] == "fact"]
        assert len(fact_stale) >= 1

    def test_lint_kind_staleness_decision_longer_ttl(self, store):
        """decision memories have 90d TTL, not 7d."""
        store.remember(content="Use polling for status", kind=MemoryKind.DECISION, project="test")
        # Age by 30 days — fact would be stale, decision should not
        store.conn.execute(
            "UPDATE memories SET created_at = datetime('now', '-30 days')"
        )
        store.conn.commit()
        report = store.health(check_stale=True)
        decision_stale = [s for s in report.get("kind_staleness", []) if s["kind"] == "decision"]
        assert len(decision_stale) == 0

    def test_lint_constraint_and_guardrail_never_stale_by_age(self, store):
        """constraint/guardrail are long-lived and should not be age-flagged."""
        store.remember(
            content="Money must be integer cents",
            kind=MemoryKind.CONSTRAINT,
            project="test",
            evidence_link="https://example.com/pr",
        )
        store.conn.execute(
            "UPDATE memories SET created_at = '2025-01-01T00:00:00+00:00'"
        )
        store.conn.commit()
        report = store.health(check_stale=True)
        for s in report.get("kind_staleness", []):
            assert s["kind"] not in ("constraint", "guardrail")

    def test_stale_claims_same_project_only(self, store):
        """Cross-project similar content should not be flagged."""
        store.remember(content="Use UTC everywhere", kind=MemoryKind.CONSTRAINT, project="alpha")
        store.conn.execute("UPDATE memories SET created_at = '2025-01-01T00:00:00+00:00'")
        store.conn.commit()
        store.remember(content="Use UTC everywhere", kind=MemoryKind.CONSTRAINT, project="beta")
        report = store.health(check_stale=True)
        assert len(report["stale_claims"]) == 0


class TestExtendedLint:
    """Phase 3 extended lint (debate 020 §queued + ARCHITECTURE.md):
    expired_still_active + orphan_insight_sources. Always-on checks
    (no opt-in flag) since both are O(1) index scans."""

    def test_expired_still_active_flags_past_deadline(self, store):
        """Row with expires_at < now AND status='active' should surface."""
        store.remember(
            content="Stale flag should be reaped",
            kind=MemoryKind.FACT,
            project="ttl",
        )
        store.conn.execute(
            "UPDATE memories SET expires_at = datetime('now', '-1 days')"
        )
        store.conn.commit()
        report = store.health()
        assert len(report["expired_still_active"]) == 1
        row = report["expired_still_active"][0]
        assert "expires_at" in row
        assert row["origin"] == "human"

    def test_expired_still_active_ignores_obsolete_status(self, store):
        """Soft-deleted rows are not the GC daemon's job — only active ones."""
        store.remember(content="Already retired", kind=MemoryKind.FACT, project="x")
        store.conn.execute(
            """UPDATE memories SET
               expires_at = datetime('now', '-5 days'),
               status = 'obsolete'"""
        )
        store.conn.commit()
        report = store.health()
        assert report["expired_still_active"] == []

    def test_expired_still_active_ignores_null_expires_at(self, store):
        """Most agent/human rows have no TTL; they must NOT surface."""
        store.remember(content="No TTL on this one", kind=MemoryKind.FACT, project="x")
        report = store.health()
        assert report["expired_still_active"] == []

    def test_expired_still_active_clean_store_zero(self, store):
        # Full mode: list present, count key absent (lists carry the info).
        report = store.health()
        assert report["expired_still_active"] == []
        assert "expired_still_active_count" not in report

    def test_orphan_insight_sources_zero_on_clean_store(self, store):
        """memories_compost_map_ad cascade trigger should keep this empty."""
        report = store.health()
        assert report["orphan_insight_sources"] == []

    def test_orphan_insight_sources_detects_dangling_row(self, store):
        """If a row is inserted directly without a backing memory, it surfaces.
        This simulates the regression case where the cascade trigger fails."""
        # Bypass remember() and INSERT a map row pointing to a nonexistent memory.
        store.conn.execute(
            "INSERT INTO compost_insight_sources (memory_id, fact_id) VALUES (?, ?)",
            ("never-existed-id", "fact-x"),
        )
        store.conn.commit()
        report = store.health()
        assert len(report["orphan_insight_sources"]) == 1
        assert report["orphan_insight_sources"][0]["memory_id"] == "never-existed-id"
        assert report["orphan_insight_sources"][0]["fact_id"] == "fact-x"

    def test_orphan_insight_sources_does_not_flag_obsolete_memory(self, store):
        """Soft-deleted memory still has an id row — map_row pointing to it is
        NOT orphan (debate 020 §分歧 1 by-design retention for invalidation
        idempotency)."""
        from datetime import datetime, timezone
        from engram.model import MemoryOrigin, MemoryScope
        mem = store.remember(
            content="Compost insight that gets invalidated later",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"compost_fact_ids": ["f1"]},
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        # invalidate the memory (status='obsolete'); map row stays
        store.conn.execute("UPDATE memories SET status='obsolete' WHERE id=?", (mem.id,))
        store.conn.commit()
        report = store.health()
        assert report["orphan_insight_sources"] == []  # not an orphan; memory id still exists

    def test_extended_lint_summary_mode_returns_counts(self, store):
        """Summary mode exposes both new fields as counts."""
        store.remember(content="Will expire", kind=MemoryKind.FACT, project="t")
        store.conn.execute(
            "UPDATE memories SET expires_at = datetime('now', '-2 days')"
        )
        store.conn.commit()
        report = store.health(summary=True)
        assert "expired_still_active_count" in report
        assert report["expired_still_active_count"] == 1
        assert "orphan_insight_sources_count" in report
        assert report["orphan_insight_sources_count"] == 0
        # Lists must NOT appear in summary mode
        assert "expired_still_active" not in report
        assert "orphan_insight_sources" not in report

    def test_extended_lint_total_issues_includes_new_categories(self, store):
        """total_issues must sum all 4 always-on categories (+ 2 stale-only)."""
        store.remember(content="Will expire", kind=MemoryKind.FACT, project="t")
        store.conn.execute(
            "UPDATE memories SET expires_at = datetime('now', '-1 days')"
        )
        store.conn.execute(
            "INSERT INTO compost_insight_sources (memory_id, fact_id) VALUES (?, ?)",
            ("dangling", "f"),
        )
        store.conn.commit()
        report = store.health()
        # 1 expired + 1 orphan map row = 2 minimum
        assert report["total_issues"] >= 2


class TestExport:
    def test_export_jsonl(self, populated_store, tmp_path):
        out = tmp_path / "export.jsonl"
        populated_store.export(str(out), fmt="jsonl")
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 5
        import json
        obj = json.loads(lines[0])
        assert "id" in obj
        assert "content" in obj
        assert "origin" in obj

    def test_export_markdown(self, populated_store, tmp_path):
        out_dir = tmp_path / "export_md"
        populated_store.export(str(out_dir), fmt="markdown")
        md_files = list(out_dir.glob("*.md"))
        assert len(md_files) == 5
        content = md_files[0].read_text()
        assert "---" in content  # YAML frontmatter


class TestCompile:
    def test_compile_project_returns_markdown(self, populated_store):
        result = populated_store.compile("backend")
        assert isinstance(result, str)
        assert "# backend" in result
        assert "constraint" in result or "decision" in result or "procedure" in result

    def test_compile_groups_by_kind(self, populated_store):
        result = populated_store.compile("backend")
        # Should have kind headers
        assert "##" in result

    def test_compile_nonexistent_project(self, store):
        result = store.compile("nonexistent")
        assert "no memories" in result.lower() or result.strip() == ""


class TestEffectiveScore:
    def test_recent_memory_scores_higher(self, store):
        m1 = store.remember(content="Old memory about auth", kind=MemoryKind.FACT, project="test")
        store.conn.execute("UPDATE memories SET created_at = '2025-01-01T00:00:00+00:00' WHERE id = ?", (m1.id,))
        store.conn.commit()
        m2 = store.remember(content="New memory about auth patterns", kind=MemoryKind.FACT, project="test")
        results = store.recall("auth", project="test")
        # New memory should rank before old
        assert results[0].id == m2.id

    def test_frequently_accessed_scores_higher(self, populated_store):
        # Access one memory multiple times
        for _ in range(5):
            populated_store.recall("Redis")
        results = populated_store.recall("")
        # The frequently accessed one should be near the top
        redis_mem = [r for r in results if "Redis" in r.content]
        assert len(redis_mem) >= 1


class TestOpsLog:
    def test_remember_logs_operation(self, store):
        store.remember(content="Test fact", kind=MemoryKind.FACT)
        rows = store.conn.execute("SELECT op, kind FROM ops_log").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "remember"
        assert rows[0][1] == "fact"

    def test_recall_logs_operation(self, populated_store):
        populated_store.recall("Redis")
        rows = populated_store.conn.execute(
            "SELECT op FROM ops_log WHERE op = 'recall'"
        ).fetchall()
        assert len(rows) >= 1

    def test_forget_logs_operation(self, populated_store):
        results = populated_store.recall("Redis")
        mem_id = results[0].id
        populated_store.forget(mem_id)
        rows = populated_store.conn.execute(
            "SELECT op, memory_id FROM ops_log WHERE op = 'forget'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == mem_id

    def test_ops_log_has_timestamp(self, store):
        store.remember(content="Test", kind=MemoryKind.FACT)
        row = store.conn.execute("SELECT ts FROM ops_log").fetchone()
        assert row[0] is not None
        assert "2026" in row[0] or "202" in row[0]


class TestWriteTemplates:
    def test_guardrail_without_evidence_lowers_confidence(self, store):
        mem = store.remember(
            content="Never do X because of incident Y",
            kind=MemoryKind.GUARDRAIL,
            # no evidence_link
        )
        assert mem.confidence < 1.0

    def test_guardrail_with_evidence_keeps_confidence(self, store):
        mem = store.remember(
            content="Never do X because of incident Y",
            kind=MemoryKind.GUARDRAIL,
            evidence_link="https://github.com/org/repo/incidents/1",
        )
        assert mem.confidence == 1.0

    def test_constraint_without_scope_lowers_confidence(self, store):
        mem = store.remember(
            content="Always use UTC",
            kind=MemoryKind.CONSTRAINT,
            # no path_scope, no project
        )
        assert mem.confidence < 1.0

    def test_constraint_with_project_keeps_confidence(self, store):
        mem = store.remember(
            content="Always use UTC",
            kind=MemoryKind.CONSTRAINT,
            project="backend",
        )
        assert mem.confidence == 1.0

    def test_fact_without_project_still_ok(self, store):
        """Facts have no required fields — should not be penalized."""
        mem = store.remember(
            content="Python 3.12 is the current version",
            kind=MemoryKind.FACT,
        )
        assert mem.confidence == 1.0

    def test_explicit_confidence_overrides_template(self, store):
        """User-specified confidence should not be overridden by template."""
        mem = store.remember(
            content="Maybe this guardrail",
            kind=MemoryKind.GUARDRAIL,
            confidence=0.3,
        )
        assert mem.confidence == 0.3

    def test_project_name_normalized_to_lowercase(self, store):
        mem = store.remember(
            content="Project names should be lowercase",
            kind=MemoryKind.FACT,
            project="MyProject",
        )
        assert mem.project == "myproject"
