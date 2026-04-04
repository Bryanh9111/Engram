"""Proactive recall engine: just-in-time guardrails, not ambient autobiography."""

from __future__ import annotations

import fnmatch
import time

from engram.model import MemoryKind, MemoryObject
from engram.store import MemoryStore

# Only these kinds are proactively pushed
_ACTIONABLE_KINDS = frozenset({
    MemoryKind.CONSTRAINT,
    MemoryKind.GUARDRAIL,
    MemoryKind.PROCEDURE,
})

_MAX_RESULTS = 3
_MIN_CONFIDENCE = 0.7


class ProactiveRecallEngine:
    def __init__(self, store: MemoryStore):
        self.store = store
        self._suppressed: dict[str, float] = {}  # id -> expiry timestamp

    def suppress(self, memory_id: str, duration_seconds: int = 300) -> None:
        """Temporarily suppress a memory from proactive recall."""
        self._suppressed[memory_id] = time.time() + duration_seconds

    def _is_suppressed(self, memory_id: str) -> bool:
        if memory_id not in self._suppressed:
            return False
        if time.time() >= self._suppressed[memory_id]:
            del self._suppressed[memory_id]
            return False
        return True

    def on_file_open(self, file_path: str) -> list[MemoryObject]:
        """Surface relevant guardrails when a file is opened.

        Returns at most 3 memories that are:
        - constraint, guardrail, or procedure (not fact/decision)
        - confidence >= 0.7
        - path_scope matches the opened file
        """
        # Get all active memories with a path_scope
        rows = self.store.conn.execute(
            """SELECT id, content, summary, kind, origin, project,
                      path_scope, tags, confidence, evidence_link,
                      status, strength, pinned, created_at,
                      accessed_at, last_verified, access_count
               FROM memories
               WHERE status = 'active'
                 AND path_scope IS NOT NULL
                 AND confidence >= ?
                 AND origin != 'compiled'""",
            (_MIN_CONFIDENCE,),
        ).fetchall()

        matches: list[MemoryObject] = []
        for row in rows:
            mem = self.store._row_to_memory(row)
            if mem.kind not in _ACTIONABLE_KINDS:
                continue
            if self._is_suppressed(mem.id):
                continue
            if mem.path_scope and fnmatch.fnmatch(file_path, mem.path_scope):
                matches.append(mem)

        # Sort by strength descending, take top 3
        matches.sort(key=lambda m: m.strength, reverse=True)
        return matches[:_MAX_RESULTS]
