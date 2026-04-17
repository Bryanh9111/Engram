"""Tests for `engram export-stream` CLI — scripted batch equivalent of
the MCP stream_for_compost tool, emitting JSONL to stdout.

Per contract line 110: "CLI engram export-stream --kinds=... --since=...
— same handler underneath, for scripted batch".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engram.cli import main as cli_main
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
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "cli_export.db"
    monkeypatch.setenv("ENGRAM_DB", str(path))
    return str(path)


@pytest.fixture
def seed_store(db_path):
    s = MemoryStore(db_path)
    yield s
    s.close()


def _run(capsys, *argv) -> list[dict]:
    cli_main(list(argv))
    out = capsys.readouterr().out.strip()
    if not out:
        return []
    return [json.loads(line) for line in out.splitlines()]


class TestBasicShape:
    def test_empty_store_prints_nothing(self, capsys, db_path):
        assert _run(capsys, "export-stream") == []

    def test_jsonl_line_per_entry(self, capsys, db_path, seed_store):
        seed_store.remember(content="first", kind=MemoryKind.FACT, project="p")
        seed_store.remember(content="second", kind=MemoryKind.FACT, project="p")
        entries = _run(capsys, "export-stream")
        assert len(entries) == 2

    def test_contract_shape_matches_mcp_tool(self, capsys, db_path, seed_store):
        seed_store.remember(
            content="cli shape check", kind=MemoryKind.FACT,
            project="p", tags=["a", "b"],
        )
        [entry] = _run(capsys, "export-stream")
        assert set(entry.keys()) == CONTRACT_KEYS

    def test_ordering_ascending_by_created_at(self, capsys, db_path, seed_store):
        now = datetime.now(timezone.utc)
        for i, ts in enumerate([now - timedelta(hours=3), now - timedelta(hours=1), now]):
            seed_store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (f"m{i}", f"c{i}", f"s{i}", ts.isoformat()),
            )
        seed_store.conn.commit()

        entries = _run(capsys, "export-stream")
        assert [e["memory_id"] for e in entries] == ["m0", "m1", "m2"]


class TestFilters:
    def test_kinds_flag_single(self, capsys, db_path, seed_store):
        seed_store.remember(content="a fact one", kind=MemoryKind.FACT, project="p")
        seed_store.remember(content="a decision one", kind=MemoryKind.DECISION, project="p")
        entries = _run(capsys, "export-stream", "--kinds", "fact")
        assert {e["kind"] for e in entries} == {"fact"}

    def test_kinds_flag_multiple(self, capsys, db_path, seed_store):
        seed_store.remember(content="f1 content", kind=MemoryKind.FACT, project="p")
        seed_store.remember(content="d1 content", kind=MemoryKind.DECISION, project="p")
        seed_store.remember(content="p1 content", kind=MemoryKind.PROCEDURE, project="p")
        entries = _run(capsys, "export-stream", "--kinds", "fact", "--kinds", "decision")
        assert {e["kind"] for e in entries} == {"fact", "decision"}

    def test_since_flag(self, capsys, db_path, seed_store):
        now = datetime.now(timezone.utc)
        seed_store.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status,
                strength, pinned, scope, created_at)
               VALUES ('old', 'old', 's', 'fact', 'human', 'p', '[]',
                       'active', 0.5, 0, 'project', ?)""",
            ((now - timedelta(hours=3)).isoformat(),),
        )
        seed_store.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status,
                strength, pinned, scope, created_at)
               VALUES ('new', 'new', 's', 'fact', 'human', 'p', '[]',
                       'active', 0.5, 0, 'project', ?)""",
            (now.isoformat(),),
        )
        seed_store.conn.commit()

        cutoff = (now - timedelta(hours=1)).isoformat()
        entries = _run(capsys, "export-stream", "--since", cutoff)
        assert [e["memory_id"] for e in entries] == ["new"]

    def test_project_flag(self, capsys, db_path, seed_store):
        seed_store.remember(content="pay one", kind=MemoryKind.FACT, project="pay")
        seed_store.remember(content="bill one", kind=MemoryKind.FACT, project="bill")
        entries = _run(capsys, "export-stream", "--project", "pay")
        assert len(entries) == 1
        assert entries[0]["project"] == "pay"


class TestFeedbackLoopFlag:
    def _insight(self, store):
        return store.remember(
            content="insight to exclude",
            kind=MemoryKind.INSIGHT,
            origin=MemoryOrigin.COMPOST,
            scope=MemoryScope.GLOBAL,
            source_trace={"compost_fact_ids": ["f1"]},
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )

    def test_compost_excluded_by_default(self, capsys, db_path, seed_store):
        seed_store.remember(content="a human fact", kind=MemoryKind.FACT, project="p")
        self._insight(seed_store)
        entries = _run(capsys, "export-stream")
        assert all(e["origin"] != "compost" for e in entries)

    def test_include_compost_flag(self, capsys, db_path, seed_store):
        seed_store.remember(content="a human fact", kind=MemoryKind.FACT, project="p")
        self._insight(seed_store)
        entries = _run(capsys, "export-stream", "--include-compost")
        assert {e["origin"] for e in entries} == {"human", "compost"}


class TestLimit:
    def test_limit_caps_rows(self, capsys, db_path, seed_store):
        for i in range(5):
            seed_store.conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status,
                    strength, pinned, scope, created_at)
                   VALUES (?, ?, ?, 'fact', 'human', 'p', '[]', 'active',
                           0.5, 0, 'project', ?)""",
                (
                    f"m{i}",
                    f"c{i}",
                    f"s{i}",
                    (datetime.now(timezone.utc) - timedelta(seconds=100 - i)).isoformat(),
                ),
            )
        seed_store.conn.commit()

        entries = _run(capsys, "export-stream", "--limit", "2")
        assert [e["memory_id"] for e in entries] == ["m0", "m1"]
