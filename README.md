# Engram

**Human-brain-like memory system for AI coding agents.**

Engram gives your AI agent persistent, cross-project memory with proactive recall. Instead of re-explaining your codebase every session, your agent remembers constraints, decisions, procedures, and hard-won lessons — and surfaces them at exactly the right moment.

```
You open payments/reconcile.ts
  Engram automatically pushes:
  [constraint] "Money values must use integer cents end-to-end, never introduce floats"
  [guardrail]  "Never parallelize migration-0042 and migration-0043"

You didn't ask. It just knew.
```

## Why Engram

AI coding agents are smart but amnesic. Every new session starts from zero. MEMORY.md files help, but they:

- Load everything into context every time (3-5K tokens wasted)
- Can't search or rank by relevance
- Don't distinguish "hard constraint" from "temporary fact"
- Never forget anything (noise accumulates)
- Can't proactively warn you before you make a mistake

Engram fixes all of this.

## How It Works

```
              AI Agent (Claude Code / Gemma / etc.)
                    |
            MCP Server (10 tools)
                    |
     .------.-------.-------.-------.
     |      |       |       |       |
  recall  remember  proactive  health  ...
     |      |       |       |       |
     '------'-------'-------'-------'
                    |
           SQLite + FTS5 (single file)
              ~/.engram/engram.db
```

**Proactive recall** is the key differentiator. When you open a file, Engram checks if any constraints, guardrails, or procedures are scoped to that path — and pushes them into context before you even ask.

Other systems wait for you to search. Engram interrupts you when it matters.

## Architecture

Designed through three rounds of multi-model AI debate (Claude Opus, Sonnet, Gemini 2.5 Pro, GPT-5.4) and validated against Karpathy's LLM Knowledge Base methodology and Obsidian second-brain patterns.

### Memory Model

Five kinds, grounded in real coding scenarios:

| Kind | Lifetime | Example |
|------|----------|---------|
| `constraint` | Semi-permanent | "Money values must use integer cents end-to-end" |
| `decision` | Until revisited | "Use polling not websockets — customer proxies break upgrades" |
| `procedure` | Version-controlled | "Integration tests: seed Redis, then worker, then API" |
| `fact` | Short-lived | "UserSearchV2 is behind SEARCH_V2=1 flag" |
| `guardrail` | Incident-driven | "Never parallelize these two migrations — caused prod failure" |

### Origin Separation

Inspired by [kepano](https://x.com/kepano) (Obsidian founder): AI-compiled knowledge must never contaminate human judgment.

| Origin | Trust | Proactive Push |
|--------|-------|----------------|
| `human` | Highest — user explicitly wrote this | Yes |
| `agent` | Medium — AI discovered during work | Yes |
| `compiled` | Reference — AI-generated summaries | **No** — only returned on explicit recall |

### Token Budget

Retrieval cost is constant regardless of memory count:

| Operation | Tokens | Scale behavior |
|-----------|--------|---------------|
| Micro-index (cold start) | ~200 | Fixed |
| Recall `budget=tiny` (5 cards) | ~300 | Fixed |
| Recall `budget=normal` (5 results) | ~800 | Fixed |
| Proactive recall (3 cards) | ~150 | Fixed |
| **Compare: MEMORY.md** | **3,000-5,000** | **Grows linearly** |

At 10,000 memories, Engram still costs ~300 tokens per retrieval. MEMORY.md would be impossible.

## Quick Start

### Install

```bash
git clone https://github.com/Bryanh9111/Engram.git
cd Engram
uv sync --extra dev --extra mcp
```

### CLI

```bash
# Remember something
engram add "Money values must use integer cents" --kind constraint --project payments --path-scope "payments/*"

# Search memories
engram search "integer cents"

# Get archive candidates
engram candidates

# Run health checks
engram health

# View stats
engram stats
```

### MCP Server (Claude Code integration)

Add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "engram": {
      "command": "uv",
      "args": ["--directory", "/path/to/Engram", "run", "engram-server"],
      "env": {
        "ENGRAM_DB": "~/.engram/engram.db"
      }
    }
  }
}
```

Restart Claude Code. Ten tools become available:

| Tool | Purpose |
|------|---------|
| `remember` | Store a memory (kind + origin) |
| `recall` | Search with budget control (`tiny`/`normal`/`deep`) |
| `proactive` | Get guardrails for a file path |
| `forget` | Soft-delete a memory |
| `suppress` | Temporarily silence a proactive memory |
| `consolidate` | List archive candidates |
| `health` | Check for missing evidence, orphans |
| `micro_index` | Compact index for cold-start (~200 tokens) |
| `stats` | Memory statistics |
| `export` | Export to JSONL or Markdown |

## Memory Cards

When you use `budget=tiny`, Engram returns compact cards instead of full documents:

```
[constraint] payments/*
"Money values must use integer cents end-to-end"
trust: 1.0 | pinned | verified 3d ago
source: github.com/org/repo/pull/42
```

~50 tokens per card. Three cards = 150 tokens. Compare that to loading an entire wiki article.

The philosophy: **memories enter context as claims, not documents; with provenance, not vibes.**

## Health Checks

```bash
engram health
```

Three checks borrowed from [Karpathy's knowledge base linting](https://x.com/karpathy/status/1911070032680222720):

- **Missing evidence**: Constraints and guardrails without source links
- **Orphans**: Memories never accessed, older than 30 days, not pinned
- **Contradictions**: (v3) Semantically similar memories with conflicting conclusions

## Export & Portability

```bash
# Lossless export
engram export --format jsonl --output memories.jsonl

# Human-readable export with YAML frontmatter
engram export --format markdown --output ./export/
```

SQLite is the runtime source of truth. JSONL is the migration format. Markdown is for human inspection. All three are interchangeable — you can rebuild any from the others.

## Design Principles

1. **Proactive recall > passive search** — The system pushes relevant memories before you ask
2. **Claims, not documents** — Each memory is one atomic, actionable statement
3. **Write quality > write quantity** — Better to store 5 precise constraints than 50 vague notes
4. **Never auto-delete** — Only mark candidates for archival, never silently remove
5. **Origin separation** — Human judgment and AI compilation never mix in retrieval
6. **Token-efficient** — Retrieval cost is constant, not proportional to memory count
7. **SQLite is the runtime truth** — Markdown is a derived export, not the source

## Tech Stack

- Python 3.11+ / [uv](https://github.com/astral-sh/uv)
- SQLite + FTS5 (WAL mode) — zero external dependencies
- [MCP](https://modelcontextprotocol.io/) protocol via FastMCP
- 85 tests, ~1,010 lines of code

## Roadmap

| Version | Trigger | Features |
|---------|---------|----------|
| **v2** (current) | — | 5 kinds, 3 origins, proactive recall, health checks, memory cards, export |
| **v3** | FTS5 miss rate > 20% | Embedding search (sqlite-vec), compile() for knowledge synthesis |
| **v4** | Memory count > 3,000 | Co-activation matrix, automatic contradiction detection |
| **v5** | Multi-agent usage | Graph relations, shared memory scopes |

## Background

Engram's architecture was validated through structured multi-model debates:

- **Round 1**: Should this be a database or files? (Verdict: SQLite, with Markdown as export)
- **Round 2**: What makes this 10x better than MEMORY.md? (Verdict: proactive recall)
- **Round 3**: How to fuse Karpathy's knowledge compilation + Obsidian's metadata system + Engram's active recall? (Verdict: dual-layer storage with origin separation)

The name "engram" comes from neuroscience — a hypothetical means by which memory traces are stored in the brain.

## License

MIT
