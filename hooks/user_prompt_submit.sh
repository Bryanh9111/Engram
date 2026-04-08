#!/usr/bin/env bash
# Engram UserPromptSubmit hook (opt-in whisper mode)
# Before each user prompt, emit top 2 relevant memories as compact cards.
# Install: add to ~/.claude/settings.json under hooks.UserPromptSubmit
#
# NOTE: This is whisper mode — adds ~150 tokens per prompt. Disable with ENGRAM_WHISPER=0.

set -e

# Opt-out via env var
if [ "${ENGRAM_WHISPER:-1}" = "0" ]; then
    exit 0
fi

ENGRAM_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    exit 0
fi

# Read user prompt from stdin (Claude Code passes hook input as JSON)
PROMPT=$(cat 2>/dev/null | head -c 500)

# Extract keywords (crude: take first few non-stopword words)
QUERY=$(echo "$PROMPT" | tr -d '"' | tr -s ' ' | cut -d' ' -f1-6)

if [ -z "$QUERY" ]; then
    exit 0
fi

cd "$ENGRAM_DIR"
RESULTS=$(uv run engram search "$QUERY" --limit 2 2>/dev/null || echo "")

if [ -n "$RESULTS" ] && [ "$RESULTS" != "No memories found." ]; then
    cat <<EOF
<engram_whisper>
$RESULTS
</engram_whisper>
EOF
fi
