### Q1 — [D]
`memories` 主表直接放 `origin=compost + kind=insight` 是最小实施面：SQLite 不能 `ALTER CHECK`，无论 A/D 都要整表重建，但 D 比 C 少一套 external-content FTS5 表、3 个 trigger 和双路 recall 合并。再补一个 `CHECK(origin != 'compost' OR kind = 'insight')`，就能在最低迁移成本下把 trust boundary 收紧到“compost 只能写 insight”。

### Q2 — [D]
`kind=note` 允许长文本原样入库，`kind=event` 才要求原子化拆分，最贴合当前 `content <= 4000` 和 zero-LLM write path，不需要在 Engram 内引入 LLM pipeline。这样 Compost 仍可异步从 note 提炼 event/insight，但 Engram 自己不背写时推理和回滚复杂度。

### Q3 — [A]
现有 `scope IN ('project','global','meta')` 已足够表达“跨项目 insight”，直接用 `global` 零 migration、零查询分叉。`meta` 更像“关于用户自身”的元记忆，拿来装跨项目模式会把语义搅混。

### Q4 — [C]
MCP tool + CLI 命令共用同一个导出 handler 最稳，仓库本来就同时有 CLI 和 MCP 包装层，复用成本很低。只暴露 SQL view 会把 DB 路径、锁行为和 schema 细节泄给 Compost，后面一改表结构就变成兼容性债。

### Q5 — [B]
默认 `recall()` 排除 `origin=compost`，需要时显式 `include_compost=True`，是最低风险的一条 SQL filter；否则 compost insight 会直接挤占 human/agent 的 top-N。被包含时继续在返回体里带 `origin` 即可，不需要为“标记”额外拆两套排序/分页逻辑。

### Q6 — [D]
SQLite 没有“到点触发”的 trigger，真实可做的是：读路径用 `julianday(expires_at) > julianday('now')` 隐藏过期 insight，后台 maintenance worker 再把“过期且宽限 N 天”的行物理删除。这样既保证 recall 一致性，又避免 C 那种十年后表/索引只涨不缩，lazy delete on read 也不必把清理责任绑在命中查询上。

### Q7 — [B]
invalidation 走 MCP tool 最符合单写者模型：Compost 改 fact 后同步调用 `invalidate_compost_fact(fact_ids)`，Engram 在一个事务里把相关 insight 标 `obsolete`。SQLite trigger 看不到外部 fact 变化，event bus 如果没有 durable queue 一样会丢消息，直接写 DB 则绕过 schema / FTS / ops_log 边界。

## 推荐组合
Q1=D Q2=D Q3=A Q4=C Q5=B Q6=D Q7=B

## Migration 002 草稿 (DDL)
Q1 改 schema，必须做 migration；SQLite 不能原地改 `CHECK`，而 `memories_fts` 是 external-content FTS5，表 swap 后必须重建 trigger 和 FTS 索引。

