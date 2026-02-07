#!/usr/bin/env bash
# block-cli.sh - Block CLI commands that have MCP tool equivalents.
#
# Works with ALL AI coding tools:
#   - Cursor    beforeShellExecution  (input: {"command": "..."})
#   - Claude    PreToolUse/Bash       (input: {"tool_input": {"command": "..."}})
#   - Gemini    BeforeTool            (input: {"tool_input": {"command": "..."}})
#   - Copilot   preToolUse            (input: {"toolArgs": "{\"command\":\"...\"}"})
#
# Reads the blocklist from config.json -> cli_to_mcp -> blocked_commands.
# Returns deny with MCP tool suggestion, or allow for non-blocked commands.
#
# Exit codes:
#   0 = allow (outputs JSON with permission/decision)
#   2 = deny  (outputs JSON with reason)

set -euo pipefail

# Read all stdin into a variable
INPUT=$(cat)

# Extract command - try each tool's format:
#   1. Cursor:  .command
#   2. Claude/Gemini: .tool_input.command
#   3. Copilot: .toolArgs (JSON string) -> parse -> .command
COMMAND=$(echo "$INPUT" | jq -r '
    .command //
    .tool_input.command //
    (if .toolArgs then (.toolArgs | fromjson | .command) else null end) //
    empty
' 2>/dev/null)

if [[ -z "${COMMAND:-}" ]]; then
    # No command found, allow
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Find config.json - look relative to script location, then env vars
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG=""

for candidate in \
    "$SCRIPT_DIR/../../config.json" \
    "${CURSOR_PROJECT_DIR:-}/config.json" \
    "${CLAUDE_PROJECT_DIR:-}/config.json" \
    "${GEMINI_PROJECT_DIR:-}/config.json"; do
    if [[ -f "$candidate" ]]; then
        CONFIG="$candidate"
        break
    fi
done

if [[ -z "$CONFIG" ]]; then
    # No config found, allow
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Check if cli_to_mcp is enabled
ENABLED=$(jq -r '.cli_to_mcp.enabled // false' "$CONFIG" 2>/dev/null)
if [[ "$ENABLED" != "true" ]]; then
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Extract the base command from the input
# Strip leading env var assignments (FOO=bar cmd ...), sudo, and path prefixes
CMD_STR="$COMMAND"

# Strip leading env var assignments
CMD_STR=$(echo "$CMD_STR" | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*=[^ ]+ +)*//')

# Strip sudo
CMD_STR=$(echo "$CMD_STR" | sed -E 's/^sudo +//')

# Get first word
BASE_CMD=$(echo "$CMD_STR" | awk '{print $1}')

# Strip path prefix (/usr/bin/curl -> curl)
BASE_CMD=$(basename "$BASE_CMD")

if [[ -z "$BASE_CMD" ]]; then
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Check if it's in the allowed list
IS_ALLOWED=$(jq -r --arg cmd "$BASE_CMD" \
    '.cli_to_mcp.allowed_commands // [] | map(select(. == $cmd)) | length' \
    "$CONFIG" 2>/dev/null)

if [[ "$IS_ALLOWED" -gt 0 ]]; then
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Check if it's in the blocked list
BLOCK_INFO=$(jq -r --arg cmd "$BASE_CMD" \
    '.cli_to_mcp.blocked_commands[$cmd] // empty' \
    "$CONFIG" 2>/dev/null)

if [[ -z "$BLOCK_INFO" ]]; then
    # Not in blocklist, allow
    echo '{"permission": "allow", "decision": "allow"}'
    exit 0
fi

# Extract MCP tool info
MODULE=$(echo "$BLOCK_INFO" | jq -r '.module // "unknown"')
TOOLS=$(echo "$BLOCK_INFO" | jq -r '.tools // [] | join(", ")')
PERSONA=$(echo "$BLOCK_INFO" | jq -r '.persona // "developer"')

# Build the denial message
REASON="BLOCKED: '$BASE_CMD' has MCP tool equivalents. Use them instead of raw CLI.

Module: $MODULE
Tools: $TOOLS
Load persona: persona_load(\"$PERSONA\")

MCP tools handle authentication, error recovery, and logging automatically.
Load the right persona first, then call the MCP tool directly."

# Output JSON that works for all tools:
# - Cursor:  reads permission, user_message, agent_message
# - Claude:  reads decision (or exit code 2 + stderr)
# - Gemini:  reads decision, reason
# - Copilot: reads exit code 2 + stderr/stdout
cat <<EOF
{
  "permission": "deny",
  "decision": "deny",
  "reason": $(echo "$REASON" | jq -Rs .),
  "user_message": "Blocked: $BASE_CMD (use MCP tool $TOOLS instead)",
  "agent_message": $(echo "$REASON" | jq -Rs .)
}
EOF

# Also write to stderr for tools that use stderr for block reasons (Gemini, Copilot)
echo "BLOCKED: '$BASE_CMD' - use MCP tool $TOOLS instead (persona: $PERSONA)" >&2

exit 2
