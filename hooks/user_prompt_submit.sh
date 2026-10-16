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
RAW_INPUT=$(cat 2>/dev/null)

if command -v jq >/dev/null 2>&1; then
    if ! PROMPT=$(printf '%s' "$RAW_INPUT" | jq -r '.prompt // empty' 2>/dev/null); then
        PROMPT="$RAW_INPUT"
    fi
elif command -v python3 >/dev/null 2>&1; then
    if ! PROMPT=$(printf '%s' "$RAW_INPUT" | python3 -c 'import json, sys; data = json.load(sys.stdin); print((data.get("prompt") or "") if isinstance(data, dict) else "")' 2>/dev/null); then
        PROMPT="$RAW_INPUT"
    fi
else
    PROMPT="$RAW_INPUT"
fi

if [ -z "$PROMPT" ]; then
    exit 0
fi

# Extract keywords (crude: take first few non-stopword words)
QUERY=$(echo "$PROMPT" | tr -d '"' | tr -s ' ' | cut -d' ' -f1-6)

if [ -z "$QUERY" ]; then
    exit 0
fi

cd "$ENGRAM_DIR"
# --no-log-miss: this is an automatic probe, so a zero-result query is not
# evidence of a retrieval gap and must not land in recall_miss_log.
RESULTS=$(uv run engram search "$QUERY" --limit 2 --no-log-miss 2>/dev/null || echo "")

if [ -n "$RESULTS" ] && [ "$RESULTS" != "No memories found." ]; then
    cat <<EOF
<engram_whisper>
$RESULTS
</engram_whisper>
EOF
fi
