"""Architecture invariant tests.

These tests enforce the architectural decisions from debates 016/017/018
at CI level, not just in documentation. They are the load-bearing guards
that keep 10-year design intent from rotting.

Invariants:
    1. Engram core code MUST NOT import LLM SDKs (zero-LLM runtime promise)
    2. Engram core code MUST NOT import compost_* (decoupling)
    3. Schema MUST have scope enum + origin CHECK + content length CHECK
    4. compost_cache MUST enforce origin='compiled' at schema level
    5. memories MUST NOT allow origin='compiled' (trust boundary)
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).parent.parent / "src" / "engram"

# Modules that form the core zero-LLM runtime path.
# server.py + cli.py are adapters but still shouldn't pull LLM SDKs directly.
CORE_MODULES = [
    "db.py",
    "model.py",
    "store.py",
    "proactive.py",
    "server.py",
    "cli.py",
]

LLM_SDK_FORBIDDEN = (
    "anthropic",
    "openai",
    "google.generativeai",
    "google.genai",
    "cohere",
    "litellm",
)

COMPOST_FORBIDDEN = ("compost",)


def _collect_imports(py_path: Path) -> set[str]:
    """Return all top-level module names imported by a Python file."""
    tree = ast.parse(py_path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
                imports.add(node.module)
    return imports


class TestNoLLMInCore:
    """Engram's zero-LLM runtime promise. Debate 016 C1 / 017 C5."""

    @pytest.mark.parametrize("module", CORE_MODULES)
    def test_no_llm_sdk_import(self, module):
        path = SRC_ROOT / module
        assert path.exists(), f"Missing core module: {path}"
        imports = _collect_imports(path)
        for forbidden in LLM_SDK_FORBIDDEN:
            matching = [i for i in imports if i == forbidden or i.startswith(forbidden + ".")]
            assert not matching, (
                f"{module} imports LLM SDK {matching}. "
                f"Engram core must be zero-LLM (debate 016 synthesis C1)."
            )


class TestNoCompostImport:
    """Engram must not depend on Compost code. Debate 016 C5."""

    @pytest.mark.parametrize("module", CORE_MODULES)
    def test_no_compost_import(self, module):
        path = SRC_ROOT / module
        imports = _collect_imports(path)
        for forbidden in COMPOST_FORBIDDEN:
            matching = [
                i for i in imports
                if i == forbidden or i.startswith(forbidden + ".") or i.startswith(forbidden + "_")
            ]
            assert not matching, (
                f"{module} imports Compost code {matching}. "
                f"Cross-system coupling must go through MCP/HTTP only."
            )


class TestSchemaInvariants:
    """Schema-level hard constraints. Debate 018 E + 017 M2."""

    @pytest.fixture
    def conn(self, tmp_path):
        from engram.db import init_db
        return init_db(str(tmp_path / "schema_test.db"))

    def test_memories_has_scope_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        assert "scope" in cols

    def test_memories_origin_check_excludes_compiled(self, conn):
        # 'compiled' is still forbidden (only human/agent/compost allowed)
        with pytest.raises(sqlite3.IntegrityError, match="origin"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("t1", "x", "s", "fact", "compiled", "test", "[]", "active", 0.5, 0, "project", "2026-04-16"),
            )

    def test_memories_origin_accepts_compost(self, conn):
        # 'compost' is a valid origin (debate 019 Q1)
        # Must also satisfy: kind=insight + source_trace + expires_at
        conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status, strength,
                pinned, scope, source_trace, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("tc", "x", "s", "insight", "compost", None, "[]", "active", 0.85, 0,
             "global", '{"compost_fact_ids":["f1"]}', "2099-01-01", "2026-04-16"),
        )
        # No exception = pass

    def test_compost_origin_requires_insight_kind(self, conn):
        # origin=compost must be paired with kind=insight
        with pytest.raises(sqlite3.IntegrityError, match="kind"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, source_trace, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("tc2", "x", "s", "fact", "compost", "test", "[]", "active", 0.5, 0,
                 "project", "{}", "2099-01-01", "2026-04-16"),
            )

    def test_compost_origin_requires_source_trace(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="source_trace"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, expires_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("tc3", "x", "s", "insight", "compost", None, "[]", "active", 0.5, 0,
                 "global", "2099-01-01", "2026-04-16"),
            )

    def test_compost_origin_requires_expires_at(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="expires_at"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, source_trace, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("tc4", "x", "s", "insight", "compost", None, "[]", "active", 0.5, 0,
                 "global", "{}", "2026-04-16"),
            )

    def test_source_trace_must_be_valid_json(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="source_trace"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, source_trace, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("tc5", "x", "s", "fact", "human", "test", "[]", "active", 0.5, 0,
                 "project", "not-valid-json", "2026-04-16"),
            )

    def test_memories_length_check_4000(self, conn):
        long_content = "x" * 4001
        with pytest.raises(sqlite3.IntegrityError, match="length"):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("t2", long_content, "s", "fact", "human", "test", "[]", "active", 0.5, 0, "project", "2026-04-16"),
            )

    def test_memories_scope_coherence_check(self, conn):
        # scope='meta' requires project IS NULL
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("t3", "x", "s", "fact", "human", "some_project", "[]", "active", 0.5, 0, "meta", "2026-04-16"),
            )

    def test_memories_scope_project_requires_project(self, conn):
        # scope='project' requires project NOT NULL
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO memories
                   (id, content, summary, kind, origin, project, tags, status, strength,
                    pinned, scope, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("t4", "x", "s", "fact", "human", None, "[]", "active", 0.5, 0, "project", "2026-04-16"),
            )

    def test_compost_cache_table_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='compost_cache'"
        ).fetchone()
        assert row is not None

    def test_compost_cache_only_accepts_compiled_origin(self, conn):
        with pytest.raises(sqlite3.IntegrityError, match="origin"):
            conn.execute(
                """INSERT INTO compost_cache
                   (cache_id, project, prompt_hash, source_hash, content,
                    ttl_expires_at, origin)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("c1", "p", "h1", "s1", "x", "2099-01-01", "human"),
            )

    def test_recall_miss_log_table_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='recall_miss_log'"
        ).fetchone()
        assert row is not None

    def test_compost_insight_sources_table_exists(self, conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='compost_insight_sources'"
        ).fetchone()
        assert row is not None

    def test_memory_scores_excludes_expired(self, conn):
        # Expired compost insight should not appear in memory_scores view
        import datetime as dt
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        # Expired
        conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status, strength,
                pinned, scope, source_trace, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("exp", "expired", "s", "insight", "compost", None, "[]", "active", 0.5, 0,
             "global", "{}", past, now),
        )
        # Not expired
        conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, tags, status, strength,
                pinned, scope, source_trace, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("live", "live", "s", "insight", "compost", None, "[]", "active", 0.5, 0,
             "global", "{}", future, now),
        )
        ids = {r[0] for r in conn.execute("SELECT id FROM memory_scores").fetchall()}
        assert "live" in ids
        assert "exp" not in ids


class TestNoEmbeddingColumn:
    """Debate 016 C6: schema禁 embedding 列 until v3.5+ re-evaluation."""

    @pytest.fixture
    def conn(self, tmp_path):
        from engram.db import init_db
        return init_db(str(tmp_path / "schema_test.db"))

    def test_memories_has_no_embedding_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        assert "embedding" not in cols, (
            "Adding embedding column is forbidden by debate 016 synthesis. "
            "If recall_miss rate >15% triggers re-evaluation, go through new debate."
        )

    def test_compost_cache_has_no_embedding_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(compost_cache)").fetchall()}
        assert "embedding" not in cols
