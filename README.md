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
            MCP Server (12 tools)
                    |
     .------.-------.-------.-------.
     |      |       |       |       |
  recall  remember  proactive  lint   ...
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

## Setup (for AI Agents and Humans)

Follow these steps exactly. Agents on new machines can execute this end-to-end without ambiguity.

### Step 1: Install uv

If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env" 2>/dev/null || source "$HOME/.cargo/env" 2>/dev/null || true
```

Verify:

```bash
uv --version
```

Expected output: `uv 0.x.x`. If the command is not found, add `~/.local/bin` to your PATH.

### Step 2: Clone the repo

Choose a clone location. The path is your choice but must be **absolute** (not relative).

```bash
# Example: clone to home directory
git clone https://github.com/Bryanh9111/Engram.git ~/Engram
cd ~/Engram
```

Remember this path. You will need the **absolute path** in Step 4. Get it with:

```bash
pwd
# Example output: /Users/yourname/Engram
```

### Step 3: Install dependencies

```bash
uv sync --extra dev --extra mcp
```

This installs Python dependencies (SQLite, FastMCP, pytest). No Docker, no Postgres, no external services. First run takes 30-60 seconds.

Verify installation:

```bash
uv run pytest tests/ -q
```

Expected: `110 passed in 0.Xs`. All tests must pass before proceeding.

### Step 4: Connect to Claude Code (global MCP)

Create or edit `~/.claude/.mcp.json`. If the file does not exist, create it:

```bash
mkdir -p ~/.claude
touch ~/.claude/.mcp.json
```

Open the file and add the following JSON. **You must replace `/absolute/path/to/Engram` with the actual absolute path from Step 2 (the output of `pwd`)**:

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

If `~/.claude/.mcp.json` already has other MCP servers, merge the `engram` entry into the existing `mcpServers` object — do not overwrite the file.

### Step 5: Restart Claude Code

Fully quit and relaunch Claude Code. The Engram MCP server starts automatically on first connection. All 12 tools become available in every project.

### Step 6: Verify end-to-end

From any terminal (not necessarily inside the Engram directory):

```bash
# Add a test memory
cd ~/Engram  # or wherever you cloned
uv run engram add "First memory on this machine" --kind fact

# Search for it
uv run engram search "First memory"

# See the full brain overview
uv run engram dashboard

# Run full health check
uv run engram lint
```

If all four commands work, Engram is installed and connected. The database is created at `~/.engram/engram.db` automatically.

### Step 7 (optional): Install Claude Code hooks

For automatic memory injection at session start, see [`hooks/README.md`](hooks/README.md) for hook installation.

---

## Daily Usage

### CLI (for humans / scripts)

```bash
uv run engram add "..."   --kind constraint --project myproj --path-scope "src/*"
uv run engram search "auth bug" --project myproj --limit 5
uv run engram dashboard                  # Full brain overview
uv run engram lint                        # Health check
uv run engram forget <memory-id>          # Soft-delete
uv run engram stats                       # Quick stats
uv run engram candidates                  # Archive candidates
```

### MCP (for Claude Code)

Claude Code calls these automatically via MCP when connected. You do not need to invoke them manually — just chat with Claude normally and it will `remember()` / `recall()` / `proactive()` as appropriate. The global CLAUDE.md instructions guide when to capture memories.

### Troubleshooting

- **`uv: command not found`** — Re-run Step 1 and add `~/.local/bin` to PATH
- **`No module named 'engram'`** — Run `uv sync --extra dev --extra mcp` again in the Engram directory
- **MCP tools not appearing in Claude Code** — Check `~/.claude/.mcp.json` syntax is valid JSON, path is absolute, then fully restart Claude Code
- **Tests failing** — Run `uv sync --extra dev --extra mcp` to ensure all dev dependencies are installed
- **Database location** — Default is `~/.engram/engram.db`. Override with `export ENGRAM_DB=/path/to/custom.db`
- **Backup** — The database is a single SQLite file. Copy `~/.engram/engram.db` (plus `.db-wal` and `.db-shm` if present) to back up. Restore by copying back.

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
- 110 tests, ~1,450 lines of code

## Roadmap

| Phase | Trigger | Features |
|-------|---------|----------|
| **v2** | — | 5 kinds, 3 origins, proactive recall, health checks, memory cards, export |
| **v2.1** | — | Ops log, write templates, stale claims detection, L0-L3 budget |
| **v3** | — | Resolved status, effective_score ranking, dashboard, compile, 12 MCP tools |
| **v3.1** (current) | — | Memory lint (kind-TTL staleness), Claude Code hooks integration |
| **v4** | 500 memories | LLM-powered compile with Planner→Worker→Critic pattern (ToFu-inspired) |
| **v4.1** | time-sensitive memories >10% | Temporal expiry (degrade, not hide) |
| **v5** | FTS5 miss evidence | Multi-path recall + LLM reranking |
| **v6** | 2000 memories | Embedding (sqlite-vec) + RRF fusion |
| **v7** | 3000 memories | Memory graph (relationships) + Dream agent |

**Killed ideas** (not in roadmap): Debounced write queue (durability > commit savings), silent auto-delete, blob memories, opaque ranking, background source rewriting.

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
