#!/usr/bin/env python3
"""Standalone workspace state sync script.

Runs independently of MCP server to:
1. Calculate static tool counts from persona YAML files
2. Sync sessions with Cursor DB
3. Scan meeting transcripts for issue keys
4. Export to workspace_states.json

This script can be run:
- Manually: python scripts/sync_workspace_state.py
- From VS Code extension background timer
- As a cron job

Usage:
    python scripts/sync_workspace_state.py [--verbose]
"""

import argparse
import logging
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

PERSONAS_DIR = PROJECT_DIR / "personas"
TOOL_MODULES_DIR = PROJECT_DIR / "tool_modules"

logger = logging.getLogger(__name__)


def count_tools_in_module(module_name: str) -> int:
    """Count @tool decorated functions in a tool module.
    
    Scans the tools_basic.py or tools.py file for @server.tool() or 
    @registry.tool() decorators.
    
    Args:
        module_name: Base module name (e.g., "git", "jira", "workflow")
        
    Returns:
        Number of tools found in the module
    """
    # Handle _basic and _extra suffixes
    base_name = module_name.replace("_basic", "").replace("_extra", "")
    module_dir = TOOL_MODULES_DIR / f"aa_{base_name}" / "src"
    
    if not module_dir.exists():
        logger.debug(f"Module directory not found: {module_dir}")
        return 0
    
    # Determine which file to scan based on suffix
    if module_name.endswith("_basic"):
        files_to_check = ["tools_basic.py"]
    elif module_name.endswith("_extra"):
        files_to_check = ["tools_extra.py"]
    else:
        # Base module: check tools_basic.py first, then tools.py
        files_to_check = ["tools_basic.py", "tools.py"]
    
    for filename in files_to_check:
        tools_file = module_dir / filename
        if tools_file.exists():
            try:
                content = tools_file.read_text()
                # Count @server.tool() or @registry.tool() decorators
                # Also count @mcp.tool() for older style
                matches = re.findall(
                    r'@(?:server|registry|mcp)\.tool\s*\(',
                    content
                )
                count = len(matches)
                if count > 0:
                    logger.debug(f"Found {count} tools in {tools_file}")
                return count
            except Exception as e:
                logger.warning(f"Error reading {tools_file}: {e}")
    
    return 0


def get_static_tool_counts() -> dict[str, int]:
    """Calculate static tool counts for all personas from YAML files.
    
    Reads each persona's YAML file, gets the list of tool modules,
    and counts the actual @tool decorated functions in each module.
    
    Returns:
        Dict mapping persona name to total tool count
    """
    import yaml
    
    counts = {}
    
    if not PERSONAS_DIR.exists():
        logger.warning(f"Personas directory not found: {PERSONAS_DIR}")
        return counts
    
    for persona_file in PERSONAS_DIR.glob("*.yaml"):
        persona_name = persona_file.stem
        try:
            with open(persona_file) as f:
                config = yaml.safe_load(f) or {}
            
            tool_modules = config.get("tools", [])
            total = 0
            module_counts = {}
            
            for module in tool_modules:
                count = count_tools_in_module(module)
                module_counts[module] = count
                total += count
            
            counts[persona_name] = total
            logger.debug(f"Persona '{persona_name}': {total} tools from {len(tool_modules)} modules")
            
        except Exception as e:
            logger.warning(f"Error processing persona {persona_name}: {e}")
            counts[persona_name] = 0
    
    return counts


def sync_and_export(verbose: bool = False) -> dict:
    """Full sync: static counts + Cursor DB + meeting transcripts + export.
    
    Args:
        verbose: If True, print detailed progress
        
    Returns:
        Dict with sync results
    """
    from server.workspace_state import WorkspaceRegistry
    from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state
    
    results = {
        "static_counts": {},
        "sync_result": {"added": 0, "removed": 0, "renamed": 0, "updated": 0},
        "sessions_updated": 0,
        "export_success": False,
    }
    
    # Step 1: Calculate static tool counts from persona YAML files
    if verbose:
        print("Calculating static tool counts from persona YAML files...")
    
    static_counts = get_static_tool_counts()
    results["static_counts"] = static_counts
    
    if verbose:
        for persona, count in static_counts.items():
            print(f"  {persona}: {count} tools")
    
    # Step 2: Load existing state from disk
    if verbose:
        print("Loading workspace state from disk...")
    
    WorkspaceRegistry.load_from_disk()
    
    # Step 3: Update static_tool_count for all sessions
    if verbose:
        print("Updating static tool counts for all sessions...")
    
    sessions_updated = 0
    for workspace in WorkspaceRegistry._workspaces.values():
        for session in workspace.sessions.values():
            persona = session.persona or "developer"
            new_count = static_counts.get(persona, 0)
            if session.static_tool_count != new_count:
                session.static_tool_count = new_count
                sessions_updated += 1
    
    results["sessions_updated"] = sessions_updated
    if verbose:
        print(f"  Updated {sessions_updated} session(s)")
    
    # Step 4: Sync with Cursor DB (names, last_activity, issue_keys, meetings)
    if verbose:
        print("Syncing with Cursor database...")
    
    sync_result = WorkspaceRegistry.sync_all_with_cursor()
    results["sync_result"] = sync_result
    
    if verbose:
        print(f"  Added: {sync_result['added']}, Removed: {sync_result['removed']}, "
              f"Renamed: {sync_result['renamed']}, Updated: {sync_result.get('updated', 0)}")
    
    # Step 5: Export to workspace_states.json
    if verbose:
        print("Exporting workspace state...")
    
    export_result = export_workspace_state()
    results["export_success"] = export_result.get("success", False)
    
    if verbose:
        if results["export_success"]:
            print(f"  Exported to {export_result.get('file', 'unknown')}")
        else:
            print(f"  Export failed: {export_result.get('error', 'unknown')}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Sync workspace state with Cursor DB and calculate tool counts"
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
        # Just print static counts
        counts = get_static_tool_counts()
        print("Static tool counts by persona:")
        for persona, count in sorted(counts.items()):
            print(f"  {persona}: {count}")
        return 0
    
    # Full sync
    try:
        results = sync_and_export(verbose=args.verbose)
        
        # Print summary
        if args.verbose:
            print("\nSync complete!")
        else:
            sync = results["sync_result"]
            print(f"Sync: +{sync['added']} -{sync['removed']} ~{sync['renamed']} "
                  f"↻{sync.get('updated', 0)} | "
                  f"Static counts updated: {results['sessions_updated']}")
        
        return 0 if results["export_success"] else 1
        
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
