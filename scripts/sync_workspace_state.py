#!/usr/bin/env python3
"""Unified Workspace State Sync Script.

Runs independently of MCP server to collect ALL UI data:
1. Sessions - Cursor DB sync, tool counts, issue keys, meeting refs
2. Services - D-Bus service status (Slack, Cron, Meet, MCP)
3. Ollama - HTTP status check for all instances
4. Cron - Config and execution history
5. Slack - Channel list (cached)
6. Sprint Issues - Jira API (cached)

All data is exported to workspace_states.json for the VS Code extension
to consume via file watcher.

Usage:
    python scripts/sync_workspace_state.py [--verbose]
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

PERSONAS_DIR = PROJECT_DIR / "personas"
TOOL_MODULES_DIR = PROJECT_DIR / "tool_modules"
CONFIG_FILE = PROJECT_DIR / "config.json"
CRON_HISTORY_FILE = Path.home() / ".config" / "aa-workflow" / "cron_history.json"

# Cache file for expensive operations
CACHE_FILE = Path.home() / ".mcp" / "workspace_states" / "sync_cache.json"

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Count Calculation
# =============================================================================

def count_tools_in_module(module_name: str) -> int:
    """Count @tool decorated functions in a tool module."""
    base_name = module_name.replace("_basic", "").replace("_extra", "")
    module_dir = TOOL_MODULES_DIR / f"aa_{base_name}" / "src"
    
    if not module_dir.exists():
        return 0
    
    if module_name.endswith("_basic"):
        files_to_check = ["tools_basic.py"]
    elif module_name.endswith("_extra"):
        files_to_check = ["tools_extra.py"]
    else:
        files_to_check = ["tools_basic.py", "tools.py"]
    
    for filename in files_to_check:
        tools_file = module_dir / filename
        if tools_file.exists():
            try:
                content = tools_file.read_text()
                matches = re.findall(r'@(?:server|registry|mcp)\.tool\s*\(', content)
                return len(matches)
            except Exception:
                pass
    return 0


def get_static_tool_counts() -> dict[str, int]:
    """Calculate static tool counts for all personas from YAML files."""
    import yaml
    
    counts = {}
    if not PERSONAS_DIR.exists():
        return counts
    
    for persona_file in PERSONAS_DIR.glob("*.yaml"):
        persona_name = persona_file.stem
        try:
            with open(persona_file) as f:
                config = yaml.safe_load(f) or {}
            
            tool_modules = config.get("tools", [])
            total = sum(count_tools_in_module(m) for m in tool_modules)
            counts[persona_name] = total
        except Exception as e:
            logger.warning(f"Error processing persona {persona_name}: {e}")
            counts[persona_name] = 0
    
    return counts


# =============================================================================
# Service Status Collection
# =============================================================================

DBUS_SERVICES = [
    {
        "name": "slack",
        "display": "Slack Agent",
        "service": "com.aiworkflow.SlackAgent",
        "path": "/com/aiworkflow/SlackAgent",
        "interface": "com.aiworkflow.SlackAgent",
        "unit": "slack-agent.service",
    },
    {
        "name": "cron",
        "display": "Cron Scheduler",
        "service": "com.aiworkflow.CronScheduler",
        "path": "/com/aiworkflow/CronScheduler",
        "interface": "com.aiworkflow.CronScheduler",
        "unit": "cron-scheduler.service",
    },
    {
        "name": "meet",
        "display": "Meet Bot",
        "service": "com.aiworkflow.MeetBot",
        "path": "/com/aiworkflow/MeetBot",
        "interface": "com.aiworkflow.MeetBot",
        "unit": "meet-bot.service",
    },
]


def query_dbus(service: str, path: str, interface: str, method: str) -> dict | None:
    """Query a D-Bus service method."""
    try:
        cmd = [
            "dbus-send",
            "--session",
            "--print-reply=literal",
            f"--dest={service}",
            path,
            f"{interface}.{method}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse D-Bus response - typically JSON string
            output = result.stdout.strip()
            if output:
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    return {"raw": output}
        return None
    except Exception as e:
        logger.debug(f"D-Bus query failed for {service}: {e}")
        return None


def check_systemd_service(unit: str) -> dict:
    """Check systemd user service status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True, timeout=5
        )
        is_active = result.stdout.strip() == "active"
        
        if is_active:
            # Get uptime
            result = subprocess.run(
                ["systemctl", "--user", "show", unit, "--property=ActiveEnterTimestamp"],
                capture_output=True, text=True, timeout=5
            )
            timestamp_str = result.stdout.strip().split("=")[-1]
            if timestamp_str:
                try:
                    # Parse systemd timestamp format
                    start_time = datetime.strptime(timestamp_str.split(".")[0], "%a %Y-%m-%d %H:%M:%S")
                    uptime_delta = datetime.now() - start_time
                    uptime = format_uptime(uptime_delta)
                except Exception:
                    uptime = "unknown"
            else:
                uptime = "unknown"
            return {"running": True, "uptime": uptime}
        return {"running": False}
    except Exception as e:
        logger.debug(f"systemctl check failed for {unit}: {e}")
        return {"running": False, "error": str(e)}


