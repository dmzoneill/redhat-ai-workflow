"""Slack Persona Vector Search Module.

Provides tools for:
- Syncing Slack messages to vector database
- Searching past conversations for context
- Managing rolling time window
"""

from .tools_basic import register_tools

__all__ = ["register_tools"]
