"""
Config, admin, and sync D-Bus handler logic for Slack daemon.

Extracted from dbus.py to reduce class size. Contains business logic
for configuration, health checks, persona tests, background sync,
and workspace admin operations.

All functions take the daemon as first argument and return JSON-serializable
dicts. The D-Bus @method() wrappers in dbus.py delegate here.
"""

import json
import logging
import time
from pathlib import Path

from services.slack.dbus_formatters import (
    format_command_list,
    format_persona_test_error,
    format_persona_test_result,
    format_slack_config,
)

logger = logging.getLogger(__name__)


# ==================== Config / Admin ====================


def handle_reload_config(daemon) -> dict:
    """Reload configuration from config.json."""
    daemon.reload_config()
    return {"success": True, "message": "Config reloaded"}


def handle_shutdown(daemon) -> dict:
    """Gracefully shutdown the daemon."""
    daemon._event_loop.call_soon(daemon.request_shutdown)
    return {"success": True, "message": "Shutdown initiated"}


def handle_health_check(daemon) -> dict:
    """Perform a comprehensive health check."""
    try:
        return daemon.health_check_sync()
    except Exception as e:
        return {
            "healthy": False,
            "checks": {"health_check_execution": False},
            "message": f"Health check failed: {e}",
            "timestamp": time.time(),
        }


def handle_get_command_list() -> dict:
    """Get list of available @me commands with descriptions."""
    try:
        from scripts.common.command_registry import get_registry

        registry = get_registry()
        commands = registry.list_commands()

        return {"success": True, "commands": format_command_list(commands)}
    except Exception as e:
        logger.error(f"GetCommandList error: {e}")
        return {"success": False, "error": str(e), "commands": []}


def handle_get_config() -> dict:
    """Get current Slack daemon configuration."""
    try:
        from scripts.common.config_loader import load_config

        config = load_config()
        return {"success": True, "config": format_slack_config(config)}
    except Exception as e:
        logger.error(f"GetConfig error: {e}")
        return {"success": False, "error": str(e)}


def handle_set_debug_mode(daemon, enabled: bool) -> dict:
    """Enable or disable debug mode."""
    try:
        if daemon:
            daemon._debug_mode = enabled
            return {
                "success": True,
                "debug_mode": enabled,
                "message": f"Debug mode {'enabled' if enabled else 'disabled'}",
            }
        return {"success": False, "error": "Daemon not available"}
    except Exception as e:
        logger.error(f"SetDebugMode error: {e}")
        return {"success": False, "error": str(e)}


# ==================== Persona / Context Test ====================


