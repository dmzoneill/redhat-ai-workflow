"""AA Slack MCP Server - Proactive Slack Integration.

This server provides event-based Slack monitoring with:
- Continuous background polling for new messages
- Proactive notifications when mentions/keywords are detected
- Tools for interacting with Slack (read/send messages)
- State persistence for restart survival
"""

from .tools import register_tools

__all__ = ["register_tools"]



