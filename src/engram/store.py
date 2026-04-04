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
        self.conn.commit()
        return mem

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
            if similarity > 0.85:
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
        """Retrieve memories matching query with filters and ranking."""
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
        self._touch(results)
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
            SELECT id, content, summary, kind, origin, project,
                   path_scope, tags, confidence, evidence_link,
                   status, strength, pinned, created_at,
                   accessed_at, last_verified, access_count
            FROM memories m
            WHERE m.status = 'active' {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, params + [limit]).fetchall()
        results = [self._row_to_memory(row) for row in rows]
        self._touch(results)
        if budget == "tiny":
            return [self._to_card(m) for m in results]
        return results

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

    def health(self, *, orphan_age_days: int = 30) -> dict:
        """Run health checks: missing evidence, orphans."""
        # Missing evidence: constraint/guardrail without evidence_link
        missing = self.conn.execute(
            """SELECT id, summary, kind FROM memories
               WHERE status = 'active'
                 AND kind IN ('constraint', 'guardrail')
                 AND (evidence_link IS NULL OR evidence_link = '')"""
        ).fetchall()
        missing_evidence = [
            {"id": r[0], "summary": r[1], "kind": r[2]} for r in missing
        ]

        # Orphans: access_count=0, old, not pinned
        orphans_rows = self.conn.execute(
            """SELECT id, summary, kind FROM memories
               WHERE status = 'active'
                 AND pinned = 0
                 AND access_count = 0
                 AND julianday('now') - julianday(created_at) > ?""",
            (orphan_age_days,),
        ).fetchall()
        orphans = [
            {"id": r[0], "summary": r[1], "kind": r[2]} for r in orphans_rows
        ]

        total_issues = len(missing_evidence) + len(orphans)
        return {
            "missing_evidence": missing_evidence,
            "orphans": orphans,
            "total_issues": total_issues,
        }

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
