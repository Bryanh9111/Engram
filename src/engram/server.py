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
        "scope": mem.scope.value if mem.scope else None,
        "expires_at": mem.expires_at.isoformat() if mem.expires_at else None,
        "source_trace": mem.source_trace,
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
    scope: str | None = None,
    source_trace: dict | None = None,
    expires_at: str | None = None,
) -> dict:
    from datetime import datetime

    from engram.model import MemoryScope

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
        scope=MemoryScope(scope) if scope else None,
        source_trace=source_trace,
        expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
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


def _handle_unpin(store: MemoryStore, memory_id: str) -> dict:
    return store.unpin(memory_id)


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
    # MCP defaults to summary mode to save tokens (~200 vs ~5500 at 300 memories).
    # CLI uses full mode via store.health() directly.
    return store.health(check_stale=check_stale, summary=True)


def _handle_export(store: MemoryStore, path: str, fmt: str = "jsonl") -> dict:
    store.export(path, fmt=fmt)
    return {"status": "exported", "path": path, "format": fmt}


def _handle_micro_index(store: MemoryStore) -> str:
    return store.micro_index()


def _memory_to_compost_dict(mem) -> dict:
    """Project MemoryObject to the engram-integration-contract shape.

    Contract keys (exactly): memory_id, kind, content, project, scope,
    created_at, updated_at, tags, origin.
    """
    return {
        "memory_id": mem.id,
        "kind": mem.kind.value,
        "content": mem.content,
        "project": mem.project,
        "scope": mem.scope.value if mem.scope else None,
        "created_at": mem.created_at.isoformat(),
        # Append-only content model: there is no separate update path, so
        # updated_at tracks created_at. If a future edit API lands, point
        # this at the real column.
        "updated_at": mem.created_at.isoformat(),
        "tags": mem.tags,
        "origin": mem.origin.value,
    }


def _handle_invalidate_compost_fact(
    store: MemoryStore,
    fact_ids: list[str],
) -> dict:
    """Mark insights resting on the given Compost fact_ids as obsolete.

    Reverse-lookup via compost_insight_sources; soft-delete; audit.
    Physical purge with 30-day grace is a Phase 3 GC concern.
    """
    if not fact_ids:
        return {"invalidated_memory_ids": [], "count": 0}

    placeholders = ",".join("?" * len(fact_ids))
    rows = store.conn.execute(
        f"""SELECT DISTINCT memory_id FROM compost_insight_sources
            WHERE fact_id IN ({placeholders})""",
        fact_ids,
    ).fetchall()
    memory_ids = [r[0] for r in rows]
    if not memory_ids:
        return {"invalidated_memory_ids": [], "count": 0}

    mem_placeholders = ",".join("?" * len(memory_ids))
    store.conn.execute(
        f"""UPDATE memories SET status = 'obsolete'
            WHERE id IN ({mem_placeholders})""",
        memory_ids,
    )
    detail = f"fact_ids={','.join(fact_ids)}"
    for mid in memory_ids:
        store._log_op("invalidate_compost_fact", mid, detail=detail)
    store.conn.commit()

    return {"invalidated_memory_ids": memory_ids, "count": len(memory_ids)}


def _handle_stream_for_compost(
    store: MemoryStore,
    since: str | None = None,
    kinds: list[str] | None = None,
    project: str | None = None,
    include_compost: bool = False,
    limit: int = 1000,
) -> list[dict]:
    """Stream entries in contract shape, bounded by `limit` for MCP transport."""
    from datetime import datetime

    since_dt = datetime.fromisoformat(since) if since else None
    kinds_enum = [MemoryKind(k) for k in kinds] if kinds else None

    results: list[dict] = []
    if limit <= 0:
        return results
    for mem in store.stream_entries(
        since=since_dt,
        kinds=kinds_enum,
        project=project,
        include_compost=include_compost,
    ):
        results.append(_memory_to_compost_dict(mem))
        if len(results) >= limit:
            break
    return results


# --- MCP Server ---


