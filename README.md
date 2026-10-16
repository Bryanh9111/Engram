# Engram — Persistent Memory System for AI Coding Agents

[![Quality](https://github.com/Bryanh9111/Engram/actions/workflows/quality.yml/badge.svg)](https://github.com/Bryanh9111/Engram/actions/workflows/quality.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-15_tools-purple)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Local First](https://img.shields.io/badge/local--first-SQLite-orange)](#)

**Zero-LLM, local-first memory server for Claude Code and MCP-compatible AI agents.** Engram gives your AI agent persistent, cross-project memory with proactive recall — so it remembers constraints, decisions, and hard-won lessons across sessions. Built on SQLite + FTS5 with an MCP server that exposes 15 tools. No embeddings, no cloud, no API keys required.

**Keywords:** MCP memory server, Claude Code memory, persistent AI agent memory, local LLM memory, proactive recall, SQLite agent memory, FTS5 knowledge base, MEMORY.md alternative

```
You open payments/reconcile.ts
  Engram automatically pushes:
  [constraint] "Money values must use integer cents end-to-end, never introduce floats"
  [guardrail]  "Never parallelize migration-0042 and migration-0043"

You didn't ask. It just knew.
```

## What is Engram

Engram is an open-source **Model Context Protocol (MCP) server** that acts as a persistent memory brain for AI coding agents like Claude Code. It stores structured memories (constraints, decisions, procedures, facts, guardrails) in a local SQLite database and surfaces them at the right moment — either on-demand via `recall()` or proactively when you open a matching file.

It exists because AI coding agents are smart but amnesic. Every new session starts from zero. The common fix — loading a `MEMORY.md` file into every prompt — wastes 3,000-5,000 tokens per session and grows linearly with your notes. Engram solves this with retrieval whose response size is set by `limit` and `budget`, not by how many memories you have: **~40 tokens for health checks, ~78 for cold-start index, ~432 for a typical search**, measured at 300 memories and unchanged in shape at 3,700 in daily use.

### When to use Engram

- You use Claude Code (or another MCP-compatible agent) daily across multiple projects
- You keep re-explaining the same constraints to your agent every session
- You want your agent to proactively warn you about incidents and gotchas before you repeat them
- You need persistent memory but don't want cloud dependencies, embeddings, or API costs
- You value explainable retrieval (no opaque vector rankings)

### When NOT to use Engram

- You only need memory within a single session (Claude Code's native context is enough)
- You need multimodal memory (images, audio) — Engram is text-only
- You want a chatbot-style conversational memory — try [Zep](https://github.com/getzep/zep) or [Mem0](https://github.com/mem0ai/mem0)
- You need a hosted/managed service — Engram is local-first by design
- You're building a personal assistant (not a coding agent) — the `proactive()` trigger is path-based, designed for code files

## How It Works

```
              AI Agent (Claude Code / Gemma / etc.)
                    |
            MCP Server (15 tools)
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

## Engram vs Other AI Memory Systems

How Engram compares to other memory solutions for AI agents:

| System | Storage | LLM calls | Local-first | Proactive | Best for |
|--------|---------|-----------|-------------|-----------|----------|
| **Engram** | SQLite + FTS5 | **Zero** | ✅ Yes | ✅ Path-based | AI coding agents |
| [Mem0](https://github.com/mem0ai/mem0) | Vector DB | Required | ⚠️ Optional | ❌ No | General LLM apps |
| [MemGPT / Letta](https://github.com/letta-ai/letta) | Postgres / SQLite | Required | ⚠️ Optional | ⚠️ Heartbeat | Conversational agents |
| [Zep](https://github.com/getzep/zep) | Graph + Vector | Required | ❌ Cloud-preferred | ❌ No | Chatbot long-term memory |
| [Supermemory](https://supermemory.ai/) | Hybrid (RAG + facts) | Required | ❌ Cloud | ❌ No | Personal knowledge base |
| [claude-subconscious](https://github.com/letta-ai/claude-subconscious) | Letta Cloud | Heavy | ❌ Cloud | ✅ Background agent | Claude Code users (hosted) |
| [Ombre Brain](https://github.com/P0lar1zzZ/Ombre-Brain) | Markdown + YAML | Optional | ✅ Yes | ⚠️ Weight pool | Personal emotional memory |
| MEMORY.md (flat file) | Text file | N/A | ✅ Yes | ❌ No | Small projects |

**Engram's differentiators:**

1. **Zero LLM calls for all core operations** — remember, recall, proactive, health, dashboard all run on pure SQL. No API keys, no token costs beyond the payload itself.
2. **Path-scoped proactive recall** — unique to Engram. Opens a file → pushes matching guardrails before you even ask. Inspired by Anthropic's Auto-Dream pattern but triggered synchronously, not via background agent.
3. **Origin separation** — every memory carries `human`, `agent`, or `compost` origin, and Compost-synthesized insights never enter proactive push, so AI output cannot feed back into the guardrails you get pushed. Ranking itself is origin-neutral: `effective_score` uses confidence, access, and recency, plus a fixed override for pinned memories; origin is never a ranking input.
4. **Bounded response size** — what `recall()` returns is capped by `limit` and `budget`, not by store size. Measured ~432 tokens for a typical recall at 300 memories; the same shape serves a 3,700-memory store in daily use.
5. **Fully explainable ranking** — `effective_score = confidence × access_boost × time_decay`. No vector similarities, no black-box rerankers.

## Architecture

**Deep dive**: [`ARCHITECTURE.md`](./ARCHITECTURE.md) — hard constraints (HC-1/HC-2), memory model, trust boundary, API surface discipline, Compost bidirectional channel contract, CI-enforced invariants, and roadmap.

Designed through multiple rounds of multi-model AI debate (Claude Opus, Sonnet 4.6, Gemini 2.5 Pro, GPT-5.4) and validated against Karpathy's LLM Knowledge Base methodology, Anthropic's harness engineering, and the Obsidian founder's (kepano) origin-separation principle.

### Memory Model

Six kinds, grounded in real coding and collaboration scenarios:

| Kind | Lifetime | Example |
|------|----------|---------|
| `constraint` | Semi-permanent | "Money values must use integer cents end-to-end" |
| `decision` | Until revisited | "Use polling not websockets — customer proxies break upgrades" |
| `procedure` | Version-controlled | "Integration tests: seed Redis, then worker, then API" |
| `fact` | Short-lived | "UserSearchV2 is behind SEARCH_V2=1 flag" |
| `guardrail` | Incident-driven | "Never parallelize these two migrations — caused prod failure" |
| `insight` | Cross-project synthesis. `origin=compost` MUST use this kind (schema CHECK enforces single direction); `origin=human/agent` MAY also write `insight` (kind not exclusive to compost) | "Users in 3 projects complain about checkout latency > 2s" |

### Origin Separation

Inspired by [kepano](https://x.com/kepano) (Obsidian founder): AI-compiled knowledge must never contaminate human judgment.

| Origin | Trust | Proactive Push | Stream Exported |
|--------|-------|----------------|-----------------|
| `human` | Highest — user explicitly wrote this | Yes | Yes |
| `agent` | Medium — AI discovered during work | Yes | Yes |
| `compost` | Synthesized cross-project insight from [Compost](https://github.com/Bryanh9111) — carries `source_trace` provenance and `expires_at` TTL | **No** — only returned on explicit recall | **Excluded by default** (prevents feedback loop when Compost re-ingests its own output) |

### Token Budget (measured at 290 memories)

Retrieval cost is constant regardless of memory count. These numbers are **real measurements**, not estimates:

| Operation | Tokens | Scale behavior |
|-----------|--------|---------------|
| `micro_index()` (cold start) | **78** | Fixed |
| `stats()` | **41** | Fixed |
| `remember()` return | **97** | Fixed |
| `recall(budget=tiny, 5)` | **432** | Fixed |
| `recall(budget=normal, 5)` | **822** | Fixed |
| `recall(budget=deep, 5)` | **3,980** | Grows with result size |
| `proactive(file_path)` | **0-300** | Depends on matches |
| `health()` via MCP (summary mode) | **40** | Fixed |
| `compile(project)` Markdown | **~3,000** | Grows with project size |
| **Compare: MEMORY.md loaded every prompt** | **3,000-5,000** | **Grows linearly** |

A typical session uses ~1-2K tokens for all memory operations — well under 2% of a Claude Max 5-hour window.

At 10,000 memories, Engram still costs the same tokens per retrieval. MEMORY.md would be impossible at that scale.

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

Expected: `113 passed in 0.Xs`. All tests must pass before proceeding.

### Step 4: Connect to Claude Code (user-scoped MCP)

Use the `claude mcp add` command to register Engram as a **user-scoped** MCP server (available in every project on your machine):

```bash
claude mcp add -s user engram uv -- --directory /absolute/path/to/Engram run engram-server
```

**Replace `/absolute/path/to/Engram` with your actual absolute path** (from `pwd` in Step 2).

The `-s user` flag is **critical** — without it, the server is only available in the directory you ran the command from. With `-s user`, it works globally.

Verify it registered:

```bash
claude mcp list
```

You should see:

```
engram: uv --directory /your/path/to/Engram run engram-server - ✓ Connected
```

If you see `✗ Failed to connect`, the server crashed on startup — run `uv run engram-server` manually from the Engram directory to see the error.

**Note:** Do NOT manually create `~/.claude/.mcp.json` — that path is not read by Claude Code. The `claude mcp add -s user` command writes to the correct location (`~/.claude.json`).

### Step 5: Restart Claude Code

Fully quit and relaunch Claude Code. The Engram MCP server starts automatically on first connection. All 15 tools become available in every project.

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
uv run engram lint --summary              # Compact hygiene counts for triage
uv run engram backup                      # Verified SQLite backup
uv run engram gc --dry-run                # Preview expired Compost pointer GC
uv run engram maintenance --json          # Backup, retention, project repair, GC
uv run engram misses --days 30             # Classify recall misses before v5/v6
uv run engram forget <memory-id>          # Soft-delete
uv run engram stats                       # Quick stats
uv run engram candidates                  # Archive candidates
```

Project names are canonicalized with `strip().lower()` on both write and read
paths. For example, `--project Helios` and `--project helios` refer to the same
project.

### MCP (for Claude Code)

Claude Code calls these automatically via MCP when connected. You do not need to invoke them manually — just chat with Claude normally and it will `remember()` / `recall()` / `proactive()` as appropriate. The global CLAUDE.md instructions guide when to capture memories.

### Troubleshooting

- **`uv: command not found`** — Re-run Step 1 and add `~/.local/bin` to PATH
- **`No module named 'engram'`** — Run `uv sync --extra dev --extra mcp` again in the Engram directory
- **MCP tools not appearing in Claude Code** — Run `claude mcp list` to check engram is registered and shows `✓ Connected`. If missing, re-run Step 4 (with `-s user`!). If `✗ Failed`, run `uv run engram-server` manually from the Engram directory to see the error. Fully restart Claude Code after fixing.
- **Tests failing** — Run `uv sync --extra dev --extra mcp` to ensure all dev dependencies are installed
- **Database location** — Default is `~/.engram/engram.db`. Engram creates `~/.engram` as owner-only (`0700`) and the SQLite files as owner-readable/writable (`0600`). Override with `export ENGRAM_DB=/path/to/custom.db`
- **Backup and maintenance** — Run `engram backup` for an online SQLite backup under `~/.engram/backups/`. `engram maintenance` creates and verifies that backup first, keeps the newest 30 timestamped backups by default, repairs legacy absolute-path project keys, then collects active `origin=compost` pointers expired beyond the 30-day grace period. Human/agent and obsolete memories are never part of automatic GC. Restore by copying a verified backup back to `~/.engram/engram.db` while Engram clients are stopped.
- **Many `engram-server` processes** — Engram MCP is stdio-based, so each active client may own a server process. More than a few idle copies usually means old agent sessions were not reaped. Confirm the DB is healthy with `sqlite3 ~/.engram/engram.db "pragma quick_check; pragma integrity_check;"`, then terminate stale `uv --directory ... run engram-server` / `.venv/bin/engram-server` processes. Fresh MCP or CLI calls should reconnect normally.

### MCP Tools (14)

Once connected, Claude Code can call these tools directly:

| Tool | Purpose |
|------|---------|
| `remember` | Store a memory (kind + origin + optional source_trace/expires_at/scope) |
| `recall` | Search with budget control (`tiny`/`normal`/`deep`), ranked by effective_score |
| `proactive` | Get guardrails for a file path |
| `forget` | Soft-delete a memory (status → obsolete) |
| `resolve` | Mark as handled (status → resolved, stops proactive but stays searchable) |
| `unpin` | Remove a pinned memory's pin (single memory; prefer supersede via new memory) |
| `suppress` | Temporarily silence a proactive memory |
| `compile` | Compile all memories for a project into structured Markdown (zero LLM) |
| `consolidate` | List archive candidates |
| `health` | Check for missing evidence, orphans, stale claims |
| `micro_index` | Compact index for cold-start (~200 tokens) |
| `stats` | Memory statistics |
| `stream_for_compost` | Stream entries to [Compost](https://github.com/Bryanh9111) for cross-project synthesis (excludes `origin=compost` by default) |
| `invalidate_compost_fact` | Mark insights as obsolete when their upstream Compost fact changes (Compost → Engram channel) |

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
engram lint

# Compact machine-readable counts for routine triage
engram lint --summary --json

# Machine-readable full report for batch hygiene work
engram lint --json

# Show more or fewer sample rows per category in text mode
engram lint --limit 25

# Online verified SQLite backup
engram backup

# Daily-safe sequence: verified backup -> retention -> project repair -> Compost TTL GC
engram maintenance --retention 30 --gc-grace-days 30 --json

# Review retrieval evidence; "candidate" is not a confirmed semantic miss
engram misses --days 30 --json
```

On macOS, [`ops/dev.engram.maintenance.plist.example`](ops/dev.engram.maintenance.plist.example)
is a launchd template for daily maintenance at 04:30 local time. Replace the
three `__...__` placeholders, install it under `~/Library/LaunchAgents/`, then
bootstrap it with `launchctl bootstrap gui/$(id -u) <plist-path>`. The job logs
JSON results to `~/.engram/maintenance.log`.

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

## Frequently Asked Questions

### What is an MCP memory server?

An **MCP (Model Context Protocol) memory server** is a standardized way for AI agents like Claude Code to access persistent memory across sessions. MCP is Anthropic's open protocol for connecting LLMs to external tools and data sources. Engram implements an MCP server that exposes 15 memory operations (`remember`, `recall`, `proactive`, `forget`, `resolve`, `compile`, etc.) that any MCP-compatible AI agent can call.

### How is Engram different from MEMORY.md?

MEMORY.md is a flat text file loaded into every prompt. It wastes 3,000-5,000 tokens per session and grows linearly with your notes. Engram is a queryable database that returns only the memories relevant to your current task — typically 40-800 tokens. MEMORY.md grows with every note you add; an Engram retrieval returns at most `limit` memories, so its size is independent of how many you have stored.

### Does Engram need an OpenAI or Anthropic API key?

**No.** Engram is zero-LLM by design. All core operations (remember, recall, proactive, health) run on pure SQLite + FTS5. You only pay tokens when the agent *uses* the retrieved memories in its own reasoning, which is the same cost as any other tool call.

### Does Engram work with Claude Code?

Yes, Engram is built primarily for Claude Code via MCP. Installation takes about 3 minutes: install `uv`, clone the repo, run `uv sync`, then `claude mcp add -s user engram uv -- --directory /path/to/Engram run engram-server`. See the Setup section above for detailed steps.

### Does Engram work with other AI agents (ChatGPT, Cursor, local LLMs)?

Any agent that speaks MCP can use Engram. The MCP protocol is supported by Claude Code natively. For other tools like Cursor, ChatGPT, or local LLMs, you'd need an MCP client adapter — or use Engram's CLI (`engram search`, `engram add`) from your agent's shell execution.

### What is proactive recall?

Proactive recall is Engram's signature feature. When you open a file (e.g., `payments/reconcile.ts`), Engram automatically checks which of your stored memories have a matching `path_scope` glob pattern and surfaces relevant constraints or guardrails before you ask. This is the opposite of traditional memory systems that wait for explicit queries. Example: opening a migration file might auto-surface "Never parallelize migrations 0042 and 0043 — caused prod failure last month."

### Why no embeddings?

The database crossed 2,000 memories in August 2026, but count alone is not retrieval evidence. `engram misses --days 30` classified only three single-hit candidate FTS gaps on the 2026-08-10 baseline; memory-ID lookups and empty project namespaces were separated from real candidates. Engram therefore keeps explainable FTS5 while collecting reviewed miss evidence, and will add sqlite-vec + RRF only when the added index has a demonstrated job. This is a **principled defer**, not an oversight — see the roadmap below.

### How do I back up Engram's memory?

Run `engram backup` for a verified SQLite online backup, or `engram maintenance` for the daily backup-first maintenance sequence. Avoid manually copying only the live `.db` file while writers are active. Restore a verified backup while Engram clients are stopped. You can also export to JSONL (lossless) or Markdown (human-readable) with `engram export`.

### Is Engram production-ready?

Engram v3.4 has 311 tests passing and has been running in daily use across 37 projects since April 2026. The core design has been validated through 5 rounds of structured multi-model debate and stress-tested against 16 reference projects (Karpathy's LLM Wiki, Anthropic Auto-Dream, Mem0, MemGPT, Zep, Letta, Ombre Brain, CatchMe, SocratiCode, Supermemory, and more). v3.4 adds a bidirectional channel to [Compost](https://github.com/Bryanh9111) for cross-project synthesis. That said, it's a personal tool by a solo developer — use at your own risk in commercial settings.

### Can I use Engram for personal knowledge management (not coding)?

Engram's storage and retrieval layer is domain-agnostic, but the `proactive()` trigger is path-based, which only makes sense for code files. For personal knowledge, you'd want to fork Engram and replace the trigger mechanism with topic/time/context-based triggers. See the "When NOT to use Engram" section above.

## Tech Stack

- Python 3.11+ / [uv](https://github.com/astral-sh/uv)
- SQLite + FTS5 (WAL mode) — zero external dependencies
- [MCP](https://modelcontextprotocol.io/) protocol via FastMCP
- 311 tests, ~2,900 lines of code

## Roadmap

| Phase | Trigger | Features |
|-------|---------|----------|
| **v2** | — | 5 kinds, 3 origins, proactive recall, health checks, memory cards, export |
| **v2.1** | — | Ops log, write templates, stale claims detection, L0-L3 budget |
| **v3** | — | Resolved status, effective_score ranking, dashboard, compile, 12 MCP tools |
| **v3.1** | — | Memory lint (kind-TTL staleness), Claude Code hooks integration |
| **v3.2** | — | Real token measurements + health summary mode (99% token reduction) |
| **v3.3 Slice A** | — | Schema hardening + unpin API + scope tri-value enum |
| **v3.4 Slice B Phase 1** | — | Compost schema foundation (insight kind, source_trace, expires_at, compost_insight_sources) |
| **v3.4 Slice B Phase 2 P0** | — | API surface invariant test + MemoryOrigin enum realignment (HUMAN/AGENT/COMPOST) |
| **v3.4 Slice B Phase 2 S2** | — | Bidirectional Compost channel: `stream_for_compost` + `invalidate_compost_fact` + CLI `export-stream` |
| **v3.4 Slice B Phase 2 S3** (current) | dogfood-found duplicate writes | Compost insight structural idempotency (migration 003): partial UNIQUE INDEX on `(origin, root_insight_id, chunk_index)`; `_find_compost_duplicate` in `remember()` returns existing id (PUT semantics, no `_strengthen`) |
| **Phase 3** | expired Compost entries observed | Extended lint + ARCH shipped; verified-backup-first maintenance, project repair, and auditable 30-day Compost TTL GC shipped; recall/proactive tier policy remains data-triggered |
| **Phase 3 ops** | dogfood runtime hygiene | Documented stdio MCP process cleanup; next step is a small stale-process detector or operator script if process accumulation recurs across multiple sessions |
| **v4** | 500 memories | LLM-powered compile with Planner→Worker→Critic pattern (ToFu-inspired) |
| **v4.1** | time-sensitive memories >10% | Temporal expiry (degrade, not hide) |
| **v5** | >5 reviewed FTS5 misses | `engram misses` classifier shipped; 3 single-hit candidates on 2026-08-10, so multi-path recall + LLM reranking remains deferred |
| **v6** | 2000 memories + demonstrated retrieval need | Count crossed (~2,200 total on 2026-08-10), but embeddings + RRF remain deferred until miss evidence justifies the added operational surface |
| **v7** | 3000 memories | Memory graph (relationships) + Dream agent |

**Killed ideas** (not in roadmap): Debounced write queue (durability > commit savings), silent auto-delete of human/agent knowledge, blob memories, opaque ranking, background source rewriting. The narrow `origin=compost` TTL lifecycle is an explicit, audited integration contract rather than general memory deletion.

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

## Lifecycle safety and verification

`resolve(memory_id)` is an audited, atomic transition from active/suspect to
resolved. Repeated resolution is idempotent; missing or obsolete IDs fail.
Explicit resolution may include pinned memories: pin protects against forgetting,
while resolved memories remain searchable and stop proactive recall.

Compost streaming accepts `(since, after_id)` for lossless timestamp-tied pages.
`states_for_compost(memory_ids)` and `engram export-states --ids ...` expose
bounded lifecycle metadata (including missing/obsolete/expired) without contents.
The nine-field content stream remains compatible. See the sibling Compost
boundary document for eventual cache invalidation and independent operation.

```bash
uv sync --frozen --extra dev --extra mcp
uv run ruff check src tests
uv run mypy
uv run coverage erase
uv run coverage run -m pytest -q
uv run coverage combine
uv run coverage report
```

Coverage includes CLI subprocess execution and must reach 90%; CI enforces the
same gates. A non-editable `uv tool install` is a packaged snapshot: reinstall
after source changes, then reconnect existing MCP clients to load the new code.
Keep the MCP extra when you do, or `engram-server` from that install stops
importing:

```bash
uv tool install --reinstall --with "mcp[cli]>=1.0,<2" .
```

See [search indexes](docs/search-indexes.md) for multilingual recall, index health, atomic rebuild and reproducible lexical evaluation.
