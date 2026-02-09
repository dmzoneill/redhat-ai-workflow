#!/usr/bin/env python3
# flake8: noqa: F401
"""
Sleep/Wake Detection for AI Workflow Daemons

DEPRECATED: This module is maintained for backward compatibility.
New code should import from services.base.sleep_wake instead.

Usage:
    # Old (still works):
    from scripts.common.sleep_wake import SleepWakeMonitor, SleepWakeAwareDaemon

    # New (preferred):
    from services.base import SleepWakeMonitor, SleepWakeAwareDaemon
"""

import sys
from pathlib import Path

# Add project root to path for services import
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Re-export everything from the new location for backward compatibility
from services.base.sleep_wake import (  # noqa: E402
    RobustPeriodicTask,
    RobustTimer,
    SleepWakeAwareDaemon,
    SleepWakeMonitor,
)

__all__ = [
    "SleepWakeMonitor",
    "SleepWakeAwareDaemon",
    "RobustTimer",
    "RobustPeriodicTask",
]