def _get_db_path() -> str:
    return os.environ.get("ENGRAM_DB", str(Path.home() / ".engram" / "engram.db"))


def create_server() -> FastMCP:
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(db_path)
    proactive_engine = ProactiveRecallEngine(store)

    mcp = FastMCP("engram", instructions="Engram: AI agent memory system. Use remember() to store constraints, decisions, procedures, facts, guardrails, or insights. Use recall(budget='tiny') for compact cards. Use proactive() before editing files. Origins: human (user-written, highest trust), agent (AI-discovered during work), compost (Compost-synthesized cross-project insight, requires kind=insight + source_trace + expires_at).")

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
        scope: str | None = None,
        source_trace: dict | None = None,
        expires_at: str | None = None,
    ) -> dict:
        """Store a memory. Kinds: constraint, decision, procedure, fact, guardrail, insight. Origins: human, agent, compost. Scope: project (default when project given), global (cross-project knowledge, requires project=None), meta (about user/agent, requires project=None). If scope omitted, inferred from project. source_trace (JSON provenance) and expires_at (ISO-8601 TTL) are required for origin=compost."""
        return _handle_remember(
            store, content, kind, origin, project, path_scope, tags,
            confidence, evidence_link, pinned, scope,
            source_trace, expires_at,
        )

    @mcp.tool()
    def recall(
        query: str,
        project: str | None = None,
        kind: str | None = None,
        limit: int = 10,
        budget: str = "normal",
    ) -> list[dict]:
        """Search memories ranked by effective_score. budget: tiny (compact cards ~50tok each), normal (full objects), deep (limit>=50, expanded results)."""
        return _handle_recall(store, query, project, kind, limit=limit, budget=budget)

    @mcp.tool()
    def forget(memory_id: str) -> dict:
        """Soft-delete a memory by ID. Cannot forget pinned memories."""
        return _handle_forget(store, memory_id)

    @mcp.tool()
    def unpin(memory_id: str) -> dict:
        """Unpin a memory so it can be forgotten or age-flagged. Use sparingly: prefer superseding via a new memory with supersedes tag. Single memory only, not batch."""
        return _handle_unpin(store, memory_id)

    @mcp.tool()
    def consolidate(max_age_days: int = 90, min_strength: float = 0.2) -> dict:
        """List memories that are candidates for archival."""
        return _handle_consolidate(store, max_age_days, min_strength)

    @mcp.tool()
    def proactive(file_path: str) -> list[dict]:
        """Get relevant guardrails/constraints/procedures for a file by path_scope match. Only returns origin in (human, agent) and confidence>=0.7; Compost-synthesized insights never enter proactive push (they live in recall only)."""
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
    def stream_for_compost(
        since: str | None = None,
        kinds: list[str] | None = None,
        project: str | None = None,
        include_compost: bool = False,
        limit: int = 1000,
    ) -> list[dict]:
        """Stream Engram memories for Compost ingestion.

        Each entry has contract-shape keys: memory_id, kind, content,
        project, scope, created_at, updated_at, tags, origin.

        Filters: since (ISO-8601 timestamp, strict >), kinds (union of
        kind strings), project. Results are capped at `limit` (default
        1000) so MCP transport stays bounded — Compost polls in rounds.

        origin='compost' entries excluded by default to prevent Compost
        re-ingesting its own insights (debate 019 Q7). Set
        include_compost=True only for admin/debug.
        """
        return _handle_stream_for_compost(
            store, since, kinds, project, include_compost, limit,
        )

    @mcp.tool()
    def invalidate_compost_fact(fact_ids: list[str]) -> dict:
        """Mark insight memories resting on these Compost fact_ids as obsolete.

        Called by Compost when an underlying fact is superseded or changes.
        Engram reverse-looks-up via compost_insight_sources and soft-deletes
        matching insights regardless of pinned state (Compost is the
        authority on insight freshness). Physical purge happens later via
        the Phase 3 GC daemon with a 30-day grace window.

        Returns: {invalidated_memory_ids, count}
        """
        return _handle_invalidate_compost_fact(store, fact_ids)

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
