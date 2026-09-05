"""Regression gates for deterministic multilingual recall and derived indexes."""

import sqlite3

import pytest

from engram.model import MemoryKind
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    instance = MemoryStore(str(tmp_path / "memory.db"))
    yield instance
    instance.close()


def test_chinese_substrings_and_literal_id(store):
    memory = store.remember(
        content="我们使用整数分保存金额并改进检索速度", kind=MemoryKind.CONSTRAINT
    )
    for query in ("整数分", "检索", "金额", memory.id):
        assert memory.id in [m.id for m in store.recall(query)]


def test_cjk_phrase_does_not_join_disconnected_bigrams(store):
    store.remember(content="整数与数分来自不同片段", kind=MemoryKind.FACT)
    assert store.recall("整数分") == []


def test_cjk_filters_and_lifecycle(store):
    keep = store.remember(
        content="付款金额使用整数分", kind=MemoryKind.CONSTRAINT, project="payments"
    )
    gone = store.remember(
        content="订单索引需要整数分字段", kind=MemoryKind.FACT, project="orders"
    )
    store.forget(gone.id)
    assert [m.id for m in store.recall("整数分", project="payments")] == [keep.id]
    assert store.recall("整数分", project="orders") == []
    store.resolve(keep.id)
    assert [m.id for m in store.recall("整数分")] == [keep.id]


def test_index_upgrade_rebuild_and_raw_sql_writer(store):
    from engram.search_index import index_status, rebuild_indexes

    path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    memory = store.remember(content="中文检索保存原始证据", kind=MemoryKind.FACT)
    # Rebuild is derived state only; all base fields must be preserved.
    before = store.conn.execute("SELECT * FROM memories").fetchall()
    rebuild_indexes(store.conn)
    assert store.conn.execute("SELECT * FROM memories").fetchall() == before
    assert index_status(store.conn)["ok"]
    assert store.recall("检索")[0].id == memory.id
    # SQL triggers work for connections without Python registered functions.
    with sqlite3.connect(path) as other:
        other.execute("DELETE FROM memories WHERE id = ?", (memory.id,))
    assert store.recall("检索") == []
    assert index_status(store.conn)["ok"]


def test_upgrade_backfills_existing_memories(tmp_path):
    from engram.db import _SCHEMA
    from engram.search_index import index_status

    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as old:
        old.executescript(_SCHEMA)
        old.execute(
            "INSERT INTO memories(id,content,summary,kind,scope,created_at) VALUES ('legacy','保存中文检索的历史','中文历史','fact','global',datetime('now'))"
        )
    with_store = MemoryStore(path)
    try:
        assert with_store.recall("检索")[0].id == "legacy"
        assert index_status(with_store.conn)["ok"]
    finally:
        with_store.close()


def test_index_drift_detection_and_atomic_rebuild(store):
    from engram.search_index import index_status, rebuild_indexes

    memory = store.remember(content="保存可靠的中文检索证据", kind=MemoryKind.FACT)
    store.conn.execute("DELETE FROM memories_cjk")
    store.conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")
    store.conn.commit()
    assert not index_status(store.conn)["ok"]
    assert rebuild_indexes(store.conn)["ok"]
    assert store.recall("检索")[0].id == memory.id
    store.conn.execute(
        "CREATE TRIGGER fail_rebuild BEFORE UPDATE ON search_index_state BEGIN SELECT RAISE(ABORT,'injected'); END"
    )
    with pytest.raises(sqlite3.DatabaseError, match="injected"):
        rebuild_indexes(store.conn)
    assert store.recall("检索")[0].id == memory.id


def test_indexes_cli(tmp_path):
    import json

    from tests.test_cli import run_cli

    path = str(tmp_path / "cli.db")
    first = run_cli("indexes", env_db=path)
    assert first.returncode == 0
    assert json.loads(first.stdout)["ok"]
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO memories_cjk(rowid,grams) VALUES (999999,'orphan')")
    assert run_cli("indexes", env_db=path).returncode == 1
    rebuilt = run_cli("indexes", "--rebuild", env_db=path)
    assert rebuilt.returncode == 0
    assert json.loads(rebuilt.stdout)["ok"]


def test_unicode_escaped_tags_and_supplementary_han(store):
    memory = store.remember(
        content="Tagged search reference", kind=MemoryKind.FACT, tags=["可靠检索"]
    )
    assert store.recall("检索")[0].id == memory.id
    rare = store.remember(content="边界字符𠀀𠀁保存", kind=MemoryKind.FACT)
    assert store.recall("𠀀𠀁")[0].id == rare.id
