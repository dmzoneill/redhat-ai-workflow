"""Centralized path definitions for all state files.

All application state is stored under ~/.config/aa-workflow/ following XDG conventions.
This module provides the single source of truth for all state file paths.

Usage:
    from server.paths import STATE_FILE, WORKSPACE_STATES_FILE, ...
"""

from pathlib import Path

# Base directory for all state
AA_CONFIG_DIR = Path.home() / ".config" / "aa-workflow"


def ensure_config_dir() -> None:
    """Create the config directory if it doesn't exist.

    Call this explicitly before writing to any state file under AA_CONFIG_DIR.
    Previously this ran on import, which caused side effects during import time.
    """
    AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Core State Files
# =============================================================================

# Runtime state (service toggles, job states, meeting overrides)
STATE_FILE = AA_CONFIG_DIR / "state.json"

# DEPRECATED: Unified workspace state file (replaced by per-service state files)
# Kept for backward compatibility during migration
WORKSPACE_STATES_FILE = AA_CONFIG_DIR / "workspace_states.json"

# Cache for expensive sync operations
SYNC_CACHE_FILE = AA_CONFIG_DIR / "sync_cache.json"

# =============================================================================
# Per-Service State Files (NEW - each service owns its own file)
# =============================================================================
# Each daemon writes to its own state file. The VS Code extension reads all
# files on refresh and merges them for display. This prevents race conditions.

# Session daemon state (Cursor sessions, workspaces)
SESSION_STATE_FILE = AA_CONFIG_DIR / "session_state.json"

# Sprint daemon state (sprint issues, approval status, bot mode)
SPRINT_STATE_FILE_V2 = AA_CONFIG_DIR / "sprint_state_v2.json"

# Meet daemon state (upcoming meetings, current meeting, calendars)
MEET_STATE_FILE = AA_CONFIG_DIR / "meet_state.json"

# Cron daemon state (job schedules, execution history)
CRON_STATE_FILE = AA_CONFIG_DIR / "cron_state.json"

# Services status (ollama, slack, general service health)
SERVICES_STATE_FILE = AA_CONFIG_DIR / "services_state.json"

# =============================================================================
# Database Files
# =============================================================================

# Meet bot SQLite database (transcripts, notes, meetings)
MEETINGS_DB_FILE = AA_CONFIG_DIR / "meetings.db"

# Slack state SQLite database (message state, user/channel cache)
SLACK_STATE_DB_FILE = AA_CONFIG_DIR / "slack_state.db"

# =============================================================================
# Sprint Bot State
# =============================================================================

SPRINT_HISTORY_FILE = (
    AA_CONFIG_DIR / "sprint_history.json"
)  # Still used for historical data

# =============================================================================
# Scheduler/Cron State
# =============================================================================

CRON_HISTORY_FILE = AA_CONFIG_DIR / "cron_history.json"

# =============================================================================
# Agent/Skill State
# =============================================================================

SKILL_EXECUTION_FILE = AA_CONFIG_DIR / "skill_execution.json"
AGENT_STATS_FILE = AA_CONFIG_DIR / "agent_stats.json"
NOTIFICATIONS_FILE = AA_CONFIG_DIR / "notifications.json"

# =============================================================================
# Performance Data
# =============================================================================

# Base directory for quarterly performance data
# Structure: PERFORMANCE_DIR/YYYY/qN/performance/daily/...
PERFORMANCE_DIR = AA_CONFIG_DIR / "performance"

# =============================================================================
# IPC
# =============================================================================

# Unix socket for meet bot attendee service
MEETBOT_SOCKET = AA_CONFIG_DIR / "meetbot.sock"
MEETBOT_SOCKET_DIR = AA_CONFIG_DIR  # For compatibility

# =============================================================================
# Meet Bot Data Directories
# =============================================================================

# Base directory for meet bot assets
MEETBOT_DATA_DIR = AA_CONFIG_DIR / "meet_bot"

# Audio output directory for generated TTS audio
MEETBOT_AUDIO_DIR = MEETBOT_DATA_DIR / "audio"

# Pre-generated video clips directory
MEETBOT_CLIPS_DIR = MEETBOT_DATA_DIR / "clips"

# Named pipes for zero-copy TTS audio transfer
MEETBOT_PIPES_DIR = MEETBOT_DATA_DIR / "pipes"

# AI model files (wav2lip, etc.)
MEETBOT_MODELS_DIR = MEETBOT_DATA_DIR / "models"

# Meeting screenshots
MEETBOT_SCREENSHOTS_DIR = MEETBOT_DATA_DIR / "screenshots"

# Meet bot logs
MEETBOT_LOGS_DIR = MEETBOT_DATA_DIR / "logs"

# Meeting recordings
MEETBOT_RECORDINGS_DIR = MEETBOT_DATA_DIR / "recordings"

# Meet bot state file
MEETBOT_STATE_FILE = MEETBOT_DATA_DIR / "state.json"


def get_performance_quarter_dir(year: int, quarter: int) -> Path:
    """Get the performance data directory for a specific quarter.

    Args:
        year: Year (e.g., 2026)
        quarter: Quarter number (1-4)

    Returns:
        Path to the quarter's performance directory
    """
    perf_dir = PERFORMANCE_DIR / str(year) / f"q{quarter}" / "performance"
    perf_dir.mkdir(parents=True, exist_ok=True)
    return perf_dir