def format_uptime(delta: timedelta) -> str:
    """Format timedelta as human-readable uptime."""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        return f"{total_seconds // 60}m"
    elif total_seconds < 86400:
        hours = total_seconds / 3600
        return f"{hours:.1f}h"
    else:
        days = total_seconds / 86400
        return f"{days:.1f}d"


def collect_service_status() -> dict:
    """Collect status for all background services."""
    services = {}
    
    for svc in DBUS_SERVICES:
        # First check systemd status
        systemd_status = check_systemd_service(svc["unit"])
        
        # If running, try to get detailed status via D-Bus
        if systemd_status.get("running"):
            dbus_status = query_dbus(
                svc["service"], svc["path"], svc["interface"], "GetStatus"
            )
            if dbus_status:
                services[svc["name"]] = {
                    "running": True,
                    "uptime": systemd_status.get("uptime", "unknown"),
                    **dbus_status,
                }
            else:
                services[svc["name"]] = systemd_status
        else:
            services[svc["name"]] = systemd_status
    
    # Check MCP server (special case - not a systemd service)
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*-m server"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        if pids:
            services["mcp"] = {"running": True, "pid": int(pids[0])}
        else:
            services["mcp"] = {"running": False}
    except Exception:
        services["mcp"] = {"running": False}
    
    return services


# =============================================================================
# Ollama Status Collection
# =============================================================================

OLLAMA_INSTANCES = [
    {"name": "npu", "port": 11434, "model": "qwen2.5:0.5b", "power": "2-5W"},
    {"name": "igpu", "port": 11435, "model": "llama3.2:3b", "power": "8-15W"},
    {"name": "nvidia", "port": 11436, "model": "llama3:7b", "power": "40-60W"},
    {"name": "cpu", "port": 11437, "model": "qwen2.5:0.5b", "power": "15-35W"},
]


def check_ollama_instance(port: int, timeout: float = 2.0) -> bool:
    """Check if Ollama instance is available on given port."""
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/api/tags",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def collect_ollama_status() -> dict:
    """Collect status for all Ollama instances."""
    ollama = {}
    
    for inst in OLLAMA_INSTANCES:
        available = check_ollama_instance(inst["port"])
        ollama[inst["name"]] = {
            "available": available,
            "port": inst["port"],
            "model": inst["model"],
            "power": inst["power"],
        }
    
    return ollama


# =============================================================================
# Cron Data Collection
# =============================================================================

def collect_cron_data(history_limit: int = 10) -> dict:
    """Collect cron configuration and execution history."""
    cron_data = {
        "enabled": False,
        "timezone": "UTC",
        "execution_mode": "claude_cli",
        "jobs": [],
        "history": [],
        "total_history": 0,
    }
    
    # Load config
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                config = json.load(f)
            schedules = config.get("schedules", {})
            cron_data["enabled"] = schedules.get("enabled", False)
            cron_data["timezone"] = schedules.get("timezone", "UTC")
            cron_data["execution_mode"] = schedules.get("execution_mode", "claude_cli")
            cron_data["jobs"] = schedules.get("jobs", [])
    except Exception as e:
        logger.warning(f"Failed to load cron config: {e}")
    
    # Load history
    try:
        if CRON_HISTORY_FILE.exists():
            with open(CRON_HISTORY_FILE) as f:
                history = json.load(f)
            executions = history.get("executions", [])
            cron_data["total_history"] = len(executions)
            # Get last N executions, newest first
            cron_data["history"] = executions[-history_limit:][::-1]
    except Exception as e:
        logger.warning(f"Failed to load cron history: {e}")
    
    return cron_data


