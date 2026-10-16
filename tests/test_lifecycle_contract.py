"""State transitions and lossless pagination across the Compost boundary."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from engram.model import MemoryKind
from engram.server import _handle_stream_for_compost, create_server
from engram.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    with_store = MemoryStore(str(tmp_path / 'engram.db'))
    yield with_store
    with_store.close()


def test_resolve_is_audited_idempotent_and_never_resurrects(store):
    mem = store.remember('Resolve lifecycle fixture', MemoryKind.DECISION, project='audit')
    assert store.resolve(mem.id)['status'] == 'resolved'
    assert store.resolve(mem.id)['status'] == 'already_resolved'
    assert store.conn.execute("SELECT count(*) FROM ops_log WHERE op='resolve'").fetchone()[0] == 1
    store.forget(mem.id)
    with pytest.raises(ValueError, match='obsolete'):
        store.resolve(mem.id)
    assert store.recall('lifecycle') == []
    with pytest.raises(ValueError, match='not found'):
        store.resolve('missing')


def test_resolve_rolls_back_when_audit_fails(store):
    mem = store.remember('Atomic transition fixture', MemoryKind.FACT)
    store.conn.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON ops_log BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
    with pytest.raises(Exception, match='audit unavailable'):
        store.resolve(mem.id)
    assert store.conn.execute('SELECT status FROM memories WHERE id=?', (mem.id,)).fetchone()[0] == 'active'


def test_resolve_mcp_uses_store_and_rejects_missing(tmp_path, monkeypatch):
    monkeypatch.setenv('ENGRAM_DB', str(tmp_path / 'mcp.db'))
    server = create_server()
    with pytest.raises(Exception, match='not found'):
        asyncio.run(server.call_tool('resolve', {'memory_id': 'missing'}))


def test_pages_keep_identical_and_submillisecond_timestamps(store):
    ids = []
    for i in range(5):
        mem = store.remember(f'Page fixture {i}', MemoryKind.FACT, project=f'page-{i}')
        ids.append(mem.id)
    for i, mid in enumerate(ids):
        ts = '2026-08-01T00:00:00.123456+00:00' if i < 3 else '2026-08-01T00:00:00.123457+00:00'
        store.conn.execute('UPDATE memories SET created_at=? WHERE id=?', (ts, mid))
    store.conn.commit()
    seen = []
    since = None
    after_id = None
    for _ in range(4):
        page = _handle_stream_for_compost(store, since=since, after_id=after_id, limit=2)
        seen.extend(r['memory_id'] for r in page)
        if not page:
            break
        since, after_id = page[-1]['updated_at'], page[-1]['memory_id']
    assert len(seen) == 5
    assert set(seen) == set(ids)


def test_state_projection_includes_revoked_expired_and_missing(store):
    active = store.remember('active state', MemoryKind.FACT, project='active')
    revoked = store.remember('revoked state', MemoryKind.FACT, project='revoked')
    expired = store.remember('expired state', MemoryKind.FACT, project='expired', expires_at=datetime.now(UTC)-timedelta(days=1))
    store.forget(revoked.id)
    rows = {r['memory_id']: r for r in store.states_for_compost([active.id, revoked.id, expired.id, 'missing'])}
    assert rows[active.id]['searchable'] is True
    assert rows[revoked.id]['status'] == 'obsolete'
    assert rows[expired.id]['searchable'] is False
    assert rows['missing']['status'] == 'missing'
    assert all('content' not in r for r in rows.values())
    assert store.states_for_compost([]) == []
    with pytest.raises(ValueError):
        store.states_for_compost(['x'] * 1001)


def test_recall_visibility_matches_states_for_compost(store):
    fixtures = {
        'active': 'Visibility fixture: ledger export runs nightly',
        'resolved': 'Visibility fixture: cache warmer retired in March',
        'suspect': 'Visibility fixture: vendor quote may be outdated',
        'obsolete': 'Visibility fixture: old staging URL decommissioned',
    }
    ids = {}
    for status, content in fixtures.items():
        mem = store.remember(content, MemoryKind.FACT, project='visibility')
        store.conn.execute('UPDATE memories SET status=? WHERE id=?', (status, mem.id))
        ids[status] = mem.id
    store.conn.commit()

    searchable = {r['memory_id']: r['searchable'] for r in store.states_for_compost(list(ids.values()))}
    recalled = {m.id for m in store.recall('visibility fixture', project='visibility')}

    assert searchable[ids['active']] is True
    assert searchable[ids['resolved']] is True
    assert searchable[ids['suspect']] is False
    assert searchable[ids['obsolete']] is False
    for status, mid in ids.items():
        assert (mid in recalled) == searchable[mid], status


def test_cli_state_export_and_tied_cursor(tmp_path):
    import json

    from tests.test_cli import run_cli

    path = str(tmp_path / 'export.db')
    db = MemoryStore(path)
    mem = db.remember('cursor export fixture', MemoryKind.FACT)
    created = mem.created_at.isoformat()
    db.close()
    result = run_cli('export-stream', '--since', created, '--after-id', mem.id, env_db=path)
    assert result.returncode == 0
    assert result.stdout.strip() == ''
    result = run_cli('export-states', '--ids', mem.id, 'missing', env_db=path)
    assert result.returncode == 0
    states = json.loads(result.stdout)
    assert states[0]['searchable'] is True
    assert states[1]['status'] == 'missing'


def test_unpin_confirmation_preserves_then_releases_memory(store, monkeypatch, capsys):
    from argparse import Namespace

    from engram.cli import cmd_unpin

    mem = store.remember('Explicit unpin constraint fixture', MemoryKind.CONSTRAINT, pinned=True)
    args = Namespace(id=mem.id, yes=False)
    monkeypatch.setattr('builtins.input', lambda _: 'n')
    cmd_unpin(args, store)
    assert 'Cancelled' in capsys.readouterr().out
    assert store.conn.execute('SELECT pinned FROM memories WHERE id=?', (mem.id,)).fetchone()[0] == 1
    monkeypatch.setattr('builtins.input', lambda _: 'y')
    cmd_unpin(args, store)
    assert 'unpinned' in capsys.readouterr().out
    assert store.conn.execute('SELECT pinned FROM memories WHERE id=?', (mem.id,)).fetchone()[0] == 0
    cmd_unpin(Namespace(id='missing', yes=False), store)
    assert 'not found' in capsys.readouterr().out


def _expired_compost_pointer(store, content, fact_id):
    from engram.model import MemoryOrigin, MemoryScope

    return store.remember(
        content,
        MemoryKind.INSIGHT,
        origin=MemoryOrigin.COMPOST,
        scope=MemoryScope.GLOBAL,
        source_trace={'compost_fact_ids': [fact_id]},
        expires_at=datetime.now(UTC) - timedelta(days=40),
    )


def test_gc_only_ids_binds_deletion_to_the_previewed_set(store):
    first = _expired_compost_pointer(store, 'Legacy Compost pointer about ledger exports', 'f1')
    second = _expired_compost_pointer(store, 'Stale Compost insight about cache warming', 'f2')
    preview = store.gc_expired_compost(grace_days=30, dry_run=True)
    assert set(preview['eligible_ids']) == {first.id, second.id}

    result = store.gc_expired_compost(grace_days=30, only_ids=[first.id])
    assert result['deleted_ids'] == [first.id]
    assert store.gc_expired_compost(grace_days=30, only_ids=[])['deleted_count'] == 0
    remaining = store.conn.execute(
        "SELECT id FROM memories WHERE origin='compost'"
    ).fetchall()
    assert remaining == [(second.id,)]


def test_gc_cli_refuses_to_delete_when_backup_raises_sqlite_error(store, tmp_path, monkeypatch, capsys):
    import sqlite3
    from argparse import Namespace

    from engram import cli

    pointer = _expired_compost_pointer(store, 'Compost pointer behind a failing backup', 'f3')

    def failing_backup(*_args, **_kwargs):
        raise sqlite3.OperationalError('unable to open database file')

    monkeypatch.setattr(cli, '_create_backup', failing_backup)
    args = Namespace(
        grace_days=30, dry_run=False, backup_dir=str(tmp_path / 'ro'), json=True,
        db_path=str(tmp_path / 'engram.db'),
    )
    with pytest.raises(SystemExit) as exc:
        cli.cmd_gc(args, store)
    assert exc.value.code == 1
    assert 'unable to open database file' in capsys.readouterr().err
    assert store.conn.execute('SELECT status FROM memories WHERE id=?', (pointer.id,)).fetchone()[0] == 'active'
