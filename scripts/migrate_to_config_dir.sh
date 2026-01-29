#!/bin/bash
# migrate_to_config_dir.sh - Migrate state files to ~/.config/aa-workflow/
#
# This script migrates all scattered state files to the centralized location.
# Run this AFTER stopping all services and BEFORE restarting with updated code.
#
# Usage:
#   1. Stop all services:
#      systemctl --user stop bot-slack bot-cron bot-meet bot-sprint 2>/dev/null || true
#      pkill -f "python.*daemon" 2>/dev/null || true
#
#   2. Run this migration script:
#      ./scripts/migrate_to_config_dir.sh
#
#   3. Restart services after code update

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Target directory
TARGET_DIR="$HOME/.config/aa-workflow"
PERF_DIR="$TARGET_DIR/performance"

# Source locations
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_MCP_DIR="$HOME/.mcp/workspace_states"
OLD_MEET_DIR="$HOME/.local/share/meet_bot"
OLD_PERF_DIR="$HOME/src/redhat-quarterly-connection"

echo -e "${YELLOW}=== AA Workflow State Migration ===${NC}"
echo ""
echo "This script will migrate state files to: $TARGET_DIR"
echo ""

# Check if services are running
if pgrep -f "python.*daemon" > /dev/null 2>&1; then
    echo -e "${RED}WARNING: Python daemons are still running!${NC}"
    echo "Please stop all services first:"
    echo "  systemctl --user stop bot-slack bot-cron bot-meet bot-sprint"
    echo "  pkill -f 'python.*daemon'"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create target directories
echo -e "${GREEN}Creating target directories...${NC}"
mkdir -p "$TARGET_DIR"
mkdir -p "$PERF_DIR"

# Function to migrate a file
migrate_file() {
    local src="$1"
    local dst="$2"
    local name="$3"

    if [ -f "$src" ]; then
        if [ -f "$dst" ]; then
            echo -e "${YELLOW}  $name: Target exists, backing up to ${dst}.bak${NC}"
            cp "$dst" "${dst}.bak"
        fi
        echo -e "${GREEN}  $name: Moving $src -> $dst${NC}"
        mv "$src" "$dst"
    else
        echo -e "  $name: Source not found (skipping)"
    fi
}

# Function to migrate a directory
migrate_dir() {
    local src="$1"
    local dst="$2"
    local name="$3"

    if [ -d "$src" ] && [ "$(ls -A "$src" 2>/dev/null)" ]; then
        echo -e "${GREEN}  $name: Moving contents from $src -> $dst${NC}"
        cp -r "$src"/* "$dst"/ 2>/dev/null || true
        echo -e "${YELLOW}  $name: Source directory preserved at $src (remove manually if desired)${NC}"
    else
        echo -e "  $name: Source not found or empty (skipping)"
    fi
}

echo ""
echo -e "${GREEN}Migrating state files...${NC}"

# 1. state.json from project root
migrate_file "$PROJECT_ROOT/state.json" "$TARGET_DIR/state.json" "state.json"

# 2. workspace_states.json from ~/.mcp/workspace_states/
migrate_file "$OLD_MCP_DIR/workspace_states.json" "$TARGET_DIR/workspace_states.json" "workspace_states.json"

# 3. sync_cache.json from ~/.mcp/workspace_states/
migrate_file "$OLD_MCP_DIR/sync_cache.json" "$TARGET_DIR/sync_cache.json" "sync_cache.json"

# 4. meetings.db from ~/.local/share/meet_bot/
migrate_file "$OLD_MEET_DIR/meetings.db" "$TARGET_DIR/meetings.db" "meetings.db"

# 5. slack_state.db from project root
migrate_file "$PROJECT_ROOT/slack_state.db" "$TARGET_DIR/slack_state.db" "slack_state.db"

# 6. Performance data from ~/src/redhat-quarterly-connection/
migrate_dir "$OLD_PERF_DIR" "$PERF_DIR" "performance data"

echo ""
echo -e "${GREEN}Cleaning up empty directories...${NC}"

# Clean up old directories if empty
if [ -d "$OLD_MCP_DIR" ] && [ -z "$(ls -A "$OLD_MCP_DIR" 2>/dev/null)" ]; then
    echo "  Removing empty $OLD_MCP_DIR"
    rmdir "$OLD_MCP_DIR" 2>/dev/null || true
fi

if [ -d "$HOME/.mcp" ] && [ -z "$(ls -A "$HOME/.mcp" 2>/dev/null)" ]; then
    echo "  Removing empty $HOME/.mcp"
    rmdir "$HOME/.mcp" 2>/dev/null || true
fi

if [ -d "$OLD_MEET_DIR" ] && [ -z "$(ls -A "$OLD_MEET_DIR" 2>/dev/null)" ]; then
    echo "  Removing empty $OLD_MEET_DIR"
    rmdir "$OLD_MEET_DIR" 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}=== Migration Complete ===${NC}"
echo ""
echo "New state directory: $TARGET_DIR"
echo ""
echo "Contents:"
ls -la "$TARGET_DIR" 2>/dev/null || echo "  (empty)"
echo ""
echo "Next steps:"
echo "  1. Update the code (git pull or apply changes)"
echo "  2. Restart services:"
echo "     systemctl --user start bot-slack bot-cron bot-meet bot-sprint"
echo ""
echo "To verify:"
echo "  python -c \"from server.paths import *; print(f'Config dir: {AA_CONFIG_DIR}')\""
