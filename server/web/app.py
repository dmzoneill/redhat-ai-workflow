"""Lightweight FastAPI web UI for the modular MCP server.

Unlike the old monolithic web app, this dynamically uses the registered
FastMCP tools instead of hardcoding everything.
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolRequest(BaseModel):
    """Request to execute a tool."""

    tool_name: str
    arguments: dict[str, Any] = {}


# Store recent activity
activity_log: list[dict] = []
MAX_ACTIVITY = 100


def log_activity(action: str, details: str, status: str = "success"):
    """Log an activity."""
    activity_log.insert(
        0,
        {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details[:100] if details else "",
            "status": status,
        },
    )
    if len(activity_log) > MAX_ACTIVITY:
        activity_log.pop()


def create_app(mcp_server: FastMCP) -> FastAPI:
    """Create FastAPI application using the configured MCP server."""

    app = FastAPI(
        title="AA Workflow MCP Server",
        description="Modular MCP Server Web Interface",
        version="2.0.0",
    )

    # Store server reference
    app.state.mcp_server = mcp_server

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Simple dashboard page."""
        # Get tool count from MCP server
        tools = await mcp_server.list_tools()
        tool_count = len(tools) if hasattr(tools, "__len__") else 0

        # Group tools by category (inferred from name prefix)
        categories = {}
        for tool in tools:
            name = tool.name if hasattr(tool, "name") else str(tool)
            prefix = name.split("_")[0] if "_" in name else "other"
            categories[prefix] = categories.get(prefix, 0) + 1

        categories_html = "\n".join(
            f"<li><strong>{cat}</strong>: {count} tools</li>" for cat, count in sorted(categories.items())
        )

        recent_activity = (
            "\n".join(
                f'<li class="{a["status"]}">[{a["timestamp"][:19]}] {a["action"]}: {a["details"]}</li>'
                for a in activity_log[:10]
            )
            or "<li>No recent activity</li>"
        )

        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>AA Workflow MCP Server</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 1200px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #00d4ff; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
        h2 {{ color: #7b68ee; }}
        .card {{ background: #16213e; border-radius: 8px; padding: 20px; margin: 20px 0;
                 border: 1px solid #0f3460; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }}
        .stat {{ background: #0f3460; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 2em; color: #00d4ff; }}
        .stat-label {{ color: #888; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ padding: 8px 0; border-bottom: 1px solid #0f3460; }}
        li.success {{ color: #4ade80; }}
        li.error {{ color: #f87171; }}
        a {{ color: #00d4ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        code {{ background: #0f3460; padding: 2px 6px; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>🚀 AA Workflow MCP Server</h1>

    <div class="stats">
        <div class="stat">
            <div class="stat-value">{tool_count}</div>
            <div class="stat-label">Total Tools</div>
        </div>
        <div class="stat">
            <div class="stat-value">{len(categories)}</div>
            <div class="stat-label">Categories</div>
        </div>
        <div class="stat">
            <div class="stat-value">{len(activity_log)}</div>
            <div class="stat-label">Activities Logged</div>
        </div>
    </div>

    <div class="card">
        <h2>📁 Tool Categories</h2>
        <ul>{categories_html}</ul>
    </div>

    <div class="card">
        <h2>📋 Recent Activity</h2>
        <ul>{recent_activity}</ul>
    </div>

    <div class="card">
        <h2>🔗 API Endpoints</h2>
        <ul>
            <li><a href="/api/tools">/api/tools</a> - List all tools with schemas</li>
            <li><a href="/api/health">/api/health</a> - Server health check</li>
            <li><code>POST /api/tools/execute</code> - Execute a tool</li>
            <li><a href="/docs">/docs</a> - OpenAPI documentation</li>
        </ul>
    </div>
</body>
</html>
"""

    @app.get("/api/health")
    async def health():
        """Health check endpoint."""
        tools = await mcp_server.list_tools()
        return {
            "status": "healthy",
            "tool_count": len(tools) if hasattr(tools, "__len__") else 0,
            "server_name": mcp_server.name,
        }

    @app.get("/api/tools")
    async def list_tools():
        """List all registered tools with their schemas."""
        tools = await mcp_server.list_tools()
        result = []
        for tool in tools:
            result.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": (tool.inputSchema if hasattr(tool, "inputSchema") else {}),
                }
            )
        return {"tools": result, "count": len(result)}

    @app.post("/api/tools/execute")
    async def execute_tool(request: ToolRequest):
        """Execute a tool via the MCP server."""
        log_activity(f"Execute: {request.tool_name}", json.dumps(request.arguments))

        try:
            # Use FastMCP's call_tool method
            result = await mcp_server.call_tool(request.tool_name, request.arguments)

            # Format result
            if hasattr(result, "content"):
                # MCP result format
                content = result.content
                if isinstance(content, list) and len(content) > 0:
                    text = content[0].text if hasattr(content[0], "text") else str(content[0])
                else:
                    text = str(content)
            else:
                text = str(result)

            log_activity(f"Result: {request.tool_name}", "Success", "success")
            return {"success": True, "result": text}

        except Exception as e:
            log_activity(f"Error: {request.tool_name}", str(e), "error")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/activity")
    async def get_activity(limit: int = 20):
        """Get recent activity."""
        return {"activity": activity_log[:limit]}

    @app.post("/api/sessions/sync")
    async def sync_sessions():
        """Sync sessions with Cursor's database and export workspace state.
        
        This endpoint:
        1. Syncs all workspaces with Cursor's database (add/remove/rename sessions)
        2. Exports the updated state to workspace_states.json
        3. Returns sync results
        """
        from server.workspace_state import WorkspaceRegistry
        from tool_modules.aa_workflow.src.workspace_exporter import export_workspace_state

        log_activity("Session Sync", "Syncing with Cursor DB")

        try:
            # Perform full sync with Cursor
            sync_result = WorkspaceRegistry.sync_all_with_cursor()
            
            # Export for UI
            export_result = export_workspace_state()

            total_changes = sum(sync_result.values())
            log_activity(
                "Session Sync",
                f"+{sync_result['added']} -{sync_result['removed']} ~{sync_result['renamed']}",
                "success"
            )

            return {
                "success": True,
                "sync": sync_result,
                "export": export_result,
                "total_changes": total_changes,
            }
        except Exception as e:
            log_activity("Session Sync", str(e), "error")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/sessions")
    async def list_sessions():
        """Get all sessions across all workspaces."""
        from server.workspace_state import WorkspaceRegistry

        sessions = WorkspaceRegistry.get_all_sessions()
        return {
            "sessions": sessions,
            "count": len(sessions),
            "workspace_count": len(WorkspaceRegistry._workspaces),
        }

    return app
