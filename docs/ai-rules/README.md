# AI Rules - Single Source of Truth

This directory contains the shared AI rules that are synced to:
- `.cursorrules` - Cursor IDE
- `CLAUDE.md` - Claude Code
- `AGENTS.md` - Cross-tool standard

## Structure

Files are numbered for ordering:

| File | Purpose |
|------|---------|
| `00-identity.md` | Who the AI is, what it does |
| `10-skill-first.md` | **CRITICAL**: Use skills before manual steps |
| `15-session-lifecycle.md` | Opening/closing session, what to log, session_close |
| `16-tool-discovery.md` | Discovering tools, skill_list, persona_load |
| `20-session-management.md` | Session ID, bootstrap, project detection, personas |
| `25-memory-operations.md` | Reading/writing memory, session log, learned, state |
| `30-git-safety.md` | Git safety rules |
| `40-ephemeral.md` | Ephemeral deployment rules |
| `50-auto-debug.md` | Self-healing tools, check_known_issues, learn_tool_fix |
| `55-work-completion.md` | Update Jira after work (transitions, comments) |
| `60-use-mcp-tools.md` | Use MCP tools instead of blocked CLI commands |

## Syncing

Run `make sync-ai-rules` to sync these rules to all targets:

```bash
make sync-ai-rules        # Sync rules + commands
make sync-ai-rules-dry    # Preview without changes
```

This will:
1. Concatenate all rules into `.cursorrules`
2. Generate `CLAUDE.md` with `@import` statements
3. Generate `AGENTS.md` for cross-tool compatibility
4. Sync slash commands (`.cursor/commands/` → `.claude/commands/`)

## Editing Rules

1. Edit files in this directory (`docs/ai-rules/`)
2. Run `make sync-ai-rules`
3. Commit all generated files

**Never edit `.cursorrules`, `CLAUDE.md`, or `AGENTS.md` directly!**
They are generated from this directory.