# =============================================================================
# Slack Channels Collection (Cached)
# =============================================================================

def collect_slack_channels(cache: dict) -> tuple[list, bool]:
    """Collect Slack channels via D-Bus (with 60s cache).
    
    Returns:
        Tuple of (channels list, whether cache was used)
    """
    cache_key = "slack_channels"
    cache_ttl = 60  # seconds
    
    # Check cache
    if cache_key in cache:
        cached = cache[cache_key]
        cached_at = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
        if datetime.now() - cached_at < timedelta(seconds=cache_ttl):
            return cached.get("data", []), True
    
    # Query D-Bus
    result = query_dbus(
        "com.aiworkflow.SlackAgent",
        "/com/aiworkflow/SlackAgent",
        "com.aiworkflow.SlackAgent",
        "GetChannels"
    )
    
    channels = []
    if result:
        if isinstance(result, list):
            channels = result
        elif isinstance(result, dict) and "channels" in result:
            channels = result["channels"]
    
    # Update cache
    cache[cache_key] = {
        "timestamp": datetime.now().isoformat(),
        "data": channels,
    }
    
    return channels, False


# =============================================================================
# Sprint Issues Collection (Cached)
# =============================================================================

def collect_sprint_issues(cache: dict) -> tuple[list, str, bool]:
    """Collect sprint issues from Jira (with 5-min cache).
    
    Returns:
        Tuple of (issues list, last_updated timestamp, whether cache was used)
    """
    cache_key = "sprint_issues"
    cache_ttl = 300  # 5 minutes
    
    # Check cache
    if cache_key in cache:
        cached = cache[cache_key]
        cached_at = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
        if datetime.now() - cached_at < timedelta(seconds=cache_ttl):
            return cached.get("data", []), cached.get("timestamp", ""), True
    
    # Try to fetch from Jira via MCP tool
    # This is expensive, so we use subprocess to call the tool
    issues = []
    try:
        # Use the jira_sprint_issues tool via direct Python call
        result = subprocess.run(
            [
                sys.executable, "-c",
                """
import sys
sys.path.insert(0, '.')
from server.utils import load_config
config = load_config()
jira_config = config.get('jira', {})
user = jira_config.get('user', '')
if user:
    import json
    # Simple JQL for assigned issues in current sprint
    jql = f'assignee = "{user}" AND sprint in openSprints() ORDER BY priority DESC'
    print(json.dumps({"jql": jql, "user": user}))
else:
    print('{}')
"""
            ],
            capture_output=True, text=True, timeout=10, cwd=str(PROJECT_DIR)
        )
        # For now, just return empty - full Jira integration would need API calls
        # The extension can still call Jira API directly if needed
        issues = []
    except Exception as e:
        logger.debug(f"Failed to fetch sprint issues: {e}")
    
    timestamp = datetime.now().isoformat()
    
    # Update cache
    cache[cache_key] = {
        "timestamp": timestamp,
        "data": issues,
    }
    
    return issues, timestamp, False


# =============================================================================
# Cache Management
# =============================================================================

def load_cache() -> dict:
    """Load sync cache from disk."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_cache(cache: dict) -> None:
    """Save sync cache to disk."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


# =============================================================================
# Main Sync Function
# =============================================================================

