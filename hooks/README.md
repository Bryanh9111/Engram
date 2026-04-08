# Engram Claude Code Hooks

Optional hooks that integrate Engram with Claude Code's native hook system. Turns Engram from a passive MCP tool into active memory capture.

Inspired by [claude-subconscious](https://github.com/letta-ai/claude-subconscious) (Letta's background agent pattern), but keeps everything local and zero-LLM.

## What's here

| Hook | Purpose | Token cost |
|------|---------|------------|
| `session_start.sh` | Inject brain overview at session start | ~200 |
| `user_prompt_submit.sh` | Whisper top 2 relevant memories before each prompt (opt-in) | ~150 |

## Installation

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/Engram/hooks/session_start.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/Engram/hooks/user_prompt_submit.sh"
          }
        ]
      }
    ]
  }
}
```

Replace `/absolute/path/to/Engram` with your actual clone path.

## Disable whisper mode

Whisper mode injects ~150 tokens per prompt. If you prefer zero auto-inject:

```bash
export ENGRAM_WHISPER=0
```

Or just don't install `user_prompt_submit.sh`.

## Design philosophy

- **Graceful degradation**: Hooks silently exit if Engram isn't installed or if `uv` is missing
- **Zero LLM calls**: All hooks use `engram` CLI (SQL-only)
- **Opt-in everything**: No hook is installed by default. Users choose their level of automation
- **No background daemons**: Unlike claude-subconscious, no persistent agents or cloud services

## What's NOT a hook (by design)

- **Stop hook for auto-remember**: Considered but deferred. Auto-extraction from transcripts requires LLM judgment, which violates zero-token principle. Instead: rely on CLAUDE.md instructions for agent to call `remember()` explicitly when it discovers something worth storing.
- **PreToolUse hook**: Too noisy. Engram's `proactive()` MCP tool is called by the agent at meaningful moments, not before every tool use.
