"""Engram CLI: engram add/search/forget/candidates/stats."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from engram.model import MemoryKind, MemoryStatus
from engram.store import MemoryStore


def _get_db_path() -> str:
    return os.environ.get("ENGRAM_DB", str(Path.home() / ".engram" / "engram.db"))


def _ensure_db_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _memory_to_dict(mem) -> dict:
    return {
        "id": mem.id,
        "content": mem.content,
        "summary": mem.summary,
        "kind": mem.kind.value,
        "project": mem.project,
        "path_scope": mem.path_scope,
        "tags": mem.tags,
        "confidence": mem.confidence,
        "status": mem.status.value,
        "strength": mem.strength,
        "pinned": mem.pinned,
        "created_at": mem.created_at.isoformat(),
    }


def cmd_add(args, store: MemoryStore) -> None:
    mem = store.remember(
        content=args.content,
        kind=MemoryKind(args.kind),
        project=args.project,
        path_scope=args.path_scope,
        tags=args.tag or [],
        confidence=args.confidence,
        pinned=args.pinned,
    )
    print(f"Remembered [{mem.kind.value}] {mem.id}: {mem.summary}")


def cmd_search(args, store: MemoryStore) -> None:
    kwargs = {}
    if args.project:
        kwargs["project"] = args.project
    if args.kind:
        kwargs["kind"] = MemoryKind(args.kind)
    if args.path_scope:
        kwargs["path_scope"] = args.path_scope

    results = store.recall(args.query, limit=args.limit, **kwargs)

    if args.json:
        print(json.dumps([_memory_to_dict(m) for m in results], indent=2))
    else:
        if not results:
            print("No memories found.")
            return
        for mem in results:
            pin = " [pinned]" if mem.pinned else ""
            print(f"  [{mem.kind.value}] {mem.id}{pin}")
            print(f"    {mem.summary}")
            if mem.project:
                print(f"    project: {mem.project}")
            print()


def cmd_forget(args, store: MemoryStore) -> None:
    store.forget(args.id)
    print(f"Forgot {args.id}")


def cmd_candidates(args, store: MemoryStore) -> None:
    candidates = store.consolidate_candidates(
        max_age_days=args.max_age_days,
        min_strength=args.min_strength,
    )
    if not candidates:
        print("No archive candidates.")
        return
    for mem in candidates:
        print(f"  [{mem.kind.value}] {mem.id} (strength={mem.strength:.2f})")
        print(f"    {mem.summary}")
        print()


def cmd_stats(args, store: MemoryStore) -> None:
    s = store.stats()
    print(f"Total: {s['total']}  Active: {s['active']}")
    if s["by_kind"]:
        print("By kind:")
        for kind, count in sorted(s["by_kind"].items()):
            print(f"  {kind}: {count}")


def cmd_lint(args, store: MemoryStore) -> None:
    report = store.health(check_stale=True)
    total = report["total_issues"]
    print(f"Engram Lint — {total} issues")
    print("-" * 40)

    if report["missing_evidence"]:
        print(f"\nMissing evidence ({len(report['missing_evidence'])}):")
        for r in report["missing_evidence"][:10]:
            print(f"  [{r['kind']}] {r['id']}: {r['summary'][:60]}")

    if report["orphans"]:
        print(f"\nOrphans ({len(report['orphans'])}):")
        for r in report["orphans"][:10]:
            print(f"  [{r['kind']}] {r['id']}: {r['summary'][:60]}")

    if report.get("stale_claims"):
        print(f"\nStale claims ({len(report['stale_claims'])}):")
        for r in report["stale_claims"][:10]:
            print(f"  {r['old_id']} → superseded by {r['new_id']}")
            print(f"    old: {r['old_content'][:60]}")

    if report.get("kind_staleness"):
        print(f"\nKind staleness ({len(report['kind_staleness'])}):")
        for r in report["kind_staleness"][:10]:
            print(f"  [{r['kind']}] {r['id']} (>{r['ttl_days']}d old): {r['summary'][:50]}")

    if total == 0:
        print("\nAll clean.")


def cmd_dashboard(args, store: MemoryStore) -> None:
    s = store.stats()
    pinned = store.conn.execute(
        "SELECT COUNT(*) FROM memories WHERE pinned = 1"
    ).fetchone()[0]
    resolved = store.conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status = 'resolved'"
    ).fetchone()[0]

    print(f"Engram Brain ({s['active']} active, {resolved} resolved, {pinned} pinned)")
    print("-" * 55)
    print()

    # By kind
    print("By Kind:")
    for kind, count in sorted(s["by_kind"].items(), key=lambda x: -x[1]):
        bar = "#" * min(count, 30)
        print(f"  {kind:12s} {count:3d} {bar}")
    print()

    # By project
    print("By Project:")
    for row in store.conn.execute(
        "SELECT project, COUNT(*) FROM memories WHERE status IN ('active','resolved') AND project IS NOT NULL GROUP BY project ORDER BY COUNT(*) DESC LIMIT 15"
    ).fetchall():
        bar = "#" * min(row[1], 30)
        print(f"  {row[0]:12s} {row[1]:3d} {bar}")
    print()

    # Health summary
    h = store.health()
    print(f"Health Issues: {h['total_issues']}")
    if h["missing_evidence"]:
        print(f"  Missing evidence: {len(h['missing_evidence'])}")
    if h["orphans"]:
        print(f"  Orphans: {len(h['orphans'])}")
    print()

    # Recent ops
    ops = store.conn.execute(
        "SELECT op, COUNT(*) FROM ops_log WHERE ts > datetime('now', '-24 hours') GROUP BY op"
    ).fetchall()
    if ops:
        print("Recent Activity (24h):")
        for op, count in ops:
            print(f"  {op}: {count}")
    else:
        print("Recent Activity (24h): none")
    print()

    # Hot memories
    hot = store.conn.execute(
        """SELECT id, summary, kind, access_count FROM memories
           WHERE status = 'active' AND access_count > 0
           ORDER BY access_count DESC LIMIT 5"""
    ).fetchall()
    if hot:
        print("Hot Memories:")
        for row in hot:
            print(f"  [{row[2]}] {row[1][:60]} ({row[3]} accesses)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="engram", description="Engram memory system")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Remember something")
    p_add.add_argument("content", help="Memory content")
    p_add.add_argument("--kind", required=True, choices=[k.value for k in MemoryKind])
    p_add.add_argument("--project")
    p_add.add_argument("--path-scope")
    p_add.add_argument("--tag", action="append")
    p_add.add_argument("--confidence", type=float, default=1.0)
    p_add.add_argument("--pinned", action="store_true")

    # search
    p_search = sub.add_parser("search", help="Recall memories")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--project")
    p_search.add_argument("--kind", choices=[k.value for k in MemoryKind])
    p_search.add_argument("--path-scope")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")

    # forget
    p_forget = sub.add_parser("forget", help="Forget a memory")
    p_forget.add_argument("id", help="Memory ID")

    # candidates
    p_cand = sub.add_parser("candidates", help="List archive candidates")
    p_cand.add_argument("--max-age-days", type=int, default=90)
    p_cand.add_argument("--min-strength", type=float, default=0.2)

    # stats
    sub.add_parser("stats", help="Show statistics")

    # dashboard
    sub.add_parser("dashboard", help="Brain status overview")

    # lint
    sub.add_parser("lint", help="Full health check (missing evidence + orphans + stale + kind TTL)")

    args = parser.parse_args(argv)

    db_path = _get_db_path()
    _ensure_db_dir(db_path)
    store = MemoryStore(db_path)

    try:
        {"add": cmd_add, "search": cmd_search, "forget": cmd_forget,
         "candidates": cmd_candidates, "stats": cmd_stats,
         "dashboard": cmd_dashboard, "lint": cmd_lint}[args.command](args, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
