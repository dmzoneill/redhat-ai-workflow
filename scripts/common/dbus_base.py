#!/usr/bin/env python3
# flake8: noqa: F821, F401
"""
Base D-Bus Interface for AI Workflow Daemons

DEPRECATED: This module is maintained for backward compatibility.
New code should import from services.base.dbus instead.

Usage:
    # Old (still works):
    from scripts.common.dbus_base import DaemonDBusBase, get_client

    # New (preferred):
    from services.base import DaemonDBusBase, get_client
"""

import sys
from pathlib import Path

# Add project root to path for services import
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Re-export everything from the new location for backward compatibility
from services.base.dbus import (
    DBUS_AVAILABLE,
    DaemonClient,
    DaemonDBusBase,
    ServiceConfig,
    check_daemon_health,
    check_daemon_status,
    create_daemon_interface,
    get_client,
)

__all__ = [
    "DBUS_AVAILABLE",
    "DaemonClient",
    "DaemonDBusBase",
    "ServiceConfig",
    "check_daemon_health",
    "check_daemon_status",
    "create_daemon_interface",
    "get_client",
]
