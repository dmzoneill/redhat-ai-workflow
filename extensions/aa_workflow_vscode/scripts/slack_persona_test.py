#!/usr/bin/env python3
"""
Slack Persona Test Script

Tests the Slack persona's context gathering capabilities using the ContextInjector.
Shows what sources would be used to answer a question, including:
- Slack vector search (past conversations)
- Code vector search (codebase knowledge)
- Jira context (if issue keys detected)
- Memory (current work, learned patterns)

Usage:
    python3 slack_persona_test.py --query "How does billing work?" [--project-root "/path/to/project"]
"""

import argparse
import json
import sys
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test Slack persona context gathering")
    parser.add_argument("--query", default="", help="The question to test")
    parser.add_argument("--project-root", default="", help="Project root directory")
    parser.add_argument("--limit", type=int, default=5, help="Max results per source")
    parser.add_argument("--include-jira", action="store_true", default=True, help="Include Jira context")
    parser.add_argument("--include-code", action="store_true", default=True, help="Include code search")
    parser.add_argument("--include-memory", action="store_true", default=True, help="Include memory context")
    parser.add_argument("--include-inscope", action="store_true", default=True, help="Include InScope AI context")
    parser.add_argument("--status-only", action="store_true", help="Only return status, don't run context gathering")
    return parser.parse_args()


def get_persona_status(project_root: Path) -> dict:
    """Get Slack persona sync status."""
    try:
        from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

        sync = SlackPersonaSync()
        status = sync.get_status()

        metadata = status.get("metadata", {})
        stats = status.get("vector_stats", {})

        return {
            "synced": bool(metadata),
            "total_messages": metadata.get("total_messages", 0),
            "last_sync": metadata.get("last_full_sync", "Never"),
            "db_size_mb": stats.get("db_size_mb", 0),
            "conversations": metadata.get("conversations", 0),
        }

    except Exception as e:
        return {
            "synced": False,
            "error": str(e),
        }


def get_code_search_status(project: str) -> dict:
    """Get code search index status."""
    try:
        from tool_modules.aa_code_search.src.tools_basic import _get_index_stats

        stats = _get_index_stats(project)
        return {
            "indexed": stats.get("indexed", False),
            "chunks": stats.get("chunks_count", 0),
            "files": stats.get("files_total", 0),
            "index_age": stats.get("index_age", "Unknown"),
            "is_stale": stats.get("is_stale", False),
        }

    except Exception:
        return {
            "indexed": False,
            "error": "Code search module not available",
        }


def get_inscope_status() -> dict:
    """Get InScope AI assistant status."""
    try:
        import asyncio
        from tool_modules.aa_inscope.src.tools_basic import _get_auth_token, KNOWN_ASSISTANTS
        
        # Check authentication
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            token = loop.run_until_complete(_get_auth_token())
        finally:
            loop.close()
        
        return {
            "available": token is not None,
            "authenticated": token is not None,
            "assistants": len(KNOWN_ASSISTANTS),
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
        }


def run_persona_test(query: str, project_root: Path, limit: int = 5,
                     include_jira: bool = True, include_code: bool = True,
                     include_memory: bool = True, include_inscope: bool = True) -> dict:
    """Run the full persona test using ContextInjector."""
    
    # Detect project from config
    project = "automation-analytics-backend"  # Default
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            repos = list(config.get("repositories", {}).keys())
            if repos:
                project = repos[0]
    except Exception:
        pass

    # Use the ContextInjector for gathering context
    try:
        from scripts.context_injector import ContextInjector
        
        injector = ContextInjector(
            project=project,
            slack_limit=limit,
            code_limit=limit,
            jira_limit=3,
            memory_limit=3,
            inscope_limit=1,
        )
        
        context = injector.gather_context(
            query=query,
            include_slack=True,
            include_code=include_code,
            include_jira=include_jira,
            include_memory=include_memory,
            include_inscope=include_inscope,
        )
        
        # Convert ContextSource objects to dicts for JSON serialization
        sources = []
        for src in context.sources:
            sources.append({
                "source": src.source,
                "found": src.found,
                "count": src.count,
                "results": src.results,
                "error": src.error,
                "latency_ms": round(src.latency_ms, 1),
            })
        
        # Get status info
        persona_status = get_persona_status(project_root)
        code_status = get_code_search_status(project)
        inscope_status = get_inscope_status()
        
        return {
            "query": context.query,
            "elapsed_ms": round(context.total_latency_ms, 1),
            "sources": sources,
            "sources_used": [s["source"] for s in sources if s.get("found")],
            "total_results": context.total_results,
            "status": {
                "slack_persona": persona_status,
                "code_search": code_status,
                "inscope": inscope_status,
            },
            "project": project,
            "formatted": context.formatted,  # Include the formatted context for display
        }
        
    except ImportError as e:
        # Fallback if ContextInjector not available
        return {
            "query": query,
            "error": f"ContextInjector not available: {e}",
            "sources": [],
            "sources_used": [],
            "total_results": 0,
            "status": {
                "slack_persona": get_persona_status(project_root),
                "code_search": get_code_search_status(project),
            },
            "project": project,
        }


def get_status_only(project_root: Path) -> dict:
    """Get just the status of all knowledge sources without running context gathering."""
    # Detect project from config
    project = "automation-analytics-backend"  # Default
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            repos = list(config.get("repositories", {}).keys())
            if repos:
                project = repos[0]
    except Exception:
        pass

    return {
        "query": "",
        "elapsed_ms": 0,
        "sources": [],
        "sources_used": [],
        "total_results": 0,
        "status": {
            "slack_persona": get_persona_status(project_root),
            "code_search": get_code_search_status(project),
            "inscope": get_inscope_status(),
        },
        "project": project,
        "status_only": True,
    }


def main():
    """Main entry point."""
    args = parse_args()

    # Determine project root
    if args.project_root:
        project_root = Path(args.project_root)
    else:
        project_root = Path.home() / "src" / "redhat-ai-workflow"

    # Add project root to path for proper module imports
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "tool_modules"))

    try:
        # If status-only mode, just return status without running context gathering
        if args.status_only:
            output = get_status_only(project_root)
        elif not args.query:
            # No query provided and not status-only mode
            print(json.dumps({
                "error": "Either --query or --status-only is required",
                "sources": [],
                "sources_used": [],
                "total_results": 0,
            }))
            return
        else:
            output = run_persona_test(
                query=args.query,
                project_root=project_root,
                limit=args.limit,
                include_jira=args.include_jira,
                include_code=args.include_code,
                include_memory=args.include_memory,
                include_inscope=args.include_inscope,
            )
        print(json.dumps(output))
    except Exception as e:
        import traceback

        print(json.dumps({
            "query": args.query if hasattr(args, 'query') else "",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "sources": [],
            "sources_used": [],
            "total_results": 0,
        }))


if __name__ == "__main__":
    main()