def handle_run_persona_test(query: str) -> dict:
    """Run a context gathering test for the Slack persona."""
    try:
        import sys

        project_root = Path(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from scripts.context_injector import ContextInjector

        injector = ContextInjector(
            project="automation-analytics-backend",
            slack_limit=5,
            code_limit=5,
            jira_limit=3,
            memory_limit=3,
            inscope_limit=1,
        )

        context = injector.gather_context(
            query=query,
            include_slack=True,
            include_code=True,
            include_jira=True,
            include_memory=True,
            include_inscope=True,
        )

        return format_persona_test_result(query, context)
    except ImportError as e:
        logger.error(f"RunPersonaTest import error: {e}")
        return format_persona_test_error(query, f"Context injector not available: {e}")
    except Exception as e:
        logger.error(f"RunPersonaTest error: {e}")
        return format_persona_test_error(query, str(e))


# ==================== App Commands ====================


async def handle_get_app_commands(daemon, summarize: bool) -> dict:
    """Get all available slash commands and app actions in the workspace."""
    if not daemon.session:
        return {"success": False, "error": "Session not available"}

    try:
        result = await daemon.session.get_app_commands()

        if not result.get("ok"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }

        if summarize:
            summary = daemon.session.get_app_commands_summary(result)
            return {"success": True, **summary}
        else:
            return {
                "success": True,
                "app_actions": result.get("app_actions", []),
                "commands": result.get("commands", []),
            }
    except Exception as e:
        logger.error(f"GetAppCommands error: {e}")
        return {"success": False, "error": str(e)}


# ==================== Channel Sections ====================


async def handle_get_channel_sections(daemon, summarize: bool) -> dict:
    """Get the user's sidebar channel sections/folders."""
    if not daemon.session:
        return {"success": False, "error": "Session not available"}

    try:
        result = await daemon.session.get_channel_sections()

        if not result.get("ok"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }

        if summarize:
            summary = daemon.session.get_channel_sections_summary(result)
            return {"success": True, **summary}
        else:
            return {
                "success": True,
                "channel_sections": result.get("channel_sections", []),
                "last_updated": result.get("last_updated", 0),
            }
    except Exception as e:
        logger.error(f"GetChannelSections error: {e}")
        return {"success": False, "error": str(e)}


# ==================== Background Sync ====================


def handle_get_sync_status() -> dict:
    """Get the status of the background sync process."""
    try:
        from src.background_sync import get_background_sync

        sync = get_background_sync()
        if not sync:
            return {
                "success": False,
                "error": "Background sync not initialized",
                "is_running": False,
            }

        status = sync.get_status()
        return {"success": True, **status}
    except ImportError:
        return {
            "success": False,
            "error": "Background sync module not available",
            "is_running": False,
        }
    except Exception as e:
        logger.error(f"GetSyncStatus error: {e}")
        return {"success": False, "error": str(e)}


async def handle_start_sync(daemon) -> dict:
    """Start the background sync process."""
    try:
        from src.background_sync import (
            BackgroundSync,
            SyncConfig,
            get_background_sync,
            set_background_sync,
        )

        existing = get_background_sync()
        if existing and existing.stats.is_running:
            return {
                "success": False,
                "error": "Background sync already running",
                "status": existing.get_status(),
            }

        if not daemon.session or not daemon.state_db:
            return {
                "success": False,
                "error": "Slack session or database not available",
            }

        config = SyncConfig(
            min_delay_seconds=1.0,
            max_delay_seconds=3.0,
            delay_start_seconds=5.0,
        )
        sync = BackgroundSync(
            slack_client=daemon.session,
            state_db=daemon.state_db,
            config=config,
        )
        set_background_sync(sync)
        await sync.start()

        return {
            "success": True,
            "message": "Background sync started",
            "status": sync.get_status(),
        }
    except Exception as e:
        logger.error(f"StartSync error: {e}")
        return {"success": False, "error": str(e)}


async def handle_stop_sync() -> dict:
    """Stop the background sync process."""
    try:
        from src.background_sync import get_background_sync

        sync = get_background_sync()
        if not sync:
            return {
                "success": False,
                "error": "Background sync not initialized",
            }

        if not sync.stats.is_running:
            return {
                "success": False,
                "error": "Background sync not running",
            }

        await sync.stop()

        return {
            "success": True,
            "message": "Background sync stopped",
            "final_stats": sync.stats.to_dict(),
        }
    except Exception as e:
        logger.error(f"StopSync error: {e}")
        return {"success": False, "error": str(e)}


async def handle_trigger_sync(sync_type: str) -> dict:
    """Manually trigger a sync operation."""
    try:
        from src.background_sync import get_background_sync

        sync = get_background_sync()
        if not sync:
            return {
                "success": False,
                "error": "Background sync not initialized",
            }

        return await sync.trigger_sync(sync_type)
    except Exception as e:
        logger.error(f"TriggerSync error: {e}")
        return {"success": False, "error": str(e)}


def handle_get_sync_config() -> dict:
    """Get the background sync configuration."""
    try:
        from src.background_sync import get_background_sync

        sync = get_background_sync()
        if sync:
            return {"success": True, "config": sync.config.to_dict()}

        from src.background_sync import SyncConfig

        default_config = SyncConfig()
        return {
            "success": True,
            "config": default_config.to_dict(),
            "note": "Using default config (sync not started)",
        }
    except Exception as e:
        logger.error(f"GetSyncConfig error: {e}")
        return {"success": False, "error": str(e)}


def handle_set_sync_config(config_json: str) -> dict:
    """Update background sync configuration."""
    try:
        from src.background_sync import get_background_sync

        sync = get_background_sync()
        if not sync:
            return {
                "success": False,
                "error": "Background sync not initialized. Start sync first.",
            }

        updates = json.loads(config_json)

        if "min_delay_seconds" in updates:
            sync.config.min_delay_seconds = float(updates["min_delay_seconds"])
        if "max_delay_seconds" in updates:
            sync.config.max_delay_seconds = float(updates["max_delay_seconds"])
        if "download_photos" in updates:
            sync.config.download_photos = bool(updates["download_photos"])
        if "max_members_per_channel" in updates:
            sync.config.max_members_per_channel = int(
                updates["max_members_per_channel"]
            )

        return {"success": True, "config": sync.config.to_dict()}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}"}
    except Exception as e:
        logger.error(f"SetSyncConfig error: {e}")
        return {"success": False, "error": str(e)}
