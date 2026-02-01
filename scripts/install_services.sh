#!/bin/bash
# Install systemd user services for AI Workflow daemons

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "Installing AI Workflow systemd services..."
echo "Project root: $PROJECT_ROOT"
echo "Systemd user dir: $SYSTEMD_USER_DIR"
echo

# Ensure virtual environment exists and is up to date
echo "Setting up Python virtual environment with uv..."
cd "$PROJECT_ROOT"
if ! command -v uv &> /dev/null; then
    echo "❌ uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Create/sync venv with all dependencies
uv sync
echo "   ✅ Virtual environment ready at $PROJECT_ROOT/.venv"
echo

# Create systemd user directory if it doesn't exist
mkdir -p "$SYSTEMD_USER_DIR"

# Function to install a service
install_service() {
    local service_name=$1
    local source_file="$PROJECT_ROOT/systemd/${service_name}.service"
    local dest_file="$SYSTEMD_USER_DIR/${service_name}.service"

    if [ ! -f "$source_file" ]; then
        echo "⚠️  Service file not found: $source_file"
        return 1
    fi

    echo "Installing $service_name..."
    cp "$source_file" "$dest_file"
    echo "   ✅ Copied to $dest_file"
}

# Install services
install_service "bot-slack" || true
install_service "bot-cron" || true
install_service "bot-meet" || true
install_service "bot-sprint" || true
install_service "bot-session" || true
install_service "bot-video" || true
install_service "bot-memory" || true
install_service "bot-stats" || true
install_service "bot-config" || true
install_service "bot-slop" || true
install_service "extension-watcher" || true

# Reload systemd
echo
echo "Reloading systemd daemon..."
systemctl --user daemon-reload
echo "   ✅ Daemon reloaded"

echo
echo "Services installed! Available commands:"
echo
echo "  Start all core services:"
echo "    systemctl --user start bot-slack bot-cron bot-session"
echo
echo "  Start individual services:"
echo "    systemctl --user start bot-slack     # Slack message monitoring"
echo "    systemctl --user start bot-cron      # Scheduled jobs"
echo "    systemctl --user start bot-meet      # Google Meet auto-join"
echo "    systemctl --user start bot-sprint    # Jira issue processing"
echo "    systemctl --user start bot-session   # Cursor session sync"
echo "    systemctl --user start bot-video     # Virtual camera"
echo "    systemctl --user start bot-memory    # Memory service"
echo "    systemctl --user start bot-stats     # Statistics service"
echo "    systemctl --user start bot-config    # Config service"
echo "    systemctl --user start bot-slop      # Code quality monitor"
echo "    systemctl --user start extension-watcher  # VSCode extension"
echo
echo "  Enable auto-start on login:"
echo "    systemctl --user enable bot-slack bot-cron bot-session"
echo
echo "  Check status:"
echo "    systemctl --user status 'bot-*'"
echo
echo "  View logs:"
echo "    journalctl --user -u bot-slack -f"
echo
