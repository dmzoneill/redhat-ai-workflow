"""AA Git MCP module.

This module can be used in two ways:

1. As a standalone server:
   python -m aa_git.server

2. As a plugin loaded by aa-common:
   python -m aa_common.server --tools git
"""

from .tools import register_tools

__all__ = ["register_tools"]
