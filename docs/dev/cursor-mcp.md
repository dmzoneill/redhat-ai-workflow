# Cursor MCP Configuration

Lessons from chat transcripts (see [lessons-learned-from-chat-transcripts](../lessons-learned-from-chat-transcripts.md)).

## MCP config location

**Cursor uses `.cursor/mcp.json` for project MCP config**, not the repo-root `.mcp.json`. When you change the MCP server command or args, update **`.cursor/mcp.json`** so Cursor picks it up. Editing only repo-root `.mcp.json` will do nothing no matter how many times you restart — keep them in sync if you maintain both (e.g. copy `aa_workflow` from `.cursor/mcp.json` into `.mcp.json` for documentation).

## Server startup

To avoid startup timeouts:

- Use **`.venv/bin/python -m server`** (or your venv path) as the MCP server command so Cursor does not run `uv sync` on every connect.
- Run `uv sync` once from the project root when dependencies change.

Keep the command in `.cursor/mcp.json` in sync with this so the MCP server starts reliably.
