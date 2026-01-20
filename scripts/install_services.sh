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
install_service "slack-agent" || true
install_service "cron-scheduler" || true
install_service "meet-bot" || true

# Reload systemd
echo
echo "Reloading systemd daemon..."
systemctl --user daemon-reload
echo "   ✅ Daemon reloaded"

echo
echo "Services installed! Available commands:"
echo
echo "  Slack Agent:"
echo "    systemctl --user start slack-agent"
echo "    systemctl --user status slack-agent"
echo "    systemctl --user enable slack-agent  # Auto-start on login"
echo
echo "  Cron Scheduler:"
echo "    systemctl --user start cron-scheduler"
echo "    systemctl --user status cron-scheduler"
echo "    systemctl --user enable cron-scheduler  # Auto-start on login"
echo
echo "  Meet Bot:"
echo "    systemctl --user start meet-bot"
echo "    systemctl --user status meet-bot"
echo "    systemctl --user enable meet-bot  # Auto-start on login"
echo
echo "View logs:"
echo "    journalctl --user -u slack-agent -f"
echo "    journalctl --user -u cron-scheduler -f"
echo "    journalctl --user -u meet-bot -f"
echo