def sync_and_export(verbose: bool = False) -> dict:
    """Full sync: collect all data and export to workspace_states.json.
    
    Args:
        verbose: If True, print detailed progress
        
    Returns:
        Dict with sync results
    """
    from server.workspace_state import WorkspaceRegistry
    from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state_with_data
    
    results = {
        "static_counts": {},
        "sync_result": {"added": 0, "removed": 0, "renamed": 0, "updated": 0},
        "sessions_updated": 0,
        "services": {},
        "ollama": {},
        "cron": {},
        "slack_channels": [],
        "sprint_issues": [],
        "export_success": False,
    }
    
    # Load cache for expensive operations
    cache = load_cache()
    
    # Step 1: Calculate static tool counts
    if verbose:
        print("Calculating static tool counts...")
    static_counts = get_static_tool_counts()
    results["static_counts"] = static_counts
    
    # Step 2: Load workspace state and sync with Cursor DB
    if verbose:
        print("Syncing with Cursor database...")
    WorkspaceRegistry.load_from_disk()
    
    # Update static_tool_count for all sessions
    sessions_updated = 0
    for workspace in WorkspaceRegistry._workspaces.values():
        for session in workspace.sessions.values():
            persona = session.persona or "developer"
            new_count = static_counts.get(persona, 0)
            if session.static_tool_count != new_count:
                session.static_tool_count = new_count
                sessions_updated += 1
    results["sessions_updated"] = sessions_updated
    
    sync_result = WorkspaceRegistry.sync_all_with_cursor()
    results["sync_result"] = sync_result
    
    # Step 3: Collect service status
    if verbose:
        print("Collecting service status...")
    results["services"] = collect_service_status()
    
    # Step 4: Collect Ollama status
    if verbose:
        print("Collecting Ollama status...")
    results["ollama"] = collect_ollama_status()
    
    # Step 5: Collect cron data
    if verbose:
        print("Collecting cron data...")
    results["cron"] = collect_cron_data()
    
    # Step 6: Collect Slack channels (cached)
    if verbose:
        print("Collecting Slack channels...")
    channels, from_cache = collect_slack_channels(cache)
    results["slack_channels"] = channels
    if verbose and from_cache:
        print("  (from cache)")
    
    # Step 7: Collect sprint issues (cached)
    if verbose:
        print("Collecting sprint issues...")
    issues, issues_updated, from_cache = collect_sprint_issues(cache)
    results["sprint_issues"] = issues
    results["sprint_issues_updated"] = issues_updated
    if verbose and from_cache:
        print("  (from cache)")
    
    # Save cache
    save_cache(cache)
    
    # Step 8: Export everything to workspace_states.json
    if verbose:
        print("Exporting workspace state...")
    
    export_result = export_workspace_state_with_data(
        services=results["services"],
        ollama=results["ollama"],
        cron=results["cron"],
        slack_channels=results["slack_channels"],
        sprint_issues=results["sprint_issues"],
        sprint_issues_updated=results.get("sprint_issues_updated", ""),
    )
    results["export_success"] = export_result.get("success", False)
    
    if verbose:
        if results["export_success"]:
            print(f"  Exported to {export_result.get('file', 'unknown')}")
        else:
            print(f"  Export failed: {export_result.get('error', 'unknown')}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Unified workspace state sync - collects all UI data"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed progress"
    )
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Only calculate and print static tool counts (no sync)"
    )
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s"
    )
    
    if args.counts_only:
        counts = get_static_tool_counts()
        print("Static tool counts by persona:")
        for persona, count in sorted(counts.items()):
            print(f"  {persona}: {count}")
        return 0
    
    # Full sync
    try:
        results = sync_and_export(verbose=args.verbose)
        
        if args.verbose:
            print("\nSync complete!")
            print(f"  Services: {len(results['services'])} checked")
            print(f"  Ollama: {sum(1 for o in results['ollama'].values() if o.get('available'))} online")
            print(f"  Cron jobs: {len(results['cron'].get('jobs', []))}")
            print(f"  Slack channels: {len(results['slack_channels'])}")
        else:
            sync = results["sync_result"]
            print(f"Sync: +{sync['added']} -{sync['removed']} ~{sync['renamed']} | "
                  f"Services: {sum(1 for s in results['services'].values() if s.get('running'))}/4 | "
                  f"Ollama: {sum(1 for o in results['ollama'].values() if o.get('available'))}/4")
        
        return 0 if results["export_success"] else 1
        
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
