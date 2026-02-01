"""
Base infrastructure for AI Workflow daemons.

This module provides common functionality used by all daemons:
- BaseDaemon: Base class with CLI, signals, and lifecycle management
- SingleInstance: Lock file management for single-instance enforcement
- DaemonDBusBase: D-Bus interface base class
- SleepWakeAwareDaemon: Mixin for sleep/wake detection
"""

from services.base.daemon import BaseDaemon, SingleInstance
from services.base.dbus import (
    DBUS_AVAILABLE,
    DaemonClient,
    DaemonDBusBase,
    ServiceConfig,
    check_daemon_health,
    check_daemon_status,
    get_client,
)
from services.base.sleep_wake import RobustPeriodicTask, RobustTimer, SleepWakeAwareDaemon, SleepWakeMonitor

__all__ = [
    # daemon.py
    "BaseDaemon",
    "SingleInstance",
    # dbus.py
    "DBUS_AVAILABLE",
    "DaemonDBusBase",
    "DaemonClient",
    "ServiceConfig",
    "get_client",
    "check_daemon_status",
    "check_daemon_health",
    # sleep_wake.py
    "SleepWakeMonitor",
    "SleepWakeAwareDaemon",
    "RobustTimer",
    "RobustPeriodicTask",
]
