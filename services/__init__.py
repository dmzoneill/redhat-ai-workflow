"""
AI Workflow Services

This package contains all daemon/service implementations for the AI Workflow system.
Each service runs as a systemd user service and communicates via D-Bus.

Services:
- cron: Scheduled job execution
- meet: Google Meet auto-join bot
- slack: Slack persona daemon
- sprint: Sprint automation bot
- video: Virtual camera video generator
- session: Cursor session state watcher
- config: Configuration cache service
- memory: Memory/state service
- stats: Statistics service
- extension_watcher: VS Code extension watcher
"""

__version__ = "1.0.0"
