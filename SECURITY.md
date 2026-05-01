# Security

Engram is a single-user, local-first memory server. The database can contain
project constraints, operational notes, and other sensitive working memory.

## Data Locality

- The default database is `~/.engram/engram.db`.
- Core operations use local SQLite + FTS5 and make no LLM or cloud calls.
- MCP clients connected to Engram can read and write the memory database, so only
  register Engram with agents you trust.

## File Permissions

Engram creates the default `~/.engram` directory with `0700` permissions and
sets SQLite database artifacts to `0600`. This protects against other non-root
users on the same machine reading the memory store. It does not protect against
root/admin access, same-user malware, or an already-compromised agent process.

If you override `ENGRAM_DB`, place it on a local, private path. Do not put the
database in a shared or cloud-synced directory unless you accept the privacy and
SQLite WAL consistency risks.

## Reporting Vulnerabilities

Open a GitHub issue for low-severity problems. For high-severity issues such as
data exposure or arbitrary code execution, contact the repository owner directly
through GitHub.