```sql
BEGIN IMMEDIATE;

-- ============================================================
-- PHASE 1: Drop dependent objects before table swap
-- ============================================================
DROP TRIGGER IF EXISTS memories_ai;
DROP TRIGGER IF EXISTS memories_ad;
DROP TRIGGER IF EXISTS memories_au;
DROP TRIGGER IF EXISTS memories_compost_map_ad;
DROP VIEW IF EXISTS memory_scores;

-- ============================================================
-- PHASE 2: Rebuild memories with compost insight support
-- Notes:
--   * Keep rowid table because memories_fts uses content_rowid='rowid'
--   * source_trace stores the contract payload JSON
--   * expires_at is required for origin='compost'
-- ============================================================
CREATE TABLE memories_v3 (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL CHECK(length(content) <= 4000),
    summary       TEXT NOT NULL,
    kind          TEXT NOT NULL,
    origin        TEXT DEFAULT 'human' CHECK(origin IN ('human','agent','compost')),
    project       TEXT,
    path_scope    TEXT,
    tags          TEXT DEFAULT '[]',
    confidence    REAL DEFAULT 1.0,
    evidence_link TEXT,
    source_trace  TEXT,
    status        TEXT DEFAULT 'active',
    strength      REAL DEFAULT 0.5,
    pinned        INTEGER DEFAULT 0,
    scope         TEXT NOT NULL DEFAULT 'project' CHECK(scope IN ('project','global','meta')),
    created_at    TEXT NOT NULL,
    accessed_at   TEXT,
    last_verified TEXT,
    expires_at    TEXT,
    access_count  INTEGER DEFAULT 0,
    CHECK(
        (scope = 'project' AND project IS NOT NULL)
        OR (scope IN ('global','meta') AND project IS NULL)
    ),
    CHECK(source_trace IS NULL OR json_valid(source_trace)),
    CHECK(expires_at IS NULL OR julianday(expires_at) IS NOT NULL),
    CHECK(origin != 'compost' OR kind = 'insight'),
    CHECK(origin != 'compost' OR source_trace IS NOT NULL),
    CHECK(origin != 'compost' OR expires_at IS NOT NULL)
);

-- ============================================================
-- PHASE 3: Copy data and preserve rowid for external-content FTS5
-- Existing rows get NULL source_trace/expires_at because they are human/agent.
-- ============================================================
INSERT INTO memories_v3 (
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, source_trace, status, strength, pinned, scope,
    created_at, accessed_at, last_verified, expires_at, access_count
)
SELECT
    rowid,
    id, content, summary, kind, origin, project, path_scope, tags,
    confidence, evidence_link, NULL, status, strength, pinned, scope,
    created_at, accessed_at, last_verified, NULL, access_count
FROM memories;

-- ============================================================
-- PHASE 4: Swap tables
-- ============================================================
DROP TABLE memories;
ALTER TABLE memories_v3 RENAME TO memories;

-- ============================================================
-- PHASE 5: Add side table for fast invalidation lookup
-- WITHOUT ROWID is appropriate here because PK is the access path.
-- ============================================================
CREATE TABLE compost_insight_sources (
    memory_id TEXT NOT NULL,
    fact_id   TEXT NOT NULL,
    PRIMARY KEY (memory_id, fact_id)
) WITHOUT ROWID;

CREATE INDEX idx_compost_insight_sources_fact_id
    ON compost_insight_sources(fact_id);

CREATE INDEX idx_memories_compost_live
    ON memories(origin, status, expires_at)
    WHERE origin = 'compost' AND status = 'active';

-- ============================================================
-- PHASE 6: Recreate derived objects
-- Expired rows are excluded from score view by wall-clock check.
-- ============================================================
CREATE VIEW memory_scores AS
SELECT id,
  CASE WHEN pinned = 1 THEN 10.0
  ELSE
    confidence
    * (1.0 + 0.1 * MIN(access_count, 20))
    * (1.0 / (1.0 + 0.02 * MAX(0, julianday('now') - julianday(COALESCE(accessed_at, created_at)))))
  END AS effective_score
FROM memories
WHERE status IN ('active', 'resolved')
  AND (expires_at IS NULL OR julianday(expires_at) > julianday('now'));

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, summary, tags)
    VALUES ('delete', old.rowid, old.content, old.summary, old.tags);
    INSERT INTO memories_fts(rowid, content, summary, tags)
    VALUES (new.rowid, new.content, new.summary, new.tags);
END;

CREATE TRIGGER memories_compost_map_ad AFTER DELETE ON memories BEGIN
    DELETE FROM compost_insight_sources WHERE memory_id = old.id;
END;

-- ============================================================
-- PHASE 7: Rebuild FTS5 index
-- Mandatory for external-content FTS after table swap.
-- ============================================================
INSERT INTO memories_fts(memories_fts) VALUES('rebuild');

COMMIT;
```

补充实现约束：
- TTL 读路径过滤应统一落在 `recall()` / `proactive()` / stream handler：`(expires_at IS NULL OR julianday(expires_at) > julianday('now'))`。
- GC 不要做 lazy delete on read；改成后台 maintenance job，例如每天执行一次：`DELETE FROM memories WHERE origin = 'compost' AND expires_at IS NOT NULL AND julianday(expires_at) <= julianday('now','-30 days');`
- invalidation 写路径建议先查 `compost_insight_sources.fact_id -> memory_id`，再同事务 `UPDATE memories SET status='obsolete' ...`；不要每次用 `json_each(source_trace)` 全表扫。

## Codex 独家警告
1. SQLite `CHECK` 不能 `ALTER COLUMN`，`origin` 从 `('human','agent')` 扩成含 `compost` 只能重建整表；如果只换表不 `INSERT INTO memories_fts(...'rebuild')`，FTS5 会静默返回错索引。
2. external-content FTS5 绑定的是 `rowid`，不是业务主键 `id`；迁移时必须显式复制 `rowid`，否则 delete/update trigger 会对错行下手，问题通常到几次更新后才暴露。
3. `DELETE` 了过期 insight 也不会立刻缩小文件；WAL 模式下长期 TTL churn 会把 DB 和索引越用越胖，`VACUUM` 又不能放在热路径或 migration 事务里，必须另做低频维护窗口。
