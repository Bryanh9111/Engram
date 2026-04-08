#!/usr/bin/env bash
# Engram SessionStart hook
# Emits a compact brain overview (~200 tokens) at the start of each Claude Code session.
# Install: add to ~/.claude/settings.json under hooks.SessionStart
#
# {
#   "hooks": {
#     "SessionStart": [
#       {"hooks": [{"type": "command", "command": "/path/to/Engram/hooks/session_start.sh"}]}
#     ]
#   }
# }

set -e

# Resolve engram directory (parent of hooks/)
ENGRAM_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Silent if engram isn't installed
if ! command -v uv >/dev/null 2>&1; then
    exit 0
fi

# Get micro_index (compact ~200 token overview)
cd "$ENGRAM_DIR"
INDEX=$(uv run engram stats 2>/dev/null || echo "")

if [ -n "$INDEX" ]; then
    cat <<EOF
<engram_brain>
$INDEX
(use recall/proactive/compile via MCP to access memories)
</engram_brain>
EOF
fi
