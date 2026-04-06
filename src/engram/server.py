"""Engram MCP Server: exposes memory operations as tools for Claude Code."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server import FastMCP

from engram.model import MemoryKind, MemoryOrigin
from engram.proactive import ProactiveRecallEngine
from engram.store import MemoryStore

# --- Tool handler functions (testable without MCP transport) ---


def _memory_to_dict(mem) -> dict:
    return {
        "id": mem.id,
        "content": mem.content,
        "summary": mem.summary,
        "kind": mem.kind.value,
        "origin": mem.origin.value,
        "project": mem.project,
        "path_scope": mem.path_scope,
        "tags": mem.tags,
        "confidence": mem.confidence,
        "status": mem.status.value,
        "strength": mem.strength,
        "pinned": mem.pinned,
    }


def _handle_remember(
    store: MemoryStore,
    content: str,
    kind: str,
    origin: str = "human",
    project: str | None = None,
    path_scope: str | None = None,
    tags: list[str] | None = None,
    confidence: float = 1.0,
    evidence_link: str | None = None,
    pinned: bool = False,
) -> dict:
    mem = store.remember(
        content=content,
        kind=MemoryKind(kind),
        origin=MemoryOrigin(origin),
        project=project,
        path_scope=path_scope,
        tags=tags,
        confidence=confidence,
        evidence_link=evidence_link,
        pinned=pinned,
    )
    return _memory_to_dict(mem)


def _handle_recall(
    store: MemoryStore,
    query: str,
    project: str | None = None,
    kind: str | None = None,
    path_scope: str | None = None,
    limit: int = 10,
    budget: str = "normal",
) -> list[dict]:
    kwargs = {}
    if project:
        kwargs["project"] = project
    if kind:
        kwargs["kind"] = MemoryKind(kind)
    if path_scope:
        kwargs["path_scope"] = path_scope

    results = store.recall(query, limit=limit, budget=budget, **kwargs)
    if budget == "tiny":
        return results  # already dicts
    return [_memory_to_dict(m) for m in results]


def _handle_forget(store: MemoryStore, memory_id: str) -> dict:
    store.forget(memory_id)
    return {"status": "forgotten", "id": memory_id}


def _handle_consolidate(
    store: MemoryStore,
    max_age_days: int = 90,
    min_strength: float = 0.2,
) -> dict:
    candidates = store.consolidate_candidates(
        max_age_days=max_age_days, min_strength=min_strength
    )
    return {
        "candidates": [_memory_to_dict(c) for c in candidates],
        "count": len(candidates),
    }


def _handle_proactive(store: MemoryStore, file_path: str) -> list[dict]:
    engine = ProactiveRecallEngine(store)
    results = engine.on_file_open(file_path)
    return [_memory_to_dict(m) for m in results]


def _handle_stats(store: MemoryStore) -> dict:
    return store.stats()


def _handle_health(store: MemoryStore, check_stale: bool = False) -> dict:
    return store.health(check_stale=check_stale)


def _handle_export(store: MemoryStore, path: str, fmt: str = "jsonl") -> dict:
    store.export(path, fmt=fmt)
    return {"status": "exported", "path": path, "format": fmt}


def _handle_micro_index(store: MemoryStore) -> str:
    return store.micro_index()


# --- MCP Server ---


def _get_db_path() -> str:
    return os.environ.get("ENGRAM_DB", str(Path.home() / ".engram" / "engram.db"))


def create_server() -> FastMCP:
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(db_path)
    proactive_engine = ProactiveRecallEngine(store)

    mcp = FastMCP("engram", instructions="Engram: AI agent memory system. Use remember() to store constraints, decisions, procedures, facts, guardrails. Use recall(budget='tiny') for compact cards. Use proactive() before editing files. Origins: human (user-written), agent (AI-discovered), compiled (AI-summarized).")

    @mcp.tool()
    def remember(
        content: str,
        kind: str,
        origin: str = "human",
        project: str | None = None,
        path_scope: str | None = None,
        tags: list[str] | None = None,
        confidence: float = 1.0,
        evidence_link: str | None = None,
        pinned: bool = False,
    ) -> dict:
        """Store a memory. Kinds: constraint, decision, procedure, fact, guardrail. Origins: human, agent, compiled."""
        return _handle_remember(
            store, content, kind, origin, project, path_scope, tags,
            confidence, evidence_link, pinned,
        )

    @mcp.tool()
    def recall(
        query: str,
        project: str | None = None,
        kind: str | None = None,
        limit: int = 10,
        budget: str = "normal",
    ) -> list[dict]:
        """Search memories. budget: tiny (compact cards ~50tok each), normal (full), deep (with compiled)."""
        return _handle_recall(store, query, project, kind, limit=limit, budget=budget)

    @mcp.tool()
    def forget(memory_id: str) -> dict:
        """Soft-delete a memory by ID. Cannot forget pinned memories."""
        return _handle_forget(store, memory_id)

    @mcp.tool()
    def consolidate(max_age_days: int = 90, min_strength: float = 0.2) -> dict:
        """List memories that are candidates for archival."""
        return _handle_consolidate(store, max_age_days, min_strength)

    @mcp.tool()
    def proactive(file_path: str) -> list[dict]:
        """Get relevant guardrails/constraints for a file. Only returns human/agent origin, never compiled."""
        return [_memory_to_dict(m) for m in proactive_engine.on_file_open(file_path)]

    @mcp.tool()
    def suppress(memory_id: str, duration_seconds: int = 300) -> dict:
        """Temporarily suppress a memory from proactive recall."""
        proactive_engine.suppress(memory_id, duration_seconds)
        return {"status": "suppressed", "id": memory_id, "duration": duration_seconds}

    @mcp.tool()
    def health(check_stale: bool = False) -> dict:
        """Run health checks: missing evidence, orphans. Set check_stale=True for stale claims detection."""
        return _handle_health(store, check_stale=check_stale)

    @mcp.tool()
    def micro_index() -> str:
        """Get compact index of all memories (~200 tokens). Use for cold-start orientation."""
        return _handle_micro_index(store)

    @mcp.tool()
    def stats() -> dict:
        """Get memory store statistics."""
        return _handle_stats(store)

    @mcp.tool()
    def compile(project: str) -> str:
        """Compile all memories for a project into structured Markdown overview. No LLM cost."""
        return store.compile(project)

    @mcp.tool()
    def resolve(memory_id: str) -> dict:
        """Mark a memory as resolved (handled, done). Stops proactive recall but keeps searchable."""
        store.conn.execute(
            "UPDATE memories SET status = 'resolved' WHERE id = ?", (memory_id,)
        )
        store.conn.commit()
        return {"status": "resolved", "id": memory_id}

    return mcp


# Entry point for: uv run engram-server
def main():
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
