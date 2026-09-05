CREATE TABLE search_index_state (
  name TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  source_revision INTEGER NOT NULL DEFAULT 0,
  indexed_revision INTEGER NOT NULL DEFAULT 0,
  indexed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  rebuilt_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE VIEW memories_cjk_source AS
SELECT rowid, COALESCE((
  WITH RECURSIVE input(body) AS (SELECT coalesce(content, '') || ' ' || coalesce(summary, '') || ' ' || coalesce((SELECT group_concat(value,' ') FROM json_each(memories.tags)), '')),
  positions(pos, size) AS (
    SELECT 1, length(body) FROM input WHERE length(body) >= 2 AND body GLOB '*[㐀-鿿豈-﫿𠀀-𲎯]*'
    UNION ALL SELECT pos + 1, size FROM positions WHERE pos + 1 < size
  )
  SELECT group_concat(token, ' ') FROM (
    SELECT CASE WHEN (unicode(substr(body,pos,1)) BETWEEN 13312 AND 40959 OR unicode(substr(body,pos,1)) BETWEEN 63744 AND 64255 OR unicode(substr(body,pos,1)) BETWEEN 131072 AND 205743) AND (unicode(substr(body,pos+1,1)) BETWEEN 13312 AND 40959 OR unicode(substr(body,pos+1,1)) BETWEEN 63744 AND 64255 OR unicode(substr(body,pos+1,1)) BETWEEN 131072 AND 205743)
      THEN lower(hex(substr(body,pos,2))) ELSE 'x' END AS token
    FROM positions, input WHERE (unicode(substr(body,pos,1)) BETWEEN 13312 AND 40959 OR unicode(substr(body,pos,1)) BETWEEN 63744 AND 64255 OR unicode(substr(body,pos,1)) BETWEEN 131072 AND 205743) ORDER BY pos
  )
), '') AS grams FROM memories;
CREATE VIRTUAL TABLE memories_cjk USING fts5(grams);
INSERT INTO search_index_state(name,version) VALUES ('memories',1);
CREATE TRIGGER memories_search_ai AFTER INSERT ON memories BEGIN

INSERT INTO memories_cjk(rowid,grams) SELECT rowid,grams FROM memories_cjk_source WHERE rowid=new.rowid;
UPDATE search_index_state SET source_revision=source_revision+1,indexed_revision=indexed_revision+1,indexed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE name='memories';
END;
CREATE TRIGGER memories_search_ad AFTER DELETE ON memories BEGIN

DELETE FROM memories_cjk WHERE rowid=old.rowid;
UPDATE search_index_state SET source_revision=source_revision+1,indexed_revision=indexed_revision+1,indexed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE name='memories';
END;
CREATE TRIGGER memories_search_au AFTER UPDATE OF content,summary,tags ON memories BEGIN

DELETE FROM memories_cjk WHERE rowid=old.rowid;
INSERT INTO memories_cjk(rowid,grams) SELECT rowid,grams FROM memories_cjk_source WHERE rowid=new.rowid;
UPDATE search_index_state SET source_revision=source_revision+1,indexed_revision=indexed_revision+1,indexed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE name='memories';
END;
INSERT INTO memories_cjk(rowid,grams) SELECT rowid,grams FROM memories_cjk_source;
DROP TRIGGER memories_au;
CREATE TRIGGER memories_au AFTER UPDATE OF content,summary,tags ON memories BEGIN
 INSERT INTO memories_fts(memories_fts,rowid,content,summary,tags)
 VALUES ('delete',old.rowid,old.content,old.summary,old.tags);
 INSERT INTO memories_fts(rowid,content,summary,tags)
 VALUES(new.rowid,new.content,new.summary,new.tags);
END;
