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
| `20-session-management.md` | Session tracking, personas |
| `30-git-safety.md` | Git safety rules |
| `40-ephemeral.md` | Ephemeral deployment rules |
| `50-auto-debug.md` | Self-healing tools |
| `60-project-context.md` | Project-specific context |

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
