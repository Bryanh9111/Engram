"""Engram MemoryStore: core read/write operations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from engram.db import init_db
from engram.model import MemoryKind, MemoryObject, MemoryOrigin, MemoryStatus


class MemoryStore:
    def __init__(self, db_path: str = "engram.db"):
        self.conn = init_db(db_path)

    def close(self):
        self.conn.close()

    def _log_op(self, op: str, memory_id: str | None = None,
                kind: str | None = None, project: str | None = None,
                detail: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO ops_log (op, memory_id, kind, project, ts, detail) VALUES (?,?,?,?,?,?)",
            (op, memory_id, kind, project,
             datetime.now(timezone.utc).isoformat(), detail),
        )

    def remember(
        self,
        content: str,
        kind: MemoryKind,
        *,
        origin: MemoryOrigin = MemoryOrigin.HUMAN,
        project: str | None = None,
        path_scope: str | None = None,
        tags: list[str] | None = None,
        confidence: float = 1.0,
        evidence_link: str | None = None,
        pinned: bool = False,
        summary: str = "",
    ) -> MemoryObject:
        """Write a memory. Deduplicates against existing similar content."""
        tags = tags or []

        # Dedup check via FTS5
        existing = self._find_duplicate(content, project)
        if existing:
            return self._strengthen(existing)

        mem = MemoryObject(
            content=content,
            kind=kind,
            origin=origin,
            project=project,
            path_scope=path_scope,
            tags=tags,
            confidence=confidence,
            evidence_link=evidence_link,
            pinned=pinned,
            summary=summary,
        )

        # Kind-specific soft quality check (only if confidence was default)
        if confidence == 1.0:
            mem.confidence = self._apply_kind_rules(mem)

        self.conn.execute(
            """INSERT INTO memories
               (id, content, summary, kind, origin, project, path_scope, tags,
                confidence, evidence_link, status, strength, pinned,
                created_at, accessed_at, last_verified, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mem.id,
                mem.content,
                mem.summary,
                mem.kind.value,
                mem.origin.value,
                mem.project,
                mem.path_scope,
                json.dumps(mem.tags),
                mem.confidence,
                mem.evidence_link,
                mem.status.value,
                mem.strength,
                int(mem.pinned),
                mem.created_at.isoformat(),
                None,
                None,
                0,
            ),
        )
        self._log_op("remember", mem.id, mem.kind.value, mem.project)
        self.conn.commit()
        return mem

    @staticmethod
    def _apply_kind_rules(mem: MemoryObject) -> float:
        """Soft quality check: lower confidence if recommended fields missing."""
        conf = 1.0
        if mem.kind == MemoryKind.GUARDRAIL and not mem.evidence_link:
            conf = min(conf, 0.7)
        if mem.kind == MemoryKind.CONSTRAINT and not mem.project and not mem.path_scope:
            conf = min(conf, 0.8)
        if mem.kind in (MemoryKind.PROCEDURE,) and not mem.path_scope and not mem.project:
            conf = min(conf, 0.9)
        return conf

    def _find_duplicate(
        self, content: str, project: str | None
    ) -> MemoryObject | None:
        """Check if very similar content already exists using FTS5."""
        # Extract key words for FTS match (first 10 significant words)
        words = [w for w in content.split() if len(w) > 2][:10]
        if not words:
            return None

        query = " ".join(words)
        try:
            rows = self.conn.execute(
                """SELECT m.id, m.content, m.summary, m.kind, m.origin, m.project,
                          m.path_scope, m.tags, m.confidence, m.evidence_link,
                          m.status, m.strength, m.pinned, m.created_at,
                          m.accessed_at, m.last_verified, m.access_count
                   FROM memories m
                   JOIN memories_fts fts ON m.rowid = fts.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT 5""",
                (query,),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        for row in rows:
            existing_content = row[1]
            similarity = self._text_similarity(content, existing_content)
            if similarity > 0.75:
                existing_project = row[5]
                if existing_project == project:
                    return self._row_to_memory(row)

        return None

    @staticmethod
    def _normalize(text: str) -> set[str]:
        """Normalize text for similarity comparison."""
        import re
        text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        return {w for w in text.split() if len(w) > 1}

    def _text_similarity(self, a: str, b: str) -> float:
        """Word-overlap Jaccard similarity with normalization."""
        words_a = self._normalize(a)
        words_b = self._normalize(b)
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _strengthen(self, mem: MemoryObject) -> MemoryObject:
        """Increase strength of an existing memory on re-encounter."""
        new_strength = min(1.0, mem.strength + 0.1)
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE memories
               SET strength = ?, accessed_at = ?, access_count = access_count + 1
               WHERE id = ?""",
            (new_strength, now, mem.id),
        )
        self.conn.commit()
        mem.strength = new_strength
        mem.access_count += 1
        return mem

    def recall(
        self,
        query: str,
        *,
        project: str | None = None,
        kind: MemoryKind | None = None,
        status: MemoryStatus | None = None,
        path_scope: str | None = None,
        limit: int = 10,
        budget: str = "normal",
    ) -> list[MemoryObject] | list[dict]:
        """Retrieve memories matching query with filters and ranking.

        Budget levels (token cost):
          tiny   ~300 tok  — compact cards (claim+kind+scope+trust)
          normal ~2-5K tok — full memory objects (default)
          deep   ~5-20K tok — expanded results, higher limit
        """
        if budget == "deep":
            limit = max(limit, 50)

        params: list = []
        where_clauses: list[str] = []

        if project:
            where_clauses.append("m.project = ?")
            params.append(project)
        if kind:
            where_clauses.append("m.kind = ?")
            params.append(kind.value)
        if status:
            where_clauses.append("m.status = ?")
            params.append(status.value)
        if path_scope:
            where_clauses.append("m.path_scope = ?")
            params.append(path_scope)

        where_sql = ""
        if where_clauses:
            where_sql = "AND " + " AND ".join(where_clauses)

        if query.strip():
            # FTS5 search with ranking
            words = [w for w in query.split() if len(w) > 1]
            if not words:
                return self._recall_recent(where_sql, params, limit, budget)

            fts_query = " OR ".join(words)
            sql = f"""
                SELECT m.id, m.content, m.summary, m.kind, m.origin, m.project,
                       m.path_scope, m.tags, m.confidence, m.evidence_link,
                       m.status, m.strength, m.pinned, m.created_at,
                       m.accessed_at, m.last_verified, m.access_count
                FROM memories m
                JOIN memories_fts fts ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ? AND m.status != 'obsolete' {where_sql}
                ORDER BY rank
                LIMIT ?
            """
            all_params = [fts_query] + params + [limit]
            try:
                rows = self.conn.execute(sql, all_params).fetchall()
            except sqlite3.OperationalError:
                return []
        else:
            return self._recall_recent(where_sql, params, limit, budget)

        results = [self._row_to_memory(row) for row in rows]
        results = self._rank_by_score(results)
        self._touch(results)
        self._log_op("recall", detail=f"query={query[:50]} results={len(results)}")
        self.conn.commit()
        if budget == "tiny":
            return [self._to_card(m) for m in results]
        return results

    def _to_card(self, mem: MemoryObject) -> dict:
        """Project a MemoryObject to a compact card (~50 tokens)."""
        return {
            "id": mem.id,
            "claim": mem.summary,
            "kind": mem.kind.value,
            "scope": mem.path_scope or mem.project or "",
            "trust": mem.confidence,
            "origin": mem.origin.value,
            "source": mem.evidence_link or "",
        }

    def _recall_recent(
        self, where_sql: str, params: list, limit: int, budget: str = "normal"
    ) -> list[MemoryObject] | list[dict]:
        """Fallback: return recent active memories when no query."""
        sql = f"""
            SELECT m.id, m.content, m.summary, m.kind, m.origin, m.project,
                   m.path_scope, m.tags, m.confidence, m.evidence_link,
                   m.status, m.strength, m.pinned, m.created_at,
                   m.accessed_at, m.last_verified, m.access_count
            FROM memories m
            LEFT JOIN memory_scores ms ON m.id = ms.id
            WHERE m.status = 'active' {where_sql}
            ORDER BY COALESCE(ms.effective_score, 0.5) DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, params + [limit]).fetchall()
        results = [self._row_to_memory(row) for row in rows]
        self._touch(results)
        self._log_op("recall", detail=f"recent results={len(results)}")
        self.conn.commit()
        if budget == "tiny":
            return [self._to_card(m) for m in results]
        return results

    def _rank_by_score(self, memories: list[MemoryObject]) -> list[MemoryObject]:
        """Re-rank by effective_score from the memory_scores view."""
        if not memories:
            return memories
        ids = [m.id for m in memories]
        placeholders = ",".join("?" * len(ids))
        scores = {}
        for row in self.conn.execute(
            f"SELECT id, effective_score FROM memory_scores WHERE id IN ({placeholders})", ids
        ).fetchall():
            scores[row[0]] = row[1]
        return sorted(memories, key=lambda m: scores.get(m.id, 0.5), reverse=True)

    def _touch(self, memories: list[MemoryObject]) -> None:
        """Update access metadata for recalled memories."""
        now = datetime.now(timezone.utc).isoformat()
        for mem in memories:
            self.conn.execute(
                """UPDATE memories
                   SET accessed_at = ?, access_count = access_count + 1
                   WHERE id = ?""",
                (now, mem.id),
            )
        self.conn.commit()

    def forget(self, memory_id: str) -> None:
        """Soft-delete a memory by marking it obsolete."""
        row = self.conn.execute(
            "SELECT pinned FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Memory {memory_id} not found")
        if row[0]:
            raise ValueError(f"Cannot forget pinned memory {memory_id}")

        self.conn.execute(
            "UPDATE memories SET status = ? WHERE id = ?",
            (MemoryStatus.OBSOLETE.value, memory_id),
        )
        self._log_op("forget", memory_id)
        self.conn.commit()

    def consolidate_candidates(
        self, *, max_age_days: int = 90, min_strength: float = 0.2
    ) -> list[MemoryObject]:
        """List memories that are candidates for archival."""
        rows = self.conn.execute(
            """SELECT id, content, summary, kind, origin, project,
                      path_scope, tags, confidence, evidence_link,
                      status, strength, pinned, created_at,
                      accessed_at, last_verified, access_count
               FROM memories
               WHERE status = 'active'
                 AND pinned = 0
                 AND strength < ?
                 AND julianday('now') - julianday(created_at) > ?
               ORDER BY strength ASC, created_at ASC""",
            (min_strength, max_age_days),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def stats(self) -> dict:
        """Return memory store statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        active = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active'"
        ).fetchone()[0]

        by_kind: dict[str, int] = {}
        for row in self.conn.execute(
            "SELECT kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY kind"
        ).fetchall():
            by_kind[row[0]] = row[1]

        return {"total": total, "active": active, "by_kind": by_kind}

    def compile(self, project: str) -> str:
        """Compile all active memories for a project into structured Markdown. No LLM."""
        rows = self.conn.execute(
            """SELECT kind, content, summary, pinned, evidence_link
               FROM memories
               WHERE status IN ('active', 'resolved') AND project = ?
               ORDER BY kind, pinned DESC, confidence DESC""",
            (project,),
        ).fetchall()

        if not rows:
            return f"# {project}\n\nNo memories found."

        lines = [f"# {project}", f"", f"*{len(rows)} memories*", ""]
        current_kind = None
        for kind, content, summary, pinned, evidence in rows:
            if kind != current_kind:
                current_kind = kind
                lines.append(f"## {kind}")
                lines.append("")
            pin = " [pinned]" if pinned else ""
            lines.append(f"- {summary}{pin}")
            if evidence:
                lines.append(f"  source: {evidence}")
        lines.append("")
        return "\n".join(lines)

    def export(self, path: str, *, fmt: str = "jsonl") -> None:
        """Export all memories to JSONL or Markdown."""
        from pathlib import Path

        rows = self.conn.execute(
            """SELECT id, content, summary, kind, origin, project,
                      path_scope, tags, confidence, evidence_link,
                      status, strength, pinned, created_at,
                      accessed_at, last_verified, access_count
               FROM memories ORDER BY created_at"""
        ).fetchall()
        memories = [self._row_to_memory(row) for row in rows]

        if fmt == "jsonl":
            with open(path, "w") as f:
                for mem in memories:
                    obj = {
                        "id": mem.id, "content": mem.content,
                        "summary": mem.summary, "kind": mem.kind.value,
                        "origin": mem.origin.value, "project": mem.project,
                        "path_scope": mem.path_scope, "tags": mem.tags,
                        "confidence": mem.confidence,
                        "evidence_link": mem.evidence_link,
                        "status": mem.status.value, "strength": mem.strength,
                        "pinned": mem.pinned,
                        "created_at": mem.created_at.isoformat(),
                    }
                    f.write(json.dumps(obj) + "\n")
        elif fmt == "markdown":
            out_dir = Path(path)
            out_dir.mkdir(parents=True, exist_ok=True)
            for mem in memories:
                md = f"""---
id: {mem.id}
kind: {mem.kind.value}
origin: {mem.origin.value}
project: {mem.project or ''}
path_scope: {mem.path_scope or ''}
confidence: {mem.confidence}
status: {mem.status.value}
pinned: {mem.pinned}
created_at: {mem.created_at.isoformat()}
---

{mem.content}
"""
                (out_dir / f"{mem.id}.md").write_text(md)

    def health(
        self,
        *,
        orphan_age_days: int = 30,
        check_stale: bool = False,
        summary: bool = False,
    ) -> dict:
        """Run health checks: missing evidence, orphans, stale claims.

        summary=False (default): returns full lists (CLI use, ~5K tokens at 300 memories)
        summary=True: returns counts only (MCP use, ~200 tokens regardless of scale)
        """
        # Missing evidence: constraint/guardrail without evidence_link
        missing = self.conn.execute(
            """SELECT id, summary, kind FROM memories
               WHERE status = 'active'
                 AND kind IN ('constraint', 'guardrail')
                 AND (evidence_link IS NULL OR evidence_link = '')"""
        ).fetchall()

        # Orphans: access_count=0, old, not pinned
        orphans_rows = self.conn.execute(
            """SELECT id, summary, kind FROM memories
               WHERE status = 'active'
                 AND pinned = 0
                 AND access_count = 0
                 AND julianday('now') - julianday(created_at) > ?""",
            (orphan_age_days,),
        ).fetchall()

        stale_claims = self._find_stale_claims() if check_stale else []
        kind_staleness = self._find_kind_staleness() if check_stale else []

        total = len(missing) + len(orphans_rows) + len(stale_claims) + len(kind_staleness)

        if summary:
            # Compact mode for MCP: counts only
            result: dict = {
                "missing_evidence_count": len(missing),
                "orphans_count": len(orphans_rows),
                "total_issues": total,
            }
            if check_stale:
                result["stale_claims_count"] = len(stale_claims)
                result["kind_staleness_count"] = len(kind_staleness)
            return result

        # Full mode for CLI: complete lists
        result = {
            "missing_evidence": [
                {"id": r[0], "summary": r[1], "kind": r[2]} for r in missing
            ],
            "orphans": [
                {"id": r[0], "summary": r[1], "kind": r[2]} for r in orphans_rows
            ],
            "total_issues": total,
        }
        if check_stale:
            result["stale_claims"] = stale_claims
            result["kind_staleness"] = kind_staleness
        return result

    # Kind-specific TTL for staleness warning (not auto-deletion).
    # constraint/guardrail are long-lived and excluded.
    _KIND_TTL_DAYS = {
        "fact": 7,
        "procedure": 30,
        "decision": 90,
    }

    def _find_kind_staleness(self) -> list[dict]:
        """Flag memories past their kind-specific TTL. Warning only, not auto-delete."""
        stale: list[dict] = []
        for kind, ttl in self._KIND_TTL_DAYS.items():
            rows = self.conn.execute(
                """SELECT id, summary, kind, created_at FROM memories
                   WHERE status = 'active'
                     AND kind = ?
                     AND pinned = 0
                     AND julianday('now') - julianday(COALESCE(accessed_at, created_at)) > ?""",
                (kind, ttl),
            ).fetchall()
            for r in rows:
                stale.append({
                    "id": r[0],
                    "summary": r[1],
                    "kind": r[2],
                    "ttl_days": ttl,
                })
        return stale

    def _find_stale_claims(self) -> list[dict]:
        """Find memories where a newer memory on same project supersedes an older one."""
        stale: list[dict] = []
        rows = self.conn.execute(
            """SELECT id, content, summary, kind, project, created_at
               FROM memories WHERE status = 'active' AND project IS NOT NULL
               ORDER BY created_at ASC"""
        ).fetchall()

        for i, row in enumerate(rows):
            old_id, old_content, old_summary, old_kind, old_project, old_ts = row
            normalized = self._normalize(old_content)
            words = list(normalized)[:8]
            if not words:
                continue
            fts_query = " OR ".join(words)
            try:
                matches = self.conn.execute(
                    """SELECT m.id, m.content, m.created_at
                       FROM memories m
                       JOIN memories_fts fts ON m.rowid = fts.rowid
                       WHERE memories_fts MATCH ?
                         AND m.status = 'active'
                         AND m.project = ?
                         AND m.id != ?
                         AND m.created_at > ?
                       ORDER BY rank LIMIT 3""",
                    (fts_query, old_project, old_id, old_ts),
                ).fetchall()
            except Exception:
                continue

            for match in matches:
                sim = self._text_similarity(old_content, match[1])
                if sim > 0.4:
                    stale.append({
                        "old_id": old_id,
                        "old_content": old_summary,
                        "new_id": match[0],
                        "new_content": match[1][:100],
                        "similarity": round(sim, 2),
                    })
                    break  # one match is enough
        return stale

    def micro_index(self) -> str:
        """Generate a compact index for AI agent cold-start (~200 tokens)."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active'"
        ).fetchone()[0]

        if total == 0:
            return "Engram: empty (0 memories)"

        lines = [f"Engram: {total} memories"]

        # By kind
        for row in self.conn.execute(
            "SELECT kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY kind ORDER BY COUNT(*) DESC"
        ).fetchall():
            lines.append(f"  {row[0]}: {row[1]}")

        # By project
        for row in self.conn.execute(
            "SELECT project, COUNT(*) FROM memories WHERE status = 'active' AND project IS NOT NULL GROUP BY project ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall():
            lines.append(f"  [{row[0]}] {row[1]}")

        return "\n".join(lines)

    def _row_to_memory(self, row: tuple) -> MemoryObject:
        return MemoryObject(
            id=row[0],
            content=row[1],
            summary=row[2],
            kind=MemoryKind(row[3]),
            origin=MemoryOrigin(row[4]) if row[4] else MemoryOrigin.HUMAN,
            project=row[5],
            path_scope=row[6],
            tags=json.loads(row[7]) if row[7] else [],
            confidence=row[8],
            evidence_link=row[9],
            status=MemoryStatus(row[10]),
            strength=row[11],
            pinned=bool(row[12]),
            created_at=datetime.fromisoformat(row[13]),
            accessed_at=datetime.fromisoformat(row[14]) if row[14] else None,
            last_verified=datetime.fromisoformat(row[15]) if row[15] else None,
            access_count=row[16],
        )
