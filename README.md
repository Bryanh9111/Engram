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

### Prerequisites

- [uv](https://github.com/astral-sh/uv) (Python package manager)
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- Python 3.11+ (uv will auto-install if needed)
- No Docker, no Postgres, no external services required

### Install

```bash
git clone https://github.com/Bryanh9111/Engram.git
cd Engram
uv sync --extra dev --extra mcp
```

That's it. The database (`~/.engram/engram.db`) is created automatically on first use.

### Connect to Claude Code

Add to `~/.claude/.mcp.json` (create the file if it doesn't exist):

```json
{
  "mcpServers": {
    "engram": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/Engram", "run", "engram-server"]
    }
  }
}
```

Replace `/absolute/path/to/Engram` with the actual path where you cloned the repo.

Restart Claude Code. Twelve tools become available in every project.

### Verify it works

```bash
# Add a test memory
engram add "This is a test" --kind fact

# Search for it
engram search "test"

# See the brain overview
engram dashboard

# Run health checks
engram health
```

### CLI Commands

```bash
engram add          # Remember something (--kind constraint/decision/procedure/fact/guardrail)
engram search       # Search memories (--project, --kind, --json, --limit)
engram forget       # Soft-delete a memory by ID
engram candidates   # List archive candidates
engram stats        # Quick statistics
engram dashboard    # Full brain status overview
engram health       # Health checks (missing evidence, orphans)
```

### MCP Tools (12)

Once connected, Claude Code can call these tools directly:

| Tool | Purpose |
|------|---------|
| `remember` | Store a memory (kind + origin) |
| `recall` | Search with budget control (`tiny`/`normal`/`deep`), ranked by effective_score |
| `proactive` | Get guardrails for a file path |
| `forget` | Soft-delete a memory (status → obsolete) |
| `resolve` | Mark as handled (status → resolved, stops proactive but stays searchable) |
| `suppress` | Temporarily silence a proactive memory |
| `compile` | Compile all memories for a project into structured Markdown (zero LLM) |
| `consolidate` | List archive candidates |
| `health` | Check for missing evidence, orphans, stale claims |
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
- **Stale claims**: (`check_stale=True`) Older memories superseded by newer similar ones

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
8. **Memories have metabolism** — Effective score decays with time, grows with access, pinned memories never fade
9. **Human-observable** — Dashboard and compile give full visibility into the memory brain

## Tech Stack

- Python 3.11+ / [uv](https://github.com/astral-sh/uv)
- SQLite + FTS5 (WAL mode) — zero external dependencies
- [MCP](https://modelcontextprotocol.io/) protocol via FastMCP
- 107 tests, ~1,250 lines of code

## Roadmap

| Phase | Trigger | Features |
|-------|---------|----------|
| **v2** | — | 5 kinds, 3 origins, proactive recall, health checks, memory cards, export |
| **v2.1** | — | Ops log, write templates, stale claims detection, L0-L3 budget |
| **v3** (current) | — | Resolved status, effective_score ranking, dashboard, compile, 12 MCP tools |
| **v4** | 500-1000 memories | LLM-powered compile (Auto-Dream style), merge threshold tuning, project-namespaced recall |
| **v5** | 1500-2000 memories | Embedding search (sqlite-vec), hybrid ranking (FTS5 + vector + score) |
| **v6** | 3000+ memories | Dream agent (Auto-Dream style periodic consolidation), co-activation matrix |

## Background

Engram's architecture was validated through five rounds of structured multi-model debates (Claude Opus, Sonnet, Gemini 2.5 Pro, GPT-5.4), drawing from:

- [Karpathy's LLM Knowledge Bases](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — compile/lint/index patterns
- [Anthropic's Harness Engineering](https://www.anthropic.com/engineering/harness-design-long-running-apps) — evaluator separation, structured handoffs
- [Claude Code Auto-Dream](https://github.com/anthropics/claude-code) — background memory consolidation (Orient→Gather→Consolidate→Prune)
- [Ombre Brain](https://github.com/P0lar1zzZ/Ombre-Brain) — Ebbinghaus decay, resolved status, weight pool
- [kepano (Obsidian founder)](https://x.com/kepano) — origin separation to prevent AI contamination of human judgment

The name "engram" comes from neuroscience — a hypothetical means by which memory traces are stored in the brain.

## License

MIT
