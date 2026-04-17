"""Tests for MemoryObject model and SQLite schema."""

import sqlite3
from datetime import datetime, timezone

import pytest

from engram.model import MemoryObject, MemoryKind, MemoryOrigin, MemoryStatus


class TestMemoryObject:
    def test_create_constraint_memory(self):
        mem = MemoryObject(
            content="Money values must use integer cents end-to-end",
            kind=MemoryKind.CONSTRAINT,
            project="payments",
        )
        assert mem.content == "Money values must use integer cents end-to-end"
        assert mem.kind == MemoryKind.CONSTRAINT
        assert mem.project == "payments"
        assert mem.status == MemoryStatus.ACTIVE
        assert mem.confidence == 1.0
        assert mem.strength == 0.5
        assert mem.pinned is False
        assert mem.access_count == 0
        assert mem.id  # auto-generated

    def test_create_guardrail_with_evidence(self):
        mem = MemoryObject(
            content="Never parallelize these two migrations",
            kind=MemoryKind.GUARDRAIL,
            project="backend",
            evidence_link="https://github.com/org/repo/issues/42",
            confidence=0.95,
            path_scope="migrations/*",
        )
        assert mem.kind == MemoryKind.GUARDRAIL
        assert mem.evidence_link == "https://github.com/org/repo/issues/42"
        assert mem.confidence == 0.95
        assert mem.path_scope == "migrations/*"

    def test_create_procedure_memory(self):
        mem = MemoryObject(
            content="Integration tests: seed Redis -> start worker -> start API",
            kind=MemoryKind.PROCEDURE,
        )
        assert mem.kind == MemoryKind.PROCEDURE

    def test_create_decision_memory(self):
        mem = MemoryObject(
            content="Use polling not websockets for job status",
            kind=MemoryKind.DECISION,
        )
        assert mem.kind == MemoryKind.DECISION

    def test_create_fact_memory(self):
        mem = MemoryObject(
            content="UserSearchV2 behind SEARCH_V2=1 flag",
            kind=MemoryKind.FACT,
        )
        assert mem.kind == MemoryKind.FACT

    def test_all_six_kinds_exist(self):
        # 5 user-facing kinds + 1 compost-reserved (debate 019 Q1)
        kinds = set(MemoryKind)
        assert kinds == {
            MemoryKind.CONSTRAINT,
            MemoryKind.DECISION,
            MemoryKind.PROCEDURE,
            MemoryKind.FACT,
            MemoryKind.GUARDRAIL,
            MemoryKind.INSIGHT,  # debate 019: Compost-produced synthesis
        }

    def test_all_statuses_exist(self):
        statuses = set(MemoryStatus)
        assert statuses == {
            MemoryStatus.ACTIVE,
            MemoryStatus.SUSPECT,
            MemoryStatus.OBSOLETE,
            MemoryStatus.RESOLVED,
        }

    def test_all_origins_exist(self):
        origins = set(MemoryOrigin)
        assert origins == {
            MemoryOrigin.HUMAN,
            MemoryOrigin.AGENT,
            MemoryOrigin.COMPOST,
        }

    def test_default_origin_is_human(self):
        mem = MemoryObject(
            content="Test memory",
            kind=MemoryKind.FACT,
        )
        assert mem.origin == MemoryOrigin.HUMAN

    def test_origin_can_be_set(self):
        mem = MemoryObject(
            content="AI discovered pattern",
            kind=MemoryKind.FACT,
            origin=MemoryOrigin.AGENT,
        )
        assert mem.origin == MemoryOrigin.AGENT

    def test_summary_auto_generated_if_not_provided(self):
        mem = MemoryObject(
            content="A very long memory content that describes something in detail "
            "about how the authentication system works with the new SSO provider "
            "and the specific configuration needed for SAML assertions.",
            kind=MemoryKind.FACT,
        )
        # summary should be set (truncated content if not provided)
        assert mem.summary
        assert len(mem.summary) <= 200

    def test_summary_preserved_if_provided(self):
        mem = MemoryObject(
            content="Long detailed content here",
            kind=MemoryKind.FACT,
            summary="Short summary",
        )
        assert mem.summary == "Short summary"

    def test_timestamps_auto_set(self):
        before = datetime.now(timezone.utc)
        mem = MemoryObject(content="test", kind=MemoryKind.FACT)
        after = datetime.now(timezone.utc)
        assert before <= mem.created_at <= after
        assert mem.accessed_at is None
        assert mem.last_verified is None


class TestDatabase:
    def test_init_creates_tables(self, tmp_path):
        from engram.db import init_db

        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))

        # Check memories table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        )
        assert cursor.fetchone() is not None

        # Check FTS virtual table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        )
        assert cursor.fetchone() is not None

        conn.close()

    def test_memories_table_schema(self, tmp_path):
        from engram.db import init_db

        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))

        cursor = conn.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id",
            "content",
            "summary",
            "kind",
            "origin",
            "project",
            "path_scope",
            "tags",
            "confidence",
            "evidence_link",
            "status",
            "strength",
            "pinned",
            "created_at",
            "accessed_at",
            "last_verified",
            "access_count",
        }
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"

        conn.close()

    def test_init_is_idempotent(self, tmp_path):
        from engram.db import init_db

        db_path = tmp_path / "test.db"
        conn1 = init_db(str(db_path))
        conn1.close()
        # Second init should not raise
        conn2 = init_db(str(db_path))
        conn2.close()

    def test_wal_mode_enabled(self, tmp_path):
        from engram.db import init_db

        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"
        conn.close()
