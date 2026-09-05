"""Deterministic lexical evaluation; temporary DB only, no model dependencies."""

import json
import tempfile
import time
from pathlib import Path

from engram.model import MemoryKind
from engram.store import MemoryStore

fixture = json.loads((Path(__file__).parent / "search-quality.json").read_text())
with tempfile.TemporaryDirectory(prefix="engram-search-quality-") as directory:
    store = MemoryStore(str(Path(directory) / "memory.db"))
    try:
        labels = {}
        for document in fixture["documents"]:
            memory = store.remember(
                content=document["content"],
                kind=MemoryKind.FACT,
                project=document["project"],
                tags=document["tags"],
            )
            labels[memory.id] = document["id"]
        rows = []
        for query in fixture["queries"]:
            started = time.perf_counter()
            hits = [
                labels[memory.id]
                for memory in store.recall(
                    query["query"], project=query.get("project"), limit=10
                )
            ]
            expected = query["expected"]
            recall = (
                len(set(hits) & set(expected)) / len(expected) if expected else None
            )
            rank = next((i + 1 for i, hit in enumerate(hits) if hit in expected), 0)
            rows.append(
                dict(
                    query=query["query"],
                    project=query.get("project"),
                    expected=expected,
                    hits=hits,
                    recall_at_10=recall,
                    reciprocal_rank=1 / rank if rank else 0,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    passed=recall == 1 if expected else not hits,
                )
            )
        positives = [row for row in rows if row["expected"]]
        report = dict(
            cases=len(rows),
            passed=sum(row["passed"] for row in rows),
            recall_at_10=sum(row["recall_at_10"] for row in positives) / len(positives),
            mrr=sum(row["reciprocal_rank"] for row in positives) / len(positives),
            rows=rows,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["passed"] != report["cases"]:
            raise SystemExit(1)
    finally:
        store.close()
