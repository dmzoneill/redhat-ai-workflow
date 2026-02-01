"""
Slop Bot Service - Code Quality Monitor.

A systemd service with named parallel analysis loops that each focus on
one code smell at a time, iterating until done before moving to the next task.

Components:
- SlopDaemon: Main daemon with file watcher and D-Bus interface
- SlopOrchestrator: Manages parallel loop execution (max 3 concurrent)
- AnalysisLoop: Named loops (LEAKY, ZOMBIE, RACER, etc.)
- SlopDatabase: SQLite storage for findings
- ExternalTools: Wrappers for fast analysis tools

Usage:
    # Run as module
    python -m services.slop --dbus

    # Import components
    from services.slop import SlopDaemon, SlopOrchestrator
"""

from services.slop.daemon import SlopDaemon
from services.slop.database import SlopDatabase
from services.slop.external_tools import ExternalTools, Finding
from services.slop.loops import LOOP_CONFIGS, PRIORITY_ORDER, AnalysisLoop, LoopResult
from services.slop.orchestrator import SlopOrchestrator

__all__ = [
    "SlopDaemon",
    "SlopOrchestrator",
    "SlopDatabase",
    "AnalysisLoop",
    "ExternalTools",
    "Finding",
    "LoopResult",
    "LOOP_CONFIGS",
    "PRIORITY_ORDER",
]
