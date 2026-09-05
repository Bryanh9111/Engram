# Deterministic multilingual search

Engram keeps SQLite and the zero-LLM recall path. The existing unicode61 FTS5
index remains available for keyword search. Migration 004 adds a transactional
Han bigram projection, backfills existing memories, and avoids rewriting the
keyword index for access-counter/status-only updates.

Overlapping Han pairs are encoded as UTF-8 hex tokens. Phrase positions enforce
continuous substrings: `整数分` matches inside a longer sentence, and `检索`
works as a two-character query. Disconnected pairs and punctuation boundaries
do not match a longer phrase. Chinese tags are decoded from JSON before indexing.
A full memory ID also supports direct lookup, subject to the same lifecycle,
expiry and project filters. Candidate retrieval combines lexical paths before
the existing deterministic memory-score ordering.

This supplemental analyzer supports literal Han substrings of two or more
characters, including supplementary Han code points. It does not add Chinese
word segmentation, synonyms, Japanese/Korean analysis, embeddings or an LLM.
English identifiers and punctuation retain the existing literal-token handling.

```bash
engram indexes                  # verify projection coverage and FTS postings
engram indexes --rebuild        # atomically rebuild both lexical indexes
uv run python bench/search_index.py
```

Diagnostics return `ok`, analyzer `version`, `source_revision`,
`indexed_revision`, `indexed_at`, `rebuilt_at`, missing/changed projections and
orphans; drift returns exit 1. Revision counters track indexed text mutations
since backfill and advance together in the source transaction. They are local
index state, not Compost export cursors. SQLite triggers also work for clients
without application functions. Status and expiry are checked in the base table
at query time, so an obsolete or expired record cannot be revived by its index.

Rebuild changes derived indexes only, verifies FTS integrity, and rolls back on
failure. Diagnostics inspect a transaction snapshot using SQLite FTS integrity
commands and may briefly contend with concurrent writers. The small hand-authored
quality fixture reports Recall@10 and MRR for its explicit cases; it does not
measure production semantic recall.

Back up the database before first activation. For a non-editable uv tool
installation, reinstall the local project with its existing MCP extra and
reconnect long-lived clients; changing the checkout alone does not update a
running installed server. Index maintenance does not rewrite memory content or
change the independent Compost integration contract.
