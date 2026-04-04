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

    args = parser.parse_args(argv)

    db_path = _get_db_path()
    _ensure_db_dir(db_path)
    store = MemoryStore(db_path)

    try:
        {"add": cmd_add, "search": cmd_search, "forget": cmd_forget,
         "candidates": cmd_candidates, "stats": cmd_stats}[args.command](args, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
