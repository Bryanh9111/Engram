"""Tests for Engram MCP Server tool definitions."""

import json

import pytest

from engram.model import MemoryKind
from engram.store import MemoryStore


class TestMCPTools:
    """Test MCP tool handler functions directly (without MCP transport)."""

    def test_remember_tool(self, tmp_path):
        from engram.server import _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        result = _handle_remember(
            store,
            content="Money values must use integer cents",
            kind="constraint",
            project="payments",
        )
        assert "id" in result
        assert result["kind"] == "constraint"

    def test_recall_tool(self, tmp_path):
        from engram.server import _handle_recall, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Redis must be seeded", kind="procedure")
        result = _handle_recall(store, query="Redis")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "Redis" in result[0]["content"]

    def test_forget_tool(self, tmp_path):
        from engram.server import _handle_forget, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        mem = _handle_remember(store, content="Temp fact", kind="fact")
        result = _handle_forget(store, memory_id=mem["id"])
        assert result["status"] == "forgotten"

    def test_stats_tool(self, tmp_path):
        from engram.server import _handle_remember, _handle_stats

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Test", kind="fact")
        result = _handle_stats(store)
        assert result["total"] == 1

    def test_proactive_tool(self, tmp_path):
        from engram.server import _handle_proactive, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(
            store,
            content="Never use floats for money",
            kind="constraint",
            path_scope="billing/*",
        )
        result = _handle_proactive(store, file_path="billing/calc.py")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_consolidate_tool(self, tmp_path):
        from engram.server import _handle_consolidate, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Old fact", kind="fact")
        result = _handle_consolidate(store)
        assert "candidates" in result

    def test_remember_with_origin(self, tmp_path):
        from engram.server import _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        result = _handle_remember(
            store, content="AI found pattern", kind="fact", origin="agent"
        )
        assert result["origin"] == "agent"

    def test_recall_with_budget(self, tmp_path):
        from engram.server import _handle_recall, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Test constraint", kind="constraint")
        result = _handle_recall(store, query="constraint", budget="tiny")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "claim" in result[0]

    def test_health_tool(self, tmp_path):
        from engram.server import _handle_health, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Missing evidence", kind="constraint")
        # MCP health returns summary mode (counts only) to save tokens
        result = _handle_health(store)
        assert "missing_evidence_count" in result
        assert result["missing_evidence_count"] >= 1

    def test_micro_index_tool(self, tmp_path):
        from engram.server import _handle_micro_index, _handle_remember

        store = MemoryStore(str(tmp_path / "test.db"))
        _handle_remember(store, content="Test", kind="fact")
        result = _handle_micro_index(store)
        assert "fact" in result
        assert "1" in result
